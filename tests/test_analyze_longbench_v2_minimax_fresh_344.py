"""Only synthetic evidence is used; no private run files or inference."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import shutil

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
import analyze_longbench_v2_minimax_fresh_344 as analyzer


def encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.fixture
def evidence(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    cases, jobs, schedule, rows = [], [], [], []
    for task in range(344):
        local = 136879 if task == 3 else (60000 if task < 4 else 1000)
        cases.append({"id": f"synthetic-private-case-{task}", "answer_key": "A",
                      "full_local_prompt_tokens": local, "sift_local_prompt_tokens": local})
        for arm in analyzer.ARMS:
            for repeat in range(3):
                i = len(jobs)
                body_sha = hashlib.sha256(f"synthetic body {i}".encode()).hexdigest()
                job = {"case_id": cases[-1]["id"], "arm": arm, "repeat": repeat,
                       "canonical_request_body_sha256": body_sha}
                jobs.append(job)
                schedule.append({"index": i, "case_id": job["case_id"], "arm": arm, "repeat": repeat,
                                 "local_prompt_tokens": local, "body_sha256": body_sha})
                row = {**schedule[-1], "job_id": analyzer._id(job), "request_body_sha256": body_sha,
                       "requested_model": analyzer.MODEL, "returned_model": analyzer.MODEL,
                       "provider": "Minimax", "response_id": f"synthetic-private-response-{i}",
                       "expected": "A", "choice": "A", "correct": True, "finish_reason": "stop",
                       "request_started_utc": "2026-10-20T00:00:00+00:00",
                       "response_completed_utc": "2026-10-20T00:00:01+00:00",
                       "started_utc": "2026-10-21T00:00:00+00:00",
                       "finished_utc": "2026-10-21T00:00:01+00:00",
                       "http_status": 200, "sse_done_received": True,
                       "reserved_cost_usd": (local * 1.5 * .3 + 64 * 1.2) / 1_000_000}
                if i < 22:
                    prompt = 52959 if i < 21 else 52961
                    receipt = .00777856 if i < 21 else .00751848
                    usage = {"prompt_tokens": prompt, "completion_tokens": 0, "is_byok": True,
                             "cost": 0, "cost_details": {"upstream_inference_cost": receipt}}
                    row.update({"usage": usage, "provider_reported_cost_usd": receipt, "answer": "A",
                                "failure": None, "raw_sse_events": [json.dumps({"id": row["response_id"],
                                    "provider": "Minimax", "model": analyzer.MODEL, "usage": usage,
                                    "choices": [{"delta": {"content": "A"}, "finish_reason": "stop"}]}), "[DONE]"]})
                elif i == 22:
                    row.update({"usage": None, "provider_reported_cost_usd": None,
                                "http_status": None, "correct": False, "choice": None,
                                "failure": "ConnectionError: private diagnostic must not leak"})
                else:
                    row.update({"state": "complete", "endpoint_model_id": analyzer.MODEL,
                                "route_tag": "minimax/fp8", "format_valid": True,
                                "prompt_tokens": 1000, "completion_tokens": 1,
                                "uncached_token_cost_usd": .0003012,
                                "provider_reported_cost_usd": .0002 if i % 2 else None,
                                "budget_cost_usd": .0003012})
                rows.append(row)
    schedule_sha = analyzer.paired.canonical_hash(jobs)
    monkeypatch.setattr(analyzer, "SCHEDULE_SHA", schedule_sha)
    base = {"status": "prepared_only_no_dispatch", "dispatch_authorized": False,
            "cohort_summary": {"schedule_sha256": schedule_sha}, "cases": cases, "jobs": jobs}
    base_sha = digest(encode(base))
    monkeypatch.setattr(analyzer, "BASE_SHA", base_sha)
    fresh = {"schema": "sift.longbench.minimax.fresh344.v1", "run_id": analyzer.RUN_ID,
             "status": "prepared_only_no_dispatch", "dispatch_authorized": False,
             "base_manifest_sha256": base_sha, "schedule_sha256": schedule_sha}
    fresh_sha = analyzer.paired.canonical_hash(fresh)
    monkeypatch.setattr(analyzer, "FRESH_SHA", fresh_sha)
    route = {"provider": "Minimax", "endpoint_model_id": analyzer.MODEL, "route_tag": "minimax/fp8",
             "max_prompt_tokens": 524288, "max_completion_tokens": 512000,
             "input_usd_per_million": .3, "output_usd_per_million": 1.2}
    prefix = {"status": "safety_guard_stopped", "actual_dispatch_started": True,
              "completed_jobs": 23, "planned_jobs": 2064, "fresh_run_id": analyzer.RUN_ID,
              "fresh_manifest_canonical_sha256": fresh_sha, "manifest_sha256": base_sha,
              "schedule": schedule, "schedule_sha256": analyzer.paired.canonical_hash(schedule),
              "samples": rows[:23], "live_route_validation": route,
              "settled_actual_cost_usd": analyzer.PREFIX_RECEIPTS,
              "in_flight": {"index": 22, "job_id": rows[22]["job_id"],
                            "state": "unknown_outcome_requires_external_reconciliation",
                            "reserved_cost_usd": analyzer.PREFIX_RESERVE}}
    prefix_sha = digest(encode(prefix))
    monkeypatch.setattr(analyzer, "PREFIX_SHA", prefix_sha)
    suffix_own = 2041 * .0003012
    suffix = {"continuation_id": analyzer.CONTINUATION_ID, "status": "completed",
              "actual_dispatch_started": True, "in_flight": None, "stop_reason": None,
              "started_utc": "2026-10-21T00:00:00+00:00",
              "finished_utc": "2026-10-21T00:00:00+00:00", "prefix_sha256": prefix_sha,
              "prefix_sha256_verified": True, "manifest_canonical_sha256": fresh_sha,
              "prefix_completed_jobs": 23, "remaining_jobs": 2041, "live_route_validation": route,
              "attempts": rows[23:], "prefix_receipts": 22,
              "prefix_receipt_cost_usd": analyzer.PREFIX_RECEIPTS,
              "prefix_uncached_token_cost_usd": analyzer.PREFIX_OWN,
              "prefix_budget_basis_usd": analyzer.PREFIX_OWN,
              "historical_unknown_reserve_usd": analyzer.HISTORICAL_RESERVE,
              "stopped_request_reserve_usd": analyzer.PREFIX_RESERVE,
              # main() records the initial suffix reserve here. dispatch_remaining()
              # updates only the nested final accounting remainder at completion.
              "cap_usd": 100, "spend_cap_usd": 100,
              "remaining_worst_case_reserve_usd": round(sum(row["reserved_cost_usd"] for row in rows[23:]), 8),
              "total_coverage_usd": analyzer.HISTORICAL_RESERVE + analyzer.PREFIX_RESERVE + analyzer.PREFIX_OWN
                  + sum(row["reserved_cost_usd"] for row in rows[23:]),
              "accounting": {"historical_reserve_usd": analyzer.HISTORICAL_RESERVE,
                  "stopped_prefix_unknown_reserve_usd": analyzer.PREFIX_RESERVE,
                  "stopped_prefix_budget_basis_usd": analyzer.PREFIX_OWN,
                  "continuation_settled_budget_usd": suffix_own,
                  "continuation_uncached_token_cost_usd": suffix_own,
                  "continuation_unknown_reserve_usd": 0, "remaining_worst_case_reserve_usd": 0}}
    return [fresh, base, prefix, suffix]


def analyze(evidence: list[dict]) -> dict:
    return analyzer.analyze(*(encode(value) for value in evidence), bootstrap_samples=200)


def repin_prefix(evidence: list[dict], monkeypatch: pytest.MonkeyPatch) -> None:
    value = digest(encode(evidence[2]))
    monkeypatch.setattr(analyzer, "PREFIX_SHA", value)
    evidence[3]["prefix_sha256"] = value


def test_complete_schedule_quality_costs_and_no_private_values(evidence: list[dict]) -> None:
    result = analyze(evidence)
    assert result["coverage"] == {"scheduled_tasks": 344, "scheduled_attempts": 2064,
        "prefix_attempts": 23, "continuation_attempts": 2041, "confirmed_response_attempts": 2063,
        "unknown_or_failed_attempts": 1, "complete_paired_six_request_tasks": 343, "incomplete_paired_tasks": 1}
    quality = result["quality"]["all_scheduled_unknowns_counted_incorrect"]
    assert quality["arms"]["sift"]["request_accuracy"] == pytest.approx(1031 / 1032)
    assert quality["arms"]["full"]["request_accuracy"] == 1
    assert quality["arms"]["sift"]["task_majority_accuracy"] == 1
    assert quality["request_accuracy_sift_minus_full"]["n_tasks"] == 344
    assert result["quality"]["complete_paired_observed_tasks"]["arms"]["sift"]["requests"] == 1029
    cost = result["usage_and_cost"]
    assert cost["own_uncached_total_usd"] == pytest.approx(.34953 + 2041 * .0003012)
    assert cost["provider_reported_total_usd"] == pytest.approx(.17086824 + 1021 * .0002)
    assert cost["current_run_unknown_held_reserve_usd"] == pytest.approx(.06167235)
    assert cost["historical_held_reserve_usd"] == pytest.approx(2.0457216)
    public = json.dumps(result)
    for token in ("synthetic-private", "private diagnostic", '"choice"', '"expected"', '"answer_key"', '"job_id"'):
        assert token not in public
    assert "runner-recorded" in public
    assert "not_blind_holdout" in result["evidence_class"]


@pytest.mark.parametrize("mutation", [
    lambda x: x[3].update(status="dispatching"),
    lambda x: x[3].update(in_flight={"state": "request_started"}),
    lambda x: x[3]["attempts"].pop(),
    lambda x: x[3]["attempts"].reverse(),
    lambda x: x[3]["attempts"].__setitem__(1, copy.deepcopy(x[3]["attempts"][0])),
    lambda x: x[3]["attempts"][0].update(request_body_sha256="0" * 64),
    lambda x: x[3]["attempts"][0].update(expected="D"),
    lambda x: x[3]["attempts"][0].update(correct=False),
    lambda x: x[3]["attempts"][0].update(choice="bad private output"),
    lambda x: x[3]["attempts"][0].update(format_valid=False),
    lambda x: x[3]["attempts"][0].update(response_id=x[3]["attempts"][1]["response_id"]),
    lambda x: x[3]["attempts"][0].update(provider="other"),
    lambda x: x[3]["attempts"][0].update(returned_model="other"),
    lambda x: x[3]["attempts"][0].update(route_tag="other"),
    lambda x: x[3]["attempts"][0].update(sse_done_received=False),
    lambda x: x[3]["attempts"][0].update(completion_tokens=65),
    lambda x: x[3]["attempts"][0].update(prompt_tokens=True),
    lambda x: x[3]["attempts"][0].update(provider_reported_cost_usd=-1),
    lambda x: x[3]["attempts"][0].update(uncached_token_cost_usd=.001),
    lambda x: x[3]["attempts"][0].update(budget_cost_usd=.001),
    lambda x: x[3]["accounting"].update(continuation_settled_budget_usd=2),
    lambda x: x[3]["accounting"].update(continuation_unknown_reserve_usd=2),
    lambda x: x[3].update(prefix_sha256="0" * 64),
    lambda x: x[3]["live_route_validation"].update(input_usd_per_million=.4),
    lambda x: x[3]["live_route_validation"].update(max_completion_tokens=64),
    lambda x: x[3]["attempts"][0].update(finished_utc="private bad timestamp"),
    lambda x: x[3].update(total_coverage_usd=0),
    lambda x: x[3].update(remaining_worst_case_reserve_usd=0),
    lambda x: x[3]["accounting"].update(remaining_worst_case_reserve_usd=.1),
])
def test_malformed_replayed_partial_or_misaccounted_data_rejected(evidence: list[dict], mutation) -> None:
    mutation(evidence)
    with pytest.raises(analyzer.AnalysisError) as error:
        analyze(evidence)
    assert "synthetic-private" not in str(error.value)
    assert "bad private output" not in str(error.value)


def test_unknown_continuation_retained_in_coverage_and_reserves(evidence: list[dict]) -> None:
    suffix = evidence[3]
    row = suffix["attempts"][50]
    for key in ("budget_cost_usd", "uncached_token_cost_usd", "provider_reported_cost_usd",
                "prompt_tokens", "completion_tokens", "correct", "choice", "format_valid", "finish_reason",
                "sse_done_received", "provider", "returned_model", "response_id"):
        row.pop(key, None)
    row.update(state="failed_or_unknown_reserved", failure_class="connection_or_timeout_unknown_outcome")
    suffix["status"] = "completed_with_failures"
    suffix["accounting"]["continuation_settled_budget_usd"] -= .0003012
    suffix["accounting"]["continuation_uncached_token_cost_usd"] -= .0003012
    suffix["accounting"]["continuation_unknown_reserve_usd"] = row["reserved_cost_usd"]
    result = analyze(evidence)
    assert result["coverage"]["unknown_or_failed_attempts"] == 2
    assert result["coverage"]["complete_paired_six_request_tasks"] == 342
    assert result["usage_and_cost"]["current_run_unknown_held_reserve_usd"] == pytest.approx(
        analyzer.PREFIX_RESERVE + row["reserved_cost_usd"])


def test_actual_dispatch_final_schema_retains_initial_top_level_reserve(
        evidence: list[dict], monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Use the real producer with synthetic responses and zero file/network IO."""
    import run_longbench_v2_minimax_fresh_continuation as producer

    jobs = []
    for frozen in evidence[1]["jobs"]:
        case = next(case for case in evidence[1]["cases"] if case["id"] == frozen["case_id"])
        jobs.append({**frozen, "body_sha256": frozen["canonical_request_body_sha256"],
                     "body": {}, "local_prompt_tokens": case[f"{frozen['arm']}_local_prompt_tokens"],
                     "expected": case["answer_key"]})

    class SyntheticResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    calls = 0

    def read_synthetic_stream(_response):
        nonlocal calls
        calls += 1
        return {"provider": "Minimax", "returned_model": analyzer.MODEL,
                "response_id": f"synthetic-dispatch-response-{calls}", "choice": "A",
                "format_valid": True, "finish_reason": "stop", "sse_done_received": True,
                "usage": {"prompt_tokens": 1000, "completion_tokens": 1}}

    monkeypatch.setattr(producer, "_write_report", lambda *_args: None)
    monkeypatch.setattr(producer, "_read_sse", read_synthetic_stream)
    report = copy.deepcopy(evidence[3])
    initial_reserve = producer._remaining_reserve(jobs[23:])
    evidence[3] = producer.dispatch_remaining(jobs, report, "synthetic-unused-key",
                                             report["live_route_validation"],
                                             post=lambda *_args, **_kwargs: SyntheticResponse())
    assert calls == 2041
    assert evidence[3]["status"] == "completed"
    assert evidence[3]["remaining_worst_case_reserve_usd"] == pytest.approx(initial_reserve)
    assert evidence[3]["accounting"]["remaining_worst_case_reserve_usd"] == pytest.approx(0, abs=1e-8)
    assert analyze(evidence)["coverage"]["scheduled_attempts"] == 2064
    assert "synthetic-dispatch-response" not in capsys.readouterr().out

    evidence[3]["remaining_worst_case_reserve_usd"] = 0
    with pytest.raises(analyzer.AnalysisError, match="reconcile"):
        analyze(evidence)
    evidence[3]["remaining_worst_case_reserve_usd"] = initial_reserve
    evidence[3]["accounting"]["remaining_worst_case_reserve_usd"] = .1
    with pytest.raises(analyzer.AnalysisError, match="reconcile"):
        analyze(evidence)


def test_invalid_answer_is_an_observed_incorrect_response(evidence: list[dict]) -> None:
    evidence[3]["attempts"][0].update(choice=None, format_valid=False, correct=False)
    result = analyze(evidence)
    assert result["coverage"]["confirmed_response_attempts"] == 2063
    assert result["coverage"]["complete_paired_six_request_tasks"] == 343


def test_prefix_reparse_detects_inconsistent_choice_even_with_test_repin(evidence: list[dict], monkeypatch) -> None:
    evidence[2]["samples"][0]["answer"] = "B"
    repin_prefix(evidence, monkeypatch)
    with pytest.raises(analyzer.AnalysisError, match="stream"):
        analyze(evidence)


def test_pins_cannot_be_replaced_with_an_unrelated_same_shape_run(evidence: list[dict]) -> None:
    evidence[2]["samples"][0]["correct"] = False
    with pytest.raises(analyzer.AnalysisError, match="pin mismatch"):
        analyze(evidence)
    with pytest.raises(analyzer.AnalysisError):
        analyzer.analyze(b'{"secret":1,"secret":2}', *(encode(x) for x in evidence[1:]), bootstrap_samples=200)


def test_cli_writes_only_aggregate_and_refuses_overwrite(evidence: list[dict], tmp_path: Path, capsys) -> None:
    args = []
    for name, value in zip(("fresh-manifest", "base-manifest", "prefix", "continuation"), evidence):
        path = tmp_path / f"{name}.json"
        path.write_bytes(encode(value))
        args += [f"--{name}", str(path)]
    output = tmp_path / "aggregate.json"
    args += ["--output", str(output), "--bootstrap-samples", "200"]
    assert analyzer.main(args) == 0
    assert "synthetic-private" not in output.read_text()
    assert "synthetic-private" not in capsys.readouterr().out
    with pytest.raises(analyzer.AnalysisError, match="exclusively"):
        analyzer.main(args)


def _assert_real_manifest_pins_and_order(root: Path) -> None:
    fresh = json.loads((root / "docs/evals/longbench-v2-minimax-fresh-344-manifest-2026-10-20.json").read_bytes())
    base_bytes = (root / "docs/evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json").read_bytes()
    base = json.loads(base_bytes)
    assert analyzer.paired.canonical_hash(fresh) == analyzer.FRESH_SHA
    assert digest(base_bytes) == analyzer.BASE_SHA
    assert analyzer.paired.canonical_hash(base["jobs"]) == analyzer.SCHEDULE_SHA
    assert len(base["jobs"]) == 2064
    assert len(base["cases"]) == 344


def test_real_tracked_manifest_pins_and_order_are_self_consistent() -> None:
    _assert_real_manifest_pins_and_order(Path(__file__).resolve().parents[1])


@pytest.mark.parametrize("autocrlf", ["false", "true"])
def test_frozen_manifest_checkout_pin_is_independent_of_autocrlf(tmp_path: Path, autocrlf: str) -> None:
    """Exercise Git checkout conversion on this host; not an OS-emulation test."""
    if shutil.which("git") is None:
        pytest.skip("Git is required for the checkout materialization regression")
    root = Path(__file__).resolve().parents[1]
    relative = "docs/evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json"
    fresh_relative = "docs/evals/longbench-v2-minimax-fresh-344-manifest-2026-10-20.json"
    blob = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=root)
    assert digest(blob) == "1277778a0c1375bb50cb773e7cf983d4d72f47097f2eda14be6078b8f4859acb"
    assert b"\r\n" not in blob
    # A tiny commit-free repository/index gives real checkout behavior without
    # changing the parent repository's index, configuration, or frozen manifest.
    repository = tmp_path / "isolated-index"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True, capture_output=True)
    (repository / ".gitattributes").write_bytes((root / ".gitattributes").read_bytes())
    for path, body in ((relative, blob), (fresh_relative, (root / fresh_relative).read_bytes())):
        destination = repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-c", f"core.autocrlf={autocrlf}",
            "-c", "core.safecrlf=false", "-C", str(repository), *args], stderr=subprocess.PIPE)

    git("add", "--", ".gitattributes", relative, fresh_relative)
    assert git("show", f":{relative}") == blob  # The tracked object remains LF.
    without_rule_sha = None
    if autocrlf == "false":
        attributes = (repository / ".gitattributes").read_bytes()
        exact_rule = f"{relative} text eol=crlf".encode()
        (repository / ".gitattributes").write_bytes(b"\n".join(
            line for line in attributes.splitlines() if line != exact_rule) + b"\n")
        git("add", "--", ".gitattributes")
        control = tmp_path / "without-rule-checkout"
        control.mkdir()
        git("checkout-index", "--all", "--force", f"--prefix={control.as_posix()}/")
        without_rule_sha = digest((control / relative).read_bytes())
        assert without_rule_sha == digest(blob) != analyzer.BASE_SHA
        (repository / ".gitattributes").write_bytes(attributes)
        git("add", "--", ".gitattributes")
    checkout = tmp_path / "materialized-checkout"
    checkout.mkdir()
    git("checkout-index", "--all", "--force", f"--prefix={checkout.as_posix()}/")
    materialized = (checkout / relative).read_bytes()
    assert materialized == blob.replace(b"\n", b"\r\n")
    assert digest(materialized) == analyzer.BASE_SHA
    _assert_real_manifest_pins_and_order(checkout)
    print(json.dumps({"core.autocrlf": autocrlf, "git_blob_sha256": digest(blob),
                      "materialized_sha256": digest(materialized),
                      "crlf_line_count": materialized.count(b"\r\n"),
                      "without_rule_materialized_sha256": without_rule_sha,
                      "pin_and_order_check": "passed", "host": sys.platform,
                      "scope": "isolated real Git checkout; not Linux execution"}, sort_keys=True))


def test_malformed_private_cli_input_has_no_traceback_or_canary(tmp_path: Path) -> None:
    private = tmp_path / "private.json"
    private.write_bytes(b'{"answer":"PRIVATE_CANARY_OUTPUT", "answer": "PRIVATE_CANARY_KEY"}')
    args = [sys.executable, str(Path(analyzer.__file__))]
    for name in ("fresh-manifest", "base-manifest", "prefix", "continuation"):
        args += [f"--{name}", str(private)]
    output = tmp_path / "output.json"
    args += ["--output", str(output)]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "validation failed" in result.stderr
    assert "Traceback" not in result.stderr
    assert "PRIVATE_CANARY" not in result.stdout + result.stderr
    assert not output.exists()
