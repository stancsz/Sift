import unittest
from pathlib import Path

import reconcile


ROOT = Path(__file__).resolve().parent


class ReconcileVisibleTests(unittest.TestCase):
    def test_current_export_returns_report_with_integer_cents(self):
        report = reconcile.make_report(
            ROOT / "orders.csv",
            ROOT / "current_export.csv",
            as_of="2025-02-01",
        )
        self.assertEqual(report["as_of"], "2025-02-01")
        self.assertEqual(len(report["orders"]), 7)
        self.assertEqual(report["orders"][0]["order_id"], "ORD-8101")
        self.assertEqual(report["orders"][0]["expected_cents"], 12_000)
        self.assertIs(type(report["orders"][0]["settled_net_cents"]), int)
        self.assertEqual(report["totals"]["expected_by_currency"], {"USD": 32_079})


if __name__ == "__main__":
    unittest.main()
