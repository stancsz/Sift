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
                    })()):
                with self.assertRaises(stage.StageError):
                    stage.main()


if __name__ == "__main__":
    unittest.main()
