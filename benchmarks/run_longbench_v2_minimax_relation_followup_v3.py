"""Run the six-case stage-one LongBench v2 MiniMax Sift-arm screen.

This is a separate research runner from the historical paired baseline. It
uses six frozen tasks with relation closure followed by option-aligned
complete-entity matrix rendering, at three matched repeats. It compares this
default-off treatment with unchanged default Sift. Any candidate fallback
fails the expansion gate. It never dispatches a full-context arm or retries.

The $4 ceiling is a best-effort client-side guard, not a provider billing cap.
"""

from __future__ import annotations

from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import requests
import sys
import time
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

import run_longbench_v2_minimax as baseline  # noqa: E402
from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from relation_matrix_candidate import MatrixError, matrix_messages  # noqa: E402
from longbench_v3_gate import expansion_gate  # noqa: E402
from sift import CompactionError, CompactionResult, compact_messages  # noqa: E402


FROZEN_CASE_COUNT = 100
STAGE1_CASE_IDS = (
    "672494e5bb02136c067d7697",
    "67249705bb02136c067d76d1",
    "6724c1d4bb02136c067d77ec",
    "67285e1dbb02136c067d901b",
    "67286036bb02136c067d9092",
    "6724c4aabb02136c067d78a6",
)
CASE_COUNT = len(STAGE1_CASE_IDS)
REPEATS = 3
TARGET = 32_768
SAFETY_MARGIN = 128
OUTPUT_TOKENS = 128
ARMS = ("sift_default", "sift_relation_matrix_v3")
MAX_REQUESTS = CASE_COUNT * REPEATS * len(ARMS)
MAX_SPEND_USD = 4.0
MAX_WORKERS = 1
REQUESTED_MODEL = "minimax/minimax-m3"
MAX_FULL_LOCAL_TOKENS = 150_000
PROVIDER_CONTEXT_ESTIMATE_FACTOR = 3.25
OPENROUTER_REQUEST_TOKEN_LIMIT = 524_288
MAX_PROVIDER_LOCAL_INPUT_RATIO = 1.05
AGGREGATE_SPEND_LIMIT_USD = 20.0
MAX_ROUTE_METADATA_AGE_SECONDS = 30 * 60
API_URL = "https://openrouter.ai/api/v1/chat/completions"
JSON_RESPONSE_FORMAT = {"type": "json_object"}


class FollowupError(RuntimeError):
    pass


def token_count(tokenizer: Tokenizer, messages: list[dict[str, Any]]) -> int:
    return len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)


def _messages_hash(messages: list[dict[str, Any]]) -> str:
    canonical = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_payload(job: dict) -> dict:
    return {
        "model": REQUESTED_MODEL,
        "messages": job["messages"],
        "temperature": 0.1,
        "top_p": 0.8,
        "seed": job["generation_seed"],
        "max_tokens": OUTPUT_TOKENS,
        "reasoning": {"enabled": False},
        "response_format": JSON_RESPONSE_FORMAT,
        "stream": True,
        "stream_options": {"include_usage": True},
        "provider": {"only": ["minimax"], "allow_fallbacks": False},
    }


def _json_object_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the frozen v2 output contract without changing source benchmark text."""
    result = [dict(message) for message in messages]
    user_indices = [index for index, message in enumerate(result) if message.get("role") == "user"]
    if not user_indices:
        raise FollowupError("LongBench prompt has no user question")
    index = user_indices[-1]
    content = result[index].get("content")
    if not isinstance(content, str):
        raise FollowupError("LongBench final user message must be plain text")
    result[index]["content"] = (
        content + "\n\nReturn a JSON object with exactly one key, `answer`, whose value is "
        "exactly one uppercase option letter: A, B, C, or D. Do not include an explanation."
    )
    return result


def _json_choice(text: str) -> str | None:
    """Accept only one unambiguous JSON object with a single A-D answer."""
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


def _call_openrouter(request_payload: dict, *, api_key: str) -> dict:
    """Send and score only the exact persisted JSON-object request payload."""
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    first_content = None
    text_parts: list[str] = []
    raw_sse_events: list[str] = []
    usage = None
    finish_reason = None
    provider = None
    returned_model = None
    response_id = None
    status = None
    raw_error_body = None
    try:
        with requests.post(
            API_URL,
            json=request_payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            stream=True,
            timeout=(30, 600),
        ) as response:
            status = response.status_code
            if status != 200:
                raw_error_body = response.text
                return {
                    "http_status": status, "normal": False,
                    "failure": "non_200_response", "raw_error_body": raw_error_body,
                    "raw_sse_events": raw_sse_events, "raw_response_body": None,
                    "model": None, "provider": None, "usage": None,
                    "cost_details": None, "response_id": None,
                    "request_started_utc": started_utc,
                    "response_completed_utc": datetime.now(timezone.utc).isoformat(),
                    "end_to_end_ms": (time.perf_counter() - started) * 1000,
                }
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                raw_sse_events.append(value)
                if value == "[DONE]":
                    break
                chunk = json.loads(value)
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                provider = chunk.get("provider") or provider
                returned_model = chunk.get("model") or returned_model
                response_id = chunk.get("id") or response_id
                for choice in chunk.get("choices", []):
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    visible = delta.get("content")
                    if isinstance(visible, str) and visible:
                        if first_content is None:
                            first_content = time.perf_counter()
                        text_parts.append(visible)
    except Exception as error:
        return {
            "http_status": status, "normal": False,
            "failure": type(error).__name__, "failure_message": str(error),
            "raw_error_body": raw_error_body, "raw_sse_events": raw_sse_events,
            "raw_response_body": "\n".join(raw_sse_events), "model": returned_model,
            "provider": provider, "response_id": response_id, "usage": usage,
            "cost_details": usage.get("cost_details") if isinstance(usage, dict) else None,
            "request_started_utc": started_utc,
            "response_completed_utc": datetime.now(timezone.utc).isoformat(),
            "end_to_end_ms": (time.perf_counter() - started) * 1000,
        }

    ended = time.perf_counter()
    text = "".join(text_parts)
    choice = _json_choice(text)
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    elapsed_after_first = ended - first_content if first_content is not None else None
    failure = None
    if returned_model != REQUESTED_MODEL:
        failure = "returned_model_missing_or_mismatched"
    elif not isinstance(provider, str) or provider.strip().casefold() != "minimax":
        failure = "returned_provider_missing_or_mismatched"
    normal = finish_reason == "stop" and first_content is not None and failure is None
    return {
        "http_status": status, "normal": normal, "failure": failure,
        "finish_reason": finish_reason, "model": returned_model,
        "response_id": response_id, "answer": text[:500], "choice": choice,
        "valid_structured_choice": choice is not None,
        "ttft_ms": (first_content - started) * 1000 if first_content is not None else None,
        "end_to_end_ms": (ended - started) * 1000,
        "completion_tokens_per_second": (
            completion_tokens / elapsed_after_first
            if type(completion_tokens) is int and elapsed_after_first and elapsed_after_first > 0 else None
        ),
        "provider": provider, "usage": usage,
        "cost_details": usage.get("cost_details") if isinstance(usage, dict) else None,
        "request_started_utc": started_utc,
        "response_completed_utc": datetime.now(timezone.utc).isoformat(),
        "raw_sse_events": raw_sse_events,
        "raw_response_body": "\n".join(raw_sse_events),
        "raw_error_body": raw_error_body,
    }


def _request_hash(request: dict) -> str:
    return hashlib.sha256(json.dumps(
        request, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _reported_cost(usage: Any, *, upstream: bool) -> float:
    if not isinstance(usage, dict):
        return 0.0
    if upstream:
        details = usage.get("cost_details")
        value = details.get("upstream_inference_cost") if isinstance(details, dict) else None
    else:
        value = usage.get("cost")
    return baseline._nonnegative_finite_number(value) or 0.0


def runtime_receipt_issues(usage: Any) -> list[str]:
    """Validate the usage fields needed for spend guards and cache accounting."""
    if not isinstance(usage, dict):
        return ["missing_usage"]
    issues = []
    if usage.get("is_byok") is not True:
        issues.append("unexpected_billing_mode")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if type(prompt_tokens) is not int or prompt_tokens <= 0:
        issues.append("invalid_prompt_tokens")
    if type(completion_tokens) is not int or completion_tokens < 0:
        issues.append("invalid_completion_tokens")
    direct_cost = baseline._nonnegative_finite_number(usage.get("cost"))
    if direct_cost is None:
        issues.append("invalid_openrouter_cost")
    details = usage.get("cost_details")
    if not isinstance(details, dict):
        issues.append("missing_cost_details")
    else:
        names = (
            "upstream_inference_cost",
            "upstream_inference_prompt_cost",
            "upstream_inference_completions_cost",
        )
        amounts = {name: baseline._nonnegative_finite_number(details.get(name)) for name in names}
        if any(value is None for value in amounts.values()):
            issues.append("invalid_upstream_cost_components")
        elif amounts["upstream_inference_cost"] <= 0 or not math.isclose(
            amounts["upstream_inference_prompt_cost"]
            + amounts["upstream_inference_completions_cost"],
            amounts["upstream_inference_cost"], rel_tol=1e-4, abs_tol=1e-8,
        ):
            issues.append("upstream_cost_components_do_not_reconcile")
    prompt_details = usage.get("prompt_tokens_details")
    if not isinstance(prompt_details, dict):
        issues.append("missing_prompt_token_details")
    elif type(prompt_tokens) is int and prompt_tokens > 0:
        cached = prompt_details.get("cached_tokens")
        cache_write = prompt_details.get("cache_write_tokens")
        if (type(cached) is not int or type(cache_write) is not int
                or cached < 0 or cache_write < 0
                or cached + cache_write > prompt_tokens):
            issues.append("invalid_cache_token_details")
    return issues


def load_route_metadata(path: Path, input_price: float, output_price: float) -> dict:
    """Validate the saved OpenRouter endpoint response against the pinned route."""
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FollowupError(f"Invalid UTF-8 OpenRouter route metadata: {path}") from error
    if not isinstance(document, dict):
        raise FollowupError("Route metadata must be a JSON object")
    data = document.get("data", document)
    if not isinstance(data, dict):
        raise FollowupError("Route metadata data field must be an object")
    if isinstance(data.get("endpoints"), list):
        if data.get("id") != REQUESTED_MODEL:
            raise FollowupError(f"Route metadata must describe {REQUESTED_MODEL}")
        matches = [item for item in data["endpoints"] if isinstance(item, dict)
                   and item.get("model_id") == REQUESTED_MODEL
                   and isinstance(item.get("provider_name"), str)
                   and item["provider_name"].strip().casefold() == "minimax"]
        if len(matches) != 1:
            raise FollowupError(f"Expected exactly one pinned Minimax endpoint; found {len(matches)}")
        endpoint = matches[0]
        provider_name = endpoint.get("provider_name")
        endpoint_name = endpoint.get("name")
        endpoint_model = endpoint.get("model_id")
        context_length = endpoint.get("context_length")
        max_prompt_tokens = endpoint.get("max_prompt_tokens")
        pricing = endpoint.get("pricing")
        checked_utc = document.get("checked_utc")
        source_response_sha256 = None
    else:
        # Accept the repository's normalized evidence snapshot as well as the
        # direct OpenRouter endpoint response. It retains the upstream response
        # hash while making the selected endpoint fields explicit.
        endpoint = data
        provider_name = endpoint.get("provider")
        endpoint_name = endpoint.get("provider_endpoint")
        endpoint_model = endpoint.get("endpoint_model_id")
        context_length = endpoint.get("context_length_tokens")
        max_prompt_tokens = endpoint.get("max_prompt_tokens")
        price_data = endpoint.get("pricing_usd_per_token")
        pricing = ({"prompt": price_data.get("prompt"), "completion": price_data.get("completion")}
                   if isinstance(price_data, dict) else None)
        checked_utc = endpoint.get("checked_utc")
        source_response_sha256 = endpoint.get("response_sha256")
        if endpoint.get("requested_model") != REQUESTED_MODEL:
            raise FollowupError(f"Route snapshot must describe {REQUESTED_MODEL}")
    if not isinstance(provider_name, str) or provider_name.strip().casefold() != "minimax":
        raise FollowupError("Route metadata provider must be Minimax")
    if endpoint_model != REQUESTED_MODEL:
        raise FollowupError("Route metadata endpoint model id is unexpected")
    if type(context_length) is not int or context_length != OPENROUTER_REQUEST_TOKEN_LIMIT:
        raise FollowupError("Minimax endpoint context_length must be 524288")
    if type(max_prompt_tokens) is not int or max_prompt_tokens != OPENROUTER_REQUEST_TOKEN_LIMIT:
        raise FollowupError("Minimax endpoint max_prompt_tokens must be 524288")
    if not isinstance(pricing, dict):
        raise FollowupError("Minimax endpoint has no pricing metadata")
    try:
        endpoint_input = float(pricing.get("prompt"))
        endpoint_output = float(pricing.get("completion"))
    except (TypeError, ValueError) as error:
        raise FollowupError("Minimax endpoint rates must be numeric") from error
    if (not math.isfinite(endpoint_input) or not math.isfinite(endpoint_output)
            or endpoint_input <= 0 or endpoint_output <= 0):
        raise FollowupError("Minimax endpoint input/output rates must be positive and finite")
    endpoint_input_million = endpoint_input * 1_000_000
    endpoint_output_million = endpoint_output * 1_000_000
    if (not math.isclose(input_price, endpoint_input_million, rel_tol=1e-9, abs_tol=1e-9)
            or not math.isclose(output_price, endpoint_output_million, rel_tol=1e-9, abs_tol=1e-9)):
        raise FollowupError(
            "CLI prices must match the validated Minimax endpoint rates: "
            f"input=${endpoint_input_million:g}/M output=${endpoint_output_million:g}/M"
        )
    now = datetime.now(timezone.utc)
    try:
        checked_at = (datetime.fromisoformat(checked_utc.replace("Z", "+00:00"))
                      if isinstance(checked_utc, str) else
                      datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
    except ValueError as error:
        raise FollowupError("Route metadata checked_utc is invalid") from error
    if checked_at.tzinfo is None:
        raise FollowupError("Route metadata checked_utc must include a timezone")
    age_seconds = (now - checked_at.astimezone(timezone.utc)).total_seconds()
    if age_seconds < -60:
        raise FollowupError("Route metadata checked_utc is unexpectedly in the future")
    if age_seconds > MAX_ROUTE_METADATA_AGE_SECONDS:
        raise FollowupError(
            f"Route metadata is stale ({age_seconds:.0f}s; max age {MAX_ROUTE_METADATA_AGE_SECONDS}s)"
        )
    if source_response_sha256 is not None and (
        not isinstance(source_response_sha256, str) or len(source_response_sha256) != 64
    ):
        raise FollowupError("Route metadata source response SHA-256 is malformed")
    return {
        "checked_utc": checked_at.astimezone(timezone.utc).isoformat(),
        "validated_utc": now.isoformat(),
        "metadata_age_seconds": max(0.0, age_seconds),
        "metadata_max_age_seconds": MAX_ROUTE_METADATA_AGE_SECONDS,
        "metadata_path": str(path.resolve()),
        "metadata_sha256": hashlib.sha256(raw).hexdigest(),
        "source_response_sha256": source_response_sha256,
        "endpoint_name": endpoint_name,
        "provider_name": provider_name,
        "model_id": endpoint_model,
        "context_length": context_length,
        "max_prompt_tokens": max_prompt_tokens,
        "input_usd_per_million": endpoint_input_million,
        "output_usd_per_million": endpoint_output_million,
        "metadata_file_mtime_utc": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def load_stage_manifest(path: Path, seed: int, baseline_manifest_path: Path,
                        route_metadata_path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FollowupError(f"Invalid UTF-8 stage manifest: {path}") from error
    if not isinstance(manifest, dict):
        raise FollowupError("Stage manifest must be a JSON object")
    protocol = manifest.get("protocol", manifest)
    if not isinstance(protocol, dict):
        raise FollowupError("Stage manifest protocol must be an object")
    stage = protocol.get("stage", manifest.get("stage"))
    task_ids = protocol.get("task_ids", manifest.get("task_ids"))
    repeats = protocol.get("repeats", manifest.get("repeats"))
    manifest_seed = protocol.get("cli_seed", manifest.get("cli_seed"))
    generation_seeds = protocol.get("generation_seeds", manifest.get("generation_seeds"))
    arms = protocol.get("arms", manifest.get("arms"))
    target = protocol.get("sift_target_tokens", protocol.get("target_tokens",
                          manifest.get("sift_target_tokens", manifest.get("target_tokens"))))
    request_count = protocol.get("request_count", manifest.get("request_count"))
    model = protocol.get("model", manifest.get("model"))
    if isinstance(model, dict):
        model = model.get("id")
    if model is None:
        model = protocol.get("requested_model", manifest.get("requested_model"))
    provider_policy = protocol.get("provider_policy", manifest.get("provider_policy"))
    if provider_policy is None:
        route = protocol.get("route", manifest.get("route"))
        if isinstance(route, dict):
            provider_policy = route.get("provider")
    if stage != 1:
        raise FollowupError("Stage manifest must declare stage 1")
    if task_ids != list(STAGE1_CASE_IDS):
        raise FollowupError("Stage manifest task_ids must exactly match the six frozen stage-one IDs")
    if repeats != REPEATS:
        raise FollowupError("Stage manifest repeats must equal 3")
    if manifest_seed != seed or generation_seeds != [seed + r + 1 for r in range(1, REPEATS + 1)]:
        raise FollowupError("Stage manifest CLI/generation seeds do not match this run")
    if arms != list(ARMS):
        raise FollowupError("Stage manifest must declare both Sift arms in protocol order")
    if target != TARGET:
        raise FollowupError(f"Stage manifest Sift target must equal {TARGET}")
    generation = protocol.get("generation")
    if (not isinstance(generation, dict)
            or generation.get("max_tokens") != OUTPUT_TOKENS
            or generation.get("response_format") != JSON_RESPONSE_FORMAT
            or generation.get("answer_format") != "json_object_single_answer_a_to_d"):
        raise FollowupError("Stage manifest generation must match the frozen JSON-object output contract")
    if request_count != MAX_REQUESTS:
        raise FollowupError(f"Stage manifest allowed request_count must equal {MAX_REQUESTS}")
    if model != REQUESTED_MODEL:
        raise FollowupError(f"Stage manifest model must be {REQUESTED_MODEL}")
    if (not isinstance(provider_policy, dict)
            or provider_policy.get("only") != ["minimax"]
            or provider_policy.get("allow_fallbacks") is not False):
        raise FollowupError("Stage manifest provider policy must pin minimax with fallbacks disabled")
    expected_baseline_hash = manifest.get("baseline_manifest_sha256")
    if expected_baseline_hash != file_sha256(baseline_manifest_path):
        raise FollowupError("Stage manifest baseline_manifest_sha256 does not match the supplied frozen manifest")
    declared_route_path = manifest.get("route_metadata_path")
    if not isinstance(declared_route_path, str):
        raise FollowupError("Stage manifest must declare route_metadata_path")
    declared_route_resolved = Path(declared_route_path)
    if not declared_route_resolved.is_absolute():
        declared_route_resolved = ROOT / declared_route_resolved
    if declared_route_resolved.resolve() != route_metadata_path.resolve():
        raise FollowupError("--route-metadata path differs from stage manifest route_metadata_path")
    if manifest.get("route_metadata_sha256") != file_sha256(route_metadata_path):
        raise FollowupError("Stage manifest route_metadata_sha256 does not match supplied route metadata")
    baseline_result_path = ROOT / "docs/results/longbench-v2-minimax-m3-100-2026-10-16.json"
    if (not baseline_result_path.is_file()
            or manifest.get("baseline_result_sha256") != file_sha256(baseline_result_path)):
        raise FollowupError("Stage manifest baseline_result_sha256 does not match the frozen baseline result")
    protocol_path_value = manifest.get("protocol_path")
    if not isinstance(protocol_path_value, str):
        raise FollowupError("Stage manifest must declare protocol_path")
    protocol_path = (ROOT / protocol_path_value).resolve()
    try:
        protocol_path.relative_to(ROOT)
    except ValueError as error:
        raise FollowupError("Stage manifest protocol_path escapes the repository") from error
    if not protocol_path.is_file():
        raise FollowupError("Stage manifest protocol_path does not exist")
    declared_sources = manifest.get("source_hashes")
    if not isinstance(declared_sources, dict):
        raise FollowupError("Stage manifest source_hashes must be an object")
    protocol_hash = declared_sources.get("protocol_sha256")
    if not isinstance(protocol_hash, str) or protocol_hash != file_sha256(protocol_path):
        raise FollowupError("Stage manifest protocol_sha256 does not match protocol_path")
    source_checks = {
        "runner_sha256": Path(__file__).resolve(),
        "analyzer_sha256": ROOT / "benchmarks/analyze_longbench_v2_minimax_relation_followup_v3.py",
        "matrix_candidate_sha256": ROOT / "benchmarks/relation_matrix_candidate.py",
        "gate_module_sha256": ROOT / "benchmarks/longbench_v3_gate.py",
        "core_sha256": ROOT / "src/sift/core.py",
    }
    for key, source_path in source_checks.items():
        if declared_sources.get(key) != file_sha256(source_path):
            raise FollowupError(f"Stage manifest {key} does not match current source: {source_path}")
    aggregate = manifest.get("aggregate_budget")
    if not isinstance(aggregate, dict):
        raise FollowupError("Stage manifest aggregate_budget is missing")
    limit = aggregate.get("limit_usd")
    if (type(limit) not in {int, float} or not math.isfinite(float(limit))
            or float(limit) != AGGREGATE_SPEND_LIMIT_USD):
        raise FollowupError(f"Stage manifest aggregate budget limit must be ${AGGREGATE_SPEND_LIMIT_USD:.2f}")
    for key in ("prior_actual_usd", "prior_unsettled_usd"):
        amount = aggregate.get(key)
        if (type(amount) not in {int, float} or not math.isfinite(float(amount))
                or float(amount) < 0):
            raise FollowupError(f"Stage manifest aggregate_budget.{key} must be a known nonnegative amount")
    return manifest, hashlib.sha256(raw).hexdigest()


def load_frozen_cases(manifest_path: Path, dataset_path: Path,
                      tokenizer_path: Path, template_path: Path):
    """Verify frozen sample inputs, while separately recording the new core hash."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("model", {}).get("id") != REQUESTED_MODEL:
        raise FollowupError(f"Frozen manifest must target {REQUESTED_MODEL}")
    harness = manifest.get("harness")
    if not isinstance(harness, dict):
        raise FollowupError("Frozen harness metadata is missing")
    # The baseline manifest intentionally freezes the old baseline core hash.
    # We verify that provenance below, and bind this run to the current
    # candidate core separately in source_hashes.
    for path_key, digest_key in (
        ("runner_path", "runner_sha256"),
        ("protocol_path", "protocol_sha256"),
        ("preparation_script", "preparation_script_sha256"),
        ("dataset_preparation_module_path", "dataset_preparation_module_sha256"),
        ("m3_renderer_module_path", "m3_renderer_module_sha256"),
    ):
        relative = harness.get(path_key)
        expected_digest = harness.get(digest_key)
        if not isinstance(relative, str) or not isinstance(expected_digest, str):
            raise FollowupError(f"Frozen manifest lacks {path_key}/{digest_key}")
        source_path = (ROOT / relative).resolve()
        try:
            source_path.relative_to(ROOT)
        except ValueError as error:
            raise FollowupError(f"Frozen source path escapes repository: {relative}") from error
        if not source_path.is_file() or file_sha256(source_path) != expected_digest:
            raise FollowupError(f"Frozen source hash mismatch: {relative}")

    frozen_cases = manifest.get("cases")
    if not isinstance(frozen_cases, list) or len(frozen_cases) != FROZEN_CASE_COUNT:
        raise FollowupError(f"Manifest must contain exactly {FROZEN_CASE_COUNT} frozen cases")
    ids = [item.get("id") for item in frozen_cases if isinstance(item, dict)]
    if len(ids) != FROZEN_CASE_COUNT or len(set(ids)) != FROZEN_CASE_COUNT:
        raise FollowupError(f"Manifest must contain {FROZEN_CASE_COUNT} distinct frozen case IDs")
    if manifest.get("selection", {}).get("selected_count") != FROZEN_CASE_COUNT:
        raise FollowupError(f"Frozen manifest selected_count must equal {FROZEN_CASE_COUNT}")
    if not set(STAGE1_CASE_IDS).issubset(set(ids)):
        raise FollowupError("Stage-one task IDs are not all present in the frozen manifest")
    if manifest.get("sift", {}).get("primary_target_tokens") != TARGET:
        raise FollowupError(f"Frozen manifest target must be {TARGET}")
    if manifest.get("dataset", {}).get("revision") != DATASET_REVISION:
        raise FollowupError("Dataset revision differs from the frozen LongBench revision")
    if manifest.get("dataset", {}).get("data_file_sha256") != DATASET_SHA256:
        raise FollowupError("Frozen manifest dataset SHA-256 is unexpected")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise FollowupError("Local LongBench v2 file SHA-256 mismatch")
    model_meta = manifest["model"]
    if file_sha256(tokenizer_path) != model_meta.get("tokenizer_sha256"):
        raise FollowupError("MiniMax tokenizer hash differs from frozen manifest")
    if file_sha256(template_path) != model_meta.get("chat_template_sha256"):
        raise FollowupError("MiniMax chat template hash differs from frozen manifest")

    frozen_core_hash = manifest.get("sift", {}).get("core_sha256")
    if not isinstance(frozen_core_hash, str) or len(frozen_core_hash) != 64:
        raise FollowupError("Baseline core provenance hash is missing")
    core_path = ROOT / "src/sift/core.py"
    current_core_hash = file_sha256(core_path)
    rows = {}
    expected = {item["id"]: item for item in frozen_cases}
    for row in iter_json_array(dataset_path):
        if row.get("_id") in expected:
            rows[row["_id"]] = row
            if len(rows) == FROZEN_CASE_COUNT:
                break
    if set(rows) != set(expected):
        raise FollowupError("Frozen LongBench rows are missing")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    cases = []
    for frozen in frozen_cases:
        if frozen["id"] not in STAGE1_CASE_IDS:
            continue
        row = rows[frozen["id"]]
        messages = make_messages(row)
        if row.get("answer") != frozen.get("answer_key"):
            raise FollowupError(f"Frozen answer key changed: {frozen['id']}")
        if prompt_sha256(messages) != frozen.get("prompt_sha256"):
            raise FollowupError(f"Frozen prompt changed: {frozen['id']}")
        actual = token_count(tokenizer, messages)
        if actual != frozen.get("m3_rendered_prompt_tokens"):
            raise FollowupError(f"Frozen tokenizer count changed: {frozen['id']}")
        if not TARGET < actual <= MAX_FULL_LOCAL_TOKENS:
            raise FollowupError(f"Frozen prompt outside eligibility limits: {frozen['id']}={actual}")
        if frozen.get("answer_key") not in {"A", "B", "C", "D"}:
            raise FollowupError(f"Invalid frozen answer key: {frozen['id']}")
        cases.append({
            "frozen": frozen,
            "messages": messages,
            "full_count": actual,
            "choices": {letter: row[f"choice_{letter}"] for letter in "ABCD"},
        })
    if len(cases) != CASE_COUNT:
        raise FollowupError(f"Stage one must contain exactly {CASE_COUNT} selected tasks")
    return manifest, tokenizer, cases, frozen_core_hash, current_core_hash


def prepare_jobs(cases: list[dict], tokenizer: Tokenizer, seed: int) -> list[dict]:
    prepared_cases = []
    effective_target = TARGET - SAFETY_MARGIN
    if effective_target <= 0:
        raise FollowupError("Sift target does not exceed the safety margin")
    for case in cases:
        frozen = case["frozen"]
        request_messages = _json_object_messages(case["messages"])
        counter = lambda value: token_count(tokenizer, value)
        default_started = time.perf_counter()
        default_result = compact_messages(
            request_messages, counter, target=effective_target,
            raw_limit=1_000_000, protocol="openai",
        )
        default_ms = (time.perf_counter() - default_started) * 1000
        default_tokens = token_count(tokenizer, default_result.messages)
        if default_tokens > effective_target:
            raise FollowupError(f"Default Sift exceeds target for {frozen['id']}: {default_tokens}")

        candidate_ms = None
        fallback_reason = None
        candidate_audit = None
        matrix_audit = None
        candidate_started = time.perf_counter()
        try:
            candidate = compact_messages(
                request_messages, counter, target=effective_target,
                raw_limit=1_000_000, protocol="openai", research_relation_closure=True,
            )
            candidate_audit = candidate.audit
            if candidate.audit.get("comparison_groups_complete") is not True:
                fallback_reason = "research_relation_incomplete_comparison_groups"
            elif (type(candidate.audit.get("unfit_comparison_groups")) is not int
                  or candidate.audit["unfit_comparison_groups"] != 0):
                fallback_reason = "research_relation_nonzero_unfit_groups"
            if fallback_reason is None:
                matrix_result, matrix_audit = matrix_messages(
                    candidate.messages, case["choices"]
                )
                matrix_tokens = token_count(tokenizer, matrix_result)
                if matrix_tokens > effective_target:
                    fallback_reason = "relation_matrix_candidate_exceeded_target"
                else:
                    candidate_result = CompactionResult(
                        matrix_result,
                        {
                            **candidate.audit,
                            "forwarded_tokens": matrix_tokens,
                            "method": "research_relation_closure+option_aligned_matrix_v3",
                            "relation_matrix_audit": matrix_audit,
                        },
                    )
            else:
                candidate_result = default_result
                matrix_tokens = default_tokens
        except MatrixError as error:
            fallback_reason = f"relation_matrix_error:{str(error)[:240]}"
        except CompactionError as error:
            fallback_reason = f"{error.code or 'compaction_error'}:{str(error)[:240]}"

        candidate_ms = (time.perf_counter() - candidate_started) * 1000
        if fallback_reason is None:
            candidate_tokens = matrix_tokens
        else:
            candidate_result = default_result
            candidate_tokens = default_tokens
        for arm, selected, selected_tokens, prep_ms in (
            ("sift_default", default_result, default_tokens, default_ms),
            ("sift_relation_matrix_v3", candidate_result, candidate_tokens,
             (candidate_ms or 0.0) + (default_ms if fallback_reason is not None else 0.0)),
        ):
            projected = math.ceil(selected_tokens * PROVIDER_CONTEXT_ESTIMATE_FACTOR)
            if projected > OPENROUTER_REQUEST_TOKEN_LIMIT:
                raise FollowupError(f"Prompt projects beyond endpoint limit: {frozen['id']}")
            prepared_cases.append({
                "case_id": frozen["id"],
                "domain": frozen["domain"],
                "expected": frozen["answer_key"],
                "arm": arm,
                "target_tokens": TARGET,
                "messages": selected.messages,
                "request_messages_sha256": _messages_hash(selected.messages),
                "original_prompt_sha256": frozen["prompt_sha256"],
                "local_rendered_prompt_tokens": selected_tokens,
                "projected_provider_prompt_tokens": projected,
                "sift_preprocessing_ms": prep_ms,
                "sift_default_preprocessing_ms": default_ms if arm == "sift_default" or fallback_reason is not None else None,
                "research_relation_candidate_ms": candidate_ms if arm == "sift_relation_matrix_v3" else None,
                "research_relation_fallback_reason": fallback_reason if arm == "sift_relation_matrix_v3" else None,
                "research_relation_candidate_audit": candidate_audit if arm == "sift_relation_matrix_v3" else None,
                "relation_matrix_audit": matrix_audit if arm == "sift_relation_matrix_v3" else None,
                "selector_audit": selected.audit,
                "sift_passthrough": selected.messages == case["messages"],
            })
    jobs = []
    for repeat in range(1, REPEATS + 1):
        by_case = {}
        for prepared in prepared_cases:
            by_case.setdefault(prepared["case_id"], []).append(prepared)
        rng = random.Random(seed + repeat)
        case_ids = list(by_case)
        rng.shuffle(case_ids)
        repeat_jobs = []
        for case_id in case_ids:
            pair = [dict(item) for item in by_case[case_id]]
            rng.shuffle(pair)
            for job in pair:
                job["job_id"] = f"{job['case_id']}:{repeat}:{job['arm']}"
                job["repeat"] = repeat
                job["generation_seed"] = seed + repeat + 1
                repeat_jobs.append(job)
        jobs.extend(repeat_jobs)
    if len(jobs) != MAX_REQUESTS:
        raise FollowupError(f"Expected exactly {MAX_REQUESTS} requests; got {len(jobs)}")
    return jobs


def estimate_cost(jobs: list[dict], input_price: float, output_price: float) -> dict:
    raw_input = sum(job["local_rendered_prompt_tokens"] for job in jobs)
    reserved_input = raw_input * baseline.INPUT_ESTIMATE_SAFETY_FACTOR
    max_output = len(jobs) * OUTPUT_TOKENS
    estimated = (reserved_input * input_price + max_output * output_price) / 1_000_000
    return {
        "planned_requests": len(jobs),
        "estimated_input_tokens": raw_input,
        "reserved_input_tokens": reserved_input,
        "maximum_output_tokens": max_output,
        "input_price_usd_per_million": input_price,
        "output_price_usd_per_million": output_price,
        "estimated_reserved_cost_usd": estimated,
        "ceiling_usd": MAX_SPEND_USD,
        "preflight_passed": estimated <= MAX_SPEND_USD,
        "note": "1.5x local input reserve plus max output allowance; best-effort estimate, not a provider-enforced billing limit.",
    }


def _job_guard_cost(job: dict, input_price: float, output_price: float) -> float:
    """Use the v2 output cap in each request reservation and aggregate guard."""
    conservative_input = job["local_rendered_prompt_tokens"] * baseline.INPUT_ESTIMATE_SAFETY_FACTOR
    return (conservative_input * input_price + OUTPUT_TOKENS * output_price) / 1_000_000


def evaluate_stage1_majority_gate(samples: list[dict], pending_jobs: list[dict] | deque) -> dict:
    """Return conservative bounds for v3 candidate-majority and accuracy gates."""
    correct = {
        case_id: {arm: 0 for arm in ARMS}
        for case_id in STAGE1_CASE_IDS
    }
    remaining = {
        case_id: {arm: 0 for arm in ARMS}
        for case_id in STAGE1_CASE_IDS
    }
    for job in pending_jobs:
        if job.get("case_id") in remaining and job.get("arm") in ARMS:
            remaining[job["case_id"]][job["arm"]] += 1
    for sample in samples:
        case_id = sample.get("case_id")
        arm = sample.get("arm")
        if case_id not in correct or arm not in ARMS:
            continue
        is_scored_correct = (
            sample.get("normal") is True
            and sample.get("choice") in {"A", "B", "C", "D"}
            and sample.get("choice") == sample.get("expected")
        )
        correct[case_id][arm] += int(is_scored_correct)

    candidate_correct_total = sum(
        values["sift_relation_matrix_v3"] for values in correct.values()
    )
    default_correct_total = sum(values["sift_default"] for values in correct.values())
    candidate_pending_total = sum(
        values["sift_relation_matrix_v3"] for values in remaining.values()
    )

    candidate_only_possible_cases = []
    candidate_only_confirmed_cases = []
    default_only_guaranteed_cases = []
    for case_id in STAGE1_CASE_IDS:
        candidate_correct = correct[case_id]["sift_relation_matrix_v3"]
        default_correct = correct[case_id]["sift_default"]
        candidate_remaining = remaining[case_id]["sift_relation_matrix_v3"]
        default_remaining = remaining[case_id]["sift_default"]
        candidate_can_majority = candidate_correct + candidate_remaining >= 2
        default_can_avoid_majority = default_correct < 2
        if candidate_can_majority and default_can_avoid_majority:
            candidate_only_possible_cases.append(case_id)
        default_majority_guaranteed = default_correct >= 2
        candidate_majority_impossible = candidate_correct + candidate_remaining < 2
        if default_majority_guaranteed and candidate_majority_impossible:
            default_only_guaranteed_cases.append(case_id)
        default_majority_impossible = default_correct + default_remaining < 2
        if candidate_correct >= 2 and default_majority_impossible:
            candidate_only_confirmed_cases.append(case_id)
    return {
        "candidate_only_possible_count": len(candidate_only_possible_cases),
        "candidate_only_possible_cases": candidate_only_possible_cases,
        "candidate_only_confirmed_count": len(candidate_only_confirmed_cases),
        "candidate_only_confirmed_cases": candidate_only_confirmed_cases,
        "default_only_guaranteed_count": len(default_only_guaranteed_cases),
        "default_only_guaranteed_cases": default_only_guaranteed_cases,
        "required_candidate_only_count": 1,
        "candidate_correct_responses_observed": candidate_correct_total,
        "default_correct_responses_observed": default_correct_total,
        "maximum_candidate_correct_minus_default_correct": (
            candidate_correct_total + candidate_pending_total - default_correct_total
        ),
        "stop_candidate_win_gate": len(candidate_only_possible_cases) < 1,
        "stop_positive_accuracy_gate": (
            candidate_correct_total + candidate_pending_total <= default_correct_total
        ),
        "stop_default_only_gate": False,
    }


def candidate_fallback_jobs(jobs: list[dict]) -> list[dict]:
    return [
        job for job in jobs
        if job.get("arm") == "sift_relation_matrix_v3"
        and job.get("research_relation_fallback_reason") is not None
    ]


def prepared_job_records(jobs: list[dict]) -> list[dict]:
    records = []
    for job in jobs:
        request = _request_payload(job)
        records.append({
            **{key: value for key, value in job.items() if key != "messages"},
            "request": request,
            "request_sha256": _request_hash(request),
        })
    return records


def write_atomic(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def run(manifest_path: Path, stage_manifest_path: Path, route_metadata_path: Path,
        dataset_path: Path, tokenizer_path: Path,
        template_path: Path, output_path: Path, seed: int = 20261022,
        input_price: float = baseline.DEFAULT_INPUT_PRICE_PER_MILLION,
        output_price: float = baseline.DEFAULT_OUTPUT_PRICE_PER_MILLION,
        dry_run: bool = False) -> dict:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite report: {output_path}")
    if (not math.isfinite(input_price) or not math.isfinite(output_price)
            or input_price < 0 or output_price < 0):
        raise ValueError("Prices must be finite and nonnegative")
    route_metadata = load_route_metadata(route_metadata_path, input_price, output_price)
    stage_manifest, stage_manifest_sha256 = load_stage_manifest(
        stage_manifest_path, seed, manifest_path, route_metadata_path
    )
    manifest, tokenizer, cases, frozen_core_hash, current_core_hash = load_frozen_cases(
        manifest_path, dataset_path, tokenizer_path, template_path
    )
    prep_started = time.perf_counter()
    jobs = prepare_jobs(cases, tokenizer, seed)
    prep_wall_ms = (time.perf_counter() - prep_started) * 1000
    if len(jobs) != stage_manifest["request_count"]:
        raise FollowupError("Prepared dispatch count differs from stage manifest request_count")
    budget = estimate_cost(jobs, input_price, output_price)
    aggregate_meta = stage_manifest["aggregate_budget"]
    prior_actual = float(aggregate_meta["prior_actual_usd"])
    prior_unsettled = float(aggregate_meta["prior_unsettled_usd"])
    planned_run_guard = sum(_job_guard_cost(job, input_price, output_price) for job in jobs)
    first_request_reservation = _job_guard_cost(jobs[0], input_price, output_price)
    aggregate_audit = {
        "limit_usd": AGGREGATE_SPEND_LIMIT_USD,
        "prior_actual_usd": prior_actual,
        "prior_unsettled_usd": prior_unsettled,
        "planned_run_guard_reserve_usd": planned_run_guard,
        "first_in_flight_reservation_usd": first_request_reservation,
        "first_in_flight_is_included_in_planned_run_reserve": True,
        "projected_total_exposure_usd": prior_actual + prior_unsettled + planned_run_guard,
        "preflight_passed": (
            prior_actual + prior_unsettled + planned_run_guard <= AGGREGATE_SPEND_LIMIT_USD
        ),
        "accounting_note": "Prior actual plus unsettled reservations plus the full 1.5x planned run guard, which includes each sequential in-flight request reservation.",
    }
    budget["aggregate_exposure_audit"] = aggregate_audit
    report = {
        "schema_version": 1,
        "status": "in_progress",
        "evaluation": "Stage-one six-case, two-arm Sift selector comparison on frozen public LongBench v2 tasks",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_manifest_sha256": file_sha256(manifest_path),
        "stage_manifest_sha256": stage_manifest_sha256,
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "model": REQUESTED_MODEL,
        "provider_endpoint": route_metadata["endpoint_name"],
        "route_metadata": route_metadata,
        "aggregate_exposure_audit": aggregate_audit,
        "route": {
            "api": "OpenRouter chat completions",
            "requested_model": REQUESTED_MODEL,
            "provider": {"only": ["minimax"], "allow_fallbacks": False},
        },
        "source_hashes": {
            "followup_runner_sha256": file_sha256(Path(__file__).resolve()),
            "matrix_candidate_sha256": file_sha256(ROOT / "benchmarks/relation_matrix_candidate.py"),
            "gate_module_sha256": file_sha256(ROOT / "benchmarks/longbench_v3_gate.py"),
            "baseline_runner_sha256": file_sha256(ROOT / manifest["harness"]["runner_path"]),
            "baseline_protocol_sha256": file_sha256(ROOT / manifest["harness"]["protocol_path"]),
            "dataset_preparation_module_sha256": file_sha256(ROOT / manifest["harness"]["dataset_preparation_module_path"]),
            "m3_renderer_module_sha256": file_sha256(ROOT / manifest["harness"]["m3_renderer_module_path"]),
            "baseline_core_sha256": frozen_core_hash,
            "followup_core_sha256": current_core_hash,
            "tokenizer_sha256": file_sha256(tokenizer_path),
            "chat_template_sha256": file_sha256(template_path),
            "route_metadata_sha256": route_metadata["metadata_sha256"],
            "stage_manifest_sha256": stage_manifest_sha256,
            "stage_manifest_source_hashes": stage_manifest.get("source_hashes"),
            "stage_protocol_path": stage_manifest["protocol_path"],
            "stage_protocol_sha256": stage_manifest["source_hashes"]["protocol_sha256"],
        },
        "protocol": {
            "stage": 1,
            "cli_seed": seed,
            "task_ids": list(STAGE1_CASE_IDS),
            "request_count": MAX_REQUESTS,
            "repeats": REPEATS,
            "arms": list(ARMS),
            "sift_target_tokens": TARGET,
            "sift_safety_margin_tokens": SAFETY_MARGIN,
            "research_relation_closure": True,
            "candidate_representation": "option-aligned matrix of complete selected entity records; all fields preserved and source paths recorded",
            "fallback": "matrix parse, coverage or target failure uses baseline Sift for that candidate slot and fails the zero-fallback expansion gate",
            "expansion_gate": "Complete valid 36-row run, zero candidate fallbacks/anomalies, at least one candidate-only task majority, and strictly more exact-choice-correct responses than unchanged default Sift; a pass permits considering a larger run only.",
            "generation_seed_formula": "cli_seed + repeat + 1; same frozen case/repeat as historical paired baseline",
            "generation_seed_support_note": (
                "Seeds are matched request parameters across arms; current route metadata does not list seed support, "
                "so provider-side deterministic RNG is not claimed."
            ),
            "temperature": 0.1,
            "top_p": 0.8,
            "reasoning": "disabled",
            "max_output_tokens": OUTPUT_TOKENS,
            "retries": 0,
            "concurrency": MAX_WORKERS,
            "answer_format": "json_object_single_answer_a_to_d",
            "response_format": JSON_RESPONSE_FORMAT,
            "shuffle": "seeded interleaving per repeat; case pair order and arm order randomized, paired arms share each case/repeat seed",
            "arm_ordering": {
                "strategy": "shuffle_pairs_then_randomize_arm_order",
                "seed_formula": "cli_seed + repeat",
                "cli_seed": seed,
                "one_worker": True,
                "dispatch_job_ids": [job["job_id"] for job in jobs],
            },
        },
        "preparation": {
            "job_generation_wall_ms": prep_wall_ms,
            "preprocessing_metric": "default Sift control compaction and candidate attempt/fallback are separately timed; each request row records its arm timing",
            "per_job_preprocessing_ms": [
                {"job_id": job["job_id"], "sift_preprocessing_ms": job["sift_preprocessing_ms"],
                 "sift_default_preprocessing_ms": job["sift_default_preprocessing_ms"],
                 "research_relation_candidate_ms": job["research_relation_candidate_ms"]}
                for job in jobs
            ],
        },
        "budget": budget,
        "samples": [],
        "not_started_jobs": [],
        "in_flight_request": None,
        "expansion_allowed": None,
        "expansion_gate_reasons": [],
        "actual_dispatch_started": False,
        "dry_run": dry_run,
    }
    fallback_jobs = candidate_fallback_jobs(jobs)
    if fallback_jobs:
        # Keep the paired diagnostic complete when a candidate slot must fall
        # back to default Sift. The fallback is recorded and permanently fails
        # the expansion gate, but it is not an operational reason to abandon
        # the remaining frozen requests.
        report["pre_dispatch_fallback_job_ids"] = [job["job_id"] for job in fallback_jobs]
    if not budget["preflight_passed"]:
        report["status"] = "not_started_estimated_budget_exceeded"
        report["expansion_allowed"] = False
        report["expansion_gate_reasons"] = ["estimated_budget_exceeded"]
        report["prepared_jobs"] = prepared_job_records(jobs)
        report["not_started_jobs"] = [
            {"job_id": job["job_id"], "case_id": job["case_id"], "repeat": job["repeat"],
             "arm": job["arm"], "reason": "estimated_budget_exceeded"}
            for job in jobs
        ]
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        write_atomic(output_path, report)
        return report
    if not aggregate_audit["preflight_passed"]:
        report["status"] = "not_started_aggregate_budget_exceeded"
        report["expansion_allowed"] = False
        report["expansion_gate_reasons"] = ["aggregate_exposure_limit_exceeded"]
        report["prepared_jobs"] = prepared_job_records(jobs)
        report["not_started_jobs"] = [
            {"job_id": job["job_id"], "case_id": job["case_id"], "repeat": job["repeat"],
             "arm": job["arm"], "reason": "aggregate_exposure_limit_exceeded"}
            for job in jobs
        ]
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        write_atomic(output_path, report)
        return report
    if dry_run:
        report["status"] = "prepared_only_no_dispatch"
        report["prepared_jobs"] = prepared_job_records(jobs)
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        write_atomic(output_path, report)
        return report
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise FollowupError("OPENROUTER_API_KEY is required")
    write_atomic(output_path, report)
    pending = deque(jobs)
    actual_guard_spend = 0.0
    stop_reasons: list[str] = []
    report["budget"]["in_flight_reserved_cost_usd"] = 0.0
    report["budget"]["budget_guard_spend_usd"] = 0.0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        while pending:
            job = pending[0]
            reservation = _job_guard_cost(job, input_price, output_price)
            if actual_guard_spend + reservation > MAX_SPEND_USD:
                break
            if (prior_actual + prior_unsettled + actual_guard_spend + reservation
                    > AGGREGATE_SPEND_LIMIT_USD):
                stop_reasons.append("aggregate_exposure_limit_would_be_exceeded")
                break
            pending.popleft()
            # Persist and send the exact same versioned payload, including the
            # JSON-object response format and its larger completion allowance.
            request_payload = _request_payload(job)
            if not report["actual_dispatch_started"]:
                report["actual_dispatch_started"] = True
                report["dispatch_started_utc"] = datetime.now(timezone.utc).isoformat()
            report["budget"]["in_flight_reserved_cost_usd"] = reservation
            report["aggregate_exposure_audit"]["in_flight_reserved_cost_usd"] = reservation
            report["aggregate_exposure_audit"]["projected_total_exposure_including_in_flight_usd"] = (
                prior_actual + prior_unsettled + actual_guard_spend + reservation
            )
            dispatch_timestamp = datetime.now(timezone.utc).isoformat()
            report["in_flight_request"] = {
                "job_id": job["job_id"],
                "request": request_payload,
                "request_sha256": _request_hash(request_payload),
                "dispatch_started_utc": dispatch_timestamp,
            }
            report["aggregate_exposure_audit"]["in_flight_request_job_id"] = job["job_id"]
            write_atomic(output_path, report)
            future = pool.submit(_call_openrouter, request_payload, api_key=api_key)
            try:
                result = future.result()
            except Exception as error:  # defensive: helper ordinarily returns structured failures
                result = {"normal": False, "failure": type(error).__name__,
                          "failure_message": str(error), "http_status": None,
                          "raw_sse_events": [], "raw_response_body": None,
                          "raw_error_body": None, "model": None, "provider": None,
                          "response_id": None, "usage": None, "cost_details": None}
            usage = result.get("usage")
            receipt, receipt_source = baseline.cost_receipt(usage)
            valid = True
            receipt_issues = runtime_receipt_issues(usage)
            if receipt_issues:
                valid = False
            for issue in receipt_issues:
                stop_reasons.append(f"invalid_usage_cost_or_cache_receipt:{issue}")
            prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
            completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
            ratio = (prompt_tokens / job["local_rendered_prompt_tokens"]
                     if type(prompt_tokens) is int and prompt_tokens > 0 else None)
            if result.get("http_status") != 200 or result.get("model") != REQUESTED_MODEL:
                stop_reasons.append("route_attribution_mismatch")
                valid = False
            provider = result.get("provider")
            if not isinstance(provider, str) or provider.strip().casefold() != "minimax":
                stop_reasons.append("provider_attribution_mismatch")
                valid = False
            if type(prompt_tokens) is not int or prompt_tokens <= 0:
                stop_reasons.append("missing_provider_prompt_usage")
                valid = False
            elif ratio is None or ratio > MAX_PROVIDER_LOCAL_INPUT_RATIO:
                stop_reasons.append("provider_local_input_ratio_exceeded")
                valid = False
            if type(completion_tokens) is not int or completion_tokens < 0:
                stop_reasons.append("missing_provider_completion_usage")
                valid = False
            if receipt is None:
                stop_reasons.append(f"missing_or_invalid_cost_receipt:{receipt_source}")
                valid = False
            if result.get("failure") is not None:
                stop_reasons.append("generation_transport_or_stream_failure")
                valid = False
            answer_valid = (
                result.get("normal") is True
                and result.get("finish_reason") == "stop"
                and result.get("choice") in {"A", "B", "C", "D"}
            )
            charge = receipt if receipt is not None else reservation
            actual_guard_spend += charge
            if actual_guard_spend > MAX_SPEND_USD:
                stop_reasons.append("client_budget_ceiling_exceeded")
                valid = False
            report["budget"]["in_flight_reserved_cost_usd"] = 0.0
            report["aggregate_exposure_audit"]["in_flight_reserved_cost_usd"] = 0.0
            report["in_flight_request"] = None
            report["aggregate_exposure_audit"]["in_flight_request_job_id"] = None
            report["aggregate_exposure_audit"]["settled_run_guard_spend_usd"] = actual_guard_spend
            report["aggregate_exposure_audit"]["projected_total_exposure_including_in_flight_usd"] = (
                prior_actual + prior_unsettled + actual_guard_spend
            )
            if report["aggregate_exposure_audit"]["projected_total_exposure_including_in_flight_usd"] > AGGREGATE_SPEND_LIMIT_USD:
                stop_reasons.append("aggregate_exposure_limit_exceeded_after_settlement")
                valid = False
            sample = {
                **result,
                **{key: value for key, value in job.items() if key not in {"messages"}},
                "request": request_payload,
                "request_sha256": _request_hash(request_payload),
                "correct": (
                    answer_valid
                    and result.get("choice") == job["expected"]
                ),
                "provider_local_input_token_ratio": ratio,
                "cost_receipt_status": (
                    "reported" if receipt is not None and not receipt_issues
                    else "missing_or_invalid"
                ),
                "cost_receipt_source": receipt_source,
                "receipt": usage,
                "guard_reserved_cost_usd": reservation,
                "guard_charge_usd": charge,
                "strict_receipt_valid": receipt is not None and not receipt_issues,
                "strict_sample_valid": valid and answer_valid,
                "valid_structured_choice": result.get("choice") in {"A", "B", "C", "D"},
                "answer_validity": "valid" if answer_valid else "invalid_or_incomplete",
            }
            report["samples"].append(sample)
            report["budget"].update({
                "actual_openrouter_reported_cost_usd": sum(
                    _reported_cost(s.get("usage"), upstream=False)
                    for s in report["samples"]
                ),
                "actual_upstream_reported_cost_usd": sum(
                    _reported_cost(s.get("usage"), upstream=True)
                    for s in report["samples"]
                ),
                "budget_guard_spend_usd": actual_guard_spend,
                "unknown_cost_receipts": sum(s["cost_receipt_status"] != "reported" for s in report["samples"]),
                "max_provider_local_input_ratio": max(
                    (s["provider_local_input_token_ratio"] for s in report["samples"]
                     if s["provider_local_input_token_ratio"] is not None), default=None
                ),
                "stop_reasons": sorted(set(stop_reasons)),
            })
            write_atomic(output_path, report)
            gate_progress = evaluate_stage1_majority_gate(report["samples"], pending)
            report["expansion_gate_progress"] = gate_progress
            report["quality_gate_progress_only_not_an_operational_stop"] = True
            write_atomic(output_path, report)
            if stop_reasons:
                break
    if pending:
        report["not_started_jobs"] = [
            {"job_id": job["job_id"], "case_id": job["case_id"], "repeat": job["repeat"],
             "arm": job["arm"],
             "reason": ";".join(sorted(set(stop_reasons)))
             or "remaining_cost_reservation_would_exceed_4_usd"}
            for job in pending
        ]
    if stop_reasons:
        report["status"] = "safety_guard_stopped"
    elif pending:
        report["status"] = "budget_guard_stopped"
    else:
        report["status"] = "complete"
    fallback_seen = any(
        sample.get("research_relation_fallback_reason") is not None
        for sample in report["samples"]
    )
    final_quality_gate = report.get("expansion_gate_progress") or evaluate_stage1_majority_gate(
        report["samples"], pending
    )
    report["expansion_gate_progress"] = final_quality_gate
    candidate_correct = sum(bool(s.get("correct")) for s in report["samples"]
                            if s.get("arm") == "sift_relation_matrix_v3")
    default_correct = sum(bool(s.get("correct")) for s in report["samples"]
                          if s.get("arm") == "sift_default")
    no_anomalies = not report["budget"].get("stop_reasons")
    final_gate = expansion_gate(
        complete_pair_receipts=(report["status"] == "complete"
                                and len(report["samples"]) == MAX_REQUESTS),
        no_candidate_fallbacks=not fallback_seen,
        no_anomalies=no_anomalies,
        no_invalid_answers=all(
            sample.get("strict_sample_valid") is True
            and sample.get("valid_structured_choice") is True
            for sample in report["samples"]
        ),
        candidate_only_majorities=final_quality_gate["candidate_only_confirmed_count"],
        candidate_exact_correct=candidate_correct,
        default_exact_correct=default_correct,
    )
    report["expansion_gate"] = final_gate
    report["expansion_allowed"] = final_gate["decision"] == "PASS"
    if fallback_seen:
        report["expansion_gate_reasons"].append("candidate_fallback_observed")
    if report["status"] != "complete":
        report["expansion_gate_reasons"].append(f"run_status_{report['status']}")
    if not final_gate["criteria"].get("no_invalid_answers", False):
        report["expansion_gate_reasons"].append("invalid_or_incomplete_answers_observed")
    if len(report["samples"]) != MAX_REQUESTS:
        report["expansion_gate_reasons"].append("stage_one_request_count_incomplete")
    if not report["expansion_allowed"] and not report["expansion_gate_reasons"]:
        report["expansion_gate_reasons"].append("strict_sample_or_answer_gate_failed")
    report["expansion_gate_reasons"] = sorted(set(report["expansion_gate_reasons"]))
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    write_atomic(output_path, report)
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a stage-one six-task, two-arm LongBench v2 Sift comparison (36 MiniMax requests)."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stage-manifest", type=Path, required=True,
                        help="Versioned stage-one manifest with task, seed, route, and source hashes.")
    parser.add_argument("--route-metadata", type=Path, required=True,
                        help="Saved OpenRouter /api/v1/models/minimax/minimax-m3/endpoints JSON response.")
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "tmp" / "minimax-m3-tokenizer.json")
    parser.add_argument("--template", type=Path, default=ROOT / "tmp" / "minimax-m3-chat-template.jinja")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate both manifests/routes and write all 36 prepared requests without API-key access or dispatch.")
    parser.add_argument("--seed", type=int, default=20261022,
                        help="CLI seed; yields matched repeat seeds 20261024, 20261025, and 20261026.")
    parser.add_argument("--input-price-per-million", type=float,
                        default=baseline.DEFAULT_INPUT_PRICE_PER_MILLION)
    parser.add_argument("--output-price-per-million", type=float,
                        default=baseline.DEFAULT_OUTPUT_PRICE_PER_MILLION)
    args = parser.parse_args()
    result = run(args.manifest, args.stage_manifest, args.route_metadata,
                 args.dataset_path, args.tokenizer, args.template,
                 args.output, args.seed, args.input_price_per_million,
                 args.output_price_per_million, dry_run=args.dry_run)
    print(json.dumps({"status": result["status"], "samples": len(result["samples"]),
                      "not_started": len(result["not_started_jobs"]),
                      "output": str(args.output)}, indent=2))
