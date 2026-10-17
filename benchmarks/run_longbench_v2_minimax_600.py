"""Deterministic offline bundle and explicit first-N MiniMax study dispatcher.

The default command only reconstructs and writes the frozen Stage 1 600-job
schedule. It does not read credentials or contact a provider. Dispatch is a
separate, explicit first-N operation and never resumes or retries requests.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
import gzip
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks import run_longbench_v2_minimax_stage1_100 as stage

ROOT = stage.ROOT
BUNDLE_DEFAULT = ROOT / ".runs/longbench-v2-minimax-600-bundle.json.gz"
OUTPUT_DEFAULT = ROOT / ".runs/longbench-v2-minimax-600-run.json"
SCHEMA_VERSION = 1
EXPECTED_TASKS = 100
EXPECTED_JOBS = 600
DEFAULT_PREFIX = EXPECTED_JOBS
MAX_DISPATCH_PREFIX = EXPECTED_JOBS
CURRENT_MANIFEST = ROOT / "docs/evals/longbench-v2-minimax-stage1-100-current-2026-10-19.json"
CURRENT_MANIFEST_SHA256 = "488d67a7072495878055e65c13a50048d85621f4346fd0844b17acf9377c3d64"
LIVE_PARENT_MANIFEST = stage.MANIFEST_344_LIVE_ROUTE
LIVE_PARENT_SHA256 = stage.MANIFEST_SHA256_344_LIVE_ROUTE
HISTORICAL_SAMPLE_MANIFEST = stage.MANIFEST
HISTORICAL_SAMPLE_SHA256 = stage.MANIFEST_SHA256_STAGE1


class PilotError(RuntimeError):
    pass


def deterministic_gzip_json(value: dict[str, Any]) -> bytes:
    """Return canonical UTF-8 JSON in a gzip stream with stable metadata."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    target = BytesIO()
    with gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0,
                       compresslevel=9) as stream:
        stream.write(raw)
    return target.getvalue()


def load_continuation_bundle(path: Path, rebuilt: dict[str, Any]) -> dict[str, Any]:
    """Load the original frozen bundle and permit runner-provenance changes only.

    Continuation requires byte-canonical original bundle integrity plus exact
    schedule and request hashes against current reconstruction. The current
    runner's own file hash necessarily differs after adding continuation code.
    """
    try:
        encoded = path.read_bytes()
        frozen = json.loads(gzip.decompress(encoded))
    except (OSError, gzip.BadGzipFile, EOFError, json.JSONDecodeError) as error:
        raise PilotError(f"Cannot load frozen continuation bundle: {error}") from error
    unhashed = dict(frozen)
    stored_content_hash = unhashed.pop("bundle_content_sha256", None)
    if (encoded != deterministic_gzip_json(frozen)
            or stored_content_hash != stage.canonical_hash(unhashed)
            or frozen.get("schedule_sha256") != stage.canonical_hash(frozen.get("schedule"))
            or frozen.get("requests_sha256") != stage.canonical_hash(frozen.get("requests"))):
        raise PilotError("Frozen continuation bundle failed canonical content/hash validation")
    if (frozen.get("schedule_sha256") != rebuilt.get("schedule_sha256")
            or frozen.get("requests_sha256") != rebuilt.get("requests_sha256")
            or frozen.get("scoring_keys") != rebuilt.get("scoring_keys")
            or frozen.get("full_schedule_jobs") != EXPECTED_JOBS):
        raise PilotError("Frozen bundle schedule/request hashes differ from current reconstruction")
    return frozen


def make_bundle(manifest: dict[str, Any], manifest_path: Path,
                jobs: list[dict[str, Any]], cases: dict[str, dict[str, Any]],
                source_manifest_sha256: str) -> dict[str, Any]:
    """Freeze every request body while keeping scoring keys in separate metadata."""
    ids = manifest.get("selection", {}).get("ids")
    if not isinstance(ids, list) or len(ids) != EXPECTED_TASKS or len(set(ids)) != EXPECTED_TASKS:
        raise PilotError("Bundle requires exactly the frozen 100-task Stage 1 sample")
    if len(jobs) != EXPECTED_JOBS or len(cases) != EXPECTED_TASKS:
        raise PilotError("Bundle requires exactly 600 jobs and 100 case records")
    schedule: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    keys: dict[str, str] = {}
    seen: set[tuple[str, str, int]] = set()
    for index, job in enumerate(jobs):
        case_id, arm, repeat = job.get("case_id"), job.get("arm"), job.get("repeat")
        identity = (case_id, arm, repeat)
        if (case_id not in cases or arm not in {"full", "sift"}
                or type(repeat) is not int or repeat not in range(3) or identity in seen):
            raise PilotError("Schedule contains an invalid or duplicate job identity")
        seen.add(identity)
        body = job.get("body")
        if not isinstance(body, dict) or body.get("messages") != cases[case_id]["messages"][arm]:
            raise PilotError("Request body does not resolve to frozen case messages")
        body_hash = stage.canonical_hash(body)
        if job.get("body_sha256") != body_hash:
            raise PilotError("Request body hash mismatch")
        job_id = f"{case_id}:{arm}:{repeat}"
        schedule.append({
            "index": index, "job_id": job_id, "case_id": case_id,
            "arm": arm, "repeat": repeat, "seed": job["seed"],
            "prompt_sha256": job["prompt_sha256"], "body_sha256": body_hash,
            "local_prompt_tokens": job["local_prompt_tokens"],
            "projected_provider_prompt_tokens": job["projected_provider_prompt_tokens"],
        })
        requests.append({"index": index, "job_id": job_id,
                         "body_sha256": body_hash, "body": body})
    if len(seen) != EXPECTED_JOBS:
        raise PilotError("Schedule is not a complete 100 × 2 × 3 design")
    for case_id in ids:
        key = cases.get(case_id, {}).get("answer")
        if key not in {"A", "B", "C", "D"}:
            raise PilotError("Every selected case requires a valid separate scoring key")
        keys[case_id] = key
    schedule_hash = stage.canonical_hash(schedule)
    requests_hash = stage.canonical_hash(requests)
    content: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "prepared_only_no_dispatch",
        "dispatch_authorized": False,
        "evidence_class": manifest.get("evidence_class", "exposed_development_sample_not_blind_holdout"),
        "cohort": "stage1_100",
        "provenance": {
            "manifest_path": manifest_path.resolve().relative_to(ROOT).as_posix(),
            "manifest_sha256": source_manifest_sha256,
            "execution_runner_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "execution_runner_sha256": stage.file_sha256(Path(__file__).resolve()),
            "source_hashes": manifest.get("source_hashes", {}),
            "dataset": manifest.get("dataset", {}),
            "protocol": manifest.get("protocol", {}),
        },
        "schedule": schedule,
        "schedule_sha256": schedule_hash,
        "requests": requests,
        "requests_sha256": requests_hash,
        "scoring_keys": keys,
        "full_schedule_jobs": EXPECTED_JOBS,
        "request_bodies_include_scoring_keys": False,
    }
    content["bundle_content_sha256"] = stage.canonical_hash(content)
    return content


def validate_prefix_and_cap(prefix: int, cap: float, jobs: list[dict[str, Any]],
                            input_price: float = stage.INPUT_PRICE,
                            output_price: float = stage.OUTPUT_PRICE) -> list[dict[str, Any]]:
    if type(prefix) is not int or not 1 <= prefix <= MAX_DISPATCH_PREFIX:
        raise PilotError("Dispatch scope must be a first-N prefix from 1 through 600")
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(float(cap)) or cap <= 0:
        raise PilotError("Spend cap must be a finite positive dollar amount")
    selected = jobs[:prefix]
    if len(selected) != prefix:
        raise PilotError("Prepared schedule is shorter than requested prefix")
    reservation = sum((job["local_prompt_tokens"] * stage.INPUT_FACTOR * input_price
                      + stage.OUTPUT_CAP * output_price) / 1_000_000 for job in selected)
    if float(cap) < reservation:
        raise PilotError(f"Spend cap is below first-{prefix} request reserve ${reservation:.6f}")
    return selected


def account_receipt(report: dict[str, Any], receipt: float | None,
                    receipt_source: str, reserve: float, cap: float,
                    index: int, job_id: str) -> str | None:
    """Record settled positive provider cost even when the request is terminally bad."""
    if receipt is None:
        report["in_flight"] = {
            "index": index, "job_id": job_id,
            "state": "unknown_outcome_requires_external_reconciliation",
            "cost_receipt_source": receipt_source,
        }
        return "positive_byok_upstream_receipt_required"
    settled = float(report.get("settled_cost_usd", 0.0)) + receipt
    report["settled_cost_usd"] = settled
    report["in_flight"] = None
    if receipt > reserve:
        return "request_receipt_exceeds_reservation"
    if settled > cap:
        return "settled_cost_exceeds_client_cap"
    return None


def score_sample(response_text: str, expected: str, valid_route: bool,
                 sse_done: bool, failure: str | None,
                 finish_reason: str | None) -> dict[str, Any]:
    """Apply the frozen strict A–D scoring rule to a provider response."""
    trimmed = response_text.strip()
    choice = trimmed if trimmed in {"A", "B", "C", "D"} else None
    scoreable = (choice is not None and valid_route and sse_done
                 and failure is None and finish_reason in {"stop", "length"})
    return {"choice": choice, "expected_answer": expected,
            "scoreable": scoreable,
            "correct": (choice == expected) if scoreable else None}


def score_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize only valid, strictly scorable responses, grouped by arm."""
    result: dict[str, Any] = {}
    for arm in ("full", "sift"):
        rows = [sample for sample in samples if sample.get("arm") == arm]
        correct = sum(sample.get("correct") is True for sample in rows)
        scorable = sum(sample.get("scoreable") is True for sample in rows)
        task_votes: dict[str, list[bool]] = {}
        for sample in rows:
            if sample.get("scoreable") is True:
                task_votes.setdefault(sample["case_id"], []).append(sample["correct"] is True)
        task_mean_accuracy = (
            sum(sum(votes) / len(votes) for votes in task_votes.values()) / len(task_votes)
            if task_votes else None
        )
        result[arm] = {
            "scheduled_or_attempted": len(rows),
            "scorable": scorable,
            "correct": correct,
            "response_accuracy": correct / scorable if scorable else None,
            "tasks_with_scorable_responses": len(task_votes),
            "equal_task_weighted_accuracy": task_mean_accuracy,
        }
    return result


def reported_token_totals(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum only provider-reported usage; leave absent usage as explicitly unknown."""
    prompt = completion = 0
    rows = 0
    unknown = 0
    for sample in samples:
        usage = sample.get("usage")
        if not isinstance(usage, dict):
            unknown += 1
            continue
        p = usage.get("prompt_tokens")
        c = usage.get("completion_tokens")
        if type(p) is int and type(c) is int and p >= 0 and c >= 0:
            prompt += p
            completion += c
            rows += 1
        else:
            unknown += 1
    return {"source": "provider_usage_receipts_only",
            "attempts_with_reported_usage": rows,
            "attempts_with_unknown_tokens": unknown,
            "prompt_tokens": prompt, "completion_tokens": completion,
            "total_reported_tokens": prompt + completion}


def verify_current_manifest(manifest: dict[str, Any], manifest_path: Path,
                            dataset: Path, tokenizer: Path,
                            template: Path) -> None:
    """Verify the new Stage 1 sample against its current, frozen 344 parent."""
    if manifest_path.resolve() != CURRENT_MANIFEST.resolve():
        raise PilotError("Only the newly pinned current Stage 1 manifest is accepted")
    if stage.file_sha256(manifest_path) != CURRENT_MANIFEST_SHA256:
        raise PilotError("Current Stage 1 manifest hash mismatch")
    parent = json.loads(LIVE_PARENT_MANIFEST.read_text(encoding="utf-8"))
    stage.verify_provenance(parent, LIVE_PARENT_MANIFEST, dataset, tokenizer, template)
    if stage.file_sha256(LIVE_PARENT_MANIFEST) != LIVE_PARENT_SHA256:
        raise PilotError("Live-route parent manifest hash mismatch")
    historical = json.loads(HISTORICAL_SAMPLE_MANIFEST.read_text(encoding="utf-8"))
    if stage.file_sha256(HISTORICAL_SAMPLE_MANIFEST) != HISTORICAL_SAMPLE_SHA256:
        raise PilotError("Historical sample selector hash mismatch")
    ids = manifest.get("selection", {}).get("ids")
    historical_ids = historical.get("selection", {}).get("ids")
    if (not isinstance(ids, list) or len(ids) != EXPECTED_TASKS
            or len(set(ids)) != EXPECTED_TASKS or ids != historical_ids):
        raise PilotError("Current sample IDs/order differ from the pinned historical selector")
    if (manifest.get("status") != "prepared_only_no_dispatch"
            or manifest.get("dispatch_authorized") is not False
            or manifest.get("evidence_class") != "exposed_development_sample_not_blind_holdout"):
        raise PilotError("Current Stage 1 manifest has an invalid status or evidence class")
    if (manifest.get("parent_manifest") != LIVE_PARENT_MANIFEST.relative_to(ROOT).as_posix()
            or manifest.get("parent_manifest_sha256") != LIVE_PARENT_SHA256):
        raise PilotError("Current Stage 1 manifest does not bind the reviewed live-route parent")
    if manifest.get("source_hashes") != parent.get("source_hashes"):
        raise PilotError("Current Stage 1 source hashes differ from the live-route parent")
    if manifest.get("route_assumptions") != parent.get("route_assumptions"):
        raise PilotError("Current Stage 1 route assumptions differ from the live-route parent")
    if manifest.get("dataset") != parent.get("dataset"):
        raise PilotError("Current Stage 1 dataset provenance differs from the live-route parent")
    if manifest.get("sift") != parent.get("sift"):
        raise PilotError("Current Stage 1 Sift configuration differs from the live-route parent")
    expected_protocol = dict(parent.get("protocol", {}))
    expected_protocol["planned_requests"] = EXPECTED_JOBS
    if manifest.get("protocol") != expected_protocol:
        raise PilotError("Current Stage 1 protocol differs from the live-route parent")
    parent_cases = {case.get("id"): case for case in parent.get("cases", [])}
    historical_cases = {case.get("id"): case for case in historical.get("cases", [])}
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_TASKS:
        raise PilotError("Current Stage 1 manifest must contain exactly 100 cases")
    if set(historical_cases) != set(ids):
        raise PilotError("Historical selector case metadata does not match its ID list")
    compare_fields = (
        "id", "answer_key", "domain", "sub_domain", "difficulty", "length",
        "source_prompt_sha256", "full_prompt_sha256", "sift_prompt_sha256",
        "full_local_prompt_tokens", "sift_local_prompt_tokens", "eligibility_rationale",
    )
    by_id = {case.get("id"): case for case in cases}
    if len(by_id) != EXPECTED_TASKS or list(by_id) != ids:
        raise PilotError("Current case metadata order/IDs differ from the sample selector")
    for case_id in ids:
        if case_id not in parent_cases:
            raise PilotError(f"Selected case is absent from live-route parent: {case_id}")
        for field in compare_fields:
            value = by_id[case_id].get(field)
            if value != parent_cases[case_id].get(field):
                raise PilotError(f"Current case metadata differs from parent for {case_id}: {field}")
            if value != historical_cases[case_id].get(field):
                raise PilotError(f"Current case metadata differs from historical sample for {case_id}: {field}")


def reconstruct(bundle_manifest: Path, dataset: Path, tokenizer: Path,
                 template: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    manifest = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    verify_current_manifest(manifest, bundle_manifest, dataset, tokenizer, template)
    jobs, cases = stage.build_jobs(manifest, "stage1_100", dataset, tokenizer)
    bundle = make_bundle(manifest, bundle_manifest, jobs, cases,
                         stage.sha256_bytes(bundle_manifest.read_bytes()))
    return manifest, jobs, cases, bundle


def _write_bundle(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise PilotError(f"Refusing to overwrite existing bundle: {path}")
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_bytes(data)
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def prepare(args: argparse.Namespace) -> int:
    # This path deliberately never accesses os.environ or creates a provider client.
    manifest, jobs, cases, bundle = reconstruct(args.manifest, args.dataset,
                                                args.tokenizer, args.template)
    compressed = deterministic_gzip_json(bundle)
    _write_bundle(args.bundle, compressed)
    print(json.dumps({"status": "prepared_only_no_dispatch", "tasks": len(cases),
                      "jobs": len(jobs), "bundle": str(args.bundle),
                      "schedule_sha256": bundle["schedule_sha256"],
                      "bundle_sha256": stage.sha256_bytes(compressed)}, sort_keys=True))
    return 0


def _dispatch_prefix(manifest: dict[str, Any], jobs: list[dict[str, Any]],
                     bundle: dict[str, Any], output: Path, cap: float,
                     prefix: int, api_key: str, no_unsettled: bool,
                     provider_billing: bool,
                     previous_report: dict[str, Any] | None = None,
                     provider_billing_authorized_unverified: bool = False,
                     prior_unknown_outcome_explicitly_accepted: bool = False) -> dict[str, Any]:
    selected = validate_prefix_and_cap(prefix, cap, jobs)
    if output.exists():
        raise PilotError("Refusing output reuse; choose a new continuation output path")
    live = stage.live_account_route_preflight(api_key, manifest, cap, selected,
                                              no_unsettled, provider_billing,
                                              provider_billing_authorized_unverified,
                                              prior_unknown_outcome_explicitly_accepted)
    if (live["input_usd_per_million"] != stage.INPUT_PRICE
            or live["output_usd_per_million"] != stage.OUTPUT_PRICE):
        raise PilotError("Live price differs from frozen reserve assumptions")
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "dispatching",
        "evidence_class": bundle["evidence_class"],
        "actual_dispatch_started": True,
        "full_schedule_complete": False,
        "full_schedule_jobs": EXPECTED_JOBS,
        "dispatch_prefix_count": prefix,
        "attempted_jobs": 0,
        "completed_jobs": 0,
        "bundle_content_sha256": bundle["bundle_content_sha256"],
        "schedule_sha256": bundle["schedule_sha256"],
        "spend_cap_usd": cap,
        "live_route_preflight": live,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "samples": [], "in_flight": None,
    }
    first_index = 0
    successful_job_ids: set[str] = set()
    if previous_report is not None:
        first_index = int(previous_report["samples"][-1]["index"])
        report.update({key: value for key, value in previous_report.items()
                       if key not in {"finished_utc", "dispatch_wall_seconds", "score_summary"}})
        report.update(status="dispatching", full_schedule_complete=False,
                      spend_cap_usd=cap, continuation_started_utc=datetime.now(timezone.utc).isoformat(),
                      prior_report_status=previous_report.get("status"),
                      prior_unknown_outcome_preserved=True,
                      live_route_preflight=live, in_flight=None)
        report["samples"] = [dict(sample) for sample in previous_report["samples"]]
        for sample in report["samples"]:
            sample.setdefault("attempt_number", 1)
            if (sample.get("http_status") == 200 and sample.get("failure") is None
                    and sample.get("sse_done_received") is True
                    and sample.get("response_id") and sample.get("usage") is not None
                    and sample.get("provider", "").strip().casefold() == "minimax"
                    and sample.get("returned_model") == stage.MODEL):
                successful_job_ids.add(sample["job_id"])
        report["completed_jobs"] = len(successful_job_ids)
        report["attempted_jobs"] = len(report["samples"])
        report["reconciliation_history"] = list(report.get("reconciliation_history", []))
        report["reconciliation_history"].append({
            "unknown_attempt": {key: previous_report["samples"][-1].get(key)
                                for key in ("index", "job_id", "failure", "http_status",
                                            "response_id", "usage", "cost_usd")},
            "retry_authorized_by": "explicit --continue-from-report --retry-unknown-once",
            "retry_started_utc": datetime.now(timezone.utc).isoformat(),
        })
    stage.atomic_write(output, report)
    started_all = time.perf_counter()
    for index in range(first_index, prefix):
        job = jobs[index]
        reserve = (job["local_prompt_tokens"] * stage.INPUT_FACTOR * live["input_usd_per_million"]
                   + stage.OUTPUT_CAP * live["output_usd_per_million"]) / 1_000_000
        settled_so_far = float(report.get("settled_cost_usd", 0.0))
        if settled_so_far + reserve > cap:
            report.update(status="budget_guard_stopped_before_request",
                          stop_reason="next_request_reservation_exceeds_cap")
            break
        job_id = f'{job["case_id"]}:{job["arm"]}:{job["repeat"]}'
        is_explicit_retry = previous_report is not None and index == first_index
        report["in_flight"] = {"index": index, "job_id": job_id,
                               "attempt_number": 2 if is_explicit_retry else 1,
                               "retry_of_attempt": 1 if is_explicit_retry else None,
                               "reserved_cost_usd": reserve, "state": "request_started"}
        stage.atomic_write(output, report)
        started = time.perf_counter()
        first_content_at = None
        fragments: list[str] = []
        usage = None
        raw_events: list[str] = []
        response_id = returned_model = provider = finish_reason = None
        status = failure = None
        sse_done = False
        try:
            with stage.requests.post(stage.API_URL, json=job["body"],
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    stream=True, timeout=(30, 600)) as response:
                status = response.status_code
                if status != 200:
                    raw_events.append(response.text)
                    failure = "http_status_not_200"
                else:
                    for line in response.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if line == "data: [DONE]":
                            sse_done = True
                            break
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        raw_events.append(raw)
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            failure = "invalid_sse_json"
                            break
                        if not isinstance(event, dict):
                            failure = "invalid_sse_event"
                            break
                        response_id = response_id or event.get("id")
                        returned_model = returned_model or event.get("model")
                        provider = provider or event.get("provider")
                        if isinstance(event.get("usage"), dict):
                            usage = event["usage"]
                        choices = event.get("choices")
                        if isinstance(choices, list) and choices:
                            choice = choices[0]
                            finish_reason = choice.get("finish_reason") or finish_reason
                            delta = choice.get("delta", {})
                            content = delta.get("content") if isinstance(delta, dict) else None
                            if isinstance(content, str):
                                if first_content_at is None:
                                    first_content_at = time.perf_counter()
                                fragments.append(content)
        except Exception as error:
            failure = f"request_exception:{type(error).__name__}"
        elapsed = time.perf_counter() - started
        receipt, receipt_source = stage.cost_receipt(usage)
        ratio = None
        if isinstance(usage, dict) and type(usage.get("prompt_tokens")) is int and usage["prompt_tokens"] > 0:
            ratio = usage["prompt_tokens"] / job["local_prompt_tokens"]
        response_text = "".join(fragments)
        valid_route = (returned_model == stage.MODEL and isinstance(provider, str)
                       and provider.strip().casefold() == "minimax")
        scored = score_sample(response_text, bundle["scoring_keys"][job["case_id"]],
                              valid_route, sse_done, failure, finish_reason)
        sample = {
            "index": index, "job_id": report["in_flight"]["job_id"],
            "attempt_number": report["in_flight"]["attempt_number"],
            "retry_of_attempt": report["in_flight"]["retry_of_attempt"],
            "case_id": job["case_id"], "arm": job["arm"], "repeat": job["repeat"],
            "request_body_sha256": job["body_sha256"], "http_status": status,
            "response_id": response_id, "returned_model": returned_model,
            "provider": provider, "finish_reason": finish_reason,
            "response_text": response_text, "raw_events": raw_events,
            "usage": usage, "cost_usd": receipt, "cost_receipt_source": receipt_source,
            "reserved_cost_usd": reserve, "sse_done_received": sse_done,
            "provider_local_input_ratio": ratio,
            "request_wall_seconds": elapsed,
            "ttft_seconds": first_content_at - started if first_content_at else None,
            "sift_preprocessing_ms": job.get("sift_preprocessing_ms"),
            "failure": failure,
            **scored,
        }
        report["samples"].append(sample)
        report["attempted_jobs"] = len(report["samples"])
        # A stream or route failure does not erase a valid upstream charge.
        # Reconcile the receipt before choosing the terminal stop reason.
        receipt_guard = account_receipt(report, receipt, receipt_source, reserve,
                                        cap, index, sample["job_id"])
        stop = receipt_guard
        if failure or status != 200:
            stop = stop or "request_failed_no_retry"
        elif not sse_done:
            stop = stop or "stream_missing_done_no_retry"
        elif not valid_route:
            stop = stop or "route_or_model_mismatch"
        elif receipt is None:
            stop = stop or "positive_byok_upstream_receipt_required"
        elif ratio is None:
            stop = stop or "prompt_usage_missing_or_invalid"
        elif ratio > stage.MAX_RATIO:
            stop = stop or "prompt_usage_exceeds_projection_guard"
        else:
            if finish_reason not in {"stop", "length"}:
                stop = stop or "request_failed_or_incomplete"
        if stop:
            report.update(status="stopped_incomplete_run", stop_reason=stop)
            stage.atomic_write(output, report)
            break
        sample["job_completed"] = True
        successful_job_ids.add(sample["job_id"])
        report["completed_jobs"] = len(successful_job_ids)
        stage.atomic_write(output, report)
    else:
        report["status"] = "complete" if report["completed_jobs"] == EXPECTED_JOBS else "completed_prefix_incomplete_schedule"
        report["full_schedule_complete"] = report["completed_jobs"] == EXPECTED_JOBS
    report.setdefault("settled_cost_usd", 0.0)
    report["score_summary"] = score_summary(report["samples"])
    report["provider_token_totals"] = reported_token_totals(report["samples"])
    report["dispatch_wall_seconds"] = time.perf_counter() - started_all
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    stage.atomic_write(output, report)
    return report


def dispatch(args: argparse.Namespace) -> int:
    if args.spend_cap_usd is None:
        raise PilotError("Explicit --dispatch requires --spend-cap-usd")
    if args.bundle.exists() is False:
        raise PilotError("Prepare the offline bundle first")
    manifest, jobs, cases, rebuilt = reconstruct(args.manifest, args.dataset,
                                                  args.tokenizer, args.template)
    expected_bytes = deterministic_gzip_json(rebuilt)
    if args.bundle.read_bytes() != expected_bytes:
        raise PilotError("Prepared bundle bytes differ from deterministic reconstruction")
    # Validate cap and prefix before credential access or any network request.
    validate_prefix_and_cap(args.prefix, args.spend_cap_usd, jobs)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise PilotError("OPENROUTER_API_KEY is required only for explicit dispatch")
    result = _dispatch_prefix(manifest, jobs, rebuilt, args.output,
                              args.spend_cap_usd, args.prefix, api_key,
                              args.confirm_no_unsettled_requests,
                              args.confirm_minimax_billing_headroom,
                              provider_billing_authorized_unverified=(
                                  args.user_authorized_spend_cap_with_unverified_provider_balance))
    print(json.dumps({key: result.get(key) for key in
                      ("status", "dispatch_prefix_count", "full_schedule_jobs",
                       "attempted_jobs", "completed_jobs", "full_schedule_complete", "settled_cost_usd",
                       "score_summary", "stop_reason", "schedule_sha256")}, sort_keys=True))
    return 0


def validate_continuation(previous: dict[str, Any], bundle: dict[str, Any], jobs: list[dict[str, Any]]) -> None:
    samples = previous.get("samples")
    if (previous.get("status") != "stopped_incomplete_run"
            or previous.get("schedule_sha256") != bundle["schedule_sha256"]
            or previous.get("bundle_content_sha256") != bundle["bundle_content_sha256"]
            or previous.get("full_schedule_jobs") != EXPECTED_JOBS
            or previous.get("dispatch_prefix_count") != EXPECTED_JOBS
            or not isinstance(samples, list) or len(samples) not in {90, 200, 226}):
        raise PilotError("Continuation source is not a recognized stopped full-schedule report")
    if len(samples) == 90:
        expected_indices = list(range(90))
        prior_unknowns: dict[int, str] = {}
        expected_retries: set[int] = set()
        target_index = 89
        expected_failure = "request_exception:SSLError"
    elif len(samples) == 200:
        expected_indices = [*range(90), 89, *range(90, 199)]
        prior_unknowns = {89: "request_exception:SSLError"}
        expected_retries = {89}
        target_index = 198
        expected_failure = "request_exception:ConnectionError"
    else:
        expected_indices = [*range(90), 89, *range(90, 199), 198, *range(199, 224)]
        prior_unknowns = {89: "request_exception:SSLError",
                          198: "request_exception:ConnectionError"}
        expected_retries = {89, 198}
        target_index = 223
        expected_failure = "request_exception:SSLError"
    if [sample.get("index") for sample in samples] != expected_indices:
        raise PilotError("Continuation source attempts do not match the approved sequential prefix/retry history")
    failed = samples[-1]
    unknown = previous.get("in_flight")
    expected_id = f'{jobs[target_index]["case_id"]}:{jobs[target_index]["arm"]}:{jobs[target_index]["repeat"]}'
    if (failed.get("index") != target_index or failed.get("job_id") != expected_id
            or failed.get("failure") != expected_failure
            or failed.get("http_status") is not None or failed.get("response_id") is not None
            or failed.get("usage") is not None or failed.get("cost_usd") is not None
            or failed.get("attempt_number") != 1
            or failed.get("retry_of_attempt") is not None
            or not isinstance(unknown, dict) or unknown.get("index") != target_index
            or unknown.get("job_id") != expected_id
            or unknown.get("state") != "unknown_outcome_requires_external_reconciliation"):
        raise PilotError("Only the exact latest unknown network failure may use this one-retry continuation path")
    for index, sample in enumerate(samples):
        schedule_index = sample["index"]
        job = jobs[schedule_index]
        expected_id = f'{job["case_id"]}:{job["arm"]}:{job["repeat"]}'
        if (sample.get("job_id") != expected_id
                or sample.get("case_id") != job["case_id"]
                or sample.get("arm") != job["arm"]
                or sample.get("repeat") != job["repeat"]
                or sample.get("request_body_sha256") != job["body_sha256"]):
            raise PilotError(f"Continuation source row {index} does not match the frozen scheduled job identity/hash")
    completed_before = [sample for sample in samples[:-1]
                        if sample.get("http_status") == 200
                        and sample.get("failure") is None
                        and sample.get("sse_done_received") is True
                        and sample.get("response_id")
                        and isinstance(sample.get("usage"), dict)
                        and sample["usage"].get("is_byok") is True
                        and type(sample["usage"].get("prompt_tokens")) is int
                        and type(sample["usage"].get("completion_tokens")) is int
                        and sample["usage"]["prompt_tokens"] >= 0
                        and sample["usage"]["completion_tokens"] >= 0
                        and sample.get("provider", "").strip().casefold() == "minimax"
                        and sample.get("returned_model") == stage.MODEL
                        and sample.get("finish_reason") in {"stop", "length"}
                        and isinstance(sample.get("cost_usd"), (int, float))]
    expected_completed_count = {90: 89, 200: 198, 226: 223}[len(samples)]
    if (len(completed_before) != expected_completed_count
            or previous.get("completed_jobs") != expected_completed_count):
        raise PilotError("Continuation source does not contain the expected receipted completed prefix")
    counts: dict[str, int] = {}
    for sample in completed_before:
        counts[sample["job_id"]] = counts.get(sample["job_id"], 0) + 1
    expected_completed_ids = {f'{jobs[index]["case_id"]}:{jobs[index]["arm"]}:{jobs[index]["repeat"]}'
                              for index in range(target_index)}
    if set(counts) != expected_completed_ids:
        raise PilotError("Continuation source is missing or has extra completed scheduled job IDs")
    if any(count != 1 for count in counts.values()):
        raise PilotError("Continuation source contains an unexpected duplicate successful attempt")
    known_tokens = reported_token_totals(samples)
    for retry_index in expected_retries:
        retried = [sample for sample in samples
                   if sample.get("index") == retry_index and sample.get("attempt_number") == 2]
        if (len(retried) != 1 or retried[0].get("retry_of_attempt") != 1
                or retried[0].get("failure") is not None
                or retried[0].get("http_status") != 200
                or retried[0].get("sse_done_received") is not True
                or not retried[0].get("response_id")):
            raise PilotError(f"Job {retry_index} retry is missing or its attempt-2 audit metadata is invalid")
    if expected_retries:
        if previous.get("attempted_jobs") != len(samples):
            raise PilotError("Continuation source attempted-job count does not match preserved attempts")
        for retry_index, expected_error in prior_unknowns.items():
            attempt = next((sample for sample in samples
                            if sample.get("index") == retry_index
                            and sample.get("attempt_number") == 1), None)
            if (attempt is None or attempt.get("failure") != expected_error
                    or attempt.get("http_status") is not None
                    or attempt.get("response_id") is not None
                    or attempt.get("usage") is not None
                    or attempt.get("cost_usd") is not None
                    or attempt.get("retry_of_attempt") is not None):
                raise PilotError(f"Prior unknown attempt at index {retry_index} was lost or altered")
        if len(samples) == 226 and (previous.get("completed_jobs") != 223
                                    or known_tokens.get("attempts_with_reported_usage") != 223
                                    or known_tokens.get("attempts_with_unknown_tokens") != 3):
            raise PilotError("Latest continuation report counts do not match the audited 226-attempt state")
        if len(samples) == 200 and (previous.get("completed_jobs") != 198
                                    or known_tokens.get("attempts_with_reported_usage") != 198
                                    or known_tokens.get("attempts_with_unknown_tokens") != 2):
            raise PilotError("Continuation report counts do not match the audited 200-attempt state")
        for sample in samples:
            if (sample.get("index") in expected_retries
                    and sample.get("attempt_number") == 2):
                continue
            if (sample.get("index") in prior_unknowns
                    and sample.get("attempt_number") == 1):
                continue
            if sample.get("attempt_number") != 1 or sample.get("retry_of_attempt") is not None:
                raise PilotError("Continuation source has an unexpected retry or attempt-number mutation")
    settled_sum = 0.0
    for sample in samples:
        receipt, receipt_source = stage.cost_receipt(sample.get("usage"))
        if receipt is None:
            if sample.get("cost_usd") is not None:
                raise PilotError("Continuation source has a cost without a matching provider usage receipt")
            continue
        if (sample.get("cost_usd") != receipt
                or sample.get("cost_receipt_source") != receipt_source):
            raise PilotError("Continuation source cost receipt does not match provider usage")
        settled_sum += receipt
    saved_settled = previous.get("settled_cost_usd")
    if (not isinstance(saved_settled, (int, float)) or isinstance(saved_settled, bool)
            or not math.isfinite(float(saved_settled))
            or not math.isclose(settled_sum, float(saved_settled), rel_tol=1e-12, abs_tol=1e-9)):
        raise PilotError("Continuation source settled receipts do not reconcile to its saved ledger")
    if (previous.get("provider_token_totals") is not None
            and previous.get("provider_token_totals") != known_tokens):
        raise PilotError("Continuation source token totals do not match its preserved provider receipts")
    if len(samples) in {200, 226} and previous.get("provider_token_totals") is None:
        raise PilotError("Latest continuation report is missing its provider token ledger")


def continue_dispatch(args: argparse.Namespace) -> int:
    if (not args.retry_unknown_once or args.spend_cap_usd is None
            or not args.accept_unknown_prior_outcome):
        raise PilotError("Continuation requires --retry-unknown-once, --accept-unknown-prior-outcome, and --spend-cap-usd")
    if args.bundle.exists() is False:
        raise PilotError("Prepared offline bundle is required")
    manifest, jobs, _cases, rebuilt = reconstruct(args.manifest, args.dataset,
                                                  args.tokenizer, args.template)
    frozen_bundle = load_continuation_bundle(args.bundle, rebuilt)
    try:
        previous = json.loads(args.continue_from_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PilotError(f"Cannot load continuation source report: {error}") from error
    validate_continuation(previous, frozen_bundle, jobs)
    validate_prefix_and_cap(EXPECTED_JOBS, args.spend_cap_usd, jobs)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise PilotError("OPENROUTER_API_KEY is required only for explicit dispatch")
    result = _dispatch_prefix(manifest, jobs, frozen_bundle, args.output,
                              args.spend_cap_usd, EXPECTED_JOBS, api_key,
                              args.confirm_no_unsettled_requests,
                              args.confirm_minimax_billing_headroom,
                              previous_report=previous,
                              provider_billing_authorized_unverified=(
                                  args.user_authorized_spend_cap_with_unverified_provider_balance),
                              prior_unknown_outcome_explicitly_accepted=args.accept_unknown_prior_outcome)
    print(json.dumps({key: result.get(key) for key in
                      ("status", "dispatch_prefix_count", "full_schedule_jobs",
                       "attempted_jobs", "completed_jobs", "full_schedule_complete",
                       "score_summary", "stop_reason", "schedule_sha256")}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=CURRENT_MANIFEST)
    p.add_argument("--dataset", type=Path, default=stage.DATASET_DEFAULT)
    p.add_argument("--tokenizer", type=Path, default=stage.TOKENIZER_DEFAULT)
    p.add_argument("--template", type=Path, default=stage.TEMPLATE_DEFAULT)
    p.add_argument("--bundle", type=Path, default=BUNDLE_DEFAULT)
    p.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    p.add_argument("--dispatch", action="store_true", help="Explicitly dispatch a first-N pilot")
    p.add_argument("--continue-from-report", type=Path,
                   help="Explicitly continue the sole eligible unknown SSL attempt in a new output report")
    p.add_argument("--retry-unknown-once", action="store_true",
                   help="Authorize exactly one retry of job 89, preserving its unknown first attempt")
    p.add_argument("--prefix", type=int, default=DEFAULT_PREFIX,
                   help="Number of first scheduled jobs; no arbitrary job selection")
    p.add_argument("--spend-cap-usd", type=float, help="Positive client-side spend cap for this prefix")
    p.add_argument("--confirm-no-unsettled-requests", action="store_true")
    p.add_argument("--confirm-minimax-billing-headroom", action="store_true")
    p.add_argument("--user-authorized-spend-cap-with-unverified-provider-balance", action="store_true",
                   help="Record user-approved spend cap while marking MiniMax-side available balance unverified")
    p.add_argument("--accept-unknown-prior-outcome", action="store_true",
                   help="Explicitly continue while preserving the prior request's unresolved outcome")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.dispatch and args.continue_from_report:
            raise PilotError("Choose --dispatch or --continue-from-report, not both")
        if args.continue_from_report:
            return continue_dispatch(args)
        return dispatch(args) if args.dispatch else prepare(args)
    except (PilotError, stage.StageError, OSError, ValueError, KeyError) as error:
        print(f"FAIL CLOSED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
