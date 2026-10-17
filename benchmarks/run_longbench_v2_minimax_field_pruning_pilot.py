"""Prepare or explicitly dispatch a frozen 4-case MiniMax field-pruning pilot.

Preparation is offline and writes a no-dispatch artifact containing every exact
request body. Dispatch is a separate explicit mode, requires that artifact,
checks the route live and refreshes the supplied spend ledger immediately
before the first request. No retries or candidate fallbacks are permitted.
"""
from __future__ import annotations

import argparse
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

import run_longbench_v2_minimax as baseline  # noqa: E402
import run_longbench_v2_minimax_relation_followup_v3 as v3  # noqa: E402
from prepare_longbench_v2 import DATASET_REVISION, DATASET_SHA256, file_sha256, iter_json_array, make_messages  # noqa: E402
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from sift import CompactionError, compact_messages  # noqa: E402

MODEL = "minimax/minimax-m3"
PILOT_VERSION = "field-pruning-openrouter-minimax-v1"
CASE_IDS = (
    "66f2b5ec821e116aacb2b1ec",
    "6719b96abb02136c067d4358",
    "671b080abb02136c067d4dde",
    "671b3cabbb02136c067d5252",
)
ARMS = ("full", "default", "field_pruning")
REPEATS = (1, 2, 3)
TARGET = 32_768
SAFETY_MARGIN = 128
EFFECTIVE_TARGET = TARGET - SAFETY_MARGIN
OUTPUT_TOKENS = 128
MAX_WORKERS = 1
MAX_REQUESTS = 36
MAX_RUN_USD = 4.0
AGGREGATE_LIMIT_USD = 20.0
PROJECTION_FACTOR = 3.25
PROVIDER_LIMIT = 524_288
MAX_ROUTE_AGE_SECONDS = 30 * 60
API_URL = "https://openrouter.ai/api/v1/chat/completions"
ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/minimax/minimax-m3/endpoints"
RESPONSE_FORMAT = {"type": "json_object"}
BASELINE_MANIFEST = ROOT / "docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json"
OFFLINE_AUDIT_SCRIPT = ROOT / "benchmarks/audit_longbench_v2_field_pruning.py"


class PilotError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def _json_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [dict(m) for m in messages]
    users = [i for i, m in enumerate(result) if m.get("role") == "user"]
    if not users or not isinstance(result[users[-1]].get("content"), str):
        raise PilotError("Expected a plain-text final user message")
    index = users[-1]
    result[index]["content"] += (
        "\n\nReturn a JSON object with exactly one key, `answer`, whose value is "
        "exactly one uppercase option letter: A, B, C, or D. Do not include an explanation."
    )
    return result


def _request_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": MODEL,
        "messages": job["messages"],
        "temperature": 0.1,
        "top_p": 0.8,
        "seed": job["generation_seed"],
        "max_tokens": OUTPUT_TOKENS,
        "reasoning": {"enabled": False},
        "response_format": RESPONSE_FORMAT,
        "stream": True,
        "stream_options": {"include_usage": True},
        "provider": {"only": ["minimax"], "allow_fallbacks": False},
    }


def _source_hashes(dataset: Path, tokenizer: Path, template: Path, gate: Path) -> dict[str, str]:
    paths = {
        "runner": Path(__file__).resolve(),
        "analyzer": ROOT / "benchmarks/analyze_longbench_v2_minimax_field_pruning_pilot.py",
        "core": ROOT / "src/sift/core.py",
        "baseline_runner": ROOT / "benchmarks/run_longbench_v2_minimax.py",
        "v3_transport": ROOT / "benchmarks/run_longbench_v2_minimax_relation_followup_v3.py",
        "dataset_preparer": ROOT / "benchmarks/prepare_longbench_v2.py",
        "renderer": ROOT / "benchmarks/prepare_longbench_v2_minimax.py",
        "baseline_manifest": BASELINE_MANIFEST,
        "offline_audit_script": OFFLINE_AUDIT_SCRIPT,
        "dataset": dataset,
        "tokenizer": tokenizer,
        "template": template,
        "offline_gate": gate,
    }
    return {key: file_sha256(path) for key, path in paths.items()}


def _validate_gate(path: Path, expected_hashes: dict[str, str]) -> dict[str, Any]:
    gate = json.loads(path.read_text(encoding="utf-8-sig"))
    if (gate.get("status") != "passed" or gate.get("audit_kind") != "offline_field_pruning_prototype_gate"
            or gate.get("network_calls") != 0 or gate.get("default_behavior_changed") is not False
            or gate.get("dataset_sha256") != DATASET_SHA256
            or gate.get("core_sha256") != expected_hashes["core"]):
        raise PilotError("Offline field-pruning gate is missing, stale, or not passed")
    if (gate.get("audit_script_sha256") != expected_hashes["offline_audit_script"]
            or gate.get("template_source_sha256") != expected_hashes["renderer"]):
        raise PilotError("Offline gate script or MiniMax rendering source changed after its audit")
    cases = gate.get("cases")
    if not isinstance(cases, list) or [c.get("id") for c in cases] != list(CASE_IDS):
        raise PilotError("Offline gate does not cover the four frozen pilot cases in order")
    if any(c.get("within_target") is not True or c.get("within_10_percent_growth") is not True
           or c.get("source_messages_unchanged") is not True for c in cases):
        raise PilotError("Offline field-pruning gate no longer satisfies its retention/size gates")
    return gate


def _validate_frozen_tokenizer_template(tokenizer_path: Path, template_path: Path) -> None:
    manifest = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8-sig"))
    model = manifest.get("model", {})
    if file_sha256(tokenizer_path) != model.get("tokenizer_sha256"):
        raise PilotError("MiniMax tokenizer differs from the frozen baseline manifest")
    if file_sha256(template_path) != model.get("chat_template_sha256"):
        raise PilotError("MiniMax chat template differs from the frozen baseline manifest")


def _load_data(dataset: Path) -> dict[str, dict[str, Any]]:
    if file_sha256(dataset) != DATASET_SHA256:
        raise PilotError("Pinned LongBench dataset SHA-256 mismatch")
    found = {}
    for row in iter_json_array(dataset):
        if row.get("_id") in CASE_IDS:
            found[row["_id"]] = row
    if set(found) != set(CASE_IDS):
        raise PilotError("Pinned LongBench data is missing one or more pilot IDs")
    return found


def _seed(cli_seed: int, case_id: str, repeat: int) -> int:
    # Arms within a task/repeat receive the same deterministic seed.
    digest = hashlib.sha256(f"{cli_seed}:{case_id}:{repeat}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def prepare(*, dataset: Path, tokenizer_path: Path, template_path: Path, gate_path: Path,
            cli_seed: int = 20261023) -> dict[str, Any]:
    hashes = _source_hashes(dataset, tokenizer_path, template_path, gate_path)
    gate = _validate_gate(gate_path, hashes)
    _validate_frozen_tokenizer_template(tokenizer_path, template_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    count_tokens = lambda messages: len(tokenizer.encode(
        render_minimax(messages), add_special_tokens=False).ids)
    data = _load_data(dataset)
    rng = random.Random(cli_seed)
    jobs: list[dict[str, Any]] = []
    for case_id in CASE_IDS:
        row = data[case_id]
        base_messages = _json_prompt(make_messages(row))
        if str(row.get("answer", "")).strip().upper() not in set("ABCD"):
            raise PilotError(f"Invalid expected choice in {case_id}")
        for repeat in REPEATS:
            seed = _seed(cli_seed, case_id, repeat)
            arm_order = list(ARMS)
            rng.shuffle(arm_order)
            compacted: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
            for arm in ARMS:
                started = time.perf_counter()
                if arm == "full":
                    messages = [dict(m) for m in base_messages]
                    audit = {"method": "full_context", "forwarded_tokens": count_tokens(messages)}
                else:
                    try:
                        result = compact_messages(
                            base_messages, count_tokens, target=EFFECTIVE_TARGET,
                            raw_limit=1_000_000, protocol="openai",
                            field_pruning=(arm == "field_pruning"),
                        )
                    except CompactionError as error:
                        raise PilotError(f"{arm} preparation failed for {case_id}: {error}") from error
                    messages, audit = result.messages, result.audit
                    if arm == "field_pruning" and audit.get("method") != "field_pruning_candidate":
                        raise PilotError(f"Candidate silently fell back for {case_id}")
                    if audit.get("fallback") or audit.get("fallback_reason"):
                        raise PilotError(f"Unexpected fallback for {arm}/{case_id}")
                local = count_tokens(messages)
                if arm != "full" and local > EFFECTIVE_TARGET:
                    raise PilotError(f"{arm} exceeded effective Sift target for {case_id}")
                projected = math.ceil(local * PROJECTION_FACTOR) + OUTPUT_TOKENS
                if projected > PROVIDER_LIMIT:
                    raise PilotError(f"Projected endpoint prompt limit exceeded by {arm}/{case_id}")
                compacted[arm] = (messages, {
                    "audit": audit,
                    "local_rendered_prompt_tokens": local,
                    "projected_provider_prompt_tokens": projected,
                    "preparation_ms": (time.perf_counter() - started) * 1000,
                })
            for order, arm in enumerate(arm_order):
                messages, meta = compacted[arm]
                job_id = f"{case_id}:r{repeat}:{arm}"
                job = {
                    "job_id": job_id, "case_id": case_id, "repeat": repeat,
                    "arm": arm, "arm_order_in_block": order,
                    "expected": str(row["answer"]).strip().upper(),
                    "generation_seed": seed, "messages": messages,
                    **meta,
                }
                payload = _request_payload(job)
                job["request_payload"] = payload
                job["request_payload_sha256"] = canonical_hash(payload)
                jobs.append(job)
    if len(jobs) != MAX_REQUESTS or len({j["job_id"] for j in jobs}) != MAX_REQUESTS:
        raise PilotError("Prepared job set is not exactly 36 unique requests")
    # Validate the within-block randomization and paired seed invariants.
    for case_id in CASE_IDS:
        for repeat in REPEATS:
            block = [j for j in jobs if j["case_id"] == case_id and j["repeat"] == repeat]
            if [j["arm"] for j in sorted(block, key=lambda x: x["arm_order_in_block"])] not in [
                    list(p) for p in __import__("itertools").permutations(ARMS)]:
                raise PilotError("Arm order block is not a permutation")
            if len({j["generation_seed"] for j in block}) != 1:
                raise PilotError("Generation seeds are not paired within a task-repeat block")
    requests = [{"job_id": j["job_id"], "request": j["request_payload"],
                 "request_sha256": j["request_payload_sha256"]} for j in jobs]
    config = {
        "pilot_version": PILOT_VERSION,
        "model": MODEL, "task_ids": list(CASE_IDS), "repeats": list(REPEATS),
        "arms": list(ARMS), "temperature": 0.1, "top_p": 0.8,
        "reasoning_enabled": False, "max_tokens": OUTPUT_TOKENS,
        "response_format": RESPONSE_FORMAT, "retries": 0, "workers": MAX_WORKERS,
        "target_tokens": TARGET, "effective_target_tokens": EFFECTIVE_TARGET,
        "projection_factor": PROJECTION_FACTOR, "endpoint_prompt_limit": PROVIDER_LIMIT,
        "provider_policy": {"only": ["minimax"], "allow_fallbacks": False},
        "generation_seed_formula": "sha256(cli_seed:case_id:repeat)[0:4] big-endian; shared across arms",
        "randomization": "seeded random permutation of three arms within each task-repeat block",
        "cli_seed": cli_seed,
    }
    reserve_per_job = max(
        ((j["local_rendered_prompt_tokens"] * 1.5 * 0.30 + OUTPUT_TOKENS * 1.20) / 1_000_000)
        for j in jobs
    )
    budget = {
        "status": "planning_estimate_only_no_dispatch",
        "run_limit_usd": MAX_RUN_USD, "aggregate_limit_usd": AGGREGATE_LIMIT_USD,
        "reserve_formula": "1.5 * local_input_tokens * input_price + max_output_tokens * output_price",
        "planning_input_price_usd_per_million": 0.30,
        "planning_output_price_usd_per_million": 1.20,
        "max_single_job_reserve_usd": reserve_per_job,
        "planned_reserve_usd": sum(
            (j["local_rendered_prompt_tokens"] * 1.5 * 0.30 + OUTPUT_TOKENS * 1.20) / 1_000_000
            for j in jobs),
        "note": "Planning only. Dispatch must fetch live endpoint metadata and require a fresh spend ledger; these prices do not authorize spend.",
    }
    frozen_job_metadata = [
        {k: v for k, v in j.items() if k not in {"messages", "request_payload"}}
        for j in jobs
    ]
    return {
        "schema_version": 1,
        "status": "prepared_only_no_dispatch",
        "dry_run": True,
        "actual_dispatch_started": False,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "model": MODEL,
        "pilot_version": PILOT_VERSION,
        "config": config,
        "config_sha256": canonical_hash(config),
        "source_hashes": hashes,
        "source_paths": {
            "dataset": str(dataset.resolve()), "tokenizer": str(tokenizer_path.resolve()),
            "template": str(template_path.resolve()), "offline_gate": str(gate_path.resolve()),
        },
        "offline_gate_audit_body_sha256": gate.get("audit_body_sha256"),
        "budget": budget,
        "preparation": {
            "job_count": len(jobs), "candidate_errors": 0,
            "max_projected_prompt_tokens": max(j["projected_provider_prompt_tokens"] for j in jobs),
            "projected_limit": PROVIDER_LIMIT,
        },
        "prepared_jobs": frozen_job_metadata,
        "prepared_jobs_sha256": canonical_hash(frozen_job_metadata),
        "prepared_requests": requests,
        "samples": [],
    }


def verify_preflight(artifact_path: Path, *, expected_source_hashes: dict[str, str] | None = None) -> dict[str, Any]:
    artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
    if (artifact.get("status") != "prepared_only_no_dispatch" or artifact.get("dry_run") is not True
            or artifact.get("actual_dispatch_started") is not False or artifact.get("samples") != []):
        raise PilotError("Preflight is not an untouched no-dispatch artifact")
    if expected_source_hashes is not None and artifact.get("source_hashes") != expected_source_hashes:
        raise PilotError("Preflight source/config provenance differs from current checkout")
    paths = artifact.get("source_paths")
    if not isinstance(paths, dict):
        raise PilotError("Preflight does not record source paths for dispatch-time hash verification")
    current = _source_hashes(
        Path(paths["dataset"]), Path(paths["tokenizer"]), Path(paths["template"]),
        Path(paths["offline_gate"]),
    )
    if artifact.get("source_hashes") != current:
        raise PilotError("A frozen source/config input changed after preparation")
    config = artifact.get("config")
    if not isinstance(config, dict) or canonical_hash(config) != artifact.get("config_sha256"):
        raise PilotError("Preflight config hash mismatch")
    records = artifact.get("prepared_requests")
    if not isinstance(records, list) or len(records) != MAX_REQUESTS:
        raise PilotError("Preflight must freeze exactly 36 request bodies")
    ids = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("request"), dict):
            raise PilotError("Malformed frozen request record")
        job_id, request, digest = record.get("job_id"), record["request"], record.get("request_sha256")
        if job_id in ids or digest != canonical_hash(request):
            raise PilotError("Duplicate job ID or exact request hash mismatch")
        ids.add(job_id)
        if (request.get("model") != MODEL or request.get("provider") != {"only": ["minimax"], "allow_fallbacks": False}
                or request.get("stream") is not True or request.get("max_tokens") != OUTPUT_TOKENS):
            raise PilotError("Frozen request does not satisfy route/output invariants")
    # Regenerate from the pinned dataset, tokenizer, gate and current source
    # before dispatch. This binds answer labels and reserve metadata to the
    # same task/arm/seed/messages as the frozen request records.
    expected = prepare(
        dataset=Path(paths["dataset"]), tokenizer_path=Path(paths["tokenizer"]),
        template_path=Path(paths["template"]), gate_path=Path(paths["offline_gate"]),
        cli_seed=config.get("cli_seed"),
    )
    for field in ("config", "config_sha256", "source_hashes", "prepared_requests",
                  "offline_gate_audit_body_sha256"):
        if artifact.get(field) != expected.get(field):
            raise PilotError(f"Preflight {field} differs from regenerated frozen preparation")
    artifact_jobs = artifact.get("prepared_jobs")
    expected_jobs = expected.get("prepared_jobs")
    if not isinstance(artifact_jobs, list) or len(artifact_jobs) != MAX_REQUESTS:
        raise PilotError("Preflight must freeze metadata for all 36 jobs")
    if artifact.get("prepared_jobs_sha256") != canonical_hash(artifact_jobs):
        raise PilotError("Preflight prepared_jobs metadata digest mismatch")
    bound_fields = ("job_id", "case_id", "repeat", "arm", "arm_order_in_block",
                    "expected", "generation_seed", "local_rendered_prompt_tokens",
                    "projected_provider_prompt_tokens")
    actual_by_id = {job.get("job_id"): job for job in artifact_jobs if isinstance(job, dict)}
    expected_by_id = {job["job_id"]: job for job in expected_jobs}
    if set(actual_by_id) != set(expected_by_id):
        raise PilotError("Preflight job metadata does not match regenerated job identities")
    for job_id, expected_job in expected_by_id.items():
        if any(actual_by_id[job_id].get(field) != expected_job.get(field) for field in bound_fields):
            raise PilotError(f"Preflight scoring or reserve metadata changed for {job_id}")
    return artifact


def _live_endpoint(api_key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    response = requests.get(ENDPOINTS_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=(15, 30))
    response.raise_for_status()
    raw = response.json()
    data = raw.get("data", raw) if isinstance(raw, dict) else None
    endpoints = data.get("endpoints") if isinstance(data, dict) else None
    matches = [e for e in endpoints or [] if isinstance(e, dict)
               and e.get("model_id") == MODEL
               and str(e.get("provider_name", "")).strip().casefold() == "minimax"]
    if len(matches) != 1:
        raise PilotError("Live route did not resolve to exactly one MiniMax endpoint")
    e = matches[0]
    if e.get("context_length") != PROVIDER_LIMIT or e.get("max_prompt_tokens") != PROVIDER_LIMIT:
        raise PilotError("Live MiniMax endpoint prompt limit differs from frozen 524,288")
    pricing = e.get("pricing")
    try:
        input_price, output_price = float(pricing["prompt"]) * 1_000_000, float(pricing["completion"]) * 1_000_000
    except (TypeError, KeyError, ValueError) as error:
        raise PilotError("Live route has invalid price metadata") from error
    if not all(math.isfinite(x) and x > 0 for x in (input_price, output_price)):
        raise PilotError("Live route rates must be positive finite values")
    return raw, {"endpoint_name": e.get("name"), "input_usd_per_million": input_price,
                 "output_usd_per_million": output_price, "context_length": e["context_length"],
                 "max_prompt_tokens": e["max_prompt_tokens"], "checked_utc": datetime.now(timezone.utc).isoformat()}


def _load_budget_ledger(path: Path) -> dict[str, float]:
    ledger = json.loads(path.read_text(encoding="utf-8-sig"))
    checked = ledger.get("checked_utc")
    try:
        dt = datetime.fromisoformat(checked.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise PilotError("Spend ledger must include a timezone-aware checked_utc") from error
    age = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
    if dt.tzinfo is None or age < -60 or age > MAX_ROUTE_AGE_SECONDS:
        raise PilotError("Spend ledger must be refreshed within 30 minutes immediately before dispatch")
    actual, unsettled = ledger.get("actual_usd"), ledger.get("unsettled_usd")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
           for v in (actual, unsettled)):
        raise PilotError("Spend ledger actual/unsettled values must be finite nonnegative numbers")
    return {"actual_usd": float(actual), "unsettled_usd": float(unsettled),
            "checked_utc": dt.astimezone(timezone.utc).isoformat()}


def _budget_projection(*, prior_actual: float, prior_unsettled: float,
                       actual_run_cost: float, remaining_reserves: list[float]) -> dict[str, float | bool]:
    """Check both caps after reserving every request that has not yet been sent."""
    reserve = sum(remaining_reserves)
    run_projected = actual_run_cost + reserve
    aggregate_projected = prior_actual + prior_unsettled + run_projected
    return {
        "remaining_reserve_usd": reserve,
        "run_projected_usd": run_projected,
        "aggregate_projected_usd": aggregate_projected,
        "run_passed": run_projected <= MAX_RUN_USD,
        "aggregate_passed": aggregate_projected <= AGGREGATE_LIMIT_USD,
    }


def _sse_answer(events: list[str]) -> str | None:
    text = ""
    done = False
    for raw in events:
        if raw == "[DONE]":
            done = True
            break
        try:
            event = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        for choice in event.get("choices", []) if isinstance(event, dict) else []:
            delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str):
                text += content
    if not done:
        return None
    try:
        obj = json.loads(text, object_pairs_hook=_unique_pairs)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    answer = obj.get("answer") if isinstance(obj, dict) and set(obj) == {"answer"} else None
    return answer if isinstance(answer, str) and len(answer) == 1 and answer in "ABCD" else None


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _call(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    started = time.perf_counter()
    start_utc = datetime.now(timezone.utc).isoformat()
    first = None
    raw_events: list[str] = []
    failure = None
    raw_error_body = None
    status = None
    response_meta: dict[str, Any] = {}
    try:
        with requests.post(API_URL, json=payload, headers={"Authorization": f"Bearer {api_key}"},
                           stream=True, timeout=(30, 600)) as response:
            status = response.status_code
            response_meta = {"model": response.headers.get("x-openrouter-model"),
                             "provider": response.headers.get("x-openrouter-provider"),
                             "response_id": response.headers.get("x-request-id")}
            if status == 200:
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    event_raw = line[5:].strip()
                    raw_events.append(event_raw)
                    if event_raw == "[DONE]":
                        break
                    try:
                        event = json.loads(event_raw)
                    except json.JSONDecodeError:
                        failure = "malformed_sse_json"
                        continue
                    response_meta["model"] = event.get("model") or response_meta.get("model")
                    response_meta["provider"] = event.get("provider") or response_meta.get("provider")
                    response_meta["response_id"] = event.get("id") or response_meta.get("response_id")
                    if event.get("usage") is not None:
                        response_meta["usage"] = event["usage"]
                    for choice in event.get("choices", []):
                        if choice.get("finish_reason") is not None:
                            response_meta["finish_reason"] = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        if isinstance(delta.get("content"), str) and delta["content"] and first is None:
                            first = time.perf_counter()
            else:
                raw_error_body = response.text
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
    ended = time.perf_counter()
    usage = response_meta.get("usage")
    return {
        "http_status": status, "failure": failure,
        "stream_complete": status == 200 and bool(raw_events) and raw_events[-1] == "[DONE]",
        "raw_error_body": raw_error_body,
        "model": response_meta.get("model"), "provider": response_meta.get("provider"),
        "response_id": response_meta.get("response_id"), "finish_reason": response_meta.get("finish_reason"),
        "usage": usage, "raw_sse_events": raw_events,
        "raw_response_body": "\n".join(raw_events), "request_started_utc": start_utc,
        "response_completed_utc": datetime.now(timezone.utc).isoformat(),
        "ttft_ms": (first - started) * 1000 if first else None,
        "end_to_end_ms": (ended - started) * 1000,
        "completion_tokens_per_second": (
            usage.get("completion_tokens") / (ended - first)
            if isinstance(usage, dict) and type(usage.get("completion_tokens")) is int and first and ended > first
            else None),
    }


def dispatch(*, preflight_path: Path, expected_preflight_sha256: str,
             output_path: Path, budget_ledger_path: Path) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite result: {output_path}")
    if (not isinstance(expected_preflight_sha256, str)
            or len(expected_preflight_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_preflight_sha256.lower())):
        raise PilotError("--expected-preflight-sha256 must be a 64-character SHA-256 digest")
    actual_preflight_sha256 = file_sha256(preflight_path)
    if actual_preflight_sha256.lower() != expected_preflight_sha256.lower():
        raise PilotError("Preflight file SHA-256 differs from --expected-preflight-sha256")
    artifact = verify_preflight(preflight_path)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise PilotError("OPENROUTER_API_KEY is required for explicit dispatch")
    # The endpoint and ledger are refreshed after preflight validation and just
    # before estimating exposure; the endpoint call is the only preflight network call.
    route_raw, route = _live_endpoint(api_key)
    ledger = _load_budget_ledger(budget_ledger_path)
    jobs = {j["job_id"]: j for j in artifact["prepared_jobs"]}
    prices = route
    reserves = {}
    for record in artifact["prepared_requests"]:
        job = jobs[record["job_id"]]
        reserve = (job["local_rendered_prompt_tokens"] * 1.5 * prices["input_usd_per_million"]
                   + OUTPUT_TOKENS * prices["output_usd_per_million"]) / 1_000_000
        reserves[record["job_id"]] = reserve
    total_reserve = sum(reserves.values())
    if total_reserve > MAX_RUN_USD or ledger["actual_usd"] + ledger["unsettled_usd"] + total_reserve > AGGREGATE_LIMIT_USD:
        raise PilotError("Fresh spend ledger plus conservative reserve exceeds pilot budget; no dispatch")
    report = {
        "schema_version": 1, "status": "in_progress", "actual_dispatch_started": False,
        "preflight_sha256": actual_preflight_sha256, "preflight": str(preflight_path.resolve()),
        "route_snapshot_sha256": sha256_bytes(json.dumps(route_raw, sort_keys=True).encode()),
        "route_snapshot": route_raw,
        "route": route, "budget_ledger": ledger,
        "budget": {"run_limit_usd": MAX_RUN_USD, "aggregate_limit_usd": AGGREGATE_LIMIT_USD,
                   "planned_reserve_usd": total_reserve, "actual_cost_usd": 0.0},
        "samples": [], "not_started_jobs": [], "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output_path, report)
    records = artifact["prepared_requests"]
    for index, record in enumerate(records):
        job_id = record["job_id"]
        request = record["request"]
        if canonical_hash(request) != record["request_sha256"]:
            raise PilotError("Frozen request body changed immediately before dispatch")
        before = _budget_projection(
            prior_actual=ledger["actual_usd"], prior_unsettled=ledger["unsettled_usd"],
            actual_run_cost=report["budget"]["actual_cost_usd"],
            remaining_reserves=[reserves[r["job_id"]] for r in records[index:]],
        )
        if not before["run_passed"]:
            report["not_started_jobs"] = [r["job_id"] for r in records
                                           if r["job_id"] not in {s["job_id"] for s in report["samples"]}]
            report["status"] = "budget_guard_stopped"
            break
        if not before["aggregate_passed"]:
            report["not_started_jobs"] = [r["job_id"] for r in records
                                           if r["job_id"] not in {s["job_id"] for s in report["samples"]}]
            report["status"] = "aggregate_budget_guard_stopped"
            break
        report["actual_dispatch_started"] = True
        result = _call(request, api_key)
        usage = result.get("usage")
        parsed = _sse_answer(result.get("raw_sse_events", []))
        job = jobs[job_id]
        usage_cost, cost_source = baseline.cost_receipt(usage)
        sample = {
            **result, "job_id": job_id, "case_id": job["case_id"], "repeat": job["repeat"],
            "arm": job["arm"], "expected": job["expected"], "choice": parsed,
            "correct": parsed == job["expected"], "request": request,
            "request_sha256": record["request_sha256"], "raw_sse_events": result["raw_sse_events"],
            "cost_receipt_status": "reported" if usage_cost is not None else "missing_or_invalid",
            "cost_receipt_source": cost_source, "cost_usd": usage_cost,
            "guard_reserve_usd": reserves[job_id], "local_rendered_prompt_tokens": job["local_rendered_prompt_tokens"],
            "preparation_ms": job["preparation_ms"],
        }
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        sample["provider_local_input_token_ratio"] = (
            prompt_tokens / job["local_rendered_prompt_tokens"]
            if type(prompt_tokens) is int and job["local_rendered_prompt_tokens"] else None)
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        sample["provider_prompt_tokens"] = prompt_tokens
        sample["provider_completion_tokens"] = completion_tokens
        sample["uncached_cost_rate_basis"] = {
            "input_usd_per_million": route["input_usd_per_million"],
            "output_usd_per_million": route["output_usd_per_million"],
        }
        token_receipt_reconciled = (
            type(prompt_tokens) is int and prompt_tokens > 0
            and type(completion_tokens) is int and completion_tokens >= 0
            and not v3.runtime_receipt_issues(usage)
        )
        sample["token_receipt_reconciled"] = token_receipt_reconciled
        sample["reconstructed_uncached_cost_usd"] = (
            (prompt_tokens * route["input_usd_per_million"]
             + completion_tokens * route["output_usd_per_million"]) / 1_000_000
            if token_receipt_reconciled else None
        )
        report["samples"].append(sample)
        report["budget"]["actual_cost_usd"] += usage_cost if usage_cost is not None else reserves[job_id]
        current_exposure = (ledger["actual_usd"] + ledger["unsettled_usd"]
                            + report["budget"]["actual_cost_usd"])
        report["budget"]["aggregate_exposure_usd"] = current_exposure
        remaining = [reserves[r["job_id"]] for r in records[index + 1:]]
        after = _budget_projection(
            prior_actual=ledger["actual_usd"], prior_unsettled=ledger["unsettled_usd"],
            actual_run_cost=report["budget"]["actual_cost_usd"], remaining_reserves=remaining,
        )
        report["budget"]["post_receipt_projection"] = after
        _atomic_write(output_path, report)
        # A transport, route, or accounting failure invalidates the strict run;
        # stop immediately and do not retry or fallback.
        if not after["run_passed"] or not after["aggregate_passed"]:
            report["status"] = (
                "budget_guard_stopped" if not after["run_passed"]
                else "aggregate_budget_guard_stopped"
            )
            report["not_started_jobs"] = [r["job_id"] for r in records[index + 1:]]
            break
        if (sample["http_status"] != 200 or sample["model"] != MODEL
                or str(sample["provider"] or "").casefold() != "minimax"
                or usage_cost is None or bool(v3.runtime_receipt_issues(usage))
                or sample.get("failure") is not None or sample.get("stream_complete") is not True
                or type(prompt_tokens) is not int or prompt_tokens <= 0
                or sample["provider_local_input_token_ratio"] is None
                or sample["provider_local_input_token_ratio"] > 1.05):
            report["status"] = "strict_gate_stopped"
            report["not_started_jobs"] = [r["job_id"] for r in records[index + 1:]]
            break
    else:
        report["status"] = "complete"
    report["arm_timings"] = _arm_timings(report["samples"])
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(output_path, report)
    return report


def _arm_timings(samples: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for arm in ARMS:
        rows = [row for row in samples if row.get("arm") == arm]
        prep = [row["preparation_ms"] for row in rows if isinstance(row.get("preparation_ms"), (int, float))]
        request = [row["end_to_end_ms"] for row in rows if isinstance(row.get("end_to_end_ms"), (int, float))]
        pipeline = [
            row["preparation_ms"] + row["end_to_end_ms"]
            for row in rows
            if isinstance(row.get("preparation_ms"), (int, float))
            and isinstance(row.get("end_to_end_ms"), (int, float))
        ]
        summary[arm] = {
            "requests": len(rows),
            "preprocessing_ms_total": sum(prep) if len(prep) == len(rows) else None,
            "preprocessing_ms_mean": sum(prep) / len(prep) if prep else None,
            "request_ms_total": sum(request) if len(request) == len(rows) else None,
            "request_ms_mean": sum(request) / len(request) if request else None,
            "preprocessing_plus_request_pipeline_ms_total": sum(pipeline) if len(pipeline) == len(rows) else None,
            "preprocessing_plus_request_pipeline_ms_mean": (
                sum(pipeline) / len(pipeline) if pipeline else None
            ),
        }
    return summary


def _atomic_write(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    prep = sub.add_parser("prepare", help="offline-only prepare and freeze exact requests")
    prep.add_argument("--dataset", type=Path, required=True)
    prep.add_argument("--tokenizer", type=Path, default=ROOT / "tmp/minimax-m3-tokenizer.json")
    prep.add_argument("--template", type=Path, default=ROOT / "tmp/minimax-m3-chat-template.jinja")
    prep.add_argument("--offline-gate", type=Path, required=True)
    prep.add_argument("--seed", type=int, default=20261023)
    prep.add_argument("--preflight-output", type=Path, required=True)
    run = sub.add_parser("dispatch", help="explicit live dispatch; refreshes route and spend ledger first")
    run.add_argument("--preflight", type=Path, required=True)
    run.add_argument("--expected-preflight-sha256", required=True,
                     help="Reviewed SHA-256 of the exact committed no-dispatch preflight file")
    run.add_argument("--budget-ledger", type=Path, required=True,
                     help="fresh JSON with checked_utc, actual_usd and unsettled_usd")
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        artifact = prepare(dataset=args.dataset, tokenizer_path=args.tokenizer,
                           template_path=args.template, gate_path=args.offline_gate, cli_seed=args.seed)
        _atomic_write(args.preflight_output, artifact)
        print(json.dumps({"status": artifact["status"], "requests": artifact["preparation"]["job_count"],
                          "max_projected_prompt_tokens": artifact["preparation"]["max_projected_prompt_tokens"],
                          "preflight": str(args.preflight_output)}, indent=2))
    else:
        result = dispatch(preflight_path=args.preflight,
                          expected_preflight_sha256=args.expected_preflight_sha256,
                          output_path=args.output,
                          budget_ledger_path=args.budget_ledger)
        print(json.dumps({"status": result["status"], "samples": len(result["samples"]),
                          "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
