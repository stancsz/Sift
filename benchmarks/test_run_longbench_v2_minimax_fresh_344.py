from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_longbench_v2_minimax_fresh_344 as fresh


def write_pinned_manifest(path: Path) -> None:
    path.write_text(json.dumps(fresh._pinned_manifest_contract(), indent=2), encoding="utf-8")


def test_only_code_pinned_manifest_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "fresh.json"
    write_pinned_manifest(path)
    accepted = fresh.load_and_validate_fresh_manifest(path)
    assert accepted["run_id"] == fresh.FRESH_RUN_ID
    assert fresh._canonical_hash(accepted) == fresh.FRESH_MANIFEST_CANONICAL_SHA256


@pytest.mark.parametrize("change", [
    {"run_id": "fresh344-minimax-second-100usd"},
    {"input_usd_per_million": 0.01},
    {"dispatch_authorized": True},
])
def test_alternate_run_id_or_manifest_is_rejected(tmp_path: Path, change: dict) -> None:
    path = tmp_path / "fresh.json"
    manifest = fresh._pinned_manifest_contract()
    manifest.update(change)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(fresh.FreshRunError, match="code-pinned|exactly match"):
        fresh.load_and_validate_fresh_manifest(path)


def test_cohort_claim_is_global_and_single_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claim = tmp_path / "cohort.claim.json"
    output = tmp_path / "dispatch.json"
    monkeypatch.setattr(fresh, "FRESH_COHORT_CLAIM", claim)
    fresh.claim_fresh_run(output_path=output, cap=100.0)
    recorded = json.loads(claim.read_text(encoding="utf-8"))
    assert recorded["run_id"] == fresh.FRESH_RUN_ID
    assert recorded["manifest_canonical_sha256"] == fresh.FRESH_MANIFEST_CANONICAL_SHA256
    with pytest.raises(fresh.FreshRunError, match="refusing replay"):
        fresh.claim_fresh_run(output_path=output, cap=100.0)


def test_dispatch_output_is_fixed_for_the_cohort() -> None:
    fresh._validate_dispatch_output(fresh.FRESH_DISPATCH_OUTPUT)
    with pytest.raises(fresh.FreshRunError, match="cohort-wide"):
        fresh._validate_dispatch_output(fresh.FRESH_STATE_DIR / "alternate-run.json")


def test_offline_preparation_cannot_consume_dispatch_state(tmp_path: Path) -> None:
    fresh._validate_prepare_output(tmp_path / "prepared.json")
    for path in (fresh.FRESH_DISPATCH_OUTPUT, fresh.FRESH_COHORT_CLAIM):
        with pytest.raises(fresh.FreshRunError, match="separate from dispatch state"):
            fresh._validate_prepare_output(path)


def test_cap_is_bounded_to_explicit_authorization() -> None:
    fresh.validate_cap(100.0)
    for value in (0.0, -1.0, 100.00001, float("inf"), float("nan")):
        with pytest.raises(fresh.FreshRunError):
            fresh.validate_cap(value)


def test_cap_covers_schedule_and_historical_reserve_before_dispatch() -> None:
    assert fresh.validate_budget_coverage(100.0, 41.86563525, 2.0457216) == pytest.approx(43.91135685)
    with pytest.raises(fresh.FreshRunError, match="historical reserve"):
        fresh.validate_budget_coverage(43.90, 41.86563525, 2.0457216)


def test_user_assumption_is_recorded_without_erasing_tracked_reserve() -> None:
    reports, reserve, evidence = fresh.resolve_prior_unknown_outcomes(
        None, assume_none_if_missing=True)
    assert reports == []
    assert reserve == pytest.approx(2.0457216)
    assert evidence["method"] == "user_assumption_with_tracked_historical_reserve"
    assert evidence["exact_reports_supplied"] is False
    assert evidence["actual_settlement_independently_verified"] is False
    assert evidence["documented_unreceipted_attempts"] == 13


def test_missing_report_assumption_is_explicit_and_mutually_exclusive(tmp_path: Path) -> None:
    with pytest.raises(fresh.FreshRunError, match="exact prior reports"):
        fresh.resolve_prior_unknown_outcomes(None, assume_none_if_missing=False)
    with pytest.raises(fresh.FreshRunError, match="not both"):
        fresh.resolve_prior_unknown_outcomes([tmp_path / "report.json"], assume_none_if_missing=True)


def test_assumption_dispatch_path_records_reserve_and_never_sends_real_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "dispatch.json"
    claim = tmp_path / "cohort.claim.json"
    monkeypatch.setattr(fresh, "FRESH_DISPATCH_OUTPUT", output)
    monkeypatch.setattr(fresh, "FRESH_COHORT_CLAIM", claim)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")
    monkeypatch.setattr(fresh.legacy.requests, "post",
                        lambda *args, **kwargs: pytest.fail("real inference request attempted"))
    monkeypatch.setattr(fresh, "_load_base_and_jobs", lambda *args: ({"route_assumptions": {}}, [{"id": 1}], {"id": {}}))
    monkeypatch.setattr(fresh.legacy, "prepare_report", lambda *args: {
        "budget_estimate": {"estimated_reserve_usd": 41.86563525},
    })
    preflight_calls = []
    monkeypatch.setattr(fresh.legacy, "live_account_route_preflight",
                        lambda *args: preflight_calls.append(args) or {"status": "stubbed-read-only"})
    dispatch_calls = []
    monkeypatch.setattr(fresh.legacy, "dispatch", lambda *args, **kwargs: dispatch_calls.append((args, kwargs)) or {
        "status": "complete", "completed_jobs": 0, "settled_actual_cost_usd": 0,
    })

    manifest = fresh.ROOT / "docs/evals/longbench-v2-minimax-fresh-344-manifest-2026-10-20.json"
    result = fresh.main([
        "--manifest", str(manifest), "--dataset", str(tmp_path / "unused-data"),
        "--tokenizer", str(tmp_path / "unused-tokenizer"), "--template", str(tmp_path / "unused-template"),
        "--output", str(output), "--dispatch", "--spend-cap-usd", "100",
        "--confirm-no-unsettled-requests", "--assume-none-if-prior-reports-missing",
        "--authorize-unverified-provider-billing",
    ])

    assert result == 0
    assert len(preflight_calls) == 1
    assert len(dispatch_calls) == 1
    dispatch_args, dispatch_kwargs = dispatch_calls[0]
    assert dispatch_kwargs["prior_unknown_outcome_reserve_usd"] == pytest.approx(2.0457216)
    report = dispatch_args[2]
    assert report["prior_unknown_outcome_accounting"]["method"] == "user_assumption_with_tracked_historical_reserve"
    assert report["prior_unknown_outcome_accounting"]["exact_reports_supplied"] is False
    assert "complete" in capsys.readouterr().out
    assert claim.is_file()


def test_user_assumption_does_not_replace_no_unsettled_dispatch_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")
    with pytest.raises(fresh.FreshRunError, match="Attest that no additional unresolved requests"):
        fresh.main([
            "--manifest", str(tmp_path / "unused-manifest"), "--dataset", str(tmp_path / "unused-data"),
            "--tokenizer", str(tmp_path / "unused-tokenizer"), "--template", str(tmp_path / "unused-template"),
            "--output", str(tmp_path / "dispatch.json"), "--dispatch", "--spend-cap-usd", "100",
            "--assume-none-if-prior-reports-missing", "--authorize-unverified-provider-billing",
        ])
