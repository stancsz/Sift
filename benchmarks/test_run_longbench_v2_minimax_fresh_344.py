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
