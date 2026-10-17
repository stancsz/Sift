"""Analyze a completed frozen 344-task paired MiniMax run without text leakage.

This analyzer accepts only the current 344-task prepare/dispatch schema. It
does not make network calls and emits aggregates only. The current dispatcher
stores raw prompts/answers/responses in its inputs; none are copied to output.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any


EXPECTED_CASES = 344
EXPECTED_ARMS = ("full", "sift")
EXPECTED_REPEATS = (0, 1, 2)
EXPECTED_JOBS = EXPECTED_CASES * len(EXPECTED_ARMS) * len(EXPECTED_REPEATS)
OUTPUT_CAP = 64
BOOTSTRAP_SEED = 20261018
BOOTSTRAP_SAMPLES = 20_000
MODEL = "minimax/minimax-m3"
PROVIDER = "minimax"
# This analyzer is bound to the reviewed live-route manifest. Update only when
# a new manifest has been deliberately reviewed and frozen.
PRIMARY_344_MANIFEST_SHA256 = "a13822840ceeb3648be58496d9814703a02dca0f70227226a9883a34f0ed4665"


class AnalysisError(RuntimeError):
    """Raised when an input does not prove a complete, frozen comparison."""


def canonical_hash(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - index) + ordered[high] * (index - low)


def distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
        "p95": percentile(values, 0.95),
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def require_pinned_manifest(manifest_sha: str) -> None:
    require(manifest_sha == PRIMARY_344_MANIFEST_SHA256,
            "Manifest is not the reviewed frozen primary 344 artifact")


def _index_schedule(prepared: dict[str, Any], manifest: dict[str, Any], manifest_sha: str
                    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    require(prepared.get("status") == "prepared_only_no_dispatch",
            "Prepared report must be a prepare-only artifact")
    require(prepared.get("actual_dispatch_started") is False,
            "Prepared report must not have dispatched requests")
    require(prepared.get("dispatch_authorized_by_manifest") is False,
            "Prepared report unexpectedly claims dispatch authorization")
    require(prepared.get("cohort") == "primary_344", "Prepared report is not the frozen primary_344 cohort")
    require(prepared.get("planned_jobs") == EXPECTED_JOBS,
            f"Prepared report must contain exactly {EXPECTED_JOBS} jobs")
    require(prepared.get("manifest_sha256") == manifest_sha,
            "Prepared report manifest hash does not match the supplied manifest")
    require(manifest.get("status") == "prepared_only_no_dispatch"
            and manifest.get("dispatch_authorized") is False,
            "Manifest must be the frozen no-dispatch study artifact")
    require(manifest.get("dataset", {}).get("id") == "zai-org/LongBench-v2"
            and manifest.get("dataset", {}).get("revision") == "2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9",
            "Manifest dataset identity or revision differs from the frozen study")
    schedule = prepared.get("schedule")
    require(isinstance(schedule, list) and len(schedule) == EXPECTED_JOBS,
            "Prepared report schedule is missing or incomplete")
    require(prepared.get("schedule_sha256") == canonical_hash(schedule),
            "Prepared schedule hash does not match its contents")
    cases = manifest.get("cases")
    require(isinstance(cases, list) and len(cases) == EXPECTED_CASES,
            "Manifest must contain exactly 344 cases")
    frozen_cases = {str(row.get("id")): row for row in cases if isinstance(row, dict)}
    require(len(frozen_cases) == EXPECTED_CASES and "None" not in frozen_cases,
            "Manifest case IDs are missing or duplicated")
    jobs = manifest.get("jobs")
    require(isinstance(jobs, list) and len(jobs) == EXPECTED_JOBS,
            "Manifest must contain exactly 2,064 frozen jobs")
    frozen_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in jobs:
        require(isinstance(row, dict), "Manifest contains a malformed job")
        key = (row.get("case_id"), row.get("arm"), row.get("repeat"))
        require(isinstance(key[0], str) and key[1] in EXPECTED_ARMS
                and type(key[2]) is int and key[2] in EXPECTED_REPEATS,
                "Manifest contains an invalid job identity")
        require(key not in frozen_by_key, "Manifest contains a duplicate job identity")
        frozen_by_key[key] = row
    require(len(frozen_by_key) == EXPECTED_JOBS, "Manifest job identities are incomplete")
    cohort_summary = manifest.get("cohort_summary", {})
    require(cohort_summary.get("schedule_sha256") == canonical_hash(jobs),
            "Manifest cohort schedule commitment does not match its jobs")

    schedule_by_id: dict[str, dict[str, Any]] = {}
    schedule_keys: set[tuple[str, str, int]] = set()
    for row in schedule:
        require(isinstance(row, dict), "Prepared schedule contains a malformed job")
        case_id, arm, repeat = row.get("case_id"), row.get("arm"), row.get("repeat")
        key = (case_id, arm, repeat)
        require(isinstance(case_id, str) and arm in EXPECTED_ARMS
                and type(repeat) is int and repeat in EXPECTED_REPEATS,
                "Prepared schedule contains an invalid task/arm/repeat")
        require(case_id in frozen_cases, "Prepared schedule contains a task outside the manifest")
        require(key not in schedule_keys, "Prepared schedule contains a duplicate job")
        schedule_keys.add(key)
        job_id = f"{case_id}:{arm}:{repeat}"
        digest = row.get("body_sha256")
        require(isinstance(digest, str) and len(digest) == 64,
                f"Prepared schedule lacks a request hash for {job_id}")
        frozen = frozen_by_key.get(key)
        require(frozen is not None, f"Prepared job is absent from the manifest: {job_id}")
        require(digest == frozen.get("canonical_request_body_sha256"),
                f"Prepared request hash disagrees with manifest for {job_id}")
        require(type(row.get("local_prompt_tokens")) is int and row["local_prompt_tokens"] >= 0,
                f"Prepared prompt token count is invalid for {job_id}")
        schedule_by_id[job_id] = row
    require(schedule_keys == set(frozen_by_key), "Prepared schedule differs from the frozen manifest jobs")
    require(len({row["case_id"] for row in schedule}) == EXPECTED_CASES,
            "Prepared schedule does not cover all 344 tasks")
    return schedule_by_id, frozen_cases


def _validate_receipt(sample: dict[str, Any], job_id: str, local_tokens: int
                     ) -> tuple[dict[str, Any], float, int, int, int, int]:
    usage = sample.get("usage")
    require(isinstance(usage, dict), f"Missing usage receipt for {job_id}")
    require(usage.get("is_byok") is True, f"Missing BYOK proof for {job_id}")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    require(type(prompt) is int and prompt >= 0, f"Invalid prompt token receipt for {job_id}")
    require(type(completion) is int and completion >= 0, f"Invalid completion token receipt for {job_id}")
    require(completion <= OUTPUT_CAP, f"Completion token receipt exceeds frozen 64-token cap for {job_id}")
    details = usage.get("prompt_tokens_details")
    require(isinstance(details, dict), f"Missing cache token details for {job_id}")
    cached = details.get("cached_tokens")
    cache_write = details.get("cache_write_tokens")
    require(type(cached) is int and cached >= 0, f"Invalid cached token count for {job_id}")
    require(type(cache_write) is int and cache_write >= 0, f"Invalid cache-write count for {job_id}")
    require(cached <= prompt and cache_write <= prompt and cached + cache_write <= prompt,
            f"Cache token counts do not reconcile with prompt tokens for {job_id}")
    upstream_details = usage.get("cost_details")
    require(isinstance(upstream_details, dict), f"Missing upstream cost details for {job_id}")
    upstream = number(upstream_details.get("upstream_inference_cost"))
    require(upstream is not None and upstream > 0, f"Missing positive BYOK upstream cost for {job_id}")
    direct_raw = usage.get("cost")
    direct = number(direct_raw)
    if direct_raw is not None:
        require(direct is not None and direct >= 0, f"Invalid OpenRouter cost receipt for {job_id}")
    prompt_cost_raw = upstream_details.get("upstream_inference_prompt_cost")
    completion_cost_raw = upstream_details.get("upstream_inference_completions_cost")
    if prompt_cost_raw is not None or completion_cost_raw is not None:
        prompt_cost, completion_cost = number(prompt_cost_raw), number(completion_cost_raw)
        require(prompt_cost is not None and prompt_cost >= 0 and completion_cost is not None
                and completion_cost >= 0, f"Invalid upstream cost components for {job_id}")
        require(math.isclose(prompt_cost + completion_cost, upstream, rel_tol=1e-4, abs_tol=1e-8),
                f"Upstream cost components do not reconcile for {job_id}")
    receipt_cost = number(sample.get("provider_reported_cost_usd"))
    expected_receipt_cost = max(upstream, direct) if direct is not None else upstream
    require(receipt_cost is not None and receipt_cost > 0
            and math.isclose(receipt_cost, expected_receipt_cost, rel_tol=1e-6, abs_tol=1e-8),
            f"Runner and usage cost receipts disagree for {job_id}")
    ratio = sample.get("provider_local_input_ratio")
    expected_ratio = prompt / local_tokens if local_tokens else None
    if expected_ratio is not None:
        require(number(ratio) is not None and math.isclose(float(ratio), expected_ratio,
                                                            rel_tol=1e-6, abs_tol=1e-8),
                f"Provider/local token ratio does not reconcile for {job_id}")
        require(expected_ratio <= 1.05, f"Provider prompt tokens exceed protocol tolerance for {job_id}")
    return usage, upstream, prompt, completion, cached, cache_write


def _choice(sample: dict[str, Any]) -> str | None:
    """Return the exact trimmed response only when transport termination is valid."""
    output = sample.get("answer")
    if not isinstance(output, str):
        return None
    choice = output.strip()
    if choice not in {"A", "B", "C", "D"}:
        return None
    if sample.get("choice") != choice:
        return None
    # The dispatcher stores raw SSE events. Require its terminal marker before
    # treating a response as scoreable; truncated streams are incorrect.
    events = sample.get("raw_sse_events")
    if not isinstance(events, list) or not events or events[-1] != "[DONE]":
        return None
    if sample.get("failure") is not None or sample.get("finish_reason") != "stop":
        return None
    if sample.get("http_status") != 200 or sample.get("returned_model") != MODEL:
        return None
    provider = sample.get("provider")
    if not isinstance(provider, str) or provider.strip().casefold() != PROVIDER:
        return None
    return choice


def _majority_ci(differences: list[int], seed: int, samples: int) -> dict[str, Any]:
    rng = random.Random(seed)
    n = len(differences)
    draws = [sum(differences[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples)]
    return {"n_tasks": n, "estimate_sift_minus_full": statistics.fmean(differences),
            "ci95_low": percentile(draws, 0.025), "ci95_high": percentile(draws, 0.975),
            "method": "percentile bootstrap resampling tasks as clusters",
            "bootstrap_samples": samples, "bootstrap_seed": seed}


def _timing(values: list[float], supplied: int, expected: int, unit: str = "ms") -> dict[str, Any]:
    if supplied == 0:
        return {"status": "unavailable", "reason": "not_supplied_by_runner", "unit": unit,
                "n": 0, "expected": expected}
    if supplied != expected:
        return {"status": "partially_available", "reason": "not_supplied_for_every_request",
                "unit": unit, "n": supplied, "expected": expected, "available_values": distribution(values)}
    return {"status": "available", "unit": unit, "expected": expected, **distribution(values)}


def analyze(prepared: dict[str, Any], run: dict[str, Any], manifest: dict[str, Any],
            manifest_sha: str, bootstrap_samples: int = BOOTSTRAP_SAMPLES) -> dict[str, Any]:
    require(type(bootstrap_samples) is int and bootstrap_samples >= 200,
            "Bootstrap sample count must be an integer >= 200")
    schedule_by_id, frozen_cases = _index_schedule(prepared, manifest, manifest_sha)
    require(run.get("status") == "complete", f"Run is not complete: {run.get('status')!r}")
    require(run.get("actual_dispatch_started") is True, "Run does not prove dispatch started")
    require(run.get("manifest_sha256") == prepared.get("manifest_sha256"),
            "Run and prepare report manifest hashes differ")
    require(run.get("schedule_sha256") == prepared.get("schedule_sha256"),
            "Run and prepare report schedule hashes differ")
    require(run.get("schedule") == prepared.get("schedule"), "Run schedule differs from frozen prepare report")
    require(run.get("execution_runner_sha256") == prepared.get("execution_runner_sha256"),
            "Run used a different runner than the frozen prepare report")
    samples = run.get("samples")
    require(isinstance(samples, list) and len(samples) == EXPECTED_JOBS,
            f"Run must contain exactly {EXPECTED_JOBS} response records")
    seen: set[str] = set()
    indexed: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    arm_rows: dict[str, list[dict[str, Any]]] = {arm: [] for arm in EXPECTED_ARMS}
    choices: dict[str, bool] = {}
    totals = {arm: {"prompt": 0, "completion": 0, "cached": 0, "cache_write": 0,
                    "upstream_cost": 0.0, "reported_cost": 0.0, "openrouter_cost": 0.0,
                    "openrouter_cost_n": 0, "uncached_cost": 0.0}
              for arm in EXPECTED_ARMS}
    live_route = run.get("live_route_validation")
    require(isinstance(live_route, dict), "Run is missing its live route validation receipt")
    input_rate, output_rate = number(live_route.get("input_usd_per_million")), number(live_route.get("output_usd_per_million"))
    cache_rate = number(live_route.get("cache_read_usd_per_million"))
    require(live_route.get("endpoint_model_id") == "minimax/minimax-m3"
            and isinstance(live_route.get("provider"), str)
            and live_route["provider"].casefold() == "minimax",
            "Live route metadata does not identify the frozen MiniMax endpoint")
    require(input_rate is not None and input_rate > 0 and output_rate is not None and output_rate > 0,
            "Live route input/output rates are missing or invalid")
    if live_route.get("cache_read_usd_per_million") is not None:
        require(cache_rate is not None and cache_rate >= 0, "Live route cache-read rate is invalid")
    frozen_route = manifest.get("route_assumptions", {})
    require(live_route.get("route_tag") == frozen_route.get("route_tag"),
            "Live route tag differs from the frozen manifest")
    frozen_input_rate = number(frozen_route.get("input_usd_per_million"))
    frozen_output_rate = number(frozen_route.get("output_usd_per_million"))
    require(frozen_input_rate is not None and frozen_output_rate is not None
            and math.isclose(input_rate, frozen_input_rate, rel_tol=0, abs_tol=1e-12)
            and math.isclose(output_rate, frozen_output_rate, rel_tol=0, abs_tol=1e-12),
            "Live route prices differ from the frozen manifest")
    require(live_route.get("max_prompt_tokens") == frozen_route.get("max_prompt_tokens")
            and live_route.get("max_completion_tokens") == frozen_route.get("max_completion_tokens"),
            "Live route context limits differ from the frozen manifest")

    # Required study fields are not inferred from external prices. Cost receipts
    # remain authoritative; reconstructions are labeled counterfactual.
    for sample in samples:
        require(isinstance(sample, dict), "Run contains a malformed sample")
        case_id, arm, repeat = sample.get("case_id"), sample.get("arm"), sample.get("repeat")
        job_id = sample.get("job_id")
        require(isinstance(case_id, str) and arm in EXPECTED_ARMS
                and type(repeat) is int and repeat in EXPECTED_REPEATS,
                "Run contains an invalid task/arm/repeat identity")
        expected_job_id = f"{case_id}:{arm}:{repeat}"
        require(job_id == expected_job_id and job_id not in seen,
                f"Missing, inconsistent, or duplicate job_id: {job_id!r}")
        seen.add(job_id)
        frozen = schedule_by_id.get(job_id)
        require(frozen is not None, f"Run contains an unscheduled job: {job_id}")
        require(sample.get("request_body_sha256") == frozen.get("body_sha256"),
                f"Request hash differs from prepare report for {job_id}")
        require(sample.get("local_prompt_tokens") == frozen.get("local_prompt_tokens"),
                f"Local prompt token count differs from prepare report for {job_id}")
        case_meta = frozen_cases[case_id]
        expected = sample.get("expected")
        require(isinstance(expected, str) and expected in {"A", "B", "C", "D"}
                and expected == case_meta.get("answer_key"),
                f"Pinned expected choice differs from manifest for {job_id}")
        pair = indexed.setdefault((case_id, repeat), {})
        require(arm not in pair, f"Duplicate arm for {case_id} repeat {repeat}")
        pair[arm] = sample
        arm_rows[arm].append(sample)
        usage, upstream, prompt, completion, cached, cache_write = _validate_receipt(
            sample, job_id, frozen["local_prompt_tokens"])
        arm_total = totals[arm]
        arm_total["prompt"] += prompt
        arm_total["completion"] += completion
        arm_total["cached"] += cached
        arm_total["cache_write"] += cache_write
        arm_total["upstream_cost"] += upstream
        arm_total["reported_cost"] += float(sample["provider_reported_cost_usd"])
        direct = number(usage.get("cost"))
        if direct is not None:
            arm_total["openrouter_cost"] += direct
            arm_total["openrouter_cost_n"] += 1
        if input_rate is not None and output_rate is not None:
            arm_total["uncached_cost"] += (prompt * input_rate + completion * output_rate) / 1_000_000
        parsed = _choice(sample)
        # Recheck all identities independently of the dispatcher's stored score.
        choices[job_id] = parsed is not None and parsed == expected

    require(seen == set(schedule_by_id), "Run job identities do not exactly cover the frozen schedule")
    require(run.get("completed_jobs") == EXPECTED_JOBS,
            "Run completion count does not match the frozen 2,064-job schedule")
    require(number(run.get("settled_actual_cost_usd")) is not None
            and math.isclose(float(run["settled_actual_cost_usd"]),
                             sum(totals[arm]["reported_cost"] for arm in EXPECTED_ARMS),
                             rel_tol=1e-6, abs_tol=1e-8),
            "Top-level settled cost does not reconcile with per-request receipts")
    require(len(indexed) == EXPECTED_CASES * len(EXPECTED_REPEATS), "Run has incomplete task-repeat pairs")
    case_ids = set(frozen_cases)
    require({case_id for case_id, _ in indexed} == case_ids, "Run does not cover every frozen task")
    for key, pair in indexed.items():
        require(set(pair) == set(EXPECTED_ARMS), f"Incomplete paired arms for task/repeat {key[0]}:{key[1]}")

    tasks: dict[str, dict[str, bool]] = {}
    per_arm: dict[str, dict[str, Any]] = {}
    differences: list[int] = []
    both = full_only = sift_only = neither = 0
    for case_id in sorted(case_ids):
        tasks[case_id] = {}
        for arm in EXPECTED_ARMS:
            wins = sum(choices[f"{case_id}:{arm}:{repeat}"] for repeat in EXPECTED_REPEATS)
            tasks[case_id][arm] = wins >= 2
        full_majority, sift_majority = tasks[case_id]["full"], tasks[case_id]["sift"]
        if full_majority and sift_majority:
            both += 1
        elif full_majority:
            full_only += 1
        elif sift_majority:
            sift_only += 1
        else:
            neither += 1
        differences.append(int(sift_majority) - int(full_majority))

    for arm in EXPECTED_ARMS:
        rows, counts = arm_rows[arm], totals[arm]
        correct = sum(choices[row["job_id"]] for row in rows)
        valid = sum(_choice(row) is not None for row in rows)
        majority = sum(tasks[case_id][arm] for case_id in case_ids)
        per_arm[arm] = {
            "requests": len(rows),
            "exact_correct": correct,
            "exact_responses": len(rows),
            "exact_accuracy": correct / len(rows),
            "valid_choices": valid,
            "invalid_or_incomplete_choices": len(rows) - valid,
            "task_majorities_correct": majority,
            "tasks": EXPECTED_CASES,
            "task_majority_accuracy": majority / EXPECTED_CASES,
            "prompt_tokens": {"total": counts["prompt"]},
            "completion_tokens": {"total": counts["completion"]},
            "cached_prompt_tokens": {"total": counts["cached"],
                                     "fraction_of_prompt_tokens": counts["cached"] / counts["prompt"] if counts["prompt"] else None},
            "cache_write_tokens": {"total": counts["cache_write"],
                                   "fraction_of_prompt_tokens": counts["cache_write"] / counts["prompt"] if counts["prompt"] else None},
            "upstream_byok_cost_usd": counts["upstream_cost"],
            "runner_reported_cost_usd": counts["reported_cost"],
            "openrouter_reported_cost_usd": counts["openrouter_cost"] if counts["openrouter_cost_n"] == len(rows) else None,
            "uncached_cost_reconstruction_usd": counts["uncached_cost"] if input_rate is not None else None,
            "cache_adjusted_cost_reconstruction_usd": None,
        }
        if input_rate is not None and cache_rate is not None and counts["cache_write"] == 0:
            per_arm[arm]["cache_adjusted_cost_reconstruction_usd"] = sum(
                ((row["usage"]["prompt_tokens"] - row["usage"]["prompt_tokens_details"]["cached_tokens"]
                  ) * input_rate
                 + row["usage"]["prompt_tokens_details"]["cached_tokens"] * cache_rate
                 + row["usage"]["completion_tokens"] * output_rate) / 1_000_000
                for row in rows)
        elif cache_rate is None:
            per_arm[arm]["cache_adjusted_cost_unavailable_reason"] = "live_route_cache_read_price_unknown"
        elif counts["cache_write"]:
            per_arm[arm]["cache_adjusted_cost_unavailable_reason"] = "cache_write_price_not_reconstructed"

    # Grouped summaries are aggregate-only and use manifest metadata.
    grouped: dict[str, Any] = {}
    for dimension, field in (("domain", "domain"), ("sub_domain", "sub_domain"),
                             ("difficulty", "difficulty"), ("length", "length")):
        keys = sorted({str(frozen_cases[case_id].get(field, "unknown")) for case_id in case_ids})
        grouped[dimension] = {}
        for value in keys:
            ids = [case_id for case_id in case_ids
                   if str(frozen_cases[case_id].get(field, "unknown")) == value]
            grouped[dimension][value] = {arm: {
                "task_majorities_correct": sum(tasks[case_id][arm] for case_id in ids),
                "tasks": len(ids),
                "task_majority_accuracy": sum(tasks[case_id][arm] for case_id in ids) / len(ids) if ids else None,
            } for arm in EXPECTED_ARMS}

    paired = {"both_correct": both, "full_only": full_only, "sift_only": sift_only, "neither": neither,
              "sift_minus_full_majority_difference": statistics.fmean(differences),
              "difference_ci95": _majority_ci(differences, BOOTSTRAP_SEED, bootstrap_samples)}
    reduction = lambda full, sift: (full - sift) / full if full > 0 else None
    efficiency = {
        "provider_prompt_token_reduction_fraction": reduction(per_arm["full"]["prompt_tokens"]["total"],
                                                               per_arm["sift"]["prompt_tokens"]["total"]),
        "upstream_byok_cost_reduction_fraction": reduction(per_arm["full"]["upstream_byok_cost_usd"],
                                                            per_arm["sift"]["upstream_byok_cost_usd"]),
        "uncached_cost_reduction_fraction": reduction(per_arm["full"]["uncached_cost_reconstruction_usd"],
                                                       per_arm["sift"]["uncached_cost_reconstruction_usd"])
        if per_arm["full"]["uncached_cost_reconstruction_usd"] is not None else None,
        "cache_adjusted_cost_reduction_fraction": reduction(per_arm["full"]["cache_adjusted_cost_reconstruction_usd"],
                                                              per_arm["sift"]["cache_adjusted_cost_reconstruction_usd"])
        if per_arm["full"]["cache_adjusted_cost_reconstruction_usd"] is not None
        and per_arm["sift"]["cache_adjusted_cost_reconstruction_usd"] is not None else None,
    }

    def timing_field(rows: list[dict[str, Any]], key: str, arms_expected: int) -> dict[str, Any]:
        vals = [number(row.get(key)) for row in rows]
        vals = [x for x in vals if x is not None and x >= 0]
        return _timing(vals, len(vals), arms_expected)

    # The runner measures Sift once per task and copies that same measurement
    # onto its three repeat records. Count it once per task in summaries.
    sift_preprocessing_by_task: dict[str, list[float]] = {}
    for row in arm_rows["sift"]:
        value = number(row.get("sift_preprocessing_ms"))
        if value is not None and value >= 0:
            sift_preprocessing_by_task.setdefault(row["case_id"], []).append(value)
    sift_preprocessing_values: list[float] = []
    for case_id, values in sift_preprocessing_by_task.items():
        require(all(math.isclose(value, values[0], rel_tol=1e-9, abs_tol=1e-6)
                    for value in values),
                f"Sift preprocessing time differs across repeats for {case_id}")
        sift_preprocessing_values.append(values[0])
    sift_preprocessing_timing = _timing(sift_preprocessing_values,
                                        len(sift_preprocessing_values), EXPECTED_CASES)
    sift_preprocessing_timing["counting_semantics"] = "one measurement per task; repeat copies counted once"

    timing = {
        "ttft_ms": {arm: timing_field(arm_rows[arm], "ttft_ms", len(arm_rows[arm])) for arm in EXPECTED_ARMS},
        "request_wall_ms": {arm: timing_field(arm_rows[arm], "total_request_wall_ms", len(arm_rows[arm])) for arm in EXPECTED_ARMS},
        "sift_preprocessing_ms": sift_preprocessing_timing,
        "end_to_end_ms": {arm: timing_field(arm_rows[arm], "end_to_end_ms", len(arm_rows[arm])) for arm in EXPECTED_ARMS},
    }
    elapsed = number(run.get("elapsed_wall_seconds"))
    timing["runner_reported_elapsed_wall_seconds"] = (
        {"status": "available", "value": elapsed, "scope": "dispatch loop only; excludes preparation and route preflight"}
        if elapsed is not None and elapsed >= 0 else
        {"status": "unavailable", "reason": "not_supplied_by_runner"})
    timing["full_preparation_to_completion_wall_time"] = {
        "status": "available" if (number(run.get("process_wall_seconds")) is not None
                                   and float(run["process_wall_seconds"]) >= 0) else "unavailable",
        "value": (number(run.get("process_wall_seconds"))
                  if number(run.get("process_wall_seconds")) is not None
                  and float(run["process_wall_seconds"]) >= 0 else None),
        "unit": "seconds",
        "scope": "process start through dispatch completion; includes prompt reconstruction and route preflight"
        if number(run.get("process_wall_seconds")) is not None
        and float(run["process_wall_seconds"]) >= 0 else None,
        "reason": None if (number(run.get("process_wall_seconds")) is not None
                           and float(run["process_wall_seconds"]) >= 0)
        else "not_supplied_by_runner"}

    return {
        "schema_version": 1,
        "status": "complete_aggregate_analysis",
        "scope": {"cohort": "primary_344", "tasks": EXPECTED_CASES,
                  "repeats_per_arm": len(EXPECTED_REPEATS), "responses_per_arm": EXPECTED_CASES * len(EXPECTED_REPEATS),
                  "total_responses": EXPECTED_JOBS, "arms": list(EXPECTED_ARMS),
                  "evidence_class": "post_census_development_evidence_not_blind_holdout",
                  "limitations": [
                      "All LongBench v2 task IDs were exposed by prior prompt/label census work; this is not blind validation.",
                      "This task-level QA benchmark does not measure multi-turn Codex or Claude Code completion time.",
                      "Observed BYOK upstream costs are provider receipts, not an invoice or a universal savings guarantee.",
                  ]},
        "provenance": {"manifest_sha256": manifest_sha,
                       "prepare_schedule_sha256": prepared["schedule_sha256"],
                       "execution_runner_sha256": prepared.get("execution_runner_sha256"),
                       "analyzer_sha256": sha256_bytes(Path(__file__).read_bytes()),
                       "bootstrap_seed": BOOTSTRAP_SEED,
                       "bootstrap_samples": bootstrap_samples},
        "quality": {"arms": per_arm, "paired_task_majority": paired, "grouped_task_majorities": grouped},
        "efficiency": efficiency,
        "route": ({key: live_route.get(key) for key in (
            "endpoint_model_id", "provider", "route_tag", "input_usd_per_million",
            "output_usd_per_million", "cache_read_usd_per_million", "max_prompt_tokens",
            "max_completion_tokens", "checked_utc")} if isinstance(live_route, dict) else
            {"status": "unavailable"}),
        "timing": timing,
        "run_status": {"status": run.get("status"), "completed_jobs": run.get("completed_jobs"),
                        "settled_actual_cost_usd": run.get("settled_actual_cost_usd")},
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AnalysisError(f"Cannot read JSON input {path}: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True, help="Frozen 344 prepare-only report")
    parser.add_argument("--run", type=Path, required=True, help="Completed dispatch report")
    parser.add_argument("--manifest", type=Path, required=True, help="Frozen 344 manifest used by the run")
    parser.add_argument("--output", type=Path, required=True, help="Aggregate-only JSON output")
    args = parser.parse_args()
    manifest_bytes = args.manifest.read_bytes()
    manifest_sha = sha256_bytes(manifest_bytes)
    require_pinned_manifest(manifest_sha)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    summary = analyze(_read_json(args.prepared), _read_json(args.run), manifest,
                      manifest_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "tasks": summary["scope"]["tasks"],
                      "responses": summary["scope"]["total_responses"], "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AnalysisError as error:
        raise SystemExit(f"LongBench 344 analysis stopped: {error}")

