"""Codex Responses Lite declarations remain exact and count against budget."""
import copy
import unittest

try:
    from fastapi import HTTPException
    from litellm import Router
    from sift.litellm_proxy import compact_proxy_request
    from sift.litellm_responses import response_selection_view
except ImportError:
    Router = None


class Counter:
    def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
        return Router._count_pre_call_check_tokens(self, messages, input, request_kwargs)


@unittest.skipIf(Router is None, "install sift-context[litellm]")
class CodexCatalogTests(unittest.TestCase):
    def catalog(self):
        return {"type": "additional_tools", "id": "catalog-1", "role": "developer", "tools": [
            {"type": "namespace", "name": "functions", "description": "Native tools", "tools": [
                {"type": "function", "name": "read", "parameters": {"type": "object", "properties": {}}},
                {"type": "custom", "name": "apply_patch", "format": {"type": "text"}},
            ]},
        ]}

    def test_real_counter_and_compaction_preserve_original_catalog(self):
        catalog = self.catalog()
        data = {"model": "default", "instructions": "Keep instructions exact", "input": [catalog,
                {"role": "user", "content": "routine archive evidence\n" * 3000},
                {"role": "assistant", "content": "acknowledged"},
                {"role": "user", "content": "Find the archive evidence"}]}
        saved = copy.deepcopy(data)
        output = compact_proxy_request(Counter(), data, call_type="aresponses", target=1500)
        self.assertEqual(output["input"][0], catalog)
        self.assertEqual(output["instructions"], data["instructions"])
        self.assertEqual(data, saved)
        self.assertTrue(output["metadata"]["sift"]["compacted"])
        self.assertTrue(output["metadata"]["sift"]["counting_responses_catalog_serialized"])
        self.assertLessEqual(output["metadata"]["sift"]["forwarded_tokens"], 1500)

    def test_oversized_catalog_is_charged_and_cannot_be_evicted(self):
        catalog = self.catalog()
        catalog["tools"][0]["description"] = "schema evidence " * 4000
        data = {"input": [catalog, {"role": "user", "content": "inspect"}]}
        with self.assertRaises(HTTPException) as caught:
            compact_proxy_request(Counter(), data, call_type="aresponses", target=1000)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(caught.exception.headers["x-sift-error-code"], "active_too_large")
        self.assertGreater(int(caught.exception.headers["x-sift-required-tokens"]), 1000)

    def test_malformed_builtin_or_pending_catalog_is_rejected(self):
        malformed = [dict(self.catalog(), role="user"), dict(self.catalog(), tools=[{"type": "web_search"}]),
                     dict(self.catalog(), tools=[{"type": "namespace", "name": "x", "tools": [{"type": "custom", "name": ""}]}])]
        for catalog in malformed:
            with self.subTest(catalog=catalog), self.assertRaises(HTTPException) as caught:
                response_selection_view({"input": [catalog, {"role": "user", "content": "task"}]})
            self.assertEqual(caught.exception.status_code, 422)
        items = [{"role": "user", "content": "task"},
                 {"type": "function_call", "name": "read", "call_id": "a", "arguments": "{}"},
                 self.catalog(), {"type": "function_call_output", "call_id": "a", "output": "result"}]
        with self.assertRaises(HTTPException):
            response_selection_view({"input": items})

    def test_sealed_reasoning_is_counted_and_restored_with_parallel_tools(self):
        sealed = {"type": "reasoning", "id": "sealed-latest", "summary": [], "encrypted_content": "OPAQUE_LATEST_" * 20}
        cycle = [sealed,
                 {"type": "function_call", "call_id": "a", "name": "read", "arguments": "{}"},
                 {"type": "custom_tool_call", "call_id": "b", "name": "apply_patch", "input": "exact patch"},
                 {"type": "function_call_output", "call_id": "a", "output": "exact result"},
                 {"type": "custom_tool_call_output", "call_id": "b", "output": "exact patch result"}]
        data = {"input": [self.catalog(),
                {"role": "user", "content": "old archive\n" * 4000},
                {"type": "reasoning", "id": "old", "summary": [], "encrypted_content": "PRIVATE_OLD_SEALED" * 1000},
                {"role": "assistant", "content": "archive received"},
                {"role": "user", "content": "Inspect archive and continue"}, *cycle]}
        saved = copy.deepcopy(data)
        output = compact_proxy_request(Counter(), data, call_type="aresponses", target=1800)
        self.assertEqual(output["input"][-len(cycle):], cycle)
        self.assertNotIn("PRIVATE_OLD_SEALED", str(output["input"]))
        self.assertEqual(data, saved)
        self.assertTrue(output["metadata"]["sift"]["counting_responses_sealed_reasoning_serialized"])
        self.assertLessEqual(output["metadata"]["sift"]["forwarded_tokens"], 1800)
        huge = {"input": [{"role": "user", "content": "current task"},
                          dict(sealed, encrypted_content="OPAQUE_" * 5000)]}
        with self.assertRaises(HTTPException) as caught:
            compact_proxy_request(Counter(), huge, call_type="aresponses", target=1000)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(caught.exception.headers["x-sift-error-code"], "active_too_large")
