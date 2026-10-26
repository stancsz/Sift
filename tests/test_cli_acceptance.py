import copy
import unittest
from unittest.mock import patch

from benchmarks.cli_acceptance import historical_gold_retained, inject_history, native_evidence


class CLIHarnessTests(unittest.TestCase):
    def test_real_compaction_finds_injected_source_after_instruction_prefix(self):
        try:
            from sift.litellm_proxy import compact_proxy_request
        except ImportError:
            self.skipTest("install sift-context[litellm]")
        import json

        class Counter:
            def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
                return len(json.dumps(messages)) // 4

        data = inject_history({"messages": [{"role": "system", "content": "exact"},
                              {"role": "user", "content": "Find acceptance_delay_seconds"}]}, lines=200)
        result = compact_proxy_request(Counter(), data, call_type="acompletion", target=1000)
        self.assertTrue(result["metadata"]["sift"]["compacted"])
        self.assertTrue(historical_gold_retained(result["messages"], 0))

    def test_current_echo_does_not_count_as_retained_historical_gold(self):
        echo = {"role": "user", "content": "acceptance_delay_seconds=37"}
        self.assertFalse(historical_gold_retained([echo], 0))
        summary = {"role": "user", "content": 'Earlier conversation, lossily excerpted\n[message 0 user] "acceptance_delay_seconds=37"'}
        self.assertTrue(historical_gold_retained([summary, echo], 0))
        self.assertFalse(historical_gold_retained([summary, echo], 1))

    def test_three_reads_without_native_workflow_cannot_pass(self):
        events = [{"type": "tool_use", "part": {"type": "tool", "callID": str(i), "tool": "read",
                   "state": {"status": "completed", "input": {"filePath": "task.py"}}}} for i in range(3)]
        events.append({"type": "step_finish", "part": {"reason": "stop"}})
        result = native_evidence("opencode", events)
        self.assertTrue(result["terminal_success"])
        self.assertFalse(result["workflow_ordered"])
    def test_proxy_dispatches_request_body_to_sift_and_preserves_guard_error(self):
        try:
            from fastapi import HTTPException
            from fastapi.testclient import TestClient
            from benchmarks.cli_acceptance import make_app
        except ImportError:
            self.skipTest("install sift-context[litellm]")
        audits = []
        app = make_app("http://127.0.0.1:4000/v1", "test-only", "default", 400, audits)
        error = HTTPException(413, "Sift: input limit", headers={"x-sift-error-code": "input_size_limit"})
        with patch("sift.litellm_proxy.SiftLiteLLMHook._compact", side_effect=error) as compact:
            with TestClient(app) as client:
                response = client.post("/v1/messages", json={"messages": [{"role": "user", "content": "task"}]})
        self.assertEqual(compact.call_count, 1)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["x-sift-error-code"], "input_size_limit")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["sift_error"], "input_size_limit")
        self.assertEqual(audits[0]["input_shapes"], [{"role": "user", "keys": ["content", "role"]}])

    def test_injection_preserves_instruction_roles_tools_and_current_cycle(self):
        for protocol in ("chat", "anthropic"):
            messages = [{"role": "system", "content": "exact instructions"}] if protocol == "chat" else []
            messages += [{"role": "user", "content": "latest task"},
                         {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "read", "input": {}}]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "exact result"}]}]
            data = {"messages": messages, "system": "top-level exact", "tools": [{"name": "read"}]}
            saved = copy.deepcopy(data)
            result = inject_history(data, lines=20)
            self.assertEqual(data, saved)
            self.assertEqual(result["messages"][-3:], messages[-3:])
            self.assertEqual(result["tools"], data["tools"])
            self.assertEqual(result["system"], data["system"])
            if protocol == "chat":
                self.assertEqual(result["messages"][0], messages[0])
            self.assertIn("acceptance_delay_seconds=37", str(result))

    def test_claude_requires_real_successful_tool_results_and_terminal_success(self):
        events = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "Write"}]}},
                  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "is_error": False}]}},
                  {"type": "result", "subtype": "success", "is_error": False}]
        result = native_evidence("claude", events)
        self.assertEqual(result["successful_tools"], ["Write"])
        self.assertTrue(result["terminal_success"])
        self.assertFalse(native_evidence("claude", [{"type": "assistant", "message": {"content": "I wrote it"}}])["terminal_success"])
        events[1]["message"]["content"][0]["is_error"] = True
        self.assertEqual(native_evidence("claude", events)["successful_tools"], [])

    def test_opencode_error_and_incomplete_events_do_not_pass(self):
        event = {"type": "tool_use", "part": {"type": "tool", "callID": "a", "tool": "edit", "state": {"status": "completed"}}}
        events = [event, {"type": "step_finish", "part": {"reason": "stop"}}]
        self.assertEqual(native_evidence("opencode", events)["successful_tools"], ["edit"])
        self.assertTrue(native_evidence("opencode", events)["terminal_success"])
        events.append({"type": "error", "error": "failed"})
        self.assertFalse(native_evidence("opencode", events)["terminal_success"])
        event["part"]["state"]["status"] = "running"
        self.assertEqual(native_evidence("opencode", [event])["completed"], 0)
