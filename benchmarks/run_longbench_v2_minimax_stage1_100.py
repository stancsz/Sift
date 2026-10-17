"""Prepare or explicitly dispatch the frozen 100-task or 344-task MiniMax study.

Default invocation is offline. The prepared artifact contains hashes and counts,
never prompt or answer text. Dispatch has no resume mode: any prior/ambiguous
dispatch must be reconciled out of band before starting a new output file.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any

import requests
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION, DATASET_SHA256, file_sha256, make_messages, prompt_sha256,
)
from audit_longbench_v2_target_sweep import iter_selected_dataset_rows  # noqa: E402
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from sift import CompactionError, compact_messages  # noqa: E402

MANIFEST = ROOT / "docs/evals/longbench-v2-minimax-stage1-100-manifest-2026-10-18.json"
MANIFEST_344 = ROOT / "docs/evals/longbench-v2-minimax-344-manifest-2026-10-17.json"
PARENT = ROOT / "docs/evals/longbench-v2-minimax-344-manifest-2026-10-17.json"
HISTORICAL = ROOT / "docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json"
DATASET_DEFAULT = ROOT / ".runs/longbench-v2-data-pinned.json"
TOKENIZER_DEFAULT = ROOT / "tmp/minimax-m3-tokenizer.json"
TEMPLATE_DEFAULT = ROOT / "tmp/minimax-m3-chat-template.jinja"
OUTPUT_DEFAULT = ROOT / ".runs/longbench-v2-minimax-stage1-100-run.json"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "minimax/minimax-m3"
TARGET = 32_768
SAFETY_MARGIN = 128
OUTPUT_CAP = 64
REPEATS = 3
STUDY_SEED = 20261018
MAX_RATIO = 1.05
INPUT_FACTOR = 1.5
INPUT_PRICE = 0.30  # dated planning rate; dispatch cap must be approved separately
OUTPUT_PRICE = 1.20
PROJECTION = 3.25
PROVIDER_LIMIT = 524_288
MANIFEST_SHA256_STAGE1 = "52a7515d9bec715ccc17c85295b2e111d97cb2bffc00bd71fc9ed933cb22fce2"
MANIFEST_SHA256_344 = "6364b4a21e5775fb4cd574e501286db64320cd4cde2b083250b07ec13ea6abc0"


class StageError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def safe_repo_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise StageError(f"Manifest path escapes repository: {relative}") from error
    if not path.is_file():
        raise StageError(f"Required frozen source is missing: {relative}")
    return path


def verify_provenance(manifest: dict, manifest_path: Path, dataset: Path,
                      tokenizer_path: Path, template_path: Path) -> tuple[str, dict]:
    is_stage1 = "selection" in manifest
    mode = "stage1_100" if is_stage1 else "primary_344"
    expected_manifest_hash = MANIFEST_SHA256_STAGE1 if is_stage1 else MANIFEST_SHA256_344
    if file_sha256(manifest_path) != expected_manifest_hash:
        raise StageError(f"Reviewed {mode} manifest hash mismatch")
    if manifest.get("dispatch_authorized") is not False:
        raise StageError("Stage manifest must remain dispatch_authorized=false")
    if manifest.get("status") != "prepared_only_no_dispatch":
        raise StageError("Unexpected prepared manifest status")
    if is_stage1:
        if manifest_path.resolve() != MANIFEST.resolve():
            raise StageError("The 100-task mode accepts only the frozen Stage 1 manifest")
        if manifest.get("evidence_class") != "exposed_development_sample_not_blind_holdout":
            raise StageError("Stage evidence class changed")
        if manifest.get("parent_manifest") != PARENT.relative_to(ROOT).as_posix():
            raise StageError("Unexpected parent manifest reference")
        if manifest.get("historical_sample_manifest") != HISTORICAL.relative_to(ROOT).as_posix():
            raise StageError("Unexpected historical sample reference")
        parent = json.loads(PARENT.read_text(encoding="utf-8"))
        historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))
        if file_sha256(PARENT) != manifest.get("parent_manifest_sha256"):
            raise StageError("Parent manifest hash mismatch")
        if file_sha256(HISTORICAL) != manifest.get("historical_sample_manifest_sha256"):
            raise StageError("Historical sample manifest hash mismatch")
        if parent.get("schema_version") != 1 or len(parent.get("cases", [])) != 344:
            raise StageError("Parent manifest is not the reviewed 344-case artifact")
        ids = manifest.get("selection", {}).get("ids")
        if (not isinstance(ids, list) or len(ids) != 100 or len(set(ids)) != 100
                or manifest.get("selection", {}).get("selected_count") != 100):
            raise StageError("Stage manifest must select exactly 100 distinct IDs")
        parent_ids = {case.get("id") for case in parent["cases"]}
        historical_ids = {case.get("id") for case in historical.get("cases", [])}
        if not set(ids) <= parent_ids or set(ids) != historical_ids:
            raise StageError("Stage IDs do not equal the historical sample within parent cohort")
        if len(manifest.get("cases", [])) != 100:
            raise StageError("Stage case metadata count is not 100")
        by_id = {case.get("id"): case for case in manifest["cases"]}
        if set(by_id) != set(ids):
            raise StageError("Stage case metadata does not match selected ID set")
    else:
        if manifest_path.resolve() != MANIFEST_344.resolve():
            raise StageError("The 344-task mode accepts only the frozen primary manifest")
        ids = [case.get("id") for case in manifest.get("cases", [])]
        if len(ids) != 344 or len(set(ids)) != 344:
            raise StageError("Primary manifest must contain exactly 344 distinct cases")
        if len(manifest.get("jobs", [])) != 2064:
            raise StageError("Primary manifest must contain exactly 2,064 frozen jobs")
    if manifest.get("dataset", {}).get("revision") != DATASET_REVISION:
        raise StageError("Dataset revision mismatch")
    dataset_digest = manifest["dataset"].get("sha256") or manifest["dataset"].get("data_file_sha256")
    if dataset_digest != DATASET_SHA256:
        raise StageError("Dataset digest in manifest mismatch")
    if file_sha256(dataset) != DATASET_SHA256:
        raise StageError("Local dataset digest mismatch")
    sources = manifest.get("source_hashes", {})
    parent_sources = parent.get("source_hashes", {}) if is_stage1 else sources
    required = {
        "builder": ROOT / "benchmarks/prepare_longbench_v2_minimax_344.py",
        "spec": ROOT / "docs/evals/longbench-v2-minimax-paired-study-spec-2026-10-17.md",
        "sift_core": ROOT / "src/sift/core.py",
        "sift_package_init": ROOT / "src/sift/__init__.py",
        "prompt_builder": ROOT / "benchmarks/prepare_longbench_v2.py",
        "renderer": ROOT / "benchmarks/prepare_longbench_v2_minimax.py",
    }
    for key, path in required.items():
        if not path.is_file():
            raise StageError(f"Missing frozen source for {key}: {path}")
        actual = file_sha256(path)
        if actual != sources.get(key) or actual != parent_sources.get(key):
            raise StageError(f"Frozen source hash mismatch: {key}")
    if file_sha256(tokenizer_path) != manifest["source_hashes"].get("tokenizer"):
        raise StageError("Tokenizer hash mismatch")
    if file_sha256(template_path) != manifest["source_hashes"].get("chat_template"):
        raise StageError("Chat template hash mismatch")
    if file_sha256(dataset) != manifest["source_hashes"].get("dataset"):
        raise StageError("Dataset source hash mismatch")
    route = manifest.get("route_assumptions", {})
    route_path = safe_repo_path(route.get("snapshot_path", ""))
    if (file_sha256(route_path) != route.get("snapshot_sha256")
            or route_path.name != "longbench-v2-minimax-stage2-route-2026-10-17.json"):
        raise StageError("Dated route snapshot provenance mismatch")
    if (route.get("requested_model") != MODEL or route.get("provider", "").casefold() != "minimax"
            or route.get("authorizes_dispatch") is not False):
        raise StageError("Route assumptions must identify MiniMax and explicitly deny dispatch authorization")
    protocol = manifest.get("protocol", {})
    expected = {
        "study_seed": STUDY_SEED, "arms": ["full", "sift"],
        "repeats_per_arm": REPEATS, "temperature": 0.1, "top_p": 0.8,
        "reasoning": {"enabled": False},
        "max_tokens": OUTPUT_CAP, "stream": True,
        "stream_options": {"include_usage": True},
        "provider": {"only": ["minimax"], "allow_fallbacks": False},
        "requested_model": MODEL,
    }
    if is_stage1:
        expected["planned_requests"] = 600
    for key, value in expected.items():
        if protocol.get(key) != value:
            raise StageError(f"Frozen protocol mismatch: {key}")
    target = manifest.get("sift", {}).get("configured_target_tokens")
    if target is None:
        target = manifest.get("sift", {}).get("target_tokens")
    if target != TARGET:
        raise StageError("Sift target mismatch")
    return mode, {"ids": ids}


def count_prompt(tokenizer: Tokenizer, messages: list[dict[str, str]]) -> int:
    return len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)


def build_jobs(manifest: dict, mode: str, dataset: Path, tokenizer_path: Path) -> tuple[list[dict], dict]:
    ids = manifest["selection"]["ids"] if mode == "stage1_100" else [case["id"] for case in manifest["cases"]]
    selected = set(ids)
    fields = {"_id", "context", "question", "choice_A", "choice_B", "choice_C", "choice_D", "answer"}
    rows: dict[str, dict] = {}
    for row in iter_selected_dataset_rows(dataset, selected, fields):
        case_id = str(row.get("_id", ""))
        if case_id in rows:
            raise StageError(f"Duplicate dataset ID: {case_id}")
        rows[case_id] = row
    if set(rows) != selected:
        raise StageError("Pinned dataset does not contain the exact selected ID set")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    metadata = {case["id"]: case for case in manifest["cases"]}
    cases = []
    for case_id in ids:
        row, frozen = rows[case_id], metadata[case_id]
        if (row.get("answer") != frozen.get("answer_key")
                or not isinstance(row.get("answer"), str)
                or row["answer"] not in {"A", "B", "C", "D"}):
            raise StageError(f"Answer key mismatch: {case_id}")
        messages = make_messages(row)
        source_prompt_hash = frozen.get("source_prompt_sha256", frozen.get("full_prompt_sha256"))
        insertion_order_prompt_hash = prompt_sha256(messages)
        # The reviewed 344 artifact predates this adapter and froze sorted-key
        # hashes. Validate that legacy representation only for provenance;
        # all newly emitted prompt hashes use the original insertion-order function.
        legacy_frozen_hash = canonical_hash(messages)
        if source_prompt_hash not in {insertion_order_prompt_hash, legacy_frozen_hash}:
            raise StageError(f"Source prompt hash mismatch: {case_id}")
        full_count = count_prompt(tokenizer, messages)
        frozen_full_count = frozen.get("full_local_prompt_tokens", frozen.get("full_local_tokens"))
        frozen_sift_count = frozen.get("sift_local_prompt_tokens", frozen.get("sift_local_tokens"))
        if full_count != frozen_full_count:
            raise StageError(f"Full prompt token count mismatch: {case_id}")
        try:
            compacted = compact_messages(messages, lambda candidate: count_prompt(tokenizer, candidate),
                                         target=TARGET - SAFETY_MARGIN, raw_limit=1_000_000,
                                         protocol="openai")
        except CompactionError as error:
            raise StageError(f"Current Sift failed closed for selected case {case_id}: {error.code}") from error
        sift_messages = compacted.messages
        sift_count = count_prompt(tokenizer, sift_messages)
        if sift_count != frozen_sift_count:
            raise StageError(f"Sift prompt token count mismatch: {case_id}")
        sift_hash = frozen.get("sift_prompt_sha256")
        sift_prompt_ordered_hash = prompt_sha256(sift_messages)
        if sift_hash not in {sift_prompt_ordered_hash, canonical_hash(sift_messages)}:
            raise StageError(f"Sift prompt hash mismatch: {case_id}")
        cases.append({"id": case_id, "answer": row["answer"],
                      "domain": frozen.get("domain", row.get("domain")),
                      "sub_domain": frozen.get("sub_domain", row.get("sub_domain")),
                      "messages": {"full": messages, "sift": sift_messages},
                      "prompt_hashes": {"full": insertion_order_prompt_hash, "sift": sift_prompt_ordered_hash},
                      "counts": {"full": full_count, "sift": sift_count}, "frozen": frozen})
    rng = random.Random(STUDY_SEED)
    jobs: list[dict] = []
    for case in cases:
        block = []
        for arm in ("full", "sift"):
            for repeat in range(REPEATS):
                body = {
                    "model": MODEL, "messages": case["messages"][arm], "temperature": 0.1,
                    "top_p": 0.8, "seed": STUDY_SEED + repeat + 1,
                    "max_tokens": OUTPUT_CAP, "reasoning": {"enabled": False},
                    "stream": True, "stream_options": {"include_usage": True},
                    "provider": {"only": ["minimax"], "allow_fallbacks": False},
                }
                block.append({"case_id": case["id"], "arm": arm, "repeat": repeat,
                              "seed": body["seed"], "body": body,
                              "body_sha256": canonical_hash(body),
                              "prompt_sha256": case["prompt_hashes"][arm],
                              "domain": case["domain"], "sub_domain": case["sub_domain"],
                              "local_prompt_tokens": case["counts"][arm],
                              "local_cost_estimate_usd": (
                                  case["counts"][arm] * INPUT_FACTOR * INPUT_PRICE
                                  + OUTPUT_CAP * OUTPUT_PRICE
                              ) / 1_000_000,
                              "projected_provider_prompt_tokens": math.ceil(case["counts"][arm] * PROJECTION),
                              "expected": case["answer"]})
        rng.shuffle(block)
        jobs.extend(block)
    if mode == "primary_344":
        frozen_jobs = manifest["jobs"]
        frozen_by_key = {(job.get("case_id"), job.get("arm"), job.get("repeat")): job for job in frozen_jobs}
        if len(frozen_by_key) != 2064 or len(frozen_jobs) != 2064:
            raise StageError("Frozen 344 job identities are not unique")
        expected_schedule_hash = manifest.get("cohort_summary", {}).get("schedule_sha256")
        if canonical_hash(frozen_jobs) != expected_schedule_hash:
            raise StageError("Frozen 344 schedule hash does not match its manifest commitment")
        generated_by_key = {(job["case_id"], job["arm"], job["repeat"]): job for job in jobs}
        if set(generated_by_key) != set(frozen_by_key):
            raise StageError("Reconstructed 344 job identities differ from the frozen schedule")
        for key, job in generated_by_key.items():
            frozen = frozen_by_key[key]
            if (job["body_sha256"] != frozen.get("canonical_request_body_sha256")
                    or job["seed"] != frozen.get("matched_seed_parameter")
                    or job["projected_provider_prompt_tokens"] != frozen.get("projected_provider_prompt_count")):
                raise StageError(f"Reconstructed request differs from frozen 344 job: {key}")
        # Use the frozen manifest order exactly; list order is part of the reviewed schedule.
        order = {(job["case_id"], job["arm"], job["repeat"]): index for index, job in enumerate(frozen_jobs)}
        jobs.sort(key=lambda job: order[(job["case_id"], job["arm"], job["repeat"])])
    keys = [(job["case_id"], job["arm"], job["repeat"]) for job in jobs]
    counts = Counter(job["arm"] for job in jobs)
    expected_n = 600 if mode == "stage1_100" else 2064
    per_arm = expected_n // 2
    if len(keys) != expected_n or len(set(keys)) != expected_n or counts != {"full": per_arm, "sift": per_arm}:
        raise StageError("Generated job schedule is incomplete or nonunique")
    if any(job["projected_provider_prompt_tokens"] > PROVIDER_LIMIT for job in jobs):
        raise StageError("Projected prompt exceeds dated provider limit")
    return jobs, {case["id"]: case for case in cases}


def cost_receipt(usage: Any) -> tuple[float | None, str]:
    if not isinstance(usage, dict) or usage.get("is_byok") is not True:
        return None, "missing_or_non_byok_usage"
    details = usage.get("cost_details")
    upstream = details.get("upstream_inference_cost") if isinstance(details, dict) else None
    direct = usage.get("cost")
    nums = [value for value in (upstream, direct) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and value >= 0]
    if (upstream is None or not isinstance(upstream, (int, float)) or isinstance(upstream, bool)
            or not math.isfinite(float(upstream)) or upstream <= 0):
        return None, "missing_upstream_cost"
    if direct is not None and (not isinstance(direct, (int, float)) or isinstance(direct, bool)
                               or not math.isfinite(float(direct)) or direct < 0):
        return None, "invalid_openrouter_cost"
    return max(nums), "upstream_and_openrouter" if direct is not None else "upstream"


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def live_account_route_preflight(management_key: str, manifest: dict, cap: float,
                                 jobs: list[dict], no_unsettled_attested: bool) -> dict:
    """Refresh endpoint/provider/pricing and reject insufficient OpenRouter balance.

    OpenRouter requires a management key for these read-only metadata endpoints.
    """
    if not no_unsettled_attested:
        raise StageError("Before dispatch, reconcile all prior/in-flight requests and pass --confirm-no-unsettled-requests")
    headers = {"Authorization": f"Bearer {management_key}", "Content-Type": "application/json"}
    endpoint_url = "https://openrouter.ai/api/v1/models/minimax/minimax-m3/endpoints"
    try:
        endpoint_response = requests.get(endpoint_url, headers=headers, timeout=(10, 30))
        credits_response = requests.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=(10, 30))
        endpoint_response.raise_for_status()
        credits_response.raise_for_status()
        endpoint_data = endpoint_response.json().get("data", {})
        endpoints = endpoint_data.get("endpoints", [])
        credit_data = credits_response.json().get("data", {})
    except Exception as error:
        raise StageError(f"Live OpenRouter account/route preflight failed closed: {type(error).__name__}: {error}") from error
    candidates = [endpoint for endpoint in endpoints if isinstance(endpoint, dict)
                  and str(endpoint.get("provider_name", "")).strip().casefold() == "minimax"]
    if not candidates:
        raise StageError("Live OpenRouter endpoint list has no MiniMax provider route")
    expected_endpoint_id = manifest.get("route_assumptions", {}).get("endpoint_model_id")
    exact = [endpoint for endpoint in candidates
             if endpoint.get("model_id") == expected_endpoint_id]
    if len(exact) != 1:
        raise StageError("Live MiniMax route is missing or ambiguous versus the frozen endpoint model ID")
    endpoint = exact[0]
    max_prompt_tokens = endpoint.get("max_prompt_tokens")
    max_completion_tokens = endpoint.get("max_completion_tokens")
    if (type(max_prompt_tokens) is not int or max_prompt_tokens <= 0
            or type(max_completion_tokens) is not int or max_completion_tokens <= 0):
        raise StageError("Live MiniMax endpoint lacks explicit prompt and completion limits; refusing dispatch")
    required_prompt = max(job["projected_provider_prompt_tokens"] for job in jobs)
    if required_prompt > max_prompt_tokens or OUTPUT_CAP > max_completion_tokens:
        raise StageError("Frozen Stage schedule exceeds live MiniMax prompt/completion limits")
    pricing = endpoint.get("pricing")
    if not isinstance(pricing, dict):
        raise StageError("Live MiniMax route omitted pricing")
    try:
        input_rate = float(pricing["prompt"])
        output_rate = float(pricing["completion"])
    except (KeyError, TypeError, ValueError) as error:
        raise StageError("Live MiniMax route pricing is malformed") from error
    if not (math.isfinite(input_rate) and math.isfinite(output_rate) and input_rate > 0 and output_rate > 0):
        raise StageError("Live MiniMax route pricing is invalid")
    credits = credit_data.get("total_credits")
    usage = credit_data.get("total_usage")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
           or value < 0 for value in (credits, usage)):
        raise StageError("OpenRouter account preflight did not return finite credit and usage totals")
    available = float(credits) - float(usage)
    if available < cap:
        raise StageError(f"OpenRouter account available credits ${available:.6f} are below approved cap ${cap:.6f}")
    return {"checked_utc": datetime.now(timezone.utc).isoformat(),
            "endpoint_model_id": endpoint.get("model_id"), "provider": endpoint.get("provider_name"),
            "input_usd_per_million": input_rate * 1_000_000,
            "output_usd_per_million": output_rate * 1_000_000,
            "max_prompt_tokens": max_prompt_tokens,
            "max_completion_tokens": max_completion_tokens,
            "available_openrouter_credits_usd": available,
            "prior_in_flight_reconciliation": "explicit operator attestation; API does not prove all upstream settlements",
            "note": "Live endpoint/credit metadata; BYOK upstream invoices may settle separately."}


def prepare_report(manifest_path: Path, manifest: dict, mode: str, jobs: list[dict], output: Path) -> dict:
    input_tokens = sum(job["local_prompt_tokens"] for job in jobs)
    estimated = (input_tokens * INPUT_FACTOR * INPUT_PRICE + len(jobs) * OUTPUT_CAP * OUTPUT_PRICE) / 1_000_000
    schedule = [{"index": index, "case_id": job["case_id"], "arm": job["arm"], "repeat": job["repeat"],
                 "seed": job["seed"], "prompt_sha256": job["prompt_sha256"],
                 "body_sha256": job["body_sha256"],
                 "domain": job["domain"], "sub_domain": job["sub_domain"],
                 "local_prompt_tokens": job["local_prompt_tokens"],
                 "local_cost_estimate_usd": job["local_cost_estimate_usd"],
                 "projected_provider_prompt_tokens": job["projected_provider_prompt_tokens"]}
                for index, job in enumerate(jobs)]
    source_hashes = manifest["source_hashes"]
    frozen_runner_hash = source_hashes.get("runner")
    report = {
        "schema_version": 1, "status": "prepared_only_no_dispatch", "actual_dispatch_started": False,
        "dispatch_authorized_by_manifest": False,
        "evidence_class": manifest.get("evidence_class", "reviewed_primary_344_cohort"),
        "manifest_sha256": file_sha256(manifest_path),
        "parent_manifest_sha256": manifest.get("parent_manifest_sha256"),
        "historical_sample_manifest_sha256": manifest.get("historical_sample_manifest_sha256"),
        "execution_runner_sha256": file_sha256(Path(__file__).resolve()),
        "frozen_source_runner_sha256": frozen_runner_hash,
        "runner_hash_semantics": "frozen_source_runner_sha256 records the legacy runner used when the parent cohort was prepared; execution_runner_sha256 records this adapter. They are not interchangeable.",
        "prepared_utc": datetime.now(timezone.utc).isoformat(),
        "cohort": mode, "planned_jobs": len(jobs),
        "arm_counts": {"full": len(jobs) // 2, "sift": len(jobs) // 2},
        "source_hashes": source_hashes,
        "protocol": manifest["protocol"], "schedule": schedule,
        "schedule_sha256": canonical_hash(schedule),
        "budget_estimate": {"local_input_tokens": input_tokens, "input_reserve_factor": INPUT_FACTOR,
                            "dated_input_usd_per_million": INPUT_PRICE,
                            "dated_output_usd_per_million": OUTPUT_PRICE,
                            "max_output_tokens": len(jobs) * OUTPUT_CAP,
                            "estimated_reserve_usd": estimated,
                            "is_live_quote_or_authorization": False},
        "request_and_answer_text_excluded": True,
    }
    return report


def dispatch(jobs: list[dict], cases: dict, report: dict, output: Path,
             cap: float, api_key: str, live_route: dict) -> dict:
    input_price = live_route["input_usd_per_million"]
    output_price = live_route["output_usd_per_million"]
    if input_price != INPUT_PRICE or output_price != OUTPUT_PRICE:
        raise StageError("Live price differs from frozen reserve rates; prepare a refreshed reviewed plan before dispatch")
    estimate = report["budget_estimate"]["estimated_reserve_usd"]
    if not math.isfinite(cap) or cap <= 0 or cap < estimate:
        raise StageError(f"Approved cap must be finite, positive, and at least the refreshed estimate ${estimate:.6f}")
    # No automatic retry/resume: an ambiguous request is written as in-flight and blocks later runs.
    report["status"] = "dispatching"
    report["actual_dispatch_started"] = True
    report["dispatch_spend_cap_usd"] = cap
    report["dispatch_started_utc"] = datetime.now(timezone.utc).isoformat()
    report["samples"] = []
    report["in_flight"] = None
    atomic_write(output, report)
    settled = 0.0
    started = time.perf_counter()
    for index, job in enumerate(jobs):
        reserve = (job["local_prompt_tokens"] * INPUT_FACTOR * input_price + OUTPUT_CAP * output_price) / 1_000_000
        if settled + reserve > cap:
            report["status"] = "budget_guard_stopped_before_request"
            report["stop_reason"] = "next_request_reservation_exceeds_approved_cap"
            break
        report["in_flight"] = {"index": index, "job_id": f'{job["case_id"]}:{job["arm"]}:{job["repeat"]}',
                               "reserved_cost_usd": reserve, "state": "request_started"}
        atomic_write(output, report)
        started_utc = datetime.now(timezone.utc).isoformat()
        request_started = time.perf_counter()
        first_content_at = None
        raw_events: list[str] = []
        fragments: list[str] = []
        usage = None
        returned_model = provider = response_id = finish_reason = None
        status = None
        failure = None
        try:
            with requests.post(API_URL, json=job["body"],
                               headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                               stream=True, timeout=(30, 600)) as response:
                status = response.status_code
                if status != 200:
                    raw_events.append(response.text)
                    failure = "http_status_not_200"
                else:
                    for line in response.iter_lines(decode_unicode=True):
                        if not line or not line.startswith("data:"):
                            continue
                        event = line[5:].strip()
                        raw_events.append(event)
                        if event == "[DONE]":
                            break
                        chunk = json.loads(event)
                        usage = chunk.get("usage") if chunk.get("usage") is not None else usage
                        provider = chunk.get("provider") or provider
                        returned_model = chunk.get("model") or returned_model
                        response_id = chunk.get("id") or response_id
                        for choice in chunk.get("choices", []):
                            if choice.get("finish_reason") is not None:
                                finish_reason = choice["finish_reason"]
                            delta = choice.get("delta") or {}
                            if isinstance(delta.get("content"), str):
                                if delta["content"] and first_content_at is None:
                                    first_content_at = time.perf_counter()
                                fragments.append(delta["content"])
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
        text = "".join(fragments)
        request_finished = time.perf_counter()
        actual, receipt_source = cost_receipt(usage)
        ratio = None
        if isinstance(usage, dict) and type(usage.get("prompt_tokens")) is int and usage["prompt_tokens"] > 0:
            ratio = usage["prompt_tokens"] / job["local_prompt_tokens"]
        choice = text.strip()
        successful_response = (
            status == 200 and returned_model == MODEL and isinstance(provider, str)
            and provider.strip().casefold() == "minimax" and finish_reason == "stop"
            and failure is None
        )
        sample = {
            "job_id": f'{job["case_id"]}:{job["arm"]}:{job["repeat"]}',
            "case_id": job["case_id"], "arm": job["arm"], "repeat": job["repeat"],
            "domain": job["domain"], "sub_domain": job["sub_domain"],
            "request_body_sha256": job["body_sha256"], "http_status": status,
            "requested_model": MODEL, "returned_model": returned_model, "provider": provider,
            "response_id": response_id, "usage": usage,
            "local_cost_estimate_usd": job["local_cost_estimate_usd"],
            "provider_reported_cost_usd": actual,
            "cost_receipt_source": receipt_source, "local_prompt_tokens": job["local_prompt_tokens"],
            "provider_local_input_ratio": ratio, "answer": text, "choice": choice if choice in "ABCD" and len(choice) == 1 else None,
            "expected": job["expected"],
            "correct": successful_response and choice == job["expected"]
            if choice in "ABCD" and len(choice) == 1 else False,
            "finish_reason": finish_reason, "failure": failure, "raw_sse_events": raw_events,
            "request_started_utc": started_utc, "response_completed_utc": datetime.now(timezone.utc).isoformat(),
            "ttft_ms": (first_content_at - request_started) * 1000 if first_content_at is not None else None,
            "total_request_wall_ms": (request_finished - request_started) * 1000,
        }
        report["samples"].append(sample)
        report["in_flight"] = None
        if actual is None:
            report["status"] = "safety_guard_stopped"
            report["stop_reason"] = f"missing_or_invalid_cost_receipt:{receipt_source}"
            report["in_flight"] = {
                "index": index, "job_id": sample["job_id"], "reserved_cost_usd": reserve,
                "state": "unknown_outcome_requires_external_reconciliation",
                "response_id": response_id,
            }
        else:
            settled += actual
            report["settled_actual_cost_usd"] = settled
            valid_route = status == 200 and returned_model == MODEL and isinstance(provider, str) and provider.casefold() == "minimax"
            if not valid_route:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "model_or_provider_attribution_mismatch"
            elif ratio is None:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "missing_provider_prompt_usage"
            elif ratio > MAX_RATIO:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "provider_local_input_ratio_exceeded"
            elif settled > cap:
                report["status"] = "budget_guard_overrun"
                report["stop_reason"] = "actual_reported_cost_exceeded_cap"
            elif failure is not None or finish_reason != "stop":
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "request_failed_or_incomplete"
        atomic_write(output, report)
        if report.get("status") in {"safety_guard_stopped", "budget_guard_overrun"}:
            # Request was sequential; its response/usage is settled before stopping. Never resume automatically.
            break
    else:
        report["status"] = "complete"
    if report.get("status") == "complete":
        report["in_flight"] = None
    report["completed_jobs"] = len(report["samples"])
    report["elapsed_wall_seconds"] = time.perf_counter() - started
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_write(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST,
                        help="Frozen Stage 1 100-task manifest or reviewed primary 344-task manifest.")
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--prepare-only", action="store_true", help="Explicitly prepare offline; this is also the default mode.")
    parser.add_argument("--dispatch", action="store_true", help="Explicitly send paid MiniMax requests.")
    parser.add_argument("--spend-cap-usd", type=float, help="User-approved aggregate cap for this run; required with --dispatch.")
    parser.add_argument("--confirm-no-unsettled-requests", action="store_true",
                        help="Attest that prior and in-flight requests from earlier runs have been reconciled before dispatch.")
    args = parser.parse_args()
    if args.dispatch != (args.spend_cap_usd is not None):
        raise StageError("Use --dispatch and --spend-cap-usd together; otherwise run offline")
    if args.confirm_no_unsettled_requests and not args.dispatch:
        raise StageError("--confirm-no-unsettled-requests is valid only with --dispatch")
    prior_report = None
    if args.output.exists():
        if not args.dispatch:
            raise StageError(f"Refusing to overwrite existing run artifact: {args.output}")
        try:
            prior_report = json.loads(args.output.read_text(encoding="utf-8"))
        except Exception as error:
            raise StageError(f"Existing run artifact is unreadable; reconcile it first: {error}") from error
        if (prior_report.get("status") != "prepared_only_no_dispatch"
                or prior_report.get("actual_dispatch_started") is not False):
            raise StageError(f"Refusing to continue or overwrite an existing dispatch; reconcile in-flight requests first: {args.output}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    mode, _ = verify_provenance(manifest, args.manifest, args.dataset, args.tokenizer, args.template)
    jobs, cases = build_jobs(manifest, mode, args.dataset, args.tokenizer)
    report = prepare_report(args.manifest, manifest, mode, jobs, args.output)
    if prior_report is not None:
        if (prior_report.get("manifest_sha256") != report.get("manifest_sha256")
                or prior_report.get("schedule") != report.get("schedule")
                or prior_report.get("execution_runner_sha256") != report.get("execution_runner_sha256")):
            raise StageError("Existing prepared artifact differs from reconstructed manifest/schedule/runner")
    if not args.dispatch:
        atomic_write(args.output, report)
        print(json.dumps({"status": report["status"], "cohort": mode, "planned_jobs": len(jobs),
                          "estimated_reserve_usd": report["budget_estimate"]["estimated_reserve_usd"],
                          "output": str(args.output)}, indent=2))
        return 0
    estimate = report["budget_estimate"]["estimated_reserve_usd"]
    if args.spend_cap_usd < estimate:
        report["status"] = "not_started_estimated_budget_exceeded"
        report["stop_reason"] = "cap_below_preflight_estimate"
        atomic_write(args.output, report)
        raise StageError(f"No requests sent: cap ${args.spend_cap_usd:.6f} < estimate ${estimate:.6f}")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise StageError("OPENROUTER_API_KEY is required for dispatch")
    management_key = os.environ.get("OPENROUTER_MANAGEMENT_KEY")
    if not management_key:
        raise StageError("OPENROUTER_MANAGEMENT_KEY is required for live endpoint and credits preflight")
    live_route = live_account_route_preflight(management_key, manifest, args.spend_cap_usd,
                                              jobs, args.confirm_no_unsettled_requests)
    # Live route metadata must match the dated reserve before any paid request.
    report["live_route_validation"] = live_route
    result = dispatch(jobs, cases, report, args.output, args.spend_cap_usd, api_key, live_route)
    print(json.dumps({"status": result["status"], "completed_jobs": result["completed_jobs"],
                      "actual_cost_usd": result.get("settled_actual_cost_usd"), "output": str(args.output)}, indent=2))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StageError as error:
        raise SystemExit(f"Stage 1 stopped: {error}")
