import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
STRINGS = {"experiment_id", "as_of", "report_id", "analysis_run_id", "dataset_id", "dataset_revision", "correction_id", "conclusion"}
INTEGERS = {"report_revision", "evaluated_pairs", "sift_successes", "baseline_successes", "delta_successes", "latency_sample_pairs", "prefill_median_before_ms", "prefill_median_after_ms"}
FILES = {"registry.jsonl", "report_revisions.jsonl", "corrections.jsonl", "dataset_and_limits.jsonl"}
CONCLUSIONS = {"latency_and_task_success_improved", "latency_improved_with_lower_task_success", "task_success_improved_without_latency_gain", "no_supported_comparison"}

class ResearchSchemaTests(unittest.TestCase):
    def test_artifact_schema(self):
        data = json.loads((ROOT / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data), STRINGS | INTEGERS | {"cost_claim_supported", "limitations", "evidence"})
        for field in STRINGS:
            self.assertIsInstance(data[field], str, field)
            self.assertTrue(data[field].strip(), field)
        for field in INTEGERS:
            self.assertIs(type(data[field]), int, field)
        self.assertIs(type(data["cost_claim_supported"]), bool)
        self.assertIsInstance(data["limitations"], list)
        self.assertTrue(data["limitations"])
        self.assertTrue(all(isinstance(value, str) and value.strip() for value in data["limitations"]))
        self.assertIn(data["conclusion"], CONCLUSIONS)

    def test_citations_are_exact_and_cover_files(self):
        data = json.loads((ROOT / "findings.json").read_text(encoding="utf-8"))
        evidence = data.get("evidence")
        self.assertIsInstance(evidence, list)
        covered = set()
        for citation in evidence:
            self.assertEqual(set(citation), {"file", "line", "quote"})
            self.assertIn(citation["file"], FILES)
            self.assertIs(type(citation["line"]), int)
            self.assertIsInstance(citation["quote"], str)
            lines = (ROOT / citation["file"]).read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(citation["line"], 1)
            self.assertLessEqual(citation["line"], len(lines))
            self.assertEqual(citation["quote"], lines[citation["line"] - 1])
            covered.add(citation["file"])
        self.assertEqual(covered, FILES)

if __name__ == "__main__":
    unittest.main()
