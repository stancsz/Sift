"""Explicit fresh-run wrapper for the frozen 344-task MiniMax LongBench cohort.

This entry point is intentionally separate from the legacy stage/continuation
runner. Default operation is offline. One cohort-wide authorization is pinned
in code; a paid run additionally requires an explicit cap (at most $100), live
route/account preflight, and a single-use cohort claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

import run_longbench_v2_minimax_stage1_100 as legacy  # noqa: E402

CURRENT_MANIFEST = ROOT / "docs/evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json"
CURRENT_MANIFEST_SHA256 = "eaddd0d337111c6ab3c36d3f4a68dae4f002c94964de39beec620280f9c657c2"
CURRENT_ROUTE = ROOT / "docs/evals/longbench-v2-openrouter-minimax-m3-endpoints-2026-10-20T1651Z.json"
CURRENT_ROUTE_SHA256 = "cd5993f3d533aaab1065dc6539a8a1a6dbb7ba43b3d62ef6fc7bd5599874bc26"
MAX_USER_CAP_USD = 100.0
TRACKED_HISTORICAL_UNKNOWN_RESERVE_USD = 2.0457216
TRACKED_HISTORICAL_UNRECEIPTED_ATTEMPTS = 13
TRACKED_HISTORICAL_RESERVE_AS_OF = "2026-10-20"
FRESH_SCHEMA = "sift.longbench.minimax.fresh344.v1"
FRESH_RUN_ID = "fresh344-minimax-20261020"
FRESH_STATE_DIR = ROOT / ".runs/longbench-v2-minimax-fresh-344"
FRESH_DISPATCH_OUTPUT = FRESH_STATE_DIR / "fresh344-dispatch.json"
FRESH_COHORT_CLAIM = FRESH_STATE_DIR / "fresh344-cohort.claim.json"
FRESH_PREPARED_OUTPUT = FRESH_STATE_DIR / "fresh344-prepared.json"
# SHA-256 of the canonical JSON contract below. This static pin intentionally
# excludes this runner's own hash, avoiding a self-referential pin.
FRESH_MANIFEST_CANONICAL_SHA256 = "881e896141de69ec4d2c9b8134f724faf0e7bb2736ea640e33e08181f35a8d5a"


class FreshRunError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pinned_manifest_contract() -> dict[str, Any]:
    return {
        "schema": FRESH_SCHEMA,
        "run_id": FRESH_RUN_ID,
        "status": "prepared_only_no_dispatch",
        "dispatch_authorized": False,
        "base_manifest_path": CURRENT_MANIFEST.relative_to(ROOT).as_posix(),
        "base_manifest_sha256": CURRENT_MANIFEST_SHA256,
        "route_snapshot_path": CURRENT_ROUTE.relative_to(ROOT).as_posix(),
        "route_snapshot_sha256": CURRENT_ROUTE_SHA256,
        "cohort_size": 344,
        "repeats_per_arm": 3,
        "arms": ["full", "sift"],
        "planned_jobs": 2064,
        "requested_model": legacy.MODEL,
        "provider": "minimax",
        "route_tag": "minimax/fp8",
        "input_usd_per_million": 0.30,
        "output_usd_per_million": 1.20,
        "max_prompt_tokens": 524288,
        "max_completion_tokens": 512000,
        "schedule_sha256": "52814e20912f272da4d0fd3b1b8668d25b120f4e3800f29cff500bb491239f1f",
        "estimated_reserve_usd": 41.86563525,
    }


def load_and_validate_fresh_manifest(path: Path) -> dict[str, Any]:
    """Accept only the single manifest contract whose canonical hash is code-pinned."""
    if not path.is_file():
        raise FreshRunError("The pinned fresh-run manifest is missing")
    try:
        fresh = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise FreshRunError(f"Fresh manifest is unreadable: {type(error).__name__}") from error
    if not isinstance(fresh, dict):
        raise FreshRunError("Fresh manifest must be a JSON object")
    expected = _pinned_manifest_contract()
    if _canonical_hash(fresh) != FRESH_MANIFEST_CANONICAL_SHA256:
        raise FreshRunError("Fresh manifest differs from the code-pinned authorization and cohort contract")
    if fresh != expected:
        raise FreshRunError("Fresh manifest fields do not exactly match the fixed cohort authorization")
    base = json.loads(CURRENT_MANIFEST.read_text(encoding="utf-8"))
    if (base.get("status") != "prepared_only_no_dispatch" or base.get("dispatch_authorized") is not False
            or len(base.get("cases", [])) != 344 or len(base.get("jobs", [])) != 2064
            or base.get("cohort_summary", {}).get("schedule_sha256") != expected["schedule_sha256"]):
        raise FreshRunError("Fresh manifest does not bind the complete reviewed 344-case schedule")
    if not isinstance(fresh.get("estimated_reserve_usd"), (int, float)) or isinstance(fresh.get("estimated_reserve_usd"), bool):
        raise FreshRunError("Fresh manifest lacks a numeric offline cost reserve")
    route_path = ROOT / fresh["route_snapshot_path"]
    if sha256_file(route_path) != fresh["route_snapshot_sha256"]:
        raise FreshRunError("Fresh route snapshot hash mismatch")
    route = json.loads(route_path.read_text(encoding="utf-8"))
    pricing = route.get("pricing", {})
    if (route.get("requested_model") != legacy.MODEL
            or route.get("endpoint_model_id") != legacy.MODEL
            or str(route.get("provider_name", "")).casefold() != "minimax"
            or route.get("tag") != "minimax/fp8" or route.get("status") != 0
            or route.get("max_prompt_tokens") != 524288
            or route.get("max_completion_tokens") != 512000
            or not math.isclose(float(pricing.get("prompt", 0)) * 1_000_000, 0.30)
            or not math.isclose(float(pricing.get("completion", 0)) * 1_000_000, 1.20)):
        raise FreshRunError("Pinned public route snapshot does not match the fresh-run provider contract")
    return fresh


def validate_cap(cap: float) -> None:
    if not math.isfinite(cap) or cap <= 0 or cap > MAX_USER_CAP_USD:
        raise FreshRunError("Spend cap must be finite, positive, and no more than the authorized $100 USD")


def validate_budget_coverage(cap: float, schedule_reserve: float, prior_reserve: float) -> float:
    """Check the full plan reserve before claiming the single-use cohort."""
    validate_cap(cap)
    values = (schedule_reserve, prior_reserve)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise FreshRunError("Schedule and historical reserves must be finite and nonnegative")
    required = schedule_reserve + prior_reserve
    if cap < required:
        raise FreshRunError(
            f"Cap is below the fresh schedule estimate plus historical reserve ${required:.8f}"
        )
    return required


def claim_fresh_run(*, output_path: Path, cap: float) -> None:
    """Create a durable exclusive claim; never remove/reuse after a run attempt."""
    claim_path = FRESH_COHORT_CLAIM
    validate_cap(cap)
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim = {
        "schema": FRESH_SCHEMA,
        "run_id": FRESH_RUN_ID,
        "manifest_canonical_sha256": FRESH_MANIFEST_CANONICAL_SHA256,
        "output_path": str(output_path.resolve()),
        "spend_cap_usd": cap,
        "claimed_utc": datetime.now(timezone.utc).isoformat(),
        "semantics": "single-use; preserve after any request attempt or ambiguous outcome",
    }
    try:
        with claim_path.open("x", encoding="utf-8") as stream:
            json.dump(claim, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise FreshRunError("Fresh-run claim already exists; refusing replay") from error


def _check_new_paths(output: Path, claim: Path) -> None:
    if output.resolve() == claim.resolve():
        raise FreshRunError("Output and one-use claim must be different paths")
    if output.exists() or claim.exists():
        raise FreshRunError("Output or claim already exists; refusing overwrite/replay")


def _validate_dispatch_output(output: Path) -> None:
    if output.resolve() != FRESH_DISPATCH_OUTPUT.resolve():
        raise FreshRunError("Paid dispatch must use the one cohort-wide output path")


def _validate_prepare_output(output: Path) -> None:
    if output.resolve() in {FRESH_DISPATCH_OUTPUT.resolve(), FRESH_COHORT_CLAIM.resolve()}:
        raise FreshRunError("Offline preparation must use a path separate from dispatch state")


def resolve_prior_unknown_outcomes(report_paths: list[Path] | None,
                                   *, assume_none_if_missing: bool) -> tuple[list[dict], float, dict]:
    """Resolve exact reports or record the user's explicit missing-report assumption.

    The assumption path does not erase tracked historical attempts: it keeps the
    dated aggregate reserve and labels that reserve as unverified evidence.
    """
    paths = report_paths or []
    if paths and assume_none_if_missing:
        raise FreshRunError("Choose exact prior reports or the explicit missing-report assumption, not both")
    if not paths and not assume_none_if_missing:
        raise FreshRunError("Supply the three exact prior reports or explicitly select the user-authorized missing-report assumption")

    if assume_none_if_missing:
        return [], TRACKED_HISTORICAL_UNKNOWN_RESERVE_USD, {
            "method": "user_assumption_with_tracked_historical_reserve",
            "user_instruction": "Assume none if exact prior unknown-outcome reports cannot be found",
            "exact_reports_supplied": False,
            "actual_settlement_independently_verified": False,
            "documented_unreceipted_attempts": TRACKED_HISTORICAL_UNRECEIPTED_ATTEMPTS,
            "reserve_as_of": TRACKED_HISTORICAL_RESERVE_AS_OF,
            "conservative_reserve_usd": TRACKED_HISTORICAL_UNKNOWN_RESERVE_USD,
            "note": "The user assumption does not erase the tracked attempts or establish their settlement.",
        }

    if len(paths) != 3:
        raise FreshRunError("Supply exactly the three pinned prior unknown-outcome reports")
    unknown = [legacy.recorded_unknown_outcome_reserve(
        path, _pinned_manifest_contract()["input_usd_per_million"],
        _pinned_manifest_contract()["output_usd_per_million"])
        for path in paths]
    required = {legacy.UNKNOWN_503_REPORT_SHA256, legacy.UNKNOWN_600_REPORT_SHA256,
                legacy.UNKNOWN_344_REPORT_SHA256}
    hashes = {item["source_report_sha256"] for item in unknown}
    if len(hashes) != 3 or hashes != required:
        raise FreshRunError("Prior reports do not match the three pinned unknown-outcome artifacts")
    return unknown, sum(item["total_reserve_usd"] for item in unknown), {
        "method": "three_pinned_reports",
        "exact_reports_supplied": True,
        "source_report_sha256": sorted(hashes),
        "conservative_reserve_usd": sum(item["total_reserve_usd"] for item in unknown),
        "actual_settlement_independently_verified": False,
    }


def _load_base_and_jobs(fresh: dict[str, Any], dataset: Path, tokenizer: Path,
                        template: Path) -> tuple[dict, list[dict], dict]:
    base = json.loads(CURRENT_MANIFEST.read_text(encoding="utf-8"))
    # The inherited current-main manifest predates the 16:51 route refresh and
    # its old route snapshot file no longer matches the recorded hash. Keep its
    # frozen cohort/source/schedule bindings, but substitute the independently
    # pinned current snapshot in memory for the legacy validator. Never rewrite
    # the historical manifest or legacy continuation configuration.
    route = dict(base.get("route_assumptions", {}))
    route["snapshot_path"] = CURRENT_ROUTE.relative_to(ROOT).as_posix()
    route["snapshot_sha256"] = CURRENT_ROUTE_SHA256
    route["checked_utc"] = "2026-10-20T16:51:40Z"
    route["requested_model"] = legacy.MODEL
    route["provider"] = "Minimax"
    route["endpoint_model_id"] = legacy.MODEL
    route["route_tag"] = "minimax/fp8"
    route["max_prompt_tokens"] = 524288
    route["max_completion_tokens"] = 512000
    route["input_usd_per_million"] = 0.30
    route["output_usd_per_million"] = 1.20
    route["authorizes_dispatch"] = False
    base["route_assumptions"] = route
    old_route_path = legacy.ROUTE_SNAPSHOT_CURRENT
    legacy.ROUTE_SNAPSHOT_CURRENT = CURRENT_ROUTE
    try:
        mode, _ = legacy.verify_provenance(base, CURRENT_MANIFEST, dataset, tokenizer, template)
    finally:
        legacy.ROUTE_SNAPSHOT_CURRENT = old_route_path
    if mode != "primary_344":
        raise FreshRunError("Bound base manifest is not the 344-case cohort")
    jobs, cases = legacy.build_jobs(base, mode, dataset, tokenizer)
    if len(jobs) != 2064 or len(cases) != 344:
        raise FreshRunError("Reconstructed fresh-run schedule is not exactly 344 × 3 × 2")
    for job in jobs:
        if job["projected_provider_prompt_tokens"] > fresh["max_prompt_tokens"]:
            raise FreshRunError("A projected prompt exceeds the pinned fresh route limit")
    total = sum((job["local_prompt_tokens"] * legacy.INPUT_FACTOR * fresh["input_usd_per_million"]
                 + legacy.OUTPUT_CAP * fresh["output_usd_per_million"]) / 1_000_000 for job in jobs)
    if not math.isclose(total, float(fresh["estimated_reserve_usd"]), rel_tol=0, abs_tol=1e-8):
        raise FreshRunError("Offline reconstructed cost reserve differs from the separately frozen manifest")
    return base, jobs, cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Separately reviewed fresh-run manifest (not a legacy continuation manifest).")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", help="Offline preparation is the default.")
    parser.add_argument("--dispatch", action="store_true", help="Explicitly send paid inference requests.")
    parser.add_argument("--spend-cap-usd", type=float)
    parser.add_argument("--confirm-no-unsettled-requests", action="store_true")
    parser.add_argument("--assume-none-if-prior-reports-missing", action="store_true",
                        help="Record the user's explicit assumption; retain the tracked historical reserve.")
    billing = parser.add_mutually_exclusive_group()
    billing.add_argument("--confirm-provider-billing-covers-cap", action="store_true")
    billing.add_argument("--authorize-unverified-provider-billing", action="store_true")
    parser.add_argument("--prior-unknown-outcome-report", type=Path, action="append")
    args = parser.parse_args(argv)
    if args.dispatch != (args.spend_cap_usd is not None):
        raise FreshRunError("Use --dispatch and --spend-cap-usd together; otherwise this is offline preparation")
    if args.dispatch:
        validate_cap(args.spend_cap_usd)
        if not args.confirm_no_unsettled_requests:
            raise FreshRunError("Attest that no additional unresolved requests exist and no dispatch is active")
        if args.confirm_provider_billing_covers_cap == args.authorize_unverified_provider_billing:
            raise FreshRunError("Choose exactly one provider-billing attestation")
        if bool(args.prior_unknown_outcome_report) == args.assume_none_if_prior_reports_missing:
            raise FreshRunError("Supply three exact prior reports or use the explicit missing-report assumption")
    fresh = load_and_validate_fresh_manifest(args.manifest)
    if args.dispatch:
        _validate_dispatch_output(args.output)
        _check_new_paths(args.output, FRESH_COHORT_CLAIM)
    else:
        _validate_prepare_output(args.output)
        if args.output.exists():
            raise FreshRunError("Prepared report already exists; refusing overwrite")
    base, jobs, cases = _load_base_and_jobs(fresh, args.dataset, args.tokenizer, args.template)
    report = legacy.prepare_report(CURRENT_MANIFEST, base, "primary_344", jobs, args.output)
    report.update({"fresh_run_id": fresh["run_id"], "fresh_manifest_canonical_sha256": FRESH_MANIFEST_CANONICAL_SHA256,
                   "fresh_route_snapshot_sha256": CURRENT_ROUTE_SHA256,
                   "run_kind": "new independent 344-case × 3-repeat study"})
    if not args.dispatch:
        legacy.atomic_write(args.output, report)
        print(json.dumps({"status": report["status"], "planned_jobs": len(jobs),
                          "estimated_reserve_usd": report["budget_estimate"]["estimated_reserve_usd"],
                          "output": str(args.output)}, indent=2))
        return 0
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise FreshRunError("OPENROUTER_API_KEY is required only for explicit dispatch")
    unknown, unknown_reserve, unknown_accounting = resolve_prior_unknown_outcomes(
        args.prior_unknown_outcome_report,
        assume_none_if_missing=args.assume_none_if_prior_reports_missing)
    estimate = report["budget_estimate"]["estimated_reserve_usd"]
    validate_budget_coverage(args.spend_cap_usd, estimate, unknown_reserve)
    live_route = legacy.live_account_route_preflight(
        api_key, base, args.spend_cap_usd, jobs, True,
        args.confirm_provider_billing_covers_cap,
        args.authorize_unverified_provider_billing, True, unknown_reserve)
    report["prior_unknown_outcome_evidence"] = unknown
    report["prior_unknown_outcome_reserve_usd"] = unknown_reserve
    report["prior_unknown_outcome_accounting"] = unknown_accounting
    report["live_route_validation"] = live_route
    claim_fresh_run(output_path=args.output, cap=args.spend_cap_usd)
    if args.output.exists():
        raise FreshRunError("Output appeared after preflight; claim is preserved and no request was sent")
    result = legacy.dispatch(jobs, cases, report, args.output, args.spend_cap_usd, api_key,
                             live_route, prior_unknown_outcome_reserve_usd=unknown_reserve,
                             process_started_perf=time.perf_counter(),
                             process_started_utc=datetime.now(timezone.utc).isoformat())
    print(json.dumps({"status": result["status"], "completed_jobs": result["completed_jobs"],
                      "actual_cost_usd": result.get("settled_actual_cost_usd"),
                      "output": str(args.output)}, indent=2))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FreshRunError, legacy.StageError) as error:
        raise SystemExit(f"Fresh 344 run stopped: {error}")
