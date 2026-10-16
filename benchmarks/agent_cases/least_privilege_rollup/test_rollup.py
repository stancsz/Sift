import json, subprocess, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT/"access_rollup.json"
SCRIPT=ROOT/"audit_rollup.py"
class VisibleContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable,str(SCRIPT)],check=True,cwd=ROOT)
        cls.report=json.loads(OUTPUT.read_text(encoding="utf-8"))
    def test_schema_and_window(self):
        self.assertEqual(self.report["subject"],"alice.chen@stratus.example")
        self.assertEqual(self.report["review_window"],{"start":"2026-07-18","end":"2026-10-16"})
        self.assertTrue({"approved","unused","policy_blocked"}.issubset(self.report))
        self.assertEqual(len(self.report["approved"])+len(self.report["unused"]),6)
        self.assertEqual(len(self.report["policy_blocked"]),3)
    def test_permission_entries_are_structured(self):
        for key in ("approved","unused","policy_blocked"):
            for item in self.report[key]:
                self.assertEqual(set(item),{"action","resource"})
    def test_report_is_deterministic(self):
        first=OUTPUT.read_bytes()
        subprocess.run([sys.executable,str(SCRIPT)],check=True,cwd=ROOT)
        self.assertEqual(OUTPUT.read_bytes(),first)
    def test_approval_and_block_lists_do_not_overlap(self):
        pairs=lambda key:{(x["action"],x["resource"]) for x in self.report[key]}
        self.assertFalse(pairs("approved") & pairs("policy_blocked"))
if __name__=="__main__": unittest.main()
