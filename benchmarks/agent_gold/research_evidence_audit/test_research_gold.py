"""Gold fixed before the first client run. Public development fixture, not a held-out score."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
EXPECTED = {
    "experiment_id": "EXP-KITE-43", "as_of": "2026-10-15T12:00:00Z",
    "report_id": "RPT-NOVA-18", "report_revision": 3,
    "analysis_run_id": "AN-6P2", "dataset_id": "DS-LANTERN-7", "dataset_revision": "d",
    "correction_id": "ERR-739", "evaluated_pairs": 120,
    "sift_successes": 91, "baseline_successes": 96, "delta_successes": -5,
    "latency_sample_pairs": 89, "prefill_median_before_ms": 840,
    "prefill_median_after_ms": 510,
    "conclusion": "latency_improved_with_lower_task_success", "cost_claim_supported": False,
}

class ResearchGoldTests(unittest.TestCase):
    def test_current_corrected_conclusions(self):
        data = json.loads((ROOT / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual(set(data), set(EXPECTED) | {"limitations", "evidence"})
        self.assertEqual({key: data.get(key) for key in EXPECTED}, EXPECTED)
        for key, value in EXPECTED.items():
            self.assertIs(type(data[key]), type(value), key)
        self.assertEqual(set(data.get("limitations", [])), {
            "synthetic_tasks_only", "single_hardware_configuration",
            "latency_subset_excludes_unsuccessful_pairs",
        })
        self.assertEqual(len(data["limitations"]), 3)

    def test_citations_support_each_join(self):
        data = json.loads((ROOT / "findings.json").read_text(encoding="utf-8"))
        cited = {}
        files = {"registry.jsonl", "report_revisions.jsonl", "corrections.jsonl", "dataset_and_limits.jsonl"}
        for citation in data.get("evidence", []):
            self.assertEqual(set(citation), {"file", "line", "quote"})
            self.assertIn(citation["file"], files)
            self.assertIs(type(citation["line"]), int)
            lines = (ROOT / citation["file"]).read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(citation["line"], 1)
            self.assertLessEqual(citation["line"], len(lines))
            line = lines[citation["line"] - 1]
            self.assertEqual(citation["quote"], line)
            record = json.loads(line)
            cited[record["record_id"]] = record
        required = {
            "REG-A31": {"experiment_id": "EXP-KITE-43", "report_id": "RPT-NOVA-18"},
            "REG-C84": {"analysis_run_id": "AN-6P2", "report_revision": 3, "dataset_revision": "d"},
            "RPT-FINAL-63": {"correction_id": "ERR-739", "sift_successes": 91, "latency_sample_pairs": 89},
            "ERR-VALID-42": {"corrected_successes": 91, "applies_to_revision": 3},
            "DS-BOUND-74": {"dataset_id": "DS-LANTERN-7", "revision": "d", "analysis_run_id": "AN-6P2"},
            "LIM-CORE-58": {"analysis_run_id": "AN-6P2", "cost_claim_supported": False},
        }
        for record_id, fields in required.items():
            self.assertIn(record_id, cited)
            self.assertEqual({key: cited[record_id].get(key) for key in fields}, fields)

if __name__ == "__main__":
    unittest.main()
