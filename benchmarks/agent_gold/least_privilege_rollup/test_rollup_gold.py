import json, subprocess, sys, unittest
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUTPUT=ROOT/"access_rollup.json"
SCRIPT=ROOT/"audit_rollup.py"
DATA=ROOT/"data"
SUBJECT="alice.chen@stratus.example"
START=date(2026,7,18); END=date(2026,10,16)
EXPECTED_APPROVED={
 ("s3:GetObject","arn:aws:s3:::analytics-prod/*"),
 ("s3:GetObject","arn:aws:s3:::logs-archive/*"),
 ("kms:Decrypt","arn:aws:kms:us-east-1:123456789012:key/analytics-key"),
}
EXPECTED_UNUSED={
 ("s3:GetObject","arn:aws:s3:::user-uploads/*"),
 ("dynamodb:Query","arn:aws:dynamodb:us-east-1:123456789012:table/sessions-prod"),
 ("rds:DescribeDBInstances","arn:aws:rds:us-east-1:123456789012:db:prod-cluster"),
}
EXPECTED_BLOCKED=EXPECTED_UNUSED

def run_report():
    subprocess.run([sys.executable,str(SCRIPT)],check=True,cwd=ROOT)
    return json.loads(OUTPUT.read_text(encoding="utf-8"))
def pairs(report,key): return {(x["action"],x["resource"]) for x in report[key]}
def parse_event(line):
    if line.lstrip().startswith("#"):
        return None
    fields=[x.strip() for x in line.split("|")]
    return fields if len(fields)==5 else None

class ExactRollupChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.report=run_report()
    def test_requested_permissions_classified_exactly(self):
        self.assertEqual(pairs(self.report,"approved"),EXPECTED_APPROVED)
        self.assertEqual(pairs(self.report,"unused"),EXPECTED_UNUSED)
        self.assertEqual(pairs(self.report,"policy_blocked"),EXPECTED_BLOCKED)
    def test_every_requested_permission_appears_once_in_used_or_unused(self):
        request=set()
        for line in (DATA/"role_request.txt").read_text(encoding="utf-8").splitlines():
            bits=line.split()
            if len(bits)==2 and not bits[0].startswith("#"): request.add((bits[0],bits[1]))
        self.assertEqual(pairs(self.report,"approved")|pairs(self.report,"unused"),request)
        self.assertFalse(pairs(self.report,"approved")&pairs(self.report,"unused"))
    def test_window_subject_and_result_filtering_has_expected_approved_evidence(self):
        allow=set()
        for path in sorted(DATA.glob("audit_events_*.log")):
            for line in path.read_text(encoding="utf-8").splitlines():
                fields=parse_event(line)
                if not fields: continue
                stamp,actor,action,resource,result=fields
                day=date.fromisoformat(stamp[:10])
                if actor==SUBJECT and result=="ALLOW" and START<=day<=END:
                    allow.add((action,resource))
        self.assertTrue(EXPECTED_APPROVED.issubset(allow))
        self.assertFalse(EXPECTED_UNUSED & allow)
    def test_policy_blocked_findings_are_not_approved(self):
        self.assertFalse(pairs(self.report,"approved")&EXPECTED_BLOCKED)
    def test_output_has_no_volatile_fields_or_absolute_machine_path(self):
        self.assertNotIn("generated_at",self.report)
        self.assertNotIn(str(ROOT),json.dumps(self.report))
if __name__=="__main__": unittest.main()
