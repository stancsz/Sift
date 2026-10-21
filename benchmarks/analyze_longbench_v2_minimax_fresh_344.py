"""Offline, aggregate-only analysis of the exact fresh344 stopped prefix and final continuation.

Inputs are private evidence. No prompt reconstruction, inference, account lookup,
or dataset download is performed. A complete schedule is required, including
failed/unknown attempts. Runner-recorded amounts are not account statements.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

try:
    from . import analyze_longbench_v2_minimax_paired_344 as paired
except ImportError:  # Direct CLI execution.
    import analyze_longbench_v2_minimax_paired_344 as paired


FRESH_SHA = "881e896141de69ec4d2c9b8134f724faf0e7bb2736ea640e33e08181f35a8d5a"
BASE_SHA = "eaddd0d337111c6ab3c36d3f4a68dae4f002c94964de39beec620280f9c657c2"
PREFIX_SHA = "c3669172ba0a29062fc3d217ebbd49946e82f19ff4d9ba353a9151364244fdc7"
SCHEDULE_SHA = "52814e20912f272da4d0fd3b1b8668d25b120f4e3800f29cff500bb491239f1f"
RUN_ID = "fresh344-minimax-20261020"
CONTINUATION_ID = "fresh344-minimax-20261020-continuation-1"
MODEL = "minimax/minimax-m3"
ARMS = ("full", "sift")
PREFIX_N = 23
JOBS_N = 2064
CASES_N = 344
HISTORICAL_RESERVE = 2.0457216
PREFIX_RESERVE = 0.06167235
PREFIX_RECEIPTS = 0.17086824
PREFIX_OWN = 0.34953


class AnalysisError(ValueError):
    """A sanitized contract violation; messages never contain input values."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def amount(value: Any) -> float:
    result = paired.number(value)
    require(result is not None and result >= 0, "Invalid numeric accounting field")
    return result


def equal_amount(value: Any, expected: float) -> None:
    require(math.isclose(amount(value), expected, rel_tol=0, abs_tol=1e-8),
            "Accounting amounts do not reconcile")


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "JSON contains duplicate object fields")
        result[key] = value
    return result


def _decode(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(AnalysisError("Nonfinite JSON value")))
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise AnalysisError("Input is not valid strict JSON") from None
    require(isinstance(value, dict), "Input root must be an object")
    return value


def _id(row: dict[str, Any]) -> str:
    return f"{row['case_id']}:{row['arm']}:{row['repeat']}"


def _timestamp(value: Any) -> datetime:
    require(isinstance(value, str), "Missing timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AnalysisError("Malformed timestamp") from None
    require(result.tzinfo is not None and result.utcoffset() is not None, "Timestamp lacks a timezone")
    return result


def _route(route: Any) -> None:
    require(isinstance(route, dict), "Missing live route record")
    require(route.get("endpoint_model_id") == MODEL
            and isinstance(route.get("provider"), str)
            and route["provider"].strip().casefold() == "minimax"
            and route.get("route_tag") == "minimax/fp8"
            and type(route.get("max_prompt_tokens")) is int and route["max_prompt_tokens"] == 524288
            and type(route.get("max_completion_tokens")) is int and route["max_completion_tokens"] == 512000,
            "Live route identity or limit differs from the frozen study")
    equal_amount(route.get("input_usd_per_million"), 0.30)
    equal_amount(route.get("output_usd_per_million"), 1.20)


def _receipt(usage: dict[str, Any]) -> float:
    require(usage.get("is_byok") is True, "Prefix usage lacks BYOK attribution")
    details = usage.get("cost_details")
    require(isinstance(details, dict), "Prefix usage lacks cost details")
    upstream = amount(details.get("upstream_inference_cost"))
    require(upstream > 0, "Prefix usage lacks a positive upstream receipt")
    direct = usage.get("cost")
    if direct is not None:
        upstream = max(upstream, amount(direct))
    return upstream


def _tokens(prompt: Any, completion: Any) -> tuple[int, int]:
    require(type(prompt) is int and 0 < prompt <= 524288
            and type(completion) is int and 0 <= completion <= 64,
            "Invalid token usage or request cap violation")
    return prompt, completion


def _own(prompt: int, completion: int) -> float:
    return (prompt * 0.30 + completion * 1.20) / 1_000_000


def _prefix_stream(row: dict[str, Any]) -> None:
    """Reparse the pinned prefix's private stream without returning its text."""
    events = row.get("raw_sse_events")
    require(isinstance(events, list) and len(events) >= 2 and events[-1] == "[DONE]",
            "Prefix stream lacks terminal evidence")
    fragments: list[str] = []
    metadata: dict[str, Any] = {}
    finish = None
    for event in events[:-1]:
        require(isinstance(event, str), "Malformed prefix stream event")
        chunk = _decode(event.encode("utf-8"))
        for field, key in (("provider", "provider"), ("model", "returned_model"),
                           ("id", "response_id"), ("usage", "usage")):
            if chunk.get(field) is not None:
                metadata[key] = chunk[field]
        choices = chunk.get("choices", [])
        require(isinstance(choices, list), "Malformed prefix stream choices")
        for choice in choices:
            require(isinstance(choice, dict), "Malformed prefix stream choice")
            if choice.get("finish_reason") is not None:
                finish = choice["finish_reason"]
            delta = choice.get("delta") or {}
            require(isinstance(delta, dict), "Malformed prefix stream delta")
            if isinstance(delta.get("content"), str):
                fragments.append(delta["content"])
    require(all(row.get(key) == value for key, value in metadata.items())
            and set(metadata) == {"provider", "returned_model", "response_id", "usage"}
            and row.get("finish_reason") == finish
            and row.get("answer") == "".join(fragments), "Prefix stream and stored fields disagree")
    choice = row["answer"].strip()
    require(row.get("choice") == (choice if choice in {"A", "B", "C", "D"} else None),
            "Prefix parsed choice disagrees with stream")


def _ci(values: list[float], samples: int) -> dict[str, Any]:
    if not values:
        return {"n_tasks": 0, "estimate": None, "ci95_low": None, "ci95_high": None}
    result = paired._majority_ci(values, paired.BOOTSTRAP_SEED, samples)
    result["estimate"] = result.pop("estimate_sift_minus_full")
    return result


def _analyze(fresh_bytes: bytes, base_bytes: bytes, prefix_bytes: bytes,
            continuation_bytes: bytes, *, bootstrap_samples: int = paired.BOOTSTRAP_SAMPLES) -> dict[str, Any]:
    """Validate four immutable input snapshots and return aggregate evidence only.

    The continuation has no pre-run response/usage commitment. Its content hash
    identifies the supplied final snapshot; it does not authenticate the provider.
    """
    require(type(bootstrap_samples) is int and bootstrap_samples >= 200,
            "Bootstrap sample count must be an integer of at least 200")
    fresh, base, prefix, continuation = map(_decode, (fresh_bytes, base_bytes, prefix_bytes, continuation_bytes))
    require(paired.canonical_hash(fresh) == FRESH_SHA, "Fresh manifest pin mismatch")
    require(hashlib.sha256(base_bytes).hexdigest() == BASE_SHA, "Base manifest pin mismatch")
    require(hashlib.sha256(prefix_bytes).hexdigest() == PREFIX_SHA, "Stopped prefix pin mismatch")
    require(fresh.get("schema") == "sift.longbench.minimax.fresh344.v1"
            and fresh.get("run_id") == RUN_ID and fresh.get("status") == "prepared_only_no_dispatch"
            and fresh.get("dispatch_authorized") is False
            and fresh.get("base_manifest_sha256") == BASE_SHA
            and fresh.get("schedule_sha256") == SCHEDULE_SHA,
            "Fresh manifest contract mismatch")
    require(base.get("status") == "prepared_only_no_dispatch" and base.get("dispatch_authorized") is False,
            "Base manifest contract mismatch")
    jobs, cases = base.get("jobs"), base.get("cases")
    require(isinstance(jobs, list) and len(jobs) == JOBS_N
            and isinstance(cases, list) and len(cases) == CASES_N,
            "Frozen schedule or cohort has an invalid shape")
    require(paired.canonical_hash(jobs) == SCHEDULE_SHA
            and base.get("cohort_summary", {}).get("schedule_sha256") == SCHEDULE_SHA,
            "Frozen ordered schedule commitment mismatch")
    case_map = {row.get("id"): row for row in cases if isinstance(row, dict) and isinstance(row.get("id"), str)}
    require(len(case_map) == CASES_N and all(row.get("answer_key") in {"A", "B", "C", "D"}
                                           for row in case_map.values()), "Frozen cohort identities or scoring keys are invalid")
    keys: set[tuple[str, str, int]] = set()
    for job in jobs:
        require(isinstance(job, dict) and isinstance(job.get("case_id"), str)
                and job.get("arm") in ARMS and type(job.get("repeat")) is int
                and job["repeat"] in (0, 1, 2) and job["case_id"] in case_map,
                "Frozen job identity is invalid")
        key = (job["case_id"], job["arm"], job["repeat"])
        require(key not in keys, "Duplicate frozen job identity")
        keys.add(key)
    require(len(keys) == CASES_N * 6, "Frozen schedule does not cover every paired repeat")
    require(prefix.get("status") == "safety_guard_stopped" and prefix.get("actual_dispatch_started") is True
            and prefix.get("completed_jobs") == PREFIX_N and prefix.get("planned_jobs") == JOBS_N
            and prefix.get("fresh_run_id") == RUN_ID and prefix.get("fresh_manifest_canonical_sha256") == FRESH_SHA
            and prefix.get("manifest_sha256") == BASE_SHA, "Stopped prefix identity or status mismatch")
    require(continuation.get("status") in {"completed", "completed_with_failures"}
            and continuation.get("actual_dispatch_started") is True and continuation.get("in_flight") is None
            and continuation.get("stop_reason") is None and isinstance(continuation.get("finished_utc"), str),
            "Continuation is partial, in flight, or not final")
    require(_timestamp(continuation.get("finished_utc")) >= _timestamp(continuation.get("started_utc")),
            "Continuation completion precedes its start")
    require(continuation.get("continuation_id") == CONTINUATION_ID
            and continuation.get("prefix_sha256") == PREFIX_SHA
            and continuation.get("prefix_sha256_verified") is True
            and continuation.get("manifest_canonical_sha256") == FRESH_SHA
            and continuation.get("prefix_completed_jobs") == PREFIX_N
            and continuation.get("remaining_jobs") == JOBS_N - PREFIX_N,
            "Continuation identity or prefix binding mismatch")
    for report in (prefix, continuation):
        _route(report.get("live_route_validation"))
    prefix_rows, continuation_rows = prefix.get("samples"), continuation.get("attempts")
    require(isinstance(prefix_rows, list) and len(prefix_rows) == PREFIX_N
            and isinstance(continuation_rows, list) and len(continuation_rows) == JOBS_N - PREFIX_N,
            "Final records do not cover the entire fixed schedule")
    flight = prefix.get("in_flight")
    require(isinstance(flight, dict) and flight.get("index") == PREFIX_N - 1
            and flight.get("job_id") == _id(jobs[PREFIX_N - 1])
            and flight.get("state") == "unknown_outcome_requires_external_reconciliation",
            "Stopped prefix unknown outcome binding mismatch")
    equal_amount(flight.get("reserved_cost_usd"), PREFIX_RESERVE)
    scheduled = prefix.get("schedule")
    require(isinstance(scheduled, list) and len(scheduled) == JOBS_N
            and prefix.get("schedule_sha256") == paired.canonical_hash(scheduled),
            "Prefix prepared schedule commitment mismatch")
    normalized: list[dict[str, Any]] = []
    response_ids: set[str] = set()
    prefix_cost = prefix_own = suffix_budget = suffix_own = suffix_held = 0.0
    suffix_initial_reserve = 0.0
    for index, (job, row, prepared) in enumerate(zip(jobs, prefix_rows + continuation_rows, scheduled, strict=True)):
        require(isinstance(row, dict) and isinstance(prepared, dict), "Malformed attempt or prepared job")
        case = case_map[job["case_id"]]
        local = case.get(f"{job['arm']}_local_prompt_tokens")
        require(type(local) is int and local > 0, "Frozen local token count is invalid")
        require(row.get("job_id") == _id(job) and row.get("case_id") == job["case_id"]
                and row.get("arm") == job["arm"] and type(row.get("repeat")) is int
                and row["repeat"] == job["repeat"]
                and row.get("request_body_sha256") == job.get("canonical_request_body_sha256")
                and type(row.get("local_prompt_tokens")) is int and row["local_prompt_tokens"] == local,
                "Attempt identity, order, request hash, or local token count mismatch")
        require(prepared.get("index") == index and prepared.get("case_id") == job["case_id"]
                and prepared.get("arm") == job["arm"] and type(prepared.get("repeat")) is int
                and prepared["repeat"] == job["repeat"] and prepared.get("local_prompt_tokens") == local
                and prepared.get("body_sha256") == job.get("canonical_request_body_sha256"),
                "Prefix prepared schedule differs from frozen jobs")
        require(row.get("requested_model") == MODEL and row.get("expected") == case["answer_key"],
                "Attempt requested model or frozen scoring key mismatch")
        reserve = (local * 1.5 * .30 + 64 * 1.20) / 1_000_000
        equal_amount(row.get("reserved_cost_usd"), reserve)
        is_prefix = index < PREFIX_N
        if not is_prefix:
            suffix_initial_reserve += reserve
            require(type(row.get("index")) is int and row["index"] == index
                    and row.get("endpoint_model_id") == MODEL and row.get("route_tag") == "minimax/fp8",
                    "Continuation attempt index or route mismatch")
        start_key, end_key = (("request_started_utc", "response_completed_utc") if is_prefix
                              else ("started_utc", "finished_utc"))
        require(_timestamp(row.get(end_key)) >= _timestamp(row.get(start_key)),
                "Attempt completion precedes its start")
        observed = index < PREFIX_N - 1 if is_prefix else row.get("state") == "complete"
        prompt = completion = 0
        receipt = own = None
        valid = correct = False
        if observed:
            require(row.get("http_status") == 200 and row.get("returned_model") == MODEL
                    and isinstance(row.get("provider"), str) and row["provider"].strip().casefold() == "minimax"
                    and row.get("sse_done_received") is True
                    and (row.get("finish_reason") is None or isinstance(row.get("finish_reason"), str)),
                    "Observed response transport or route is invalid")
            response_id = row.get("response_id")
            require(isinstance(response_id, str) and bool(response_id) and response_id not in response_ids,
                    "Missing or replayed provider response identity")
            response_ids.add(response_id)
            if is_prefix:
                require(row.get("failure") is None, "Observed prefix response records a failure")
                _prefix_stream(row)
                usage = row.get("usage")
                require(isinstance(usage, dict), "Prefix lacks token usage")
                prompt, completion = _tokens(usage.get("prompt_tokens"), usage.get("completion_tokens"))
                receipt = _receipt(usage)
                equal_amount(row.get("provider_reported_cost_usd"), receipt)
            else:
                require(row.get("failure_class") is None, "Completed continuation attempt records a failure")
                prompt, completion = _tokens(row.get("prompt_tokens"), row.get("completion_tokens"))
                receipt = row.get("provider_reported_cost_usd")
                if receipt is not None:
                    receipt = amount(receipt)
                require(row.get("choice") is None or row.get("choice") in {"A", "B", "C", "D"},
                        "Invalid parsed choice")
                require(type(row.get("format_valid")) is bool
                        and row["format_valid"] == (row.get("choice") is not None), "Parsed choice and format flag disagree")
            own = _own(prompt, completion)
            valid = row.get("choice") in {"A", "B", "C", "D"} and row["finish_reason"] == "stop"
            correct = valid and row["choice"] == case["answer_key"]
            require(type(row.get("correct")) is bool and row["correct"] == correct,
                    "Stored score disagrees with frozen key and parsed choice")
            if is_prefix:
                prefix_cost += receipt
                prefix_own += own
            else:
                equal_amount(row.get("uncached_token_cost_usd"), own)
                budget = max(own, receipt or 0.0)
                equal_amount(row.get("budget_cost_usd"), budget)
                require(budget <= reserve + 1e-12, "Recorded cost exceeds frozen request reserve")
                suffix_budget += budget
                suffix_own += own
        elif is_prefix:
            require(row.get("usage") is None and row.get("http_status") is None
                    and row.get("provider_reported_cost_usd") is None
                    and isinstance(row.get("failure"), str) and row["failure"].startswith("ConnectionError")
                    and row.get("correct") is False, "Final prefix attempt is not its pinned unknown outcome")
            equal_amount(reserve, PREFIX_RESERVE)
        else:
            # The final continuation can contain transport unknowns. Safety-guard
            # failures stop dispatch, so a final full schedule cannot contain them.
            require(row.get("state") == "failed_or_unknown_reserved"
                    and (row.get("failure_class") in {"connection_or_timeout_unknown_outcome",
                                                       "request_transport_unknown_outcome"}
                         or row.get("failure_class") == "http_429"
                         or row.get("failure_class") in {f"http_{code}" for code in range(500, 600)}),
                    "Invalid failure state in final continuation")
            require(all(row.get(field) is None for field in ("budget_cost_usd", "uncached_token_cost_usd",
                                                            "prompt_tokens", "completion_tokens", "provider_reported_cost_usd"))
                    and (row.get("correct") is None or row.get("correct") is False),
                    "Unknown attempt contains settled usage or a score")
            suffix_held += reserve
        normalized.append({"case": job["case_id"], "arm": job["arm"], "observed": observed,
                           "correct": correct, "valid": valid, "prompt": prompt, "completion": completion,
                           "own": own, "receipt": receipt, "held": 0.0 if observed else reserve})
    equal_amount(prefix_cost, PREFIX_RECEIPTS)
    equal_amount(prefix_own, PREFIX_OWN)
    equal_amount(prefix.get("settled_actual_cost_usd"), prefix_cost)
    equal_amount(continuation.get("total_coverage_usd"), HISTORICAL_RESERVE + PREFIX_RESERVE
                 + prefix_own + suffix_initial_reserve)
    for field, value in (("prefix_receipts", PREFIX_N - 1), ("prefix_receipt_cost_usd", prefix_cost),
                         ("prefix_uncached_token_cost_usd", prefix_own), ("prefix_budget_basis_usd", prefix_own),
                         ("historical_unknown_reserve_usd", HISTORICAL_RESERVE),
                         ("stopped_request_reserve_usd", PREFIX_RESERVE), ("spend_cap_usd", 100), ("cap_usd", 100),
                         ("remaining_worst_case_reserve_usd", suffix_initial_reserve)):
        equal_amount(continuation.get(field), value)
    accounting = continuation.get("accounting")
    require(isinstance(accounting, dict), "Missing final continuation accounting")
    for field, value in (("historical_reserve_usd", HISTORICAL_RESERVE),
                         ("stopped_prefix_unknown_reserve_usd", PREFIX_RESERVE),
                         ("stopped_prefix_budget_basis_usd", prefix_own),
                         ("continuation_settled_budget_usd", suffix_budget),
                         ("continuation_uncached_token_cost_usd", suffix_own),
                         ("continuation_unknown_reserve_usd", suffix_held)):
        equal_amount(accounting.get(field), value)
    # The producer repeatedly subtracts float reservations. A terminal zero can
    # consequently be slightly negative; tolerate only arithmetic-scale residue.
    remaining = paired.number(accounting.get("remaining_worst_case_reserve_usd"))
    require(remaining is not None and abs(remaining) <= 1e-8,
            "Terminal remaining reserve does not reconcile")
    require(continuation["status"] == ("completed_with_failures" if suffix_held else "completed"),
            "Final status does not reconcile with unknown reserves")
    budget_coverage = HISTORICAL_RESERVE + PREFIX_RESERVE + prefix_own + suffix_budget + suffix_held
    require(budget_coverage <= 100 + 1e-8, "Final calculated budget coverage exceeds authorized cap")
    return _aggregate(normalized, cases, bootstrap_samples, {
        "fresh_manifest_canonical_sha256": FRESH_SHA, "base_manifest_sha256": BASE_SHA,
        "prefix_sha256": PREFIX_SHA, "continuation_sha256": hashlib.sha256(continuation_bytes).hexdigest(),
        "ordered_frozen_schedule_sha256": SCHEDULE_SHA,
    }, budget_coverage)


def analyze(fresh_bytes: bytes, base_bytes: bytes, prefix_bytes: bytes,
            continuation_bytes: bytes, *, bootstrap_samples: int = paired.BOOTSTRAP_SAMPLES) -> dict[str, Any]:
    """Public byte-snapshot API; malformed private fields never enter errors."""
    try:
        return _analyze(fresh_bytes, base_bytes, prefix_bytes, continuation_bytes,
                        bootstrap_samples=bootstrap_samples)
    except AnalysisError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError, RecursionError):
        raise AnalysisError("Malformed input contract") from None


def _aggregate(rows: list[dict[str, Any]], cases: list[dict[str, Any]], samples: int,
               provenance: dict[str, Any], budget_coverage: float) -> dict[str, Any]:
    by_case = {case["id"]: [row for row in rows if row["case"] == case["id"]] for case in cases}
    complete = {key for key, values in by_case.items() if all(row["observed"] for row in values)}

    def quality(selected: set[str]) -> dict[str, Any]:
        arms = {}
        task_scores: dict[str, dict[str, bool]] = {key: {} for key in selected}
        request_deltas, majority_deltas = [], []
        for arm in ARMS:
            values = [row for row in rows if row["case"] in selected and row["arm"] == arm]
            for key in selected:
                task_scores[key][arm] = sum(row["correct"] for row in by_case[key] if row["arm"] == arm) >= 2
            arms[arm] = {"requests": len(values), "correct_requests": sum(row["correct"] for row in values),
                         "request_accuracy": sum(row["correct"] for row in values) / len(values) if values else None,
                         "confirmed_responses": sum(row["observed"] for row in values),
                         "valid_stopped_choices": sum(row["valid"] for row in values),
                         "tasks": len(selected), "correct_task_majorities": sum(task_scores[key][arm] for key in selected),
                         "task_majority_accuracy": sum(task_scores[key][arm] for key in selected) / len(selected) if selected else None}
        # Manifest order makes the existing bootstrap deterministic.
        for key in by_case:
            if key in selected:
                request_deltas.append(sum(int(row["correct"]) * (1 if row["arm"] == "sift" else -1)
                                          for row in by_case[key]) / 3)
                majority_deltas.append(int(task_scores[key]["sift"]) - int(task_scores[key]["full"]))
        return {"arms": arms, "request_accuracy_sift_minus_full": _ci(request_deltas, samples),
                "task_majority_accuracy_sift_minus_full": _ci(majority_deltas, samples)}

    costs = {}
    for arm in ARMS:
        values = [row for row in rows if row["arm"] == arm]
        costs[arm] = {"scheduled_attempts": len(values), "usage_recorded_attempts": sum(row["observed"] for row in values),
                      "prompt_tokens": sum(row["prompt"] for row in values),
                      "completion_tokens": sum(row["completion"] for row in values),
                      "own_uncached_cost_usd": sum(row["own"] or 0 for row in values),
                      "provider_reported_cost_usd": sum(row["receipt"] or 0 for row in values),
                      "provider_reported_cost_attempts": sum(row["receipt"] is not None for row in values),
                      "unknown_outcome_held_reserve_usd": sum(row["held"] for row in values)}
    def reduction(field: str) -> float | None:
        full, sift = costs["full"][field], costs["sift"][field]
        return (full - sift) / full if full else None
    return {"schema": "sift.longbench.minimax.fresh344.aggregate.v1", "status": "complete_schedule_aggregate_analysis",
            "evidence_class": "public_exposed_development_cohort_not_blind_holdout",
            "provenance": provenance,
            "coverage": {"scheduled_tasks": CASES_N, "scheduled_attempts": JOBS_N,
                         "prefix_attempts": PREFIX_N, "continuation_attempts": JOBS_N - PREFIX_N,
                         "confirmed_response_attempts": sum(row["observed"] for row in rows),
                         "unknown_or_failed_attempts": sum(not row["observed"] for row in rows),
                         "complete_paired_six_request_tasks": len(complete),
                         "incomplete_paired_tasks": CASES_N - len(complete)},
            "quality": {"all_scheduled_unknowns_counted_incorrect": quality(set(by_case)),
                        "complete_paired_observed_tasks": quality(complete)},
            "usage_and_cost": {"arms": costs,
                "own_uncached_total_usd": sum(value["own_uncached_cost_usd"] for value in costs.values()),
                "provider_reported_total_usd": sum(value["provider_reported_cost_usd"] for value in costs.values()),
                "current_run_unknown_held_reserve_usd": sum(row["held"] for row in rows),
                "historical_held_reserve_usd": HISTORICAL_RESERVE,
                "conservative_budget_coverage_usd": budget_coverage,
                "own_uncached_usd_per_million": {"input": .30, "output": 1.20},
                "recorded_prompt_token_reduction_fraction": reduction("prompt_tokens"),
                "recorded_own_uncached_cost_reduction_fraction": reduction("own_uncached_cost_usd"),
                "reduction_scope": "recorded usage only; unknown usage remains unquantified; arm coverage may differ"},
            "integrity_limits": [
                "Frozen manifests commit the ordered request hashes and expected keys; requests are not reconstructed.",
                "The exact stopped prefix is byte-pinned and its completed streams are reparsed.",
                "Continuation choices, transport flags, token usage, and optional provider costs are runner-recorded; raw streams and raw usage receipts were not retained, so they cannot be independently revalidated.",
                "Continuation content hash identifies this final snapshot; it is not a precommitted response hash or provider signature.",
                "The continuation report does not record its execution source hash; source identity cannot be proved from this report alone.",
                "Provider-reported costs are not invoices or account balances; own uncached amounts are token-rate calculations. Missing provider costs are not invented.",
                "Unknown attempts stay in scheduled denominators and retain reserves; complete paired quality uses only tasks with all six confirmed responses.",
                "The public task cohort was exposed previously; these results do not establish blind validation, parity, or multi-turn agent benefits.",
            ]}


def _read_snapshot(path: Path) -> bytes:
    try:
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
    except OSError:
        raise AnalysisError("An input snapshot is unreadable") from None
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            "Input changed during snapshot read")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fresh-manifest", "base-manifest", "prefix", "continuation", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=paired.BOOTSTRAP_SAMPLES)
    args = parser.parse_args(argv)
    inputs = [args.fresh_manifest, args.base_manifest, args.prefix, args.continuation]
    require(args.output.resolve() not in {path.resolve() for path in inputs}, "Output must differ from inputs")
    result = analyze(*(_read_snapshot(path) for path in inputs), bootstrap_samples=args.bootstrap_samples)
    try:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except OSError:
        raise AnalysisError("Aggregate output cannot be created exclusively") from None
    print(json.dumps({"status": result["status"], "scheduled_attempts": JOBS_N,
                      "complete_paired_tasks": result["coverage"]["complete_paired_six_request_tasks"]}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AnalysisError, KeyError, TypeError, OverflowError):
        raise SystemExit("Fresh344 analysis rejected: input contract or accounting validation failed") from None
