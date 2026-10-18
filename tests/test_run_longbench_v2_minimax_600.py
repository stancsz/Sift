from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import run_longbench_v2_minimax_600 as pilot
from benchmarks import run_longbench_v2_minimax_stage1_100 as stage


def synthetic_inputs():
    ids = [f"case-{n:03d}" for n in range(100)]
    manifest = {
        "selection": {"ids": ids},
        "evidence_class": "exposed_development_sample_not_blind_holdout",
        "source_hashes": {"fixture": "f" * 64},
        "dataset": {"revision": "fixture-revision", "sha256": "d" * 64},
        "protocol": {"requested_model": "minimax/minimax-m3"},
    }
    jobs, cases = [], {}
    for task_index, case_id in enumerate(ids):
        full = [{"role": "user", "content": f"Prompt {task_index} A/B/C/D?"}]
        sift = [{"role": "user", "content": f"Compact prompt {task_index} A/B/C/D?"}]
        cases[case_id] = {"answer": "ABCD"[task_index % 4],
                          "messages": {"full": full, "sift": sift}}
        for arm in ("full", "sift"):
            for repeat in range(3):
                body = {"model": "minimax/minimax-m3",
                        "messages": cases[case_id]["messages"][arm],
                        "seed": 20261019 + repeat}
                jobs.append({"case_id": case_id, "arm": arm, "repeat": repeat,
                             "seed": body["seed"], "body": body,
                             "body_sha256": stage.canonical_hash(body),
                             "prompt_sha256": stage.canonical_hash(body["messages"]),
                             "local_prompt_tokens": 100,
                             "projected_provider_prompt_tokens": 150,
                             "sift_preprocessing_ms": 1.25 if arm == "sift" else None})
    return manifest, jobs, cases


class FakeStreamResponse:
    status_code = 200
    text = ""

    def __init__(self, usage: dict, include_done: bool):
        event = {"id": "mock-response", "model": "minimax/minimax-m3",
                 "provider": "minimax", "usage": usage,
                 "choices": [{"delta": {"content": "A"}, "finish_reason": "stop"}]}
        self.lines = ["data: " + json.dumps(event)]
        if include_done:
            self.lines.append("data: [DONE]")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)


class Runner600Tests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.jobs, self.cases = synthetic_inputs()
        self.bundle = pilot.make_bundle(self.manifest, pilot.ROOT / "fixture-manifest.json",
                                        self.jobs, self.cases, "a" * 64)

    def test_bundle_bytes_are_deterministic_and_contain_full_schedule(self):
        first = pilot.deterministic_gzip_json(self.bundle)
        second = pilot.deterministic_gzip_json(self.bundle)
        self.assertEqual(first, second)
        decoded = json.loads(gzip.decompress(first))
        self.assertEqual(len(decoded["schedule"]), 600)
        self.assertEqual(len(decoded["requests"]), 600)
        self.assertEqual(len(set(entry["case_id"] for entry in decoded["schedule"])), 100)
        self.assertEqual(decoded["schedule"][:10], self.bundle["schedule"][:10])
        self.assertEqual([row["index"] for row in decoded["schedule"][:10]], list(range(10)))
        self.assertEqual(decoded["schedule_sha256"], stage.canonical_hash(decoded["schedule"]))

    def test_runtime_preprocessing_durations_do_not_change_bundle_identity(self):
        slower_jobs = [dict(job, sift_preprocessing_ms=(job.get("sift_preprocessing_ms") or 0) + 123.456)
                       for job in self.jobs]
        slower_bundle = pilot.make_bundle(
            self.manifest, pilot.ROOT / "fixture-manifest.json", slower_jobs,
            self.cases, "a" * 64)
        self.assertEqual(pilot.deterministic_gzip_json(self.bundle),
                         pilot.deterministic_gzip_json(slower_bundle))
        self.assertTrue(all("sift_preprocessing_ms" not in row for row in self.bundle["schedule"]))

    def test_scoring_keys_are_separate_from_frozen_request_messages(self):
        encoded = json.dumps(self.bundle["requests"], ensure_ascii=False)
        self.assertNotIn('"expected"', encoded)
        self.assertNotIn('"answer"', encoded)
        for row in self.bundle["requests"]:
            self.assertNotIn("answer", row["body"])
            self.assertNotIn("expected", row["body"])
        self.assertEqual(len(self.bundle["scoring_keys"]), 100)

    def test_scoring_is_strict_and_requires_valid_completed_route(self):
        self.assertEqual(pilot.score_sample(" A ", "A", True, True, None, "stop"),
                         {"choice": "A", "expected_answer": "A", "scoreable": True, "correct": True})
        for args in (
            ("The answer is A", "A", True, True, None, "stop"),
            ("A", "A", False, True, None, "stop"),
            ("A", "A", True, False, None, "stop"),
            ("A", "A", True, True, "http_status_not_200", "stop"),
            ("A", "A", True, True, None, "content_filter"),
        ):
            with self.subTest(args=args):
                self.assertFalse(pilot.score_sample(*args)["scoreable"])

    def test_dispatch_scope_accepts_complete_schedule_and_rejects_invalid_caps(self):
        prefix = pilot.validate_prefix_and_cap(600, 10, self.jobs)
        self.assertEqual(len(prefix), 600)
        self.assertEqual(prefix, self.jobs)
        for value in (0, -1, 601, True):
            with self.subTest(prefix=value), self.assertRaises(pilot.PilotError):
                pilot.validate_prefix_and_cap(value, 10, self.jobs)
        for cap in (0, -0.01, float("nan"), float("inf"), True, "1"):
            with self.subTest(cap=cap), self.assertRaises(pilot.PilotError):
                pilot.validate_prefix_and_cap(10, cap, self.jobs)
        with self.assertRaises(pilot.PilotError):
            pilot.validate_prefix_and_cap(10, 0.000001, self.jobs)

    def test_positive_receipt_is_settled_before_terminal_stream_failure(self):
        report = {"settled_cost_usd": 0.0,
                  "in_flight": {"index": 0, "state": "request_started"}}
        guard = pilot.account_receipt(report, 0.0005, "upstream_and_openrouter",
                                      reserve=0.001, cap=0.01, index=0,
                                      job_id="case-000:full:0")
        # The caller then classifies the missing [DONE] marker as terminal.
        report.update(status="stopped_incomplete_run",
                      stop_reason="stream_missing_done_no_retry")
        self.assertIsNone(guard)
        self.assertEqual(report["settled_cost_usd"], 0.0005)
        self.assertIsNone(report["in_flight"])
        self.assertEqual(report["stop_reason"], "stream_missing_done_no_retry")

    def test_provider_token_totals_exclude_unknown_attempts_instead_of_zero_filling(self):
        totals = pilot.reported_token_totals([
            {"usage": {"prompt_tokens": 12, "completion_tokens": 3}},
            {"usage": None},
            {"usage": {"prompt_tokens": 2}},
        ])
        self.assertEqual(totals, {
            "source": "provider_usage_receipts_only",
            "attempts_with_reported_usage": 1,
            "attempts_with_unknown_tokens": 2,
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_reported_tokens": 15,
        })

    def test_continuation_requires_exact_unknown_ssl_failure_and_receipted_prefix(self):
        samples = []
        for index, job in enumerate(self.jobs[:89]):
            samples.append({"index": index,
                            "job_id": f'{job["case_id"]}:{job["arm"]}:{job["repeat"]}',
                            "case_id": job["case_id"], "arm": job["arm"],
                            "repeat": job["repeat"], "request_body_sha256": job["body_sha256"],
                            "attempt_number": 1,
                            "http_status": 200, "failure": None,
                            "sse_done_received": True, "response_id": f"r-{index}",
                            "finish_reason": "stop", "cost_usd": 0.00005,
                            "cost_receipt_source": "upstream_and_openrouter",
                            "usage": {"is_byok": True, "prompt_tokens": 100,
                                      "completion_tokens": 1, "cost": 0,
                                      "cost_details": {"upstream_inference_cost": 0.00005}},
                            "provider": "minimax", "returned_model": stage.MODEL})
        failed_job = self.jobs[89]
        failed_id = f'{failed_job["case_id"]}:{failed_job["arm"]}:{failed_job["repeat"]}'
        samples.append({"index": 89, "job_id": failed_id,
                        "case_id": failed_job["case_id"], "arm": failed_job["arm"],
                        "repeat": failed_job["repeat"], "request_body_sha256": failed_job["body_sha256"],
                        "attempt_number": 1,
                        "failure": "request_exception:SSLError", "http_status": None,
                        "response_id": None, "usage": None, "cost_usd": None})
        report = {"status": "stopped_incomplete_run", "schedule_sha256": self.bundle["schedule_sha256"],
                  "bundle_content_sha256": self.bundle["bundle_content_sha256"],
                  "full_schedule_jobs": 600, "dispatch_prefix_count": 600,
                  "completed_jobs": 89, "samples": samples,
                  "settled_cost_usd": 89 * 0.00005,
                  "in_flight": {"index": 89, "job_id": failed_id,
                                "state": "unknown_outcome_requires_external_reconciliation"}}
        pilot.validate_continuation(report, self.bundle, self.jobs)
        report["samples"][-1]["failure"] = "request_exception:Timeout"
        with self.assertRaises(pilot.PilotError):
            pilot.validate_continuation(report, self.bundle, self.jobs)
        report["samples"][-1]["failure"] = "request_exception:SSLError"
        report["samples"][12]["request_body_sha256"] = "0" * 64
        with self.assertRaises(pilot.PilotError):
            pilot.validate_continuation(report, self.bundle, self.jobs)

    def _run_mock_dispatch(self, cost: float, cap: float, include_done: bool):
        manifest = {"route_assumptions": {}}
        live_route = {"input_usd_per_million": stage.INPUT_PRICE,
                      "output_usd_per_million": stage.OUTPUT_PRICE}
        usage = {"is_byok": True,
                 "cost_details": {"upstream_inference_cost": cost},
                 "cost": cost, "prompt_tokens": 100, "completion_tokens": 1}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "pilot.json"
            with patch.object(stage, "live_account_route_preflight", return_value=live_route), \
                 patch.object(stage.requests, "post",
                              return_value=FakeStreamResponse(usage, include_done)):
                report = pilot._dispatch_prefix(
                    manifest, self.jobs, self.bundle, output, cap, 10,
                    "synthetic-key", True, True)
            self.assertTrue(output.is_file())
            return report

    def test_mocked_dispatch_accounts_positive_receipt_when_done_marker_is_missing(self):
        report = self._run_mock_dispatch(cost=0.00005, cap=0.01, include_done=False)
        self.assertEqual(report["status"], "stopped_incomplete_run")
        self.assertEqual(report["stop_reason"], "stream_missing_done_no_retry")
        self.assertEqual(report["settled_cost_usd"], 0.00005)
        self.assertEqual(report["attempted_jobs"], 1)
        self.assertEqual(report["completed_jobs"], 0)
        self.assertIsNone(report["in_flight"])

    def test_mocked_dispatch_preserves_over_reservation_receipt_at_cap_stop(self):
        report = self._run_mock_dispatch(cost=0.002, cap=0.0013, include_done=True)
        self.assertEqual(report["status"], "stopped_incomplete_run")
        self.assertEqual(report["stop_reason"], "request_receipt_exceeds_reservation")
        self.assertEqual(report["settled_cost_usd"], 0.002)
        self.assertIsNone(report["in_flight"])

    def test_mocked_full_dispatch_marks_complete_and_scores_all_600(self):
        manifest = {"route_assumptions": {}}
        live_route = {"input_usd_per_million": stage.INPUT_PRICE,
                      "output_usd_per_million": stage.OUTPUT_PRICE}
        usage = {"is_byok": True,
                 "cost_details": {"upstream_inference_cost": 0.00005},
                 "cost": 0.00005, "prompt_tokens": 100, "completion_tokens": 1}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "complete.json"
            with patch.object(stage, "live_account_route_preflight", return_value=live_route), \
                 patch.object(stage.requests, "post",
                              return_value=FakeStreamResponse(usage, include_done=True)) as post:
                report = pilot._dispatch_prefix(
                    manifest, self.jobs, self.bundle, output, 10, 600,
                    "synthetic-key", True, True)
            self.assertEqual(post.call_count, 600)
            self.assertEqual(report["status"], "complete")
            self.assertTrue(report["full_schedule_complete"])
            self.assertEqual(report["completed_jobs"], 600)
            self.assertEqual(report["attempted_jobs"], 600)
            self.assertEqual(report["score_summary"]["full"]["scheduled_or_attempted"], 300)
            self.assertEqual(report["score_summary"]["sift"]["scheduled_or_attempted"], 300)
            self.assertEqual(report["score_summary"]["full"]["scorable"], 300)
            self.assertEqual(report["score_summary"]["sift"]["scorable"], 300)
            for arm in ("full", "sift"):
                self.assertEqual(report["score_summary"][arm]["correct"], 75)
                self.assertEqual(report["score_summary"][arm]["response_accuracy"], 0.25)
                self.assertEqual(report["score_summary"][arm]["tasks_with_scorable_responses"], 100)
                self.assertEqual(report["score_summary"][arm]["equal_task_weighted_accuracy"], 0.25)


if __name__ == "__main__":
    unittest.main()
