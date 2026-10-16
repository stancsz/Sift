"""Validate and summarize the frozen OpenRouter MiniMax LongBench run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any


EXPECTED_CASES = 100
EXPECTED_REPEATS = 3
EXPECTED_ARMS = ("full", "sift")
BOOTSTRAP_SAMPLES = 20_000
ROOT = Path(__file__).resolve().parents[1]


class AnalysisError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def _distribution(values: list[float]) -> dict[str, float | None]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p25": _percentile(values, 0.25),
        "p75": _percentile(values, 0.75),
        "p95": _percentile(values, 0.95),
    }


def _savings(baseline: float, comparison: float) -> float | None:
    if baseline <= 0:
        return None
    return (baseline - comparison) / baseline


def _exact_binomial_two_sided(a: int, b: int) -> float | None:
    discordant = a + b
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, k) for k in range(min(a, b) + 1)) / (2 ** discordant)
    return min(1.0, 2.0 * tail)


def _majority_ci(differences: list[int], seed: int) -> dict[str, float | int | None]:
    if not differences:
        return {"n_tasks": 0, "estimate": None, "ci95_low": None, "ci95_high": None}
    rng = random.Random(seed)
    n = len(differences)
    estimate = statistics.fmean(differences)
    draws = []
    for _ in range(BOOTSTRAP_SAMPLES):
        draws.append(sum(differences[rng.randrange(n)] for _ in range(n)) / n)
    return {
        "n_tasks": n,
        "estimate": estimate,
        "ci95_low": _percentile(draws, 0.025),
        "ci95_high": _percentile(draws, 0.975),
        "method": "percentile bootstrap resampling tasks as clusters",
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": seed,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def _elapsed_seconds(start: Any, end: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except ValueError:
        return None


def analyze(report: dict[str, Any], manifest: dict[str, Any], manifest_sha256: str,
            input_price: float, output_price: float, cache_read_price: float,
            bootstrap_seed: int) -> dict[str, Any]:
    _require(report.get("status") == "complete", f"Run status is {report.get('status')!r}, expected 'complete'")
    samples = report.get("samples")
    _require(isinstance(samples, list), "Run report has no samples list")
    _require(len(samples) == EXPECTED_CASES * EXPECTED_REPEATS * len(EXPECTED_ARMS),
             f"Expected 600 responses, found {len(samples)}")
    _require(report.get("manifest_sha256") == manifest_sha256,
             "Run report does not match the supplied frozen manifest")
    frozen_cases = manifest.get("cases")
    _require(isinstance(frozen_cases, list) and len(frozen_cases) == EXPECTED_CASES,
             "Supplied manifest must contain exactly 100 frozen cases")
    frozen_by_id = {case.get("id"): case for case in frozen_cases if isinstance(case, dict)}
    _require(len(frozen_by_id) == EXPECTED_CASES, "Manifest case IDs are missing or duplicated")
    harness = manifest.get("harness")
    _require(isinstance(harness, dict), "Manifest does not contain frozen harness metadata")
    analysis_path = harness.get("analysis_script_path")
    analysis_sha256 = harness.get("analysis_script_sha256")
    _require(isinstance(analysis_path, str) and isinstance(analysis_sha256, str),
             "Manifest does not freeze the analysis script")
    resolved_analysis = (ROOT / analysis_path).resolve()
    try:
        resolved_analysis.relative_to(ROOT)
    except ValueError as error:
        raise AnalysisError("Frozen analysis script path escapes repository root") from error
    _require(resolved_analysis == Path(__file__).resolve()
             and hashlib.sha256(resolved_analysis.read_bytes()).hexdigest() == analysis_sha256,
             "Current analyzer does not match the frozen analysis script")

    by_pair: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm in EXPECTED_ARMS}
    seen_jobs: set[str] = set()
    execution = report.get("execution")
    _require(isinstance(execution, dict) and type(execution.get("cli_seed")) is int,
             "Run report does not record the CLI seed")
    cli_seed = execution["cli_seed"]
    _require(execution.get("repeats") == EXPECTED_REPEATS
             and execution.get("sift_target_tokens") == 32_768,
             "Run report does not match the frozen repeat count and Sift target")
    for row in samples:
        job_id = row.get("job_id")
        _require(isinstance(job_id, str) and job_id not in seen_jobs,
                 f"Missing or duplicate job_id: {job_id!r}")
        seen_jobs.add(job_id)
        arm = row.get("arm")
        _require(arm in EXPECTED_ARMS, f"Unexpected arm {arm!r}")
        case_id = row.get("case_id")
        repeat = row.get("repeat")
        _require(isinstance(case_id, str) and type(repeat) is int and 1 <= repeat <= EXPECTED_REPEATS,
                 f"Invalid pair key for {job_id}")
        _require(case_id in frozen_by_id, f"Case ID is not in the frozen manifest: {case_id}")
        frozen_case = frozen_by_id[case_id]
        _require(row.get("domain") == frozen_case.get("domain"),
                 f"Task domain differs from the frozen manifest for {case_id}")
        _require(row.get("expected") == frozen_case.get("answer_key"),
                 f"Answer key differs from the frozen manifest for {case_id}")
        pair = by_pair.setdefault((case_id, repeat), {})
        _require(arm not in pair, f"Duplicate arm for {case_id} repeat {repeat}")
        pair[arm] = row
        by_arm[arm].append(row)

        _require(row.get("http_status") == 200, f"Non-200 response at {job_id}")
        _require(row.get("model") == "minimax/minimax-m3", f"Unexpected model at {job_id}: {row.get('model')!r}")
        _require(isinstance(row.get("provider"), str) and row["provider"].casefold() == "minimax",
                 f"Unexpected provider at {job_id}: {row.get('provider')!r}")
        _require(row.get("is_byok") is True or row.get("usage", {}).get("is_byok") is True,
                 f"Unexpected billing mode at {job_id}")
        _require(row.get("cost_receipt_status") == "reported", f"Missing cost receipt at {job_id}")
        local_tokens = row.get("local_rendered_prompt_tokens")
        _require(type(local_tokens) is int and local_tokens >= 0, f"Missing local token count at {job_id}")
        if arm == "full":
            _require(local_tokens > execution["sift_target_tokens"],
                     f"Full-context prompt does not exceed the Sift target at {job_id}")
        else:
            _require(local_tokens <= execution["sift_target_tokens"],
                     f"Sift prompt exceeds the target at {job_id}")
        _require(type(row.get("generation_seed")) is int, f"Missing generation seed at {job_id}")
        _require(row["generation_seed"] == cli_seed + repeat + 1,
                 f"Generation seed does not match the frozen formula at {job_id}")
        digest = row.get("request_messages_sha256")
        _require(isinstance(digest, str) and len(digest) == 64, f"Missing request hash at {job_id}")
        _require(isinstance(row.get("request_started_utc"), str)
                 and isinstance(row.get("response_completed_utc"), str),
                 f"Missing request timestamps at {job_id}")
        usage = row.get("usage")
        _require(isinstance(usage, dict), f"Missing usage at {job_id}")
        _require(usage.get("is_byok") is True, f"Unexpected billing mode at {job_id}")
        for key in ("prompt_tokens", "completion_tokens"):
            _require(type(usage.get(key)) is int and usage[key] >= 0, f"Missing/invalid {key} at {job_id}")
        details = usage.get("cost_details")
        upstream_cost = details.get("upstream_inference_cost") if isinstance(details, dict) else None
        _require(_number(upstream_cost) is not None and _number(upstream_cost) > 0,
                 f"Missing positive upstream cost at {job_id}")
        _require(_number(usage.get("cost")) is not None and _number(usage.get("cost")) >= 0,
                 f"Missing/invalid OpenRouter cost receipt at {job_id}")
        prompt_details = usage.get("prompt_tokens_details")
        _require(isinstance(prompt_details, dict), f"Missing cache-token details at {job_id}")
        for cache_key in ("cached_tokens", "cache_write_tokens"):
            cache_value = prompt_details.get(cache_key)
            _require(type(cache_value) is int and cache_value >= 0,
                     f"Missing/invalid {cache_key} at {job_id}")
        _require(prompt_details["cached_tokens"] <= usage["prompt_tokens"],
                 f"Cached tokens exceed prompt tokens at {job_id}")
        prompt_cost = details.get("upstream_inference_prompt_cost") if isinstance(details, dict) else None
        completion_cost = details.get("upstream_inference_completions_cost") if isinstance(details, dict) else None
        _require(_number(prompt_cost) is not None and _number(prompt_cost) >= 0
                 and _number(completion_cost) is not None and _number(completion_cost) >= 0,
                 f"Missing upstream cost components at {job_id}")
        _require(math.isclose(float(prompt_cost) + float(completion_cost), float(upstream_cost),
                              rel_tol=1e-4, abs_tol=1e-8),
                 f"Upstream cost components do not reconcile at {job_id}")
        expected = row.get("expected")
        choice = row.get("choice")
        scoreable = row.get("normal") is True and choice in {"A", "B", "C", "D"}
        _require(row.get("valid_structured_choice") is (choice in {"A", "B", "C", "D"}),
                 f"Choice-validity flag disagrees with answer at {job_id}")
        _require(row.get("correct") is (scoreable and choice == expected),
                 f"Correctness flag disagrees with response at {job_id}")
        for latency_key in ("end_to_end_ms", "sift_preprocessing_ms"):
            latency = row.get(latency_key)
            if latency_key == "sift_preprocessing_ms" and arm == "full":
                _require(latency is None, f"Full-context arm must not claim Sift preprocessing at {job_id}")
            elif latency_key == "sift_preprocessing_ms" or latency is not None:
                _require(_number(latency) is not None and _number(latency) >= 0,
                         f"Missing/invalid {latency_key} at {job_id}")
        ttft_value = row.get("ttft_ms")
        if ttft_value is not None:
            _require(_number(ttft_value) is not None and _number(ttft_value) >= 0,
                     f"Invalid ttft_ms at {job_id}")

    case_ids = sorted({case_id for case_id, _ in by_pair})
    _require(set(case_ids) == set(frozen_by_id), "Run case IDs do not exactly match the frozen manifest")
    _require(len(case_ids) == EXPECTED_CASES, f"Expected 100 case IDs, found {len(case_ids)}")
    _require(len(by_pair) == EXPECTED_CASES * EXPECTED_REPEATS,
             f"Expected 300 task-repeat pairs, found {len(by_pair)}")
    for (case_id, repeat), pair in by_pair.items():
        _require(set(pair) == set(EXPECTED_ARMS), f"Incomplete paired result for {case_id} repeat {repeat}")
        full, sift = pair["full"], pair["sift"]
        _require(full.get("expected") == sift.get("expected"), f"Answer key mismatch for {case_id}")
        _require(full.get("generation_seed") == sift.get("generation_seed"),
                 f"Paired generation seed mismatch for {case_id} repeat {repeat}")
        _require(full.get("request_messages_sha256") != sift.get("request_messages_sha256"),
                 f"Full and Sift outbound message hashes unexpectedly match for {case_id}")
    for case_id in case_ids:
        for arm in EXPECTED_ARMS:
            hashes = {by_pair[(case_id, repeat)][arm]["request_messages_sha256"]
                      for repeat in range(1, EXPECTED_REPEATS + 1)}
            _require(len(hashes) == 1, f"Outbound request changed between repeats for {case_id} {arm} arm")
    for (case_id, repeat), pair in by_pair.items():
        _require(pair["full"].get("expected") == by_pair[(case_id, 1)]["full"].get("expected"),
                 f"Answer key changed between repeats for {case_id}")
    for arm in EXPECTED_ARMS:
        _require(len(by_arm[arm]) == EXPECTED_CASES * EXPECTED_REPEATS,
                 f"Expected 300 {arm} responses, found {len(by_arm[arm])}")

    task_results: dict[str, dict[str, Any]] = {}
    for case_id in case_ids:
        task_results[case_id] = {}
        for arm in EXPECTED_ARMS:
            rows = [by_pair[(case_id, repeat)][arm] for repeat in range(1, EXPECTED_REPEATS + 1)]
            correct = sum(row.get("correct") is True for row in rows)
            task_results[case_id][arm] = {
                "correct_repeats": correct,
                "majority_correct": correct >= 2,
                "invalid_repeats": sum(
                    row.get("normal") is not True or row.get("valid_structured_choice") is not True
                    for row in rows
                ),
            }

    both = full_only = sift_only = neither = 0
    differences = []
    for case_id in case_ids:
        full_correct = task_results[case_id]["full"]["majority_correct"]
        sift_correct = task_results[case_id]["sift"]["majority_correct"]
        if full_correct and sift_correct:
            both += 1
        elif full_correct:
            full_only += 1
        elif sift_correct:
            sift_only += 1
        else:
            neither += 1
        differences.append(int(sift_correct) - int(full_correct))

    arm_results: dict[str, Any] = {}
    per_repeat: dict[str, Any] = {}
    paired_request_wall_ms: list[float] = []
    paired_ttft_ms: list[float] = []
    for pair in by_pair.values():
        full_row, sift_row = pair["full"], pair["sift"]
        full_wall = _number(full_row.get("end_to_end_ms"))
        sift_wall = _number(sift_row.get("end_to_end_ms"))
        if full_wall is not None and sift_wall is not None:
            paired_request_wall_ms.append(sift_wall - full_wall)
        full_ttft = _number(full_row.get("ttft_ms"))
        sift_ttft = _number(sift_row.get("ttft_ms"))
        if full_ttft is not None and sift_ttft is not None:
            paired_ttft_ms.append(sift_ttft - full_ttft)
    for arm in EXPECTED_ARMS:
        rows = by_arm[arm]
        prompt_tokens = [int(row["usage"]["prompt_tokens"]) for row in rows]
        completion_tokens = [int(row["usage"]["completion_tokens"]) for row in rows]
        cached_tokens = [row["usage"]["prompt_tokens_details"]["cached_tokens"] for row in rows]
        cache_write_tokens = [row["usage"]["prompt_tokens_details"]["cache_write_tokens"] for row in rows]
        upstream_costs = [float(row["usage"]["cost_details"]["upstream_inference_cost"]) for row in rows]
        openrouter_costs = [
            _number(row["usage"].get("cost")) for row in rows
            if _number(row["usage"].get("cost")) is not None
        ]
        openrouter_cost_missing = sum(_number(row["usage"].get("cost")) is None for row in rows)
        uncached_costs = [
            (row["usage"]["prompt_tokens"] * input_price
             + row["usage"]["completion_tokens"] * output_price) / 1_000_000
            for row in rows
        ]
        cached_adjusted_costs = [
            ((row["usage"]["prompt_tokens"] -
              row["usage"]["prompt_tokens_details"]["cached_tokens"]) * input_price
             + row["usage"]["prompt_tokens_details"]["cached_tokens"] * cache_read_price
             + row["usage"]["completion_tokens"] * output_price) / 1_000_000
            for row in rows
        ]
        _require(all(cached <= prompt for cached, prompt in zip(cached_tokens, prompt_tokens)),
                 f"Cached tokens exceed prompt tokens in {arm} arm")
        correct_responses = sum(row.get("correct") is True for row in rows)
        valid_responses = sum(row.get("valid_structured_choice") is True for row in rows)
        majority_correct = sum(task_results[case_id][arm]["majority_correct"] for case_id in case_ids)
        prep_ms = [float(row["sift_preprocessing_ms"]) for row in rows
                   if arm == "sift" and _number(row.get("sift_preprocessing_ms")) is not None]
        if arm == "sift":
            _require(len(prep_ms) == len(rows), "Sift preprocessing time is missing from a request")
        else:
            _require(all(row.get("sift_preprocessing_ms") is None for row in rows),
                     "Full-context arm must have null Sift preprocessing time")
        ttft = [float(row["ttft_ms"]) for row in rows if _number(row.get("ttft_ms")) is not None]
        end_to_end = [float(row["end_to_end_ms"]) for row in rows
                      if _number(row.get("end_to_end_ms")) is not None]
        arm_results[arm] = {
            "requests": len(rows),
            "response_level": {
                "correct": correct_responses,
                "responses": len(rows),
                "accuracy": correct_responses / len(rows),
                "valid_choices": valid_responses,
                "invalid_choices": len(rows) - valid_responses,
            },
            "task_majority": {"correct": majority_correct, "tasks": len(case_ids),
                              "accuracy": majority_correct / len(case_ids)},
            "provider_prompt_tokens": {"total": sum(prompt_tokens), **_distribution([float(x) for x in prompt_tokens])},
            "completion_tokens": {"total": sum(completion_tokens), **_distribution([float(x) for x in completion_tokens])},
            "cached_prompt_tokens": {
                "total": sum(cached_tokens),
                "fraction_of_prompt_tokens": sum(cached_tokens) / sum(prompt_tokens) if sum(prompt_tokens) else None,
            },
            "cache_write_tokens": {"total": sum(cache_write_tokens),
                                   "all_zero": all(value == 0 for value in cache_write_tokens)},
            "cache_inclusive_upstream_cost_usd": sum(upstream_costs),
            "openrouter_reported_cost_usd": sum(openrouter_costs),
            "openrouter_cost_receipts_missing": openrouter_cost_missing,
            "reconstructed_uncached_cost_usd": sum(uncached_costs),
            "reconstructed_cache_adjusted_cost_usd": (
                sum(cached_adjusted_costs) if all(value == 0 for value in cache_write_tokens) else None
            ),
            "ttft_ms": _distribution(ttft),
            "end_to_end_ms": _distribution(end_to_end),
            "sift_preprocessing_ms": _distribution(prep_ms) if arm == "sift" else None,
        }
        for repeat in range(1, EXPECTED_REPEATS + 1):
            repeat_rows = [row for row in rows if row.get("repeat") == repeat]
            per_repeat.setdefault(str(repeat), {})[arm] = {
                "requests": len(repeat_rows),
                "correct": sum(row.get("correct") is True for row in repeat_rows),
                "accuracy": sum(row.get("correct") is True for row in repeat_rows) / len(repeat_rows),
                "prompt_tokens": sum(int(row["usage"]["prompt_tokens"]) for row in repeat_rows),
                "cached_tokens": sum(int((row["usage"].get("prompt_tokens_details") or {}).get("cached_tokens", 0))
                                      for row in repeat_rows),
                "upstream_cost_usd": sum(float(row["usage"]["cost_details"]["upstream_inference_cost"])
                                          for row in repeat_rows),
                "uncached_cost_usd": sum(
                    (row["usage"]["prompt_tokens"] * input_price
                     + row["usage"]["completion_tokens"] * output_price) / 1_000_000
                    for row in repeat_rows
                ),
            }

    full = arm_results["full"]
    sift = arm_results["sift"]
    summary = {
        "schema_version": 1,
        "evaluation": "LongBench v2 100-task MiniMax M3 development sample",
        "analyzed_utc": datetime.now(timezone.utc).isoformat(),
        "analysis": {
            "script": Path(__file__).as_posix(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "bootstrap_seed": bootstrap_seed,
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "input_price_per_million_usd": input_price,
            "cache_read_price_per_million_usd": cache_read_price,
            "output_price_per_million_usd": output_price,
        },
        "run": {
            "status": report.get("status"),
            "created_utc": report.get("created_utc"),
            "completed_utc": report.get("completed_utc"),
            "wall_clock_seconds": _elapsed_seconds(report.get("created_utc"), report.get("completed_utc")),
            "model": report.get("model"),
            "route": report.get("route"),
            "provider_endpoint": report.get("provider_endpoint"),
            "source_hashes": report.get("source_hashes"),
            "manifest_sha256": report.get("manifest_sha256"),
            "execution": report.get("execution"),
            "preparation": report.get("preparation"),
        },
        "sample": {"cases": len(case_ids), "repeats": EXPECTED_REPEATS,
                   "responses_per_arm": len(by_arm["full"]),
                   "limitations": ["length-conditioned sample of public training split",
                                   "not a full-suite score or blind holdout",
                                   "MiniMax implicit prompt caching is enabled; first repeat is not necessarily cold"]},
        "quality": {
            "paired_task_majority": {
                "both_correct": both,
                "full_only": full_only,
                "sift_only": sift_only,
                "neither": neither,
                "sift_minus_full_accuracy_difference": (sift_only - full_only) / len(case_ids),
                "exact_mcnemar_two_sided_p": _exact_binomial_two_sided(sift_only, full_only),
                "difference_ci95": _majority_ci(differences, bootstrap_seed),
            },
            "arms": {arm: {"response_level": arm_results[arm]["response_level"],
                           "task_majority": arm_results[arm]["task_majority"]}
                     for arm in EXPECTED_ARMS},
            "by_domain": {},
        },
        "efficiency": {
            "input_token_reduction_fraction": _savings(
                float(full["provider_prompt_tokens"]["total"]),
                float(sift["provider_prompt_tokens"]["total"])),
            "cache_inclusive_upstream_cost_savings_fraction": _savings(
                float(full["cache_inclusive_upstream_cost_usd"]),
                float(sift["cache_inclusive_upstream_cost_usd"])),
            "reconstructed_uncached_cost_savings_fraction": _savings(
                float(full["reconstructed_uncached_cost_usd"]),
                float(sift["reconstructed_uncached_cost_usd"])),
            "reconstructed_cache_adjusted_cost_savings_fraction": (
                _savings(float(full["reconstructed_cache_adjusted_cost_usd"]),
                         float(sift["reconstructed_cache_adjusted_cost_usd"]))
                if full["reconstructed_cache_adjusted_cost_usd"] is not None
                and sift["reconstructed_cache_adjusted_cost_usd"] is not None
                else None
            ),
            "rates_usd_per_million_tokens": {"uncached_input": input_price,
                                             "cache_read_input": cache_read_price,
                                             "output": output_price},
            "rate_note": "Counterfactual reconstructions use configured endpoint rates and are not observed invoices.",
        },
        "arms": arm_results,
        "latency": {
            "paired_sift_minus_full_request_wall_ms": _distribution(paired_request_wall_ms),
            "paired_sift_minus_full_ttft_ms": _distribution(paired_ttft_ms),
            "pairing_unit": "same task and repeat; lower values favor Sift",
        },
        "per_repeat": per_repeat,
    }
    for domain in sorted({row.get("domain", "unknown") for row in samples}):
        ids = [case_id for case_id in case_ids
               if any(row.get("case_id") == case_id and row.get("domain", "unknown") == domain for row in samples)]
        summary["quality"]["by_domain"][domain] = {
            arm: {
                "majority_correct": sum(task_results[case_id][arm]["majority_correct"] for case_id in ids),
                "tasks": len(ids),
                "majority_accuracy": (sum(task_results[case_id][arm]["majority_correct"] for case_id in ids) / len(ids))
                if ids else None,
            }
            for arm in EXPECTED_ARMS
        }
    for repeat, arms in per_repeat.items():
        arms["savings"] = {
            "input_token_reduction_fraction": _savings(
                arms["full"]["prompt_tokens"], arms["sift"]["prompt_tokens"]),
            "cache_inclusive_cost_reduction_fraction": _savings(
                arms["full"]["upstream_cost_usd"], arms["sift"]["upstream_cost_usd"]),
            "reconstructed_uncached_cost_reduction_fraction": _savings(
                arms["full"]["uncached_cost_usd"], arms["sift"]["uncached_cost_usd"]),
        }
    return summary


def markdown(summary: dict[str, Any]) -> str:
    quality = summary["quality"]
    efficiency = summary["efficiency"]
    arms = summary["arms"]
    pair = quality["paired_task_majority"]
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{100 * value:.1f}%"
    def usd(value: float | None) -> str:
        return "n/a" if value is None else f"${value:.4f}"
    def milliseconds(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0f} ms"
    lines = [
        "# LongBench v2 MiniMax M3 results",
        "",
        f"Run: `{summary['run'].get('created_utc')}` · Model: `{summary['run'].get('model')}` · "
        f"{summary['sample']['cases']} tasks × {summary['sample']['repeats']} repeats",
        "",
        "## Quality",
        "",
        "| Measure | Full context | Sift |",
        "|---|---:|---:|",
        f"| Correct responses | {arms['full']['response_level']['correct']}/{arms['full']['response_level']['responses']} "
        f"({pct(arms['full']['response_level']['accuracy'])}) | {arms['sift']['response_level']['correct']}/"
        f"{arms['sift']['response_level']['responses']} ({pct(arms['sift']['response_level']['accuracy'])}) |",
        f"| Correct task majorities | {arms['full']['task_majority']['correct']}/{arms['full']['task_majority']['tasks']} "
        f"({pct(arms['full']['task_majority']['accuracy'])}) | {arms['sift']['task_majority']['correct']}/"
        f"{arms['sift']['task_majority']['tasks']} ({pct(arms['sift']['task_majority']['accuracy'])}) |",
        f"| Invalid choices | {arms['full']['response_level']['invalid_choices']} | {arms['sift']['response_level']['invalid_choices']} |",
        "",
        f"Task-majority pairs: **{pair['both_correct']} both correct**, **{pair['full_only']} full only**, "
        f"**{pair['sift_only']} Sift only**, **{pair['neither']} neither**. Sift–full difference: "
        f"{pct(pair['sift_minus_full_accuracy_difference'])}; 95% task-cluster bootstrap CI "
        f"[{pct(pair['difference_ci95']['ci95_low'])}, {pct(pair['difference_ci95']['ci95_high'])}]; "
        f"exact McNemar p={pair['exact_mcnemar_two_sided_p']:.4g}.",
        "",
        "## Efficiency",
        "",
        "| Measure | Full context | Sift | Reduction with Sift |",
        "|---|---:|---:|---:|",
        f"| Provider prompt tokens | {arms['full']['provider_prompt_tokens']['total']:,} | "
        f"{arms['sift']['provider_prompt_tokens']['total']:,} | {pct(efficiency['input_token_reduction_fraction'])} |",
        f"| Cache-inclusive upstream cost | {usd(arms['full']['cache_inclusive_upstream_cost_usd'])} | "
        f"{usd(arms['sift']['cache_inclusive_upstream_cost_usd'])} | "
        f"{pct(efficiency['cache_inclusive_upstream_cost_savings_fraction'])} |",
        f"| Reconstructed uncached cost | {usd(arms['full']['reconstructed_uncached_cost_usd'])} | "
        f"{usd(arms['sift']['reconstructed_uncached_cost_usd'])} | "
        f"{pct(efficiency['reconstructed_uncached_cost_savings_fraction'])} |",
        f"| Reconstructed cache-adjusted cost | {usd(arms['full']['reconstructed_cache_adjusted_cost_usd'])} | "
        f"{usd(arms['sift']['reconstructed_cache_adjusted_cost_usd'])} | "
        f"{pct(efficiency['reconstructed_cache_adjusted_cost_savings_fraction'])} |",
        "",
        f"Cached prompt-token fractions: full {pct(arms['full']['cached_prompt_tokens']['fraction_of_prompt_tokens'])}; "
        f"Sift {pct(arms['sift']['cached_prompt_tokens']['fraction_of_prompt_tokens'])}.",
        "",
        "## Latency and scope",
        "",
        f"Median TTFT: full {milliseconds(arms['full']['ttft_ms']['median'])}, "
        f"Sift {milliseconds(arms['sift']['ttft_ms']['median'])}. "
        f"Median request wall time: full {milliseconds(arms['full']['end_to_end_ms']['median'])}, "
        f"Sift {milliseconds(arms['sift']['end_to_end_ms']['median'])}. "
        f"Median paired request wall-time difference (Sift − full): "
        f"{milliseconds(summary['latency']['paired_sift_minus_full_request_wall_ms']['median'])}; "
        f"paired TTFT difference: {milliseconds(summary['latency']['paired_sift_minus_full_ttft_ms']['median'])}. "
        f"Median Sift preprocessing: {milliseconds(arms['sift']['sift_preprocessing_ms']['median'])} per request.",
        "",
        "The task-cluster bootstrap interval is exploratory and conditional on this quota-balanced sample.",
        "",
        "This is a length-conditioned sample from the public LongBench v2 training split, not a full-suite score or blind holdout. "
        "MiniMax implicit caching was enabled; the observed cost is cache-inclusive upstream-reported pass-through cost, not an invoice. "
        "The uncached and cache-adjusted cost rows are reconstructions, not observed charges.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Completed runner JSON report")
    parser.add_argument("--manifest", type=Path, required=True, help="Exact frozen manifest used for this run")
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--input-price-per-million", type=float, default=0.30)
    parser.add_argument("--cache-read-price-per-million", type=float, default=0.06)
    parser.add_argument("--output-price-per-million", type=float, default=1.20)
    parser.add_argument("--bootstrap-seed", type=int, default=20261022)
    args = parser.parse_args()
    for price in (args.input_price_per_million, args.cache_read_price_per_million,
                  args.output_price_per_million):
        _require(math.isfinite(price) and price >= 0, "Prices must be finite and nonnegative")
    report = json.loads(args.input.read_text(encoding="utf-8"))
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    summary = analyze(report, manifest, manifest_sha256,
                      args.input_price_per_million, args.output_price_per_million,
                      args.cache_read_price_per_million, args.bootstrap_seed)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown(summary), encoding="utf-8")
    print(json.dumps({"status": "complete", "cases": summary["sample"]["cases"],
                      "json": str(args.json_output), "markdown": str(args.markdown_output)}, indent=2))


if __name__ == "__main__":
    main()
