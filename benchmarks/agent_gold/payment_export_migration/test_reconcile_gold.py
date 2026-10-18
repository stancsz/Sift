import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import reconcile


ROOT = Path(__file__).resolve().parent


class PaymentExportAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = reconcile.make_report(
            ROOT / "orders.csv", ROOT / "current_export.csv", as_of="2025-02-01"
        )
        cls.orders = {row["order_id"]: row for row in cls.report["orders"]}
        cls.exceptions = {(row["code"], row["event_id"]): row
                          for row in cls.report["exceptions"]}

    def test_settlement_logic_and_duplicates(self):
        self.assertEqual(self.orders["ORD-8101"]["settled_net_cents"], 10_000)
        self.assertEqual(self.orders["ORD-8101"]["status"], "partial_refund")
        self.assertEqual(self.orders["ORD-8101"]["included_event_ids"], ["E-1001", "E-1002"])
        self.assertNotIn("E-1002", self.orders["ORD-8102"]["included_event_ids"])
        self.assertEqual(self.orders["ORD-8102"]["settled_net_cents"], 0)
        self.assertEqual(self.orders["ORD-8102"]["status"], "refunded")
        self.assertEqual(self.orders["ORD-8102"]["included_event_ids"], ["E-2001", "E-2002"])
        self.assertIn(("duplicate_event", "E-1002"), self.exceptions)
        self.assertIn(("orphan_refund", "E-9001"), self.exceptions)

    def test_mismatches_pending_and_totals_are_not_hidden(self):
        self.assertEqual(self.orders["ORD-8103"]["settled_net_cents"], 7_800)
        self.assertEqual(self.orders["ORD-8103"]["status"], "amount_mismatch")
        self.assertEqual(self.orders["ORD-8104"]["settled_net_cents"], 0)
        self.assertEqual(self.orders["ORD-8104"]["status"], "currency_mismatch")
        self.assertEqual(self.orders["ORD-8105"]["settled_net_cents"], 0)
        self.assertEqual(self.orders["ORD-8105"]["status"], "pending")
        self.assertEqual(self.orders["ORD-8106"]["settled_net_cents"], 1_234)
        self.assertEqual(self.orders["ORD-8106"]["status"], "paid")
        self.assertEqual(self.orders["ORD-8106"]["included_event_ids"], ["E-6001"])
        self.assertEqual(self.orders["ORD-8107"]["settled_net_cents"], 0)
        self.assertEqual(self.orders["ORD-8107"]["status"], "pending")
        self.assertEqual(self.orders["ORD-8107"]["included_event_ids"], [])
        self.assertEqual(self.report["totals"]["expected_by_currency"], {"USD": 32_079})
        self.assertEqual(self.report["totals"]["settled_by_currency"], {"USD": 19_034})
        self.assertIn(("amount_mismatch", "E-3001"), self.exceptions)
        self.assertIn(("currency_mismatch", "E-4001"), self.exceptions)

    def test_order_and_exception_sorting_are_deterministic(self):
        ids = [row["order_id"] for row in self.report["orders"]]
        self.assertEqual(ids, sorted(ids))
        exception_keys = [(row["code"], row["event_id"])
                          for row in self.report["exceptions"]]
        self.assertEqual(exception_keys, sorted(exception_keys))
        self.assertEqual(
            reconcile.make_report(ROOT / "orders.csv", ROOT / "current_export.csv",
                                  as_of="2025-02-01"),
            self.report,
        )

    def test_cli_json_output_and_nonzero_conflicting_duplicate(self):
        run = subprocess.run(
            [sys.executable, str(ROOT / "reconcile.py"), "--orders", str(ROOT / "orders.csv"),
             "--events", str(ROOT / "current_export.csv"), "--as-of", "2025-02-01"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), self.report)

        with tempfile.TemporaryDirectory() as temporary:
            conflicting = Path(temporary) / "events.csv"
            with (ROOT / "current_export.csv").open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            rows.append({**rows[0], "amount": "2001"})
            with conflicting.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.DictWriter(destination, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            failed = subprocess.run(
                [sys.executable, str(ROOT / "reconcile.py"), "--orders", str(ROOT / "orders.csv"),
                 "--events", str(conflicting), "--as-of", "2025-02-01"],
                capture_output=True, text=True, check=False,
            )
        self.assertNotEqual(failed.returncode, 0)
        self.assertTrue(failed.stderr.strip())


if __name__ == "__main__":
    unittest.main()
