"""Test paired task summaries without turning repeats into extra tasks."""

import importlib.util
from pathlib import Path
import unittest


AUDIT_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "audit_longbench_v2_rows.py"
SPEC = importlib.util.spec_from_file_location("sift_longbench_audit", AUDIT_PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class LongBenchAuditTests(unittest.TestCase):
    def test_majority_results_are_paired_by_task(self):
        report = {
            "sift_target_estimated_tokens": 100,
            "cases": [
                {"id": "a", "full_exact_input_tokens": 101},
                {"id": "b", "full_exact_input_tokens": 102},
                {"id": "c", "full_exact_input_tokens": 103},
                {"id": "under", "full_exact_input_tokens": 99},
            ],
            "samples": [],
        }
        answers = {
            "a": {"full": [True, True, False], "sift": [False, False, True]},
            "b": {"full": [True, False, False], "sift": [True, True, True]},
            "c": {"full": [False, False, False], "sift": [False, True, False]},
            "under": {"full": [True] * 3, "sift": [False] * 3},
        }
        for case_id, arms in answers.items():
            for arm, values in arms.items():
                report["samples"].extend(
                    {"case_id": case_id, "arm": arm, "correct": value}
                    for value in values
                )

        result = audit.paired_task_majority_sensitivity(report)["none"]
        self.assertEqual(result["tasks"], 3)
        self.assertEqual(result["outcomes"], {
            "both_correct": 0,
            "full_only": 1,
            "sift_only": 1,
            "neither": 1,
        })

    def test_even_or_missing_repeats_are_rejected(self):
        report = {
            "sift_target_estimated_tokens": 0,
            "cases": [{"id": "a", "full_exact_input_tokens": 1}],
            "samples": [
                {"case_id": "a", "arm": "full", "correct": True},
                {"case_id": "a", "arm": "full", "correct": False},
                {"case_id": "a", "arm": "sift", "correct": True},
            ],
        }
        with self.assertRaisesRegex(ValueError, "odd, nonempty"):
            audit.paired_task_majority_sensitivity(report)


if __name__ == "__main__":
    unittest.main()
