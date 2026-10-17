import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

import run_longbench_v2_minimax_hybrid_stage2 as stage2  # noqa: E402


def test_frozen_request_record_contains_exact_canonical_request(monkeypatch):
    payload = {
        "model": "minimax/minimax-m3",
        "messages": [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "long prompt " * 100},
        ],
        "temperature": 0.1,
        "seed": 20261024,
        "max_tokens": 128,
        "response_format": {"type": "json_object"},
        "provider": {"only": ["minimax"], "allow_fallbacks": False},
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    monkeypatch.setattr(stage2.v3, "_request_payload", lambda _job: payload)
    monkeypatch.setattr(stage2.v3, "_request_hash", lambda value: hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest())
    job = {"job_id": "case:1:sift_hybrid_stage2"}

    record = stage2.freeze_job_request(job)

    assert record == {"job_id": job["job_id"], "request": payload, "request_sha256": digest}
    assert stage2.verify_frozen_job_request(job, record) is payload


def test_frozen_request_verification_rejects_tampered_payload(monkeypatch):
    monkeypatch.setattr(stage2.v3, "_request_payload", lambda _job: {"messages": [{"content": "original"}]})
    monkeypatch.setattr(stage2.v3, "_request_hash", lambda value: hashlib.sha256(
        json.dumps(value, separators=(",", ":")).encode("utf-8")
    ).hexdigest())
    job = {"job_id": "case:1:sift_hybrid_stage2"}
    record = stage2.freeze_job_request(job)
    record["request"]["messages"][0]["content"] = "changed"

    with pytest.raises(stage2.Stage2Error, match="Frozen request payload changed"):
        stage2.verify_frozen_job_request(job, record)


def test_source_hash_closure_covers_request_and_receipt_helpers():
    expected = {
        "runner_sha256",
        "analyzer_sha256",
        "v3_analysis_sha256",
        "v3_gate_sha256",
        "matrix_candidate_sha256",
        "core_sha256",
        "v3_runner_sha256",
        "baseline_runner_sha256",
        "dataset_preparation_module_sha256",
        "minimax_renderer_module_sha256",
        "sift_package_init_sha256",
    }

    assert expected.issubset(stage2.SOURCE_PATHS)
    hashes = stage2.current_source_hashes()
    assert set(hashes) == expected
    assert all(len(digest) == 64 for digest in hashes.values())


def test_runtime_reproducibility_metadata_is_nonsecret_and_complete():
    metadata = stage2.runtime_reproducibility_metadata()

    assert set(metadata) == {
        "python_version",
        "python_implementation",
        "tokenizers_version",
        "requests_version",
        "platform",
    }
    assert metadata["python_version"]
    assert metadata["python_implementation"]
    assert metadata["tokenizers_version"]
    assert metadata["requests_version"]
    assert metadata["platform"]
    assert not any("key" in key.casefold() or "secret" in key.casefold() for key in metadata)


def _preflight_fixture(monkeypatch, tmp_path):
    payload = {
        "model": "minimax/minimax-m3",
        "messages": [{"role": "user", "content": "frozen prompt"}],
        "seed": 20261024,
    }
    monkeypatch.setattr(stage2.v3, "_request_payload", lambda _job: payload)
    monkeypatch.setattr(stage2.v3, "_request_hash", lambda value: hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest())
    job = {"job_id": "case:1:sift_hybrid_stage2"}
    record = stage2.freeze_job_request(job)
    expected_report = {
        "stage_manifest_sha256": "stage-hash",
        "baseline_manifest_sha256": "baseline-hash",
        "baseline_result_sha256": "result-hash",
        "source_hashes": {"runner_sha256": "source-hash"},
        "route_metadata": {"endpoint": "Minimax"},
        "budget": {"planned_requests": 1, "aggregate_exposure": {"passed": True}},
        "protocol": {"dispatch_job_ids": [job["job_id"]]},
        "runtime_reproducibility": {"python_version": "3.14"},
        "preparation": {
            "prepared_job_count": 1,
            "matrix_selected_job_count": 1,
            "matrix_fallback_job_count": 0,
            "max_projected_prompt_tokens": 128,
        },
        "prepared_jobs": [{
            "job_id": job["job_id"],
            "request_payload_sha256": job["request_payload_sha256"],
        }],
        "prepared_requests": [record],
    }
    artifact = {
        **expected_report,
        "status": "prepared_only_no_dispatch",
        "dry_run": True,
        "actual_dispatch_started": False,
        "samples": [],
    }
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path, job, expected_report, artifact


def test_preflight_verification_returns_request_objects_from_artifact(monkeypatch, tmp_path):
    path, job, expected_report, artifact = _preflight_fixture(monkeypatch, tmp_path)

    records = stage2.verify_preflight_artifact(path, jobs=[job], expected_report=expected_report)
    indexed = stage2.index_frozen_request_records(records)

    assert records[0]["request"] == job["request_payload"]
    assert indexed[job["job_id"]] is records[0]
    job["request_payload"] = indexed[job["job_id"]]["request"]
    assert job["request_payload"] is records[0]["request"]


@pytest.mark.parametrize("tamper", ["identity", "payload", "job_id"])
def test_preflight_verification_rejects_identity_or_request_mismatch(monkeypatch, tmp_path, tamper):
    path, job, expected_report, artifact = _preflight_fixture(monkeypatch, tmp_path)
    if tamper == "identity":
        artifact["source_hashes"] = {"runner_sha256": "different-source"}
    elif tamper == "payload":
        artifact["prepared_requests"][0]["request"]["messages"][0]["content"] = "changed"
    else:
        artifact["prepared_requests"][0]["job_id"] = "another-job"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(stage2.Stage2Error):
        stage2.verify_preflight_artifact(path, jobs=[job], expected_report=expected_report)
