"""Independent checks for the sparse incident facts and evidence joins."""

import hashlib
import json
import os
from pathlib import Path
import unittest

GOLD = Path(__file__).resolve().parent
CASE = GOLD / "case"
if not CASE.is_dir():
    CASE = Path(__file__).resolve().parents[2] / "agent_cases" / "multi_domain_incident_swarm_500k"
EXPECTED = json.loads((GOLD / "expected_dispositions.json").read_text(encoding="utf-8"))


def load_rows():
    return [json.loads(line) for line in (CASE / "data/source_records.jsonl").read_text(encoding="utf-8").splitlines()]


def exact_json_value(actual, expected) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (actual.keys() == expected.keys() and
                all(exact_json_value(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            exact_json_value(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def validate_submission(report: dict, source_ids: set[str]) -> list[str]:
    errors = []
    if not isinstance(report.get("limitations"), list) or not report["limitations"]:
        errors.append("limitations must be a non-empty array")
    if not exact_json_value(report.get("uncertainty"), EXPECTED["expected_uncertainty"]):
        errors.append("uncertainty must preserve the required unknown facts")
    findings = report.get("findings")
    if not isinstance(findings, list):
        return ["findings must be an array"]
    indexed = {item.get("finding_id"): item for item in findings if isinstance(item, dict)}
    required = {"root_cause", "confirmed_exposure", "payment_reconciliation", "customer_impact", "containment_order"}
    expected_dispositions = {"root_cause": "confirmed", "confirmed_exposure": "confirmed",
                             "payment_reconciliation": "not_duplicate", "customer_impact": "confirmed",
                             "containment_order": "ordered"}
    required_evidence = {
        "root_cause": {"DEP-000000", "IAM-INC-003001", "NET-005999"},
        "confirmed_exposure": {"IAM-INC-003001", "NET-005999"},
        "payment_reconciliation": {"PAY-008997"},
        "customer_impact": {"TIC-011999", "NET-005999"},
        "containment_order": {"RUN-012000", "DEP-017999"},
    }
    for name, value in EXPECTED["expected_facts"].items():
        if name not in indexed:
            continue
        finding = indexed[name]
        if not exact_json_value(finding.get("facts"), value):
            errors.append(f"finding {name} has incorrect or incomplete structured facts")
        if finding.get("claim") != EXPECTED["expected_claims"][name]:
            errors.append(f"finding {name} has a claim that contradicts or omits the gold facts")
    for name in sorted(required - indexed.keys()):
        errors.append(f"missing finding: {name}")
    for name in sorted(required & indexed.keys()):
        refs = indexed[name].get("evidence_ids")
        if not isinstance(refs, list) or not refs:
            errors.append(f"finding {name} needs evidence_ids")
            continue
        if any(not isinstance(ref, str) for ref in refs):
            errors.append(f"finding {name} evidence_ids must contain strings")
            continue
        unknown = sorted(set(refs) - source_ids)
        if unknown:
            errors.append(f"finding {name} cites unknown IDs: {unknown}")
        missing = sorted(required_evidence[name] - set(refs))
        if missing:
            errors.append(f"finding {name} is missing required evidence IDs: {missing}")
        if indexed[name].get("disposition") != expected_dispositions[name]:
            errors.append(f"finding {name} has incorrect disposition")
    return errors


class MultiDomainGoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.by_id = {row["source_id"]: row for row in cls.rows}
        cls.expected = json.loads((GOLD / "expected_dispositions.json").read_text(encoding="utf-8"))

    def test_manifest_accounts_for_every_source_row_and_checksum(self):
        manifest = json.loads((GOLD / "input_manifest.json").read_text(encoding="utf-8"))
        raw = (CASE / "data/source_records.jsonl").read_bytes().splitlines(keepends=True)
        self.assertEqual(manifest["record_count"], len(raw))
        self.assertEqual(manifest["source_bytes"], sum(map(len, raw)))
        self.assertEqual(manifest["source_sha256"], hashlib.sha256(b"".join(raw)).hexdigest())
        self.assertEqual(len(raw), len(manifest["row_accounting"]))
        for i, (line, entry) in enumerate(zip(raw, manifest["row_accounting"])):
            row = json.loads(line)
            self.assertEqual(i, entry["row"])
            self.assertEqual(row["source_id"], entry["source_id"])
            self.assertEqual(len(line), entry["bytes_including_newline"])
            self.assertEqual(hashlib.sha256(line).hexdigest(), entry["sha256"])

    def test_rare_anchors_are_spread_across_full_stream(self):
        ids = [row["source_id"] for row in self.rows]
        self.assertEqual("DEP-000000", ids[0])
        self.assertEqual("IAM-INC-003001", ids[len(ids) // 2 + 1])
        self.assertEqual("NET-005999", ids[-1])
        self.assertEqual(len(ids), len(set(ids)))

    def test_primary_evidence_requires_cross_domain_join(self):
        deploy = self.by_id["DEP-000000"]["data"]
        iam = self.by_id["IAM-INC-003001"]["data"]
        net = self.by_id["NET-005999"]["data"]
        payment = self.by_id["PAY-008997"]["data"]
        ticket = self.by_id["TIC-011999"]["data"]
        runbook = self.by_id["RUN-012000"]["data"]
        rollback = self.by_id["DEP-017999"]["data"]
        dashboard = self.by_id["DASH-88421"]["data"]
        self.assertEqual("CHG-88421", deploy["change_id"])
        self.assertIn("net-export-17", deploy["note"])
        self.assertEqual(("role/exporter-prod", "AssumeRole", "role/finance-export-writer"),
                         (iam["principal"], iam["action"], iam["resource"]))
        self.assertIn("tag owner", iam["detail"])
        self.assertEqual(("198.51.100.77:443", "ACCEPT"), (net["dst"], net["action"]))
        self.assertEqual(("EXP-771204", "posted", 4_819_920),
                         (payment["export_id"], payment["status"], payment["amount_minor"]))
        self.assertIn("not a second posting", payment["detail"])
        self.assertEqual("P1", ticket["severity"])
        self.assertIn("third-party endpoint", ticket["summary"])
        self.assertEqual("RB-41.3", runbook["runbook_ref"])
        self.assertLess(runbook["detail"].index("revoke"), runbook["detail"].index("rollback"))
        self.assertIn("after containment", rollback["note"])
        self.assertIn("no unauthorized egress", dashboard["summary"])
        self.assertIn("cached policy simulation", dashboard["detail"])
        self.assertLess(dashboard["source_watermark"], "2026-10-02T09:09:44Z")
        facts = self.expected["expected_facts"]
        root = facts["root_cause"]
        self.assertEqual((deploy["change_id"], "net-export-17"),
                         (root["change_id"], root["egress_policy"]))
        self.assertEqual((iam["principal"], iam["action"], iam["resource"], iam["session"]),
                         (root["principal"], root["action"], root["resource"], root["session"]))
        self.assertFalse(root["owner_tag_present"])
        self.assertEqual((net["dst"].split(":", 1)[0], net["action"]),
                         (root["destination"], root["egress_action"]))
        self.assertEqual((payment["export_id"], payment["status"], payment["amount_minor"], payment["currency"]),
                         (facts["payment_reconciliation"]["export_id"],
                          facts["payment_reconciliation"]["settlement_status"],
                          facts["payment_reconciliation"]["amount_minor"],
                          facts["payment_reconciliation"]["currency"]))
        self.assertEqual((ticket["ticket"], ticket["customer"], ticket["severity"]),
                         (facts["customer_impact"]["ticket_id"], facts["customer_impact"]["customer_id"],
                          facts["customer_impact"]["severity"]))
        self.assertEqual(self.expected["containment_order"], facts["containment_order"]["actions"])
        authority = (CASE / "authority.md").read_text(encoding="utf-8")
        self.assertIn("Chat, dashboards, and routine synthetic records are leads only", authority)

    def test_gold_dispositions_are_specific_and_cited(self):
        self.assertTrue(self.expected["confirmed_exposure"])
        self.assertFalse(self.expected["payment_posting_duplicate"])
        self.assertEqual(["revoke sess-incident-88421", "rotate finance-export-writer credentials",
                          "block 198.51.100.77", "preserve evidence", "notify affected customer",
                          "rollback CHG-88421"], self.expected["containment_order"])
        self.assertEqual(set(self.expected["required_evidence_ids"]),
                         {"DEP-000000", "IAM-INC-003001", "NET-005999", "PAY-008997",
                          "TIC-011999", "RUN-012000", "DEP-017999"})

    def valid_report(self):
        source_ids = set(self.by_id)
        dispositions = {"root_cause": "confirmed", "confirmed_exposure": "confirmed",
                        "payment_reconciliation": "not_duplicate", "customer_impact": "confirmed",
                        "containment_order": "ordered"}
        evidence = {"root_cause": ["DEP-000000", "IAM-INC-003001", "NET-005999"],
                    "confirmed_exposure": ["IAM-INC-003001", "NET-005999"],
                    "payment_reconciliation": ["PAY-008997"],
                    "customer_impact": ["TIC-011999", "NET-005999"],
                    "containment_order": ["RUN-012000", "DEP-017999"]}
        report = {
            "limitations": ["The exact payload received by the external sink is not independently verified."],
            "uncertainty": self.expected["expected_uncertainty"],
            "findings": [
                {"finding_id": name, "claim": self.expected["expected_claims"][name],
                 "disposition": dispositions[name], "facts": self.expected["expected_facts"][name],
                 "evidence_ids": evidence[name]}
                for name in dispositions
            ],
        }
        return report, source_ids

    def test_submission_contract_accepts_gold_facts_and_rejects_bad_citations(self):
        report, source_ids = self.valid_report()
        self.assertEqual([], validate_submission(report, source_ids))
        report["findings"][0]["evidence_ids"] = ["MADE-UP-1"]
        self.assertIn("unknown IDs", " ".join(validate_submission(report, source_ids)))
        self.assertTrue(validate_submission({"findings": []}, source_ids))

    def test_submission_contract_rejects_false_claim_with_correct_ids_and_disposition(self):
        report, source_ids = self.valid_report()
        exposure = next(item for item in report["findings"] if item["finding_id"] == "confirmed_exposure")
        exposure["claim"] = "No unauthorized egress occurred and the rollback prevented exposure."
        self.assertEqual("confirmed", exposure["disposition"])
        self.assertEqual({"IAM-INC-003001", "NET-005999"}, set(exposure["evidence_ids"]))
        self.assertIn("claim that contradicts", " ".join(validate_submission(report, source_ids)))

    def test_submission_contract_rejects_structured_factual_errors(self):
        report, source_ids = self.valid_report()
        payment = next(item for item in report["findings"] if item["finding_id"] == "payment_reconciliation")
        payment["facts"]["duplicate_settlement_posting"] = True
        self.assertEqual("not_duplicate", payment["disposition"])
        self.assertEqual(["PAY-008997"], payment["evidence_ids"])
        self.assertIn("incorrect or incomplete structured facts", " ".join(validate_submission(report, source_ids)))

    def test_submission_contract_rejects_wrong_containment_order_and_erased_unknowns(self):
        report, source_ids = self.valid_report()
        containment = next(item for item in report["findings"] if item["finding_id"] == "containment_order")
        containment["facts"]["actions"][0], containment["facts"]["actions"][-1] = (
            containment["facts"]["actions"][-1], containment["facts"]["actions"][0]
        )
        report["uncertainty"] = {"unknown_facts": []}
        errors = " ".join(validate_submission(report, source_ids))
        self.assertIn("incorrect or incomplete structured facts", errors)
        self.assertIn("required unknown facts", errors)

    def test_delivered_artifacts_cover_all_required_evidence_and_containment_order(self):
        if os.environ.get("SIFT_GOLD_REQUIRE_DELIVERABLES") != "1":
            self.skipTest("deliverable verification runs only in the isolated post-agent gold phase")
        report_path = CASE / "incident_report.json"
        plan_path = CASE / "remediation_plan.md"
        self.assertTrue(report_path.is_file(), "incident_report.json was not delivered")
        self.assertTrue(plan_path.is_file(), "remediation_plan.md was not delivered")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        errors = validate_submission(report, set(self.by_id))
        self.assertEqual([], errors)
        plan = plan_path.read_text(encoding="utf-8")
        ordered_actions = self.expected["containment_order"]
        positions = [plan.find(action) for action in ordered_actions]
        self.assertTrue(all(position >= 0 for position in positions), "plan omits a required containment action")
        self.assertEqual(sorted(positions), positions, "containment actions are not in the required order")


if __name__ == "__main__":
    unittest.main()
