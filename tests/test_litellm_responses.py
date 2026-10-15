"""Responses acceptance boundaries against the deployed LiteLLM converter."""

import copy
import unittest

try:
    from fastapi import HTTPException
    from litellm import Router
    from sift.litellm_proxy import compact_proxy_request
except ImportError:
    Router = None


class DeployedCounter:
    def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
        return Router._count_pre_call_check_tokens(self, messages, input, request_kwargs)


@unittest.skipIf(Router is None, "install sift-context[litellm] for Responses tests")
class ResponsesTests(unittest.TestCase):
    def compact(self, data, target=1_000):
        return compact_proxy_request(DeployedCounter(), data, call_type="aresponses", target=target)

    def test_noop_retains_input_identity_instructions_tools_and_limits(self):
        data = {"model": "local-chat", "instructions": "Keep this instruction exact.",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
                "tools": [{"type": "function", "name": "run", "parameters": {
                    "type": "object", "properties": {"values": {"type": "array"}},
                }}], "max_output_tokens": 100, "store": False, "truncation": "disabled"}
        saved = copy.deepcopy(data)
        output = self.compact(data)
        self.assertEqual(data, saved)
        self.assertIs(output["input"], data["input"])
        self.assertIs(output["tools"], data["tools"])
        for key in ("instructions", "max_output_tokens", "store", "truncation"):
            self.assertEqual(output[key], data[key])
        self.assertNotIn("messages", output)
        self.assertFalse(output["metadata"]["sift"]["compacted"])
        self.assertTrue(output["metadata"]["sift"]["counting_tool_schema_items_filled"])

    def test_middle_evidence_and_exact_latest_item_are_preserved(self):
        lines = [f"routine record {index} processed normally" for index in range(2_000)]
        lines[1_000:1_002] = ["FAILED test_release_deadline", "timeout_ms=4500; old timeout_ms=9000"]
        latest = {"type": "message", "id": "msg_latest", "role": "user",
                  "content": [{"type": "input_text", "text": "What caused FAILED test_release_deadline?"}]}
        data = {"model": "local-chat", "instructions": "Use only supplied evidence.", "input": [
            {"role": "user", "content": "\n".join(lines)},
            {"type": "message", "id": "msg_old", "role": "assistant", "content": "Received."}, latest,
        ]}
        saved = copy.deepcopy(data)
        with self.assertLogs("LiteLLM Proxy", level="INFO") as logs:
            output = self.compact(data)
        self.assertEqual(data, saved)
        self.assertIs(output["input"][-1], latest)
        self.assertIn("timeout_ms=4500", str(output["input"]))
        self.assertLessEqual(output["metadata"]["sift"]["forwarded_tokens"], 1_000)
        self.assertIn("sift_request protocol=aresponses compacted=true", logs.output[0])
        self.assertNotIn("test_release_deadline", str(logs.output))
        self.assertEqual(output["instructions"], data["instructions"])

    def test_parallel_function_and_custom_calls_stay_whole_and_cache_prefix_appends(self):
        task = {"role": "user", "content": "Investigate the release incident and failing tests."}
        items = [task]
        histories = []
        for index in range(20):
            items.extend([
                {"type": "reasoning", "id": f"rs_{index}", "summary": [{"type": "summary_text", "text": "Inspect the log."}]},
                {"type": "function_call", "id": f"fc_{index}", "name": "run", "arguments": "{}", "call_id": f"call_{index}"},
                {"type": "reasoning", "id": f"rs_parallel_{index}", "summary": [{"type": "summary_text", "text": "Apply the related change."}]},
                {"type": "custom_tool_call", "id": f"ct_{index}", "name": "patch", "input": "patch content", "call_id": f"custom_{index}"},
                {"type": "function_call_output", "call_id": f"call_{index}", "output": "routine output " * 80 + f"FAILED test_release_{index}"},
                {"type": "custom_tool_call_output", "call_id": f"custom_{index}", "output": "applied"},
            ])
            if index < 17:
                continue
            data = {"model": "local-chat", "instructions": "Inspect historical evidence.", "input": list(items)}
            saved = copy.deepcopy(data)
            output = self.compact(data, target=3_000)
            self.assertEqual(data, saved)
            self.assertIs(output["input"][0], task)
            self.assertEqual(output["input"][-6:], items[-6:])
            self.assertTrue(output["metadata"]["sift"]["compacted"])
            self.assertLessEqual(output["metadata"]["sift"]["forwarded_tokens"], 3_000)
            calls = {item["call_id"] for item in output["input"] if item.get("type") in {"function_call", "custom_tool_call"}}
            outputs = {item["call_id"] for item in output["input"] if item.get("type") in {"function_call_output", "custom_tool_call_output"}}
            self.assertEqual(calls, outputs)
            histories.append(output["input"])
        self.assertEqual(histories[1][:len(histories[0])], histories[0])
        self.assertEqual(histories[2][:len(histories[1])], histories[1])

    def test_stateful_opaque_builtin_and_media_inputs_fail_closed(self):
        base = {"model": "local-chat", "input": [{"role": "user", "content": "hello"}]}
        cases = [
            {**base, "previous_response_id": "resp_saved"},
            {**base, "conversation": "conv_saved"},
            {**base, "input": [{"type": "item_reference", "id": "msg_saved"}]},
            {**base, "input": [{"role": "user", "content": [{"type": "input_image", "image_url": "data:image/png;base64,AA"}]}]},
            {**base, "input": [{"type": "reasoning", "summary": [], "encrypted_content": "opaque"}]},
            {**base, "input": [{"type": "reasoning", "summary": None}]},
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(HTTPException) as raised:
                self.compact(data)
            self.assertEqual(raised.exception.status_code, 422)

    def test_instructions_and_tools_consume_the_same_input_budget(self):
        data = {"model": "local-chat", "instructions": "Important constraint. " * 500,
                "input": "hello"}
        with self.assertRaises(HTTPException) as raised:
            self.compact(data, target=600)
        self.assertEqual(raised.exception.status_code, 413)

    def test_namespace_and_custom_definitions_cannot_bypass_input_budget(self):
        for tool in (
            {"type": "namespace", "name": "reports", "description": "Report operations", "tools": [
                {"type": "function", "name": "list_reports", "description": "Reports require authorization. " * 800,
                 "parameters": {"type": "object", "properties": {}}},
            ]},
            {"type": "custom", "name": "apply_patch", "description": "Patch format documentation. " * 800},
        ):
            data = {"model": "local-chat", "input": "hello", "tools": [tool]}
            saved = copy.deepcopy(data)
            with self.subTest(tool=tool["type"]), self.assertRaises(HTTPException) as raised:
                self.compact(data, target=1_000)
            self.assertEqual(raised.exception.status_code, 413)
            self.assertEqual(data, saved)
            output = self.compact(data, target=10_000)
            self.assertIs(output["tools"], data["tools"])
            self.assertTrue(output["metadata"]["sift"]["counting_responses_tools_translated"])
            self.assertGreater(output["metadata"]["sift"]["input_tokens"], 1_000)

    def test_unknown_namespace_child_and_orphan_or_incomplete_tools_rejected(self):
        cases = [
            {"input": "hello", "tools": [{"type": "namespace", "name": "outer", "tools": [{"type": "custom", "name": "unsupported"}]}]},
            {"input": [{"type": "function_call_output", "call_id": "missing", "output": "data"}]},
            {"input": [{"role": "user", "content": "run"}, {"type": "function_call", "call_id": "pending", "name": "run", "arguments": "{}"}]},
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(HTTPException) as raised:
                self.compact({"model": "local-chat", **data})
            self.assertEqual(raised.exception.status_code, 422)

    def test_schema_branches_cannot_hide_tool_context_from_target_or_raw_limit(self):
        description = "Branch format documentation. " * 1_000
        for schema in (
            {"type": "object", "$defs": {"Details": {"type": "string", "description": description}},
             "properties": {"data": {"$ref": "#/$defs/Details"}}},
            {"type": "object", "properties": {"data": {"anyOf": [{"type": "string", "description": description}]}}},
        ):
            data = {"model": "local-chat", "input": "hello", "tools": [
                {"type": "function", "name": "format", "parameters": schema},
            ]}
            saved = copy.deepcopy(data)
            with self.assertRaises(HTTPException) as raised:
                self.compact(data, target=1_000)
            self.assertEqual(raised.exception.status_code, 413)
            with self.assertRaises(HTTPException) as raised:
                compact_proxy_request(DeployedCounter(), data, call_type="aresponses", target=1_000, raw_limit=1_500)
            self.assertEqual(raised.exception.status_code, 413)
            output = self.compact(data, target=10_000)
            self.assertGreater(output["metadata"]["sift"]["counting_tool_floor_adjustment"], 1_000)
            self.assertIs(output["tools"], data["tools"])
            self.assertEqual(data, saved)


if __name__ == "__main__":
    unittest.main()
