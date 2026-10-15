import asyncio
import copy
import json
import unittest
from unittest.mock import patch

try:
    import litellm
    from fastapi import HTTPException
    from litellm.integrations.custom_logger import CustomLogger
    from sift.litellm_proxy import SiftLiteLLMHook, compact_proxy_request
except ImportError:
    SiftLiteLLMHook = None


class RouterCounter:
    def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
        tools = request_kwargs.get("tools") or []
        for tool in tools:
            schema = tool.get("function", {}).get("parameters", {})
            for property_schema in schema.get("properties", {}).values():
                if property_schema.get("type") == "array" and "items" not in property_schema:
                    raise KeyError("items")
        return (len(json.dumps(messages, ensure_ascii=False)) +
                len(json.dumps(tools, ensure_ascii=False)) + 3) // 4


@unittest.skipIf(SiftLiteLLMHook is None, "install sift-context[litellm] for proxy tests")
class LiteLLMProxyTests(unittest.TestCase):
    def test_callback_is_native_and_ignores_other_models(self):
        hook = SiftLiteLLMHook({"local-chat": 700})
        self.assertIsInstance(hook, CustomLogger)
        result = asyncio.run(hook.async_pre_call_hook(
            None, None, {"model": "another", "messages": []}, "acompletion",
        ))
        self.assertIsNone(result)

    def test_callback_uses_litellm_router_for_selected_model(self):
        from litellm.proxy import proxy_server

        hook = SiftLiteLLMHook({"local-chat": 700})
        lines = [f"routine output {index}" for index in range(800)]
        lines[400] = "FAILED test_invoice_total"
        lines[401] = "rounding_mode=HALF_EVEN; observed +0.01"
        data = {"model": "local-chat", "messages": [
            {"role": "user", "content": "\n".join(lines)},
            {"role": "assistant", "content": "received"},
            {"role": "user", "content": "What caused FAILED test_invoice_total?"},
        ]}
        with patch.object(proxy_server, "llm_router", RouterCounter()):
            result = asyncio.run(hook.async_pre_call_hook(None, None, data, "acompletion"))
        self.assertIn("rounding_mode=HALF_EVEN", str(result["messages"]))
        self.assertLessEqual(result["metadata"]["sift"]["forwarded_tokens"], 700)
        headers = asyncio.run(hook.async_post_call_response_headers_hook(result, None, None))
        self.assertEqual(headers["x-sift-compacted"], "true")
        self.assertEqual(headers["x-sift-estimated-forwarded-tokens"],
                         str(result["metadata"]["sift"]["forwarded_tokens"]))

    def test_under_target_keeps_messages_and_reports_no_op(self):
        data = {"model": "local-chat", "messages": [{"role": "user", "content": "hello"}]}
        result = compact_proxy_request(RouterCounter(), data, call_type="acompletion", target=700)
        self.assertIs(result["messages"], data["messages"])
        self.assertFalse(result["metadata"]["sift"]["compacted"])
        self.assertNotIn("metadata", data)

    def test_compaction_preserves_diagnostic_and_provider_schema(self):
        lines = [f"routine build output {index}" for index in range(1000)]
        lines[500] = "FAILED test_invoice_total"
        lines[501] = "rounding_mode=HALF_EVEN; observed +0.01 versus Decimal expected"
        data = {
            "model": "local-chat",
            "messages": [
                {"role": "user", "content": "\n".join(lines)},
                {"role": "assistant", "content": "log received"},
                {"role": "user", "content": "What caused FAILED test_invoice_total?"},
            ],
            "tools": [{"type": "function", "function": {"name": "run", "parameters": {
                "type": "object", "properties": {"commands": {"type": "array"}},
            }}}],
        }
        saved = copy.deepcopy(data)
        result = compact_proxy_request(RouterCounter(), data, call_type="acompletion", target=700)
        self.assertIsNotNone(result)
        self.assertEqual(data, saved)
        self.assertEqual(result["tools"], data["tools"])
        self.assertIn("rounding_mode=HALF_EVEN", str(result["messages"]))
        self.assertTrue(result["metadata"]["sift"]["counting_tool_schema_items_filled"])
        self.assertLessEqual(result["metadata"]["sift"]["forwarded_tokens"], 700)

    def test_oversized_active_turn_fails_closed(self):
        data = {"model": "local-chat", "messages": [
            {"role": "user", "content": "old " * 1000},
            {"role": "assistant", "content": "noted"},
            {"role": "user", "content": "active " * 1000},
        ]}
        with self.assertRaises(HTTPException) as caught:
            compact_proxy_request(RouterCounter(), data, call_type="acompletion", target=400)
        self.assertEqual(caught.exception.status_code, 413)

    def test_deployed_litellm_counter_accepts_counting_only_schema_copy(self):
        class ActualCounter:
            def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
                return litellm.token_counter(messages=messages, tools=request_kwargs.get("tools"))

        tools = [{"type": "function", "function": {"name": "run", "parameters": {
            "type": "object", "properties": {"commands": {"type": "array"}},
        }}}]
        data = {"model": "local-chat", "tools": tools, "messages": [
            {"role": "user", "content": "routine output\n" * 2000},
            {"role": "assistant", "content": "received"},
            {"role": "user", "content": "What happened?"},
        ]}
        result = compact_proxy_request(ActualCounter(), data, call_type="acompletion", target=600)
        self.assertIsNotNone(result)
        self.assertIs(result["tools"], tools)
        self.assertNotIn("items", tools[0]["function"]["parameters"]["properties"]["commands"])
        self.assertTrue(result["metadata"]["sift"]["counting_tool_schema_items_filled"])


if __name__ == "__main__":
    unittest.main()
