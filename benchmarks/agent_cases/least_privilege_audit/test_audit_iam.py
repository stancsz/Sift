"""Visible acceptance tests for the least-privilege audit task."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "access_audit_report.json"
SCRIPT = ROOT / "audit_iam.py"
EXPECTED_REQUEST = [
    ("s3:GetObject", "arn:aws:s3:::analytics-prod/*"),
    ("s3:GetObject", "arn:aws:s3:::logs-archive/*"),
    ("s3:GetObject", "arn:aws:s3:::user-uploads/*"),
    ("kms:Decrypt", "arn:aws:kms:us-east-1:123456789012:key/analytics-key"),
    ("dynamodb:Query", "arn:aws:dynamodb:us-east-1:123456789012:table/sessions-prod"),
    ("rds:DescribeDBInstances", "arn:aws:rds:us-east-1:123456789012:db:prod-cluster"),
]


def run_audit() -> dict:
    subprocess.run([sys.executable, str(SCRIPT)], check=True)
    return json.loads(REPORT.read_text(encoding="utf-8"))


def pairs(items) -> set[tuple[str, str]]:
    return {(item["action"], item["resource"]) for item in items}


def joined(items) -> str:
    return " ".join(json.dumps(item) for item in (items or [])).lower()


class AccessAuditVisibleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_audit()

    def test_required_fields_and_fixed_window(self):
        required = {
            "subject", "role", "request_effective", "review_window",
            "requested_permissions", "approved_permissions", "overgrants",
            "undergrants", "constraint_violations", "citations",
        }
        self.assertTrue(required.issubset(self.report))
        self.assertEqual(self.report["request_effective"], "2026-11-01")
        self.assertEqual(self.report["review_window"], {
            "start": "2026-07-18", "end": "2026-10-16"
        })

    def test_subject_and_role(self):
        self.assertEqual(self.report["subject"], "alice.chen@stratus.example")
        self.assertEqual(self.report["role"], "data-eng-prod-read")

    def test_request_parser_normalizes_whitespace(self):
        actual = [
            (item["action"], item["resource"])
            for item in self.report["requested_permissions"]
        ]
        self.assertEqual(actual, EXPECTED_REQUEST)

    def test_unused_user_uploads_request_is_reported(self):
        self.assertIn("user-uploads", joined(self.report["overgrants"]))

    def test_frequent_unrequested_redshift_access_is_reported(self):
        self.assertIn("redshift", joined(self.report["undergrants"]))

    def test_production_database_policy_conflicts_are_reported(self):
        findings = joined(self.report["constraint_violations"])
        self.assertIn("dynamodb", findings)
        self.assertIn("rds", findings)

    def test_policy_conflicts_are_not_approved(self):
        approved = pairs(self.report["approved_permissions"])
        self.assertNotIn(EXPECTED_REQUEST[4], approved)
        self.assertNotIn(EXPECTED_REQUEST[5], approved)

    def test_output_is_deterministic(self):
        first = REPORT.read_bytes()
        run_audit()
        self.assertEqual(REPORT.read_bytes(), first)

    def test_citations_have_positive_line_numbers(self):
        citations = self.report["citations"]
        self.assertTrue(citations)
        for refs in citations.values():
            self.assertTrue(refs)
            for ref in refs:
                self.assertIn("file", ref)
                self.assertIsInstance(ref["line"], int)
                self.assertGreater(ref["line"], 0)
