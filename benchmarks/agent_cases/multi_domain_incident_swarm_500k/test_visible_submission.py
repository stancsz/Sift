"""Visible delivery contract; independent cross-source gold runs after the agent exits."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class IncidentSubmissionTests(unittest.TestCase):
    def test_report_has_required_findings_and_citations(self):
        report_path = ROOT / "incident_report.json"
        self.assertTrue(report_path.is_file(), "deliver incident_report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIsInstance(report.get("findings"), list)
        findings = {item.get("finding_id"): item for item in report["findings"]
                    if isinstance(item, dict)}
        required = {"root_cause", "confirmed_exposure", "payment_reconciliation",
                    "customer_impact", "containment_order"}
        self.assertTrue(required.issubset(findings))
        sources = {json.loads(line)["source_id"] for line in
                   (ROOT / "data" / "source_records.jsonl").read_text(encoding="utf-8").splitlines()}
        for name in required:
            with self.subTest(finding=name):
                self.assertTrue(findings[name].get("claim"))
                evidence = findings[name].get("evidence_ids")
                self.assertIsInstance(evidence, list)
                self.assertTrue(evidence)
                self.assertTrue(set(evidence).issubset(sources))
        self.assertTrue(report.get("limitations"), "state what the evidence cannot establish")

    def test_plan_contains_ordered_containment_and_rollback(self):
        plan_path = ROOT / "remediation_plan.md"
        self.assertTrue(plan_path.is_file(), "deliver remediation_plan.md")
        plan = plan_path.read_text(encoding="utf-8")
        required = ["revoke sess-incident-88421", "rotate finance-export-writer credentials",
                    "block 198.51.100.77", "preserve evidence", "notify affected customer",
                    "rollback CHG-88421"]
        positions = [plan.find(action) for action in required]
        self.assertTrue(all(position >= 0 for position in positions))
        self.assertEqual(sorted(positions), positions)


if __name__ == "__main__":
    unittest.main()
