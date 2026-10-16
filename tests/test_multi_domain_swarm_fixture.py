"""Build and verify the cross-domain swarm corpus without network access."""

import hashlib
import json
from pathlib import Path
import unittest

from benchmarks import build_multi_domain_swarm_500k as builder


class MultiDomainFixtureBuilderTests(unittest.TestCase):
    def test_seeded_records_are_stable_and_provenance_tagged(self):
        first = builder.records()
        second = builder.records()
        self.assertEqual(first, second)
        self.assertEqual(builder.ROWS, len(first))
        self.assertEqual(len(first), len({row["source_id"] for row in first}))
        self.assertTrue(all({"source_id", "source_system", "provenance", "row_sha256"} <= row.keys()
                            for row in first))
        for row in first:
            raw = {key: value for key, value in row.items() if key != "row_sha256"}
            self.assertEqual(hashlib.sha256(builder.canonical(raw)).hexdigest(), row["row_sha256"])

    def test_domain_coverage_and_dispersed_critical_evidence(self):
        rows = builder.records()
        self.assertEqual({"deploy", "iam", "network", "payments", "tickets", "dashboard"},
                         {row["record_type"] for row in rows})
        self.assertEqual("DEP-000000", rows[0]["source_id"])
        self.assertEqual("IAM-INC-003001", rows[len(rows) // 2 + 1]["source_id"])
        self.assertEqual("NET-005999", rows[-1]["source_id"])

    def test_fixture_token_estimate_is_explicitly_non_qualifying(self):
        manifest = json.loads((builder.GOLD / "input_manifest.json").read_text(encoding="utf-8"))
        estimate = manifest["token_estimate"]
        self.assertIn("LiteLLM 1.103.0", estimate["method"])
        self.assertFalse(estimate["route_qualified"])
        self.assertIsInstance(estimate["count"], int)
        packet = (builder.CASE / "swarm_context.md").read_bytes()
        self.assertEqual(len(packet), estimate["packet_bytes"])
        self.assertEqual(hashlib.sha256(packet).hexdigest(), estimate["packet_sha256"])

    def test_cross_domain_task_requires_four_distinct_read_only_investigations(self):
        task = (builder.CASE / "task.md").read_text(encoding="utf-8")
        for role in ("deployment_auditor", "identity_auditor",
                     "network_payment_auditor", "response_auditor"):
            with self.subTest(role=role):
                self.assertIn(role, task)
        self.assertIn("four distinct agent calls", task)
        self.assertIn("parent is the only writer", task)


if __name__ == "__main__":
    unittest.main()
