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

    def test_scoring_keys_are_separate_from_frozen_request_messages(self):
        encoded = json.dumps(self.bundle["requests"], ensure_ascii=False)
        self.assertNotIn('"expected"', encoded)
        self.assertNotIn('"answer"', encoded)
        for row in self.bundle["requests"]:
            self.assertNotIn("answer", row["body"])
            self.assertNotIn("expected", row["body"])
        self.assertEqual(len(self.bundle["scoring_keys"]), 100)

    def test_dispatch_scope_is_first_n_and_rejects_invalid_caps(self):
        prefix = pilot.validate_prefix_and_cap(10, 0.01, self.jobs)
        self.assertEqual(len(prefix), 10)
        self.assertEqual(prefix, self.jobs[:10])
        for value in (0, -1, 11, 601, True):
            with self.subTest(prefix=value), self.assertRaises(pilot.PilotError):
                pilot.validate_prefix_and_cap(value, 0.01, self.jobs)
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
        report.update(status="stopped_incomplete_pilot",
                      stop_reason="stream_missing_done_no_retry")
        self.assertIsNone(guard)
        self.assertEqual(report["settled_cost_usd"], 0.0005)
        self.assertIsNone(report["in_flight"])
        self.assertEqual(report["stop_reason"], "stream_missing_done_no_retry")

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
        self.assertEqual(report["status"], "stopped_incomplete_pilot")
        self.assertEqual(report["stop_reason"], "stream_missing_done_no_retry")
        self.assertEqual(report["settled_cost_usd"], 0.00005)
        self.assertIsNone(report["in_flight"])

    def test_mocked_dispatch_preserves_over_reservation_receipt_at_cap_stop(self):
        report = self._run_mock_dispatch(cost=0.002, cap=0.0013, include_done=True)
        self.assertEqual(report["status"], "stopped_incomplete_pilot")
        self.assertEqual(report["stop_reason"], "request_receipt_exceeds_reservation")
        self.assertEqual(report["settled_cost_usd"], 0.002)
        self.assertIsNone(report["in_flight"])


if __name__ == "__main__":
    unittest.main()
