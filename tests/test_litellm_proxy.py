import asyncio
import copy
import json
from pathlib import Path
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

    def test_legacy_function_call_history_compacts_through_callback(self):
        messages = [{"role": "user", "content": "Old configuration " * 1_500},
                    {"role": "assistant", "content": "Previous search complete."},
                    {"role": "user", "content": "Find the current deployment setting."}]
        cycles = []
        for index in range(12):
            cycles.extend([
                {"role": "assistant", "content": None, "function_call": {
                    "name": "read_file", "arguments": json.dumps({"path": f"config-{index}.py"}),
                }},
                {"role": "function", "name": "read_file",
                 "content": f"config result {index}: " + "deployment setting evidence " * 42},
            ])
        final = {"role": "assistant", "content": "The latest file is authoritative."}
        messages.extend([*cycles, final])
        data = {"model": "local-chat", "messages": messages}
        saved = copy.deepcopy(data)

        result = compact_proxy_request(RouterCounter(), data, call_type="acompletion", target=1_800)

        self.assertTrue(result["metadata"]["sift"]["compacted"])
        self.assertLessEqual(result["metadata"]["sift"]["forwarded_tokens"], 1_800)
        self.assertEqual(result["messages"][-3:], [cycles[-2], cycles[-1], final])
        self.assertEqual(data, saved)

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
        self.assertEqual(caught.exception.headers["x-sift-error-code"], "active_too_large")
        self.assertEqual(caught.exception.detail, "Sift: active turn and instructions exceed target")
        self.assertEqual(caught.exception.__cause__.code, "active_too_large")
        self.assertEqual(data, {"model": "local-chat", "messages": [
            {"role": "user", "content": "old " * 1000},
            {"role": "assistant", "content": "noted"},
            {"role": "user", "content": "active " * 1000},
        ]})

    def test_oversized_latest_tool_cycle_has_same_machine_code(self):
        data = {"model": "local-chat", "messages": [
            {"role": "user", "content": "Investigate the issue."},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-1", "type": "function", "function": {
                    "name": "inspect", "arguments": "{}",
                },
            }]},
            {"role": "tool", "tool_call_id": "call-1", "content": "evidence " * 1000},
        ]}
        saved = copy.deepcopy(data)
        with self.assertRaises(HTTPException) as caught:
            compact_proxy_request(RouterCounter(), data, call_type="acompletion", target=400)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(caught.exception.headers["x-sift-error-code"], "active_too_large")
        self.assertEqual(caught.exception.detail, "Sift: active task or latest tool cycle exceeds target")
        self.assertEqual(caught.exception.__cause__.code, "active_too_large")
        self.assertEqual(data, saved)

    def test_other_413_codes_remain_distinguishable_and_fail_closed(self):
        raw_data = {"model": "local-chat", "messages": [
            {"role": "user", "content": "raw " * 1000},
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": "current"},
        ]}
        raw_saved = copy.deepcopy(raw_data)
        with self.assertRaises(HTTPException) as raw:
            compact_proxy_request(
                RouterCounter(), raw_data, call_type="acompletion", target=100,
                raw_limit=250,
            )
        self.assertEqual(raw.exception.status_code, 413)
        self.assertEqual(raw.exception.headers["x-sift-error-code"], "raw_limit")
        self.assertEqual(raw.exception.detail, "Sift: request exceeds raw_limit")
        self.assertEqual(raw_data, raw_saved)

        precount_data = {"model": "local-chat", "messages": [
            {"role": "user", "content": "Read the evidence."},
        ], "tools": [{"type": "function", "function": {
            "name": "read_evidence", "description": "evidence " * 1000,
            "parameters": {"type": "object", "properties": {}},
        }}]}
        precount_saved = copy.deepcopy(precount_data)
        with self.assertRaises(HTTPException) as precount:
            compact_proxy_request(
                RouterCounter(), precount_data, call_type="acompletion", target=100,
                max_input_characters=1_000,
            )
        self.assertEqual(precount.exception.status_code, 413)
        self.assertEqual(precount.exception.headers["x-sift-error-code"], "input_size_limit")
        self.assertEqual(precount.exception.detail, "Sift: request exceeds the pre-count text limit")
        self.assertEqual(precount_data, precount_saved)

    def test_documented_callback_passes_active_capacity_and_preserves_guards(self):
        from litellm.proxy import proxy_server

        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        examples = [block.split("```", 1)[0] for block in readme.split("```python\n")[1:]]
        callback_code, = [code for code in examples if "class PassThroughOn413Hook" in code]
        namespace = {}
        exec(compile(callback_code, "README callback", "exec"), namespace)
        callback = namespace["PassThroughOn413Hook"]

        active = {"model": "local-chat", "messages": [
            {"role": "user", "content": "old " * 1000},
            {"role": "assistant", "content": "noted"},
            {"role": "user", "content": "active " * 1000},
        ]}
        cycle = {"model": "local-chat", "messages": [
            {"role": "user", "content": "Inspect the issue."},
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-1", "type": "function",
                "function": {"name": "inspect", "arguments": "{}"},
            }]},
            {"role": "tool", "tool_call_id": "call-1", "content": "evidence " * 1000},
        ]}
        cases = [
            ("active turn", active, {}, None),
            ("latest tool cycle", cycle, {}, None),
            ("raw limit", active, {"raw_limit": 600}, "raw_limit"),
            ("input size", active, {"max_input_characters": 100}, "input_size_limit"),
        ]
        with patch.object(proxy_server, "llm_router", RouterCounter()):
            for name, data, options, error_code in cases:
                with self.subTest(name=name):
                    saved = copy.deepcopy(data)
                    hook = callback({"local-chat": 400}, **options)
                    if error_code is None:
                        result = asyncio.run(hook.async_pre_call_hook(None, None, data, "acompletion"))
                        self.assertIsNone(result)
                    else:
                        with self.assertRaises(HTTPException) as caught:
                            asyncio.run(hook.async_pre_call_hook(None, None, data, "acompletion"))
                        self.assertEqual(caught.exception.status_code, 413)
                        self.assertEqual(caught.exception.headers["x-sift-error-code"], error_code)
                    self.assertEqual(data, saved)

    def test_fastapi_serializes_machine_code_header(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.post("/compact")
        def compact(request: dict):
            return compact_proxy_request(
                RouterCounter(), request, call_type="acompletion", target=400,
            )

        response = TestClient(app).post("/compact", json={"model": "local-chat", "messages": [
            {"role": "user", "content": "old " * 1000},
            {"role": "assistant", "content": "noted"},
            {"role": "user", "content": "active " * 1000},
        ]})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers["x-sift-error-code"], "active_too_large")
        self.assertEqual(response.json()["detail"], "Sift: active turn and instructions exceed target")

    def test_precount_guard_includes_tool_schemas_before_route_tokenization(self):
        class CountingRouter:
            calls = 0

            def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
                self.calls += 1
                return 10

        router = CountingRouter()
        data = {"model": "local-chat", "messages": [
            {"role": "user", "content": "Read the evidence."},
        ], "tools": [{"type": "function", "function": {
            "name": "read_evidence", "description": "evidence " * 1_000,
            "parameters": {"type": "object", "properties": {}},
        }}]}
        with self.assertRaises(HTTPException) as caught:
            compact_proxy_request(
                router, data, call_type="acompletion", target=100,
                max_input_characters=1_000,
            )
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(caught.exception.headers["x-sift-error-code"], "input_size_limit")
        self.assertEqual(router.calls, 0)

    def test_default_precount_guard_accepts_near_million_unicode_tokens(self):
        from sift import compact_messages

        messages = [{"role": "user", "content": "界" * 990_000}]
        result = compact_messages(
            messages, lambda items: litellm.token_counter(messages=items),
            target=1_000_000, raw_limit=1_000_000,
        )
        self.assertGreaterEqual(result.audit["input_tokens"], 990_000)
        self.assertLessEqual(result.audit["input_tokens"], 1_000_000)
        self.assertFalse(result.audit["compacted"])

    def test_precount_limits_are_configurable_for_trusted_workloads(self):
        data = {"model": "local-chat", "messages": [
            {"role": "user", "content": "trusted " * 200},
        ]}
        result = compact_proxy_request(
            RouterCounter(), data, call_type="acompletion", target=1_000,
            max_input_characters=2_000, max_input_nodes=100,
        )
        self.assertFalse(result["metadata"]["sift"]["compacted"])

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
