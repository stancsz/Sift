import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from benchmarks import analyze_longbench_v2_minimax_paired_344 as analyzer


def _fixture():
    cases = [{"id": f"task-{i:03d}", "answer_key": "A", "domain": "synthetic",
              "sub_domain": "fixture", "difficulty": "easy", "length": "short"}
             for i in range(344)]
    manifest_jobs = []
    schedule = []
    for case in cases:
        for arm in ("full", "sift"):
            for repeat in (0, 1, 2):
                key = {"case_id": case["id"], "arm": arm, "repeat": repeat}
                body_hash = analyzer.canonical_hash({**key, "synthetic": True})
                manifest_jobs.append({**key, "canonical_request_body_sha256": body_hash})
                schedule.append({"index": len(schedule), **key, "seed": 20261019 + repeat,
                                 "prompt_sha256": "p" * 64, "body_sha256": body_hash,
                                 "local_prompt_tokens": 100, "domain": "synthetic",
                                 "sub_domain": "fixture"})
    manifest = {"status": "prepared_only_no_dispatch", "dispatch_authorized": False,
                "dataset": {"id": "zai-org/LongBench-v2",
                            "revision": "2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9"},
                "route_assumptions": {"route_tag": "minimax/fp8",
                                      "input_usd_per_million": 0.3,
                                      "output_usd_per_million": 1.2,
                                      "max_prompt_tokens": 524288,
                                      "max_completion_tokens": 512000},
                "cases": cases, "jobs": manifest_jobs,
                "cohort_summary": {"schedule_sha256": analyzer.canonical_hash(manifest_jobs)}}
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    manifest_sha = analyzer.sha256_bytes(manifest_bytes)
    prepared = {"status": "prepared_only_no_dispatch", "actual_dispatch_started": False,
                "dispatch_authorized_by_manifest": False, "cohort": "primary_344",
                "planned_jobs": 2064, "manifest_sha256": manifest_sha,
                "execution_runner_sha256": "r" * 64, "schedule": schedule,
                "schedule_sha256": analyzer.canonical_hash(schedule)}
    samples = []
    for case_index, case in enumerate(cases):
        for arm in ("full", "sift"):
            for repeat in (0, 1, 2):
                expected = "A"
                answer = "A"
                finish = "stop"
                failure = None
                choice = "A"
                if arm == "sift" and case_index == 0 and repeat == 0:
                    answer, choice = "not a choice", None
                if arm == "sift" and case_index == 1 and repeat == 0:
                    answer, choice = "B", "B"
                if arm == "sift" and case_index == 2 and repeat == 0:
                    finish = "length"
                if arm == "sift" and case_index == 3:
                    answer, choice = "B", "B"
                row = next(x for x in schedule if x["case_id"] == case["id"]
                           and x["arm"] == arm and x["repeat"] == repeat)
                cost = 0.0002
                sample = {
                    "job_id": f"{case['id']}:{arm}:{repeat}", "case_id": case["id"],
                    "arm": arm, "repeat": repeat, "request_body_sha256": row["body_sha256"],
                    "local_prompt_tokens": 100, "http_status": 200,
                    "requested_model": "minimax/minimax-m3", "returned_model": "minimax/minimax-m3",
                    "provider": "Minimax", "usage": {
                        "is_byok": True, "prompt_tokens": 100, "completion_tokens": 1,
                        "prompt_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 0},
                        "cost_details": {"upstream_inference_cost": cost,
                                         "upstream_inference_prompt_cost": cost * 0.9,
                                         "upstream_inference_completions_cost": cost * 0.1},
                        "cost": 0,
                    },
                    "provider_reported_cost_usd": cost, "provider_local_input_ratio": 1.0,
                    "answer": answer, "choice": choice, "expected": expected,
                    "failure": failure, "finish_reason": finish,
                    "sift_preprocessing_ms": float(case_index + 10) if arm == "sift" else None,
                    "raw_sse_events": ['{"choices": []}', "[DONE]"],
                    "ttft_ms": 10.0, "total_request_wall_ms": 20.0,
                    "prompt": "PROMPT_SENTINEL", "response_text": "RESPONSE_SENTINEL",
                    "answer_text": "ANSWER_SENTINEL",
                }
                samples.append(sample)
    run = {"status": "complete", "actual_dispatch_started": True,
           "manifest_sha256": manifest_sha, "schedule_sha256": prepared["schedule_sha256"],
           "schedule": schedule, "execution_runner_sha256": prepared["execution_runner_sha256"],
           "samples": samples, "completed_jobs": 2064, "elapsed_wall_seconds": 120.0,
           "process_wall_seconds": 140.0,
           "settled_actual_cost_usd": 2064 * 0.0002,
           "live_route_validation": {"endpoint_model_id": "minimax/minimax-m3", "provider": "Minimax",
                                     "route_tag": "minimax/fp8", "input_usd_per_million": 0.3,
                                     "output_usd_per_million": 1.2, "cache_read_usd_per_million": None,
                                     "max_prompt_tokens": 524288, "max_completion_tokens": 512000}}
    return prepared, run, manifest, manifest_sha


class Paired344AnalyzerTests(unittest.TestCase):
    def test_synthetic_complete_run_scores_aggregate_only_and_marks_missing_timing_unavailable(self):
        prepared, run, manifest, manifest_sha = _fixture()
        result = analyzer.analyze(prepared, run, manifest, manifest_sha, bootstrap_samples=200)

        self.assertEqual(result["scope"]["tasks"], 344)
        self.assertEqual(result["scope"]["total_responses"], 2064)
        self.assertEqual(result["quality"]["arms"]["full"]["exact_correct"], 1032)
        self.assertEqual(result["quality"]["arms"]["sift"]["exact_correct"], 1026)
        self.assertEqual(result["quality"]["arms"]["sift"]["invalid_or_incomplete_choices"], 2)
        paired = result["quality"]["paired_task_majority"]
        self.assertEqual((paired["both_correct"], paired["full_only"], paired["sift_only"], paired["neither"]),
                         (343, 1, 0, 0))
        self.assertEqual(paired["difference_ci95"]["bootstrap_samples"], 200)
        self.assertEqual(result["efficiency"]["provider_prompt_token_reduction_fraction"], 0)
        self.assertEqual(result["quality"]["arms"]["full"]["cached_prompt_tokens"]["total"], 20_640)
        self.assertEqual(result["quality"]["arms"]["full"]["prompt_tokens"]["total"], 103_200)
        self.assertAlmostEqual(result["quality"]["arms"]["full"]["upstream_byok_cost_usd"], 0.2064)
        self.assertAlmostEqual(result["quality"]["paired_task_majority"]["sift_minus_full_majority_difference"],
                               -1 / 344)
        ci = result["quality"]["paired_task_majority"]["difference_ci95"]
        self.assertLessEqual(ci["ci95_low"], ci["estimate_sift_minus_full"])
        self.assertGreaterEqual(ci["ci95_high"], ci["estimate_sift_minus_full"])
        self.assertEqual(result["timing"]["ttft_ms"]["full"]["status"], "available")
        self.assertEqual(result["timing"]["request_wall_ms"]["sift"]["status"], "available")
        self.assertEqual(result["timing"]["sift_preprocessing_ms"]["status"], "available")
        self.assertEqual(result["timing"]["sift_preprocessing_ms"]["expected"], 344)
        self.assertEqual(result["timing"]["sift_preprocessing_ms"]["n"], 344)
        self.assertAlmostEqual(result["timing"]["sift_preprocessing_ms"]["mean"], 181.5)
        self.assertEqual(result["timing"]["end_to_end_ms"]["full"]["status"], "unavailable")
        self.assertEqual(result["timing"]["full_preparation_to_completion_wall_time"]["status"], "available")
        self.assertEqual(result["timing"]["full_preparation_to_completion_wall_time"]["value"], 140.0)
        serialized = json.dumps(result)
        for sentinel in ("PROMPT_SENTINEL", "RESPONSE_SENTINEL", "ANSWER_SENTINEL"):
            self.assertNotIn(sentinel, serialized)
        self.assertNotIn("answer_text", serialized)
        self.assertNotIn("response_text", serialized)

    def test_rejects_incomplete_schedule_or_result(self):
        prepared, run, manifest, manifest_sha = _fixture()
        with self.assertRaisesRegex(analyzer.AnalysisError, "schedule"):
            analyzer.analyze({**prepared, "schedule": prepared["schedule"][:-1]}, run, manifest,
                             manifest_sha, bootstrap_samples=200)
        prepared, run, manifest, manifest_sha = _fixture()
        with self.assertRaisesRegex(analyzer.AnalysisError, "exactly 2064 response"):
            analyzer.analyze(prepared, {**run, "samples": run["samples"][:-1]}, manifest,
                             manifest_sha, bootstrap_samples=200)

    def test_rejects_hash_or_cost_mismatch(self):
        prepared, run, manifest, manifest_sha = _fixture()
        broken = copy.deepcopy(run)
        broken["samples"][0]["request_body_sha256"] = "0" * 64
        with self.assertRaisesRegex(analyzer.AnalysisError, "Request hash"):
            analyzer.analyze(prepared, broken, manifest, manifest_sha, bootstrap_samples=200)
        prepared, run, manifest, manifest_sha = _fixture()
        broken = copy.deepcopy(run)
        broken["samples"][0]["provider_reported_cost_usd"] = 5.0
        with self.assertRaisesRegex(analyzer.AnalysisError, "cost receipts disagree"):
            analyzer.analyze(prepared, broken, manifest, manifest_sha, bootstrap_samples=200)

    def test_truncated_or_error_output_is_incorrect_not_repaired(self):
        prepared, run, manifest, manifest_sha = _fixture()
        broken = copy.deepcopy(run)
        target = next(row for row in broken["samples"]
                      if row["case_id"] == "task-000" and row["arm"] == "full")
        target["raw_sse_events"] = ['{"choices": []}']
        result = analyzer.analyze(prepared, broken, manifest, manifest_sha, bootstrap_samples=200)
        self.assertEqual(result["quality"]["arms"]["full"]["exact_correct"], 1031)
        target["failure"] = "synthetic request error"
        result = analyzer.analyze(prepared, broken, manifest, manifest_sha, bootstrap_samples=200)
        self.assertEqual(result["quality"]["arms"]["full"]["exact_correct"], 1031)

    def test_strict_output_and_route_boundaries_are_not_repaired(self):
        prepared, run, manifest, manifest_sha = _fixture()
        candidates = [
            {"answer": "a", "choice": None},
            {"answer": "A.", "choice": None},
            {"answer": "A", "choice": "B"},
            {"http_status": 502},
            {"returned_model": "other-model"},
            {"provider": "other-provider"},
            {"raw_sse_events": ['{"choices": []}']},
        ]
        for index, changes in enumerate(candidates):
            target = run["samples"][index]
            target.update(changes)
        result = analyzer.analyze(prepared, run, manifest, manifest_sha, bootstrap_samples=200)
        self.assertEqual(result["quality"]["arms"]["full"]["exact_correct"], 1028)
        self.assertEqual(result["quality"]["arms"]["full"]["invalid_or_incomplete_choices"], 4)

        prepared, run, manifest, manifest_sha = _fixture()
        run["live_route_validation"]["route_tag"] = "minimax/other"
        with self.assertRaisesRegex(analyzer.AnalysisError, "route tag"):
            analyzer.analyze(prepared, run, manifest, manifest_sha, bootstrap_samples=200)
        run["live_route_validation"]["route_tag"] = "minimax/fp8"
        run["live_route_validation"]["input_usd_per_million"] = 0.31
        with self.assertRaisesRegex(analyzer.AnalysisError, "prices"):
            analyzer.analyze(prepared, run, manifest, manifest_sha, bootstrap_samples=200)

    def test_receipt_guards_and_known_cache_price_reconstruction(self):
        mutations = [
            ({"usage": {"is_byok": False}}, "BYOK proof"),
            ({"usage": {"prompt_tokens_details": {"cached_tokens": 101,
                                                       "cache_write_tokens": 0}}}, "Cache token counts"),
            ({"usage": {"cost_details": {"upstream_inference_cost": 0.0002,
                                           "upstream_inference_prompt_cost": 0.00009,
                                           "upstream_inference_completions_cost": 0.0001}}}, "do not reconcile"),
            ({"usage": {"prompt_tokens": 106}, "provider_local_input_ratio": 1.06}, "tolerance"),
            ({"usage": {"cost": -1}}, "Invalid OpenRouter cost"),
        ]
        for mutation, message in mutations:
            prepared, run, manifest, manifest_sha = _fixture()
            sample = run["samples"][0]
            for key, value in mutation.items():
                if key == "usage":
                    sample["usage"].update(value)
                    if "prompt_tokens_details" in value:
                        sample["usage"]["prompt_tokens_details"].update(value["prompt_tokens_details"])
                    if "cost_details" in value:
                        sample["usage"]["cost_details"].update(value["cost_details"])
                else:
                    sample[key] = value
            with self.assertRaisesRegex(analyzer.AnalysisError, message):
                analyzer.analyze(prepared, run, manifest, manifest_sha, bootstrap_samples=200)

        prepared, run, manifest, manifest_sha = _fixture()
        run["live_route_validation"]["cache_read_usd_per_million"] = 0.06
        result = analyzer.analyze(prepared, run, manifest, manifest_sha, bootstrap_samples=200)
        reconstructed = result["quality"]["arms"]["full"]["cache_adjusted_cost_reconstruction_usd"]
        self.assertAlmostEqual(reconstructed, 1032 * (80 * 0.3 + 20 * 0.06 + 1 * 1.2) / 1_000_000)

    def test_rejects_unreviewed_manifest_hash(self):
        with self.assertRaisesRegex(analyzer.AnalysisError, "reviewed frozen"):
            analyzer.require_pinned_manifest("0" * 64)

        prepared, run, manifest, manifest_sha = _fixture()
        with self.assertRaisesRegex(analyzer.AnalysisError, "Prepared report manifest hash"):
            analyzer.analyze({**prepared, "manifest_sha256": "0" * 64}, run, manifest,
                             manifest_sha, bootstrap_samples=200)

        prepared, run, manifest, manifest_sha = _fixture()
        sample = next(row for row in run["samples"] if row["arm"] == "sift" and row["repeat"] == 1)
        sample["sift_preprocessing_ms"] += 1
        with self.assertRaisesRegex(analyzer.AnalysisError, "differs across repeats"):
            analyzer.analyze(prepared, run, manifest, manifest_sha, bootstrap_samples=200)

        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "unreviewed.json"
            manifest_path.write_text("{}", encoding="utf-8")
            with mock.patch("sys.argv", ["analyzer", "--prepared", "unused", "--run", "unused",
                                         "--manifest", str(manifest_path), "--output", "unused"]):
                with self.assertRaisesRegex(analyzer.AnalysisError, "reviewed frozen"):
                    analyzer.main()


if __name__ == "__main__":
    unittest.main()

