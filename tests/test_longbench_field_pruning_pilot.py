import json
import copy
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks import analyze_longbench_v2_minimax_field_pruning_pilot as analyzer
from benchmarks import run_longbench_v2_minimax_field_pruning_pilot as runner
from benchmarks.prepare_longbench_v2 import file_sha256


def _fake_prepared(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_source_hashes", lambda *a, **k: {
        "runner": "a" * 64, "analyzer": "b" * 64, "core": "c" * 64,
        "baseline_runner": "d" * 64, "v3_transport": "e" * 64,
        "dataset_preparer": "f" * 64, "renderer": "1" * 64,
        "baseline_manifest": "7" * 64, "offline_audit_script": "8" * 64,
        "dataset": "2" * 64, "tokenizer": "3" * 64, "template": "4" * 64,
        "offline_gate": "5" * 64,
    })
    monkeypatch.setattr(runner, "_validate_gate", lambda *a, **k: {
        "audit_body_sha256": "6" * 64,
    })
    monkeypatch.setattr(runner, "_validate_frozen_tokenizer_template", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_load_data", lambda path: {
        case_id: {"_id": case_id, "answer": "A", "question": "Question",
                  "context": "some context", "choice_A": "a", "choice_B": "b",
                  "choice_C": "c", "choice_D": "d"}
        for case_id in runner.CASE_IDS
    })
    class FakeTokenizer:
        def encode(self, text, add_special_tokens=False):
            return SimpleNamespace(ids=list(range(max(1, len(text) // 80))))
    monkeypatch.setattr(runner.Tokenizer, "from_file", lambda _: FakeTokenizer())
    monkeypatch.setattr(runner, "render_minimax", lambda messages: json.dumps(messages))
    monkeypatch.setattr(runner, "make_messages", lambda row: [
        {"role": "user", "content": row["context"] + row["question"]}
    ])
    def compact(messages, count, *, target, raw_limit, protocol, field_pruning):
        arm = "field_pruning_candidate" if field_pruning else "default_sift"
        return SimpleNamespace(messages=[dict(m) for m in messages],
                               audit={"method": arm, "forwarded_tokens": count(messages)})
    monkeypatch.setattr(runner, "compact_messages", compact)
    paths = [tmp_path / name for name in ("data.json", "tokenizer.json", "template.jinja", "gate.json")]
    for path in paths:
        path.write_text("fixture", encoding="utf-8")
    return runner.prepare(dataset=paths[0], tokenizer_path=paths[1], template_path=paths[2],
                          gate_path=paths[3], cli_seed=1234), paths


def test_prepare_freezes_36_exact_hash_bound_requests_and_paired_randomized_seeds(monkeypatch, tmp_path):
    first, paths = _fake_prepared(monkeypatch, tmp_path)
    second = runner.prepare(dataset=paths[0], tokenizer_path=paths[1], template_path=paths[2],
                            gate_path=paths[3], cli_seed=1234)
    assert first["status"] == "prepared_only_no_dispatch"
    assert first["actual_dispatch_started"] is False
    assert first["preparation"]["job_count"] == 36
    assert first["prepared_requests"] == second["prepared_requests"]
    assert first["config_sha256"] == second["config_sha256"]
    assert first["preparation"]["max_projected_prompt_tokens"] <= runner.PROVIDER_LIMIT
    by_job = {record["job_id"]: record for record in first["prepared_requests"]}
    for case_id in runner.CASE_IDS:
        for repeat in runner.REPEATS:
            block = [j for j in first["prepared_jobs"] if j["case_id"] == case_id and j["repeat"] == repeat]
            assert {j["arm"] for j in block} == set(runner.ARMS)
            assert len({j["generation_seed"] for j in block}) == 1
            assert len({j["arm_order_in_block"] for j in block}) == 3
            for job in block:
                request = by_job[job["job_id"]]["request"]
                assert set(request) == {
                    "model", "messages", "temperature", "top_p", "seed", "max_tokens",
                    "reasoning", "response_format", "stream", "stream_options", "provider",
                }
                assert request["seed"] == job["generation_seed"]
                assert runner.canonical_hash(request) == by_job[job["job_id"]]["request_sha256"]


def test_preflight_rejects_tampered_exact_request_hash(monkeypatch, tmp_path):
    artifact, paths = _fake_prepared(monkeypatch, tmp_path)
    artifact_path = tmp_path / "preflight.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert runner.verify_preflight(artifact_path)["status"] == "prepared_only_no_dispatch"
    artifact["prepared_requests"][0]["request"]["temperature"] = 9
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(runner.PilotError, match="hash mismatch"):
        runner.verify_preflight(artifact_path)


def test_preflight_binds_scoring_and_reserve_metadata(monkeypatch, tmp_path):
    artifact, _paths = _fake_prepared(monkeypatch, tmp_path)
    artifact_path = tmp_path / "preflight-metadata.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    artifact["prepared_jobs"][0]["expected"] = "D"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(runner.PilotError, match="prepared_jobs metadata digest mismatch"):
        runner.verify_preflight(artifact_path)


def test_preflight_digest_covers_frozen_preparation_timings(monkeypatch, tmp_path):
    artifact, _paths = _fake_prepared(monkeypatch, tmp_path)
    artifact_path = tmp_path / "preflight-preparation-time.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    artifact["prepared_jobs"][0]["preparation_ms"] += 1.0
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(runner.PilotError, match="prepared_jobs metadata digest mismatch"):
        runner.verify_preflight(artifact_path)


def test_candidate_fallback_or_error_aborts_preparation(monkeypatch, tmp_path):
    _artifact, paths = _fake_prepared(monkeypatch, tmp_path)
    def fallback(messages, count, *, target, raw_limit, protocol, field_pruning):
        return SimpleNamespace(messages=[dict(m) for m in messages],
                               audit={"method": "default_sift", "fallback": True})
    monkeypatch.setattr(runner, "compact_messages", fallback)
    with pytest.raises(runner.PilotError, match="silently fell back|Unexpected fallback"):
        runner.prepare(dataset=paths[0], tokenizer_path=paths[1], template_path=paths[2],
                       gate_path=paths[3], cli_seed=1234)


def _sse(answer, *, done=True, finish="stop", usage=None):
    events = [json.dumps({"choices": [{"delta": {"content": json.dumps({"answer": answer})},
                                       "finish_reason": finish}],
                         **({"usage": usage} if usage is not None else {})})]
    if done:
        events.append("[DONE]")
    return events


def _route_snapshot():
    return {"data": {
        "id": runner.MODEL,
        "endpoints": [{
            "model_id": runner.MODEL, "provider_name": "MiniMax", "name": "MiniMax M3",
            "context_length": runner.PROVIDER_LIMIT,
            "max_prompt_tokens": runner.PROVIDER_LIMIT,
            "pricing": {"prompt": "0.0000003", "completion": "0.0000012"},
        }],
    }}


@pytest.mark.parametrize("events", [
    _sse("A", done=False), _sse("A", finish="length"),
    ["not-json", "[DONE]"], _sse("A trailing"), _sse("E"), _sse(["A"]),
])
def test_raw_sse_rejects_truncated_malformed_and_non_ad(events):
    assert analyzer.parse_raw_sse(events) is None


def test_analyzer_requires_exact_36_pairs_and_scores_raw_sse_only(monkeypatch, tmp_path):
    artifact, paths = _fake_prepared(monkeypatch, tmp_path)
    preflight_path = tmp_path / "verified-preflight.json"
    preflight_path.write_text(json.dumps(artifact), encoding="utf-8")
    preflight = runner.verify_preflight(preflight_path)
    frozen_requests = {r["job_id"]: r for r in artifact["prepared_requests"]}
    jobs = {j["job_id"]: j for j in artifact["prepared_jobs"]}
    samples = []
    for case_id in analyzer.CASE_IDS:
        for repeat in analyzer.REPEATS:
            for arm in analyzer.ARMS:
                job_id = f"{case_id}:r{repeat}:{arm}"
                payload = frozen_requests[job_id]["request"]
                usage = {
                    "is_byok": True, "prompt_tokens": 100, "completion_tokens": 4,
                    "cost": 0.00095,
                    "prompt_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 0},
                    "cost_details": {
                        "upstream_inference_cost": 0.001,
                        "upstream_inference_prompt_cost": 0.0009,
                        "upstream_inference_completions_cost": 0.0001,
                    },
                }
                reconstructed = (100 * 0.3 + 4 * 1.2) / 1_000_000
                request_started = datetime.now(timezone.utc)
                response_completed = request_started + timedelta(milliseconds=200)
                samples.append({
                    "case_id": case_id, "repeat": repeat, "arm": arm,
                    "job_id": job_id, "expected": jobs[job_id]["expected"],
                    "local_rendered_prompt_tokens": jobs[job_id]["local_rendered_prompt_tokens"],
                    "preparation_ms": jobs[job_id]["preparation_ms"], "request": payload,
                    "request_sha256": analyzer.canonical_hash(payload),
                    "http_status": 200, "model": analyzer.MODEL, "provider": "minimax",
                    "raw_sse_events": _sse("A" if repeat < 3 else "B", usage=usage),
                    "usage": usage,
                    "cost_receipt_status": "reported",
                    "cost_receipt_source": "max_upstream_or_openrouter_cost",
                    "cost_usd": 0.001, "ttft_ms": 30,
                    "completion_tokens_per_second": 20,
                    "request_started_utc": request_started.isoformat(),
                    "response_completed_utc": response_completed.isoformat(),
                    "end_to_end_ms": 200,
                    "uncached_cost_rate_basis": {
                        "input_usd_per_million": 0.3, "output_usd_per_million": 1.2,
                    },
                    "token_receipt_reconciled": True,
                    "reconstructed_uncached_cost_usd": reconstructed,
                })
    route_snapshot = _route_snapshot()
    route_snapshot_sha256 = hashlib.sha256(json.dumps(route_snapshot, sort_keys=True).encode()).hexdigest()
    report = {"status": "complete", "actual_dispatch_started": True,
              "preflight_sha256": file_sha256(preflight_path),
              "route_snapshot_sha256": route_snapshot_sha256,
              "route_snapshot": route_snapshot,
              "route": {"endpoint_name": "MiniMax M3",
                        "input_usd_per_million": 0.3, "output_usd_per_million": 1.2,
                        "context_length": runner.PROVIDER_LIMIT,
                        "max_prompt_tokens": runner.PROVIDER_LIMIT,
                        "checked_utc": datetime.now(timezone.utc).isoformat()},
              "samples": samples}
    result = analyzer.analyze(report, preflight, file_sha256(preflight_path))
    assert result["pooled"]["field_pruning"]["exact_correct"] == 8
    assert result["per_task"]["field_pruning"][analyzer.CASE_IDS[0]]["majority_correct"] is True
    assert result["pooled"]["field_pruning"]["preprocessing_ms_total"] == pytest.approx(
        sum(j["preparation_ms"] for j in jobs.values() if j["arm"] == "field_pruning")
    )
    assert result["pooled"]["field_pruning"]["reconstructed_uncached_cost_usd_total"] == pytest.approx(
        12 * (100 * 0.3 + 4 * 1.2) / 1_000_000
    )
    tampered_observed = copy.deepcopy(report)
    tampered_observed["samples"][0]["cost_usd"] += 0.01
    with pytest.raises(analyzer.AnalysisError, match="Observed cost does not reconcile"):
        analyzer.analyze(tampered_observed, preflight, file_sha256(preflight_path))
    tampered_uncached = copy.deepcopy(report)
    tampered_uncached["samples"][0]["reconstructed_uncached_cost_usd"] += 0.01
    with pytest.raises(analyzer.AnalysisError, match="Reconstructed uncached cost"):
        analyzer.analyze(tampered_uncached, preflight, file_sha256(preflight_path))
    tampered_route = copy.deepcopy(report)
    tampered_route["route"]["input_usd_per_million"] = 0.31
    with pytest.raises(analyzer.AnalysisError, match="Normalized live route fields"):
        analyzer.analyze(tampered_route, preflight, file_sha256(preflight_path))
    tampered_raw = copy.deepcopy(report)
    tampered_raw["route_snapshot"]["data"]["endpoints"][0]["pricing"]["prompt"] = "0.00000031"
    with pytest.raises(analyzer.AnalysisError, match="does not match route_snapshot_sha256"):
        analyzer.analyze(tampered_raw, preflight, file_sha256(preflight_path))
    tampered_raw_rehashed = copy.deepcopy(tampered_raw)
    tampered_raw_rehashed["route_snapshot_sha256"] = hashlib.sha256(
        json.dumps(tampered_raw_rehashed["route_snapshot"], sort_keys=True).encode()
    ).hexdigest()
    with pytest.raises(analyzer.AnalysisError, match="Normalized live route fields"):
        analyzer.analyze(tampered_raw_rehashed, preflight, file_sha256(preflight_path))
    tampered_hash = copy.deepcopy(report)
    tampered_hash["route_snapshot_sha256"] = "0" * 64
    with pytest.raises(analyzer.AnalysisError, match="does not match route_snapshot_sha256"):
        analyzer.analyze(tampered_hash, preflight, file_sha256(preflight_path))
    tampered_normalized = copy.deepcopy(report)
    tampered_normalized["route"]["max_prompt_tokens"] -= 1
    with pytest.raises(analyzer.AnalysisError, match="Normalized live route fields"):
        analyzer.analyze(tampered_normalized, preflight, file_sha256(preflight_path))
    tampered_timing = copy.deepcopy(report)
    tampered_timing["samples"][0]["preparation_ms"] += 0.01
    with pytest.raises(analyzer.AnalysisError, match="metadata or body differs"):
        analyzer.analyze(tampered_timing, preflight, file_sha256(preflight_path))
    tampered_duration = copy.deepcopy(report)
    tampered_duration["samples"][0]["end_to_end_ms"] = 9999
    with pytest.raises(analyzer.AnalysisError, match="does not reconcile with timestamps"):
        analyzer.analyze(tampered_duration, preflight, file_sha256(preflight_path))
    samples[0]["expected"] = "D"
    with pytest.raises(analyzer.AnalysisError, match="differs from the verified preflight"):
        analyzer.analyze(report, preflight, file_sha256(preflight_path))
    samples.pop()
    samples[0]["expected"] = "A"
    with pytest.raises(analyzer.AnalysisError, match="exactly 36"):
        analyzer.analyze(report, preflight, file_sha256(preflight_path))


def test_stale_or_excess_budget_stops_before_any_completion_request(monkeypatch, tmp_path):
    artifact, paths = _fake_prepared(monkeypatch, tmp_path)
    preflight = tmp_path / "preflight.json"
    preflight.write_text(json.dumps(artifact), encoding="utf-8")
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps({
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "actual_usd": 20, "unsettled_usd": 0,
    }), encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(runner, "_live_endpoint", lambda key: ({}, {
        "input_usd_per_million": 0.3, "output_usd_per_million": 1.2,
        "context_length": runner.PROVIDER_LIMIT, "max_prompt_tokens": runner.PROVIDER_LIMIT,
    }))
    def forbidden_post(*a, **k):
        raise AssertionError("budget gate must prevent any completion request")
    monkeypatch.setattr(runner, "_call", forbidden_post)
    with pytest.raises(runner.PilotError, match="exceeds pilot budget"):
        runner.dispatch(preflight_path=preflight, expected_preflight_sha256=file_sha256(preflight),
                        output_path=tmp_path / "result.json",
                        budget_ledger_path=ledger_path)


def test_budget_ledger_staleness_is_rejected(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"checked_utc": "2020-01-01T00:00:00+00:00",
                                "actual_usd": 0, "unsettled_usd": 0}), encoding="utf-8")
    with pytest.raises(runner.PilotError, match="within 30 minutes"):
        runner._load_budget_ledger(path)


def test_budget_projection_reserves_every_unsent_request_under_both_caps():
    passing = runner._budget_projection(
        prior_actual=16.0, prior_unsettled=0.1, actual_run_cost=3.0,
        remaining_reserves=[0.25, 0.25],
    )
    assert passing["run_passed"] is True
    assert passing["aggregate_passed"] is True
    run_fail = runner._budget_projection(
        prior_actual=0, prior_unsettled=0, actual_run_cost=3.75,
        remaining_reserves=[0.30, 0.01],
    )
    assert run_fail["run_passed"] is False
    aggregate_fail = runner._budget_projection(
        prior_actual=19.4, prior_unsettled=0.1, actual_run_cost=0.2,
        remaining_reserves=[0.2, 0.2],
    )
    assert aggregate_fail["aggregate_passed"] is False


def test_midstream_failure_stops_before_dispatching_next_request(monkeypatch, tmp_path):
    artifact, paths = _fake_prepared(monkeypatch, tmp_path)
    preflight = tmp_path / "preflight-midstream.json"
    preflight.write_text(json.dumps(artifact), encoding="utf-8")
    ledger = tmp_path / "fresh-ledger.json"
    ledger.write_text(json.dumps({
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "actual_usd": 0, "unsettled_usd": 0,
    }), encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(runner, "_live_endpoint", lambda _key: ({}, {
        "input_usd_per_million": 0.3, "output_usd_per_million": 1.2,
        "context_length": runner.PROVIDER_LIMIT, "max_prompt_tokens": runner.PROVIDER_LIMIT,
    }))
    calls = []
    def broken_stream(_request, _key):
        calls.append(1)
        return {
            "http_status": 200, "failure": "read timeout",
            "stream_complete": False, "model": runner.MODEL, "provider": "minimax",
            "usage": {"is_byok": True, "prompt_tokens": 10, "completion_tokens": 1,
                      "cost": 0.0, "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                      "cost_details": {"upstream_inference_cost": 0.00001,
                                       "upstream_inference_prompt_cost": 0.000009,
                                       "upstream_inference_completions_cost": 0.000001}},
            "raw_sse_events": [], "end_to_end_ms": 1.0, "ttft_ms": None,
            "completion_tokens_per_second": None,
        }
    monkeypatch.setattr(runner, "_call", broken_stream)
    result = runner.dispatch(preflight_path=preflight,
                            expected_preflight_sha256=file_sha256(preflight),
                            output_path=tmp_path / "result.json",
                            budget_ledger_path=ledger)
    assert len(calls) == 1
    assert result["status"] == "strict_gate_stopped"
    assert len(result["samples"]) == 1
    assert len(result["not_started_jobs"]) == 35


def test_preflight_hash_mismatch_stops_before_route_or_completion_lookup(monkeypatch, tmp_path):
    artifact, _paths = _fake_prepared(monkeypatch, tmp_path)
    preflight = tmp_path / "preflight-hash-check.json"
    preflight.write_text(json.dumps(artifact), encoding="utf-8")
    ledger = tmp_path / "fresh-ledger.json"
    ledger.write_text(json.dumps({
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "actual_usd": 0, "unsettled_usd": 0,
    }), encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    def forbidden_lookup(*_args, **_kwargs):
        raise AssertionError("mismatched preflight must stop before endpoint lookup")
    monkeypatch.setattr(runner, "_live_endpoint", forbidden_lookup)
    monkeypatch.setattr(runner, "_call", forbidden_lookup)
    with pytest.raises(runner.PilotError, match="Preflight file SHA-256 differs"):
        runner.dispatch(
            preflight_path=preflight, expected_preflight_sha256="0" * 64,
            output_path=tmp_path / "hash-mismatch-result.json",
            budget_ledger_path=ledger,
        )
