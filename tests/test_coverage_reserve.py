"""Regression screen for public weak-overlap epoch coverage cases."""

import importlib.util
import json
from pathlib import Path
import unittest

from sift import core

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sift_coverage_reserve_benchmark", ROOT / "benchmarks" / "coverage_reserve.py")
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


class CoverageReserveTests(unittest.TestCase):
    def test_query_echo_does_not_steal_coverage_reserve(self):
        fixture = json.loads(coverage.FIXTURE.read_text(encoding="utf-8"))
        case = next(item for item in fixture["cases"] if item["name"] == "refund_retention")
        messages = coverage.make_messages(case)
        _, reserve = core._linked_candidates(messages[1:9], case["task"], with_coverage=True)
        self.assertIsNotNone(reserve)
        self.assertIn(case["required_span"], reserve.text)

    def test_public_development_cases_preserve_weak_overlap_and_invariants(self):
        report = coverage.run()
        self.assertEqual(report["fixture_sha256"],
                         "3e7a9d67b5d7fbd40d38ab9becf55ffbd56a0e68618ae35801d77285ce6dd843")
        aggregate = report["aggregate"]
        self.assertEqual(aggregate["exact_spans"], 6)
        self.assertEqual(aggregate["complete_cases"], 6)
        self.assertEqual(aggregate["budget_passes"], aggregate["cases"])
        self.assertEqual(aggregate["protected_task_passes"], aggregate["cases"])
        self.assertEqual(aggregate["latest_cycle_passes"], aggregate["cases"])
        self.assertEqual(aggregate["immutable_input_passes"], aggregate["cases"])


if __name__ == "__main__":
    unittest.main()
