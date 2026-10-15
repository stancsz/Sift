"""Boundary tests for the benchmark control, not a competing provider stack."""

import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from sift import CompactionError


SPEC = importlib.util.spec_from_file_location(
    "sift_benchmark_recency", Path(__file__).resolve().parents[1] / "benchmarks" / "recency.py")
recency = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recency)


def count(messages):
    return (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4


def chat_cycles(number):
    messages = [{"role": "system", "content": "Keep the instructions exact."},
                {"role": "user", "content": "Investigate the task."}]
    for index in range(number):
        messages.extend([
            {"role": "assistant", "content": "Inspect both files.", "tool_calls": [
                {"id": f"a{index}", "type": "function", "function": {"name": "read", "arguments": "{}"}},
                {"id": f"b{index}", "type": "function", "function": {"name": "read", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": f"a{index}", "content": f"file {index} " + "noise " * 60},
            {"role": "tool", "tool_call_id": f"b{index}", "content": "second output " * 25},
        ])
    return messages


class RecencyTests(unittest.TestCase):
    def test_noop_copies_input_without_mutating_it(self):
        messages = [{"role": "user", "content": "hello"}]
        result = recency.compact_messages(messages, count, target=100)
        self.assertEqual(result.messages, messages)
        self.assertIsNot(result.messages, messages)
        self.assertFalse(result.audit["compacted"])

    def test_parallel_chat_cycles_remain_complete_and_recent(self):
        messages = chat_cycles(12)
        saved = copy.deepcopy(messages)
        result = recency.compact_messages(messages, count, target=700)
        self.assertEqual(messages, saved)
        self.assertEqual(result.messages[:2], messages[:2])
        self.assertEqual(result.messages[-3:], messages[-3:])
        calls = {call["id"] for message in result.messages for call in message.get("tool_calls", [])}
        outputs = {message["tool_call_id"] for message in result.messages if message.get("role") == "tool"}
        self.assertEqual(calls, outputs)
        self.assertNotIn("a0", calls)
        self.assertLessEqual(count(result.messages), 700)
        self.assertEqual(result.audit["selected_excerpts"], 0)

    def test_prior_human_turns_are_retained_or_dropped_whole(self):
        messages = [
            {"role": "system", "content": "Pinned system."},
            {"role": "developer", "content": "Pinned developer."},
            {"role": "user", "content": "old task " * 500},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "recent task"},
            {"role": "assistant", "content": "recent answer"},
            {"role": "user", "content": "current task"},
        ]
        result = recency.compact_messages(messages, count, target=250)
        self.assertEqual(result.messages, messages[:2] + messages[4:])
        self.assertEqual(result.audit["preserved_recent_turns"], 1)

    def test_anthropic_tool_results_do_not_replace_the_task(self):
        messages = [{"role": "user", "content": "Original task"}]
        for index in range(10):
            messages.extend([
                {"role": "assistant", "content": [
                    {"type": "thinking", "thinking": "Private reasoning", "signature": "sig"},
                    {"type": "tool_use", "id": f"a{index}", "name": "read", "input": {}},
                    {"type": "tool_use", "id": f"b{index}", "name": "read", "input": {}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": f"a{index}", "content": "noise " * 80},
                    {"type": "tool_result", "tool_use_id": f"b{index}", "content": "noise " * 80},
                ]},
            ])
        result = recency.compact_messages(messages, count, target=800, protocol="anthropic")
        self.assertEqual(result.messages[0], messages[0])
        self.assertEqual(result.messages[-2:], messages[-2:])
        self.assertTrue(all(
            message["role"] == ("assistant" if index % 2 else "user")
            for index, message in enumerate(result.messages)))
        self.assertLessEqual(count(result.messages), 800)

    def test_oversized_essential_work_and_raw_intake_fail_closed(self):
        for messages in (
            [{"role": "user", "content": "active " * 1000}],
            chat_cycles(1)[:-1] + [{"role": "tool", "tool_call_id": "b0", "content": "large " * 1000}],
        ):
            with self.subTest(messages=messages[-1]["role"]), self.assertRaises(CompactionError) as caught:
                recency.compact_messages(messages, count, target=250)
            self.assertEqual(caught.exception.code, "active_too_large")
        with self.assertRaises(CompactionError) as caught:
            recency.compact_messages(chat_cycles(10), count, target=250, raw_limit=300)
        self.assertEqual(caught.exception.code, "raw_limit")

    def test_unsupported_history_and_late_instructions_are_not_dropped(self):
        for field, message, code in (
            ("media", {"role": "user", "content": [{"type": "image_url", "image_url": "opaque"}]}, "unsupported_content"),
            ("instruction", {"role": "developer", "content": "late instruction"}, "late_instruction"),
        ):
            messages = chat_cycles(10)
            messages.insert(2, message)
            with self.subTest(field=field), self.assertRaises(CompactionError) as caught:
                recency.compact_messages(messages, count, target=700)
            self.assertEqual(caught.exception.code, code)


try:
    from litellm import Router
    from sift import litellm_proxy as integration
except ImportError:
    Router = None


@unittest.skipIf(Router is None, "install sift-context[litellm] for the Responses baseline boundary")
class RecencyAdapterTests(unittest.TestCase):
    def setUp(self):
        from litellm.litellm_core_utils import token_counter

        formatter = token_counter._format_type
        self.addCleanup(setattr, token_counter, "_format_type", formatter)

    def test_noop_wrapper_preserves_input_identity_and_definitions(self):
        data = {"input": "hello", "instructions": "Pinned instruction", "max_output_tokens": 100,
                "tools": [{"type": "function", "name": "read", "parameters": {"type": "object", "properties": {}}}]}
        counter = type("Counter", (), {"_count_pre_call_check_tokens": Router._count_pre_call_check_tokens})()
        with patch.object(integration, "compact_messages", recency.compact_messages):
            output = integration.compact_proxy_request(counter, data, call_type="aresponses", target=1000)
        self.assertIs(output["input"], data["input"])
        self.assertIs(output["tools"], data["tools"])
        self.assertEqual(output["instructions"], data["instructions"])
        self.assertEqual(output["max_output_tokens"], data["max_output_tokens"])

    def test_responses_pending_parallel_batches_and_reasoning_remain_whole(self):
        for mode in ("reasoning", "interleaved"):
            with self.subTest(mode=mode):
                items = [{"role": "user", "content": "Original task"}]
                for index in range(18):
                    calls = [{"type": "function_call", "call_id": f"{tag}{index}", "name": "read", "arguments": "{}"}
                             for tag in ("a", "b", "c")]
                    outputs = [{"type": "function_call_output", "call_id": f"{tag}{index}", "output": "noise " * 200}
                               for tag in ("a", "b", "c")]
                    if mode == "interleaved":
                        items.extend([calls[0], calls[1], outputs[0], calls[2], outputs[1], outputs[2]])
                    else:
                        for tag, call in zip(("a", "b", "c"), calls):
                            items.extend([
                                {"type": "reasoning", "id": f"rs{tag}{index}", "summary": [{"type": "summary_text", "text": "Inspect further"}]}, call,
                            ])
                        items.extend(outputs)
                data = {"input": items, "instructions": "Keep this exact."}
                saved = copy.deepcopy(data)
                counter = type("Counter", (), {"_count_pre_call_check_tokens": Router._count_pre_call_check_tokens})()
                with patch.object(integration, "compact_messages", recency.compact_messages):
                    output = integration.compact_proxy_request(counter, data, call_type="aresponses", target=2000)
                self.assertEqual(data, saved)
                size = 9 if mode == "reasoning" else 6
                self.assertEqual(output["input"][-size:], items[-size:])
                calls = {item["call_id"] for item in output["input"] if item.get("type") == "function_call"}
                outputs = {item["call_id"] for item in output["input"] if item.get("type") == "function_call_output"}
                self.assertEqual(calls, outputs)
                self.assertLessEqual(output["metadata"]["sift"]["forwarded_tokens"], 2000)

    def load_callback(self):
        spec = importlib.util.spec_from_file_location(
            "sift_native_benchmark_callback", Path(__file__).resolve().parents[1] / "benchmarks" / "native_callback.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_isolated_startup_selector_is_fixed_and_audits_no_bodies(self):
        # Exercise startup policy independently of the host's optional SDK
        # version. Deployed 1.103.0 compatibility is checked separately.
        with patch.dict(sys.modules, {"recency": recency}), patch.dict(os.environ, {"SIFT_BENCH_ARM": "recency"}), \
                patch("importlib.metadata.version", return_value="1.103.0"), \
                patch.object(integration, "compact_messages", integration.compact_messages):
            callback = self.load_callback()
            os.environ["SIFT_BENCH_ARM"] = "sift"
            with self.assertLogs("LiteLLM Proxy", level="INFO") as logs:
                result = callback.observed_selection(
                    [{"role": "user", "content": "PRIVATE_BENCHMARK_BODY"}], count, target=700)
            self.assertEqual(result.audit["method"], "whole_unit_recency")
            self.assertIn("selector=recency", logs.output[0])
            self.assertIn("thread_cpu_ms=", logs.output[0])
            self.assertNotIn("PRIVATE_BENCHMARK_BODY", str(logs.output))
            with self.assertLogs("LiteLLM Proxy", level="INFO") as logs, self.assertRaises(CompactionError):
                callback.observed_selection(
                    [{"role": "user", "content": "PRIVATE_BENCHMARK_BODY " * 1000}], count, target=250)
            self.assertIn("status=failed", logs.output[0])
            self.assertNotIn("PRIVATE_BENCHMARK_BODY", str(logs.output))
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(callback.benchmark_hook.async_pre_call_hook(
                    None, None, {"model": callback.MODEL, "max_output_tokens": 4097}, "aresponses"))
            self.assertEqual(caught.exception.status_code, 422)

    def test_unsupported_sdk_or_selector_fails_before_installing_the_binding(self):
        for sdk, arm in (("1.100.1", "sift"), ("1.103.0", "unknown")):
            with self.subTest(sdk=sdk, arm=arm), patch.dict(sys.modules, {"recency": recency}), \
                    patch.dict(os.environ, {"SIFT_BENCH_ARM": arm}), \
                    patch("importlib.metadata.version", return_value=sdk):
                original = integration.compact_messages
                with self.assertRaises(RuntimeError):
                    self.load_callback()
                self.assertIs(integration.compact_messages, original)

    def test_native_anthropic_qwen_profile_preserves_objects_and_output_contract(self):
        from litellm.llms.anthropic.experimental_pass_through.adapters.transformation import (
            LiteLLMAnthropicMessagesAdapter,
        )

        adapter = LiteLLMAnthropicMessagesAdapter()
        request = {"model": "qwen3.8-27b", "max_tokens": 4096, "temperature": 0,
                   "system": [{"type": "text", "text": "BASE_INSTRUCTIONS"}],
                   "tools": [{"name": "inspect", "input_schema": {"type": "object", "properties": {}}}],
                   "messages": [{"role": "user", "content": "TASK"},
                                {"role": "system", "content": [{"type": "text", "text": "LATER_INSTRUCTIONS"}]}]}
        original = copy.deepcopy(request)
        before, _ = adapter.translate_anthropic_to_openai(
            anthropic_message_request=request, custom_llm_provider="openai")
        self.assertEqual([message["role"] for message in before["messages"]], ["system", "user", "system"])
        for arm in ("sift", "recency"):
            with self.subTest(arm=arm), patch.dict(sys.modules, {"recency": recency}), \
                    patch.dict(os.environ, {"SIFT_BENCH_ARM": arm}), \
                    patch("importlib.metadata.version", return_value="1.103.0"), \
                    patch.object(integration, "compact_messages", integration.compact_messages):
                callback = self.load_callback()
                placed = callback.qwen_instruction_prefix(request, "anthropic_messages")
                self.assertIs(placed["messages"][0], request["messages"][1])
                self.assertIs(placed["messages"][1], request["messages"][0])
                self.assertIs(placed["tools"], request["tools"])
                self.assertIs(placed["system"], request["system"])
                after, _ = adapter.translate_anthropic_to_openai(
                    anthropic_message_request=placed, custom_llm_provider="openai")
                self.assertEqual(after["messages"], [before["messages"][0], before["messages"][2], before["messages"][1]])
                self.assertEqual(after["tools"], before["tools"])
                self.assertEqual(after["max_tokens"], 4096)
                self.assertEqual(after["temperature"], 0)
                self.assertEqual(request, original)
                for protocol in ("acompletion", "aresponses"):
                    self.assertIs(callback.qwen_instruction_prefix(request, protocol), request)
                other = {**request, "model": "other-model"}
                self.assertIs(callback.qwen_instruction_prefix(other, "anthropic_messages"), other)
                self.assertIs(callback.qwen_instruction_prefix(placed, "anthropic_messages"), placed)

    def test_real_router_prechecks_reject_oversized_nested_unconstrained_arrays(self):
        import litellm
        from litellm.litellm_core_utils import token_counter

        messages = [{"role": "user", "content": ""}]
        tools = [{"type": "function", "function": {"name": "inspect_values", "parameters": {
            "type": "object", "properties": {
                "values": {"type": "array"},
                "nested": {"type": "array", "items": {"type": "object", "properties": {
                    "other": {"type": "array"}}}},
            }}}}]
        original_tools = copy.deepcopy(tools)
        constrained = [{"type": "function", "function": {"name": "read", "parameters": {
            "type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}}}}}]
        expected = litellm.token_counter(messages=messages, tools=constrained)
        with patch.dict(sys.modules, {"recency": recency}), \
                patch.dict(os.environ, {"SIFT_BENCH_ARM": "recency"}), \
                patch("importlib.metadata.version", return_value="1.103.0"), \
                patch.object(integration, "compact_messages", integration.compact_messages):
            callback = self.load_callback()
            installed = token_counter._format_type
            callback.install_benchmark_counter_fix()
            self.assertIs(token_counter._format_type, installed)
            self.assertEqual(litellm.token_counter(messages=messages, tools=constrained), expected)
            router = Router(model_list=[{"model_name": "fixture", "litellm_params": {
                "model": "openai/gpt-4o-mini", "api_key": "offline-fixture"},
                "model_info": {"max_input_tokens": 8}}], enable_pre_call_checks=True)
            self.assertLessEqual(router._count_pre_call_check_tokens(messages=messages, input=None, request_kwargs={}), 8)
            self.assertGreater(router._count_pre_call_check_tokens(messages=messages, input=None, request_kwargs={"tools": tools}), 8)
            with patch.object(litellm, "completion", side_effect=AssertionError("Provider calls forbidden")), \
                    patch.object(litellm, "acompletion", side_effect=AssertionError("Provider calls forbidden")):
                with self.assertRaises(litellm.ContextWindowExceededError):
                    router.get_available_deployment(model="fixture", messages=messages, request_kwargs={"tools": tools})
                with self.assertRaises(litellm.ContextWindowExceededError):
                    asyncio.run(router.async_get_available_deployment(
                        model="fixture", messages=messages, request_kwargs={"tools": tools}))
            self.assertEqual(tools, original_tools)


if __name__ == "__main__":
    unittest.main()
