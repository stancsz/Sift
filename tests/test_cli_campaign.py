import unittest
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.cli_acceptance import native_evidence
from benchmarks.cli_campaign import parse_events, recovered_disconnect_count, session_id
from benchmarks.cli_matrix import pending_jobs, run, schedule


class CampaignTests(unittest.TestCase):
    def test_disconnect_requires_later_success_for_the_identical_request(self):
        error = {"upstream_status": 500, "upstream_transport_error": "provider_connection_closed", "request_sha256": "same", "response_finished_at": 1.0}
        success = {"upstream_status": 200, "request_sha256": "same", "request_received_at": 2.0}
        self.assertEqual(recovered_disconnect_count([success]), 0)
        self.assertEqual(recovered_disconnect_count([error, success]), 1)
        self.assertEqual(recovered_disconnect_count([error, error, success]), 2)
        for audits in ([success, error], [error], [error, dict(success, request_sha256="different")],
                       [dict(error, upstream_transport_error=None), success],
                       [dict(error, upstream_status=429), success],
                       [error, dict(success, request_received_at=.5)],
                       [dict(error, response_finished_at=None), success],
                       [dict(error, request_sha256=None), dict(success, request_sha256=None)]):
            self.assertIsNone(recovered_disconnect_count(audits))

    def test_completed_checkpoint_resume_does_not_dispatch_or_discard_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = []
            for client, task, repeat in schedule():
                name = f"{client}-{task}-{repeat+1}"
                receipt = {"accepted": True, "source_sha256": {"sift": "current"},
                           "active_client_seconds": 186, "turns": [{}] * 6}
                (root / (name + ".json")).write_text(json.dumps(receipt), encoding="utf8")
                records.append({"name": name, "accepted": True, "key_revoked": True, "receipt": name + ".json"})
            attempts = [{"name": "prior-provider-failure", "accepted": False, "key_revoked": True}] + records
            previous = {"source_sha256": {"sift": "current"}, "active_sessions": [],
                        "records": records, "attempts": attempts}
            (root / "matrix.json").write_text(json.dumps(previous), encoding="utf8")
            args = SimpleNamespace(output_dir=root, resume=True, control_key_env="SIFT_TEST_CONTROL")
            with patch.dict(os.environ, {"SIFT_TEST_CONTROL": "synthetic"}), \
                 patch("benchmarks.cli_matrix.source_hashes", return_value={"sift": "current"}), \
                 patch("httpx.Client") as network:
                self.assertTrue(run(args))
                network.assert_not_called()
            result = json.loads((root / "matrix.json").read_text(encoding="utf8"))
            self.assertTrue(result["complete"])
            self.assertEqual(result["attempts"], attempts)

    def test_resume_rejects_changed_source_active_sessions_and_unrevoked_keys_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(output_dir=root, resume=True, control_key_env="SIFT_TEST_CONTROL")
            baseline = {"source_sha256": {"sift": "current"}, "active_sessions": [], "records": [], "attempts": []}
            invalid = [dict(baseline, source_sha256={"sift": "old"}),
                       dict(baseline, active_sessions=[{"name": "unfinished"}]),
                       dict(baseline, attempts=[{"key_revoked": False}])]
            for receipt in invalid:
                (root / "matrix.json").write_text(json.dumps(receipt), encoding="utf8")
                with patch.dict(os.environ, {"SIFT_TEST_CONTROL": "synthetic"}), \
                     patch("benchmarks.cli_matrix.source_hashes", return_value={"sift": "current"}), \
                     self.assertRaises(ValueError):
                    run(args)

    def test_recovery_skips_only_accepted_cases_and_keeps_failed_cases_pending(self):
        records = [{"name": "claude-expenses-1", "accepted": True},
                   {"name": "opencode-expenses-1", "accepted": False}]
        jobs = pending_jobs(records)
        self.assertEqual(len(jobs), 26)
        self.assertNotIn(("claude", "expenses", 0), jobs)
        self.assertIn(("opencode", "expenses", 0), jobs)
        self.assertEqual(len(pending_jobs([])), 27)

    def test_matrix_covers_all_three_clients_tasks_and_repetitions(self):
        jobs = schedule()
        self.assertEqual(len(jobs), 27)
        self.assertEqual(len(set(jobs)), 27)
        for client in ("codex", "claude", "opencode"):
            for task in ("engineering", "migration", "expenses"):
                self.assertEqual({repeat for c, t, repeat in jobs if c == client and t == task}, {0, 1, 2})

    def test_native_session_identity_is_required_and_protocol_specific(self):
        cases = [("codex", {"type": "thread.started", "thread_id": "owned-id"}),
                 ("claude", {"type": "result", "session_id": "owned-id"}),
                 ("opencode", {"type": "step_start", "sessionID": "owned-id"})]
        for client, event in cases:
            self.assertEqual(session_id(client, [event]), "owned-id")
            self.assertIsNone(session_id(client, []))
        self.assertEqual(parse_events('not json\n{"type":"turn.completed"}\n'), [{"type": "turn.completed"}])

    def test_codex_native_command_and_patch_events_prove_workflow(self):
        def command(index, text, output, code):
            return {"type": "item.completed", "item": {"id": str(index), "type": "command_execution",
                    "command": '"C:/runtime/pwsh.exe" -Command \'' + text + "'",
                    "aggregated_output": output, "exit_code": code, "status": "completed"}}
        events = [command(0, "Get-Content task.py", "def clamp(value):", 0),
                  command(1, "Get-Content test_task.py", "class Checks:", 0),
                  command(2, '& "C:/python.exe" -m unittest -q', "Ran 2 tests\nFAILED", 1),
                  {"type": "item.completed", "item": {"id": "patch", "type": "file_change", "status": "completed",
                   "changes": [{"path": "C:/workspace/task.py"}, {"path": "C:/workspace/evidence.json"}]}},
                  command(4, '& "C:/python.exe" -m unittest -q', "Ran 2 tests\nOK", 0),
                  {"type": "turn.completed"}]
        result = native_evidence("codex", events)
        self.assertEqual(result["calls"], 5)
        self.assertTrue(result["workflow_ordered"])
        self.assertTrue(result["baseline_failed"])
        self.assertTrue(result["final_passed"])
        self.assertFalse(native_evidence("codex", events[1:])["workflow_ordered"])
        self.assertFalse(native_evidence("codex", events[:-2] + [{"type": "turn.completed"}])["workflow_ordered"])
