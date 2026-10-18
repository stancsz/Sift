"""Independent acceptance checks for the least-privilege audit fixture."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

# The harness copies this test module into an isolated post-run workspace
# beside the immutable case files, then executes unittest with that directory
# as the working directory.
CASE_ROOT = Path(__file__).resolve().parent
REPORT = CASE_ROOT / "access_audit_report.json"
SCRIPT = CASE_ROOT / "audit_iam.py"
DATA = CASE_ROOT / "data"
SUBJECT = "alice.chen@stratus.example"
WINDOW_START = date(2026, 7, 18)
WINDOW_END = date(2026, 10, 16)
EXPECTED_REQUEST = {
    ("s3:GetObject", "arn:aws:s3:::analytics-prod/*"),
    ("s3:GetObject", "arn:aws:s3:::logs-archive/*"),
    ("s3:GetObject", "arn:aws:s3:::user-uploads/*"),
    ("kms:Decrypt", "arn:aws:kms:us-east-1:123456789012:key/analytics-key"),
    ("dynamodb:Query", "arn:aws:dynamodb:us-east-1:123456789012:table/sessions-prod"),
    ("rds:DescribeDBInstances", "arn:aws:rds:us-east-1:123456789012:db:prod-cluster"),
}
EXPECTED_APPROVED = {
    ("s3:GetObject", "arn:aws:s3:::analytics-prod/*"),
    ("s3:GetObject", "arn:aws:s3:::logs-archive/*"),
    ("kms:Decrypt", "arn:aws:kms:us-east-1:123456789012:key/analytics-key"),
}
EXPECTED_UNUSED = {
    ("s3:GetObject", "arn:aws:s3:::user-uploads/*"),
    ("dynamodb:Query", "arn:aws:dynamodb:us-east-1:123456789012:table/sessions-prod"),
    ("rds:DescribeDBInstances", "arn:aws:rds:us-east-1:123456789012:db:prod-cluster"),
}
EXPECTED_CONFLICTS = EXPECTED_UNUSED
EXPECTED_UNDERGRANT = (
    "redshift:Select",
    "arn:aws:redshift:us-east-1:123456789012:cluster:warehouse/analytics",
)


def run_audit() -> dict:
    subprocess.run([sys.executable, str(SCRIPT)], check=True)
    return json.loads(REPORT.read_text(encoding="utf-8"))


def pairs(items) -> set[tuple[str, str]]:
    return {(item["action"], item["resource"]) for item in items}


def citation_lines(report: dict, finding: str) -> list[tuple[str, int, str]]:
    refs = report.get("citations", {}).get(finding, [])
    assert refs, f"missing citations for {finding}"
    output = []
    for ref in refs:
        name = ref.get("file", "")
        assert name and not Path(name).is_absolute(), f"citation path must be case-relative: {name!r}"
        path = CASE_ROOT / name
        assert path.is_file(), f"citation file does not exist: {name}"
        line = ref.get("line")
        assert type(line) is int and line > 0, f"invalid one-based line: {ref!r}"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert line <= len(lines), f"line is outside {name}: {line}"
        output.append((name.replace("\\", "/"), line, lines[line - 1]))
    return output


def event_fields(line: str):
    fields = [field.strip() for field in line.split("|")]
    if len(fields) != 5:
        return None
    return fields


class ReportContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_audit()

    def test_fixed_subject_role_and_window(self):
        self.assertEqual(self.report["subject"], SUBJECT)
        self.assertEqual(self.report["role"], "data-eng-prod-read")
        self.assertEqual(self.report["request_effective"], "2026-11-01")
        self.assertEqual(self.report["review_window"], {
            "start": "2026-07-18", "end": "2026-10-16"
        })

    def test_request_is_parsed_exactly(self):
        self.assertEqual(pairs(self.report["requested_permissions"]), EXPECTED_REQUEST)
        for item in self.report["requested_permissions"]:
            self.assertEqual(item["resource"], item["resource"].strip())

    def test_approved_permissions_exclude_policy_conflicts(self):
        self.assertEqual(pairs(self.report["approved_permissions"]), EXPECTED_APPROVED)
        self.assertFalse(pairs(self.report["approved_permissions"]) & EXPECTED_CONFLICTS)

    def test_unused_requests_and_policy_conflicts_are_exact(self):
        self.assertEqual(pairs(self.report["overgrants"]), EXPECTED_UNUSED)
        self.assertEqual(pairs(self.report["constraint_violations"]), EXPECTED_CONFLICTS)

    def test_undergrant_count_filters_subject_and_break_glass(self):
        entries = self.report["undergrants"]
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]["action"], entries[0]["resource"]), EXPECTED_UNDERGRANT)
        self.assertEqual(entries[0]["allow_count"], 5)

    def test_report_has_no_volatile_fields_or_absolute_paths(self):
        self.assertNotIn("generated_at", self.report)
        serialized = json.dumps(self.report)
        self.assertNotIn(str(CASE_ROOT), serialized)


class CitationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_audit()

    def test_every_finding_has_valid_case_relative_citations(self):
        for finding in ("approved_permissions", "overgrants", "undergrants", "constraint_violations"):
            self.assertTrue(citation_lines(self.report, finding))

    def test_approved_citations_support_each_allowed_permission(self):
        cited = citation_lines(self.report, "approved_permissions")
        supported = set()
        for name, _, line in cited:
            fields = event_fields(line)
            if fields is None or name.startswith("data/") is False:
                continue
            timestamp, actor, action, resource, result = fields
            event_date = date.fromisoformat(timestamp[:10])
            if actor == SUBJECT and result == "ALLOW" and WINDOW_START <= event_date <= WINDOW_END:
                supported.add((action, resource))
        self.assertTrue(EXPECTED_APPROVED.issubset(supported))

    def test_undergrant_citations_include_five_in_window_subject_events(self):
        cited = citation_lines(self.report, "undergrants")
        matching = set()
        for name, line_no, text in cited:
            fields = event_fields(text)
            if fields is None:
                continue
            timestamp, actor, action, resource, result = fields
            event_date = date.fromisoformat(timestamp[:10])
            if (actor == SUBJECT and (action, resource) == EXPECTED_UNDERGRANT
                    and result == "ALLOW" and WINDOW_START <= event_date <= WINDOW_END):
                matching.add((name, line_no))
        self.assertGreaterEqual(len(matching), 5)

    def test_constraint_citations_cover_policy_sections_and_requested_resources(self):
        text = "\n".join(row[2] for row in citation_lines(self.report, "constraint_violations")).lower()
        self.assertTrue("§2" in text or "sessions" in text)
        self.assertTrue("prod-cluster" in text or "rds" in text)
        self.assertTrue("§3" in text or "user-uploads" in text)

    def test_overgrant_citations_point_to_request_and_policy_or_events(self):
        lines = citation_lines(self.report, "overgrants")
        text = "\n".join(row[2] for row in lines).lower()
        self.assertIn("user-uploads", text)
        self.assertTrue(any("role_request.txt" in row[0] for row in lines))
        self.assertTrue(any(row[0].startswith("data/audit_events_") for row in lines))


class WindowBoundaryTests(unittest.TestCase):
    def test_source_data_has_no_other_subject_audit_counted_as_alice(self):
        all_events = []
        for path in sorted(DATA.glob("audit_events_*.log")):
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                fields = event_fields(line)
                if fields is not None:
                    all_events.append((path.name, line_no, fields))
        in_window = [fields for _, _, fields in all_events
                     if fields[1] == SUBJECT and fields[4] == "ALLOW"
                     and WINDOW_START <= date.fromisoformat(fields[0][:10]) <= WINDOW_END]
        redshift = [fields for fields in in_window
                    if (fields[2], fields[3]) == EXPECTED_UNDERGRANT]
        self.assertEqual(len(redshift), 5)
        self.assertTrue(any(fields[1] == "alice.chen+breakglass@stratus.example"
                            and (fields[2], fields[3]) == EXPECTED_UNDERGRANT
                            and fields[4] == "ALLOW" for _, _, fields in all_events))


if __name__ == "__main__":
    unittest.main()
