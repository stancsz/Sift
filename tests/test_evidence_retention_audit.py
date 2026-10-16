"""Regression tests for source-evidence decoding in the LongBench audit."""

import importlib.util
import json
from pathlib import Path
import unittest


AUDIT_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "audit_longbench_v2_minimax_evidence.py"
SPEC = importlib.util.spec_from_file_location("sift_minimax_evidence_audit", AUDIT_PATH)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class EvidenceRetentionAuditTests(unittest.TestCase):
    def test_duplicate_comment_can_be_retained_by_any_exact_source_record(self):
        first = 'REV-1,"same exact comment"\n'
        second = 'REV-2,"same exact comment"\n'
        excerpt = "review_id,text\n" + second
        messages = [{
            "role": "user",
            "content": "Earlier conversation\n[message 1 user] " + json.dumps(excerpt),
        }]
        evidence = {
            "kind": "complete_unique_csv_field_values",
            "unique_exact_comment_count": 1,
            "required_unique_comment_raw_records": [
                {"text": "same exact comment", "records": [first, second]},
            ],
        }

        result = audit._retention(evidence, messages)

        self.assertEqual(result["retained_evidence_items"], 1)
        self.assertTrue(result["complete_evidence_set"])


if __name__ == "__main__":
    unittest.main()
