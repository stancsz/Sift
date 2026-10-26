import unittest

from benchmarks.cli_acceptance import native_evidence
from benchmarks.cli_campaign import parse_events, session_id
from benchmarks.cli_matrix import schedule


class CampaignTests(unittest.TestCase):
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
