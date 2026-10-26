"""Regression for OpenCode's real OpenAI-compatible reasoning continuation."""
import copy
import json
import unittest

from sift import CompactionError, compact_messages


def count(messages):
    return len(json.dumps(messages)) // 4


class ReasoningContentTests(unittest.TestCase):
    def test_retained_reasoning_exact_and_historical_reasoning_not_evidence(self):
        latest = [
            {"role": "assistant", "content": None, "reasoning_content": "current exact reasoning",
             "tool_calls": [{"id": "a", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "approved acceptance_delay_seconds=37"},
        ]
        messages = [
            {"role": "user", "content": "routine archive\n" * 4000},
            {"role": "assistant", "content": "previous work completed", "reasoning_content": "PRIVATE_OLD_REASONING " * 1000},
            {"role": "user", "content": "Find the approved acceptance_delay_seconds"}, *latest,
        ]
        saved = copy.deepcopy(messages)
        result = compact_messages(messages, count, target=1200)
        self.assertTrue(result.audit["compacted"])
        self.assertEqual(result.messages[-2:], latest)
        self.assertNotIn("PRIVATE_OLD_REASONING", str(result.messages))
        self.assertEqual(messages, saved)
        self.assertLessEqual(count(result.messages), 1200)

    def test_invalid_reasoning_role_or_type_still_fails_closed(self):
        for role, value in [("assistant", []), ("assistant", {}), ("assistant", 123), ("user", "text")]:
            messages = [{"role": "user", "content": "archive " * 4000},
                        {"role": role, "content": "text", "reasoning_content": value},
                        {"role": "user", "content": "current task"}]
            with self.subTest(role=role, value=value), self.assertRaises(CompactionError) as caught:
                compact_messages(messages, count, target=1000)
            self.assertEqual(caught.exception.code, "unsupported_content")

    def test_proxy_charges_reasoning_ignored_by_native_counter(self):
        try:
            from fastapi import HTTPException
            from sift.litellm_proxy import compact_proxy_request
        except ImportError:
            self.skipTest("install sift-context[litellm]")

        class IgnoringCounter:
            def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
                return count([{k: v for k, v in msg.items() if k != "reasoning_content"} for msg in messages])

        data = {"messages": [
            {"role": "user", "content": "inspect"},
            {"role": "assistant", "content": None, "reasoning_content": "reasoning " * 4000,
             "tool_calls": [{"id": "a", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "a", "content": "exact result"},
        ]}
        saved = copy.deepcopy(data)
        with self.assertRaises(HTTPException) as caught:
            compact_proxy_request(IgnoringCounter(), data, call_type="acompletion", target=400)
        self.assertEqual(caught.exception.headers["x-sift-error-code"], "active_too_large")
        self.assertGreater(int(caught.exception.headers["x-sift-required-tokens"]), 400)
        self.assertEqual(data, saved)

        class IncludingCounter:
            def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
                return count(messages)

        result = compact_proxy_request(IncludingCounter(), data, call_type="acompletion", target=100000)
        self.assertEqual(result["metadata"]["sift"]["input_tokens"], count(data["messages"]))
        self.assertFalse(result["metadata"]["sift"]["counting_reasoning_content_floor_applied"])
