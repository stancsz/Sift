"""Visible baseline tests for the MDC-3 change audit.

Run from the workspace root:
    python -m unittest discover -s case -p "test_task.py"

These tests describe the contract for `case/audit.py`. The starter stub in
`case/audit.py` is intentionally non-functional and MUST fail this suite
until the audit is implemented.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CASE = Path(__file__).resolve().parent


def _run_audit_once() -> tuple[dict | None, str | None, subprocess.CompletedProcess]:
    with tempfile.TemporaryDirectory() as td:
        proc = subprocess.run(
            [sys.executable, str(CASE / "audit.py")],
            cwd=td,
            capture_output=True,
            text=True,
            timeout=120,
        )
        report_path = Path(td) / "report.json"
        if proc.returncode != 0 or not report_path.exists():
            return None, None, proc
        raw = report_path.read_text(encoding="utf-8")
        return json.loads(raw), raw, proc


class TaskBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._report, cls._raw, cls.audit_process = _run_audit_once()

    @property
    def report(self) -> dict:
        self.assertEqual(
            self.audit_process.returncode,
            0,
            f"audit.py exited nonzero: {self.audit_process.stderr[-800:]}",
        )
        self.assertIsNotNone(self._report, "audit.py did not write report.json in cwd")
        return self._report

    @property
    def raw(self) -> str:
        _ = self.report
        return self._raw

    # -- schema -----------------------------------------------------------

    def test_top_level_schema(self):
        r = self.report
        self.assertEqual(r["schema_version"], 3)
        self.assertEqual(r["datacenter"], "MDC-3")
        self.assertEqual(r["window_closed_utc"], "2026-09-30T22:00:00Z")
        self.assertEqual(
            list(r.keys()),
            [
                "schema_version",
                "datacenter",
                "window_closed_utc",
                "changes",
                "superseded_changes",
                "unattributed_events",
                "report_notes",
            ],
        )

    def test_change_entry_schema(self):
        for c in self.report["changes"]:
            self.assertEqual(
                list(c.keys()),
                [
                    "change_id",
                    "severity",
                    "status",
                    "window_id",
                    "in_window",
                    "approvals",
                    "rolled_back",
                    "post_change_loss_pct",
                    "baseline_loss_pct",
                    "loss_delta_pp",
                    "baseline_delta",
                ],
            )
            self.assertEqual(
                list(c["approvals"].keys()), ["requested_by", "approved_by"]
            )

    # -- supersession -----------------------------------------------------

    def test_supersession(self):
        r = self.report
        self.assertEqual(
            r["superseded_changes"],
            [{"change_id": "CHG-2026-1147", "superseded_by": "CHG-2026-1188"}],
        )
        ids = [c["change_id"] for c in r["changes"]]
        self.assertNotIn("CHG-2026-1147", ids)
        self.assertIn("CHG-2026-1188", ids)
        self.assertEqual(
            ids,
            ["CHG-2026-1188", "CHG-2026-1193", "CHG-2026-1201", "CHG-2026-1210"],
        )
        self.assertTrue(
            any(
                n.startswith("supersession:")
                and "CHG-2026-1147" in n
                and "CHG-2026-1188" in n
                for n in r["report_notes"]
            ),
            "expected a supersession report note",
        )

    # -- window boundary ---------------------------------------------------

    def test_window_boundary_inclusive_end(self):
        r = self.report
        by_id = {c["change_id"]: c for c in r["changes"]}
        # 1201 has a controller event exactly at 22:00:00Z (inclusive
        # boundary) plus a 22:00:03Z event after window end.
        self.assertIs(by_id["CHG-2026-1201"]["in_window"], False)
        # 1188 events are strictly inside MW-2026-118.
        self.assertIs(by_id["CHG-2026-1188"]["in_window"], True)
        self.assertEqual(by_id["CHG-2026-1188"]["window_id"], "MW-2026-118")

    # -- approvals (policy matrix) -----------------------------------------

    def test_approval_matrix(self):
        by_id = {c["change_id"]: c for c in self.report["changes"]}
        a = by_id["CHG-2026-1188"]["approvals"]
        self.assertEqual(a["requested_by"], "dana.ferro")
        self.assertEqual(a["approved_by"], ["p.sandoval"])
        self.assertEqual(by_id["CHG-2026-1188"]["status"], "approved")
        # 1210 is critical and self-approved by the requester -> invalid.
        self.assertEqual(by_id["CHG-2026-1210"]["status"], "rejected")
        self.assertEqual(
            by_id["CHG-2026-1210"]["approvals"]["requested_by"], "j.blythe"
        )
        # 1255 is an MDC-2 ticket; it must not appear at all.
        self.assertNotIn("CHG-2026-1255", by_id)

    # -- telemetry judgment ------------------------------------------------

    def test_post_change_baseline_delta(self):
        by_id = {c["change_id"]: c for c in self.report["changes"]}
        for cid in ("CHG-2026-1188", "CHG-2026-1193", "CHG-2026-1201",
                    "CHG-2026-1210"):
            c = by_id[cid]
            self.assertEqual(c["baseline_loss_pct"], 0.02)
            self.assertGreater(c["post_change_loss_pct"], 0.0)
            self.assertEqual(c["loss_delta_pp"], round(c["post_change_loss_pct"] - 0.02, 4))
            expected = "elevated" if c["loss_delta_pp"] > 0.5 else "normal"
            self.assertEqual(c["baseline_delta"], expected)
        self.assertEqual(by_id["CHG-2026-1188"]["post_change_loss_pct"], 0.782)
        self.assertEqual(by_id["CHG-2026-1188"]["baseline_delta"], "elevated")

    # -- determinism -------------------------------------------------------

    def test_deterministic_output(self):
        again, raw_again, process_again = _run_audit_once()
        self.assertEqual(process_again.returncode, 0, process_again.stderr[-800:])
        self.assertIsNotNone(again, "audit.py did not write report.json in cwd")
        self.assertEqual(again, self.report)
        self.assertEqual(raw_again, self.raw)
        self.assertTrue(self.raw.endswith("\n"), "report.json must end with newline")


if __name__ == "__main__":
    unittest.main()
