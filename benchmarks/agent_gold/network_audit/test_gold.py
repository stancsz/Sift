"""Gold acceptance tests for the MDC-3 change audit fixture.

Independent of the visible tests: nothing is imported from `case/` except
the program under test itself, `case/audit.py`, which is loaded directly
by file path. Evidence is re-derived inside these tests from the raw
source files so the gold expectations are not copied from the visible
suite.

Run from the workspace root:
    python -m unittest discover -s gold -p "test_gold.py"
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
CASE = WORKSPACE
AUDIT = CASE / "audit.py"

REQUIRED_NOTES = {
    "supersession: CHG-2026-1147 superseded by CHG-2026-1188",
    "conflict: ops channel claim contradicts controller record for CHG-2026-1193",
    "conflict: CHG-2026-1201 controller marker corroborated by switch record at UTC 2026-09-30T22:00:04Z",
    "window: CHG-2026-1201 event at or after window end",
    "approval: CHG-2026-1210 lacks an independent network engineering lead approval",
    "rollback: CHG-2026-1210 rolled back",
    "telemetry: CHG-2026-1188 baseline_delta elevated",
}


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("mdc3_audit_under_test", AUDIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_audit(cwd: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(AUDIT)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"audit.py failed: {proc.stderr[-800:]}"
    report = cwd / "report.json"
    assert report.exists(), "report.json was not written"
    return report.read_text(encoding="utf-8")


class _ReportCache:
    _raw: str | None = None

    @classmethod
    def raw(cls) -> str:
        if cls._raw is None:
            with tempfile.TemporaryDirectory() as td:
                cls._raw = _run_audit(Path(td))
        return cls._raw

    @classmethod
    def report(cls) -> dict:
        return json.loads(cls.raw())


class GoldSupersessionTests(unittest.TestCase):
    """The superseded ticket must not be audited; successor is effective."""

    def test_effective_ticket_set_from_authoritative_tickets(self):
        tickets = json.loads(
            (CASE / "data" / "tickets.json").read_text(encoding="utf-8")
        )["tickets"]
        expected = sorted(
            t["change_id"]
            for t in tickets
            if t.get("site") == "MDC-3" and t.get("superseded_by") is None
        )
        report = _ReportCache.report()
        got = [c["change_id"] for c in report["changes"]]
        self.assertEqual(got, expected)

    def test_out_of_site_ticket_is_excluded(self):
        tickets = json.loads((CASE / "data" / "tickets.json").read_text(encoding="utf-8"))["tickets"]
        offsite = next(t for t in tickets if t["change_id"] == "CHG-2026-1255")
        self.assertEqual(offsite["site"], "MDC-2")
        self.assertNotIn("CHG-2026-1255", [c["change_id"] for c in _ReportCache.report()["changes"]])

    def test_superseded_changes_list(self):
        report = _ReportCache.report()
        self.assertEqual(
            report["superseded_changes"],
            [{"change_id": "CHG-2026-1147", "superseded_by": "CHG-2026-1188"}],
        )

    def test_supersession_note_exact(self):
        self.assertIn(
            "supersession: CHG-2026-1147 superseded by CHG-2026-1188",
            _ReportCache.report()["report_notes"],
        )


class GoldWeakOverlapFactTests(unittest.TestCase):
    """The post-window marker needs a join across unlike controller and
    syslog vocabulary. The sources share only numeric/interface identifiers
    and near-adjacent times after the +02:00 timestamp is normalized."""

    @classmethod
    def setUpClass(cls):
        cls.report = _ReportCache.report()
        cls.log_text = (CASE / "logs" / "switch_fabric.log").read_text(
            encoding="utf-8"
        )

    def test_late_warning_corroboration_line(self):
        # The corroborating syslog line is 2026-10-01 00:00:04 +02:00 local
        # == 2026-09-30 22:00:04 UTC, i.e. 4s AFTER the 22:00:00Z window end.
        # It only lines up once the +02:00 wall clock is converted to UTC; the
        # line has no shared 'prefix_recount' token with the controller event.
        m = re.search(
            r"^2026-10-01 00:00:04 \+02:00 .*ifIndex=408 route-admission-count \+2 sample=42$",
            self.log_text,
            re.MULTILINE,
        )
        self.assertIsNotNone(m, "expected corroborating switch syslog line")
        local = datetime.fromisoformat("2026-10-01T00:00:04+02:00")
        self.assertEqual(local.astimezone(timezone.utc).isoformat(), "2026-09-30T22:00:04+00:00")
        events = [json.loads(line) for line in (CASE / "logs" / "controller_events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        marker = next(e for e in events if e.get("event_type") == "network.audit_marker")
        self.assertEqual(marker["ts"], "2026-09-30T22:00:03Z")
        self.assertEqual(marker["change_id"], "CHG-2026-1201")
        self.assertEqual(marker["detail"], "metric=2; port_index=408; sample=42; post-window check")

    def test_report_flags_the_conflict(self):
        notes = self.report["report_notes"]
        self.assertIn(
            "conflict: ops channel claim contradicts controller record "
            "for CHG-2026-1193",
            notes,
        )

    def test_report_flags_the_weak_overlap_join(self):
        self.assertIn(
            "conflict: CHG-2026-1201 controller marker corroborated by switch record at UTC 2026-09-30T22:00:04Z",
            self.report["report_notes"],
        )

    def test_every_policy_note_is_present(self):
        self.assertTrue(REQUIRED_NOTES.issubset(set(self.report["report_notes"])))

    def test_window_note_present(self):
        self.assertIn(
            "window: CHG-2026-1201 event at or after window end",
            self.report["report_notes"],
        )

    def test_channel_claim_is_contradicted_by_controller(self):
        # Informal claim (channel): 1193 "done, no issues".
        channel = (CASE / "docs" / "comms" / "ops_channel.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("1193", channel)
        # Authoritative controller completion at 19:55:47Z includes 18 CRC
        # errors and 0.91% loss, contradicting the channel's clean/no-error claim.
        events = [
            json.loads(line)
            for line in (CASE / "logs" / "controller_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        completed = [
            e
            for e in events
            if e["change_id"] == "CHG-2026-1193"
            and e["event_type"] == "change.completed"
        ]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["ts"], "2026-09-30T19:55:47Z")
        self.assertIn("18 CRC errors", completed[0]["detail"])
        self.assertIn("0.91% loss", completed[0]["detail"])

    def test_unattributed_events_count(self):
        tickets = {
            t["change_id"]
            for t in json.loads(
                (CASE / "data" / "tickets.json").read_text(encoding="utf-8")
            )["tickets"]
            if t.get("site") == "MDC-3"
        }
        events = [
            json.loads(line)
            for line in (CASE / "logs" / "controller_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        expected = sum(
            1
            for e in events
            if e.get("change_id") is None or e.get("change_id") not in tickets
        )
        self.assertEqual(self.report["unattributed_events"], expected)
        self.assertGreater(expected, 0)

    def test_approval_note_matches_self_approval_rule(self):
        report = _ReportCache.report()
        change = next(c for c in report["changes"] if c["change_id"] == "CHG-2026-1210")
        self.assertEqual(change["status"], "rejected")
        self.assertIn("approval: CHG-2026-1210 lacks an independent network engineering lead approval", report["report_notes"])

    def test_exact_site_scope_and_hour_win_over_decoys(self):
        baseline = json.loads((CASE / "data" / "baseline.json").read_text(encoding="utf-8"))
        tickets = json.loads((CASE / "data" / "tickets.json").read_text(encoding="utf-8"))["tickets"]
        ticket = next(t for t in tickets if t["change_id"] == "CHG-2026-1188")
        rows = [json.loads(line) for line in (CASE / "data" / "telemetry.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        at_hour = [r for r in rows if r["hour_utc"] == "2026-09-30T23:00:00Z"]
        exact = [r for r in at_hour if r["site"] == "MDC-3" and r["scope"] == ticket["link_scope"] == baseline["scope"]]
        self.assertEqual(len(exact), 1)
        self.assertGreater(max(r["avg_loss_pct"] for r in at_hour if r not in exact), exact[0]["avg_loss_pct"])
        change = next(c for c in _ReportCache.report()["changes"] if c["change_id"] == "CHG-2026-1188")
        self.assertEqual(change["post_change_loss_pct"], exact[0]["avg_loss_pct"])
