"""Analyze the six-case MiniMax relation-matrix v3 follow-up.

This is an exploratory gate over six prompts selected by the offline
relation-closure sweep. It compares default Sift and option-aligned complete-
entity matrix treatment within the same interleaved run; historical Full/Sift rows remain non-concurrent
references and can be affected by provider/model drift.

Example::

    python benchmarks/analyze_longbench_v2_minimax_relation_followup_v3.py \
      --followup docs/results/followup.json \
      --historical docs/results/longbench-v2-minimax-m3-100-2026-10-16.json \
      --manifest docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json \
      --stage-manifest docs/evals/longbench-v2-minimax-relation-stage1-manifest-2026-10-16.json \
      --route-metadata docs/evals/longbench-v2-minimax-stage1-route-2026-10-16.json \
      --json-output docs/results/relation-followup-analysis.json \
      --markdown-output docs/evals/relation-followup-analysis.md
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
import sys
from typing import Any


EXPECTED_CASES = (
    "672494e5bb02136c067d7697",
    "67249705bb02136c067d76d1",
    "6724c1d4bb02136c067d77ec",
    "67285e1dbb02136c067d901b",
    "67286036bb02136c067d9092",
    "6724c4aabb02136c067d78a6",
)
EXPECTED_REPEATS = (1, 2, 3)
EXPECTED_FOLLOWUP_ARMS = ("sift_default", "sift_relation_matrix_v3")
MODEL = "minimax/minimax-m3"
TARGET_TOKENS = 32_768
EFFECTIVE_TARGET_TOKENS = 32_640
MAX_PROVIDER_LOCAL_RATIO = 1.05
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from longbench_v3_gate import expansion_gate  # noqa: E402


class AnalysisError(ValueError):
    """Raised when the result does not satisfy the frozen six-case gate."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _nonnegative(value: Any, label: str) -> float:
    number = _finite_number(value)
    _require(number is not None and number >= 0, f"Missing or invalid {label}")
    assert number is not None
    return number


def _utc(value: Any, label: str) -> datetime:
    _require(isinstance(value, str), f"Missing {label}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AnalysisError(f"Invalid {label}: {value!r}") from error
    _require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return parsed


def _score(row: dict[str, Any], label: str) -> dict[str, Any]:
    choice = row.get("choice")
    valid = row.get("normal") is True and choice in {"A", "B", "C", "D"}
    _require(row.get("valid_structured_choice") is (choice in {"A", "B", "C", "D"}),
             f"{label}: structured-choice flag disagrees with choice")
    correct = valid and choice == row.get("expected")
    _require(row.get("correct") is correct, f"{label}: correctness flag disagrees with answer")
    return {"choice": choice, "valid": valid, "correct": correct}


def _parse_json_object_answer(text: Any) -> str | None:
    """Mirror the v2 runner's strict single-key JSON answer parser."""
    if not isinstance(text, str):
        return None

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if (not isinstance(value, dict) or set(value) != {"answer"}
            or value.get("answer") not in {"A", "B", "C", "D"}):
        return None
    return value["answer"]


def _validate_receipt(row: dict[str, Any], *, label: str, followup: bool) -> dict[str, Any]:
    _require(row.get("http_status") == 200, f"{label}: HTTP status is not 200")
    _require(row.get("model") == MODEL, f"{label}: unexpected model {row.get('model')!r}")
    provider = row.get("provider")
    _require(isinstance(provider, str) and provider.strip().casefold() == "minimax",
             f"{label}: provider is not MiniMax")
    _require(row.get("cost_receipt_status") == "reported", f"{label}: cost receipt is not reported")
    usage = row.get("usage")
    _require(isinstance(usage, dict), f"{label}: missing usage object")
    _require(usage.get("is_byok") is True, f"{label}: usage is not marked BYOK")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    _require(type(prompt_tokens) is int and prompt_tokens > 0, f"{label}: missing prompt token receipt")
    _require(type(completion_tokens) is int and completion_tokens >= 0,
             f"{label}: missing completion token receipt")
    details = usage.get("cost_details")
    _require(isinstance(details, dict), f"{label}: missing upstream cost details")
    upstream_cost = _nonnegative(details.get("upstream_inference_cost"), f"{label} upstream cost")
    _require(upstream_cost > 0, f"{label}: upstream cost receipt must be positive")
    prompt_cost = _nonnegative(details.get("upstream_inference_prompt_cost"), f"{label} prompt cost")
    completion_cost = _nonnegative(
        details.get("upstream_inference_completions_cost"), f"{label} completion cost"
    )
    _require(math.isclose(prompt_cost + completion_cost, upstream_cost, rel_tol=1e-4, abs_tol=1e-8),
             f"{label}: upstream cost components do not reconcile")
    local_tokens = row.get("local_rendered_prompt_tokens")
    _require(type(local_tokens) is int and local_tokens > 0, f"{label}: missing local prompt token count")
    ratio = _finite_number(row.get("provider_local_input_token_ratio"))
    if followup:
        _require(type(row.get("strict_sample_valid")) is bool,
                 f"{label}: strict sample validity flag is missing")
        _require(ratio is not None and 0 < ratio <= MAX_PROVIDER_LOCAL_RATIO,
                 f"{label}: provider/local input ratio is missing or exceeds guard")
        _require(prompt_tokens / local_tokens <= MAX_PROVIDER_LOCAL_RATIO,
                 f"{label}: actual provider/local prompt ratio exceeds guard")
    usage_openrouter_cost = _finite_number(usage.get("cost"))
    _require(usage_openrouter_cost is not None and usage_openrouter_cost >= 0,
             f"{label}: missing OpenRouter cost receipt")
    prompt_details = usage.get("prompt_tokens_details")
    _require(isinstance(prompt_details, dict), f"{label}: missing prompt token details")
    cached_tokens = prompt_details.get("cached_tokens")
    cache_write_tokens = prompt_details.get("cache_write_tokens")
    _require(type(cached_tokens) is int and 0 <= cached_tokens <= prompt_tokens,
             f"{label}: invalid cached prompt-token count")
    _require(type(cache_write_tokens) is int and 0 <= cache_write_tokens <= prompt_tokens - cached_tokens,
             f"{label}: invalid cache-write token count")
    _require(cached_tokens + cache_write_tokens <= prompt_tokens,
             f"{label}: cached and cache-write prompt tokens exceed provider prompt tokens")
    return {
        "case_id": row.get("case_id"),
        "repeat": row.get("repeat"),
        "arm": row.get("arm"),
        "local_prompt_tokens": local_tokens,
        "provider_prompt_tokens": prompt_tokens,
        "cached_prompt_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "completion_tokens": completion_tokens,
        "upstream_cost_usd": upstream_cost,
        "openrouter_reported_cost_usd": usage_openrouter_cost,
        "provider_local_input_token_ratio": ratio,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_provenance(followup: dict[str, Any], historical: dict[str, Any], *,
                      historical_path: Path, baseline_manifest_path: Path,
                      stage_manifest_path: Path, route_metadata_path: Path) -> dict[str, Any]:
    """Check every supplied artifact hash against report/stage declarations and the checkout."""
    stage_raw = stage_manifest_path.read_bytes()
    route_raw = route_metadata_path.read_bytes()
    baseline_manifest_raw = baseline_manifest_path.read_bytes()
    historical_raw = historical_path.read_bytes()
    stage = json.loads(stage_raw.decode("utf-8-sig"))
    route_doc = json.loads(route_raw.decode("utf-8-sig"))
    baseline_manifest = json.loads(baseline_manifest_raw.decode("utf-8-sig"))
    _require(isinstance(stage, dict) and isinstance(route_doc, dict)
             and isinstance(baseline_manifest, dict), "Provenance inputs must be JSON objects")
    stage_hash = hashlib.sha256(stage_raw).hexdigest()
    route_hash = hashlib.sha256(route_raw).hexdigest()
    baseline_manifest_hash = hashlib.sha256(baseline_manifest_raw).hexdigest()
    historical_hash = hashlib.sha256(historical_raw).hexdigest()

    _require(followup.get("stage_manifest_sha256") == stage_hash,
             "Follow-up report stage_manifest_sha256 does not match the supplied stage manifest")
    _require(followup.get("baseline_manifest_sha256") == baseline_manifest_hash
             and historical.get("manifest_sha256") == baseline_manifest_hash
             and stage.get("baseline_manifest_sha256") == baseline_manifest_hash,
             "Baseline manifest hash does not match the report, historical result and stage manifest")
    _require(stage.get("baseline_result_sha256") == historical_hash,
             "Stage manifest baseline_result_sha256 does not match the supplied historical result")
    stage_route_hash = stage.get("route_metadata_sha256")
    report_sources = followup.get("source_hashes")
    _require(isinstance(report_sources, dict), "Follow-up report source_hashes are missing")
    _require(stage_route_hash == route_hash == report_sources.get("route_metadata_sha256"),
             "Route metadata hash does not match the stage manifest and follow-up report")
    reported_route = followup.get("route_metadata")
    _require(isinstance(reported_route, dict)
             and reported_route.get("metadata_sha256") == route_hash,
             "Follow-up route_metadata metadata_sha256 does not match the supplied route snapshot")
    _require(isinstance(reported_route.get("provider_name", "MiniMax"), str)
             and reported_route.get("provider_name", "MiniMax").casefold() == "minimax"
             and reported_route.get("model_id", MODEL) == MODEL,
             "Follow-up route metadata does not identify the pinned MiniMax model")

    declared_route_path = stage.get("route_metadata_path")
    _require(isinstance(declared_route_path, str), "Stage manifest route_metadata_path is missing")
    declared_route_resolved = Path(declared_route_path)
    if not declared_route_resolved.is_absolute():
        declared_route_resolved = ROOT / declared_route_resolved
    _require(declared_route_resolved.resolve() == route_metadata_path.resolve(),
             "Supplied route metadata path differs from the stage manifest")

    stage_sources = stage.get("source_hashes")
    _require(isinstance(stage_sources, dict), "Stage manifest source_hashes are missing")
    _require(followup.get("source_hashes", {}).get("stage_manifest_source_hashes") == stage_sources,
             "Follow-up source hashes do not preserve the stage manifest source hash map")
    source_paths = {
        "followup_runner_sha256": ROOT / "benchmarks/run_longbench_v2_minimax_relation_followup_v3.py",
        "matrix_candidate_sha256": ROOT / "benchmarks/relation_matrix_candidate.py",
        "gate_module_sha256": ROOT / "benchmarks/longbench_v3_gate.py",
        "baseline_runner_sha256": ROOT / "benchmarks/run_longbench_v2_minimax.py",
        "baseline_protocol_sha256": ROOT / "docs/evals/longbench-v2-minimax-m3-100-protocol-2026-10-16.md",
        "dataset_preparation_module_sha256": ROOT / "benchmarks/prepare_longbench_v2.py",
        "m3_renderer_module_sha256": ROOT / "benchmarks/prepare_longbench_v2_minimax.py",
        "followup_core_sha256": ROOT / "src/sift/core.py",
        "stage_manifest_sha256": stage_manifest_path,
        "route_metadata_sha256": route_metadata_path,
    }
    for name, path in source_paths.items():
        expected = report_sources.get(name)
        _require(isinstance(expected, str) and len(expected) == 64 and path.is_file()
                 and _sha256(path) == expected,
                 f"Follow-up report {name} does not match the specified source file")

    frozen_sources = baseline_manifest.get("harness")
    _require(isinstance(frozen_sources, dict), "Baseline manifest harness source hashes are missing")
    _require(report_sources.get("baseline_core_sha256") == historical.get("sift_core_sha256")
             and report_sources.get("tokenizer_sha256") == baseline_manifest.get("model", {}).get("tokenizer_sha256")
             and report_sources.get("chat_template_sha256") == baseline_manifest.get("model", {}).get("chat_template_sha256"),
             "Reported baseline core/tokenizer/template hashes disagree with frozen baseline metadata")
    for key, path_key in (
        ("baseline_runner_sha256", "runner_path"),
        ("baseline_protocol_sha256", "protocol_path"),
        ("dataset_preparation_module_sha256", "dataset_preparation_module_path"),
        ("m3_renderer_module_sha256", "m3_renderer_module_path"),
    ):
        path_value = baseline_manifest.get("harness", {}).get(path_key)
        digest_key = {
            "baseline_runner_sha256": "runner_sha256",
            "baseline_protocol_sha256": "protocol_sha256",
            "dataset_preparation_module_sha256": "dataset_preparation_module_sha256",
            "m3_renderer_module_sha256": "m3_renderer_module_sha256",
        }[key]
        _require(report_sources.get(key) == frozen_sources.get(digest_key),
                 f"Report {key} differs from the frozen baseline manifest")
        _require(path_value is not None and (ROOT / path_value).is_file()
                 and _sha256(ROOT / path_value) == frozen_sources.get(digest_key),
                 f"Frozen baseline source hash mismatch for {path_key}")

    stage_source_paths = {
        "runner_sha256": ROOT / "benchmarks/run_longbench_v2_minimax_relation_followup_v3.py",
        # The stage was frozen against the original analyzer; this corrected
        # post-run analyzer preserves that immutable provenance check.
        "analyzer_sha256": ROOT / "benchmarks/analyze_longbench_v2_minimax_relation_followup_v3.py",
        "matrix_candidate_sha256": ROOT / "benchmarks/relation_matrix_candidate.py",
        "gate_module_sha256": ROOT / "benchmarks/longbench_v3_gate.py",
        "core_sha256": ROOT / "src/sift/core.py",
        "protocol_sha256": ROOT / "docs/evals/longbench-v2-minimax-relation-stage1-v3-protocol-2026-10-17.md",
    }
    for key, path in stage_source_paths.items():
        expected = stage_sources.get(key)
        _require(isinstance(expected, str) and path.is_file() and _sha256(path) == expected,
                 f"Stage manifest {key} does not match the current specified source")
    route_data = route_doc.get("data", route_doc)
    if isinstance(route_data, dict) and isinstance(route_data.get("endpoints"), list):
        endpoint_matches = [row for row in route_data["endpoints"] if isinstance(row, dict)
                            and row.get("model_id") == MODEL
                            and isinstance(row.get("provider_name"), str)
                            and row["provider_name"].casefold() == "minimax"]
        _require(len(endpoint_matches) == 1, "Route metadata must identify exactly one MiniMax endpoint")
        pricing = endpoint_matches[0].get("pricing")
    else:
        pricing = route_data.get("pricing_usd_per_token") if isinstance(route_data, dict) else None
        _require(isinstance(route_data, dict) and route_data.get("requested_model") == MODEL,
                 "Normalized route metadata model is unexpected")
    _require(isinstance(pricing, dict), "Route metadata pricing is missing")
    try:
        input_price = float(pricing["prompt"]) * 1_000_000
        output_price = float(pricing["completion"]) * 1_000_000
        cache_read_price = float(pricing["input_cache_read"]) * 1_000_000
        cache_write_price = (
            float(pricing["input_cache_write"]) * 1_000_000
            if pricing.get("input_cache_write") is not None else None
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AnalysisError("Route metadata must provide input, output, and cache-read prices") from error
    _require(all(math.isfinite(value) and value >= 0
                 for value in (input_price, output_price, cache_read_price)),
             "Route metadata prices must be finite and nonnegative")
    _require(cache_write_price is None or math.isfinite(cache_write_price) and cache_write_price >= 0,
             "Route metadata cache-write price must be finite and nonnegative")
    _require(math.isclose(reported_route.get("input_usd_per_million", input_price), input_price,
                          rel_tol=1e-9, abs_tol=1e-9)
             and math.isclose(reported_route.get("output_usd_per_million", output_price), output_price,
                              rel_tol=1e-9, abs_tol=1e-9),
             "Run route metadata rates disagree with the supplied route snapshot")
    return {
        "stage_manifest_sha256": stage_hash,
        "route_metadata_sha256": route_hash,
        "baseline_manifest_sha256": baseline_manifest_hash,
        "historical_result_sha256": historical_hash,
        "validated_source_hashes": dict(report_sources),
        "input_price_usd_per_million": input_price,
        "output_price_usd_per_million": output_price,
        "cache_read_price_usd_per_million": cache_read_price,
        "cache_write_price_usd_per_million": cache_write_price,
    }


def _index_historical(report: dict[str, Any]) -> dict[tuple[str, int, str], dict[str, Any]]:
    _require(report.get("status") == "complete", "Historical run is not complete")
    _require(report.get("model") == MODEL, "Historical run uses an unexpected model")
    samples = report.get("samples")
    _require(isinstance(samples, list), "Historical run has no samples list")
    index: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in samples:
        if not isinstance(row, dict) or row.get("case_id") not in EXPECTED_CASES:
            continue
        if type(row.get("repeat")) is not int or row.get("arm") not in {"full", "sift"}:
            continue
        key = (row["case_id"], row["repeat"], row["arm"])
        _require(key not in index, f"Duplicate historical row: {key}")
        index[key] = row
    expected = {
        (case_id, repeat, arm)
        for case_id in EXPECTED_CASES
        for repeat in EXPECTED_REPEATS
        for arm in ("full", "sift")
    }
    _require(set(index) == expected, "Historical run must contain the six cases × three repeats × full/Sift")
    for key, row in index.items():
        _validate_receipt(row, label=f"historical {key}", followup=False)
        _score(row, f"historical {key}")
        _require(type(row.get("generation_seed")) is int, f"Historical {key}: missing generation seed")
    return index


def _summarize_repeats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [_score(row, f"{row.get('case_id')} repeat {row.get('repeat')}") for row in rows]
    correct = sum(score["correct"] for score in scores)
    return {
        "correct_repeats": correct,
        "valid_repeats": sum(score["valid"] for score in scores),
        "invalid_repeats": sum(not score["valid"] for score in scores),
        "majority_correct": correct >= 2,
        "choices": [score["choice"] if score["valid"] else None for score in scores],
    }


def _arm_receipt_accounting(rows: list[dict[str, Any]], validated: list[dict[str, Any]],
                           prices: dict[str, float]) -> dict[str, Any]:
    input_price = prices["input_price_usd_per_million"]
    output_price = prices["output_price_usd_per_million"]
    cache_read_price = prices["cache_read_price_usd_per_million"]
    cache_write_price = prices.get("cache_write_price_usd_per_million")
    cached_total = sum(item["cached_prompt_tokens"] for item in validated)
    prompt_total = sum(item["provider_prompt_tokens"] for item in validated)
    write_total = sum(item["cache_write_tokens"] for item in validated)
    uncached_counterfactual = sum(
        (item["provider_prompt_tokens"] * input_price + item["completion_tokens"] * output_price) / 1_000_000
        for item in validated
    )
    expected_cache_cost = 0.0
    checked_cache_cost_rows = 0
    skipped_cache_write_rows = 0
    validated_by_key = {
        (item["case_id"], item["repeat"], item["arm"]): item
        for item in validated
    }
    row_keys = [(row.get("case_id"), row.get("repeat"), row.get("arm")) for row in rows]
    _require(len(validated_by_key) == len(validated)
             and set(row_keys) == set(validated_by_key),
             "Receipt rows do not exactly match accounting rows by case, repeat, and arm")
    for row in rows:
        item = validated_by_key[(row.get("case_id"), row.get("repeat"), row.get("arm"))]
        completion_cost = float(row["usage"]["cost_details"]["upstream_inference_completions_cost"])
        reconstructed_completion_cost = item["completion_tokens"] * output_price / 1_000_000
        _require(math.isclose(reconstructed_completion_cost, completion_cost, rel_tol=1e-4, abs_tol=1e-8),
                 f"{row.get('case_id')} repeat {row.get('repeat')} {row.get('arm')}: completion-cost reconstruction disagrees with receipt")
        write_tokens = item["cache_write_tokens"]
        if write_tokens and cache_write_price is None:
            skipped_cache_write_rows += 1
            continue
        uncached_input_tokens = item["provider_prompt_tokens"] - item["cached_prompt_tokens"] - write_tokens
        reconstructed_prompt_cost = (
            uncached_input_tokens * input_price
            + item["cached_prompt_tokens"] * cache_read_price
            + write_tokens * (cache_write_price if cache_write_price is not None else input_price)
        ) / 1_000_000
        actual_prompt_cost = float(row["usage"]["cost_details"]["upstream_inference_prompt_cost"])
        _require(math.isclose(reconstructed_prompt_cost, actual_prompt_cost, rel_tol=1e-4, abs_tol=1e-8),
                 f"{row.get('case_id')} repeat {row.get('repeat')} {row.get('arm')}: cached prompt-cost reconstruction disagrees with receipt")
        expected_cache_cost += reconstructed_prompt_cost + (
            item["completion_tokens"] * output_price / 1_000_000
        )
        checked_cache_cost_rows += 1
    actual_upstream_cost = sum(item["upstream_cost_usd"] for item in validated)
    return {
        "requests": len(rows),
        "provider_prompt_tokens_total": prompt_total,
        "cached_prompt_tokens_total": cached_total,
        "cached_prompt_fraction_of_provider_prompt_tokens": cached_total / prompt_total if prompt_total else None,
        "cache_write_tokens_total": write_total,
        "completion_tokens_total": sum(item["completion_tokens"] for item in validated),
        "cache_inclusive_upstream_reported_cost_usd": actual_upstream_cost,
        "openrouter_reported_cost_usd": sum(item["openrouter_reported_cost_usd"] for item in validated),
        "reconstructed_uncached_cost_counterfactual_usd": uncached_counterfactual,
        "uncached_counterfactual_basis": "provider-reported prompt_tokens × uncached input rate + completion_tokens × output rate; counterfactual estimate, not observed billing",
        "cache_accounting_consistency": {
            "cached_tokens_within_prompt_tokens": cached_total <= prompt_total,
            "upstream_components_reconciled": True,
            "cache_inclusive_prompt_cost_rows_checked": checked_cache_cost_rows,
            "rows_not_reconstructable_due_to_missing_cache_write_rate": skipped_cache_write_rows,
            "reconstructed_cache_inclusive_cost_usd_for_checked_rows": expected_cache_cost,
            "interpretation": "Prompt-cost reconstructions are checked against upstream prompt cost where cache-read/write rates permit; upstream total is independently checked as prompt plus completion component.",
        },
    }


def analyze(followup: dict[str, Any], historical: dict[str, Any],
            prices: dict[str, float]) -> dict[str, Any]:
    _require(isinstance(prices, dict)
             and all(_finite_number(prices.get(key)) is not None
                     and _finite_number(prices.get(key)) >= 0
                     for key in ("input_price_usd_per_million", "output_price_usd_per_million",
                                 "cache_read_price_usd_per_million")),
             "Verified route input/output/cache-read prices are required for cost reconstruction")
    _require(followup.get("status") == "complete", f"Follow-up status is {followup.get('status')!r}")
    _require(followup.get("model") == MODEL, "Follow-up uses an unexpected model")
    execution = followup.get("protocol")
    _require(isinstance(execution, dict), "Follow-up does not record its protocol")
    declared_ids = execution.get("task_ids")
    _require(isinstance(declared_ids, list) and set(declared_ids) == set(EXPECTED_CASES)
             and len(declared_ids) == len(EXPECTED_CASES),
             "Follow-up protocol task IDs differ from the six offline-qualified cases")
    _require(execution.get("repeats") == 3, "Follow-up protocol must declare three repeats")
    _require(execution.get("arms") == list(EXPECTED_FOLLOWUP_ARMS),
             "Follow-up protocol must declare default Sift and relation-follow-up arms")
    _require(execution.get("sift_target_tokens") == TARGET_TOKENS,
             f"Follow-up target must be {TARGET_TOKENS} tokens")
    route = followup.get("route")
    _require(isinstance(route, dict), "Follow-up has no route declaration")
    _require(route.get("requested_model") == MODEL, "Route declaration model mismatch")
    provider_policy = route.get("provider")
    _require(isinstance(provider_policy, dict)
             and provider_policy.get("only") == ["minimax"]
             and provider_policy.get("allow_fallbacks") is False,
             "Follow-up route must pin MiniMax and disable provider fallbacks")
    _require(isinstance(followup.get("created_utc"), str)
             and isinstance(followup.get("completed_utc"), str),
             "Follow-up creation/completion timestamps are missing")
    followup_created = _utc(followup["created_utc"], "follow-up created_utc")
    followup_completed = _utc(followup["completed_utc"], "follow-up completed_utc")
    _require(followup_completed >= followup_created, "Follow-up completion predates creation")

    historical_index = _index_historical(historical)
    historical_completed = _utc(historical.get("completed_utc"), "historical completed_utc")
    _require(followup_created >= historical_completed,
             "Follow-up must start after historical run completion to qualify as non-concurrent")

    ordering = execution.get("arm_ordering")
    cli_seed = execution.get("cli_seed")
    _require(isinstance(ordering, dict)
             and ordering.get("strategy") == "shuffle_pairs_then_randomize_arm_order"
             and ordering.get("seed_formula") == "cli_seed + repeat"
             and ordering.get("one_worker") is True
             and type(cli_seed) is int
             and ordering.get("cli_seed") == cli_seed,
             "Follow-up must record seeded pair shuffling, randomized within-pair arm order, and one worker")
    samples = followup.get("samples")
    _require(isinstance(samples, list), "Follow-up has no samples list")
    expected_response_count = len(EXPECTED_CASES) * len(EXPECTED_REPEATS) * len(EXPECTED_FOLLOWUP_ARMS)
    _require(len(samples) == expected_response_count,
             f"Expected exactly {expected_response_count} follow-up responses, found {len(samples)}")
    followup_index: dict[tuple[str, int, str], dict[str, Any]] = {}
    receipt_rows_by_arm: dict[str, list[dict[str, Any]]] = {
        arm: [] for arm in EXPECTED_FOLLOWUP_ARMS
    }
    sample_job_ids: list[str] = []
    seen_job_ids: set[str] = set()
    for row in samples:
        _require(isinstance(row, dict), "Follow-up sample is not an object")
        case_id, repeat = row.get("case_id"), row.get("repeat")
        _require(case_id in EXPECTED_CASES and type(repeat) is int and repeat in EXPECTED_REPEATS,
                 f"Unexpected case/repeat pair: {case_id!r}/{repeat!r}")
        arm = row.get("arm")
        _require(arm in EXPECTED_FOLLOWUP_ARMS, f"Unexpected follow-up arm: {arm!r}")
        key = (case_id, repeat, arm)
        _require(key not in followup_index, f"Duplicate follow-up row: {key}")
        followup_index[key] = row
        job_id = row.get("job_id")
        expected_job_id = f"{case_id}:{repeat}:{arm}"
        _require(job_id == expected_job_id and job_id not in seen_job_ids,
                 f"{key}: missing, unexpected, or duplicate job_id {job_id!r}")
        seen_job_ids.add(job_id)
        sample_job_ids.append(job_id)
        pair_label = (case_id, repeat)
        _require(row.get("target_tokens") == TARGET_TOKENS, f"{key}: target differs from protocol")
        _require(type(row.get("generation_seed")) is int, f"{key}: missing generation seed")
        historical_full = historical_index[(case_id, repeat, "full")]
        historical_sift = historical_index[(case_id, repeat, "sift")]
        _require(row["generation_seed"] == historical_full.get("generation_seed")
                 == historical_sift.get("generation_seed"),
                 f"{key}: generation seed does not match both historical arms")
        _require(row.get("expected") == historical_full.get("expected") == historical_sift.get("expected"),
                 f"{key}: answer key differs from historical arms")
        request = row.get("request")
        _require(isinstance(request, dict), f"{key}: stored request payload is missing")
        try:
            canonical_request = json.dumps(
                request, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise AnalysisError(f"{key}: stored request payload cannot be canonicalized") from error
        request_hash = hashlib.sha256(canonical_request).hexdigest()
        _require(row.get("request_sha256") == request_hash,
                 f"{key}: request_sha256 does not match the stored request payload")
        _require(request.get("model") == MODEL and request.get("seed") == row["generation_seed"],
                 f"{key}: stored request model or seed disagrees with the sample")
        _require(request.get("provider") == {"only": ["minimax"], "allow_fallbacks": False},
                 f"{key}: stored request does not pin MiniMax without fallbacks")
        response_format = request.get("response_format")
        _require(isinstance(response_format, dict) and response_format.get("type") == "json_object",
                 f"{key}: stored request does not require JSON-object output")
        _require(type(request.get("temperature")) in (int, float)
                 and request.get("temperature") == 0.1,
                 f"{key}: stored request temperature differs from protocol")
        _require(type(request.get("top_p")) in (int, float)
                 and request.get("top_p") == 0.8,
                 f"{key}: stored request top_p differs from protocol")
        _require(type(request.get("max_tokens")) is int and request.get("max_tokens") == 128,
                 f"{key}: stored request output cap differs from protocol")
        _require(request.get("reasoning") == {"enabled": False},
                 f"{key}: stored request reasoning differs from protocol")
        _require(request.get("stream") is True
                 and request.get("stream_options") == {"include_usage": True},
                 f"{key}: stored request streaming/usage settings differ from protocol")
        _require(isinstance(request.get("messages"), list) and request["messages"],
                 f"{key}: stored request messages are missing")
        parsed_choice = _parse_json_object_answer(row.get("answer"))
        _require(parsed_choice == row.get("choice")
                 and row.get("valid_structured_choice") is (parsed_choice is not None),
                 f"{key}: JSON answer parsing disagrees with choice/valid_structured_choice")
        _require(row.get("strict_sample_valid") is _score(row, f"follow-up {key}")["valid"],
                 f"{key}: strict_sample_valid disagrees with completed answer validity")
        receipt_rows_by_arm[arm].append(_validate_receipt(row, label=f"follow-up {key}", followup=True))
        _score(row, f"follow-up {key}")

        local_tokens = row["local_rendered_prompt_tokens"]
        _require(local_tokens <= EFFECTIVE_TARGET_TOKENS,
                 f"{key}: selected prompt exceeds effective target {EFFECTIVE_TARGET_TOKENS}")
        if arm == "sift_relation_matrix_v3":
            candidate_ms = _finite_number(row.get("research_relation_candidate_ms"))
            _require(candidate_ms is not None and candidate_ms >= 0,
                     f"{key}: missing candidate-attempt preprocessing time")
            fallback_reason = row.get("research_relation_fallback_reason")
            selected_audit = row.get("selector_audit")
            _require(isinstance(selected_audit, dict), f"{key}: missing selected-selector audit")
            candidate_audit = row.get("research_relation_candidate_audit")
            if fallback_reason is None:
                _require(isinstance(candidate_audit, dict), f"{key}: selected candidate lacks candidate audit")
                _require(candidate_audit.get("method") == "research_relation_closure"
                         and candidate_audit.get("comparison_groups_complete") is True
                         and candidate_audit.get("unfit_comparison_groups") == 0,
                         f"{key}: candidate audit does not prove complete relation closure")
                _require(selected_audit.get("method") == "research_relation_closure+option_aligned_matrix_v3",
                         f"{key}: candidate marked selected but selected audit is another method")
                matrix_audit = row.get("relation_matrix_audit")
                _require(isinstance(matrix_audit, dict)
                         and matrix_audit.get("method") == "option_aligned_complete_entity_matrix_v3"
                         and matrix_audit.get("all_selected_entities_preserved") is True
                         and matrix_audit.get("all_entity_fields_preserved") is True
                         and matrix_audit.get("predicate_fields_filtered") is False
                         and matrix_audit.get("other_messages_unchanged") is True,
                         f"{key}: option-aligned complete-entity matrix audit is missing or invalid")
            else:
                _require(isinstance(fallback_reason, str) and fallback_reason,
                         f"{key}: invalid fallback reason")
                _require(selected_audit.get("method") != "research_relation_closure",
                         f"{key}: fallback reason conflicts with selected closure audit")
        else:
            _require(isinstance(row.get("selector_audit"), dict),
                     f"{key}: default Sift row lacks selector audit")

    expected_keys = {
        (case_id, repeat, arm)
        for case_id in EXPECTED_CASES for repeat in EXPECTED_REPEATS for arm in EXPECTED_FOLLOWUP_ARMS
    }
    _require(set(followup_index) == expected_keys,
             "Follow-up rows do not exactly cover six case × three repeat × two arm pairs")
    for case_id in EXPECTED_CASES:
        for repeat in EXPECTED_REPEATS:
            default = followup_index[(case_id, repeat, "sift_default")]
            candidate = followup_index[(case_id, repeat, "sift_relation_matrix_v3")]
            _require(default.get("generation_seed") == candidate.get("generation_seed"),
                     f"{case_id} repeat {repeat}: paired follow-up arms use different seeds")
            _require(default.get("expected") == candidate.get("expected"),
                     f"{case_id} repeat {repeat}: paired follow-up arms use different answer keys")

    dispatch_ids = ordering.get("dispatch_job_ids")
    _require(isinstance(dispatch_ids, list) and len(dispatch_ids) == expected_response_count
             and all(isinstance(job_id, str) for job_id in dispatch_ids)
             and len(set(dispatch_ids)) == expected_response_count,
             "Recorded randomized dispatch order must contain 36 unique job IDs")
    expected_job_ids = {
        f"{case_id}:{repeat}:{arm}"
        for case_id in EXPECTED_CASES for repeat in EXPECTED_REPEATS for arm in EXPECTED_FOLLOWUP_ARMS
    }
    _require(set(dispatch_ids) == expected_job_ids,
             "Recorded dispatch order does not correspond exactly to the validated 36 rows")
    _require(sample_job_ids == dispatch_ids,
             "Sample order does not match the recorded sequential dispatch order")
    dispatch_positions = {job_id: position for position, job_id in enumerate(dispatch_ids)}
    replayed_dispatch_ids: list[str] = []
    for repeat in EXPECTED_REPEATS:
        rng = random.Random(cli_seed + repeat)
        case_order = list(EXPECTED_CASES)
        rng.shuffle(case_order)
        for case_id in case_order:
            jobs = [f"{case_id}:{repeat}:{arm}" for arm in EXPECTED_FOLLOWUP_ARMS]
            rng.shuffle(jobs)
            replayed_dispatch_ids.extend(jobs)
            positions = sorted(dispatch_positions[job] for job in jobs)
            _require(positions[1] == positions[0] + 1,
                     f"{case_id} repeat {repeat}: paired arms were not dispatched adjacently")
    _require(replayed_dispatch_ids == dispatch_ids,
             "Recorded dispatch order does not match the documented Python seed/shuffle procedure")

    candidate_rows = [followup_index[(case_id, repeat, "sift_relation_matrix_v3")]
                      for case_id in EXPECTED_CASES for repeat in EXPECTED_REPEATS]
    default_rows = [followup_index[(case_id, repeat, "sift_default")]
                    for case_id in EXPECTED_CASES for repeat in EXPECTED_REPEATS]
    fallback_rows = [row for row in candidate_rows if row.get("research_relation_fallback_reason") is not None]
    task_outcomes: list[dict[str, Any]] = []
    comparison_keys = (
        "relation_vs_default",
        "relation_vs_historical_full",
        "relation_vs_historical_sift",
        "default_vs_historical_full",
        "default_vs_historical_sift",
    )
    comparisons = {key: {"wins": 0, "losses": 0, "ties": 0} for key in comparison_keys}
    for case_id in EXPECTED_CASES:
        arm_rows = {
            "relation_followup": [followup_index[(case_id, repeat, "sift_relation_matrix_v3")]
                                  for repeat in EXPECTED_REPEATS],
            "sift_default": [followup_index[(case_id, repeat, "sift_default")]
                             for repeat in EXPECTED_REPEATS],
            "historical_full": [historical_index[(case_id, repeat, "full")] for repeat in EXPECTED_REPEATS],
            "historical_sift": [historical_index[(case_id, repeat, "sift")] for repeat in EXPECTED_REPEATS],
        }
        outcomes = {arm: _summarize_repeats(rows) for arm, rows in arm_rows.items()}
        for comparison_key, left, right in (
            ("relation_vs_default", "relation_followup", "sift_default"),
            ("relation_vs_historical_full", "relation_followup", "historical_full"),
            ("relation_vs_historical_sift", "relation_followup", "historical_sift"),
            ("default_vs_historical_full", "sift_default", "historical_full"),
            ("default_vs_historical_sift", "sift_default", "historical_sift"),
        ):
            left_majority = outcomes[left]["majority_correct"]
            historical_majority = outcomes[right]["majority_correct"]
            if left_majority == historical_majority:
                comparisons[comparison_key]["ties"] += 1
            elif left_majority:
                comparisons[comparison_key]["wins"] += 1
            else:
                comparisons[comparison_key]["losses"] += 1
        task_outcomes.append({
            "case_id": case_id,
            "expected": followup_index[(case_id, 1, "sift_relation_matrix_v3")]["expected"],
            "relation_followup": outcomes["relation_followup"],
            "sift_default": outcomes["sift_default"],
            "historical_full": outcomes["historical_full"],
            "historical_sift": outcomes["historical_sift"],
        })

    prompt_tokens = {
        arm: [receipt["local_prompt_tokens"] for receipt in receipt_rows_by_arm[arm]]
        for arm in EXPECTED_FOLLOWUP_ARMS
    }
    provider_tokens = {
        arm: [receipt["provider_prompt_tokens"] for receipt in receipt_rows_by_arm[arm]]
        for arm in EXPECTED_FOLLOWUP_ARMS
    }
    completion_tokens = {
        arm: [receipt["completion_tokens"] for receipt in receipt_rows_by_arm[arm]]
        for arm in EXPECTED_FOLLOWUP_ARMS
    }
    costs = {
        arm: [receipt["upstream_cost_usd"] for receipt in receipt_rows_by_arm[arm]]
        for arm in EXPECTED_FOLLOWUP_ARMS
    }
    openrouter_costs = {
        arm: [receipt["openrouter_reported_cost_usd"] for receipt in receipt_rows_by_arm[arm]]
        for arm in EXPECTED_FOLLOWUP_ARMS
    }
    provider_ratios = {
        arm: [receipt["provider_local_input_token_ratio"] for receipt in receipt_rows_by_arm[arm]]
        for arm in EXPECTED_FOLLOWUP_ARMS
    }
    latencies = {
        "sift_relation_matrix_v3": [_finite_number(row.get("end_to_end_ms")) for row in candidate_rows],
        "sift_default": [_finite_number(row.get("end_to_end_ms")) for row in default_rows],
    }
    preprocess = {
        "sift_relation_matrix_v3": [_finite_number(row.get("sift_preprocessing_ms")) for row in candidate_rows],
        "sift_default": [_finite_number(row.get("sift_preprocessing_ms")) for row in default_rows],
    }
    for arm in EXPECTED_FOLLOWUP_ARMS:
        _require(all(value is not None and value >= 0 for value in latencies[arm]),
                 f"Missing/invalid {arm} end-to-end latency receipt")
        _require(all(value is not None and value >= 0 for value in preprocess[arm]),
                 f"Missing/invalid {arm} Sift preprocessing latency receipt")

    historical_full_rows = [historical_index[(case_id, repeat, "full")]
                            for case_id in EXPECTED_CASES for repeat in EXPECTED_REPEATS]
    historical_sift_rows = [historical_index[(case_id, repeat, "sift")]
                            for case_id in EXPECTED_CASES for repeat in EXPECTED_REPEATS]
    historical_full_tokens = sum(row["local_rendered_prompt_tokens"] for row in historical_full_rows)
    historical_sift_tokens = sum(row["local_rendered_prompt_tokens"] for row in historical_sift_rows)
    historical_full_cost = sum(_finite_number(row["usage"]["cost_details"]["upstream_inference_cost"]) or 0.0
                               for row in historical_full_rows)
    historical_sift_cost = sum(_finite_number(row["usage"]["cost_details"]["upstream_inference_cost"]) or 0.0
                               for row in historical_sift_rows)
    arm_receipts = {
        arm: _arm_receipt_accounting(
            rows,
            receipt_rows_by_arm[arm],
            prices,
        )
        for arm, rows in (("sift_relation_matrix_v3", candidate_rows), ("sift_default", default_rows))
    }
    historical_receipts = {
        "historical_full": _arm_receipt_accounting(
            historical_full_rows,
            [_validate_receipt(row, label=f"historical full {row['case_id']}:{row['repeat']}", followup=False)
             for row in historical_full_rows], prices,
        ),
        "historical_sift": _arm_receipt_accounting(
            historical_sift_rows,
            [_validate_receipt(row, label=f"historical sift {row['case_id']}:{row['repeat']}", followup=False)
             for row in historical_sift_rows], prices,
        ),
    }
    start_delta = (followup_created - historical_completed).total_seconds()
    complete_pair_receipt_gate = (
        len(candidate_rows) == 18 and len(default_rows) == 18
        and len(receipt_rows_by_arm["sift_relation_matrix_v3"]) == 18
        and len(receipt_rows_by_arm["sift_default"]) == 18
        and len(followup_index) == 36
    )
    no_fallback_gate = len(fallback_rows) == 0
    candidate_only_majorities = comparisons["relation_vs_default"]["wins"]
    default_only_majorities = comparisons["relation_vs_default"]["losses"]
    relation_token_total = sum(prompt_tokens["sift_relation_matrix_v3"])
    default_token_total = sum(prompt_tokens["sift_default"])
    candidate_correct = sum(_score(row, "relation candidate")["correct"] for row in candidate_rows)
    default_correct = sum(_score(row, "default Sift")["correct"] for row in default_rows)
    candidate_invalid = sum(not _score(row, "relation candidate")["valid"] for row in candidate_rows)
    default_invalid = sum(not _score(row, "default Sift")["valid"] for row in default_rows)
    zero_invalid_gate = candidate_invalid == 0 and default_invalid == 0
    gate_result = expansion_gate(
        complete_pair_receipts=complete_pair_receipt_gate,
        no_candidate_fallbacks=no_fallback_gate,
        no_anomalies=True,  # all receipt, route, usage, cost, target and parse checks raised above
        no_invalid_answers=zero_invalid_gate,
        candidate_only_majorities=candidate_only_majorities,
        candidate_exact_correct=candidate_correct,
        default_exact_correct=default_correct,
    )
    expansion_gate_passed = gate_result["decision"] == "PASS"

    return {
        "schema_version": 1,
        "evaluation": "six-task exploratory LongBench v2 paired Sift-arm gate; not a benchmark aggregate",
        "status": "validated",
        "integrity_status": "validated",
        "expansion_gate": {
            "decision": gate_result["decision"],
            "eligible_for_larger_followup_review": expansion_gate_passed,
            "criteria": gate_result["criteria"],
            "observed": {
                "valid_paired_rows": len(followup_index),
                "required_rows": 36,
                "candidate_only_correct_majorities": candidate_only_majorities,
                "default_only_correct_majorities": default_only_majorities,
                "candidate_exact_choice_correct": candidate_correct,
                "default_exact_choice_correct": default_correct,
                "fallback_selected_requests": len(fallback_rows),
            },
            "meaning": "PASS authorizes considering a larger follow-up only; it does not establish benchmark-wide quality, parity, or causality.",
        },
        "scope": {
            "qualified_case_ids": list(EXPECTED_CASES),
            "task_count": len(EXPECTED_CASES),
            "repeats_per_task": len(EXPECTED_REPEATS),
            "candidate_response_count": len(candidate_rows),
            "default_sift_response_count": len(default_rows),
            "total_followup_response_count": len(followup_index),
            "selection_basis": "six closure-supported IDs from .runs/longbench-relation-closure-offline.json",
            "offline_sweep_closure_count": 6,
            "offline_sweep_fallback_count": 94,
            "not_a_longbench_aggregate": True,
        },
        "comparison_design": {
            "historical_result_created_utc": historical.get("created_utc"),
            "historical_result_completed_utc": historical.get("completed_utc"),
            "followup_created_utc": followup.get("created_utc"),
            "followup_completed_utc": followup.get("completed_utc"),
            "within_run_arms_concurrent": False,
            "within_run_pairing": "Each case/repeat has default Sift and the option-aligned complete-entity matrix treatment dispatched adjacently with the same generation seed in one worker; randomized order is recorded.",
            "recorded_dispatch_job_ids": dispatch_ids,
            "historical_non_concurrent": True,
            "seconds_after_historical_completion": start_delta,
            "historical_provider_drift_limited": True,
            "historical_limitation": "Historical Full/Sift generations occurred in an earlier non-concurrent run; MiniMax model/provider behavior can drift. Matching case/repeat/seeds do not control provider changes.",
            "paired_keys": "Within-run arms pair by case_id + repeat + generation_seed; historical Full/Sift remain same-key, non-concurrent references.",
            "artifact_hashes": prices.get("provenance"),
        },
        "quality": {
            "exact_choice_correct": {
                "sift_relation_matrix_v3": candidate_correct,
                "sift_default": default_correct,
            },
            "exact_choice_total_per_arm": 18,
            "invalid_response_count": {
                "sift_relation_matrix_v3": candidate_invalid,
                "sift_default": default_invalid,
            },
            "task_majority_correct_count": {
                arm: sum(item[arm]["majority_correct"] for item in task_outcomes)
                for arm in ("relation_followup", "sift_default", "historical_full", "historical_sift")
            },
            "task_majority_total": len(task_outcomes),
            "task_majority_comparison": comparisons,
            "task_outcomes": task_outcomes,
        },
        "selection_and_budget": {
            "targeted_case_repeat_pairs": len(EXPECTED_CASES) * len(EXPECTED_REPEATS),
            "targeted_requests": len(followup_index),
            "target_tokens": TARGET_TOKENS,
            "effective_target_tokens": EFFECTIVE_TARGET_TOKENS,
            "candidate_attempted_requests": sum(
                _finite_number(row.get("research_relation_candidate_ms")) is not None for row in candidate_rows
            ),
            "candidate_selected_requests": len(candidate_rows) - len(fallback_rows),
            "fallback_selected_requests": len(fallback_rows),
            "fallback_reasons": {
                reason: sum(row.get("research_relation_fallback_reason") == reason for row in fallback_rows)
                for reason in sorted({row.get("research_relation_fallback_reason") for row in fallback_rows})
            },
            "target_compliant_requests": len(followup_index),
        },
        "receipts": {
            "local_prompt_tokens": {
                "sift_relation_matrix_v3_total": relation_token_total,
                "concurrent_sift_default_total": default_token_total,
                "historical_full_same_cases_total": historical_full_tokens,
                "historical_sift_same_cases_total": historical_sift_tokens,
                "relation_vs_concurrent_default_reduction_percent": (
                    100 * (default_token_total - relation_token_total) / default_token_total
                    if default_token_total else None
                ),
                "relation_vs_historical_sift_reduction_percent": (
                    100 * (historical_sift_tokens - relation_token_total) / historical_sift_tokens
                    if historical_sift_tokens else None
                ),
                "relation_vs_historical_full_reduction_percent": (
                    100 * (historical_full_tokens - relation_token_total) / historical_full_tokens
                    if historical_full_tokens else None
                ),
                "per_arm_min": {arm: min(values) for arm, values in prompt_tokens.items()},
                "per_arm_max": {arm: max(values) for arm, values in prompt_tokens.items()},
            },
            "provider_prompt_tokens_total": {arm: sum(values) for arm, values in provider_tokens.items()},
            "completion_tokens_total": {arm: sum(values) for arm, values in completion_tokens.items()},
            "upstream_reported_cost_usd": {arm: sum(values) for arm, values in costs.items()},
            "openrouter_reported_cost_usd": {arm: sum(values) for arm, values in openrouter_costs.items()},
            "historical_full_upstream_cost_same_cases_usd": historical_full_cost,
            "historical_sift_upstream_cost_same_cases_usd": historical_sift_cost,
            "provider_local_input_token_ratio_max": {arm: max(values) for arm, values in provider_ratios.items()},
            "arm_usage_cost_accounting": arm_receipts,
            "historical_usage_cost_accounting": historical_receipts,
            "counterfactual_price_basis": {
                key: prices[key] for key in (
                    "input_price_usd_per_million", "output_price_usd_per_million",
                    "cache_read_price_usd_per_million", "cache_write_price_usd_per_million",
                )
            },
            "end_to_end_ms_median": {
                arm: statistics.median(value for value in values if value is not None)
                for arm, values in latencies.items()
            },
            "end_to_end_ms_p95": {
                arm: _percentile([value for value in values if value is not None], 0.95)
                for arm, values in latencies.items()
            },
            "sift_preprocessing_ms_median": {
                arm: statistics.median(value for value in values if value is not None)
                for arm, values in preprocess.items()
            },
            "sift_preprocessing_ms_p95": {
                arm: _percentile([value for value in values if value is not None], 0.95)
                for arm, values in preprocess.items()
            },
        },
        "interpretation": "Exploratory six-task paired gate only, not LongBench aggregate, general quality estimate, parity result, or causal effect. Historical Full/Sift comparisons are non-concurrent provider-drift-limited references.",
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lo, hi = math.floor(index), math.ceil(index)
    return ordered[lo] if lo == hi else ordered[lo] * (hi - index) + ordered[hi] * (index - lo)


def render_markdown(result: dict[str, Any]) -> str:
    q = result["quality"]
    counts = result["selection_and_budget"]
    receipts = result["receipts"]
    tokens = receipts["local_prompt_tokens"]
    gate = result["expansion_gate"]
    lines = [
        "# MiniMax relation-matrix v3 follow-up: six-task paired exploratory gate",
        "",
        "This result covers six relation-closure-supported tasks, three repeats, and two Sift arms (36 calls). The matrix was developed on these same public training prompts, so this candidate-enriched diagnostic is not a LongBench v2 aggregate, holdout, or generalization result. Unchanged default Sift and the option-aligned complete-entity matrix treatment are paired in the same interleaved run. Historical Full/Sift are non-concurrent references and may be affected by provider/model drift.",
        "",
        f"- Analysis integrity: **{result['integrity_status'].upper()}**. Stage-1 expansion gate: **{gate['decision']}**.",
        "- Gate checks: " + "; ".join(
            f"{'PASS' if passed else 'FAIL'} — {criterion.replace('_', ' ')}"
            for criterion, passed in gate["criteria"].items()
        ) + ".",
        f"- Exact-choice correct: matrix candidate **{q['exact_choice_correct']['sift_relation_matrix_v3']}/18**, default Sift **{q['exact_choice_correct']['sift_default']}/18**; invalids: matrix candidate **{q['invalid_response_count']['sift_relation_matrix_v3']}**, default **{q['invalid_response_count']['sift_default']}**.",
        f"- Task majorities: matrix candidate **{q['task_majority_correct_count']['relation_followup']}/6**, default Sift **{q['task_majority_correct_count']['sift_default']}/6**.",
        f"- Concurrent task-majority comparison: **{gate['observed']['candidate_only_correct_majorities']} candidate-only wins**, **{gate['observed']['default_only_correct_majorities']} default-only wins**, {q['task_majority_comparison']['relation_vs_default']['ties']} ties.",
        f"- Candidate selector: {counts['candidate_selected_requests']} complete-entity matrix selections; {counts['fallback_selected_requests']} default-Sift fallbacks across 18 candidate attempts and {counts['targeted_requests']} total calls.",
        f"- Local prompt tokens: relation {tokens['sift_relation_matrix_v3_total']:,}; concurrent default Sift {tokens['concurrent_sift_default_total']:,}; historical Sift {tokens['historical_sift_same_cases_total']:,}; historical Full {tokens['historical_full_same_cases_total']:,}.",
        f"- Upstream reported cost: relation ${receipts['upstream_reported_cost_usd']['sift_relation_matrix_v3']:.6f}; default Sift ${receipts['upstream_reported_cost_usd']['sift_default']:.6f}.",
        f"- Median end-to-end: relation {receipts['end_to_end_ms_median']['sift_relation_matrix_v3']:.1f} ms; default Sift {receipts['end_to_end_ms_median']['sift_default']:.1f} ms.",
    ]
    usage_rows = receipts["arm_usage_cost_accounting"]
    historical_usage = receipts["historical_usage_cost_accounting"]
    lines.extend([
        "",
        "## Provider usage and cache accounting",
        "",
        "The uncached estimate is a counterfactual at the saved MiniMax route rates; it is not observed billing. Observed cache-inclusive cost comes from the upstream receipt.",
        "",
        "| Arm | Provider prompt tokens | Cached tokens | Cached fraction | Observed upstream cost | Reconstructed uncached cost (counterfactual) |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for arm, label, accounting in (
        ("sift_relation_matrix_v3", "Option-aligned complete-entity matrix", usage_rows["sift_relation_matrix_v3"]),
        ("sift_default", "Concurrent default Sift", usage_rows["sift_default"]),
        ("historical_full", "Historical Full", historical_usage["historical_full"]),
        ("historical_sift", "Historical Sift", historical_usage["historical_sift"]),
    ):
        cached_fraction = accounting["cached_prompt_fraction_of_provider_prompt_tokens"]
        fraction_display = "n/a" if cached_fraction is None else f"{cached_fraction:.1%}"
        lines.append(
            f"| {label} | {accounting['provider_prompt_tokens_total']:,} | "
            f"{accounting['cached_prompt_tokens_total']:,} | {fraction_display} | "
            f"${accounting['cache_inclusive_upstream_reported_cost_usd']:.6f} | "
            f"${accounting['reconstructed_uncached_cost_counterfactual_usd']:.6f} |"
        )
    price_basis = receipts["counterfactual_price_basis"]
    cache_write_display = (
        "unavailable"
        if price_basis["cache_write_price_usd_per_million"] is None
        else f"${price_basis['cache_write_price_usd_per_million']:.6f}"
    )
    lines.extend([
        "",
        "Counterfactual rate basis per million tokens: uncached input "
        f"${price_basis['input_price_usd_per_million']:.6f}, output "
        f"${price_basis['output_price_usd_per_million']:.6f}, cache read "
        f"${price_basis['cache_read_price_usd_per_million']:.6f}; cache write rate "
        f"{cache_write_display}.",
        "",
        "## Per-task outcomes",
        "",
        "| Case ID | Relation | Default Sift | Historical Full | Historical Sift | Relation vs default |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for item in q["task_outcomes"]:
        rel = item["relation_followup"]
        default = item["sift_default"]
        full, sift = item["historical_full"], item["historical_sift"]
        if rel["majority_correct"] == default["majority_correct"]:
            pair_result = "tie"
        elif rel["majority_correct"]:
            pair_result = "candidate-only win"
        else:
            pair_result = "default-only win"

        lines.append(
            f"| `{item['case_id']}` | {rel['correct_repeats']}/3 ({'majority' if rel['majority_correct'] else 'no majority'}) | "
            f"{default['correct_repeats']}/3 ({'majority' if default['majority_correct'] else 'no majority'}) | "
            f"{full['correct_repeats']}/3 ({'majority' if full['majority_correct'] else 'no majority'}) | "
            f"{sift['correct_repeats']}/3 ({'majority' if sift['majority_correct'] else 'no majority'}) | "
            f"{pair_result} |"
        )
    lines.extend([
        "",
        "## Historical reference comparison",
        "",
        "| Paired arm vs historical reference | Wins | Losses | Ties |",
        "|---|---:|---:|---:|",
    ])
    for arm in ("relation_vs_historical_full", "relation_vs_historical_sift",
                "default_vs_historical_full", "default_vs_historical_sift"):
        values = q["task_majority_comparison"][arm]
        lines.append(f"| {arm.replace('_', ' ').title()} | {values['wins']} | {values['losses']} | {values['ties']} |")
    lines.extend([
        "",
        "The cases were selected because the offline relation-closure parser supported them. This is a targeted debugging/evidence-retention screen, not a representative benchmark sample. The concurrent arm comparison is paired by task/repeat with the same seed; historical references remain non-concurrent and provider-drift-limited.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--followup", type=Path, required=True, help="Completed six-case relation-follow-up result JSON")
    parser.add_argument("--historical", type=Path, required=True, help="Frozen historical paired 100-task result JSON")
    parser.add_argument("--manifest", type=Path, required=True, help="Frozen baseline sample manifest")
    parser.add_argument("--stage-manifest", type=Path, required=True, help="Exact stage-one manifest used for the run")
    parser.add_argument("--route-metadata", type=Path, required=True, help="Exact saved OpenRouter route metadata snapshot")
    parser.add_argument("--json-output", type=Path, required=True, help="Where to write the JSON analysis")
    parser.add_argument("--markdown-output", type=Path, required=True, help="Where to write the Markdown analysis")
    args = parser.parse_args()
    try:
        followup = json.loads(args.followup.read_text(encoding="utf-8"))
        historical = json.loads(args.historical.read_text(encoding="utf-8"))
        provenance = verify_provenance(
            followup, historical,
            historical_path=args.historical,
            baseline_manifest_path=args.manifest,
            stage_manifest_path=args.stage_manifest,
            route_metadata_path=args.route_metadata,
        )
        prices = {
            key: provenance[key] for key in (
                "input_price_usd_per_million", "output_price_usd_per_million",
                "cache_read_price_usd_per_million", "cache_write_price_usd_per_million",
            )
        }
        prices["provenance"] = {
            key: provenance[key] for key in (
                "stage_manifest_sha256", "route_metadata_sha256", "baseline_manifest_sha256",
                "historical_result_sha256",
            )
        }
        prices["provenance"]["corrected_analyzer_sha256"] = _sha256(Path(__file__).resolve())
        result = analyze(followup, historical, prices)
    except (OSError, json.JSONDecodeError, AnalysisError) as error:
        parser.error(str(error))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({"integrity_status": result["integrity_status"],
                      "expansion_gate": result["expansion_gate"]["decision"],
                      "responses": 36,
                      "json": str(args.json_output), "markdown": str(args.markdown_output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
