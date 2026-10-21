from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
import run_longbench_v2_minimax_fresh_continuation as continuation  # noqa: E402


def _jobs(count: int = 2064) -> list[dict]:
    return [{"case_id": f"case-{i:04d}", "arm": "sift" if i % 2 else "full",
             "repeat": i % 3, "body_sha256": f"sha-{i:04d}",
             "body": {"max_tokens": 64}, "local_prompt_tokens": 1000,
             "projected_provider_prompt_tokens": 1500, "expected": "A",
             "domain": "synthetic", "sub_domain": "fixture"}
            for i in range(count)]


def _row(job: dict, index: int) -> dict:
    usage = None
    failure = "ConnectionError: simulated" if index == 22 else None
    if index < 22:
        # Sums to 1,165,100 prompt tokens and $0.34953 at the pinned rates.
        prompt = 52959 if index < 21 else 52961
        receipt = 0.00777856 if index < 21 else 0.00751848
        usage = {"prompt_tokens": prompt, "completion_tokens": 0, "is_byok": True,
                 "cost": 0, "cost_details": {"upstream_inference_cost": receipt}}
    return {"job_id": continuation._job_id(job), "case_id": job["case_id"],
            "arm": job["arm"], "repeat": job["repeat"],
            "request_body_sha256": job["body_sha256"], "usage": usage,
            "provider_reported_cost_usd": None, "http_status": None if index == 22 else 200,
            "failure": failure, "reserved_cost_usd": continuation.PREFIX_UNKNOWN_RESERVE_USD
            if index == 22 else 0.01}


def _prefix(jobs: list[dict]) -> dict:
    return {"status": "safety_guard_stopped", "completed_jobs": 23,
            "planned_jobs": 2064, "fresh_run_id": continuation.fresh.FRESH_RUN_ID,
            "fresh_manifest_canonical_sha256": continuation.fresh.FRESH_MANIFEST_CANONICAL_SHA256,
            "samples": [_row(job, i) for i, job in enumerate(jobs[:23])],
            "in_flight": {"index": 22, "job_id": continuation._job_id(jobs[22]),
                          "state": "unknown_outcome_requires_external_reconciliation",
                          "reserved_cost_usd": continuation.PREFIX_UNKNOWN_RESERVE_USD}}


def test_prefix_is_pinned_sequential_and_continuation_starts_after_unknown_job() -> None:
    jobs = _jobs()
    accounting = continuation.validate_prefix(_prefix(jobs), continuation.PREFIX_SHA256, jobs)
    assert accounting["completed_jobs"] == 23
    assert accounting["remaining_jobs"] == 2041
    assert accounting["continuation_start_index"] == 23
    assert accounting["receipt_count"] == 22
    assert accounting["receipt_usd"] == pytest.approx(0.17086824)
    assert accounting["token_rate_usd"] == pytest.approx(0.34953)
    assert accounting["budget_basis_usd"] == pytest.approx(0.34953)
    attempted = {row["job_id"] for row in _prefix(jobs)["samples"]}
    assert jobs[23]["case_id"] + ":" + jobs[23]["arm"] + ":" + str(jobs[23]["repeat"]) not in attempted


def test_prefix_hash_duplicate_and_frozen_body_mismatch_fail_closed() -> None:
    jobs = _jobs()
    with pytest.raises(continuation.ContinuationError, match="SHA-256"):
        continuation.validate_prefix(_prefix(jobs), "0" * 64, jobs)
    duplicate = _prefix(jobs)
    duplicate["samples"][1]["job_id"] = duplicate["samples"][0]["job_id"]
    with pytest.raises(continuation.ContinuationError, match="frozen unique schedule"):
        continuation.validate_prefix(duplicate, continuation.PREFIX_SHA256, jobs)
    mismatch = _prefix(jobs)
    mismatch["samples"][5]["request_body_sha256"] = "wrong"
    with pytest.raises(continuation.ContinuationError, match="frozen unique schedule"):
        continuation.validate_prefix(mismatch, continuation.PREFIX_SHA256, jobs)


def test_cost_arithmetic_is_uncached_and_reserve_covers_receipt_or_tokens() -> None:
    assert continuation._uncached_cost(853376, 85) == pytest.approx(0.2561148)
    assert continuation._uncached_cost(311296, 22) == pytest.approx(0.0934152)
    assert max(0.17086824, 0.34953) == pytest.approx(0.34953)
    assert continuation._job_reserve(_jobs(1)[0]) == pytest.approx(0.0005268)


def test_unknown_request_stays_reserved_and_is_never_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = _jobs(24)
    output = tmp_path / "continuation.json"
    monkeypatch.setattr(continuation, "OUTPUT_PATH", output)
    calls = 0

    def fail_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise requests.ConnectionError("simulated")

    report = {"spend_cap_usd": 100.0}
    live = {"input_usd_per_million": 0.30, "output_usd_per_million": 1.20,
            "endpoint_model_id": continuation.legacy.MODEL, "route_tag": "minimax/fp8",
            "max_prompt_tokens": 524288}
    result = continuation.dispatch_remaining(jobs, report, "test-key", live, post=fail_once)
    assert calls == 1
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["state"] == "failed_or_unknown_reserved"
    assert result["accounting"]["continuation_unknown_reserve_usd"] == pytest.approx(
        result["attempts"][0]["reserved_cost_usd"])
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["attempts"][0]["failure_class"] == "connection_or_timeout_unknown_outcome"
    assert "answer" not in saved["attempts"][0]
    assert "raw_sse_events" not in saved["attempts"][0]


def test_successful_sse_records_only_exact_choice_and_quality_metadata(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = _jobs(24)
    output = tmp_path / "success.json"
    monkeypatch.setattr(continuation, "OUTPUT_PATH", output)

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_lines(self, decode_unicode=True):
            events = [
                {"id": "resp-1", "provider": "Minimax", "model": continuation.legacy.MODEL,
                 "choices": [{"delta": {"content": "A"}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 1000, "completion_tokens": 1,
                           "is_byok": True, "cost": 0,
                           "cost_details": {"upstream_inference_cost": 0.00025}}},
            ]
            yield "data: " + json.dumps(events[0])
            yield "data: [DONE]"

    calls = 0

    def succeed_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response()

    live = {"input_usd_per_million": 0.30, "output_usd_per_million": 1.20,
            "endpoint_model_id": continuation.legacy.MODEL, "route_tag": "minimax/fp8",
            "max_prompt_tokens": 524288}
    result = continuation.dispatch_remaining(jobs, {"spend_cap_usd": 100.0}, "test-key", live,
                                             post=succeed_once)
    assert calls == 1
    row = result["attempts"][0]
    assert row["case_id"] == jobs[23]["case_id"]
    assert row["arm"] == jobs[23]["arm"]
    assert row["domain"] == jobs[23]["domain"]
    assert row["sub_domain"] == jobs[23]["sub_domain"]
    assert row["response_id"] == "resp-1"
    assert row["route_tag"] == "minimax/fp8"
    assert row["choice"] == "A"
    assert row["format_valid"] is True
    assert row["correct"] is True
    assert row["uncached_token_cost_usd"] == pytest.approx(0.0003012)
    assert row["provider_reported_cost_usd"] == pytest.approx(0.00025)
    assert row["budget_cost_usd"] == pytest.approx(0.0003012)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert "answer" not in saved["attempts"][0]
    assert "raw_sse_events" not in saved["attempts"][0]


def test_completion_usage_over_request_cap_stops_with_known_cost_persisted(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = _jobs(24)
    output = tmp_path / "over-cap.json"
    monkeypatch.setattr(continuation, "OUTPUT_PATH", output)

    class Response:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_lines(self, decode_unicode=True):
            chunk = {"id": "resp-over-cap", "provider": "Minimax",
                     "model": continuation.legacy.MODEL,
                     "choices": [{"delta": {"content": "A"}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 1000, "completion_tokens": 65,
                               "is_byok": True, "cost": 0,
                               "cost_details": {"upstream_inference_cost": 0.0003}}}
            yield "data: " + json.dumps(chunk)
            yield "data: [DONE]"

    live = {"input_usd_per_million": 0.30, "output_usd_per_million": 1.20,
            "endpoint_model_id": continuation.legacy.MODEL, "route_tag": "minimax/fp8",
            "max_prompt_tokens": 524288}
    result = continuation.dispatch_remaining(jobs, {"spend_cap_usd": 100.0}, "test-key", live,
                                             post=lambda *_a, **_k: Response())
    row = result["attempts"][0]
    assert result["status"] == "safety_guard_stopped"
    assert row["failure_class"] == "usage_completion_exceeds_request_cap"
    assert row["correct"] is False
    assert row["uncached_token_cost_usd"] == pytest.approx(0.000378)
    assert result["accounting"]["continuation_settled_budget_usd"] == pytest.approx(0.000378)
    assert result["accounting"]["continuation_unknown_reserve_usd"] == 0

