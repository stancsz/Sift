from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import run_longbench_v2_minimax_stage1_100 as stage


class RecordedUnknownOutcomeTests(unittest.TestCase):
    def _write_report(self, value: dict) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "private-run.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_344_run_requires_the_exact_unreceipted_529_and_reserves_full_route(self):
        job_id = next(iter(stage.UNKNOWN_344_JOB_IDS))
        report = {
            "status": "safety_guard_stopped",
            "manifest_sha256": stage.UNKNOWN_344_MANIFEST_SHA256,
            "stop_reason": "missing_or_invalid_cost_receipt:missing_or_non_byok_usage",
            "completed_jobs": 542,
            "in_flight": {"job_id": job_id,
                          "state": "unknown_outcome_requires_external_reconciliation"},
            "samples": [{"job_id": job_id, "http_status": 529, "usage": None,
                         "provider_reported_cost_usd": None,
                         "failure": "http_status_not_200"}],
        }
        path = self._write_report(report)
        with patch.object(stage, "file_sha256", return_value=stage.UNKNOWN_344_REPORT_SHA256):
            evidence = stage.recorded_unknown_outcome_reserve(path)
        expected = (stage.PROVIDER_LIMIT * stage.INPUT_PRICE
                    + stage.OUTPUT_CAP * stage.OUTPUT_PRICE) / 1_000_000
        self.assertAlmostEqual(evidence["total_reserve_usd"], expected)
        self.assertEqual(evidence["source_unknown_job_ids"], [job_id])

        report["samples"][0]["http_status"] = 200
        path.write_text(json.dumps(report), encoding="utf-8")
        with patch.object(stage, "file_sha256", return_value=stage.UNKNOWN_344_REPORT_SHA256):
            with self.assertRaises(stage.StageError):
                stage.recorded_unknown_outcome_reserve(path)

    def test_503_report_requires_all_four_pinned_unreceipted_jobs(self):
        ids = sorted(stage.UNKNOWN_503_JOB_IDS)
        report = {
            "status": "prefix_incomplete",
            "unknown_outcome_job_ids": ids,
            "schedule": [{"job_id": job_id, "arm": "full", "local_prompt_tokens": 100}
                         for job_id in ids],
            "samples": [{"job_id": job_id, "usage": None,
                         "failure": "request_exception:SSLError"} for job_id in ids],
        }
        path = self._write_report(report)
        with patch.object(stage, "file_sha256", return_value=stage.UNKNOWN_503_REPORT_SHA256):
            evidence = stage.recorded_unknown_outcome_reserve(path)
        self.assertEqual(set(evidence["source_unknown_job_ids"]), stage.UNKNOWN_503_JOB_IDS)
        self.assertEqual(len(evidence["per_job_reserves_usd"]), 4)

    def test_continuation_validates_prefix_and_skips_529_without_resending(self):
        case_ids = [f"case-{case:03d}" for case in range(344)]
        unknown = ("66f53892821e116aacb33225", "full", 2)
        case_ids[170] = unknown[0]
        keys = [(case_id, arm, repeat)
                for case_id in case_ids for arm in ("full", "sift") for repeat in range(3)]
        keys.remove(unknown)
        keys.insert(541, unknown)
        jobs = []
        for index, (case_id, arm, repeat) in enumerate(keys):
            body = {"case_id": case_id, "arm": arm, "repeat": repeat}
            jobs.append({"case_id": case_id, "arm": arm, "repeat": repeat,
                         "seed": repeat, "prompt_sha256": stage.canonical_hash(body),
                         "body_sha256": stage.canonical_hash({"request": body}),
                         "local_prompt_tokens": 100, "local_cost_estimate_usd": 0.001,
                         "projected_provider_prompt_tokens": 150,
                         "domain": "fixture", "sub_domain": "fixture"})
        manifest = {"source_hashes": {}, "protocol": {}, "evidence_class": "fixture"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.json"
            manifest_path = root / "manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            prepared = stage.prepare_report(manifest_path, manifest,
                                            "primary_344", jobs, source)
            samples = []
            for index, row in enumerate(prepared["schedule"][:542]):
                job_id = f'{row["case_id"]}:{row["arm"]}:{row["repeat"]}'
                if index == 541:
                    samples.append({"job_id": job_id, "request_body_sha256": row["body_sha256"],
                                    "http_status": 529, "usage": None,
                                    "provider_reported_cost_usd": None})
                else:
                    samples.append({"job_id": job_id, "request_body_sha256": row["body_sha256"],
                                    "http_status": 200,
                                    "returned_model": stage.MODEL,
                                    "provider": "Minimax",
                                    "sse_done_received": True,
                                    "failure": None,
                                    "usage": {"is_byok": True, "cost": 0.001,
                                              "cost_details": {"upstream_inference_cost": 0.001}},
                                    "provider_reported_cost_usd": 0.001})
            prepared.update({"status": "safety_guard_stopped",
                             "stop_reason": "missing_or_invalid_cost_receipt:missing_or_non_byok_usage",
                             "manifest_sha256": stage.UNKNOWN_344_MANIFEST_SHA256,
                             "completed_jobs": 542,
                             "settled_actual_cost_usd": 541 * 0.001,
                             "samples": samples,
                             "in_flight": {"index": 541,
                                           "job_id": f"{unknown[0]}:{unknown[1]}:{unknown[2]}",
                                           "state": "unknown_outcome_requires_external_reconciliation"}})
            source.write_text(json.dumps(prepared), encoding="utf-8")
            with patch.object(stage, "file_sha256", return_value=stage.UNKNOWN_344_REPORT_SHA256):
                remaining, settled = stage.validate_stopped_344_continuation(source, jobs)
            self.assertEqual(len(remaining), 1522)
            self.assertAlmostEqual(settled, 0.541)
            remaining_ids = {f'{job["case_id"]}:{job["arm"]}:{job["repeat"]}'
                             for job in remaining}
            self.assertNotIn(f"{unknown[0]}:{unknown[1]}:{unknown[2]}", remaining_ids)
            self.assertEqual(remaining[0]["case_id"], keys[542][0])

    def test_dispatch_minimum_cap_includes_previous_settled_and_unknown_costs(self):
        report = {"budget_estimate": {"estimated_reserve_usd": 1.0}}
        live_route = {"input_usd_per_million": stage.INPUT_PRICE,
                      "output_usd_per_million": stage.OUTPUT_PRICE}
        with tempfile.TemporaryDirectory() as temporary, self.assertRaisesRegex(
                stage.StageError, "at least the refreshed estimate"):
            stage.dispatch([], {}, report, Path(temporary) / "out.json", 1.4,
                           "synthetic-key", live_route,
                           prior_unknown_outcome_reserve_usd=0.2,
                           prior_settled_cost_usd=0.3)

    def test_single_use_claim_prevents_replaying_the_same_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "continuation.json"
            claim = root / "continuation-claimed.json"
            with patch.object(stage, "CONTINUATION_OUTPUT", output):
                stage.claim_single_use_continuation(
                    root / "stopped.json", output, 100.0, claim_path=claim)
                with self.assertRaisesRegex(stage.StageError, "already been claimed"):
                    stage.claim_single_use_continuation(
                        root / "stopped.json", output, 100.0, claim_path=claim)
                with self.assertRaisesRegex(stage.StageError, "single-use path"):
                    stage.claim_single_use_continuation(
                        root / "stopped.json", root / "alternate.json", 100.0,
                        claim_path=claim)

    def test_preflight_cannot_bypass_known_unknown_reserve_with_clean_attestation(self):
        with self.assertRaisesRegex(stage.StageError, "known unresolved"):
            stage.live_account_route_preflight(
                "synthetic-key", {}, 100.0, [], no_unsettled_attested=True,
                provider_billing_attested=False,
                provider_billing_authorized_unverified=True,
                prior_unknown_outcome_explicitly_accepted=False,
                prior_unknown_outcome_reserve_usd=0.0)

    def test_preflight_requires_attestation_for_no_additional_unknowns(self):
        with self.assertRaisesRegex(stage.StageError, "no additional unresolved"):
            stage.live_account_route_preflight(
                "synthetic-key", {}, 100.0, [], no_unsettled_attested=False,
                provider_billing_attested=False,
                provider_billing_authorized_unverified=True,
                prior_unknown_outcome_explicitly_accepted=True,
                prior_unknown_outcome_reserve_usd=1.0)

    def test_cli_rejects_dispatch_with_only_one_known_unknown_report(self):
        for no_additional, accepted, paths in (
                (True, False, None), (True, True, [Path("only-one.json")]),
                (False, True, [Path("one.json"), Path("two.json")])):
            with patch.object(stage.argparse.ArgumentParser, "parse_args", return_value=type(
                    "Args", (), {
                        "dispatch": True, "spend_cap_usd": 100.0,
                        "confirm_no_unsettled_requests": no_additional,
                        "confirm_provider_billing_covers_cap": False,
                        "authorize_unverified_provider_billing": True,
                        "accept_recorded_unknown_outcomes": accepted,
                        "prior_unknown_outcome_report": paths,
                        "continue_after_known_unknown_report": None,
                    })()):
                with self.assertRaises(stage.StageError):
                    stage.main()


if __name__ == "__main__":
    unittest.main()
