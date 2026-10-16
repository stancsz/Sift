import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from evidence_retention import (
    assess_pre_edit_retention,
    audit_retention,
    first_direct_edit_timestamp_ns,
    load_required_spans,
    parse_selection_events,
)


class EvidenceRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "bench"
        self.gold = self.root / "agent_gold" / "fixture_one"
        self.case = self.root / "agent_cases" / "fixture_one"
        self.gold.mkdir(parents=True)
        self.case.mkdir(parents=True)
        self.source = 'header\nCafé marker = "exact-required-evidence"\ncontinued\nfooter\n'
        (self.case / "source.txt").write_text(self.source, encoding="utf-8")
        self.span_text = 'Café marker = "exact-required-evidence"\ncontinued'
        start = self.source.index(self.span_text)
        self.manifest = self.gold / "evidence.json"
        self._write_manifest(start, start + len(self.span_text))

    def tearDown(self):
        self.temp.cleanup()

    def _write_manifest(self, start, end, *, digest=None, source_file="source.txt"):
        value = self.source[start:end]
        data = {
            "schema_version": 1,
            "fixture": "fixture_one",
            "required_spans": [{
                "id": "e001",
                "source": {"file": source_file, "start_char": start, "end_char": end},
                "sha256": digest or hashlib.sha256(value.encode("utf-8")).hexdigest(),
            }],
        }
        self.manifest.write_text(json.dumps(data), encoding="utf-8")

    def test_loads_exact_utf8_character_span_from_confined_fixture(self):
        spans = load_required_spans(self.manifest)
        self.assertEqual([(span.span_id, span.text) for span in spans], [("e001", self.span_text)])

    def test_audits_retained_omitted_missing_and_introduced_spans_without_text(self):
        spans = load_required_spans(self.manifest)
        source_message = {"role": "tool", "content": self.span_text}
        messages = [source_message, {"role": "user", "content": "Other request"}]
        forwarded = [{"role": "user", "content": "quoted " + json.dumps(self.span_text, ensure_ascii=False)}]
        self.assertEqual(audit_retention(messages, forwarded, spans), {"e001": "retained"})

        self.assertEqual(audit_retention(messages, [], spans), {"e001": "omitted"})
        self.assertEqual(audit_retention([], [], spans), {"e001": "not_in_input"})
        self.assertEqual(audit_retention([], [source_message], spans), {"e001": "forwarded_only"})
        report = json.dumps(audit_retention(messages, forwarded, spans))
        self.assertNotIn(self.span_text, report)

    def test_hash_mismatch_and_path_escape_fail_closed(self):
        start = self.source.index(self.span_text)
        self._write_manifest(start, start + len(self.span_text), digest="0" * 64)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            load_required_spans(self.manifest)

        self._write_manifest(start, start + len(self.span_text), source_file="../outside.txt")
        with self.assertRaisesRegex(ValueError, "invalid source coordinates"):
            load_required_spans(self.manifest)

    def test_public_rollup_annotations_match_the_frozen_source_spans(self):
        root = Path(__file__).resolve().parents[1]
        spans = load_required_spans(
            root / "benchmarks" / "agent_gold" / "least_privilege_rollup" / "evidence.json"
        )
        raw = [{"role": "tool", "content": span.text} for span in spans]
        forwarded = [{
            "role": "user",
            "content": "\n".join(json.dumps(span.text, ensure_ascii=False) for span in spans),
        }]
        self.assertEqual(
            audit_retention(raw, forwarded, spans),
            {span.span_id: "retained" for span in spans},
        )

    def test_native_trace_and_gateway_event_prove_or_reject_pre_edit_order(self):
        trace = self.root / "native.stdout.jsonl"
        trace.write_text(json.dumps({
            "type": "assistant",
            "timestamp": "1970-01-01T00:00:00.000001Z",
            "message": {"content": [{
                "type": "tool_use", "name": "Edit",
                "input": {"file_path": r"C:\case\workspace\audit_rollup.py"},
            }]},
        }) + "\n", encoding="utf-8")
        edit_time = first_direct_edit_timestamp_ns(
            trace, r"C:\case\workspace", {"audit_rollup.py"},
        )
        self.assertEqual(edit_time, 1_000)

        before = parse_selection_events(
            "INFO sift_benchmark_selection selector=sift request_seq=7 "
            "observed_utc_ns=100 status=ok input_tokens=100 forwarded_tokens=50 evidence=e001:retained"
        )
        report = assess_pre_edit_retention(before, edit_time, {"e001"})
        self.assertEqual(report["status"], "verified_before_edit")
        self.assertEqual(report["request_seq"], 7)

        after = parse_selection_events(
            "INFO sift_benchmark_selection selector=sift request_seq=8 "
            "observed_utc_ns=1100 status=ok input_tokens=100 forwarded_tokens=50 evidence=e001:retained"
        )
        self.assertEqual(
            assess_pre_edit_retention(after, edit_time, {"e001"})["status"],
            "after_edit",
        )

        omitted = parse_selection_events(
            "INFO sift_benchmark_selection selector=sift request_seq=9 "
            "observed_utc_ns=100 status=ok input_tokens=100 forwarded_tokens=50 evidence=e001:omitted"
        )
        self.assertEqual(
            assess_pre_edit_retention(omitted, edit_time, {"e001"})["status"],
            "required_span_not_retained",
        )

        unchanged = parse_selection_events(
            "INFO sift_benchmark_selection selector=sift request_seq=10 "
            "observed_utc_ns=100 status=ok input_tokens=100 forwarded_tokens=100 evidence=e001:retained"
        )
        self.assertEqual(
            assess_pre_edit_retention(unchanged, edit_time, {"e001"})["status"],
            "no_compaction_before_edit",
        )

    def test_edit_order_is_unknown_for_unsupported_or_out_of_workspace_edits(self):
        trace = self.root / "native.stdout.jsonl"
        trace.write_text(json.dumps({
            "type": "assistant",
            "timestamp": "1970-01-01T00:00:00.000001Z",
            "message": {"content": [{
                "type": "tool_use", "name": "Edit",
                "input": {"file_path": r"C:\outside\audit_rollup.py"},
            }]},
        }) + "\n", encoding="utf-8")
        self.assertIsNone(first_direct_edit_timestamp_ns(
            trace, r"C:\case\workspace", {"audit_rollup.py"},
        ))

    def test_cli_emits_a_body_free_verified_report(self):
        workspace = self.root / "workspace"
        workspace.mkdir()
        trace = self.root / "native.stdout.jsonl"
        trace.write_text(json.dumps({
            "type": "assistant",
            "timestamp": "1970-01-01T00:00:00.000001Z",
            "message": {"content": [{
                "type": "tool_use", "name": "Edit",
                "input": {"file_path": str(workspace / "audit_rollup.py")},
            }]},
        }) + "\n", encoding="utf-8")
        gateway = self.root / "gateway.log"
        gateway.write_text(
            "INFO sift_benchmark_selection selector=sift request_seq=4 "
            "observed_utc_ns=500 status=ok input_tokens=100 forwarded_tokens=50 evidence=e001:retained\n",
            encoding="utf-8",
        )
        script = Path(__file__).resolve().parents[1] / "benchmarks" / "audit_native_evidence.py"
        completed = subprocess.run([
            sys.executable, str(script), "--gateway-log", str(gateway),
            "--native-trace", str(trace), "--workspace", str(workspace),
            "--manifest", str(self.manifest), "--editable", "audit_rollup.py",
        ], capture_output=True, text=True, check=False, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "verified_before_edit")
        self.assertEqual(report["request_seq"], 4)
        self.assertNotIn(self.span_text, completed.stdout)


if __name__ == "__main__":
    unittest.main()
