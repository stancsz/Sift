"""Run a frozen MiniMax M3 LongBench sample through OpenRouter in parallel.

The default run compares full context with one primary Sift target (32K) on
every selected case, including cases where Sift is a pass-through. A local
tokenizer-based cost estimate must fit under the configured ceiling before
the first provider request is sent.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import threading
import time
from typing import Any

import requests
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import (  # noqa: E402
    render_minimax,
)
from sift import compact_messages  # noqa: E402


API_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUESTED_MODEL = "minimax/minimax-m3"
OUTPUT_TOKENS = 16
MAX_WORKERS = 4
SAFETY_MARGIN = 128
DEFAULT_TARGET = 32_768
DEFAULT_REPEATS = 3
# Defaults use prior observed MiniMax BYOK upstream usage receipts. Override
# these flags if the rates applicable to the account have changed.
DEFAULT_INPUT_PRICE_PER_MILLION = 0.30
DEFAULT_OUTPUT_PRICE_PER_MILLION = 1.20
DEFAULT_ESTIMATED_SPEND_CEILING_USD = 20.0
# Route-specific M3 receipts have matched the pinned local tokenizer so far.
# Keep a 1.5x cost reserve, and fail closed if any new prompt count exceeds 1.05x.
# This is a best-effort local guard, not a provider-enforced hard billing cap.
INPUT_ESTIMATE_SAFETY_FACTOR = 1.5
MAX_PROVIDER_LOCAL_INPUT_RATIO = 1.05
OPENROUTER_REQUEST_TOKEN_LIMIT = 524_288
PROVIDER_CONTEXT_ESTIMATE_FACTOR = 3.25
FULL_CASE_COUNT = 100
FULL_REPEATS = 3
PRIMARY_TARGET = 32_768
MAX_FULL_LOCAL_TOKENS = 150_000
class EvaluationError(RuntimeError):
    pass


def count_prompt(tokenizer: Tokenizer, messages: list[dict[str, str]]) -> int:
    rendered = render_minimax(messages)
    return len(tokenizer.encode(rendered, add_special_tokens=False).ids)


def load_cases(manifest_path: Path, dataset_path: Path, tokenizer_path: Path, template_path: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    harness = manifest.get("harness", {})
    if not isinstance(harness, dict):
        raise EvaluationError("Frozen manifest harness metadata is missing")
    frozen_sources = [
        ("runner_path", "runner_sha256"),
        ("protocol_path", "protocol_sha256"),
        ("preparation_script", "preparation_script_sha256"),
        ("dataset_preparation_module_path", "dataset_preparation_module_sha256"),
        ("m3_renderer_module_path", "m3_renderer_module_sha256"),
    ]
    for path_key, digest_key in frozen_sources:
        relative_path = harness.get(path_key)
        expected_digest = harness.get(digest_key)
        if not isinstance(relative_path, str) or not isinstance(expected_digest, str):
            raise EvaluationError(f"Frozen manifest must record {path_key} and {digest_key}")
        source_path = (ROOT / relative_path).resolve()
        try:
            source_path.relative_to(ROOT)
        except ValueError as error:
            raise EvaluationError(f"Frozen source path escapes repository: {relative_path}") from error
        if not source_path.is_file() or file_sha256(source_path) != expected_digest:
            raise EvaluationError(f"Frozen preparation source hash mismatch: {relative_path}")
    if manifest.get("model", {}).get("id") != REQUESTED_MODEL:
        raise EvaluationError(f"Frozen manifest must target {REQUESTED_MODEL}")
    frozen_cases = manifest.get("cases")
    if not isinstance(frozen_cases, list) or len(frozen_cases) != FULL_CASE_COUNT:
        raise EvaluationError(f"Frozen manifest must contain exactly {FULL_CASE_COUNT} cases")
    case_ids = [case.get("id") for case in frozen_cases if isinstance(case, dict)]
    if len(case_ids) != FULL_CASE_COUNT or len(set(case_ids)) != FULL_CASE_COUNT:
        raise EvaluationError("Frozen manifest must contain exactly 100 distinct case IDs")
    if manifest.get("selection", {}).get("selected_count") != FULL_CASE_COUNT:
        raise EvaluationError("Frozen manifest metadata must record exactly 100 selected cases")
    if manifest.get("sift", {}).get("primary_target_tokens") != PRIMARY_TARGET:
        raise EvaluationError(f"Frozen manifest target must be {PRIMARY_TARGET} tokens")
    if manifest["dataset"]["revision"] != DATASET_REVISION or manifest["dataset"]["data_file_sha256"] != DATASET_SHA256:
        raise EvaluationError("Frozen sample does not use the pinned LongBench v2 dataset")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise EvaluationError("Local LongBench v2 file SHA-256 mismatch")
    if file_sha256(tokenizer_path) != manifest["model"]["tokenizer_sha256"]:
        raise EvaluationError("MiniMax tokenizer hash differs from frozen manifest")
    if file_sha256(template_path) != manifest["model"]["chat_template_sha256"]:
        raise EvaluationError("MiniMax chat template hash differs from frozen manifest")
    core_hash = hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest()
    if core_hash != manifest["sift"]["core_sha256"]:
        raise EvaluationError("Sift core changed after sample freeze")
    expected = {case["id"]: case for case in manifest["cases"]}
    rows = {}
    for row in iter_json_array(dataset_path):
        if row["_id"] in expected:
            rows[row["_id"]] = row
            if len(rows) == len(expected):
                break
    if set(rows) != set(expected):
        raise EvaluationError("Frozen LongBench rows are missing")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    prepared = []
    for frozen in manifest["cases"]:
        row = rows[frozen["id"]]
        messages = make_messages(row)
        if row["answer"] != frozen["answer_key"] or prompt_sha256(messages) != frozen["prompt_sha256"]:
            raise EvaluationError(f"Frozen prompt or answer changed: {frozen['id']}")
        actual_count = count_prompt(tokenizer, messages)
        if actual_count != frozen["m3_rendered_prompt_tokens"]:
            raise EvaluationError(f"MiniMax tokenizer count changed: {frozen['id']}")
        if not PRIMARY_TARGET < actual_count <= MAX_FULL_LOCAL_TOKENS:
            raise EvaluationError(
                f"Frozen full prompt must be >{PRIMARY_TARGET} and <= {MAX_FULL_LOCAL_TOKENS} "
                f"local M3 tokens: {frozen['id']}={actual_count}"
            )
        projected_provider_count = math.ceil(actual_count * PROVIDER_CONTEXT_ESTIMATE_FACTOR)
        if projected_provider_count > OPENROUTER_REQUEST_TOKEN_LIMIT:
            raise EvaluationError(
                f"Frozen full prompt projects beyond the observed OpenRouter request limit: "
                f"{frozen['id']} local={actual_count}, projected={projected_provider_count}, "
                f"limit={OPENROUTER_REQUEST_TOKEN_LIMIT}"
            )
        if row["answer"] not in {"A", "B", "C", "D"}:
            raise EvaluationError(f"Invalid LongBench v2 answer key: {frozen['id']}")
        prepared.append({"frozen": frozen, "messages": messages, "full_count": actual_count})
    return manifest, tokenizer, prepared


def make_jobs(cases: list[dict], tokenizer: Tokenizer, seed: int, repeat: int,
              target_tokens: int) -> list[dict]:
    jobs = []
    def messages_digest(messages: list[dict[str, str]]) -> str:
        packed = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(packed.encode("utf-8")).hexdigest()

    for case in cases:
        frozen = case["frozen"]
        case_id = frozen["id"]
        full_count = case["full_count"]
        jobs.append({
            "case_id": case_id,
            "domain": frozen["domain"],
            "expected": frozen["answer_key"],
            "arm": "full",
            "target": None,
            "messages": deepcopy(case["messages"]),
            "estimated_tokens": full_count,
            "projected_provider_tokens": math.ceil(full_count * PROVIDER_CONTEXT_ESTIMATE_FACTOR),
            "selector_audit": None,
            "repeat": repeat,
            "generation_seed": seed + repeat + 1,
            "sift_preprocessing_ms": None,
            "request_messages_sha256": messages_digest(case["messages"]),
        })
        effective_target = target_tokens - SAFETY_MARGIN
        if effective_target <= 0:
            raise EvaluationError("target must be larger than the safety margin")
        below_budget_before_selection = full_count <= effective_target
        preprocessing_started = time.perf_counter()
        result = compact_messages(
            case["messages"], lambda value: count_prompt(tokenizer, value),
            target=effective_target, raw_limit=1_000_000, protocol="openai",
        )
        measured = count_prompt(tokenizer, result.messages)
        sift_preprocessing_ms = (time.perf_counter() - preprocessing_started) * 1000
        if measured > effective_target:
            raise EvaluationError(f"Sift prompt exceeds target for {case_id} at {target_tokens}")
        projected_provider_count = math.ceil(measured * PROVIDER_CONTEXT_ESTIMATE_FACTOR)
        if projected_provider_count > OPENROUTER_REQUEST_TOKEN_LIMIT:
            raise EvaluationError(f"Sift prompt projects beyond the observed OpenRouter request limit: {case_id}")
        passthrough = result.messages == case["messages"]
        jobs.append({
            "case_id": case_id,
            "domain": frozen["domain"],
            "expected": frozen["answer_key"],
            "arm": "sift",
            "target": target_tokens,
            "messages": result.messages,
            "estimated_tokens": measured,
            "projected_provider_tokens": projected_provider_count,
            "passthrough": passthrough,
            "below_budget_before_selection": below_budget_before_selection,
            "selector_audit": result.audit,
            "repeat": repeat,
            "generation_seed": seed + repeat + 1,
            "sift_preprocessing_ms": sift_preprocessing_ms,
            "request_messages_sha256": messages_digest(result.messages),
        })
    random.Random(seed + repeat).shuffle(jobs)
    return jobs


def parse_choice(text: str) -> str | None:
    choice = text.strip()
    return choice if choice in {"A", "B", "C", "D"} else None


def call_openrouter(job: dict, *, api_key: str, seed: int) -> dict:
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    first_content = None
    text_parts: list[str] = []
    usage = None
    finish_reason = None
    provider = None
    returned_model = None
    response_id = None
    status = None
    raw_sse_events: list[str] = []
    raw_error_body = None
    payload = {
        "model": REQUESTED_MODEL,
        "messages": job["messages"],
        "temperature": 0.1,
        "top_p": 0.8,
        "seed": seed,
        "max_tokens": OUTPUT_TOKENS,
        "reasoning": {"enabled": False},
        "stream": True,
        "stream_options": {"include_usage": True},
        "provider": {"only": ["minimax"], "allow_fallbacks": False},
    }
    try:
        with requests.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            stream=True,
            timeout=(30, 600),
        ) as response:
            status = response.status_code
            if status != 200:
                raw_error_body = response.text
                return {"http_status": status, "normal": False,
                        "failure": "non_200_response", "raw_error_body": raw_error_body,
                        "raw_sse_events": raw_sse_events, "raw_response_body": None,
                        "model": None, "provider": None, "usage": None,
                        "cost_details": None, "response_id": None,
                        "request_started_utc": started_utc,
                        "response_completed_utc": datetime.now(timezone.utc).isoformat(),
                        "end_to_end_ms": (time.perf_counter() - started) * 1000}
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
            "http_status": status,
            "normal": False,
            "failure": type(error).__name__,
            "failure_message": str(error),
            "raw_error_body": raw_error_body,
            "raw_sse_events": raw_sse_events,
            "raw_response_body": "\n".join(raw_sse_events),
            "model": returned_model,
            "provider": provider,
            "response_id": response_id,
            "usage": usage,
            "cost_details": usage.get("cost_details") if isinstance(usage, dict) else None,
            "request_started_utc": started_utc,
            "response_completed_utc": datetime.now(timezone.utc).isoformat(),
            "end_to_end_ms": (time.perf_counter() - started) * 1000,
        }

    ended = time.perf_counter()
    text = "".join(text_parts)
    choice = parse_choice(text)
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    elapsed_after_first = ended - first_content if first_content is not None else None
    failure = None
    if returned_model != REQUESTED_MODEL:
        failure = "returned_model_missing_or_mismatched"
    elif not isinstance(provider, str) or provider.strip().casefold() != "minimax":
        failure = "returned_provider_missing_or_mismatched"
    normal = finish_reason == "stop" and first_content is not None and failure is None
    return {
        "http_status": status,
        "normal": normal,
        "failure": failure,
        "finish_reason": finish_reason,
        "model": returned_model,
        "response_id": response_id,
        "answer": text[:500],
        "choice": choice,
        "valid_structured_choice": choice is not None,
        "ttft_ms": (first_content - started) * 1000 if first_content is not None else None,
        "end_to_end_ms": (ended - started) * 1000,
        "completion_tokens_per_second": (
            completion_tokens / elapsed_after_first
            if type(completion_tokens) is int and elapsed_after_first and elapsed_after_first > 0 else None
        ),
        "provider": provider,
        "usage": usage,
        "cost_details": usage.get("cost_details") if isinstance(usage, dict) else None,
        "request_started_utc": started_utc,
        "response_completed_utc": datetime.now(timezone.utc).isoformat(),
        "raw_sse_events": raw_sse_events,
        "raw_response_body": "\n".join(raw_sse_events),
        "raw_error_body": raw_error_body,
    }


def estimate_budget(jobs: list[dict], repeats: int, *, input_price_per_million: float,
                    output_price_per_million: float, ceiling_usd: float) -> dict:
    """Estimate the planned run from local M3 rendered tokens and output caps."""
    input_tokens = sum(job["estimated_tokens"] for job in jobs)
    conservative_input_tokens = input_tokens * INPUT_ESTIMATE_SAFETY_FACTOR
    output_tokens = len(jobs) * OUTPUT_TOKENS
    estimated_input_cost = conservative_input_tokens * input_price_per_million / 1_000_000
    estimated_output_cost = output_tokens * output_price_per_million / 1_000_000
    estimated = estimated_input_cost + estimated_output_cost
    return {
        "basis": "local published MiniMax tokenizer rendered counts; provider usage is authoritative after calls",
        "planned_requests": len(jobs),
        "repeats": repeats,
        "estimated_input_tokens": input_tokens,
        "conservative_input_tokens_for_budget": conservative_input_tokens,
        "estimated_max_output_tokens": output_tokens,
        "input_price_usd_per_million": input_price_per_million,
        "output_price_usd_per_million": output_price_per_million,
        "estimated_input_cost_usd": estimated_input_cost,
        "estimated_max_output_cost_usd": estimated_output_cost,
        "estimated_total_cost_usd": estimated,
        "ceiling_usd": ceiling_usd,
        "preflight_passed": estimated <= ceiling_usd,
        "actual_openrouter_reported_cost_usd": 0.0,
        "actual_upstream_reported_cost_usd": 0.0,
        "actual_cost_basis": "separate OpenRouter and upstream-reported fields; guard settles to the larger reported value when both exist, otherwise the available value; provider receipts are not invoice-verified",
        "input_estimate_safety_factor": INPUT_ESTIMATE_SAFETY_FACTOR,
        "input_estimate_note": "Budget guard reserves 1.5x local M3 rendered tokens based on route-specific exact provider/local prompt counts from development and longest-case smoke receipts; dispatch closes if any observed ratio exceeds 1.05x. A separate 3.25x context projection checks the verified 524,288-token Minimax endpoint prompt limit. These are best-effort estimates, not provider-enforced limits or guaranteed invoice bounds.",
        "pricing_source": "OpenRouter endpoint metadata checked 2026-10-16 for Minimax minimax/minimax-m3-20260531: $0.30/M input and $1.20/M output; configurable because endpoint/account rates may change.",
        "budget_guard_spend_usd": 0.0,
        "budget_guard_settlement_note": "Reported provider cost when available; otherwise the reserved estimate is charged against the guard. This accounting value is not an invoice.",
        "unknown_cost_receipts": 0,
        "unknown_cost_job_ids": [],
        "max_provider_local_input_ratio": None,
        "max_provider_local_input_ratio_guard": MAX_PROVIDER_LOCAL_INPUT_RATIO,
        "stop_reasons": [],
        "budget_guard_stopped": False,
    }


def estimate_job_guard_cost(job: dict, input_price_per_million: float,
                            output_price_per_million: float) -> float:
    conservative_input = job["estimated_tokens"] * INPUT_ESTIMATE_SAFETY_FACTOR
    return (
        conservative_input * input_price_per_million
        + OUTPUT_TOKENS * output_price_per_million
    ) / 1_000_000


def _nonnegative_finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def cost_receipt(usage: Any) -> tuple[float | None, str]:
    """Return one guard-settlement amount, or None when the receipt is unknown."""
    if not isinstance(usage, dict):
        return None, "missing_usage"
    details = usage.get("cost_details")
    upstream = details.get("upstream_inference_cost") if isinstance(details, dict) else None
    direct = usage.get("cost")
    valid_upstream = _nonnegative_finite_number(upstream)
    valid_direct = _nonnegative_finite_number(direct)
    if (upstream is not None and valid_upstream is None) or (direct is not None and valid_direct is None):
        return None, "invalid_cost_receipt"
    if usage.get("is_byok") is not True:
        return None, "unexpected_billing_mode"
    if valid_upstream is None or valid_upstream <= 0:
        return None, "byok_zero_or_missing_upstream_cost"
    if valid_upstream is not None and valid_direct is not None:
        return max(valid_upstream, valid_direct), "max_upstream_or_openrouter_cost"
    if valid_upstream is not None:
        return valid_upstream, "upstream_inference_cost"
    if usage.get("is_byok") is True:
        return None, "byok_without_upstream_cost"
    if valid_direct is not None:
        return valid_direct, "openrouter_cost"
    return None, "missing_cost_fields"


def update_actual_budget(report: dict) -> None:
    openrouter_cost = 0.0
    upstream_cost = 0.0
    guard_spend = 0.0
    unknown_cost_job_ids = []
    for sample in report.get("samples", []):
        usage = sample.get("usage")
        if isinstance(usage, dict):
            cost = usage.get("cost")
            valid_cost = _nonnegative_finite_number(cost)
            if valid_cost is not None:
                openrouter_cost += valid_cost
            details = usage.get("cost_details")
            if isinstance(details, dict):
                upstream = details.get("upstream_inference_cost")
                valid_upstream = _nonnegative_finite_number(upstream)
                if valid_upstream is not None:
                    upstream_cost += valid_upstream
        guard_spend += float(sample.get("guard_charge_usd", 0.0))
        if sample.get("cost_receipt_status") != "reported":
            unknown_cost_job_ids.append(sample.get("job_id"))
    report["budget"]["actual_openrouter_reported_cost_usd"] = openrouter_cost
    report["budget"]["actual_upstream_reported_cost_usd"] = upstream_cost
    report["budget"]["budget_guard_spend_usd"] = guard_spend
    report["budget"]["unknown_cost_receipts"] = len(unknown_cost_job_ids)
    report["budget"]["unknown_cost_job_ids"] = unknown_cost_job_ids


def write_report_atomic(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(manifest_path: Path, dataset_path: Path, tokenizer_path: Path,
        template_path: Path, output_path: Path, repeats: int, seed: int, workers: int,
        target_tokens: int = DEFAULT_TARGET, case_ids: list[str] | None = None,
        estimated_spend_ceiling_usd: float = DEFAULT_ESTIMATED_SPEND_CEILING_USD,
        input_price_per_million: float = DEFAULT_INPUT_PRICE_PER_MILLION,
        output_price_per_million: float = DEFAULT_OUTPUT_PRICE_PER_MILLION,
        smoke: bool = False) -> dict:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite report: {output_path}")
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if repeats < 1:
        raise ValueError("repeats must be at least one")
    if target_tokens <= SAFETY_MARGIN:
        raise ValueError(f"target must be greater than the {SAFETY_MARGIN}-token safety margin")
    if not math.isfinite(estimated_spend_ceiling_usd) or estimated_spend_ceiling_usd <= 0:
        raise ValueError("estimated spend ceiling must be positive")
    if (not math.isfinite(input_price_per_million) or not math.isfinite(output_price_per_million)
            or input_price_per_million < 0 or output_price_per_million < 0):
        raise ValueError("input and output prices must be nonnegative")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise EvaluationError("OPENROUTER_API_KEY is required")
    manifest, tokenizer, cases = load_cases(manifest_path, dataset_path, tokenizer_path, template_path)
    if len(cases) != FULL_CASE_COUNT:
        raise EvaluationError(
            f"Full-run manifest must contain exactly {FULL_CASE_COUNT} frozen cases; observed {len(cases)}"
        )
    if len({case["frozen"]["id"] for case in cases}) != FULL_CASE_COUNT:
        raise EvaluationError(f"Full-run manifest must contain {FULL_CASE_COUNT} distinct case IDs")
    over_context_cap = [
        (case["frozen"]["id"], case["full_count"])
        for case in cases if case["full_count"] > MAX_FULL_LOCAL_TOKENS
    ]
    if over_context_cap:
        preview = ", ".join(f"{case_id}={tokens}" for case_id, tokens in over_context_cap[:5])
        raise EvaluationError(
            f"Manifest has full prompts over the {MAX_FULL_LOCAL_TOKENS}-token local cap: {preview}"
        )
    if case_ids:
        if not smoke or len(case_ids) != 1:
            raise EvaluationError("A case subset is allowed only for an explicit one-case --smoke run")
        if repeats != 1:
            raise EvaluationError("A one-case --smoke run must use exactly one repeat")
        if target_tokens != PRIMARY_TARGET:
            raise EvaluationError(f"Smoke run must use the primary {PRIMARY_TARGET}-token Sift target")
        selected_ids = set(case_ids)
        if len(selected_ids) != 1:
            raise EvaluationError("Smoke mode requires one distinct frozen case ID")
        cases = [case for case in cases if case["frozen"]["id"] in selected_ids]
        if len(cases) != len(selected_ids):
            raise EvaluationError("Requested case IDs do not match distinct frozen cases")
    elif smoke:
        raise EvaluationError("--smoke requires exactly one --case-id")
    else:
        if repeats != FULL_REPEATS:
            raise EvaluationError(f"Full run requires exactly {FULL_REPEATS} repeats")
        if target_tokens != PRIMARY_TARGET:
            raise EvaluationError(f"Full run requires the primary {PRIMARY_TARGET}-token Sift target")
    jobs = []
    job_preparation_started = time.perf_counter()
    for repeat in range(1, repeats + 1):
        jobs.extend(make_jobs(cases, tokenizer, seed, repeat, target_tokens))
    job_preparation_wall_ms = (time.perf_counter() - job_preparation_started) * 1000
    budget = estimate_budget(
        jobs, repeats, input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
        ceiling_usd=estimated_spend_ceiling_usd,
    )
    report = {
        "schema_version": 1,
        "status": "in_progress",
        "evaluation": "public LongBench v2 MiniMax M3 development screen; not a holdout or model-to-model comparison",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": file_sha256(manifest_path),
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "sift_core_sha256": hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest(),
        "model": REQUESTED_MODEL,
        "full_context_local_token_cap": MAX_FULL_LOCAL_TOKENS,
        "openrouter_endpoint_max_prompt_tokens": OPENROUTER_REQUEST_TOKEN_LIMIT,
        "provider_context_estimate_factor": PROVIDER_CONTEXT_ESTIMATE_FACTOR,
        "route": "OpenRouter; requested model and MiniMax provider are verified per response; allow_fallbacks=false",
        "provider_endpoint": manifest.get("provider_endpoint"),
        "source_hashes": {
            "runner_sha256": file_sha256(Path(__file__).resolve()),
            "manifest_sha256": file_sha256(manifest_path),
            "protocol_sha256": file_sha256(ROOT / manifest["harness"]["protocol_path"]),
            "sample_preparation_script_sha256": file_sha256(
                ROOT / manifest["harness"]["preparation_script"]
            ),
            "dataset_preparation_module_sha256": file_sha256(
                ROOT / manifest["harness"]["dataset_preparation_module_path"]
            ),
            "m3_renderer_module_sha256": file_sha256(
                ROOT / manifest["harness"]["m3_renderer_module_path"]
            ),
            "sift_core_sha256": hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest(),
            "tokenizer_sha256": file_sha256(tokenizer_path),
            "chat_template_sha256": file_sha256(template_path),
        },
        "budget": budget,
        "execution": {
            "arms": ["full", "sift"], "sift_target_tokens": target_tokens,
            "full_context_local_token_cap": MAX_FULL_LOCAL_TOKENS,
            "sift_safety_margin_tokens": SAFETY_MARGIN,
            "repeats": repeats, "concurrency": workers,
            "cli_seed": seed,
            "generation_seed_formula": "cli_seed + repeat + 1; paired arms share each case/repeat seed",
            "request_order": "seeded shuffle across cases, arms, and repeats",
            "temperature": 0.1, "top_p": 0.8, "reasoning": "disabled",
            "max_output_tokens": OUTPUT_TOKENS, "retries": 0,
            "answer_format": "exactly one option letter; only exact A/B/C/D outputs are scorable",
            "provider_usage_is_authoritative": True,
            "requested_model": REQUESTED_MODEL,
            "provider_policy": {"only": ["minimax"], "allow_fallbacks": False},
        },
        "preparation": {
            "tokenizer_count": "MiniMax published tokenizer over published rendered chat template",
            "job_generation_wall_ms": job_preparation_wall_ms,
            "sift_preprocessing_metric": "per-request job.sift_preprocessing_ms measures compact_messages plus post-compaction token recount; null for full-context arm",
            "provider_count_note": "Per-request OpenRouter usage is authoritative; local token counts include a 128-token safety margin for Sift targets.",
            "context_projection": {
                "factor": PROVIDER_CONTEXT_ESTIMATE_FACTOR,
                "observed_request_token_limit": OPENROUTER_REQUEST_TOKEN_LIMIT,
                "note": "The 3.25x projection is a conservative client-side check against the current provider-specific endpoint metadata; actual provider usage is captured per request.",
            },
        },
        "samples": [],
        "mode": "single_case_smoke" if smoke else "full_100_case_run",
    }
    if case_ids:
        report["selected_case_ids"] = list(case_ids)
    report["budget"]["in_flight_reserved_cost_usd"] = 0.0
    if not budget["preflight_passed"]:
        report["status"] = "not_started_estimated_budget_exceeded"
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        write_report_atomic(output_path, report)
        raise EvaluationError(
            f"Estimated cost ${budget['estimated_total_cost_usd']:.6f} exceeds ceiling "
            f"${estimated_spend_ceiling_usd:.2f}; no API requests were sent"
        )
    write_report_atomic(output_path, report)
    pending_jobs = deque(jobs)
    in_flight: dict[Any, tuple[dict, float]] = {}
    guard_spend = 0.0
    stopped_for_budget = False
    budget_gate_closed = False
    safety_stop_reasons: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while pending_jobs or in_flight:
            while pending_jobs and len(in_flight) < workers:
                if budget_gate_closed:
                    break
                if guard_spend > estimated_spend_ceiling_usd:
                    stopped_for_budget = True
                    budget_gate_closed = True
                    break
                job = pending_jobs[0]
                reservation = estimate_job_guard_cost(
                    job, input_price_per_million, output_price_per_million
                )
                reserved_in_flight = sum(amount for _, amount in in_flight.values())
                if guard_spend + reserved_in_flight + reservation > estimated_spend_ceiling_usd:
                    stopped_for_budget = True
                    budget_gate_closed = True
                    break
                pending_jobs.popleft()
                future = pool.submit(call_openrouter, job, api_key=api_key,
                                     seed=job["generation_seed"])
                in_flight[future] = (job, reservation)

            if not in_flight:
                break
            report["budget"]["in_flight_reserved_cost_usd"] = sum(
                amount for _, amount in in_flight.values()
            )
            report["in_flight_jobs"] = [
                {
                    "job_id": f"{active_job['case_id']}:{active_job['arm']}:{active_job['repeat']}",
                    "reserved_cost_usd": active_reservation,
                }
                for active_job, active_reservation in in_flight.values()
            ]
            write_report_atomic(output_path, report)
            completed, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in completed:
                job, reservation = in_flight.pop(future)
                try:
                    result = future.result()
                except Exception as error:
                    result = {
                        "normal": False, "failure": type(error).__name__,
                        "failure_message": str(error), "http_status": None,
                        "raw_sse_events": [], "raw_response_body": None,
                        "raw_error_body": None, "model": None, "provider": None,
                        "response_id": None, "usage": None, "cost_details": None,
                        "end_to_end_ms": None,
                    }
                actual_cost, receipt_source = cost_receipt(result.get("usage"))
                receipt_reported = actual_cost is not None
                guard_charge = actual_cost if receipt_reported else reservation
                guard_spend += guard_charge
                usage = result.get("usage")
                provider_prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
                ratio = (
                    provider_prompt_tokens / job["estimated_tokens"]
                    if type(provider_prompt_tokens) is int and provider_prompt_tokens > 0
                    and job["estimated_tokens"] > 0
                    else None
                )
                route_valid = (
                    result.get("http_status") == 200
                    and result.get("model") == REQUESTED_MODEL
                    and isinstance(result.get("provider"), str)
                    and result["provider"].strip().casefold() == "minimax"
                )
                if not route_valid and "route_attribution_mismatch" not in safety_stop_reasons:
                    safety_stop_reasons.append("route_attribution_mismatch")
                if ratio is None and "missing_provider_prompt_usage" not in safety_stop_reasons:
                    safety_stop_reasons.append("missing_provider_prompt_usage")
                elif ratio is not None and ratio > MAX_PROVIDER_LOCAL_INPUT_RATIO:
                    if "provider_local_input_ratio_exceeded" not in safety_stop_reasons:
                        safety_stop_reasons.append("provider_local_input_ratio_exceeded")
                if not receipt_reported:
                    cost_reason = (
                        "invalid_provider_cost_receipt"
                        if receipt_source == "invalid_cost_receipt"
                        else "missing_provider_cost_receipt"
                    )
                    if cost_reason not in safety_stop_reasons:
                        safety_stop_reasons.append(cost_reason)
                if safety_stop_reasons:
                    budget_gate_closed = True
                    stopped_for_budget = True
                result.update({
                    "job_id": f"{job['case_id']}:{job['arm']}:{job['repeat']}",
                    "case_id": job["case_id"], "domain": job["domain"], "arm": job["arm"],
                    "target_tokens": job["target"], "repeat": job["repeat"],
                    "generation_seed": job["generation_seed"],
                    "request_messages_sha256": job["request_messages_sha256"],
                    "sift_preprocessing_ms": job["sift_preprocessing_ms"],
                    "expected": job["expected"],
                    "correct": result.get("normal") is True and result.get("choice") == job["expected"],
                    "local_rendered_prompt_tokens": job["estimated_tokens"],
                    "provider_local_input_token_ratio": ratio,
                    "projected_provider_prompt_tokens": job["projected_provider_tokens"],
                    "sift_passthrough": job["passthrough"] if job["arm"] == "sift" else False,
                    "full_prompt_below_target_before_selection": (
                        job["below_budget_before_selection"] if job["arm"] == "sift" else None
                    ),
                    "selector_audit": job["selector_audit"],
                    "cost_receipt_status": "reported" if receipt_reported else "missing",
                    "cost_receipt_source": receipt_source,
                    "guard_reserved_cost_usd": reservation,
                    "guard_charge_usd": guard_charge,
                })
                report["samples"].append(result)
                update_actual_budget(report)
                report["budget"]["stop_reasons"] = list(safety_stop_reasons)
                ratios = [
                    sample["provider_local_input_token_ratio"]
                    for sample in report["samples"]
                    if isinstance(sample.get("provider_local_input_token_ratio"), (int, float))
                ]
                report["budget"]["max_provider_local_input_ratio"] = max(ratios) if ratios else None
                report["budget"]["in_flight_reserved_cost_usd"] = sum(
                    amount for _, amount in in_flight.values()
                )
                report["in_flight_jobs"] = [
                    {
                        "job_id": f"{active_job['case_id']}:{active_job['arm']}:{active_job['repeat']}",
                        "reserved_cost_usd": active_reservation,
                    }
                    for active_job, active_reservation in in_flight.values()
                ]
                write_report_atomic(output_path, report)
                if guard_spend > estimated_spend_ceiling_usd:
                    stopped_for_budget = True
                    budget_gate_closed = True
            report["budget"]["in_flight_reserved_cost_usd"] = sum(
                amount for _, amount in in_flight.values()
            )
            report["in_flight_jobs"] = [
                {
                    "job_id": f"{active_job['case_id']}:{active_job['arm']}:{active_job['repeat']}",
                    "reserved_cost_usd": active_reservation,
                }
                for active_job, active_reservation in in_flight.values()
            ]
            write_report_atomic(output_path, report)

    if pending_jobs:
        report["not_started_jobs"] = [
            {
                "job_id": f"{job['case_id']}:{job['arm']}:{job['repeat']}",
                "case_id": job["case_id"], "arm": job["arm"], "repeat": job["repeat"],
                "target_tokens": job["target"],
                "local_rendered_prompt_tokens": job["estimated_tokens"],
                "reserved_cost_usd": estimate_job_guard_cost(
                    job, input_price_per_million, output_price_per_million
                ),
                "reason": ";".join(safety_stop_reasons) if safety_stop_reasons
                else "actual_usage_plus_in_flight_reservations_reached_budget_ceiling",
            }
            for job in pending_jobs
        ]
    report["budget"]["budget_guard_stopped"] = (
        stopped_for_budget or bool(pending_jobs) or guard_spend > estimated_spend_ceiling_usd
    )
    if guard_spend > estimated_spend_ceiling_usd:
        report["status"] = "budget_guard_overrun"
    elif safety_stop_reasons:
        report["status"] = "safety_guard_stopped"
    elif pending_jobs:
        report["status"] = "budget_guard_stopped"
    else:
        report["status"] = "complete"
    report["budget"]["in_flight_reserved_cost_usd"] = 0.0
    report["in_flight_jobs"] = []
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    write_report_atomic(output_path, report)
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-path", type=Path, default=(Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"))
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "tmp" / "minimax-m3-tokenizer.json")
    parser.add_argument("--template", type=Path, default=ROOT / "tmp" / "minimax-m3-chat-template.jinja")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--target", type=int, default=DEFAULT_TARGET,
                        help="Primary Sift context target in local MiniMax-tokenizer tokens.")
    parser.add_argument("--case-id", action="append", dest="case_ids",
                        help="Optional frozen case subset; repeat the flag for multiple IDs.")
    parser.add_argument("--smoke", action="store_true",
                        help="Explicitly allow one frozen case with exactly one repeat.")
    parser.add_argument("--estimated-spend-ceiling-usd", type=float,
                        default=DEFAULT_ESTIMATED_SPEND_CEILING_USD)
    parser.add_argument("--input-price-per-million", type=float,
                        default=DEFAULT_INPUT_PRICE_PER_MILLION)
    parser.add_argument("--output-price-per-million", type=float,
                        default=DEFAULT_OUTPUT_PRICE_PER_MILLION)
    args = parser.parse_args()
    result = run(args.manifest, args.dataset_path, args.tokenizer, args.template, args.output,
                 args.repeats, args.seed, args.workers, args.target, args.case_ids,
                 args.estimated_spend_ceiling_usd, args.input_price_per_million,
                 args.output_price_per_million, args.smoke)
    print(json.dumps({"status": result["status"], "samples": len(result["samples"]),
                      "output": str(args.output)}, indent=2))
