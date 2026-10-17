"""Validate and summarize the 100-task hybrid MiniMax Stage 2 result."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
import run_longbench_v2_minimax_relation_followup_v3 as v3  # noqa: E402
import analyze_longbench_v2_minimax_relation_followup_v3_corrected as v3_analysis  # noqa: E402
import run_longbench_v2_minimax as baseline  # noqa: E402
import run_longbench_v2_minimax_hybrid_stage2 as stage2_runner  # noqa: E402

EXPECTED_MODEL = "minimax/minimax-m3"
EXPECTED_ARM = "sift_hybrid_stage2"
EXPECTED_REPEATS = (1, 2, 3)
EXPECTED_TASK_COUNT = 100
EXPECTED_PROVIDER_RATIO = 1.05
EXPECTED_MATRIX_IDS = {
    "672494e5bb02136c067d7697", "67249705bb02136c067d76d1",
    "6724c1d4bb02136c067d77ec", "67285e1dbb02136c067d901b",
    "67286036bb02136c067d9092", "6724c4aabb02136c067d78a6",
}


class AnalysisError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    if path.suffix.casefold() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8-sig") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.suffix.casefold() == ".gz":
        with gzip.open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


sha = sha256


def correct_majority(rows: list[dict[str, Any]]) -> bool:
    return sum(row.get("correct") is True and row.get("strict_sample_valid") is True for row in rows) >= 2


def _metric_receipts(rows: list[dict[str, Any]], input_price: float, output_price: float,
                     cache_read_price: float | None, *, verify_price_reconstruction: bool) -> dict[str, Any]:
    prompt = cached = completions = 0
    upstream = direct = uncached_counterfactual = 0.0
    for row in rows:
        usage = row.get("usage")
        require(isinstance(usage, dict) and usage.get("is_byok") is True,
                f"{row.get('job_id')}: missing BYOK usage receipt")
        tokens = usage.get("prompt_tokens")
        output = usage.get("completion_tokens")
        require(type(tokens) is int and tokens > 0 and type(output) is int and output >= 0,
                f"{row.get('job_id')}: invalid token usage")
        details = usage.get("cost_details")
        require(isinstance(details, dict), f"{row.get('job_id')}: missing cost details")
        prompt_cost = details.get("upstream_inference_prompt_cost")
        completion_cost = details.get("upstream_inference_completions_cost")
        total_cost = details.get("upstream_inference_cost")
        require(all(type(x) in (int, float) and math.isfinite(x) and x >= 0
                    for x in (prompt_cost, completion_cost, total_cost)),
                f"{row.get('job_id')}: invalid upstream cost components")
        require(math.isclose(prompt_cost + completion_cost, total_cost, rel_tol=1e-4, abs_tol=1e-8),
                f"{row.get('job_id')}: upstream cost components do not reconcile")
        detail = usage.get("prompt_tokens_details")
        require(isinstance(detail, dict), f"{row.get('job_id')}: missing cache token details")
        cache = detail.get("cached_tokens")
        write = detail.get("cache_write_tokens")
        require(type(cache) is int and type(write) is int and 0 <= cache <= tokens
                and 0 <= write <= tokens - cache, f"{row.get('job_id')}: invalid cached token counts")
        uncached_tokens = tokens - cache - write
        if verify_price_reconstruction:
            require(cache_read_price is not None, "Route snapshot lacks cache-read pricing")
            # A missing cache-write rate cannot safely be inferred from the regular input rate.
            require(write == 0, f"{row.get('job_id')}: cache-write rate is unavailable for reconstruction")
            expected_prompt_cost = (uncached_tokens * input_price + cache * cache_read_price) / 1_000_000
            require(math.isclose(expected_prompt_cost, prompt_cost, rel_tol=1e-4, abs_tol=1e-8),
                    f"{row.get('job_id')}: cached prompt-cost reconstruction differs from receipt")
            require(math.isclose(output * output_price / 1_000_000, completion_cost,
                                 rel_tol=1e-4, abs_tol=1e-8),
                    f"{row.get('job_id')}: completion-cost reconstruction differs from receipt")
        prompt += tokens
        cached += cache
        completions += output
        upstream += total_cost
        direct += usage.get("cost") or 0.0
        uncached_counterfactual += (tokens * input_price + output * output_price) / 1_000_000
    return {
        "requests": len(rows),
        "provider_prompt_tokens": prompt,
        "cached_prompt_tokens": cached,
        "cached_prompt_fraction": cached / prompt if prompt else None,
        "completion_tokens": completions,
        "upstream_reported_cache_inclusive_cost_usd": upstream,
        "openrouter_cost_field_usd": direct,
        "reconstructed_uncached_cost_counterfactual_usd": uncached_counterfactual,
        "per_row_prompt_and_completion_cost_reconstruction_checks": len(rows) if verify_price_reconstruction else 0,
        "receipt_price_reconstruction": "verified against pinned route snapshot" if verify_price_reconstruction else "not reconstructed: historical manifest has no cache-tier rates; observed upstream receipts retained",
        "counterfactual_basis": "prompt_tokens × uncached input price + completion_tokens × output price; estimate, not observed billing",
    }


def _raw_stream(row: dict[str, Any], *, label: str, json_answer: bool) -> dict[str, Any]:
    """Recompute answer/route fields from retained SSE chunks, never from saved flags."""
    events = row.get("raw_sse_events")
    require(isinstance(events, list) and events and all(isinstance(event, str) for event in events),
            f"{label}: raw SSE events are missing")
    require(row.get("raw_response_body") == "\n".join(events), f"{label}: raw response body differs from SSE events")
    text_parts: list[str] = []
    model = provider = response_id = finish_reason = None
    usage = None
    saw_content = False
    done = False
    for event in events:
        if event == "[DONE]":
            done = True
            continue
        try:
            chunk = json.loads(event)
        except (json.JSONDecodeError, TypeError) as error:
            raise AnalysisError(f"{label}: malformed retained SSE JSON") from error
        require(isinstance(chunk, dict), f"{label}: SSE event is not an object")
        model = chunk.get("model") or model
        provider = chunk.get("provider") or provider
        response_id = chunk.get("id") or response_id
        if chunk.get("usage") is not None:
            usage = chunk["usage"]
        choices = chunk.get("choices", [])
        require(isinstance(choices, list), f"{label}: malformed SSE choices")
        for item in choices:
            require(isinstance(item, dict), f"{label}: malformed SSE choice")
            if item.get("finish_reason") is not None:
                finish_reason = item["finish_reason"]
            delta = item.get("delta") or {}
            require(isinstance(delta, dict), f"{label}: malformed SSE delta")
            content = delta.get("content")
            if isinstance(content, str) and content:
                saw_content = True
                text_parts.append(content)
    raw_text = "".join(text_parts)
    choice = v3._json_choice(raw_text) if json_answer else baseline.parse_choice(raw_text)
    normal = (row.get("http_status") == 200 and finish_reason == "stop" and saw_content
              and model == EXPECTED_MODEL and isinstance(provider, str)
              and provider.strip().casefold() == "minimax" and row.get("failure") is None)
    require(done, f"{label}: stream is missing [DONE]")
    require(row.get("model") == model and row.get("provider", "").strip().casefold() ==
            (provider.strip().casefold() if isinstance(provider, str) else None),
            f"{label}: saved model/provider disagree with retained stream")
    require(row.get("response_id") == response_id, f"{label}: response ID differs from retained stream")
    require(row.get("finish_reason") == finish_reason, f"{label}: finish reason differs from retained stream")
    require(row.get("usage") == usage, f"{label}: usage receipt differs from retained stream")
    require(row.get("answer") == raw_text[:500],
            f"{label}: saved answer differs from retained stream's 500-character display prefix")
    require(row.get("choice") == choice, f"{label}: saved choice differs from parsed retained answer")
    require(row.get("normal") is normal, f"{label}: normal flag differs from retained stream status")
    require(row.get("valid_structured_choice") is (choice is not None),
            f"{label}: structured-choice flag differs from retained answer")
    valid = normal and finish_reason == "stop" and choice in {"A", "B", "C", "D"}
    if json_answer:
        require(row.get("answer_validity") == ("valid" if valid else "invalid_or_incomplete"),
                f"{label}: answer-validity flag differs from retained answer")
    correct = normal and choice == row.get("expected")
    require(row.get("correct") is correct, f"{label}: correctness flag differs from retained answer")
    return {"choice": choice, "correct": correct, "normal": normal, "valid": valid, "usage": usage}


def _validate_stage_request(row: dict[str, Any], *, label: str) -> None:
    request = row.get("request")
    require(isinstance(request, dict), f"{label}: saved request payload is missing")
    digest = v3._request_hash(request)
    require(row.get("request_sha256") == digest and row.get("request_payload_sha256") == digest,
            f"{label}: request payload hash mismatch")
    expected = {
        "model": EXPECTED_MODEL, "temperature": 0.1, "top_p": 0.8,
        "seed": row.get("generation_seed"), "max_tokens": 128,
        "reasoning": {"enabled": False}, "response_format": {"type": "json_object"},
        "stream": True, "stream_options": {"include_usage": True},
        "provider": {"only": ["minimax"], "allow_fallbacks": False},
    }
    for key, value in expected.items():
        require(request.get(key) == value, f"{label}: request {key} differs from frozen protocol")
    messages = request.get("messages")
    require(isinstance(messages, list) and messages, f"{label}: request messages are missing")
    require(v3._messages_hash(messages) == row.get("request_messages_sha256"),
            f"{label}: request message hash mismatch")
    require(row.get("arm") == EXPECTED_ARM and row.get("target_tokens") == 32768,
            f"{label}: arm or target differs from frozen protocol")
    local = row.get("local_rendered_prompt_tokens")
    provider = (row.get("usage") or {}).get("prompt_tokens")
    require(type(local) is int and local > 0 and type(provider) is int and provider > 0,
            f"{label}: local/provider prompt token counts are invalid")
    ratio = provider / local
    require(ratio <= EXPECTED_PROVIDER_RATIO, f"{label}: provider/local prompt ratio exceeds guard")
    saved_ratio = row.get("provider_local_input_token_ratio")
    require(isinstance(saved_ratio, (int, float)) and math.isclose(saved_ratio, ratio, rel_tol=1e-9),
            f"{label}: saved provider/local prompt ratio differs from usage")


def _validate_route_binding(stage: dict[str, Any], route_path: Path) -> None:
    declared_route_path = stage.get("route_metadata_path")
    require(isinstance(declared_route_path, str), "Stage manifest route_metadata_path is missing")
    resolved_route_path = Path(declared_route_path)
    if not resolved_route_path.is_absolute():
        resolved_route_path = ROOT / resolved_route_path
    require(resolved_route_path.resolve() == route_path.resolve(),
            "Supplied route metadata path differs from the frozen stage manifest")
    require(stage.get("route_metadata_sha256") == sha(route_path)
            and stage.get("source_hashes", {}).get("route_metadata_sha256") == sha(route_path),
            "Supplied route metadata hash differs from the frozen stage manifest")


def _validate_strict_sample_valid(row: dict[str, Any], computed: dict[str, Any], *, label: str) -> None:
    require(type(row.get("strict_sample_valid")) is bool,
            f"{label}: strict sample validity flag is missing")
    require(row["strict_sample_valid"] is computed["valid"],
            f"{label}: strict sample flag differs from recomputed answer/operational validity")


def _validate_source_binding(result: dict[str, Any], stage: dict[str, Any]) -> None:
    source_hashes = result.get("source_hashes", {})
    expected_sources = stage.get("source_hashes", {})
    require(isinstance(source_hashes, dict) and isinstance(expected_sources, dict),
            "Stage 2 source hash maps are missing")
    for key, source_path in stage2_runner.SOURCE_PATHS.items():
        expected_digest = expected_sources.get(key)
        require(isinstance(expected_digest, str) and len(expected_digest) == 64
                and source_hashes.get(key) == expected_digest,
                f"Stage 2 source hash {key} differs between result and frozen manifest")
        require(source_path.is_file() and sha(source_path) == expected_digest,
                f"Stage 2 source hash {key} differs from the current source file")
    for key, expected_digest in expected_sources.items():
        require(source_hashes.get(key) == expected_digest,
                f"Stage 2 source hash {key} differs between result and frozen manifest")


def _comparison_key(outcome: str) -> str:
    return {"win": "wins", "loss": "losses", "tie": "ties"}[outcome]


def _route_pricing(route_path: Path) -> tuple[float, float, float]:
    """Read cache prices from either frozen normalized metadata or raw endpoint data."""
    document = json.loads(route_path.read_text(encoding="utf-8-sig"))
    data = document.get("data", document)
    require(isinstance(data, dict), "Route metadata must contain an object")
    endpoints = data.get("endpoints")
    if isinstance(endpoints, list):
        pinned = [row for row in endpoints if isinstance(row, dict)
                  and row.get("model_id") == EXPECTED_MODEL
                  and isinstance(row.get("provider_name"), str)
                  and row["provider_name"].strip().casefold() == "minimax"]
        require(len(pinned) == 1, "Route snapshot must have exactly one pinned MiniMax endpoint")
        prices = pinned[0].get("pricing", {})
    else:
        require(data.get("requested_model") == EXPECTED_MODEL
                and data.get("endpoint_model_id") == EXPECTED_MODEL
                and str(data.get("provider", "")).strip().casefold() == "minimax",
                "Normalized route snapshot does not identify the pinned MiniMax endpoint")
        prices = data.get("pricing_usd_per_token", {})
    try:
        values = (float(prices["prompt"]), float(prices["completion"]),
                  float(prices["input_cache_read"]))
    except (TypeError, KeyError, ValueError) as error:
        raise AnalysisError("Pinned route snapshot lacks valid input/output/cache-read prices") from error
    require(all(math.isfinite(value) and value > 0 for value in values),
            "Pinned route input/output/cache-read prices must be positive and finite")
    return tuple(value * 1_000_000 for value in values)


def analyze(result: dict[str, Any], historical: dict[str, Any], *, result_path: Path,
            historical_path: Path, manifest_path: Path, stage_path: Path,
            route_path: Path) -> dict[str, Any]:
    stage = json.loads(stage_path.read_text(encoding="utf-8-sig"))
    frozen_manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    require(result.get("status") == "complete", "Stage 2 report is not complete")
    require(historical.get("status") == "complete", "Historical result is not complete")
    require(historical.get("manifest_sha256") == sha(manifest_path),
            "Historical result does not identify the supplied frozen baseline manifest")
    require(result.get("baseline_result_sha256") == _content_sha256(historical_path),
            "Stage 2 report does not identify the supplied historical result")
    require(result.get("model") == EXPECTED_MODEL, "Unexpected Stage 2 model")
    require(result.get("stage_manifest_sha256") == sha256(stage_path), "Stage manifest hash differs")
    require(result.get("baseline_manifest_sha256") == sha(manifest_path), "Baseline manifest hash differs")
    require(result.get("baseline_result_sha256") == _content_sha256(historical_path), "Baseline result hash differs")
    require(result.get("source_hashes", {}).get("route_metadata_sha256") == sha(route_path),
            "Route metadata hash differs")
    _validate_source_binding(result, stage)
    _validate_route_binding(stage, route_path)
    protocol = stage.get("protocol")
    require(isinstance(protocol, dict), "Stage 2 frozen protocol is missing")
    manifest_cases = frozen_manifest.get("cases")
    require(isinstance(manifest_cases, list), "Frozen baseline manifest has no cases")
    manifest_task_ids = [item.get("id") for item in manifest_cases if isinstance(item, dict)]
    require(len(manifest_task_ids) == EXPECTED_TASK_COUNT and len(set(manifest_task_ids)) == EXPECTED_TASK_COUNT,
            "Frozen baseline manifest must identify exactly 100 unique tasks")
    frozen_task_ids = protocol.get("task_ids")
    require(isinstance(frozen_task_ids, list) and frozen_task_ids == manifest_task_ids,
            "Stage 2 task IDs/order differ from the exact frozen 100-task manifest")
    require(protocol.get("model", {}).get("id") == EXPECTED_MODEL
            and protocol.get("arms") == [EXPECTED_ARM]
            and protocol.get("repeats") == len(EXPECTED_REPEATS)
            and protocol.get("sift_target_tokens") == 32768,
            "Frozen Stage 2 model, arm, repeat count, or target differs")
    require(protocol.get("provider_policy") == {"only": ["minimax"], "allow_fallbacks": False},
            "Frozen Stage 2 provider policy differs")
    require(protocol.get("generation") == {
        "temperature": 0.1, "top_p": 0.8, "reasoning_enabled": False,
        "max_tokens": 128, "response_format": {"type": "json_object"},
        "answer_format": "json_object_single_answer_a_to_d", "retries": 0, "workers": 1,
    }, "Frozen Stage 2 generation configuration differs")
    require(protocol.get("candidate_policy", {}).get("matrix_candidate_ids") == sorted(EXPECTED_MATRIX_IDS)
            or set(protocol.get("candidate_policy", {}).get("matrix_candidate_ids", [])) == EXPECTED_MATRIX_IDS,
            "Frozen Stage 2 matrix candidate IDs differ")
    require(protocol.get("candidate_policy", {}).get("matrix_fallbacks_allowed") is False,
            "Frozen Stage 2 protocol allows matrix candidate fallbacks")
    rows = result.get("samples")
    require(isinstance(rows, list) and len(rows) == EXPECTED_TASK_COUNT * 3,
            "Stage 2 must contain exactly 300 response rows")
    keys: set[tuple[str, int, str]] = set()
    row_index: dict[tuple[str, int, str], dict[str, Any]] = {}
    frozen_case_by_id = {item["id"]: item for item in manifest_cases}
    for row in rows:
        require(row.get("arm") == EXPECTED_ARM, "Unexpected Stage 2 arm")
        require(row.get("model") == EXPECTED_MODEL
                and isinstance(row.get("provider"), str)
                and row["provider"].strip().casefold() == "minimax",
                f"{row.get('job_id')}: provider attribution mismatch")
        require(row.get("http_status") == 200 and row.get("strict_receipt_valid") is True,
                f"{row.get('job_id')}: invalid HTTP or receipt status")
        key = (row.get("case_id"), row.get("repeat"), row.get("arm"))
        require(key[0] in frozen_case_by_id and type(key[1]) is int and key[1] in EXPECTED_REPEATS
                and key[2] == EXPECTED_ARM,
                "Invalid Stage 2 task/repeat key")
        require(key not in keys, f"Duplicate Stage 2 sample key {key}")
        keys.add(key)
        label = str(row.get("job_id") or key)
        require(row.get("expected") == frozen_case_by_id[key[0]].get("answer_key"),
                f"{label}: expected answer differs from frozen task manifest")
        _validate_stage_request(row, label=label)
        require(row.get("strict_receipt_valid") is True and row.get("cost_receipt_status") == "reported",
                f"{label}: strict receipt flags do not indicate a complete reported receipt")
        v3_analysis._validate_receipt(row, label=label, followup=True)
        computed = _raw_stream(row, label=label, json_answer=True)
        _validate_strict_sample_valid(row, computed, label=label)
        should_be_matrix = key[0] in EXPECTED_MATRIX_IDS
        require(row.get("matrix_candidate_attempted") is should_be_matrix
                and row.get("matrix_candidate_selected") is should_be_matrix
                and row.get("candidate_fallback_reason") is None,
                f"{label}: matrix selection/fallback does not match the frozen six-ID policy")
        require(row.get("selection_method") == (
            "option_aligned_matrix_v3" if should_be_matrix else "default_sift"
        ), f"{label}: selected method does not match the frozen six-ID policy")
        row_index[key] = row
    task_ids = frozen_task_ids
    require(set(key[0] for key in keys) == set(task_ids), "Stage 2 task IDs differ from the exact frozen manifest")
    require(keys == {(task, repeat, EXPECTED_ARM) for task in task_ids for repeat in EXPECTED_REPEATS},
            "Stage 2 does not have exactly three repeats per task")
    require(sum(row.get("selection_method") == "option_aligned_matrix_v3" for row in rows) == 18
            and sum(row.get("selection_method") == "default_sift" for row in rows) == 282,
            "Stage 2 must contain 18 matrix selections and 282 default-Sift selections")
    require(result.get("budget", {}).get("unknown_cost_receipts") == 0,
            "Stage 2 contains unknown cost receipts")
    require(not result.get("budget", {}).get("stop_reasons"), "Stage 2 recorded operational stop reasons")

    historical_rows = historical.get("samples")
    require(isinstance(historical_rows, list), "Historical result has no sample rows")
    expected_historical_keys = {
        (task, repeat, arm) for task in task_ids for repeat in EXPECTED_REPEATS for arm in ("full", "sift")
    }
    historical_index: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in historical_rows:
        require(isinstance(row, dict), "Historical result contains a non-object sample")
        key = (row.get("case_id"), row.get("repeat"), row.get("arm"))
        require(key in expected_historical_keys, f"Unexpected historical task/repeat/arm key {key}")
        require(key not in historical_index, f"Duplicate historical sample key {key}")
        require(row.get("model") == EXPECTED_MODEL and isinstance(row.get("provider"), str)
                and row["provider"].strip().casefold() == "minimax",
                f"Historical sample {key}: model/provider attribution mismatch")
        require(row.get("expected") == frozen_case_by_id[key[0]].get("answer_key"),
                f"Historical sample {key}: expected answer differs from frozen task manifest")
        v3_analysis._validate_receipt(row, label=f"historical {key}", followup=False)
        _raw_stream(row, label=f"historical {key}", json_answer=False)
        historical_index[key] = row
    require(set(historical_index) == expected_historical_keys,
            "Historical result does not contain exactly Full and Sift for every frozen task/repeat")
    task_outcomes = []
    comparisons = {arm: {"wins": 0, "losses": 0, "ties": 0}
                   for arm in ("historical_full", "historical_sift")}
    exact = {"sift_hybrid_stage2": 0, "historical_full": 0, "historical_sift": 0}
    majorities = {key: 0 for key in exact}
    historical_cost_rows: dict[str, list[dict[str, Any]]] = {"historical_full": [], "historical_sift": []}
    for task in task_ids:
        hybrid = [row_index[(task, repeat, EXPECTED_ARM)] for repeat in EXPECTED_REPEATS]
        full = [historical_index[(task, repeat, "full")] for repeat in EXPECTED_REPEATS]
        sift = [historical_index[(task, repeat, "sift")] for repeat in EXPECTED_REPEATS]
        for arm, sample in (("sift_hybrid_stage2", hybrid), ("historical_full", full), ("historical_sift", sift)):
            exact[arm] += sum(row.get("correct") is True for row in sample)
            majority = sum(row.get("correct") is True for row in sample) >= 2
            majorities[arm] += int(majority)
        hybrid_maj = sum(row.get("correct") is True and row.get("strict_sample_valid") is True for row in hybrid) >= 2
        for key, sample in (("historical_full", full), ("historical_sift", sift)):
            historical_maj = sum(row.get("correct") is True for row in sample) >= 2
            outcome = "tie" if hybrid_maj == historical_maj else ("win" if hybrid_maj else "loss")
            comparisons[key][_comparison_key(outcome)] += 1
        task_outcomes.append({
            "case_id": task,
            "hybrid_correct_repeats": sum(row.get("correct") is True for row in hybrid),
            "hybrid_majority_correct": hybrid_maj,
            "historical_full_correct_repeats": sum(row.get("correct") is True for row in full),
            "historical_full_majority_correct": sum(row.get("correct") is True for row in full) >= 2,
            "historical_sift_correct_repeats": sum(row.get("correct") is True for row in sift),
            "historical_sift_majority_correct": sum(row.get("correct") is True for row in sift) >= 2,
            "selection_method": hybrid[0].get("selection_method"),
        })
        historical_cost_rows["historical_full"].extend(full)
        historical_cost_rows["historical_sift"].extend(sift)

    input_price, output_price, cache_read_price = _route_pricing(route_path)
    hybrid_metrics = _metric_receipts(rows, input_price, output_price, cache_read_price,
                                     verify_price_reconstruction=True)
    historical_endpoint = frozen_manifest.get("provider_endpoint", {})
    historical_input_price = float(historical_endpoint["input_price_per_million_usd"])
    historical_output_price = float(historical_endpoint["output_price_per_million_usd"])
    historical_metrics = {}
    for key, hist_rows in historical_cost_rows.items():
        historical_metrics[key] = _metric_receipts(
            hist_rows, historical_input_price, historical_output_price, None,
            verify_price_reconstruction=False,
        )
    local_tokens = sum(row["local_rendered_prompt_tokens"] for row in rows)
    historical_local = {
        "historical_full": sum(row.get("local_rendered_prompt_tokens", 0) for row in historical_cost_rows["historical_full"]),
        "historical_sift": sum(row.get("local_rendered_prompt_tokens", 0) for row in historical_cost_rows["historical_sift"]),
    }
    preproc = [float(row["sift_preprocessing_ms"]) for row in rows]
    latency = [float(row["end_to_end_ms"]) for row in rows if isinstance(row.get("end_to_end_ms"), (int, float))]
    first_dispatch = datetime.fromisoformat(rows[0]["request_started_utc"].replace("Z", "+00:00"))
    last_completion = datetime.fromisoformat(result["completed_utc"].replace("Z", "+00:00"))
    reused_count = int(result.get("continuation_provenance", {}).get("checkpoint_samples_reused", 0))
    continuation_start = datetime.fromisoformat(rows[reused_count]["request_started_utc"].replace("Z", "+00:00")) if 0 < reused_count < len(rows) else first_dispatch
    run_elapsed_seconds = (last_completion - first_dispatch).total_seconds()
    continuation_elapsed_seconds = (last_completion - continuation_start).total_seconds()
    return {
        "schema_version": 1,
        "status": "validated",
        "integrity_status": "validated",
        "evaluation": "100-task in-sample hybrid development evaluation, not LongBench full-suite or holdout evidence",
        "sample": {"task_count": len(task_ids), "repeats_per_task": 3, "response_count": len(rows),
                   "candidate_task_count": 6, "default_sift_task_count": 94},
        "provenance": {"result_sha256": sha(result_path), "historical_sha256": sha(historical_path),
                       "historical_content_sha256": _content_sha256(historical_path),
                       "manifest_sha256": sha(manifest_path), "stage_manifest_sha256": sha(stage_path),
                       "route_metadata_sha256": sha(route_path),
                       "analysis_implementation_sha256": sha(Path(__file__).resolve()),
                       "frozen_analyzer_sha256": "d05b2db6ecb48333b60289e4fe8e4b936993184dbde7767560967e8668d80606",
                       "correction_note": "Preserves frozen analyzer; fixes loss pluralization and accepts the frozen normalized route snapshot."},
        "quality": {"exact_choice_correct": exact, "responses_per_arm": 300,
                    "task_majority_correct": majorities, "task_majority_total": 100,
                    "task_majority_comparison_vs_historical": comparisons,
                    "task_outcomes": task_outcomes,
                    "invalid_answer_count": sum(row.get("answer_validity") != "valid" for row in rows)},
        "run_timing": {
            "dispatch_to_completion_seconds": run_elapsed_seconds,
            "dispatch_to_completion_minutes": run_elapsed_seconds / 60,
            "continuation_start_utc": continuation_start.isoformat(),
            "continuation_to_completion_seconds": continuation_elapsed_seconds,
            "continuation_to_completion_minutes": continuation_elapsed_seconds / 60,
            "continuation_request_count": len(rows) - reused_count,
            "checkpoint_samples_reused": reused_count,
        },
        "efficiency": {"local_prompt_tokens": {"hybrid": local_tokens, **historical_local},
                       "local_token_reduction_vs_historical_sift_percent": 100 * (historical_local["historical_sift"] - local_tokens) / historical_local["historical_sift"],
                       "provider_usage_and_cost": {"hybrid": hybrid_metrics, **historical_metrics},
                       "preprocessing_ms_median": statistics.median(preproc),
                       "end_to_end_ms_median": statistics.median(latency),
                       "end_to_end_ms_p95_linear_interpolation": statistics.quantiles(latency, n=20, method="inclusive")[18]},
        "comparison_limits": [
            "Historical Full and Sift are non-concurrent cross-run references; provider behavior, cache state, and timing can differ.",
            "Historical observed costs are the saved upstream receipts from the frozen baseline run. Historical counterfactual estimates use that run's pinned input/output rates; its manifest has no cache-tier prices, so cached receipt costs are not reconstructed from rates.",
            "The relation-matrix candidate was developed on the same six LongBench training prompts it uses here; the 94 unchanged tasks add coverage for the hybrid policy, not candidate generalization.",
            "This is a 100-task development sample, not the full LongBench v2 suite or a blind holdout.",
            "Upstream-reported cost is cache-inclusive provider pass-through data, not an independently verified invoice. The uncached estimate is counterfactual.",
        ],
    }


def markdown(report: dict[str, Any]) -> str:
    q = report["quality"]
    e = report["efficiency"]
    m = e["provider_usage_and_cost"]
    t = report["run_timing"]
    arms = (
        ("sift_hybrid_stage2", "hybrid", "Hybrid Sift (Stage 2)"),
        ("historical_full", "historical_full", "Historical Full"),
        ("historical_sift", "historical_sift", "Historical Sift"),
    )
    full = m["historical_full"]
    hybrid = m["hybrid"]
    sift = m["historical_sift"]
    token_reduction_full = 100 * (full["provider_prompt_tokens"] - hybrid["provider_prompt_tokens"]) / full["provider_prompt_tokens"]
    cost_reduction_full = 100 * (full["upstream_reported_cache_inclusive_cost_usd"] - hybrid["upstream_reported_cache_inclusive_cost_usd"]) / full["upstream_reported_cache_inclusive_cost_usd"]
    token_reduction_sift = 100 * (sift["provider_prompt_tokens"] - hybrid["provider_prompt_tokens"]) / sift["provider_prompt_tokens"]
    cost_increase_sift = 100 * (hybrid["upstream_reported_cache_inclusive_cost_usd"] - sift["upstream_reported_cache_inclusive_cost_usd"]) / sift["upstream_reported_cache_inclusive_cost_usd"]
    accuracy = q["exact_choice_correct"]
    majority = q["task_majority_correct"]
    lines = [
        "# MiniMax LongBench v2 Stage 2 hybrid development evaluation",
        "",
        f"**Integrity:** {report['integrity_status'].upper()} · **Scope:** 100 tasks × 3 repeats · 300 Sift responses",
        "",
        "This hybrid applies the research matrix to six in-sample relation-closure task IDs and unchanged default Sift to the other 94.",
        "",
        "## Results",
        "",
        "| Arm/reference | Exact answers | Task majorities | Provider prompt tokens | Cached prompt share | Observed pass-through cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for quality_arm, metric_arm, title in arms:
        metric = m[metric_arm]
        lines.append(
            f"| {title} | {accuracy[quality_arm]}/300 ({accuracy[quality_arm] / 3:.1f}%) | "
            f"{majority[quality_arm]}/100 | {metric['provider_prompt_tokens']:,} | "
            f"{metric['cached_prompt_fraction'] * 100:.1f}% | "
            f"${metric['upstream_reported_cache_inclusive_cost_usd']:.6f} |"
        )
    lines += [
        "",
        f"Against the saved Full-context reference, this sample recorded **{accuracy['sift_hybrid_stage2'] / 3 - accuracy['historical_full'] / 3:+.1f} percentage points** in exact answers, **{token_reduction_full:.1f}% fewer provider prompt tokens**, and **{cost_reduction_full:.1f}% lower observed pass-through cost**.",
        "",
        f"Against historical Sift, the hybrid recorded **{accuracy['sift_hybrid_stage2'] / 3 - accuracy['historical_sift'] / 3:+.1f} percentage points** in exact answers and **{token_reduction_sift:.1f}% fewer prompt tokens**; observed pass-through cost was **{cost_increase_sift:.1f}% higher**. Cache hit share was {hybrid['cached_prompt_fraction'] * 100:.1f}% for the hybrid and {sift['cached_prompt_fraction'] * 100:.1f}% for historical Sift, so cross-run cost is cache-sensitive.",
        "",
        "## Runtime",
        "",
        f"The full request schedule took **{t['dispatch_to_completion_minutes']:.1f} minutes** from first dispatch through completion, including the safe checkpoint and resume. The resumed 207-request continuation took **{t['continuation_to_completion_minutes']:.1f} minutes**. Per-request end-to-end median was **{e['end_to_end_ms_median']:.0f} ms** (p95 **{e['end_to_end_ms_p95_linear_interpolation']:.0f} ms**).",
        "",
        "## Limits",
        "",
    ]
    lines.extend(f"- {item}" for item in report["comparison_limits"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("result", "historical", "manifest", "stage-manifest", "route-metadata", "json-output", "markdown-output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = _read_json(args.result)
        historical = _read_json(args.historical)
        report = analyze(result, historical, result_path=args.result,
                         historical_path=args.historical, manifest_path=args.manifest,
                         stage_path=args.stage_manifest, route_path=args.route_metadata)
    except (OSError, json.JSONDecodeError, AnalysisError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "responses": 300,
                      "json": str(args.json_output), "markdown": str(args.markdown_output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
