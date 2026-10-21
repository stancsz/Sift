"""One-use, no-retry continuation for the stopped fresh344 MiniMax cohort."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable

import requests

import run_longbench_v2_minimax_fresh_344 as fresh

legacy = fresh.legacy
ROOT = fresh.ROOT
STATE_DIR = fresh.FRESH_STATE_DIR
PREFIX_PATH = STATE_DIR / "fresh344-dispatch.json"
PREFIX_SHA256 = "c3669172ba0a29062fc3d217ebbd49946e82f19ff4d9ba353a9151364244fdc7"
MANIFEST_PATH = ROOT / "docs/evals/longbench-v2-minimax-fresh-344-manifest-2026-10-20.json"
CONTINUATION_ID = "fresh344-minimax-20261020-continuation-1"
CLAIM_PATH = STATE_DIR / "fresh344-continuation-1.claim.json"
OUTPUT_PATH = STATE_DIR / "fresh344-continuation-1.json"
CAP_USD = 100.0
HISTORICAL_RESERVE_USD = 2.0457216
PREFIX_UNKNOWN_RESERVE_USD = 0.06167235
PREFIX_COMPLETED = 23
PREFIX_RECEIPTS = 22
PREFIX_RECEIPT_COST_USD = 0.17086824
PREFIX_TOKEN_COST_USD = 0.34953
MAX_CONSECUTIVE_FAILURES = 10


class ContinuationError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _job_id(job: dict[str, Any]) -> str:
    return f"{job['case_id']}:{job['arm']}:{job['repeat']}"


def _valid_tokens(usage: Any) -> tuple[int, int]:
    if not isinstance(usage, dict):
        raise ContinuationError("Attempt omitted usage token counts")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if (type(prompt) is not int or prompt < 0 or type(completion) is not int
            or completion < 0 or prompt == 0):
        raise ContinuationError("Attempt usage token counts are invalid")
    return prompt, completion


def _uncached_cost(prompt: int, completion: int, input_rate: float = 0.30,
                   output_rate: float = 1.20) -> float:
    return (prompt * input_rate + completion * output_rate) / 1_000_000


def _receipt_cost(usage: Any) -> float | None:
    amount, _source = legacy.cost_receipt(usage)
    if amount is None:
        return None
    if not math.isfinite(float(amount)) or amount < 0:
        raise ContinuationError("Provider cost receipt is invalid")
    return float(amount)


def _prefix_accounting(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if len(rows) != PREFIX_COMPLETED:
        raise ContinuationError("Pinned prefix must contain exactly 23 attempt rows")
    receipt_total = 0.0
    token_total = 0.0
    receipt_count = 0
    for row in rows[:PREFIX_RECEIPTS]:
        prompt, completion = _valid_tokens(row.get("usage"))
        token_total += _uncached_cost(prompt, completion)
        receipt = _receipt_cost(row.get("usage"))
        if receipt is not None:
            receipt_total += receipt
            receipt_count += 1
    if receipt_count != PREFIX_RECEIPTS:
        raise ContinuationError("The first 22 prefix attempts must have valid provider receipts")
    if not math.isclose(receipt_total, PREFIX_RECEIPT_COST_USD, abs_tol=1e-8, rel_tol=0):
        raise ContinuationError("Prefix provider receipt total differs from the pinned accounting")
    if not math.isclose(token_total, PREFIX_TOKEN_COST_USD, abs_tol=1e-8, rel_tol=0):
        raise ContinuationError("Prefix token-rate total differs from the pinned accounting")
    last = rows[-1]
    if (last.get("http_status") is not None or last.get("usage") is not None
            or _receipt_cost(last.get("usage")) is not None
            or not str(last.get("failure", "")).startswith("ConnectionError")):
        raise ContinuationError("Pinned final attempt is not the expected unreceipted connection failure")
    return {"receipt_count": receipt_count, "receipt_usd": receipt_total,
            "token_rate_usd": token_total,
            "budget_basis_usd": max(receipt_total, token_total)}


def validate_prefix(prefix: dict[str, Any], prefix_sha256: str,
                    jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate the exact stopped prefix, without returning or logging its payloads."""
    if prefix_sha256 != PREFIX_SHA256:
        raise ContinuationError("Stopped prefix SHA-256 differs from the one-use pin")
    if (prefix.get("status") != "safety_guard_stopped"
            or prefix.get("completed_jobs") != PREFIX_COMPLETED
            or prefix.get("planned_jobs") != 2064
            or prefix.get("fresh_run_id") != fresh.FRESH_RUN_ID
            or prefix.get("fresh_manifest_canonical_sha256") != fresh.FRESH_MANIFEST_CANONICAL_SHA256):
        raise ContinuationError("Stopped prefix identity or status differs from the fixed run")
    rows = prefix.get("samples")
    flight = prefix.get("in_flight")
    if (not isinstance(rows, list) or len(rows) != PREFIX_COMPLETED
            or not isinstance(flight, dict) or len(jobs) != 2064):
        raise ContinuationError("Stopped prefix or reconstructed schedule has an invalid shape")
    seen: set[str] = set()
    for index, (row, job) in enumerate(zip(rows, jobs[:PREFIX_COMPLETED], strict=True)):
        expected_id = _job_id(job)
        if (not isinstance(row, dict) or row.get("job_id") != expected_id
                or row.get("case_id") != job["case_id"] or row.get("arm") != job["arm"]
                or row.get("repeat") != job["repeat"]
                or row.get("request_body_sha256") != job["body_sha256"]
                or expected_id in seen):
            raise ContinuationError(f"Prefix attempt {index + 1} does not match the frozen unique schedule")
        seen.add(expected_id)
    if (flight.get("index") != PREFIX_COMPLETED - 1
            or flight.get("job_id") != _job_id(jobs[PREFIX_COMPLETED - 1])
            or flight.get("state") != "unknown_outcome_requires_external_reconciliation"
            or not math.isclose(float(flight.get("reserved_cost_usd", -1)),
                                PREFIX_UNKNOWN_RESERVE_USD, abs_tol=1e-10, rel_tol=0)
            or not math.isclose(float(rows[-1].get("reserved_cost_usd", -1)),
                                PREFIX_UNKNOWN_RESERVE_USD, abs_tol=1e-10, rel_tol=0)):
        raise ContinuationError("Final prefix job is not the pinned unknown outcome")
    accounting = _prefix_accounting(rows)
    accounting.update({"completed_jobs": PREFIX_COMPLETED,
                       "continuation_start_index": PREFIX_COMPLETED,
                       "remaining_jobs": len(jobs) - PREFIX_COMPLETED})
    return accounting


def _job_reserve(job: dict[str, Any], input_rate: float = 0.30,
                 output_rate: float = 1.20) -> float:
    return (job["local_prompt_tokens"] * legacy.INPUT_FACTOR * input_rate
            + legacy.OUTPUT_CAP * output_rate) / 1_000_000


def _remaining_reserve(jobs: list[dict[str, Any]], input_rate: float = 0.30,
                       output_rate: float = 1.20) -> float:
    return sum(_job_reserve(job, input_rate, output_rate) for job in jobs)


def _write_initial_exclusive(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _write_report(path: Path, report: dict[str, Any]) -> None:
    temp = path.with_name(path.name + ".tmp")
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with temp.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _read_sse(response: Any) -> dict[str, Any]:
    usage = provider = returned_model = finish_reason = response_id = None
    fragments: list[str] = []
    done = False
    try:
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            event = line[5:].strip()
            if event == "[DONE]":
                done = True
                break
            try:
                chunk = json.loads(event)
            except (TypeError, ValueError):
                raise ContinuationError("Streaming response contained malformed JSON") from None
            if not isinstance(chunk, dict):
                raise ContinuationError("Streaming response event was not an object")
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            if chunk.get("provider") is not None:
                provider = chunk["provider"]
            if chunk.get("model") is not None:
                returned_model = chunk["model"]
            if chunk.get("id") is not None:
                response_id = chunk["id"]
            choices = chunk.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                finish_reason = choices[0].get("finish_reason", finish_reason)
                delta = choices[0].get("delta") or {}
                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    fragments.append(delta["content"])
    except ContinuationError:
        raise
    text_choice = "".join(fragments).strip()
    choice = text_choice if len(text_choice) == 1 and text_choice in "ABCD" else None
    return {"usage": usage, "provider": provider, "returned_model": returned_model,
            "response_id": response_id, "choice": choice, "format_valid": choice is not None,
            "finish_reason": finish_reason, "sse_done_received": done}


def dispatch_remaining(jobs: list[dict[str, Any]], report: dict[str, Any], api_key: str,
                       live_route: dict[str, Any], post: Callable[..., Any] | None = None) -> dict[str, Any]:
    post = post or requests.post
    input_rate = float(live_route["input_usd_per_million"])
    output_rate = float(live_route["output_usd_per_million"])
    if (input_rate != 0.30 or output_rate != 1.20
            or live_route.get("endpoint_model_id") != legacy.MODEL
            or live_route.get("route_tag") != "minimax/fp8"
            or live_route.get("max_prompt_tokens") != 524288):
        raise ContinuationError("Live route differs from the pinned MiniMax route, price, or limit")
    pending = jobs[PREFIX_COMPLETED:]
    base_reserved = (HISTORICAL_RESERVE_USD + PREFIX_UNKNOWN_RESERVE_USD
                     + PREFIX_TOKEN_COST_USD)
    future_reserve = _remaining_reserve(pending, input_rate, output_rate)
    cap = report["spend_cap_usd"]
    if base_reserved + future_reserve > cap:
        raise ContinuationError("Historical, prefix, and remaining worst-case reserves exceed cap")
    report.update({"status": "dispatching", "actual_dispatch_started": True,
                   "started_utc": datetime.now(timezone.utc).isoformat(),
                   "live_route_validation": live_route,
                   "remaining_worst_case_reserve_usd": future_reserve,
                   "attempts": [], "in_flight": None,
                   "failure_policy": "No retries; reserve every ambiguous/failed request and advance once."})
    _write_report(OUTPUT_PATH, report)
    settled = 0.0
    own_rate_settled = 0.0
    held = 0.0
    consecutive_failures = 0
    for index, job in enumerate(pending, start=PREFIX_COMPLETED):
        reserve = _job_reserve(job, input_rate, output_rate)
        future_reserve -= reserve
        coverage = base_reserved + settled + held + future_reserve + reserve
        if coverage > cap:
            report["status"] = "budget_guard_stopped_before_request"
            report["stop_reason"] = "next_request_reservation_exceeds_cap"
            break
        attempt = {"index": index, "job_id": _job_id(job),
                   "request_body_sha256": job["body_sha256"],
                   "reserved_cost_usd": reserve, "state": "request_started"}
        report["in_flight"] = attempt
        _write_report(OUTPUT_PATH, report)
        started = time.perf_counter()
        row: dict[str, Any] = {**attempt, "started_utc": datetime.now(timezone.utc).isoformat()}
        row.update({"case_id": job["case_id"], "arm": job["arm"], "repeat": job["repeat"],
                    "domain": job.get("domain"), "sub_domain": job.get("sub_domain"),
                    "local_prompt_tokens": job["local_prompt_tokens"],
                    "sift_preprocessing_ms": job.get("sift_preprocessing_ms"),
                    "expected": job["expected"], "requested_model": legacy.MODEL,
                    "endpoint_model_id": live_route["endpoint_model_id"],
                    "route_tag": live_route["route_tag"]})
        failure_class = None
        response_status = None
        try:
            with post(legacy.API_URL, json=job["body"],
                      headers={"Authorization": f"Bearer {api_key}",
                               "Content-Type": "application/json"},
                      stream=True, timeout=(30, 600)) as response:
                response_status = int(response.status_code)
                row["http_status"] = response_status
                if response_status != 200:
                    failure_class = f"http_{response_status}"
                else:
                    parsed = _read_sse(response)
                    row.update({"provider": parsed["provider"],
                                "returned_model": parsed["returned_model"],
                                "response_id": parsed["response_id"],
                                "choice": parsed["choice"],
                                "format_valid": parsed["format_valid"],
                                "finish_reason": parsed["finish_reason"],
                                "sse_done_received": parsed["sse_done_received"]})
                    if parsed["provider"] is None or str(parsed["provider"]).casefold() != "minimax":
                        failure_class = "provider_mismatch"
                    elif parsed["returned_model"] != legacy.MODEL:
                        failure_class = "model_mismatch"
                    elif not parsed["sse_done_received"]:
                        failure_class = "stream_incomplete"
                    else:
                        prompt_tokens, completion_tokens = _valid_tokens(parsed["usage"])
                        receipt = _receipt_cost(parsed["usage"])
                        own_cost = _uncached_cost(prompt_tokens, completion_tokens, input_rate, output_rate)
                        charged = max(own_cost, receipt if receipt is not None else 0.0)
                        row.update({"state": "complete", "prompt_tokens": prompt_tokens,
                                    "completion_tokens": completion_tokens,
                                    "uncached_token_cost_usd": own_cost,
                                    "provider_reported_cost_usd": receipt,
                                    "budget_cost_usd": charged,
                                    "correct": bool(parsed["finish_reason"] == "stop"
                                                    and parsed["choice"] is not None
                                                    and parsed["choice"] == job["expected"]),
                                    "finish_reason": parsed["finish_reason"]})
                        if prompt_tokens > live_route["max_prompt_tokens"]:
                            failure_class = "usage_prompt_exceeds_live_limit"
                        elif completion_tokens > legacy.OUTPUT_CAP:
                            failure_class = "usage_completion_exceeds_request_cap"
                        elif charged > reserve + 1e-12:
                            failure_class = "usage_cost_exceeds_request_reserve"
                        else:
                            settled += charged
                            own_rate_settled += own_cost
                            consecutive_failures = 0
        except (ContinuationError, legacy.StageError):
            failure_class = "invalid_usage_or_cost_guard"
        except (requests.ConnectionError, requests.Timeout):
            failure_class = "connection_or_timeout_unknown_outcome"
        except requests.RequestException:
            failure_class = "request_transport_unknown_outcome"
        row["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        row["finished_utc"] = datetime.now(timezone.utc).isoformat()
        if failure_class:
            row.update({"state": "failed_or_unknown_reserved", "failure_class": failure_class})
            known_cost = row.get("budget_cost_usd")
            if isinstance(known_cost, (int, float)) and math.isfinite(float(known_cost)):
                row["correct"] = False
                settled += float(known_cost)
                own_rate_settled += float(row.get("uncached_token_cost_usd", 0.0))
            else:
                held += reserve
            consecutive_failures += 1
            if failure_class in {"http_401", "http_403", "http_402", "provider_mismatch",
                                 "model_mismatch", "invalid_usage_or_cost_guard",
                                 "usage_prompt_exceeds_live_limit", "usage_completion_exceeds_request_cap",
                                 "usage_cost_exceeds_request_reserve"}:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = failure_class
            elif failure_class == "connection_or_timeout_unknown_outcome" or failure_class == "request_transport_unknown_outcome" or response_status == 429 or (response_status is not None and 500 <= response_status <= 599):
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    report["status"] = "safety_guard_stopped"
                    report["stop_reason"] = "ten_consecutive_failures"
            else:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "non_retryable_http_or_stream_failure"
        report["attempts"].append(row)
        report["in_flight"] = None
        report["accounting"] = {"historical_reserve_usd": HISTORICAL_RESERVE_USD,
                                "stopped_prefix_unknown_reserve_usd": PREFIX_UNKNOWN_RESERVE_USD,
                                "stopped_prefix_budget_basis_usd": PREFIX_TOKEN_COST_USD,
                                "continuation_settled_budget_usd": settled,
                                "continuation_uncached_token_cost_usd": own_rate_settled,
                                "continuation_unknown_reserve_usd": held,
                                "remaining_worst_case_reserve_usd": future_reserve}
        _write_report(OUTPUT_PATH, report)
        if len(report["attempts"]) % 25 == 0:
            print(json.dumps({"progress_attempts": len(report["attempts"]),
                              "own_rate_budget_subtotal_usd": round(own_rate_settled, 8),
                              "unknown_reserved_usd": round(held, 8)}), flush=True)
        if report["status"] == "safety_guard_stopped":
            break
    else:
        report["status"] = "completed_with_failures" if held else "completed"
        report["stop_reason"] = None
    if report["status"] == "dispatching":
        report["status"] = "completed_with_failures" if held else "completed"
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    _write_report(OUTPUT_PATH, report)
    return report


def _load_prefix() -> tuple[dict[str, Any], str]:
    digest = _hash(PREFIX_PATH)
    if digest != PREFIX_SHA256:
        raise ContinuationError("Stopped prefix SHA-256 differs from the one-use pin")
    try:
        return json.loads(PREFIX_PATH.read_text(encoding="utf-8")), digest
    except (OSError, ValueError) as error:
        raise ContinuationError(f"Stopped prefix is unreadable: {type(error).__name__}") from error


def _check_fixed_paths() -> None:
    for path in (CLAIM_PATH, OUTPUT_PATH, OUTPUT_PATH.with_name(OUTPUT_PATH.name + ".tmp")):
        if path.exists():
            raise ContinuationError("The one-use continuation claim/output already exists")


def _claim(report: dict[str, Any]) -> None:
    claim = {"continuation_id": CONTINUATION_ID,
             "prefix_sha256": PREFIX_SHA256,
             "fresh_manifest_canonical_sha256": fresh.FRESH_MANIFEST_CANONICAL_SHA256,
             "fixed_output": OUTPUT_PATH.relative_to(ROOT).as_posix(),
             "created_utc": datetime.now(timezone.utc).isoformat(),
             "spend_cap_usd": report["spend_cap_usd"],
             "no_retry": True}
    payload = (json.dumps(claim, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(CLAIM_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", help="Offline validation only; default behavior.")
    parser.add_argument("--dispatch", action="store_true", help="Dispatch remaining jobs once, with no retries.")
    parser.add_argument("--spend-cap-usd", type=float)
    parser.add_argument("--confirm-no-unsettled-requests", action="store_true")
    parser.add_argument("--assume-none-if-prior-reports-missing", action="store_true")
    parser.add_argument("--authorize-unverified-provider-billing", action="store_true")
    args = parser.parse_args(argv)
    if args.prepare_only and args.dispatch:
        raise ContinuationError("Choose either offline preparation or explicit dispatch")
    if args.dispatch != (args.spend_cap_usd is not None):
        raise ContinuationError("Use --dispatch and --spend-cap-usd together")
    if args.dispatch and (not args.confirm_no_unsettled_requests
                          or not args.assume_none_if_prior_reports_missing
                          or not args.authorize_unverified_provider_billing):
        raise ContinuationError("Dispatch requires the explicit no-unsettled, missing-report, and unverified-billing authorizations")
    cap = CAP_USD if args.spend_cap_usd is None else args.spend_cap_usd
    fresh.validate_cap(cap)
    _check_fixed_paths() if args.dispatch else None
    fresh_manifest = fresh.load_and_validate_fresh_manifest(MANIFEST_PATH)
    prefix, prefix_sha = _load_prefix()
    base, jobs, _cases = fresh._load_base_and_jobs(fresh_manifest, args.dataset, args.tokenizer, args.template)
    prior = validate_prefix(prefix, prefix_sha, jobs)
    remaining = jobs[PREFIX_COMPLETED:]
    remaining_cost = _remaining_reserve(remaining)
    total_coverage = (HISTORICAL_RESERVE_USD + PREFIX_UNKNOWN_RESERVE_USD
                      + float(prior["budget_basis_usd"]) + remaining_cost)
    fresh.validate_budget_coverage(cap, remaining_cost,
                                   HISTORICAL_RESERVE_USD + PREFIX_UNKNOWN_RESERVE_USD
                                   + float(prior["budget_basis_usd"]))
    summary = {"continuation_id": CONTINUATION_ID, "status": "prepared_only_no_dispatch",
               "prefix_sha256_verified": True, "prefix_completed_jobs": PREFIX_COMPLETED,
               "prefix_sha256": prefix_sha,
               "prefix_receipts": prior["receipt_count"],
               "prefix_receipt_cost_usd": round(float(prior["receipt_usd"]), 8),
               "prefix_uncached_token_cost_usd": round(float(prior["token_rate_usd"]), 8),
               "prefix_budget_basis_usd": round(float(prior["budget_basis_usd"]), 8),
               "historical_unknown_reserve_usd": HISTORICAL_RESERVE_USD,
               "missing_prior_reports_assumption": "user-directed assume-none; tracked historical reserve retained",
               "stopped_request_reserve_usd": PREFIX_UNKNOWN_RESERVE_USD,
               "remaining_jobs": len(remaining),
               "remaining_worst_case_reserve_usd": round(remaining_cost, 8),
               "cap_usd": cap, "total_coverage_usd": round(total_coverage, 8),
               "manifest_canonical_sha256": fresh.FRESH_MANIFEST_CANONICAL_SHA256,
               "fixed_output": OUTPUT_PATH.relative_to(ROOT).as_posix()}
    if not args.dispatch:
        print(json.dumps(summary, indent=2))
        return 0
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ContinuationError("OPENROUTER_API_KEY is required only for explicit dispatch")
    live_route = legacy.live_account_route_preflight(
        api_key, base, cap, remaining, True, False, True, True,
        HISTORICAL_RESERVE_USD + PREFIX_UNKNOWN_RESERVE_USD)
    if (live_route.get("input_usd_per_million") != 0.30
            or live_route.get("output_usd_per_million") != 1.20
            or live_route.get("route_tag") != "minimax/fp8"
            or live_route.get("endpoint_model_id") != legacy.MODEL
            or live_route.get("max_prompt_tokens") != 524288):
        raise ContinuationError("Live route differs from pinned price, model, tag, or prompt limit")
    _check_fixed_paths()
    _claim(summary)
    _write_initial_exclusive(OUTPUT_PATH, {**summary, "status": "claimed_no_request_yet",
                                          "actual_dispatch_started": False})
    report = {**summary, "spend_cap_usd": cap}
    result = dispatch_remaining(jobs, report, api_key, live_route)
    print(json.dumps({"status": result["status"], "attempts": len(result["attempts"]),
                      "settled_budget_usd": result.get("accounting", {}).get("continuation_settled_budget_usd", 0.0),
                      "unknown_reserve_usd": result.get("accounting", {}).get("continuation_unknown_reserve_usd", 0.0),
                      "output": OUTPUT_PATH.relative_to(ROOT).as_posix()}, indent=2))
    return 0 if result["status"] in {"completed", "completed_with_failures"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContinuationError, fresh.FreshRunError, legacy.StageError) as error:
        raise SystemExit(f"Continuation blocked: {error}")
