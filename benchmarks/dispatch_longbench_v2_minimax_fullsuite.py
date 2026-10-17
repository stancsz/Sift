"""Offline-first dispatcher for the frozen one-repeat LongBench v2 full-suite manifest.

The default invocation is prepare-only: it verifies the manifest, pinned source
files, all 503 dataset rows, and every reconstructed Full/Sift request. It does
not read credentials or access the network. Paid dispatch requires an explicit
``--dispatch`` flag and is constrained to OpenRouter's MiniMax provider with
fallback disabled. Ambiguous attempts are never retried automatically.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

import prepare_longbench_v2_minimax_fullsuite as preparer  # noqa: E402

from tokenizers import Tokenizer  # noqa: E402
from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import (  # noqa: E402
    HF_TEMPLATE_URL,
    HF_TOKENIZER_URL,
    MODEL_ID,
    render_minimax,
)
from sift import CompactionError, compact_messages  # noqa: E402


DATASET_DEFAULT = preparer.DATASET_DEFAULT
TOKENIZER_DEFAULT = preparer.TOKENIZER_DEFAULT
TEMPLATE_DEFAULT = preparer.TEMPLATE_DEFAULT
MANIFEST_DEFAULT = preparer.OUTPUT_DEFAULT
PREPARED_DEFAULT = ROOT / ".runs/longbench-v2-minimax-fullsuite-prepared.json"
DISPATCH_DEFAULT = ROOT / ".runs/longbench-v2-minimax-fullsuite-run.json"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = MODEL_ID
PROVIDER = "minimax"
EXPECTED_ROWS = preparer.EXPECTED_ROWS
EXPECTED_JOBS = EXPECTED_ROWS * 2
MAX_SPEND_CAP_USD = 2_000.0
INPUT_PRICE_USD_PER_MILLION = 0.30
OUTPUT_PRICE_USD_PER_MILLION = 1.20
INPUT_RESERVE_FACTOR = 1.5


class DispatchError(RuntimeError):
    """A validation or safety stop before or during dispatch."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace a JSON checkpoint; use a unique temp on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    value.pop("checkpoint_sha256", None)
    value["checkpoint_sha256"] = canonical_sha256(value)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        for attempt in range(8):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(0.1 * (2 ** attempt), 1.0))
    finally:
        if temp.exists():
            temp.unlink()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        decoded = gzip.decompress(raw) if path.suffix == ".gz" else raw
        manifest = json.loads(decoded)
    except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError) as error:
        raise DispatchError(f"Cannot read full-suite manifest: {type(error).__name__}: {error}") from error
    if not isinstance(manifest, dict):
        raise DispatchError("Manifest root must be a JSON object")
    stored_hash = manifest.get("manifest_sha256")
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    if stored_hash != canonical_sha256(unsigned):
        raise DispatchError("Manifest canonical SHA-256 does not match its contents")
    if (manifest.get("schema_version") != 1
            or manifest.get("status") != "prepared_only_no_dispatch"
            or manifest.get("dispatch_authorized") is not False
            or manifest.get("preparation_is_offline_only") is not True
            or manifest.get("network_calls") != 0
            or manifest.get("credential_access") is not False):
        raise DispatchError("Manifest is not the expected offline-only prepared schema")
    if manifest.get("scoring_keys_separate_from_request_bodies") is not True:
        raise DispatchError("Manifest does not assert scoring-key/request separation")
    return manifest


def validate_source_hashes(manifest: dict[str, Any], dataset: Path,
                           tokenizer: Path, template: Path) -> dict[str, str]:
    expected = manifest.get("source_hashes")
    if not isinstance(expected, dict):
        raise DispatchError("Manifest source_hashes must be an object")
    paths = {
        "dataset": dataset,
        "dataset_reader": ROOT / "benchmarks/prepare_longbench_v2.py",
        "renderer": ROOT / "benchmarks/prepare_longbench_v2_minimax.py",
        "sift_core": ROOT / "src/sift/core.py",
        "runner": ROOT / "benchmarks/prepare_longbench_v2_minimax_fullsuite.py",
        "tokenizer": tokenizer,
        "chat_template": template,
    }
    actual: dict[str, str] = {}
    for key, path in paths.items():
        if not path.is_file():
            raise DispatchError(f"Required source file is missing: {path}")
        actual[key] = file_sha256(path)
    if actual != expected:
        differing = sorted(key for key in set(actual) | set(expected)
                           if actual.get(key) != expected.get(key))
        raise DispatchError("Pinned source hash mismatch: " + ", ".join(differing))
    if actual["dataset"] != DATASET_SHA256 or manifest.get("dataset", {}).get("sha256") != DATASET_SHA256:
        raise DispatchError("Dataset is not the repository's pinned LongBench v2 revision")
    return actual


def validate_protocol(manifest: dict[str, Any]) -> dict[str, Any]:
    protocol = manifest.get("protocol")
    if not isinstance(protocol, dict):
        raise DispatchError("Manifest protocol must be an object")
    exact = {
        "arms": ["full", "sift"],
        "repeats_per_arm": 1,
        "planned_jobs": EXPECTED_JOBS,
        "temperature": 0.1,
        "top_p": 0.8,
        "reasoning": {"enabled": False},
        "stream": True,
        "stream_options": {"include_usage": True},
        "matched_seed_formula": "seed + dataset_index + 1; same seed for both arms of each question",
        "request_order": "pinned dataset row order; deterministic random arm order within each pair",
        "choice_scoring_rule": "exact uppercase A/B/C/D after trimming; scoring keys kept separately",
    }
    for key, wanted in exact.items():
        if protocol.get(key) != wanted:
            raise DispatchError(f"Manifest protocol mismatch for {key}")
    for key in ("seed", "max_output_tokens", "sift_configured_target_tokens",
                "sift_safety_margin_tokens", "sift_effective_target_tokens",
                "sift_raw_limit_tokens", "sift_max_input_characters", "sift_max_input_nodes"):
        if type(protocol.get(key)) is not int:
            raise DispatchError(f"Manifest protocol lacks integer {key}")
    if (protocol["max_output_tokens"] <= 0
            or protocol["sift_effective_target_tokens"] != (
                protocol["sift_configured_target_tokens"] - protocol["sift_safety_margin_tokens"])
            or protocol["sift_raw_limit_tokens"] < protocol["sift_effective_target_tokens"]):
        raise DispatchError("Manifest target, safety margin, raw limit, or output cap is invalid")
    model = manifest.get("model_and_tokenizer", {})
    if (model.get("model_id") != MODEL
            or model.get("tokenizer_source") != HF_TOKENIZER_URL
            or model.get("chat_template_source") != HF_TEMPLATE_URL):
        raise DispatchError("Manifest model/tokenizer route differs from the pinned MiniMax M3 protocol")
    dataset = manifest.get("dataset", {})
    if (dataset.get("id") != "zai-org/LongBench-v2"
            or dataset.get("revision") != DATASET_REVISION
            or dataset.get("split") != "train"
            or dataset.get("expected_rows") != EXPECTED_ROWS
            or dataset.get("observed_rows") != EXPECTED_ROWS):
        raise DispatchError("Manifest dataset identity/revision/row count is not the pinned 503-row split")
    route = manifest.get("provider_route_assumption", {})
    if (route.get("requested_model") != MODEL or route.get("provider_slug") != PROVIDER
            or route.get("fallbacks_allowed") is not False):
        raise DispatchError("Manifest route must pin MiniMax M3 to provider minimax without fallbacks")
    return protocol


def _request_body(messages: list[dict[str, str]], seed: int,
                  output_tokens: int) -> dict[str, Any]:
    return preparer._body(messages=messages, seed=seed, output_tokens=output_tokens)


def reconstruct(manifest: dict[str, Any], tokenizer_path: Path,
                dataset_path: Path) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    """Rebuild all 1,006 scheduled bodies and verify each against the manifest."""
    protocol = validate_protocol(manifest)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def count_messages(messages: list[dict[str, str]]) -> int:
        return len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)

    expected_cases = manifest.get("cases")
    expected_jobs = manifest.get("schedule")
    keys = manifest.get("scoring_keys")
    if (not isinstance(expected_cases, list) or len(expected_cases) != EXPECTED_ROWS
            or not isinstance(expected_jobs, list) or len(expected_jobs) != EXPECTED_JOBS
            or not isinstance(keys, dict) or len(keys) != EXPECTED_ROWS):
        raise DispatchError("Manifest must retain 503 case rows, 1,006 schedule rows, and separate keys")
    if manifest.get("schedule_sha256") != canonical_sha256(expected_jobs):
        raise DispatchError("Manifest schedule SHA-256 mismatch")
    expected_case_map = {case.get("case_id"): case for case in expected_cases
                         if isinstance(case, dict)}
    if len(expected_case_map) != EXPECTED_ROWS:
        raise DispatchError("Manifest case IDs are missing or duplicated")
    if set(keys) != set(expected_case_map) or any(v not in {"A", "B", "C", "D"} for v in keys.values()):
        raise DispatchError("Separate scoring keys do not cover exactly the 503 case IDs")

    # Iterate the pinned source once; no dataset download or network access occurs here.
    seen: set[str] = set()
    reconstructed_jobs: list[dict[str, Any]] = []
    actual_case_summaries: dict[str, Any] = {}
    for dataset_index, row in enumerate(iter_json_array(dataset_path)):
        case_id = row.get("_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise DispatchError(f"Dataset row {dataset_index} has a missing or duplicate ID")
        seen.add(case_id)
        case_meta = expected_case_map.get(case_id)
        if case_meta is None or row.get("answer") != keys.get(case_id):
            raise DispatchError(f"Dataset ID or separate answer key mismatch for {case_id}")
        messages = make_messages(row)
        full_tokens = count_messages(messages)
        full_prompt_hash = prompt_sha256(messages)
        seed = protocol["seed"] + dataset_index + 1
        full_body = _request_body(messages, seed, protocol["max_output_tokens"])
        full_status = preparer._route_status(
            full_tokens, manifest["provider_route_assumption"]["input_cap_tokens"])
        try:
            compacted = compact_messages(
                messages,
                count_messages,
                target=protocol["sift_effective_target_tokens"],
                raw_limit=protocol["sift_raw_limit_tokens"],
                max_input_characters=protocol["sift_max_input_characters"],
                max_input_nodes=protocol["sift_max_input_nodes"],
                protocol="openai",
            )
            sift_messages = compacted.messages
            sift_tokens = compacted.audit["forwarded_tokens"]
            sift_prompt_hash = prompt_sha256(sift_messages)
            sift_body = _request_body(sift_messages, seed, protocol["max_output_tokens"])
            sift_status = preparer._route_status(
                sift_tokens, manifest["provider_route_assumption"]["input_cap_tokens"])
            sift_audit = {
                key: compacted.audit.get(key)
                for key in ("compacted", "input_tokens", "forwarded_tokens",
                            "omitted_estimated_tokens", "preserved_recent_turns",
                            "preserved_recent_tool_cycles", "selected_excerpts", "method")
                if key in compacted.audit
            }
        except CompactionError as error:
            reason = error.code if error.code == "raw_limit" else "compaction_error"
            sift_tokens = full_tokens
            sift_prompt_hash = None
            sift_body = None
            sift_status = {"status": "ineligible", "reason": reason,
                           "error_code": error.code}
            sift_audit = None

        actual_case_summaries[case_id] = {
            "dataset_index": dataset_index,
            "full": {"prompt_sha256": full_prompt_hash,
                     "local_prompt_tokens": full_tokens, "eligibility": full_status},
            "sift": {"prompt_sha256": sift_prompt_hash,
                     "local_prompt_tokens": sift_tokens, "eligibility": sift_status,
                     "audit": sift_audit},
        }
        if case_meta.get("dataset_index") != dataset_index:
            raise DispatchError(f"Manifest dataset index differs for {case_id}")
        for arm, generated in (("full", actual_case_summaries[case_id]["full"]),
                               ("sift", actual_case_summaries[case_id]["sift"])):
            frozen = case_meta.get(arm)
            if not isinstance(frozen, dict):
                raise DispatchError(f"Manifest has no {arm} metadata for {case_id}")
            for field in ("prompt_sha256", "local_prompt_tokens", "eligibility"):
                if frozen.get(field) != generated.get(field):
                    raise DispatchError(f"Reconstructed {arm} {field} mismatch for {case_id}")

        for arm, body, p_hash, local_tokens, status, audit in (
            ("full", full_body, full_prompt_hash, full_tokens, full_status, None),
            ("sift", sift_body, sift_prompt_hash, sift_tokens, sift_status, sift_audit),
        ):
            schedule_index = len(reconstructed_jobs)
            frozen_job = expected_jobs[schedule_index]
            if (frozen_job.get("case_id") != case_id
                    or frozen_job.get("arm") not in {"full", "sift"}
                    or frozen_job.get("repeat") != 1):
                raise DispatchError(f"Schedule order or identity mismatch at {schedule_index}")
            # The manifest randomizes arm order per pair. Match by identity below;
            # append in frozen order after both candidate jobs are reconstructed.
            job_id = f"{case_id}:{arm}:1"
            reconstructed_jobs.append({
                "case_id": case_id, "arm": arm, "repeat": 1, "seed": seed,
                "job_id": job_id, "prompt_sha256": p_hash,
                "body": body, "body_sha256": canonical_sha256(body) if body is not None else None,
                "local_prompt_tokens": local_tokens, "eligibility": status,
                "sift_preprocessing_ms": None, "sift_audit": audit,
            })
    if len(seen) != EXPECTED_ROWS:
        raise DispatchError(f"Pinned dataset must have 503 rows; saw {len(seen)}")

    # Restore the exact deterministic pair order in the manifest and compare
    # every eligibility, request hash, seed, and schedule row.
    by_identity = {(job["case_id"], job["arm"], job["repeat"]): job
                   for job in reconstructed_jobs}
    if len(by_identity) != EXPECTED_JOBS:
        raise DispatchError("Reconstructed job identities are not unique")
    ordered: list[dict[str, Any]] = []
    for index, frozen in enumerate(expected_jobs):
        ident = (frozen.get("case_id"), frozen.get("arm"), frozen.get("repeat"))
        job = by_identity.get(ident)
        if job is None:
            raise DispatchError(f"Manifest schedule contains unknown job identity at {index}")
        if frozen.get("seed") != job["seed"]:
            raise DispatchError(f"Matched seed mismatch for {job['job_id']}")
        expected_eligibility = frozen.get("eligibility")
        if expected_eligibility != job["eligibility"]:
            raise DispatchError(f"Eligibility mismatch for {job['job_id']}")
        if expected_eligibility.get("status") == "eligible_by_local_token_estimate":
            if (job["body"] is None or frozen.get("prompt_sha256") != job["prompt_sha256"]
                    or frozen.get("body_sha256") != job["body_sha256"]
                    or frozen.get("local_prompt_tokens") != job["local_prompt_tokens"]):
                raise DispatchError(f"Eligible request hash/token mismatch for {job['job_id']}")
        else:
            # The preparer hashes Full-context bodies even when the local
            # provider-cap estimate makes them ineligible. Keep those hashes
            # auditable, but never include the jobs in the eligible dispatch set.
            if frozen.get("body_sha256") is None:
                if job["body"] is not None:
                    raise DispatchError(f"Unexpected body for ineligible job: {job['job_id']}")
            elif (job["body"] is None
                  or frozen.get("body_sha256") != job["body_sha256"]
                  or frozen.get("prompt_sha256") != job["prompt_sha256"]
                  or frozen.get("local_prompt_tokens") != job["local_prompt_tokens"]):
                raise DispatchError(f"Ineligible request hash/token mismatch for {job['job_id']}")
        job["index"] = index
        ordered.append(job)
    # Validate each adjacent pair has the one matched seed and expected IDs;
    # ineligible jobs remain represented in this full ordered schedule.
    if canonical_sha256([
        {key: job[key] for key in ("case_id", "arm", "repeat", "seed",
                                   "prompt_sha256", "body_sha256",
                                   "local_prompt_tokens", "eligibility")}
        for job in ordered
    ]) != manifest["schedule_sha256"]:
        raise DispatchError("Reconstructed schedule SHA-256 differs from the manifest")
    eligible = [job for job in ordered
                if job["eligibility"].get("status") == "eligible_by_local_token_estimate"]
    return ordered, keys, {"eligible_jobs": eligible,
                           "eligible_count": len(eligible),
                           "manifest_sha256": manifest["manifest_sha256"],
                           "schedule_sha256": manifest["schedule_sha256"],
                           "source_hashes": manifest["source_hashes"],
                           "protocol": protocol}


def build_report(manifest: dict[str, Any], manifest_path: Path,
                 ordered_jobs: list[dict[str, Any]], validated: dict[str, Any],
                 cap: float | None = None) -> dict[str, Any]:
    eligible = validated["eligible_jobs"]
    counts = Counter(job["eligibility"].get("status") for job in ordered_jobs)
    total_local = sum(job["local_prompt_tokens"] for job in eligible)
    protocol = validated["protocol"]
    max_output = len(eligible) * protocol["max_output_tokens"]
    estimate = (total_local * INPUT_RESERVE_FACTOR * INPUT_PRICE_USD_PER_MILLION
                + max_output * OUTPUT_PRICE_USD_PER_MILLION) / 1_000_000
    return {
        "schema_version": 1,
        "status": "prepared_only_no_dispatch",
        "actual_dispatch_started": False,
        "evidence_class": manifest["evidence_class"],
        "manifest_path": manifest_path.resolve().relative_to(ROOT).as_posix(),
        "manifest_sha256": validated["manifest_sha256"],
        "schedule_sha256": validated["schedule_sha256"],
        "source_hashes": validated["source_hashes"],
        "provider": PROVIDER,
        "requested_model": MODEL,
        "fallbacks_allowed": False,
        "full_schedule_rows": len(ordered_jobs),
        "dataset_rows": EXPECTED_ROWS,
        "eligible_jobs": len(eligible),
        "eligible_counts_by_arm": {
            arm: sum(job["arm"] == arm for job in eligible) for arm in ("full", "sift")
        },
        "schedule_eligibility_counts": dict(counts),
        "ineligible_job_ids": [job["job_id"] for job in ordered_jobs
                               if job not in eligible],
        "spend_cap_usd": cap,
        "budget_reserve": {
            "method": "local prompt token estimate × 1.5 × dated planning rate plus output cap",
            "input_tokens": total_local,
            "max_output_tokens": max_output,
            "input_usd_per_million": INPUT_PRICE_USD_PER_MILLION,
            "output_usd_per_million": OUTPUT_PRICE_USD_PER_MILLION,
            "estimated_usd": estimate,
            "is_live_quote": False,
        },
        "schedule": [{
            "index": job["index"], "job_id": job["job_id"], "case_id": job["case_id"],
            "arm": job["arm"], "repeat": job["repeat"], "seed": job["seed"],
            "prompt_sha256": job["prompt_sha256"], "body_sha256": job["body_sha256"],
            "local_prompt_tokens": job["local_prompt_tokens"],
            "eligibility": job["eligibility"],
        } for job in ordered_jobs],
        "request_bodies_and_answer_keys_excluded": True,
    }


def reported_token_totals(samples: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = completion = receipts = unknown = invalid = 0
    for sample in samples:
        usage = sample.get("usage")
        if not isinstance(usage, dict):
            if sample.get("outcome_class") != "provider_context_limit_rejected_before_generation":
                unknown += 1
            continue
        p, c = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if type(p) is int and type(c) is int and p >= 0 and c >= 0:
            prompt += p
            completion += c
            receipts += 1
        else:
            invalid += 1
    return {
        "source": "provider_usage_receipts_only",
        "attempts_with_valid_usage": receipts,
        "attempts_with_unknown_usage": unknown,
        "attempts_with_invalid_usage": invalid,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_reported_tokens": prompt + completion,
    }


def strict_score(text: str, expected: str, provider: str | None,
                 returned_model: str | None, status: int | None, done: bool,
                 failure: str | None, finish_reason: str | None) -> dict[str, Any]:
    choice = text.strip()
    is_choice = choice in {"A", "B", "C", "D"}
    valid_route = (isinstance(provider, str)
                   and provider.strip().casefold() == PROVIDER
                   and returned_model == MODEL)
    scoreable = (is_choice and valid_route and status == 200 and done
                 and failure is None and finish_reason in {"stop", "length"})
    return {
        "choice": choice if is_choice else None,
        "scoreable": scoreable,
        "correct": (choice == expected) if scoreable else None,
        "outcome_class": (
            "correct" if scoreable and choice == expected
            else "wrong_answer" if scoreable
            else "invalid_or_incomplete_response" if status is not None
            else "unknown_transport_outcome"
        ),
    }


def is_provider_context_limit_rejection(status: int | None,
                                        raw_events: list[str]) -> bool:
    """Recognize explicit provider HTTP 400s rejected before model generation."""
    if status != 400:
        return False
    for event in raw_events:
        try:
            payload = json.loads(event)
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            continue
        message = error.get("message")
        if (error.get("code") == 400 and isinstance(message, str)
                and "maximum context length" in message.casefold()
                and "requested" in message.casefold()):
            return True
    return False


def score_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arm in ("full", "sift"):
        rows = [sample for sample in samples if sample.get("arm") == arm]
        valid = [sample for sample in rows if sample.get("scoreable") is True]
        grouped: dict[str, list[bool]] = {}
        for sample in valid:
            grouped.setdefault(sample["case_id"], []).append(sample["correct"] is True)
        result[arm] = {
            "attempts": len(rows),
            "scorable": len(valid),
            "correct": sum(item["correct"] is True for item in valid),
            "response_accuracy": (sum(item["correct"] is True for item in valid) / len(valid)
                                  if valid else None),
            "tasks_with_scorable_responses": len(grouped),
            "equal_task_weighted_accuracy": (
                sum(sum(votes) / len(votes) for votes in grouped.values()) / len(grouped)
                if grouped else None
            ),
        }
    return result


def _receipt_cost(usage: Any) -> float | None:
    """Accept a positive upstream BYOK receipt only; never infer token usage."""
    if not isinstance(usage, dict) or usage.get("is_byok") is not True:
        return None
    details = usage.get("cost_details")
    upstream = details.get("upstream_inference_cost") if isinstance(details, dict) else None
    if (isinstance(upstream, bool) or not isinstance(upstream, (int, float))
            or not math.isfinite(float(upstream)) or upstream <= 0):
        return None
    return float(upstream)


def load_previous_report(path: Path, manifest_hash: str, schedule_hash: str,
                         jobs: list[dict[str, Any]], allow_unknown: bool,
                         allow_invalid_retry: bool = False,
                         allow_unknown_retry: bool = False) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DispatchError(f"Cannot load previous dispatch report: {error}") from error
    samples = report.get("samples")
    if (report.get("manifest_sha256") != manifest_hash
            or report.get("schedule_sha256") != schedule_hash
            or report.get("provider") != PROVIDER
            or report.get("requested_model") != MODEL
            or not isinstance(samples, list)):
        raise DispatchError("Previous report does not match the frozen manifest, schedule, and provider")
    stored_hash = report.get("checkpoint_sha256")
    unsigned = dict(report)
    unsigned.pop("checkpoint_sha256", None)
    if stored_hash != canonical_sha256(unsigned):
        raise DispatchError("Previous report checkpoint integrity hash does not match its contents")
    status = report.get("status")
    if status not in {"complete", "prefix_incomplete", "budget_guard_stopped_before_request",
                      "stopped_incomplete_run", "dispatching"}:
        raise DispatchError(f"Previous report status is not resumable: {status}")
    by_index = {job["index"]: job for job in jobs}
    unknown_ids = report.get("unknown_outcome_job_ids", [])
    schedule_job_ids = {job["job_id"] for job in jobs}
    if (not isinstance(unknown_ids, list)
            or any(not isinstance(job_id, str) or job_id not in schedule_job_ids
                   for job_id in unknown_ids)
            or len(unknown_ids) != len(set(unknown_ids))):
        raise DispatchError("Previous report has invalid or duplicate unknown-outcome job IDs")
    last_index = -1
    seen_attempts: set[tuple[int, int]] = set()
    previous_sample: dict[str, Any] | None = None
    for sample in samples:
        index = sample.get("index")
        attempt = sample.get("attempt_number")
        job = by_index.get(index)
        if (job is None or job["eligibility"].get("status") != "eligible_by_local_token_estimate"
                or sample.get("job_id") != job["job_id"]
                or sample.get("request_body_sha256") != job["body_sha256"]
                or type(attempt) is not int or attempt not in {1, 2, 3}
                or (index, attempt) in seen_attempts or index < last_index):
            raise DispatchError("Previous report contains a duplicate, retried, or nonsequential attempt")
        if index == last_index:
            valid_second_attempt = (
                attempt == 2 and previous_sample is not None
                and previous_sample.get("index") == index
                and previous_sample.get("attempt_number") == 1
                and previous_sample.get("scoreable") is False
                and ((previous_sample.get("provider_usage_cost_usd") is not None
                      and previous_sample.get("failure") is None)
                     or (allow_unknown_retry
                         and previous_sample.get("unknown_attempt_without_receipt") is True
                         and sample.get("job_id") in report.get("unknown_outcome_job_ids", [])))
            )
            valid_third_attempt = (
                attempt == 3 and allow_unknown_retry and previous_sample is not None
                and previous_sample.get("index") == index
                and previous_sample.get("attempt_number") == 2
                and previous_sample.get("scoreable") is False
                and previous_sample.get("unknown_attempt_without_receipt") is True
                and sample.get("job_id") in report.get("unknown_outcome_job_ids", [])
            )
            if not (valid_second_attempt or valid_third_attempt):
                raise DispatchError("Retry history is not permitted by the saved receipt and approval policy")
        elif attempt != 1:
            raise DispatchError("A first attempt must be numbered 1")
        seen_attempts.add((index, attempt))
        last_index = index
        previous_sample = sample
    recomputed_totals = reported_token_totals(samples)
    stored_totals = report.get("provider_token_totals")
    sample_job_ids = {sample.get("job_id") for sample in samples}
    unknown_without_sample = sum(
        1 for job_id in report.get("unknown_outcome_job_ids", [])
        if job_id not in sample_job_ids
    )
    if (not isinstance(stored_totals, dict)
            or any(stored_totals.get(key) != value
                   for key, value in recomputed_totals.items())
            or stored_totals.get("unknown_outcome_attempts_without_saved_response", 0)
            != unknown_without_sample):
        raise DispatchError("Previous report token totals do not match its receipt-backed samples")
    expected_cost = sum(
        float(sample["provider_usage_cost_usd"])
        for sample in samples
        if isinstance(sample.get("provider_usage_cost_usd"), (int, float))
        and math.isfinite(float(sample["provider_usage_cost_usd"]))
        and float(sample["provider_usage_cost_usd"]) >= 0
    )
    prior_cost = report.get("settled_upstream_cost_usd")
    if (not isinstance(prior_cost, (int, float)) or not math.isfinite(float(prior_cost))
            or abs(float(prior_cost) - expected_cost) > 1e-9):
        raise DispatchError("Previous report settled cost does not match receipt-backed samples")
    flight = report.get("in_flight")
    if isinstance(flight, dict) and flight.get("state") == "unknown_outcome_requires_external_reconciliation":
        if not allow_unknown:
            raise DispatchError("Previous report has an ambiguous attempt; use explicit --accept-unknown-and-continue only after reconciliation")
        flight_samples = [row for row in samples if row.get("job_id") == flight.get("job_id")]
        latest_flight_attempt = flight_samples[-1] if flight_samples else None
        valid_unknown_retry_flight = (
            allow_unknown_retry and flight.get("job_id") in unknown_ids
            and flight.get("index") == by_index.get(flight.get("index"), {}).get("index")
            and ((not flight_samples and flight.get("index") == last_index + 1)
                 or (latest_flight_attempt is not None
                     and latest_flight_attempt.get("scoreable") is False
                     and latest_flight_attempt.get("provider_usage_cost_usd") is None
                     and latest_flight_attempt.get("attempt_number") in {1, 2}
                     and (flight.get("attempt_number") is None
                          or latest_flight_attempt.get("attempt_number") == flight.get("attempt_number"))))
        )
        if allow_unknown_retry:
            if not valid_unknown_retry_flight:
                raise DispatchError("Ambiguous in-flight retry does not match its saved unknown attempt")
        elif flight.get("index") != last_index:
            raise DispatchError("Ambiguous in-flight index does not match the latest recorded attempt")
        if allow_unknown_retry and flight.get("job_id") not in unknown_ids:
            raise DispatchError("Unknown-outcome retry is missing its preserved unknown job ID")
    elif status == "dispatching" and isinstance(flight, dict):
        next_eligible = min(
            (index for index, job in by_index.items()
             if index > last_index
             and job["eligibility"].get("status") == "eligible_by_local_token_estimate"),
            default=None,
        )
        retry_in_flight = (
            type(flight.get("index")) is int
            and flight.get("index") == last_index
            and flight.get("attempt_number") == 2
            and previous_sample is not None
            and previous_sample.get("index") == last_index
            and previous_sample.get("attempt_number") == 1
            and previous_sample.get("scoreable") is False
            and previous_sample.get("failure") is None
            and allow_invalid_retry
        )
        if not allow_unknown:
            raise DispatchError("Previous report was interrupted during a request; use explicit --accept-unknown-and-continue after reconciliation")
        if (flight.get("state") != "request_started"
                or type(flight.get("index")) is not int
                or flight.get("index") not in by_index
                or by_index[flight["index"]]["eligibility"].get("status") != "eligible_by_local_token_estimate"
                or flight.get("job_id") != by_index[flight["index"]]["job_id"]
                or flight.get("request_body_sha256") != by_index[flight["index"]]["body_sha256"]
                or flight.get("attempt_number") not in {1, 2}
                or (flight.get("attempt_number") == 2 and not retry_in_flight)
                or flight["index"] != (last_index if retry_in_flight else next_eligible)):
            raise DispatchError("Interrupted request marker is inconsistent with the next eligible schedule row")
    elif status == "stopped_incomplete_run":
        retry_sample = samples[-1] if samples else None
        if (not allow_invalid_retry or report.get("stop_reason") != "response_not_strictly_scoreable"
                or retry_sample is None or retry_sample.get("scoreable") is not False
                or retry_sample.get("failure") is not None
                or retry_sample.get("job_completed") is True
                or retry_sample.get("provider_usage_cost_usd") is None
                or report.get("unknown_outcome_job_ids")):
            raise DispatchError("Prior run stopped on a settled safety failure; do not continue this schedule")
    elif isinstance(flight, dict):
        raise DispatchError("Previous report has an unresolved in-flight request")
    return report


def dispatch(args: argparse.Namespace, manifest: dict[str, Any],
             ordered_jobs: list[dict[str, Any]], validated: dict[str, Any],
             expected_keys: dict[str, str], prepared_report: dict[str, Any]) -> dict[str, Any]:
    # Validate bounds and full-schedule reserve before touching credentials.
    if (not math.isfinite(args.spend_cap_usd) or args.spend_cap_usd <= 0
            or args.spend_cap_usd > MAX_SPEND_CAP_USD):
        raise DispatchError(f"--spend-cap-usd must be positive and no more than ${MAX_SPEND_CAP_USD:.2f}")
    eligible = validated["eligible_jobs"]
    if type(args.prefix) is not int or not 1 <= args.prefix <= len(eligible):
        raise DispatchError(f"--prefix must be from 1 through {len(eligible)} eligible jobs")
    selected = eligible[:args.prefix]
    estimate = (sum(job["local_prompt_tokens"] for job in selected)
                * INPUT_RESERVE_FACTOR * INPUT_PRICE_USD_PER_MILLION
                + len(selected) * validated["protocol"]["max_output_tokens"]
                * OUTPUT_PRICE_USD_PER_MILLION) / 1_000_000
    if args.spend_cap_usd < estimate:
        raise DispatchError(f"Cap ${args.spend_cap_usd:.6f} is below selected-prefix reserve ${estimate:.6f}")
    previous = None
    if args.resume_from_report:
        previous = load_previous_report(args.resume_from_report,
                                        validated["manifest_sha256"],
                                        validated["schedule_sha256"],
                                        ordered_jobs, args.accept_unknown_and_continue,
                                        args.retry_invalid_response,
                                        args.retry_unknown_outcome)
        if args.output.exists():
            raise DispatchError(f"Refusing to overwrite continuation output: {args.output}")
    elif args.output.exists():
        raise DispatchError(f"Refusing to overwrite an existing report: {args.output}")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise DispatchError("OPENROUTER_API_KEY is required only for explicit --dispatch")
    import requests  # lazy import; offline/help modes do not construct provider clients

    report = dict(prepared_report)
    report.update({
        "status": "dispatching",
        "actual_dispatch_started": True,
        "dispatch_prefix_count": args.prefix,
        "eligible_prefix_job_ids": [job["job_id"] for job in selected],
        "spend_cap_usd": args.spend_cap_usd,
        "dispatch_started_utc": datetime.now(timezone.utc).isoformat(),
        "samples": [],
        "attempted_jobs": 0,
        "completed_jobs": 0,
        "unknown_outcome_job_ids": [],
        "runtime_ineligible_job_ids": [],
        "settled_upstream_cost_usd": 0.0,
        "in_flight": None,
    })
    completed_indices: set[int] = set()
    if previous is not None:
        prior_flight = previous.get("in_flight")
        previous_prefix = previous.get("dispatch_prefix_count")
        report.update({key: value for key, value in previous.items()
                       if key not in {"status", "stop_reason", "finished_utc", "in_flight"}})
        report.update(
            status="dispatching",
            actual_dispatch_started=True,
            dispatch_prefix_count=args.prefix,
            eligible_prefix_job_ids=[job["job_id"] for job in selected],
            spend_cap_usd=args.spend_cap_usd,
            full_schedule_complete=False,
            previous_dispatch_prefix_count=previous_prefix,
            continuation_started_utc=datetime.now(timezone.utc).isoformat(),
        )
        report["samples"] = [dict(row) for row in previous.get("samples", [])]
        report["attempted_jobs"] = len(report["samples"])
        report["completed_jobs"] = sum(row.get("job_completed") is True
                                       for row in report["samples"])
        completed_indices = {row["index"] for row in report["samples"]
                             if row.get("job_completed") is True}
        report["unknown_outcome_job_ids"] = list(previous.get("unknown_outcome_job_ids", []))
        report["runtime_ineligible_job_ids"] = list(
            previous.get("runtime_ineligible_job_ids", []))
        report["settled_upstream_cost_usd"] = float(previous.get("settled_upstream_cost_usd", 0.0))
        report["prior_report_path"] = str(args.resume_from_report)
        report["prior_unknown_outcome_accepted"] = args.accept_unknown_and_continue
        report["invalid_response_retry_authorized"] = args.retry_invalid_response
        if (isinstance(prior_flight, dict)
                and prior_flight.get("state") == "request_started"):
            flight_id = prior_flight["job_id"]
            if flight_id not in report["unknown_outcome_job_ids"]:
                report["unknown_outcome_job_ids"].append(flight_id)
            report["interrupted_in_flight_reconciled_as_unknown"] = {
                "index": prior_flight["index"], "job_id": flight_id,
                "request_body_sha256": prior_flight["request_body_sha256"],
                "decision": "skip_without_retry_after_explicit_acceptance",
            }
        elif (isinstance(prior_flight, dict)
              and prior_flight.get("state") == "unknown_outcome_requires_external_reconciliation"
              and args.retry_unknown_outcome):
            flight_job = next(job for job in ordered_jobs
                              if job["index"] == prior_flight["index"])
            flight_id = prior_flight["job_id"]
            report.setdefault("retried_unknown_outcome_job_ids", [])
            if flight_id not in report["retried_unknown_outcome_job_ids"]:
                report["retried_unknown_outcome_job_ids"].append(flight_id)
            flight_attempt = prior_flight.get("attempt_number") or (
                1 + sum(row.get("job_id") == flight_id for row in report["samples"]))
            saved_unknown_row = next((
                row for row in report["samples"]
                if row.get("job_id") == flight_id
                and row.get("attempt_number") == flight_attempt
                and row.get("scoreable") is False
                and row.get("provider_usage_cost_usd") is None
            ), None)
            if saved_unknown_row is None:
                report["samples"].append({
                "index": flight_job["index"], "job_id": flight_id,
                "attempt_number": flight_attempt, "case_id": flight_job["case_id"],
                "arm": flight_job["arm"], "repeat": flight_job["repeat"],
                "seed": flight_job["seed"],
                "request_body_sha256": flight_job["body_sha256"],
                "http_status": None, "response_id": None,
                "requested_model": MODEL, "returned_model": None,
                "provider": None, "usage": None, "finish_reason": None,
                "response_text": "", "raw_events": [],
                "sse_done_received": False,
                "provider_usage_cost_usd": None,
                "provider_local_input_ratio": None,
                "request_started_utc": None, "response_completed_utc": None,
                "ttft_seconds": None, "request_wall_seconds": None,
                "sift_preprocessing_ms": flight_job["sift_preprocessing_ms"],
                "failure": None, "choice": None, "scoreable": False,
                "correct": None, "outcome_class": "unknown_transport_outcome",
                "unknown_attempt_without_receipt": True,
                "job_completed": False,
                })
                report["samples"].sort(key=lambda row: (row["index"], row["attempt_number"]))
                report["attempted_jobs"] = len(report["samples"])
            else:
                saved_unknown_row["unknown_attempt_without_receipt"] = True
            report["interrupted_in_flight_reconciled_as_unknown"] = {
                "index": prior_flight["index"], "job_id": flight_id,
                "request_body_sha256": prior_flight["request_body_sha256"],
                "decision": "one_retry_authorized; original_usage_remains_unknown",
            }
    report["provider_token_totals"] = reported_token_totals(report["samples"])
    saved_job_ids = {sample.get("job_id") for sample in report["samples"]}
    report["provider_token_totals"]["unknown_outcome_attempts_without_saved_response"] = sum(
        1 for job_id in report.get("unknown_outcome_job_ids", [])
        if job_id not in saved_job_ids
    )
    atomic_write(args.output, report)
    settled = report["settled_upstream_cost_usd"]
    start_index = max((row["index"] for row in report["samples"]), default=-1) + 1
    if (previous is not None and args.retry_invalid_response
            and previous.get("status") == "stopped_incomplete_run"
            and previous.get("stop_reason") == "response_not_strictly_scoreable"):
        start_index = previous["samples"][-1]["index"]
    if report.get("interrupted_in_flight_reconciled_as_unknown"):
        interrupted = report["interrupted_in_flight_reconciled_as_unknown"]
        if interrupted.get("decision", "").startswith("one_retry_authorized"):
            start_index = min(start_index, interrupted["index"])
        else:
            start_index = max(start_index, interrupted["index"] + 1)
    selected_indices = {job["index"] for job in selected}
    jobs_to_dispatch = list(selected)
    queued_retry_indices: set[int] = set()
    if previous is not None and args.retry_invalid_response:
        pending_retry_indices = {
            row.get("index") for row in previous.get("samples", [])
            if row.get("scoreable") is False
            and row.get("failure") is None
            and row.get("job_completed") is not True
            and row.get("provider_usage_cost_usd") is not None
            and row.get("index", -1) < start_index
        }
        jobs_to_dispatch.extend(
            job for job in selected if job["index"] in pending_retry_indices)
        queued_retry_indices.update(pending_retry_indices)
    if (args.retry_unknown_outcome
            and isinstance(report.get("interrupted_in_flight_reconciled_as_unknown"), dict)
            and report["interrupted_in_flight_reconciled_as_unknown"].get("decision", "").startswith("one_retry_authorized")):
        unknown_retry_index = report["interrupted_in_flight_reconciled_as_unknown"]["index"]
        if unknown_retry_index not in queued_retry_indices:
            jobs_to_dispatch.extend(job for job in selected if job["index"] == unknown_retry_index)
        queued_retry_indices.add(unknown_retry_index)
    elapsed_start = time.perf_counter()
    for job in jobs_to_dispatch:
        index = job["index"]
        if ((index < start_index and index not in queued_retry_indices)
                or index in completed_indices):
            continue
        attempt_number = 1 + sum(sample.get("index") == index
                                 for sample in report["samples"])
        if attempt_number > (3 if args.retry_unknown_outcome else 2) or (attempt_number == 2
                                  and not (args.retry_invalid_response
                                           or args.retry_unknown_outcome)):
            raise DispatchError(f"Retry policy does not permit attempt {attempt_number} for {job['job_id']}")
        reserve = (job["local_prompt_tokens"] * INPUT_RESERVE_FACTOR
                   * INPUT_PRICE_USD_PER_MILLION
                   + validated["protocol"]["max_output_tokens"]
                   * OUTPUT_PRICE_USD_PER_MILLION) / 1_000_000
        if settled + reserve > args.spend_cap_usd:
            report.update(status="budget_guard_stopped_before_request",
                          stop_reason="next_request_reservation_exceeds_cap")
            break
        report["in_flight"] = {
            "index": index, "job_id": job["job_id"], "attempt_number": attempt_number,
            "request_body_sha256": job["body_sha256"],
            "reserved_cost_usd": reserve, "state": "request_started",
        }
        atomic_write(args.output, report)
        started = time.perf_counter()
        request_started_utc = datetime.now(timezone.utc).isoformat()
        first_content_at: float | None = None
        fragments: list[str] = []
        raw_events: list[str] = []
        usage = None
        status = response_id = returned_model = returned_provider = finish_reason = None
        failure = None
        done = False
        try:
            with requests.post(
                API_URL,
                json=job["body"],
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                stream=True,
                timeout=(30, 600),
            ) as response:
                status = response.status_code
                if status != 200:
                    failure = "http_status_not_200"
                    raw_events.append(response.text)
                else:
                    for line in response.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if line.strip() == "data: [DONE]":
                            done = True
                            break
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        raw_events.append(raw)
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            failure = "invalid_sse_json"
                            break
                        if not isinstance(event, dict):
                            failure = "invalid_sse_event"
                            break
                        response_id = response_id or event.get("id")
                        returned_model = event.get("model") or returned_model
                        returned_provider = event.get("provider") or returned_provider
                        if isinstance(event.get("usage"), dict):
                            usage = event["usage"]
                        choices = event.get("choices")
                        if isinstance(choices, list):
                            # OpenAI-compatible SSE ends with an optional
                            # usage-only event whose choices array is empty.
                            if len(choices) > 1:
                                failure = "unexpected_choice_count"
                                break
                            for choice_event in choices:
                                if (not isinstance(choice_event, dict)
                                        or choice_event.get("index") not in (0, None)):
                                    failure = "unexpected_choice_shape"
                                    break
                                finish_reason = choice_event.get("finish_reason") or finish_reason
                                delta = choice_event.get("delta") or {}
                                content = delta.get("content") if isinstance(delta, dict) else None
                                if isinstance(content, str):
                                    if content and first_content_at is None:
                                        first_content_at = time.perf_counter()
                                    fragments.append(content)
        except Exception as error:
            # This is ambiguous: preserve it, stop immediately, and never retry.
            failure = f"request_exception:{type(error).__name__}"
        wall = time.perf_counter() - started
        text = "".join(fragments)
        receipt_cost = _receipt_cost(usage)
        score = strict_score(text, expected_keys[job["case_id"]], returned_provider,
                             returned_model, status, done, failure, finish_reason)
        context_rejected = is_provider_context_limit_rejection(status, raw_events)
        if context_rejected:
            score["outcome_class"] = "provider_context_limit_rejected_before_generation"
            if job["job_id"] not in report["runtime_ineligible_job_ids"]:
                report["runtime_ineligible_job_ids"].append(job["job_id"])
        sample = {
            "index": index, "job_id": job["job_id"], "attempt_number": attempt_number,
            "case_id": job["case_id"], "arm": job["arm"], "repeat": job["repeat"],
            "seed": job["seed"], "request_body_sha256": job["body_sha256"],
            "http_status": status, "response_id": response_id,
            "requested_model": MODEL, "returned_model": returned_model,
            "provider": returned_provider, "usage": usage,
            "finish_reason": finish_reason, "response_text": text,
            "raw_events": raw_events, "sse_done_received": done,
            "provider_usage_cost_usd": receipt_cost,
            "provider_local_input_ratio": (
                usage.get("prompt_tokens") / job["local_prompt_tokens"]
                if isinstance(usage, dict)
                and type(usage.get("prompt_tokens")) is int
                and usage["prompt_tokens"] > 0 else None
            ),
            "request_started_utc": request_started_utc,
            "response_completed_utc": datetime.now(timezone.utc).isoformat(),
            "ttft_seconds": first_content_at - started if first_content_at is not None else None,
            "request_wall_seconds": wall,
            "sift_preprocessing_ms": job["sift_preprocessing_ms"],
            "failure": failure,
            **score,
        }
        report["samples"].append(sample)
        if receipt_cost is None and failure is not None and not context_rejected:
            sample["unknown_attempt_without_receipt"] = True
        report["samples"].sort(key=lambda row: (row["index"], row["attempt_number"]))
        report["attempted_jobs"] = len(report["samples"])
        report["provider_token_totals"] = reported_token_totals(report["samples"])
        report["in_flight"] = None
        terminal_reason = None
        if context_rejected:
            # The provider explicitly rejected the input before generation. It
            # has no usage receipt because no model request ran, so it is a
            # resolved runtime ineligibility rather than ambiguous usage.
            pass
        elif failure is not None or status != 200:
            terminal_reason = "request_failed_no_retry"
        elif not done:
            terminal_reason = "missing_sse_done_no_retry"
        elif (not isinstance(returned_provider, str)
              or returned_provider.strip().casefold() != PROVIDER
              or returned_model != MODEL):
            terminal_reason = "provider_or_model_mismatch"
        elif receipt_cost is None:
            terminal_reason = "positive_byok_upstream_receipt_required"
        elif not isinstance(usage, dict) or type(usage.get("prompt_tokens")) is not int or type(usage.get("completion_tokens")) is not int:
            terminal_reason = "provider_token_usage_missing_or_invalid"
        elif (usage.get("prompt_tokens") < 0 or usage.get("completion_tokens") < 0
              or usage.get("prompt_tokens") / job["local_prompt_tokens"] > INPUT_RESERVE_FACTOR):
            terminal_reason = "provider_usage_exceeds_token_reserve"
        elif receipt_cost > reserve:
            terminal_reason = "request_receipt_exceeds_reservation"
        elif settled + receipt_cost > args.spend_cap_usd:
            terminal_reason = "settled_cost_exceeds_client_cap"
        elif finish_reason not in {"stop", "length"}:
            terminal_reason = "request_incomplete_or_unexpected_finish_reason"
        elif not score["scoreable"] and attempt_number == 1:
            if args.retry_invalid_response:
                # The user-approved policy permits one receipt-backed retry for
                # strict-format failures. Queue it after the original schedule so
                # the full manifest preflight is not repeated for each bad answer.
                jobs_to_dispatch.append(job)
            else:
                terminal_reason = "response_not_strictly_scoreable"
        if receipt_cost is not None:
            settled += receipt_cost
            report["settled_upstream_cost_usd"] = settled
        if terminal_reason:
            report["status"] = "stopped_incomplete_run"
            report["stop_reason"] = terminal_reason
            if receipt_cost is None:
                report["in_flight"] = {
                    "index": index, "job_id": job["job_id"],
                    "state": "unknown_outcome_requires_external_reconciliation",
                    "request_body_sha256": job["body_sha256"],
                }
                report["unknown_outcome_job_ids"].append(job["job_id"])
            atomic_write(args.output, report)
            break
        if score["scoreable"] or attempt_number >= 2 or context_rejected:
            sample["job_completed"] = True
            report["completed_jobs"] += 1
        atomic_write(args.output, report)
    else:
        report["status"] = "complete" if report["completed_jobs"] == len(selected) else "prefix_incomplete"
    report["full_schedule_complete"] = (
        report["completed_jobs"] == len(eligible)
        and len(eligible) == len(selected)
        and not report.get("unknown_outcome_job_ids")
    )
    report["score_summary"] = score_summary(report["samples"])
    report["provider_token_totals"] = reported_token_totals(report["samples"])
    report["provider_token_totals"]["unknown_outcome_attempts_without_saved_response"] = sum(
        1 for item in report.get("unknown_outcome_job_ids", [])
        if not any(sample.get("job_id") == item for sample in report["samples"])
    )
    report["dispatch_wall_seconds"] = time.perf_counter() - elapsed_start
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_write(args.output, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true",
                      help="Verify and reconstruct offline; this is the default and makes no API calls.")
    mode.add_argument("--dispatch", action="store_true",
                      help="Explicitly send eligible jobs through provider minimax only.")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--prefix", type=int, default=None,
                        help="Dispatch the first N eligible jobs in frozen schedule order.")
    parser.add_argument("--spend-cap-usd", type=float, default=None,
                        help="Explicit client-side cap, at most $2,000.")
    parser.add_argument("--resume-from-report", type=Path, default=None,
                        help="Continue after a reviewed report; an unknown request is never retried.")
    parser.add_argument("--accept-unknown-and-continue", action="store_true",
                        help="After external reconciliation, skip the ambiguous job and continue; its result stays unknown.")
    parser.add_argument("--retry-invalid-response", action="store_true",
                        help="Retry once after a receipt-backed response fails strict choice scoring; all attempts remain reported.")
    parser.add_argument("--retry-unknown-outcome", action="store_true",
                        help="After explicit acceptance, retry one unknown-usage request; its original usage remains unknown.")
    args = parser.parse_args(argv)
    dispatch_mode = bool(args.dispatch)
    if dispatch_mode:
        if args.spend_cap_usd is None or args.prefix is None:
            raise DispatchError("--dispatch requires both --spend-cap-usd and bounded --prefix")
        if args.accept_unknown_and_continue and not args.resume_from_report:
            raise DispatchError("--accept-unknown-and-continue requires --resume-from-report")
        if args.retry_invalid_response and not args.resume_from_report:
            raise DispatchError("--retry-invalid-response requires --resume-from-report")
        if args.retry_unknown_outcome and not (args.resume_from_report
                                               and args.accept_unknown_and_continue):
            raise DispatchError("--retry-unknown-outcome requires a report and --accept-unknown-and-continue")
    elif (any(value is not None for value in (args.spend_cap_usd, args.prefix, args.resume_from_report))
          or args.accept_unknown_and_continue or args.retry_invalid_response
          or args.retry_unknown_outcome):
        raise DispatchError("Dispatch options require explicit --dispatch")

    manifest = load_manifest(args.manifest)
    validate_source_hashes(manifest, args.dataset, args.tokenizer, args.template)
    ordered_jobs, scoring_keys, validated = reconstruct(manifest, args.tokenizer, args.dataset)
    output = args.output or (DISPATCH_DEFAULT if dispatch_mode else PREPARED_DEFAULT)
    report = build_report(manifest, args.manifest, ordered_jobs, validated,
                          args.spend_cap_usd if dispatch_mode else None)
    if not dispatch_mode:
        if output.exists():
            raise DispatchError(f"Refusing to overwrite existing prepared report: {output}")
        atomic_write(output, report)
        print(json.dumps({
            "status": report["status"], "manifest_sha256": report["manifest_sha256"],
            "schedule_sha256": report["schedule_sha256"], "dataset_rows": report["dataset_rows"],
            "full_schedule_rows": report["full_schedule_rows"],
            "eligible_jobs": report["eligible_jobs"],
            "eligible_counts_by_arm": report["eligible_counts_by_arm"],
            "output": str(output),
        }, sort_keys=True))
        return 0
    if args.resume_from_report is not None:
        load_previous_report(args.resume_from_report, validated["manifest_sha256"],
                             validated["schedule_sha256"], ordered_jobs,
                             args.accept_unknown_and_continue,
                             args.retry_invalid_response,
                             args.retry_unknown_outcome)
    result = dispatch(args, manifest, ordered_jobs, validated, scoring_keys, report)
    print(json.dumps({key: result.get(key) for key in (
        "status", "dispatch_prefix_count", "eligible_jobs", "attempted_jobs",
        "completed_jobs", "full_schedule_complete", "provider_token_totals",
        "score_summary", "stop_reason", "schedule_sha256")}, sort_keys=True))
    return 0 if result.get("status") in {"complete", "prefix_incomplete", "budget_guard_stopped_before_request"} else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DispatchError as error:
        raise SystemExit(f"LongBench full-suite dispatcher stopped: {error}")
