"""Strict raw-SSE analyzer for the frozen 36-request field-pruning pilot."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from run_longbench_v2_minimax_field_pruning_pilot import ARMS, CASE_IDS, MAX_REQUESTS, REPEATS, MODEL, PILOT_VERSION, canonical_hash
from prepare_longbench_v2 import file_sha256
from run_longbench_v2_minimax import cost_receipt
from run_longbench_v2_minimax_relation_followup_v3 import runtime_receipt_issues
from run_longbench_v2_minimax_field_pruning_pilot import PROVIDER_LIMIT

TIMESTAMP_DURATION_TOLERANCE_MS = 100.0


class AnalysisError(ValueError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise AnalysisError(message)


def parse_raw_sse(events: Any) -> str | None:
    """Reconstruct only a complete, well-formed, single-key JSON A-D answer."""
    if not isinstance(events, list):
        return None
    text = ""
    done = False
    finish_reasons = []
    for raw in events:
        if not isinstance(raw, str):
            return None
        if raw == "[DONE]":
            done = True
            break
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict):
            return None
        choices = event.get("choices", [])
        if not isinstance(choices, list):
            return None
        for choice in choices:
            if not isinstance(choice, dict):
                return None
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                return None
            content = delta.get("content")
            if content is not None and not isinstance(content, str):
                return None
            if isinstance(content, str):
                text += content
            if choice.get("finish_reason") is not None:
                finish_reasons.append(choice.get("finish_reason"))
    if not done or finish_reasons != ["stop"]:
        return None

    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate key")
            out[key] = value
        return out

    try:
        obj = json.loads(text, object_pairs_hook=unique)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(obj, dict) or set(obj) != {"answer"}:
        return None
    answer = obj["answer"]
    return answer if isinstance(answer, str) and answer in {"A", "B", "C", "D"} else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def _raw_sse_usage(events: Any) -> dict[str, Any] | None:
    if not isinstance(events, list):
        return None
    found = []
    for raw in events:
        if raw == "[DONE]":
            break
        if not isinstance(raw, str):
            return None
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(event, dict):
            return None
        if "usage" in event:
            if not isinstance(event["usage"], dict):
                return None
            found.append(event["usage"])
    return found[0] if len(found) == 1 else None


def _close(a: Any, b: Any) -> bool:
    av, bv = _number(a), _number(b)
    return av is not None and bv is not None and math.isclose(av, bv, rel_tol=1e-10, abs_tol=1e-12)


def _verified_route(report: dict[str, Any]) -> tuple[dict[str, Any], float, float]:
    raw = report.get("route_snapshot")
    _require(isinstance(raw, dict), "Result is missing the raw public OpenRouter endpoint response")
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
    _require(report.get("route_snapshot_sha256") == digest,
             "Raw OpenRouter endpoint response does not match route_snapshot_sha256")
    data = raw.get("data", raw)
    _require(isinstance(data, dict), "Raw OpenRouter endpoint response has invalid data")
    endpoints = data.get("endpoints")
    _require(isinstance(endpoints, list), "Raw OpenRouter route response has no endpoint list")
    matches = [
        endpoint for endpoint in endpoints
        if isinstance(endpoint, dict)
        and endpoint.get("model_id") == MODEL
        and isinstance(endpoint.get("provider_name"), str)
        and endpoint["provider_name"].strip().casefold() == "minimax"
    ]
    _require(len(matches) == 1, "Raw OpenRouter response must identify exactly one MiniMax endpoint")
    endpoint = matches[0]
    context = endpoint.get("context_length")
    maximum = endpoint.get("max_prompt_tokens")
    _require(type(context) is int and context == PROVIDER_LIMIT
             and type(maximum) is int and maximum == PROVIDER_LIMIT,
             "Raw MiniMax endpoint limits differ from the frozen 524,288-token protocol")
    pricing = endpoint.get("pricing")
    _require(isinstance(pricing, dict), "Raw MiniMax endpoint is missing pricing")
    try:
        input_rate = float(pricing["prompt"]) * 1_000_000
        output_rate = float(pricing["completion"]) * 1_000_000
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise AnalysisError("Raw MiniMax endpoint rates are invalid") from error
    _require(math.isfinite(input_rate) and input_rate > 0
             and math.isfinite(output_rate) and output_rate > 0,
             "Raw MiniMax endpoint rates must be positive and finite")
    normalized = report.get("route")
    _require(isinstance(normalized, dict), "Result is missing its normalized live route record")
    _require(normalized.get("endpoint_name") == endpoint.get("name")
             and normalized.get("input_usd_per_million") == input_rate
             and normalized.get("output_usd_per_million") == output_rate
             and normalized.get("context_length") == context
             and normalized.get("max_prompt_tokens") == maximum
             and isinstance(normalized.get("checked_utc"), str),
             "Normalized live route fields do not reconcile to the raw OpenRouter response")
    return normalized, input_rate, output_rate


def _validate_run(report: dict[str, Any], preflight: dict[str, Any],
                  preflight_sha256: str) -> list[dict[str, Any]]:
    _require(report.get("status") == "complete", "Run is not complete; strict full-pilot scoring unavailable")
    _require(report.get("actual_dispatch_started") is True, "Run contains no confirmed dispatch")
    _require(report.get("preflight_sha256") == preflight_sha256,
             "Result is not bound to the supplied verified preflight artifact")
    _require(preflight.get("status") == "prepared_only_no_dispatch"
             and preflight.get("pilot_version") == PILOT_VERSION,
             "Supplied preflight has unexpected status or pilot version")
    prepared_jobs = preflight.get("prepared_jobs")
    request_records = preflight.get("prepared_requests")
    _require(isinstance(prepared_jobs, list) and len(prepared_jobs) == MAX_REQUESTS,
             "Verified preflight has incomplete job metadata")
    _require(preflight.get("prepared_jobs_sha256") == canonical_hash(prepared_jobs),
             "Verified preflight prepared_jobs digest mismatch")
    _require(isinstance(request_records, list) and len(request_records) == MAX_REQUESTS,
             "Verified preflight has incomplete frozen requests")
    jobs_by_id = {job.get("job_id"): job for job in prepared_jobs if isinstance(job, dict)}
    requests_by_id = {row.get("job_id"): row for row in request_records if isinstance(row, dict)}
    _require(len(jobs_by_id) == MAX_REQUESTS and len(requests_by_id) == MAX_REQUESTS,
             "Preflight job/request IDs are missing or duplicated")
    _route, input_rate, output_rate = _verified_route(report)
    samples = report.get("samples")
    _require(isinstance(samples, list) and len(samples) == MAX_REQUESTS,
             "Expected exactly 36 unique task/repeat/arm rows")
    expected = {(case_id, repeat, arm) for case_id in CASE_IDS for repeat in REPEATS for arm in ARMS}
    observed = set()
    for row in samples:
        _require(isinstance(row, dict), "Malformed sample row")
        key = (row.get("case_id"), row.get("repeat"), row.get("arm"))
        _require(key in expected and key not in observed, f"Unexpected or duplicate task/repeat/arm row: {key}")
        observed.add(key)
        request = row.get("request")
        _require(isinstance(request, dict) and row.get("request_sha256") == canonical_hash(request),
                 f"Request hash mismatch for {key}")
        _require(request.get("model") == MODEL, f"Unexpected model in frozen request for {key}")
        job_id = f"{key[0]}:r{key[1]}:{key[2]}"
        frozen_job = jobs_by_id.get(job_id)
        frozen_request = requests_by_id.get(job_id)
        _require(isinstance(frozen_job, dict) and isinstance(frozen_request, dict),
                 f"Result row has no matching frozen job: {job_id}")
        _require(row.get("job_id") == job_id and row.get("expected") == frozen_job.get("expected")
                 and row.get("local_rendered_prompt_tokens") == frozen_job.get("local_rendered_prompt_tokens")
                 and _close(row.get("preparation_ms"), frozen_job.get("preparation_ms"))
                 and request == frozen_request.get("request")
                 and row.get("request_sha256") == frozen_request.get("request_sha256"),
                 f"Result scoring/reserve metadata or body differs from the verified preflight: {job_id}")
        _require(row.get("http_status") == 200 and row.get("model") == MODEL
                 and str(row.get("provider") or "").strip().casefold() == "minimax",
                 f"Route attribution failed for {key}")
        try:
            started = datetime.fromisoformat(row["request_started_utc"].replace("Z", "+00:00"))
            completed = datetime.fromisoformat(row["response_completed_utc"].replace("Z", "+00:00"))
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise AnalysisError(f"Invalid request timing timestamps for {key}") from error
        _require(started.tzinfo is not None and completed.tzinfo is not None,
                 f"Request timing timestamps must be timezone-aware for {key}")
        reported_ms = _number(row.get("end_to_end_ms"))
        timestamp_ms = (completed - started).total_seconds() * 1000
        _require(reported_ms is not None and timestamp_ms >= 0
                 and math.isclose(timestamp_ms, reported_ms, rel_tol=0.01,
                                  abs_tol=TIMESTAMP_DURATION_TOLERANCE_MS),
                 f"Reported end-to-end duration does not reconcile with timestamps for {key}")
        raw_usage = _raw_sse_usage(row.get("raw_sse_events"))
        _require(isinstance(raw_usage, dict) and row.get("usage") == raw_usage,
                 f"Stored usage does not match the raw SSE receipt for {key}")
        observed_cost, receipt_source = cost_receipt(raw_usage)
        _require(observed_cost is not None and row.get("cost_receipt_status") == "reported"
                 and row.get("cost_receipt_source") == receipt_source
                 and _close(row.get("cost_usd"), observed_cost),
                 f"Observed cost does not reconcile to the raw usage receipt for {key}")
        receipt_issues = runtime_receipt_issues(raw_usage)
        _require(not receipt_issues, f"Raw usage receipt failed integrity checks for {key}: {receipt_issues}")
        p_tokens = raw_usage.get("prompt_tokens")
        c_tokens = raw_usage.get("completion_tokens")
        _require(type(p_tokens) is int and p_tokens > 0 and type(c_tokens) is int and c_tokens >= 0,
                 f"Raw usage token counts are invalid for {key}")
        basis = row.get("uncached_cost_rate_basis")
        _require(isinstance(basis, dict)
                 and _close(basis.get("input_usd_per_million"), input_rate)
                 and _close(basis.get("output_usd_per_million"), output_rate),
                 f"Per-row uncached cost rates differ from the verified live route for {key}")
        reconstructed = (p_tokens * input_rate + c_tokens * output_rate) / 1_000_000
        _require(row.get("token_receipt_reconciled") is True
                 and _close(row.get("reconstructed_uncached_cost_usd"), reconstructed),
                 f"Reconstructed uncached cost does not reconcile to usage and route rates for {key}")
    _require(observed == expected, "Missing task/repeat/arm rows")
    return samples


def analyze(report: dict[str, Any], preflight: dict[str, Any],
            preflight_sha256: str) -> dict[str, Any]:
    samples = _validate_run(report, preflight, preflight_sha256)
    by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    scored = []
    for row in samples:
        choice = parse_raw_sse(row.get("raw_sse_events"))
        correct = choice is not None and choice == row.get("expected")
        derived = {**row, "derived_choice": choice, "derived_correct": correct}
        scored.append(derived)
        by_arm[row["arm"]].append(derived)
    summaries = {}
    task_summaries = {}
    for arm, rows in by_arm.items():
        _require(len(rows) == len(CASE_IDS) * len(REPEATS), f"Wrong row count for {arm}")
        valid = [r for r in rows if r["derived_choice"] is not None]
        prompt = [v for r in rows if (v := _number((r.get("usage") or {}).get("prompt_tokens"))) is not None]
        completion = [v for r in rows if (v := _number((r.get("usage") or {}).get("completion_tokens"))) is not None]
        cached = [v for r in rows if (v := _number(((r.get("usage") or {}).get("prompt_tokens_details") or {}).get("cached_tokens"))) is not None]
        cache_write = [v for r in rows if (v := _number(((r.get("usage") or {}).get("prompt_tokens_details") or {}).get("cache_write_tokens"))) is not None]
        costs = [v for r in rows if (v := _number(r.get("cost_usd"))) is not None]
        ttft = [v for r in rows if (v := _number(r.get("ttft_ms"))) is not None]
        latency = [v for r in rows if (v := _number(r.get("end_to_end_ms"))) is not None]
        tps = [v for r in rows if (v := _number(r.get("completion_tokens_per_second"))) is not None]
        prep = [v for r in rows if (v := _number(r.get("preparation_ms"))) is not None]
        pipeline = [
            r["preparation_ms"] + r["end_to_end_ms"]
            for r in rows
            if _number(r.get("preparation_ms")) is not None
            and _number(r.get("end_to_end_ms")) is not None
        ]
        reconstructed = [v for r in rows if (v := _number(r.get("reconstructed_uncached_cost_usd"))) is not None]
        summaries[arm] = {
            "rows": len(rows), "strict_valid_answers": len(valid),
            "exact_correct": sum(r["derived_correct"] for r in rows),
            "exact_accuracy": sum(r["derived_correct"] for r in rows) / len(rows),
            "prompt_tokens_total": sum(prompt) if len(prompt) == len(rows) else None,
            "prompt_tokens_receipts": len(prompt),
            "completion_tokens_total": sum(completion) if len(completion) == len(rows) else None,
            "completion_tokens_receipts": len(completion),
            "cached_prompt_tokens_total": sum(cached) if len(cached) == len(rows) else None,
            "cache_write_prompt_tokens_total": sum(cache_write) if len(cache_write) == len(rows) else None,
            "cache_receipt_rows": len(cached),
            "cache_hit_share": sum(cached) / sum(prompt) if len(cached) == len(rows) and sum(prompt) else None,
            "cost_usd_total": sum(costs) if len(costs) == len(rows) else None,
            "cost_receipt_rows": len(costs),
            "reconstructed_uncached_cost_usd_total": (
                sum(reconstructed) if len(reconstructed) == len(rows) else None
            ),
            "reconstructed_uncached_cost_rows": len(reconstructed),
            "reconstructed_uncached_cost_label": "estimate at live uncached route list rates using reconciled provider prompt/completion tokens",
            "preprocessing_ms_total": sum(prep) if len(prep) == len(rows) else None,
            "preprocessing_ms_mean": mean(prep) if prep else None,
            "preprocessing_plus_request_pipeline_ms_total": (
                sum(pipeline) if len(pipeline) == len(rows) else None
            ),
            "preprocessing_plus_request_pipeline_ms_mean": mean(pipeline) if pipeline else None,
            "mean_ttft_ms": mean(ttft) if ttft else None,
            "median_ttft_ms": median(ttft) if ttft else None,
            "mean_end_to_end_ms": mean(latency) if latency else None,
            "median_end_to_end_ms": median(latency) if latency else None,
            "mean_completion_tokens_per_second": mean(tps) if tps else None,
        }
        task_summaries[arm] = {}
        for case_id in CASE_IDS:
            task_rows = [r for r in rows if r["case_id"] == case_id]
            correct_count = sum(r["derived_correct"] for r in task_rows)
            task_summaries[arm][case_id] = {
                "exact_correct": correct_count, "repeats": len(task_rows),
                "majority_correct": correct_count >= 2,
                "choices": [r["derived_choice"] for r in sorted(task_rows, key=lambda r: r["repeat"])],
            }
    return {
        "schema_version": 1, "pilot_version": PILOT_VERSION,
        "analysis": "longbench-v2-field-pruning-pilot",
        "status": "analyzed_complete_36_row_run", "model": MODEL,
        "preflight_sha256": preflight_sha256,
        "tasks": list(CASE_IDS), "repeats": list(REPEATS), "arms": list(ARMS),
        "score_source": "raw SSE only; absent DONE, malformed JSON, truncated JSON, or non-A-D is incorrect",
        "timing_reconciliation": {
            "source": "UTC request_started_utc and response_completed_utc",
            "reported_duration_field": "end_to_end_ms",
            "absolute_tolerance_ms": TIMESTAMP_DURATION_TOLERANCE_MS,
            "relative_tolerance": 0.01,
        },
        "pooled": summaries, "per_task": task_summaries,
        "scored_rows": [{"case_id": r["case_id"], "repeat": r["repeat"], "arm": r["arm"],
                         "choice": r["derived_choice"], "correct": r["derived_correct"]}
                        for r in scored],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--preflight", required=True, type=Path,
                        help="Original frozen no-dispatch artifact used for this result")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8-sig"))
    from run_longbench_v2_minimax_field_pruning_pilot import verify_preflight
    preflight = verify_preflight(args.preflight)
    result = analyze(report, preflight, file_sha256(args.preflight))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "pooled": result["pooled"], "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
