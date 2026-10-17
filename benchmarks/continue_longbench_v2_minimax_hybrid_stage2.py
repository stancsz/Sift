"""Continue an interrupted Stage 2 run from a validated receipt checkpoint.

The continuation keeps the original Stage 2 runner and source hashes frozen.
It uses only request objects from the original no-dispatch preflight artifact,
never rewrites the source checkpoint, and refuses ambiguous in-flight jobs.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "src"))

import run_longbench_v2_minimax as baseline  # noqa: E402
import run_longbench_v2_minimax_hybrid_stage2 as stage2  # noqa: E402
import run_longbench_v2_minimax_relation_followup_v3 as v3  # noqa: E402


class ContinuationError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContinuationError(message)


def validate_dispatch_prefix(dispatch_ids: list[str], samples: list[dict[str, Any]]) -> None:
    sample_ids = [sample.get("job_id") for sample in samples]
    _require(sample_ids == dispatch_ids[:len(samples)],
             "Checkpoint samples are not an exact dispatched prefix; refusing duplicate-risk continuation")


def require_resumable_checkpoint(checkpoint: dict[str, Any]) -> None:
    _require(checkpoint.get("status") == "in_progress", "Checkpoint must be an interrupted in-progress result")
    _require(checkpoint.get("dry_run") is False, "Checkpoint cannot be a dry run")
    _require(checkpoint.get("actual_dispatch_started") is True, "Checkpoint has no dispatch history")
    _require(checkpoint.get("in_flight_request") is None,
             "Checkpoint has an ambiguous in-flight request; reconcile its provider receipt before resuming")
    _require(not checkpoint.get("budget", {}).get("stop_reasons"),
             "Checkpoint stopped on a safety guard; do not resume automatically")


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise ContinuationError(f"Frozen path escapes repository: {value}") from error
    return path


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContinuationError(f"Cannot read JSON artifact {path}: {error}") from error
    _require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def _revalidate_sample_from_sse(sample: dict[str, Any], expected: dict[str, Any]) -> None:
    events = sample.get("raw_sse_events")
    _require(isinstance(events, list) and events, f"Checkpoint raw SSE is missing: {sample.get('job_id')}")
    text_parts: list[str] = []
    usage: Any = None
    model = provider = response_id = None
    finish_reason = None
    first_content = False
    done_seen = False
    for event in events:
        _require(isinstance(event, str), f"Checkpoint SSE event is not text: {sample.get('job_id')}")
        if event == "[DONE]":
            done_seen = True
            continue
        try:
            chunk = json.loads(event)
        except json.JSONDecodeError as error:
            raise ContinuationError(f"Malformed raw SSE JSON: {sample.get('job_id')}") from error
        _require(isinstance(chunk, dict), f"Raw SSE chunk is not an object: {sample.get('job_id')}")
        if chunk.get("usage") is not None:
            usage = chunk["usage"]
        model = chunk.get("model") or model
        provider = chunk.get("provider") or provider
        response_id = chunk.get("id") or response_id
        for choice_data in chunk.get("choices", []):
            if choice_data.get("finish_reason") is not None:
                finish_reason = choice_data["finish_reason"]
            delta = choice_data.get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str) and content:
                first_content = True
                text_parts.append(content)
    text = "".join(text_parts)
    _require(done_seen, f"Checkpoint raw SSE is missing the terminal [DONE] event: {sample.get('job_id')}")
    choice = v3._json_choice(text)
    failure = None
    if model != stage2.REQUESTED_MODEL:
        failure = "returned_model_missing_or_mismatched"
    elif not isinstance(provider, str) or provider.strip().casefold() != "minimax":
        failure = "returned_provider_missing_or_mismatched"
    normal = finish_reason == "stop" and first_content and failure is None
    answer_valid = (normal and choice in {"A", "B", "C", "D"})
    job_id = sample.get("job_id")
    _require(sample.get("answer") == text[:500], f"Raw SSE answer differs: {job_id}")
    _require(sample.get("choice") == choice, f"Raw SSE structured choice differs: {job_id}")
    _require(sample.get("valid_structured_choice") is (choice is not None),
             f"Raw SSE validity flag differs: {job_id}")
    _require(sample.get("finish_reason") == finish_reason and sample.get("normal") is normal,
             f"Raw SSE finish/normal status differs: {job_id}")
    _require(sample.get("failure") == failure and sample.get("model") == model
             and sample.get("provider") == provider,
             f"Raw SSE attribution/failure differs: {job_id}")
    _require(sample.get("response_id") == response_id, f"Raw SSE response ID differs: {job_id}")
    _require(sample.get("usage") == usage and sample.get("receipt") == usage,
             f"Raw SSE usage receipt differs: {job_id}")
    _require(sample.get("cost_details") == (usage.get("cost_details") if isinstance(usage, dict) else None),
             f"Raw SSE cost details differ: {job_id}")
    _require(sample.get("raw_response_body") == "\n".join(events),
             f"Raw SSE response body differs: {job_id}")
    _require(sample.get("answer_validity") == ("valid" if answer_valid else "invalid_or_incomplete"),
             f"Raw SSE answer-validity classification differs: {job_id}")
    _require(sample.get("correct") is (answer_valid and choice == expected.get("expected")),
             f"Raw SSE correctness classification differs: {job_id}")
    _require(sample.get("strict_sample_valid") is answer_valid,
             f"Raw SSE strict-sample classification differs: {job_id}")


def validate_checkpoint_samples(preflight_requests: list[dict[str, Any]],
                                samples: list[dict[str, Any]],
                                expected_jobs: list[dict[str, Any]] | None = None) -> tuple[dict[str, dict[str, Any]], float]:
    """Validate unique completed receipts against frozen requests; return rows and settled spend."""
    request_by_id: dict[str, dict[str, Any]] = {}
    for record in preflight_requests:
        _require(isinstance(record, dict), "Preflight request row must be an object")
        job_id = record.get("job_id")
        _require(isinstance(job_id, str) and job_id not in request_by_id,
                 f"Preflight has duplicate or invalid job ID: {job_id}")
        request = record.get("request")
        _require(isinstance(request, dict), f"Preflight request body is missing: {job_id}")
        _require(record.get("request_sha256") == v3._request_hash(request),
                 f"Preflight request hash is invalid: {job_id}")
        request_by_id[job_id] = record
    job_by_id = {job.get("job_id"): job for job in expected_jobs or []}
    if expected_jobs is not None:
        _require(len(job_by_id) == len(expected_jobs), "Frozen job metadata IDs are not unique")

    seen: set[str] = set()
    settled = 0.0
    by_id: dict[str, dict[str, Any]] = {}
    for sample in samples:
        _require(isinstance(sample, dict), "Checkpoint sample must be an object")
        job_id = sample.get("job_id")
        _require(isinstance(job_id, str) and job_id not in seen,
                 f"Checkpoint has duplicate or invalid job ID: {job_id}")
        seen.add(job_id)
        expected = request_by_id.get(job_id)
        _require(expected is not None, f"Checkpoint contains a job outside preflight: {job_id}")
        frozen_job = job_by_id.get(job_id) if expected_jobs is not None else None
        if expected_jobs is not None:
            _require(frozen_job is not None, f"Checkpoint job metadata is not in preflight: {job_id}")
            volatile = {"default_sift_preprocessing_ms", "candidate_preprocessing_ms", "sift_preprocessing_ms"}
            for key, value in frozen_job.items():
                if key in volatile or key in {"messages", "request_payload"}:
                    continue
                _require(sample.get(key) == value,
                         f"Checkpoint sample metadata differs from frozen job for {job_id}: {key}")
        request = sample.get("request")
        _require(request == expected["request"], f"Checkpoint request body differs from preflight: {job_id}")
        _require(sample.get("request_sha256") == expected["request_sha256"]
                 and v3._request_hash(request) == expected["request_sha256"],
                 f"Checkpoint request hash differs from preflight: {job_id}")
        _require(sample.get("http_status") == 200, f"Checkpoint HTTP status is invalid: {job_id}")
        if frozen_job is not None:
            _revalidate_sample_from_sse(sample, frozen_job)
        else:
            _require(sample.get("model") == stage2.REQUESTED_MODEL,
                     f"Checkpoint model attribution is invalid: {job_id}")
            _require(isinstance(sample.get("provider"), str)
                     and sample["provider"].casefold() == "minimax",
                     f"Checkpoint provider attribution is invalid: {job_id}")
        usage = sample.get("usage")
        receipt, receipt_source = baseline.cost_receipt(usage)
        issues = v3.runtime_receipt_issues(usage)
        _require(receipt is not None and not issues and sample.get("strict_receipt_valid") is True,
                 f"Checkpoint raw usage receipt is invalid for {job_id}: {issues or receipt_source}")
        _require(sample.get("cost_receipt_status") == "reported",
                 f"Checkpoint receipt status is not reported: {job_id}")
        _require(sample.get("cost_receipt_source") == receipt_source
                 and sample.get("guard_charge_usd") == receipt,
                 f"Checkpoint settled charge differs from raw receipt: {job_id}")
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        local_tokens = sample.get("local_rendered_prompt_tokens")
        ratio = (prompt_tokens / local_tokens
                 if type(prompt_tokens) is int and type(local_tokens) is int and local_tokens > 0
                 else None)
        _require(ratio is not None and ratio <= 1.05,
                 f"Checkpoint prompt-token ratio is invalid for {job_id}")
        _require(sample.get("provider_local_input_token_ratio") == ratio,
                 f"Checkpoint provider/local token ratio differs from raw usage: {job_id}")
        settled += receipt
        by_id[job_id] = sample
    return by_id, settled


def continuation_budget(preflight: dict[str, Any], settled_usd: float,
                        remaining_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    budget = preflight.get("budget", {})
    aggregate = budget.get("aggregate_exposure", {})
    run_limit = float(budget.get("run_ceiling_usd", stage2.MAX_SPEND_USD))
    aggregate_limit = float(aggregate.get("limit_usd", stage2.AGGREGATE_LIMIT_USD))
    input_price = float(budget["input_price_usd_per_million"])
    output_price = float(budget["output_price_usd_per_million"])
    remaining_reserve = sum(stage2._job_reserve(job, input_price, output_price)
                            for job in remaining_jobs)
    prior_actual = float(aggregate["prior_actual_usd"])
    prior_unsettled = float(aggregate["prior_unsettled_usd"])
    total_run_exposure = settled_usd + remaining_reserve
    aggregate_exposure = prior_actual + prior_unsettled + total_run_exposure
    return {
        "settled_receipt_cost_usd": settled_usd,
        "remaining_request_count": len(remaining_jobs),
        "remaining_reserve_usd": remaining_reserve,
        "run_exposure_usd": total_run_exposure,
        "run_limit_usd": run_limit,
        "run_limit_passed": total_run_exposure <= run_limit,
        "prior_actual_usd": prior_actual,
        "prior_unsettled_usd": prior_unsettled,
        "aggregate_exposure_usd": aggregate_exposure,
        "aggregate_limit_usd": aggregate_limit,
        "aggregate_limit_passed": aggregate_exposure <= aggregate_limit,
        "input_price_usd_per_million": input_price,
        "output_price_usd_per_million": output_price,
        "reservation_basis": "settled raw receipt charges plus 1.5x local prompt-token reservations and output-token reservations for each missing request",
    }


def route_configuration_identity(route: dict[str, Any]) -> dict[str, Any]:
    """Fields that must remain unchanged between frozen and fresh route snapshots."""
    fields = (
        "endpoint_name", "provider_name", "model_id", "context_length",
        "max_prompt_tokens", "input_usd_per_million", "output_usd_per_million",
    )
    return {key: route.get(key) for key in fields}


def validate_fresh_route(fresh_route_path: Path, frozen_route: dict[str, Any],
                         frozen_route_path: Path, input_price: float,
                         output_price: float) -> dict[str, Any]:
    """Validate a fresh route snapshot without replacing frozen route evidence."""
    _require(fresh_route_path.resolve() != frozen_route_path.resolve(),
             "Fresh route metadata must be a separate file from frozen manifest evidence")
    document = _load_json(fresh_route_path)
    data = document.get("data", document)
    _require(isinstance(data, dict), "Fresh route metadata has no endpoint data")
    endpoint = data
    if isinstance(data.get("endpoints"), list):
        matches = [row for row in data["endpoints"] if isinstance(row, dict)
                   and row.get("model_id") == stage2.REQUESTED_MODEL
                   and str(row.get("provider_name", "")).casefold() == "minimax"]
        _require(len(matches) == 1, "Fresh route must contain exactly one pinned MiniMax endpoint")
        endpoint = matches[0]
    status = endpoint.get("status", document.get("status"))
    supported = endpoint.get("supported_parameters", document.get("supported_parameters"))
    _require(type(status) is int and status == 0, "Fresh MiniMax route status is not healthy")
    _require(isinstance(supported, list), "Fresh route is missing supported_parameters")
    required_parameters = {"max_tokens", "temperature", "top_p", "response_format", "reasoning"}
    _require(required_parameters.issubset(set(supported)),
             "Fresh MiniMax route lacks required generation parameters")
    try:
        fresh = v3.load_route_metadata(fresh_route_path, input_price, output_price)
    except Exception as error:
        raise ContinuationError(f"Fresh route validation failed: {error}") from error
    _require(route_configuration_identity(fresh) == route_configuration_identity(frozen_route),
             "Fresh provider/model/limits/pricing differ from the frozen preflight route")
    return {
        "metadata": fresh,
        "sha256": sha256(fresh_route_path),
        "checked_utc": fresh.get("checked_utc"),
        "validated_utc": fresh.get("validated_utc"),
        "status": status,
        "supported_parameters": sorted(supported),
    }


def validate_resume_inputs(checkpoint_path: Path, preflight_path: Path,
                           stage_path: Path, route_path: Path,
                           fresh_route_path: Path,
                           tokenizer_path: Path, template_path: Path) -> tuple[
                               dict[str, Any], dict[str, Any], list[dict[str, Any]],
                               list[dict[str, Any]], dict[str, dict[str, Any]], float,
                               dict[str, Any]
                           ]:
    checkpoint = _load_json(checkpoint_path)
    preflight = _load_json(preflight_path)
    stage = _load_json(stage_path)
    require_resumable_checkpoint(checkpoint)
    _require(preflight.get("status") == "prepared_only_no_dispatch"
             and preflight.get("dry_run") is True
             and preflight.get("actual_dispatch_started") is False
             and preflight.get("samples") == [],
             "Expected untouched no-dispatch preflight artifact")

    preflight_sha = sha256(preflight_path)
    _require(checkpoint.get("preflight_artifact_sha256") == preflight_sha,
             "Checkpoint does not reference this exact preflight artifact")
    stage_sha = sha256(stage_path)
    _require(checkpoint.get("stage_manifest_sha256") == stage_sha
             and preflight.get("stage_manifest_sha256") == stage_sha,
             "Stage manifest hash differs from checkpoint/preflight")
    _require(stage.get("route_metadata_sha256") == sha256(route_path),
             "Stage manifest route metadata hash differs")
    declared_route = Path(stage.get("route_metadata_path", ""))
    if not declared_route.is_absolute():
        declared_route = ROOT / declared_route
    _require(declared_route.resolve() == route_path.resolve(),
             "Route metadata path differs from frozen stage manifest")
    _require(stage.get("source_hashes", {}).get("runner_sha256")
             == checkpoint.get("source_hashes", {}).get("runner_sha256"),
             "Frozen Stage 2 runner source hash differs")
    _require(sha256(ROOT / stage["baseline_manifest_path"]) == checkpoint.get("baseline_manifest_sha256"),
             "Frozen baseline manifest hash differs")
    _require(sha256(ROOT / stage["baseline_result_path"]) == checkpoint.get("baseline_result_sha256"),
             "Frozen baseline result hash differs")
    _require(sha256(route_path) == checkpoint.get("source_hashes", {}).get("route_metadata_sha256")
             and sha256(route_path) == preflight.get("source_hashes", {}).get("route_metadata_sha256"),
             "Route metadata source hash differs from frozen preflight")
    protocol_path = _resolve_repo_path(stage["protocol_path"])
    current_sources = stage2.current_source_hashes(
        tokenizer_path=tokenizer_path,
        template_path=template_path,
        protocol_path=protocol_path,
        route_path=route_path,
    )
    for key, value in current_sources.items():
        _require(checkpoint.get("source_hashes", {}).get(key) == value
                 and preflight.get("source_hashes", {}).get(key) == value,
                 f"Current source/artifact differs from frozen run: {key}")
    _require(checkpoint.get("source_hashes") == preflight.get("source_hashes"),
             "Checkpoint source provenance differs from preflight")
    _require(checkpoint.get("baseline_manifest_sha256") == preflight.get("baseline_manifest_sha256")
             and checkpoint.get("baseline_result_sha256") == preflight.get("baseline_result_sha256"),
             "Checkpoint baseline identity differs from preflight")
    _require(checkpoint.get("protocol") == preflight.get("protocol"),
             "Checkpoint protocol differs from preflight")
    _require(stage2.stable_route_identity(checkpoint.get("route_metadata", {}))
             == stage2.stable_route_identity(preflight.get("route_metadata", {})),
             "Checkpoint route identity differs from preflight")

    requests = preflight.get("prepared_requests")
    jobs = preflight.get("prepared_jobs")
    samples = checkpoint.get("samples")
    _require(isinstance(requests, list) and len(requests) == stage2.EXPECTED_TASKS * stage2.REPEATS,
             "Preflight must contain 300 frozen requests")
    _require(isinstance(jobs, list) and len(jobs) == len(requests),
             "Preflight job metadata does not cover all request bodies")
    _require(checkpoint.get("prepared_requests") == requests,
             "Checkpoint prepared request bodies differ from the exact preflight")
    checkpoint_jobs = checkpoint.get("prepared_jobs")
    _require(isinstance(checkpoint_jobs, list) and len(checkpoint_jobs) == len(jobs),
             "Checkpoint prepared job metadata does not cover preflight")
    volatile_job_fields = {
        "default_sift_preprocessing_ms", "candidate_preprocessing_ms", "sift_preprocessing_ms",
    }
    for saved_job, frozen_job in zip(checkpoint_jobs, jobs, strict=True):
        stable_saved = {key: value for key, value in saved_job.items() if key not in volatile_job_fields}
        stable_frozen = {key: value for key, value in frozen_job.items() if key not in volatile_job_fields}
        _require(stable_saved == stable_frozen,
                 f"Checkpoint prepared job metadata differs from exact preflight: {frozen_job.get('job_id')}")
    _require(isinstance(samples, list) and 0 < len(samples) < len(requests),
             "Checkpoint sample count must be a nonempty incomplete prefix")
    request_by_id = {record.get("job_id"): record for record in requests}
    _require(len(request_by_id) == len(requests) and None not in request_by_id,
             "Preflight request IDs are not unique")
    dispatch_ids = preflight.get("protocol", {}).get("dispatch_job_ids")
    _require(isinstance(dispatch_ids, list) and len(dispatch_ids) == len(requests),
             "Preflight dispatch order is missing or incomplete")
    validate_dispatch_prefix(dispatch_ids, samples)
    sample_by_id, settled = validate_checkpoint_samples(requests, samples, jobs)
    _require(len(sample_by_id) == len(samples), "Checkpoint sample IDs are not unique")
    missing_jobs = [job for job in jobs if job.get("job_id") not in sample_by_id]
    _require(len(missing_jobs) + len(samples) == len(requests),
             "Checkpoint and pending jobs do not partition the frozen request set")
    for job in missing_jobs:
        record = request_by_id.get(job.get("job_id"))
        _require(record is not None and job.get("request_payload_sha256") == record.get("request_sha256"),
                 f"Pending job differs from frozen preflight: {job.get('job_id')}")
    fresh_route = validate_fresh_route(
        fresh_route_path, preflight["route_metadata"], route_path,
        float(checkpoint["budget"]["input_price_usd_per_million"]),
        float(checkpoint["budget"]["output_price_usd_per_million"]),
    )
    budget = continuation_budget(preflight, settled, missing_jobs)
    _require(budget["run_limit_passed"], "Settled plus missing-job reserve exceeds the $4 run ceiling")
    _require(budget["aggregate_limit_passed"], "Settled plus missing-job reserve exceeds the $20 aggregate cap")
    return checkpoint, preflight, requests, jobs, sample_by_id, settled, {
        "missing_jobs": missing_jobs,
        "budget": budget,
        "preflight_sha256": preflight_sha,
        "stage_manifest_sha256": stage_sha,
        "frozen_route_metadata_sha256": sha256(route_path),
        "fresh_route_metadata": fresh_route,
    }


def _atomic_checkpoint(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        last_error: OSError | None = None
        for attempt in range(5):
            try:
                os.replace(temp, path)
                return
            except PermissionError as error:
                last_error = error
                if attempt < 4:
                    time.sleep(0.2 * (attempt + 1))
        raise ContinuationError(
            f"Checkpoint replacement failed; complete recovery JSON remains at {temp}: {last_error}"
        )
    except Exception:
        # Preserve a complete temp file after replacement errors for manual recovery.
        if temp.exists() and temp.stat().st_size == len(encoded):
            raise
        temp.unlink(missing_ok=True)
        raise


def continue_run(checkpoint_path: Path, preflight_path: Path, stage_path: Path,
                 route_path: Path, fresh_route_path: Path,
                 tokenizer_path: Path, template_path: Path,
                 output_path: Path) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite continuation output: {output_path}")
    if output_path.resolve() in {checkpoint_path.resolve(), preflight_path.resolve()}:
        raise ContinuationError("Continuation output must be distinct from checkpoint and preflight")
    checkpoint, preflight, requests, jobs, completed_by_id, settled, verified = validate_resume_inputs(
        checkpoint_path, preflight_path, stage_path, route_path, fresh_route_path,
        tokenizer_path, template_path,
    )
    request_by_id = {record["job_id"]: record for record in requests}
    pending = deque(verified["missing_jobs"])
    samples = list(checkpoint["samples"])
    report = dict(checkpoint)
    report["samples"] = samples
    report["status"] = "in_progress"
    report["in_flight_request"] = None
    report["not_started_jobs"] = []
    report["continuation_provenance"] = {
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_sha256": sha256(checkpoint_path),
        "checkpoint_samples_reused": len(samples),
        "preflight_path": str(preflight_path),
        "preflight_sha256": verified["preflight_sha256"],
        "original_runner_sha256": checkpoint["source_hashes"]["runner_sha256"],
        "continuation_runner_path": str(Path(__file__).resolve()),
        "continuation_runner_sha256": sha256(Path(__file__)),
        "dispatch_policy": "only request objects read from the verified frozen preflight; no retries; ambiguous in-flight checkpoints are refused",
        "initial_budget_recalculation": verified["budget"],
        "frozen_route_metadata_sha256": verified["frozen_route_metadata_sha256"],
        "fresh_route_metadata": verified["fresh_route_metadata"],
    }
    report["continuation_runner_sha256"] = sha256(Path(__file__))
    report["budget"]["continuation"] = verified["budget"]
    report["budget"]["actual_upstream_reported_cost_usd"] = sum(
        v3._reported_cost(sample.get("usage"), upstream=True) for sample in samples
    )
    report["budget"]["budget_guard_spend_usd"] = settled
    _atomic_checkpoint(output_path, report)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ContinuationError("OPENROUTER_API_KEY is required to continue the dispatched experiment")
    stop_reasons: list[str] = []
    guard_spend = settled
    input_price = float(report["budget"]["input_price_usd_per_million"])
    output_price = float(report["budget"]["output_price_usd_per_million"])
    prior_actual = float(report["budget"]["aggregate_exposure"]["prior_actual_usd"])
    prior_unsettled = float(report["budget"]["aggregate_exposure"]["prior_unsettled_usd"])
    while pending:
        job = pending[0]
        reserve = stage2._job_reserve(job, input_price, output_price)
        if (guard_spend + reserve > stage2.MAX_SPEND_USD
                or prior_actual + prior_unsettled + guard_spend + reserve > stage2.AGGREGATE_LIMIT_USD):
            stop_reasons.append("budget_guard_would_be_exceeded")
            break
        pending.popleft()
        record = request_by_id[job["job_id"]]
        request = record["request"]
        _require(v3._request_hash(request) == record["request_sha256"],
                 f"Frozen preflight request changed before dispatch: {job['job_id']}")
        report["in_flight_request"] = {
            "job_id": job["job_id"],
            "request": request,
            "request_sha256": record["request_sha256"],
            "guard_reservation_usd": reserve,
            "continuation_dispatch_started_utc": datetime.now(timezone.utc).isoformat(),
        }
        _atomic_checkpoint(output_path, report)
        result = v3._call_openrouter(request, api_key=api_key)
        usage = result.get("usage")
        receipt, receipt_source = baseline.cost_receipt(usage)
        receipt_issues = v3.runtime_receipt_issues(usage)
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        local_tokens = job.get("local_rendered_prompt_tokens")
        ratio = prompt_tokens / local_tokens if type(prompt_tokens) is int and type(local_tokens) is int and local_tokens > 0 else None
        valid_answer = (result.get("normal") is True
                        and result.get("finish_reason") == "stop"
                        and result.get("choice") in {"A", "B", "C", "D"})
        if result.get("http_status") != 200 or result.get("model") != stage2.REQUESTED_MODEL:
            stop_reasons.append("route_attribution_mismatch")
        if not isinstance(result.get("provider"), str) or result["provider"].casefold() != "minimax":
            stop_reasons.append("provider_attribution_mismatch")
        if receipt is None or receipt_issues:
            stop_reasons.append("invalid_usage_or_cost_receipt")
        if type(prompt_tokens) is not int or prompt_tokens <= 0 or ratio is None or ratio > 1.05:
            stop_reasons.append("provider_prompt_usage_or_ratio_invalid")
        if type(completion_tokens) is not int or completion_tokens < 0 or result.get("failure") is not None:
            stop_reasons.append("transport_or_completion_usage_failure")
        charge = receipt if receipt is not None else reserve
        guard_spend += charge
        if guard_spend > stage2.MAX_SPEND_USD or prior_actual + prior_unsettled + guard_spend > stage2.AGGREGATE_LIMIT_USD:
            stop_reasons.append("settled_budget_ceiling_exceeded")
        sample = {
            **result,
            **{key: value for key, value in job.items() if key not in {"messages", "request_payload"}},
            "request": request,
            "request_sha256": record["request_sha256"],
            "correct": valid_answer and result.get("choice") == job["expected"],
            "answer_validity": "valid" if valid_answer else "invalid_or_incomplete",
            "strict_sample_valid": not stop_reasons and valid_answer,
            "strict_receipt_valid": receipt is not None and not receipt_issues,
            "cost_receipt_status": "reported" if receipt is not None and not receipt_issues else "missing_or_invalid",
            "cost_receipt_source": receipt_source,
            "receipt": usage,
            "provider_local_input_token_ratio": ratio,
            "guard_reserved_cost_usd": reserve,
            "guard_charge_usd": charge,
            "continuation_runner_sha256": report["continuation_runner_sha256"],
        }
        report["in_flight_request"] = None
        report["samples"].append(sample)
        report["budget"].update({
            "actual_upstream_reported_cost_usd": sum(
                v3._reported_cost(row.get("usage"), upstream=True) for row in report["samples"]
            ),
            "budget_guard_spend_usd": guard_spend,
            "unknown_cost_receipts": sum(row.get("cost_receipt_status") != "reported" for row in report["samples"]),
            "stop_reasons": sorted(set(stop_reasons)),
        })
        _atomic_checkpoint(output_path, report)
        if stop_reasons:
            break
    if pending:
        report["not_started_jobs"] = [
            {"job_id": row["job_id"], "case_id": row["case_id"], "repeat": row["repeat"],
             "reason": ";".join(sorted(set(stop_reasons))) or "budget_guard_would_be_exceeded"}
            for row in pending
        ]
    report["status"] = "safety_guard_stopped" if stop_reasons else ("budget_guard_stopped" if pending else "complete")
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_checkpoint(output_path, report)
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--stage-manifest", type=Path, required=True)
    parser.add_argument("--route-metadata", type=Path, required=True)
    parser.add_argument("--fresh-route-metadata", type=Path, required=True,
                        help="New endpoint snapshot used for freshness checks; frozen route file remains unchanged")
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "tmp/minimax-m3-tokenizer.json")
    parser.add_argument("--template", type=Path, default=ROOT / "tmp/minimax-m3-chat-template.jinja")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = continue_run(args.checkpoint, args.preflight, args.stage_manifest,
                          args.route_metadata, args.fresh_route_metadata,
                          args.tokenizer, args.template, args.output)
    print(json.dumps({
        "status": result["status"],
        "samples": len(result["samples"]),
        "not_started_jobs": len(result.get("not_started_jobs", [])),
        "budget": result["budget"].get("continuation"),
        "output": str(args.output),
    }, indent=2))
