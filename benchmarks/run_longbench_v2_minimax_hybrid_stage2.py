"""Run the frozen 100-task MiniMax hybrid Sift development evaluation.

The relation-matrix candidate is attempted only for the six audited IDs.
Unchanged default Sift handles the other 94 tasks and any audited-ID candidate
fallback. This is one Sift request per task/repeat, not a full-context rerun.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import platform
import random
import sys
import time
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

import run_longbench_v2_minimax as baseline  # noqa: E402
import run_longbench_v2_minimax_relation_followup_v3 as v3  # noqa: E402
from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from relation_matrix_candidate import MatrixError, matrix_messages  # noqa: E402
from sift import CompactionError, compact_messages  # noqa: E402

REQUESTED_MODEL = "minimax/minimax-m3"
TARGET = 32_768
SAFETY_MARGIN = 128
EFFECTIVE_TARGET = TARGET - SAFETY_MARGIN
REPEATS = 3
EXPECTED_TASKS = 100
OUTPUT_TOKENS = 128
MAX_WORKERS = 1
MAX_SPEND_USD = 4.0
AGGREGATE_LIMIT_USD = 20.0
PROVIDER_PROJECTION = 3.25
PROVIDER_LIMIT = 524_288
MATRIX_CASE_IDS = (
    "672494e5bb02136c067d7697",
    "67249705bb02136c067d76d1",
    "6724c1d4bb02136c067d77ec",
    "67285e1dbb02136c067d901b",
    "67286036bb02136c067d9092",
    "6724c4aabb02136c067d78a6",
)

# Hash the complete repository-local call surface used to build, dispatch, and
# validate each request.  The manifest freezes these hashes before dispatch.
# Keep aliases already consumed by the analyzer alongside the more explicit
# provenance names so existing readers remain compatible.
SOURCE_PATHS = {
    "runner_sha256": ROOT / "benchmarks/run_longbench_v2_minimax_hybrid_stage2.py",
    "analyzer_sha256": ROOT / "benchmarks/analyze_longbench_v2_minimax_hybrid_stage2.py",
    "v3_analysis_sha256": ROOT / "benchmarks/analyze_longbench_v2_minimax_relation_followup_v3_corrected.py",
    "matrix_candidate_sha256": ROOT / "benchmarks/relation_matrix_candidate.py",
    "v3_gate_sha256": ROOT / "benchmarks/longbench_v3_gate.py",
    "core_sha256": ROOT / "src/sift/core.py",
    "v3_runner_sha256": ROOT / "benchmarks/run_longbench_v2_minimax_relation_followup_v3.py",
    "baseline_runner_sha256": ROOT / "benchmarks/run_longbench_v2_minimax.py",
    "dataset_preparation_module_sha256": ROOT / "benchmarks/prepare_longbench_v2.py",
    "minimax_renderer_module_sha256": ROOT / "benchmarks/prepare_longbench_v2_minimax.py",
    "sift_package_init_sha256": ROOT / "src/sift/__init__.py",
}


class Stage2Error(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def runtime_reproducibility_metadata() -> dict[str, str | None]:
    """Capture non-secret runtime versions that affect tokenization/transport."""
    def package_version(name: str) -> str | None:
        try:
            return version(name)
        except PackageNotFoundError:
            return None

    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "tokenizers_version": package_version("tokenizers"),
        "requests_version": package_version("requests"),
        "platform": platform.platform(),
    }


def current_source_hashes(*, tokenizer_path: Path | None = None,
                          template_path: Path | None = None,
                          protocol_path: Path | None = None,
                          route_path: Path | None = None) -> dict[str, str]:
    """Return the source/artifact hashes that must be frozen in the Stage 2 manifest."""
    hashes = {key: file_sha256(path) for key, path in SOURCE_PATHS.items()}
    for key, path in (
        ("tokenizer_sha256", tokenizer_path),
        ("chat_template_sha256", template_path),
        ("protocol_sha256", protocol_path),
        ("route_metadata_sha256", route_path),
    ):
        if path is not None:
            hashes[key] = file_sha256(path)
    return hashes


def freeze_job_request(job: dict[str, Any]) -> dict[str, Any]:
    """Attach and return the canonical request record for one prepared job."""
    payload = v3._request_payload(job)
    digest = v3._request_hash(payload)
    job["request_payload"] = payload
    job["request_payload_sha256"] = digest
    return {"job_id": job["job_id"], "request": payload, "request_sha256": digest}


def verify_frozen_job_request(job: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Return the exact frozen body after checking its identity and digest."""
    if record.get("job_id") != job.get("job_id"):
        raise Stage2Error(f"Frozen request belongs to a different job: {job.get('job_id')}")
    payload = record.get("request")
    digest = record.get("request_sha256")
    if not isinstance(payload, dict) or digest != job.get("request_payload_sha256"):
        raise Stage2Error(f"Frozen request metadata mismatch: {job.get('job_id')}")
    if v3._request_hash(payload) != digest or payload != job.get("request_payload"):
        raise Stage2Error(f"Frozen request payload changed: {job.get('job_id')}")
    return payload


def verify_preflight_artifact(preflight_path: Path, *, jobs: list[dict[str, Any]],
                             expected_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate reviewed preflight identity and return its exact request records."""
    try:
        artifact = json.loads(preflight_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Stage2Error(f"Unable to read Stage 2 preflight artifact: {error}") from error
    if (artifact.get("status") != "prepared_only_no_dispatch"
            or artifact.get("dry_run") is not True
            or artifact.get("actual_dispatch_started") is not False
            or artifact.get("samples") != []):
        raise Stage2Error("Preflight artifact must be an untouched no-dispatch dry run")

    identity_fields = (
        "stage_manifest_sha256", "baseline_manifest_sha256", "baseline_result_sha256",
        "source_hashes", "budget", "protocol",
        "runtime_reproducibility",
    )
    for field in identity_fields:
        if artifact.get(field) != expected_report.get(field):
            raise Stage2Error(f"Preflight artifact {field} differs from current dispatch inputs")
    preflight_route = artifact.get("route_metadata")
    current_route = expected_report.get("route_metadata")
    if (not isinstance(preflight_route, dict) or not isinstance(current_route, dict)
            or stable_route_identity(preflight_route) != stable_route_identity(current_route)):
        raise Stage2Error("Preflight artifact stable route identity differs from current dispatch inputs")
    expected_preparation = expected_report.get("preparation", {})
    artifact_preparation = artifact.get("preparation", {})
    stable_preparation_fields = (
        "prepared_job_count", "matrix_selected_job_count", "matrix_fallback_job_count",
        "max_projected_prompt_tokens",
    )
    for field in stable_preparation_fields:
        if artifact_preparation.get(field) != expected_preparation.get(field):
            raise Stage2Error(f"Preflight artifact preparation.{field} differs")

    records = artifact.get("prepared_requests")
    if not isinstance(records, list) or len(records) != len(jobs):
        raise Stage2Error("Preflight artifact must contain every prepared request body")
    prepared_job_rows = artifact.get("prepared_jobs")
    if not isinstance(prepared_job_rows, list) or len(prepared_job_rows) != len(jobs):
        raise Stage2Error("Preflight artifact prepared_jobs do not cover the complete dispatch")
    expected_jobs = {job["job_id"]: job for job in jobs}
    if len(expected_jobs) != len(jobs):
        raise Stage2Error("Locally regenerated dispatch job IDs are not unique")
    for row, job in zip(prepared_job_rows, jobs, strict=True):
        if (row.get("job_id") != job["job_id"]
                or row.get("request_payload_sha256") != job["request_payload_sha256"]):
            raise Stage2Error(f"Preflight prepared-job identity differs: {job['job_id']}")

    seen: set[str] = set()
    for record, job in zip(records, jobs, strict=True):
        if not isinstance(record, dict):
            raise Stage2Error("Preflight request record is not an object")
        job_id = record.get("job_id")
        if job_id in seen or job_id != job["job_id"]:
            raise Stage2Error(f"Preflight request ordering or identity differs: {job_id}")
        seen.add(job_id)
        verify_frozen_job_request(job, record)
    return records


def index_frozen_request_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index already-verified artifact records without rebuilding their objects."""
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        job_id = record.get("job_id")
        if not isinstance(job_id, str) or job_id in indexed:
            raise Stage2Error("Frozen preflight request IDs must be unique strings")
        indexed[job_id] = record
    return indexed


def stable_route_identity(route: dict[str, Any]) -> dict[str, Any]:
    """Drop only values recalculated during route freshness validation."""
    volatile = {"validated_utc", "metadata_age_seconds"}
    return {key: value for key, value in route.items() if key not in volatile}


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_cases(manifest_path: Path, dataset_path: Path, tokenizer_path: Path,
               template_path: Path) -> tuple[dict[str, Any], Tokenizer, list[dict[str, Any]]]:
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    if manifest.get("model", {}).get("id") != REQUESTED_MODEL:
        raise Stage2Error("Frozen baseline manifest model does not match MiniMax M3")
    if manifest.get("dataset", {}).get("revision") != DATASET_REVISION:
        raise Stage2Error("Frozen baseline dataset revision is unexpected")
    if manifest.get("dataset", {}).get("data_file_sha256") != DATASET_SHA256:
        raise Stage2Error("Frozen baseline dataset hash metadata is unexpected")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise Stage2Error("Local LongBench v2 data hash does not match the pinned dataset")
    frozen = manifest.get("cases")
    if not isinstance(frozen, list) or len(frozen) != EXPECTED_TASKS:
        raise Stage2Error("Frozen development manifest must contain exactly 100 tasks")
    ids = [row.get("id") for row in frozen if isinstance(row, dict)]
    if len(ids) != EXPECTED_TASKS or len(set(ids)) != EXPECTED_TASKS:
        raise Stage2Error("Frozen task IDs must be unique")
    if not set(MATRIX_CASE_IDS).issubset(ids):
        raise Stage2Error("All six audited matrix IDs must appear in the frozen sample")
    harness = manifest.get("harness", {})
    for path_key, digest_key in (
        ("runner_path", "runner_sha256"),
        ("protocol_path", "protocol_sha256"),
        ("preparation_script", "preparation_script_sha256"),
        ("dataset_preparation_module_path", "dataset_preparation_module_sha256"),
        ("m3_renderer_module_path", "m3_renderer_module_sha256"),
    ):
        rel = harness.get(path_key)
        expected = harness.get(digest_key)
        if not isinstance(rel, str) or not isinstance(expected, str):
            raise Stage2Error(f"Frozen sample is missing harness provenance {path_key}/{digest_key}")
        source = (ROOT / rel).resolve()
        try:
            source.relative_to(ROOT)
        except ValueError as error:
            raise Stage2Error(f"Frozen source escapes repository: {rel}") from error
        if not source.is_file() or file_sha256(source) != expected:
            raise Stage2Error(f"Frozen baseline source hash mismatch: {rel}")
    model = manifest.get("model", {})
    if file_sha256(tokenizer_path) != model.get("tokenizer_sha256"):
        raise Stage2Error("MiniMax tokenizer hash differs from frozen sample")
    if file_sha256(template_path) != model.get("chat_template_sha256"):
        raise Stage2Error("MiniMax chat template hash differs from frozen sample")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    expected = {row["id"]: row for row in frozen}
    rows: dict[str, dict[str, Any]] = {}
    for row in iter_json_array(dataset_path):
        if row.get("_id") in expected:
            rows[row["_id"]] = row
            if len(rows) == EXPECTED_TASKS:
                break
    if set(rows) != set(expected):
        raise Stage2Error("Frozen LongBench data rows are missing")
    cases = []
    for item in frozen:
        row = rows[item["id"]]
        messages = make_messages(row)
        if row.get("answer") != item.get("answer_key"):
            raise Stage2Error(f"Frozen answer key changed: {item['id']}")
        if prompt_sha256(messages) != item.get("prompt_sha256"):
            raise Stage2Error(f"Frozen prompt hash changed: {item['id']}")
        rendered = v3.token_count(tokenizer, messages)
        if rendered != item.get("m3_rendered_prompt_tokens"):
            raise Stage2Error(f"Pinned MiniMax token count changed: {item['id']}")
        if not TARGET < rendered <= 150_000:
            raise Stage2Error(f"Frozen prompt outside eligibility bounds: {item['id']}={rendered}")
        if item.get("answer_key") not in {"A", "B", "C", "D"}:
            raise Stage2Error(f"Invalid answer key: {item['id']}")
        cases.append({
            "frozen": item,
            "messages": messages,
            "choices": {letter: row[f"choice_{letter}"] for letter in "ABCD"},
        })
    return manifest, tokenizer, cases


def prepare_jobs(cases: list[dict[str, Any]], tokenizer: Tokenizer, seed: int) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    counter = lambda value: v3.token_count(tokenizer, value)
    for case in cases:
        frozen = case["frozen"]
        messages = v3._json_object_messages(case["messages"])
        default_started = time.perf_counter()
        default_result = compact_messages(
            messages, counter, target=EFFECTIVE_TARGET,
            raw_limit=1_000_000, protocol="openai",
        )
        default_ms = (time.perf_counter() - default_started) * 1000
        default_tokens = counter(default_result.messages)
        if default_tokens > EFFECTIVE_TARGET:
            raise Stage2Error(f"Default Sift exceeds target for {frozen['id']}")

        candidate_ms = None
        candidate_audit = None
        matrix_audit = None
        fallback_reason = None
        selected = default_result
        selected_by = "default_sift"
        if frozen["id"] in MATRIX_CASE_IDS:
            started = time.perf_counter()
            try:
                candidate = compact_messages(
                    messages, counter, target=EFFECTIVE_TARGET,
                    raw_limit=1_000_000, protocol="openai", research_relation_closure=True,
                )
                candidate_audit = candidate.audit
                if candidate.audit.get("comparison_groups_complete") is not True:
                    fallback_reason = "research_relation_incomplete_comparison_groups"
                elif candidate.audit.get("unfit_comparison_groups") != 0:
                    fallback_reason = "research_relation_nonzero_unfit_groups"
                if fallback_reason is None:
                    matrix, matrix_audit = matrix_messages(candidate.messages, case["choices"])
                    if counter(matrix) > EFFECTIVE_TARGET:
                        fallback_reason = "relation_matrix_candidate_exceeded_target"
                    else:
                        selected = type(default_result)(
                            matrix,
                            {**candidate.audit,
                             "forwarded_tokens": counter(matrix),
                             "method": "research_relation_closure+option_aligned_matrix_v3",
                             "relation_matrix_audit": matrix_audit},
                        )
                        selected_by = "option_aligned_matrix_v3"
            except MatrixError as error:
                fallback_reason = f"relation_matrix_error:{str(error)[:240]}"
            except CompactionError as error:
                fallback_reason = f"{error.code or 'compaction_error'}:{str(error)[:240]}"
            candidate_ms = (time.perf_counter() - started) * 1000
            if fallback_reason is not None:
                selected = default_result
                selected_by = "default_sift_candidate_fallback"

        local_tokens = counter(selected.messages)
        projected = math.ceil(local_tokens * PROVIDER_PROJECTION) + OUTPUT_TOKENS
        if projected > PROVIDER_LIMIT:
            raise Stage2Error(f"Projected provider request exceeds endpoint limit: {frozen['id']}")
        prepared.append({
            "case_id": frozen["id"],
            "domain": frozen["domain"],
            "expected": frozen["answer_key"],
            "arm": "sift_hybrid_stage2",
            "selection_method": selected_by,
            "matrix_candidate_attempted": frozen["id"] in MATRIX_CASE_IDS,
            "matrix_candidate_selected": selected_by == "option_aligned_matrix_v3",
            "candidate_fallback_reason": fallback_reason,
            "candidate_audit": candidate_audit,
            "relation_matrix_audit": matrix_audit,
            "target_tokens": TARGET,
            "messages": selected.messages,
            "request_messages_sha256": v3._messages_hash(selected.messages),
            "original_prompt_sha256": frozen["prompt_sha256"],
            "local_rendered_prompt_tokens": local_tokens,
            "projected_provider_prompt_tokens": projected,
            "default_sift_preprocessing_ms": default_ms,
            "candidate_preprocessing_ms": candidate_ms,
            "sift_preprocessing_ms": default_ms + (candidate_ms or 0.0),
            "selector_audit": selected.audit,
        })
    by_case = {job["case_id"]: job for job in prepared}
    jobs = []
    for repeat in range(1, REPEATS + 1):
        case_ids = list(by_case)
        random.Random(seed + repeat).shuffle(case_ids)
        for case_id in case_ids:
            job = dict(by_case[case_id])
            job["repeat"] = repeat
            job["generation_seed"] = seed + repeat + 1
            job["job_id"] = f"{case_id}:{repeat}:sift_hybrid_stage2"
            # Materialize the exact canonical body now.  Preflight inspection and
            # dispatch both use this same object; dispatch never reconstructs it.
            freeze_job_request(job)
            jobs.append(job)
    if len(jobs) != EXPECTED_TASKS * REPEATS or len({j["job_id"] for j in jobs}) != len(jobs):
        raise Stage2Error("Prepared job count or IDs are invalid")
    return jobs


def _job_reserve(job: dict[str, Any], input_price: float, output_price: float) -> float:
    return (job["local_rendered_prompt_tokens"] * 1.5 * input_price
            + OUTPUT_TOKENS * output_price) / 1_000_000


def run(manifest_path: Path, stage_manifest_path: Path, route_path: Path,
        dataset_path: Path, tokenizer_path: Path, template_path: Path,
        output_path: Path, seed: int = 20261022,
        input_price: float = 0.30, output_price: float = 1.20,
        dry_run: bool = False,
        preflight_artifact_path: Path | None = None) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite result: {output_path}")
    route = v3.load_route_metadata(route_path, input_price, output_price)
    baseline_manifest, tokenizer, cases = load_cases(
        manifest_path, dataset_path, tokenizer_path, template_path
    )
    baseline_result = ROOT / "docs/results/longbench-v2-minimax-m3-100-2026-10-16.json"
    baseline_result_sha = file_sha256(baseline_result)
    stage_raw = stage_manifest_path.read_bytes()
    stage = json.loads(stage_raw.decode("utf-8-sig"))
    protocol = stage.get("protocol", {})
    if protocol.get("stage") != 2 or protocol.get("request_count") != EXPECTED_TASKS * REPEATS:
        raise Stage2Error("Stage manifest must freeze Stage 2 with exactly 300 requests")
    if protocol.get("task_ids") != [case["frozen"]["id"] for case in cases]:
        raise Stage2Error("Stage manifest task order differs from the frozen 100-task sample")
    if protocol.get("arms") != ["sift_hybrid_stage2"] or protocol.get("repeats") != REPEATS:
        raise Stage2Error("Stage manifest arm or repeat count is unexpected")
    if protocol.get("candidate_policy", {}).get("matrix_candidate_ids") != list(MATRIX_CASE_IDS):
        raise Stage2Error("Stage manifest candidate allowlist differs from the reviewed six IDs")
    if protocol.get("candidate_policy", {}).get("matrix_fallbacks_allowed") is not False:
        raise Stage2Error("Stage manifest must disallow candidate fallbacks")
    if protocol.get("model", {}).get("id") != REQUESTED_MODEL:
        raise Stage2Error("Stage manifest model is unexpected")
    if protocol.get("provider_policy") != {"only": ["minimax"], "allow_fallbacks": False}:
        raise Stage2Error("Stage manifest provider policy must pin MiniMax without fallbacks")
    expected_generation = {
        "temperature": 0.1, "top_p": 0.8, "reasoning_enabled": False,
        "max_tokens": OUTPUT_TOKENS, "response_format": {"type": "json_object"},
        "answer_format": "json_object_single_answer_a_to_d", "retries": 0, "workers": 1,
    }
    if protocol.get("generation") != expected_generation:
        raise Stage2Error("Stage manifest generation parameters differ from the runner")
    if protocol.get("cli_seed") != seed or protocol.get("generation_seeds") != [seed + r + 1 for r in range(1, 4)]:
        raise Stage2Error("Stage manifest generation seeds differ from CLI seed")
    if protocol.get("sift_target_tokens") != TARGET:
        raise Stage2Error("Stage manifest Sift target differs from 32,768")
    if stage.get("baseline_manifest_sha256") != file_sha256(manifest_path):
        raise Stage2Error("Stage manifest baseline sample hash differs")
    if stage.get("baseline_result_sha256") != baseline_result_sha:
        raise Stage2Error("Stage manifest baseline result hash differs")
    if stage.get("route_metadata_sha256") != file_sha256(route_path):
        raise Stage2Error("Stage manifest route metadata hash differs")
    declared_route = Path(stage.get("route_metadata_path", ""))
    if not declared_route.is_absolute():
        declared_route = ROOT / declared_route
    if declared_route.resolve() != route_path.resolve():
        raise Stage2Error("Route metadata path differs from the frozen stage manifest")
    protocol_file = (ROOT / stage["protocol_path"]).resolve()
    try:
        protocol_file.relative_to(ROOT)
    except ValueError as error:
        raise Stage2Error("Stage manifest protocol path escapes repository") from error
    expected_hashes = current_source_hashes(
        tokenizer_path=tokenizer_path,
        template_path=template_path,
        protocol_path=protocol_file,
        route_path=route_path,
    )
    declared_hashes = stage.get("source_hashes")
    if not isinstance(declared_hashes, dict):
        raise Stage2Error("Stage manifest source_hashes must be an object")
    missing_hashes = sorted(set(expected_hashes) - set(declared_hashes))
    if missing_hashes:
        raise Stage2Error("Stage manifest is missing source hashes: " + ", ".join(missing_hashes))
    for key, digest in expected_hashes.items():
        if declared_hashes.get(key) != digest:
            raise Stage2Error(f"Stage manifest {key} differs")

    jobs = prepare_jobs(cases, tokenizer, seed)
    prepared_request_records = [
        {"job_id": job["job_id"], "request": job["request_payload"],
         "request_sha256": job["request_payload_sha256"]}
        for job in jobs
    ]
    matrix_selected = [j for j in jobs if j["matrix_candidate_selected"]]
    matrix_fallbacks = [j for j in jobs if j["candidate_fallback_reason"]]
    if len(matrix_selected) != len(MATRIX_CASE_IDS) * REPEATS:
        raise Stage2Error("Not all six audited matrix tasks were selected in all repeats")
    if matrix_fallbacks:
        raise Stage2Error("A matrix fallback occurred during frozen Stage 2 preparation")
    input_total = sum(j["local_rendered_prompt_tokens"] for j in jobs)
    planned_reserve = sum(_job_reserve(j, input_price, output_price) for j in jobs)
    budget = {
        "planned_requests": len(jobs),
        "input_tokens_local": input_total,
        "input_reserve_multiplier": 1.5,
        "planned_run_reserve_usd": planned_reserve,
        "run_ceiling_usd": MAX_SPEND_USD,
        "run_ceiling_passed": planned_reserve <= MAX_SPEND_USD,
        "input_price_usd_per_million": input_price,
        "output_price_usd_per_million": output_price,
    }
    aggregate = stage["aggregate_budget"]
    prior_actual = float(aggregate["prior_actual_usd"])
    prior_unsettled = float(aggregate["prior_unsettled_usd"])
    projected = prior_actual + prior_unsettled + planned_reserve
    budget["aggregate_exposure"] = {
        "limit_usd": AGGREGATE_LIMIT_USD,
        "prior_actual_usd": prior_actual,
        "prior_unsettled_usd": prior_unsettled,
        "planned_run_reserve_usd": planned_reserve,
        "projected_total_usd": projected,
        "remaining_headroom_usd": AGGREGATE_LIMIT_USD - projected,
        "passed": projected <= AGGREGATE_LIMIT_USD,
        "accounting_note": "Task-scoped conservative artifact ledger; BYOK key usage is aggregate/unitemized, not an invoice.",
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "prepared_only_no_dispatch" if dry_run else "in_progress",
        "evaluation": "100-task in-sample hybrid LongBench v2 MiniMax Sift development evaluation",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "model": REQUESTED_MODEL,
        "runtime_reproducibility": runtime_reproducibility_metadata(),
        "route_metadata": route,
        "route": {"provider": {"only": ["minimax"], "allow_fallbacks": False}},
        "baseline_manifest_sha256": file_sha256(manifest_path),
        "baseline_result_sha256": baseline_result_sha,
        "stage_manifest_sha256": sha256_bytes(stage_raw),
        "source_hashes": {
            **expected_hashes,
            "baseline_manifest_sha256": file_sha256(manifest_path),
        },
        "protocol": {
            "stage": 2,
            "task_count": EXPECTED_TASKS,
            "task_ids": protocol["task_ids"],
            "repeats": REPEATS,
            "request_count": len(jobs),
            "arms": ["sift_hybrid_stage2"],
            "candidate_ids": list(MATRIX_CASE_IDS),
            "default_sift_ids": [case["frozen"]["id"] for case in cases if case["frozen"]["id"] not in MATRIX_CASE_IDS],
            "candidate_policy": "matrix only on six audited IDs; require successful complete-entity matrix; default Sift elsewhere",
            "fallback_policy": "any audited-ID candidate fallback invalidates the frozen preflight; no API dispatch",
            "target_tokens": TARGET,
            "generation_seed_formula": "cli_seed + repeat + 1",
            "retries": 0,
            "workers": MAX_WORKERS,
            "shuffle": "seeded case order per repeat; one Sift request per task/repeat",
            "dispatch_job_ids": [j["job_id"] for j in jobs],
            "request_hash_algorithm": "sha256(utf8(json.dumps(request, ensure_ascii=False, separators=(',', ':'))))",
        },
        "budget": budget,
        "preparation": {
            "prepared_job_count": len(jobs),
            "matrix_selected_job_count": len(matrix_selected),
            "matrix_fallback_job_count": len(matrix_fallbacks),
            "max_projected_prompt_tokens": max(j["projected_provider_prompt_tokens"] for j in jobs),
            "preprocessing_ms_total": sum(j["sift_preprocessing_ms"] for j in jobs),
        },
        "prepared_jobs": [{k: v for k, v in job.items()
                           if k not in {"messages", "request_payload"}} for job in jobs],
        # Exact request bodies, including all messages and generation fields,
        # are retained for review and independently verifiable against each
        # prepared job's request_payload_sha256 before any API call.
        "prepared_requests": prepared_request_records,
        "samples": [],
        "not_started_jobs": [],
        "actual_dispatch_started": False,
        "dry_run": dry_run,
    }
    if not budget["run_ceiling_passed"] or not budget["aggregate_exposure"]["passed"]:
        report["status"] = "not_started_budget_exceeded"
        atomic_write(output_path, report)
        return report
    if dry_run:
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_write(output_path, report)
        return report

    if preflight_artifact_path is None:
        raise Stage2Error("--preflight-artifact is required before any API dispatch")
    frozen_request_records = verify_preflight_artifact(
        preflight_artifact_path, jobs=jobs, expected_report=report,
    )
    # Use the JSON-parsed request objects from the inspected artifact itself.
    # Equality/hash checks above prove they match regeneration; object identity
    # here ensures no request body is rebuilt after review.
    for job, record in zip(jobs, frozen_request_records, strict=True):
        job["request_payload"] = record["request"]
    report["prepared_requests"] = frozen_request_records
    report["preflight_artifact_sha256"] = file_sha256(preflight_artifact_path)

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise Stage2Error("OPENROUTER_API_KEY is required")
    atomic_write(output_path, report)
    frozen_requests = index_frozen_request_records(frozen_request_records)
    pending = deque(jobs)
    stop_reasons: list[str] = []
    guard_spend = 0.0
    while pending:
        job = pending[0]
        reserve = _job_reserve(job, input_price, output_price)
        if guard_spend + reserve > MAX_SPEND_USD or prior_actual + prior_unsettled + guard_spend + reserve > AGGREGATE_LIMIT_USD:
            stop_reasons.append("budget_guard_would_be_exceeded")
            break
        pending.popleft()
        payload = verify_frozen_job_request(job, frozen_requests[job["job_id"]])
        if not report["actual_dispatch_started"]:
            report["actual_dispatch_started"] = True
            report["dispatch_started_utc"] = datetime.now(timezone.utc).isoformat()
        report["in_flight_request"] = {
            "job_id": job["job_id"], "request": payload,
            "request_sha256": v3._request_hash(payload),
            "guard_reservation_usd": reserve,
            "dispatch_started_utc": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write(output_path, report)
        result = v3._call_openrouter(payload, api_key=api_key)
        usage = result.get("usage")
        receipt, receipt_source = baseline.cost_receipt(usage)
        receipt_issues = v3.runtime_receipt_issues(usage)
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        ratio = prompt_tokens / job["local_rendered_prompt_tokens"] if type(prompt_tokens) is int else None
        answer_valid = (result.get("normal") is True
                        and result.get("finish_reason") == "stop"
                        and result.get("choice") in {"A", "B", "C", "D"})
        if result.get("http_status") != 200 or result.get("model") != REQUESTED_MODEL:
            stop_reasons.append("route_attribution_mismatch")
        if not isinstance(result.get("provider"), str) or result["provider"].casefold() != "minimax":
            stop_reasons.append("provider_attribution_mismatch")
        if receipt is None or receipt_issues:
            stop_reasons.extend(f"invalid_usage_or_cost_receipt:{x}" for x in receipt_issues or [receipt_source])
        if type(prompt_tokens) is not int or prompt_tokens <= 0 or ratio is None or ratio > 1.05:
            stop_reasons.append("provider_prompt_usage_or_ratio_invalid")
        if type(completion_tokens) is not int or completion_tokens < 0 or result.get("failure") is not None:
            stop_reasons.append("transport_or_completion_usage_failure")
        charge = receipt if receipt is not None else reserve
        guard_spend += charge
        if guard_spend > MAX_SPEND_USD or prior_actual + prior_unsettled + guard_spend > AGGREGATE_LIMIT_USD:
            stop_reasons.append("settled_budget_ceiling_exceeded")
        sample = {
            **result,
            **{k: v for k, v in job.items() if k != "messages"},
            "request": payload,
            "request_sha256": v3._request_hash(payload),
            "correct": answer_valid and result.get("choice") == job["expected"],
            "answer_validity": "valid" if answer_valid else "invalid_or_incomplete",
            "strict_sample_valid": not stop_reasons and answer_valid,
            "strict_receipt_valid": receipt is not None and not receipt_issues,
            "cost_receipt_status": "reported" if receipt is not None and not receipt_issues else "missing_or_invalid",
            "cost_receipt_source": receipt_source,
            "receipt": usage,
            "provider_local_input_token_ratio": ratio,
            "guard_reserved_cost_usd": reserve,
            "guard_charge_usd": charge,
        }
        report["in_flight_request"] = None
        report["samples"].append(sample)
        report["budget"].update({
            "actual_upstream_reported_cost_usd": sum(v3._reported_cost(s.get("usage"), upstream=True) for s in report["samples"]),
            "budget_guard_spend_usd": guard_spend,
            "unknown_cost_receipts": sum(s["cost_receipt_status"] != "reported" for s in report["samples"]),
            "stop_reasons": sorted(set(stop_reasons)),
        })
        atomic_write(output_path, report)
        if stop_reasons:
            break
    if pending:
        report["not_started_jobs"] = [
            {"job_id": j["job_id"], "case_id": j["case_id"], "repeat": j["repeat"],
             "reason": ";".join(sorted(set(stop_reasons))) or "budget_guard_would_be_exceeded"}
            for j in pending
        ]
    report["status"] = "safety_guard_stopped" if stop_reasons else ("budget_guard_stopped" if pending else "complete")
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_write(output_path, report)
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--stage-manifest", type=Path)
    parser.add_argument("--route-metadata", type=Path)
    parser.add_argument("--dataset-path", type=Path)
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "tmp/minimax-m3-tokenizer.json")
    parser.add_argument("--template", type=Path, default=ROOT / "tmp/minimax-m3-chat-template.jinja")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--input-price-per-million", type=float, default=0.30)
    parser.add_argument("--output-price-per-million", type=float, default=1.20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-artifact", type=Path,
                        help="Reviewed no-dispatch artifact required before live dispatch")
    parser.add_argument(
        "--print-source-hashes", action="store_true",
        help="Print hashes to freeze in the Stage 2 manifest; no requests are sent.",
    )
    parser.add_argument("--protocol", type=Path, help="Protocol file for --print-source-hashes")
    parser.add_argument("--route-for-hashes", type=Path, help="Route metadata for --print-source-hashes")
    parser.add_argument("--print-tokenizer", type=Path, help="Tokenizer for --print-source-hashes")
    parser.add_argument("--print-template", type=Path, help="Chat template for --print-source-hashes")
    args = parser.parse_args()
    if args.print_source_hashes:
        print(json.dumps(current_source_hashes(
            tokenizer_path=args.print_tokenizer,
            template_path=args.print_template,
            protocol_path=args.protocol,
            route_path=args.route_for_hashes,
        ), indent=2, sort_keys=True))
        raise SystemExit(0)
    missing_args = [name for name in ("manifest", "stage_manifest", "route_metadata", "dataset_path", "output")
                    if getattr(args, name) is None]
    if missing_args:
        parser.error("required unless --print-source-hashes is used: " + ", ".join("--" + value.replace("_", "-") for value in missing_args))
    result = run(args.manifest, args.stage_manifest, args.route_metadata,
                 args.dataset_path, args.tokenizer, args.template, args.output,
                 args.seed, args.input_price_per_million,
                 args.output_price_per_million, args.dry_run,
                 args.preflight_artifact)
    print(json.dumps({"status": result["status"], "samples": len(result["samples"]),
                      "prepared_jobs": result["preparation"]["prepared_job_count"],
                      "budget": result["budget"], "output": str(args.output)}, indent=2))
