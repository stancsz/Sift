import sys
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

import continue_longbench_v2_minimax_hybrid_stage2 as continuation  # noqa: E402
import run_longbench_v2_minimax_relation_followup_v3 as v3  # noqa: E402


def _usage():
    return {
        "prompt_tokens": 100,
        "completion_tokens": 2,
        "cost": 0,
        "is_byok": True,
        "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "cost_details": {
            "upstream_inference_cost": 0.000031,
            "upstream_inference_prompt_cost": 0.000030,
            "upstream_inference_completions_cost": 0.000001,
        },
    }


def _record(job_id="case:1:sift_hybrid_stage2"):
    request = {"model": "minimax/minimax-m3", "messages": [{"role": "user", "content": "frozen"}]}
    digest = v3._request_hash(request)
    return {"job_id": job_id, "request": request, "request_sha256": digest}


def _job(record):
    return {
        "job_id": record["job_id"],
        "case_id": "case",
        "domain": "test",
        "expected": "A",
        "arm": "sift_hybrid_stage2",
        "repeat": 1,
        "selection_method": "default_sift",
        "matrix_candidate_attempted": False,
        "matrix_candidate_selected": False,
        "candidate_fallback_reason": None,
        "target_tokens": 32768,
        "request_payload_sha256": record["request_sha256"],
        "original_prompt_sha256": "prompt-hash",
        "local_rendered_prompt_tokens": 100,
        "projected_provider_prompt_tokens": 150,
    }


def _sample(record):
    usage = _usage()
    event = json.dumps({
        "id": "resp-1",
        "model": "minimax/minimax-m3",
        "provider": "Minimax",
        "usage": usage,
        "choices": [{"delta": {"content": '{"answer":"A"}'}, "finish_reason": "stop"}],
    })
    return {
        **_job(record),
        "request": record["request"],
        "request_sha256": record["request_sha256"],
        "http_status": 200,
        "answer": '{"answer":"A"}',
        "choice": "A",
        "valid_structured_choice": True,
        "finish_reason": "stop",
        "normal": True,
        "failure": None,
        "response_id": "resp-1",
        "model": "minimax/minimax-m3",
        "provider": "Minimax",
        "usage": usage,
        "receipt": usage,
        "cost_details": usage["cost_details"],
        "raw_sse_events": [event, "[DONE]"],
        "raw_response_body": event + "\n[DONE]",
        "answer_validity": "valid",
        "correct": True,
        "strict_sample_valid": True,
        "strict_receipt_valid": True,
        "cost_receipt_status": "reported",
        "cost_receipt_source": "max_upstream_or_openrouter_cost",
        "guard_charge_usd": 0.000031,
        "provider_local_input_token_ratio": 1.0,
    }


def test_checkpoint_validation_uses_unique_exact_requests_and_settles_receipts():
    record = _record()

    by_id, settled = continuation.validate_checkpoint_samples([record], [_sample(record)], [_job(record)])

    assert list(by_id) == [record["job_id"]]
    assert settled == pytest.approx(0.000031)


@pytest.mark.parametrize("bad_sample", ["duplicate", "request", "receipt", "ratio", "answer", "correctness", "case", "repeat", "missing_done"])
def test_checkpoint_validation_rejects_duplicate_or_malformed_evidence(bad_sample):
    record = _record()
    sample = _sample(record)
    samples = [sample]
    if bad_sample == "duplicate":
        samples.append(dict(sample))
    elif bad_sample == "request":
        sample["request"]["messages"][0]["content"] = "changed"
    elif bad_sample == "receipt":
        sample["usage"]["cost_details"]["upstream_inference_cost"] = 0
    elif bad_sample == "ratio":
        sample["local_rendered_prompt_tokens"] = 90
    elif bad_sample == "answer":
        sample["answer"] = '{"answer":"B"}'
    elif bad_sample == "correctness":
        sample["correct"] = False
    elif bad_sample == "case":
        sample["case_id"] = "other-case"
    elif bad_sample == "missing_done":
        sample["raw_sse_events"] = sample["raw_sse_events"][:-1]
        sample["raw_response_body"] = sample["raw_sse_events"][0]
    else:
        sample["repeat"] = 2

    with pytest.raises(continuation.ContinuationError):
        continuation.validate_checkpoint_samples([record], samples, [_job(record)])


def test_resume_budget_counts_settled_receipts_plus_only_missing_reservations():
    preflight = {
        "budget": {
            "run_ceiling_usd": 4,
            "input_price_usd_per_million": 0.30,
            "output_price_usd_per_million": 1.20,
            "aggregate_exposure": {
                "limit_usd": 20,
                "prior_actual_usd": 14.5,
                "prior_unsettled_usd": 0.2,
            },
        },
    }
    missing = [
        {"local_rendered_prompt_tokens": 100_000},
        {"local_rendered_prompt_tokens": 150_000},
    ]

    plan = continuation.continuation_budget(preflight, 0.75, missing)

    assert plan["settled_receipt_cost_usd"] == 0.75
    assert plan["remaining_request_count"] == 2
    assert plan["remaining_reserve_usd"] == pytest.approx(0.1128072)
    assert plan["run_limit_passed"] is True
    assert plan["aggregate_limit_passed"] is True


def test_resume_budget_stops_when_either_cap_would_be_exceeded():
    preflight = {
        "budget": {
            "run_ceiling_usd": 4,
            "input_price_usd_per_million": 0.30,
            "output_price_usd_per_million": 1.20,
            "aggregate_exposure": {
                "limit_usd": 20,
                "prior_actual_usd": 19.8,
                "prior_unsettled_usd": 0.1,
            },
        },
    }
    missing = [{"local_rendered_prompt_tokens": 100_000}]

    plan = continuation.continuation_budget(preflight, 3.99, missing)

    assert plan["run_limit_passed"] is False
    assert plan["aggregate_limit_passed"] is False


def test_checkpoint_must_be_a_dispatched_prefix():
    rows = [{"job_id": "a"}, {"job_id": "b"}]

    continuation.validate_dispatch_prefix(["a", "b", "c"], rows)
    with pytest.raises(continuation.ContinuationError, match="exact dispatched prefix"):
        continuation.validate_dispatch_prefix(["a", "b", "c"], [rows[0], {"job_id": "c"}])
    with pytest.raises(continuation.ContinuationError, match="exact dispatched prefix"):
        continuation.validate_dispatch_prefix(["a", "b", "c"], list(reversed(rows)))


def test_resume_refuses_ambiguous_in_flight_job():
    checkpoint = {
        "status": "in_progress",
        "dry_run": False,
        "actual_dispatch_started": True,
        "in_flight_request": {"job_id": "possibly-billed"},
        "budget": {"stop_reasons": []},
    }

    with pytest.raises(continuation.ContinuationError, match="ambiguous in-flight"):
        continuation.require_resumable_checkpoint(checkpoint)


def test_atomic_checkpoint_leaves_recoverable_complete_temp_after_replace_failure(monkeypatch, tmp_path):
    output = tmp_path / "resume.json"
    monkeypatch.setattr(continuation.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(continuation.os, "replace", lambda *_args: (_ for _ in ()).throw(PermissionError("locked")))

    with pytest.raises(continuation.ContinuationError, match="recovery JSON remains"):
        continuation._atomic_checkpoint(output, {"samples": [1, 2], "status": "in_progress"})

    recovery_files = list(tmp_path.glob(".resume.json.*.tmp"))
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text(encoding="utf-8")) == {
        "samples": [1, 2], "status": "in_progress",
    }


def _route_snapshot(tmp_path, *, provider="Minimax", model="minimax/minimax-m3",
                    prompt_price="0.0000003", status=0, supported=None):
    route = {
        "schema_version": 1,
        "checked_utc": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        "response_sha256": "a" * 64,
        "requested_model": "minimax/minimax-m3",
        "provider": provider,
        "provider_endpoint": "Minimax | minimax/minimax-m3-20260531",
        "endpoint_model_id": model,
        "context_length_tokens": 524288,
        "max_prompt_tokens": 524288,
        "max_completion_tokens": 512000,
        "pricing_usd_per_token": {
            "prompt": prompt_price,
            "completion": "0.0000012",
            "input_cache_read": "0.00000006",
            "discount": 0,
        },
        "status": status,
        "supported_parameters": supported or [
            "reasoning", "max_tokens", "temperature", "top_p", "response_format",
        ],
    }
    path = tmp_path / "fresh-route.json"
    path.write_text(json.dumps(route), encoding="utf-8")
    return path


def test_stale_frozen_route_accepts_fresh_snapshot_with_same_configuration(tmp_path):
    frozen = {
        "checked_utc": "2026-10-17T02:00:00+00:00",
        "validated_utc": "2026-10-17T02:00:01+00:00",
        "metadata_age_seconds": 1900,
        "metadata_path": "frozen-route.json",
        "metadata_sha256": "frozen-hash",
        "source_response_sha256": "b" * 64,
        "endpoint_name": "Minimax | minimax/minimax-m3-20260531",
        "provider_name": "Minimax",
        "model_id": "minimax/minimax-m3",
        "context_length": 524288,
        "max_prompt_tokens": 524288,
        "input_usd_per_million": 0.30,
        "output_usd_per_million": 1.20,
    }
    fresh_path = _route_snapshot(tmp_path)

    result = continuation.validate_fresh_route(fresh_path, frozen, tmp_path / "frozen-route.json", 0.30, 1.20)

    assert result["metadata"]["provider_name"] == "Minimax"
    assert result["status"] == 0
    assert "reasoning" in result["supported_parameters"]
    assert result["sha256"]
    assert result["validated_utc"]


@pytest.mark.parametrize("change", ["provider", "price", "model"])
def test_fresh_route_rejects_provider_price_or_model_drift(tmp_path, change):
    frozen = {
        "endpoint_name": "Minimax | minimax/minimax-m3-20260531",
        "provider_name": "Minimax",
        "model_id": "minimax/minimax-m3",
        "context_length": 524288,
        "max_prompt_tokens": 524288,
        "input_usd_per_million": 0.30,
        "output_usd_per_million": 1.20,
    }
    kwargs = {}
    if change == "provider":
        kwargs["provider"] = "Other"
    elif change == "price":
        kwargs["prompt_price"] = "0.0000004"
    else:
        kwargs["model"] = "minimax/another-model"
    fresh_path = _route_snapshot(tmp_path, **kwargs)

    with pytest.raises(continuation.ContinuationError):
        continuation.validate_fresh_route(fresh_path, frozen, tmp_path / "frozen-route.json", 0.30, 1.20)
