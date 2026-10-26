"""Public error classification and deliberately narrow overflow policy."""
import ast
import asyncio
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    from fastapi import HTTPException
    from sift import compact_dynamic
    from sift.core import CompactionError
    from sift.litellm_proxy import (
        COMPACTION_HTTP_STATUS, SiftLiteLLMHook, _compaction_http_exception,
    )
except ImportError:
    SiftLiteLLMHook = None


@unittest.skipIf(SiftLiteLLMHook is None, "install sift-context[litellm]")
class ProxyPolicyTests(unittest.TestCase):
    def test_status_map_covers_all_core_and_dynamic_error_literals(self):
        root = Path(__file__).resolve().parents[1] / "src" / "sift"
        codes = {"invalid"}
        for name in ("core.py", "dynamic.py"):
            for node in ast.walk(ast.parse((root / name).read_text(encoding="utf-8"))):
                if (isinstance(node, ast.keyword) and node.arg == "code"
                        and isinstance(node.value, ast.Constant)):
                    codes.add(node.value.value)
        self.assertLessEqual(codes, COMPACTION_HTTP_STATUS.keys())
        self.assertEqual(COMPACTION_HTTP_STATUS["late_instruction_limit"], 422)
        self.assertEqual(COMPACTION_HTTP_STATUS["field_pruning_target_exceeded"], 413)
        self.assertEqual(COMPACTION_HTTP_STATUS["research_relation_unsupported"], 422)
        for code in codes:
            error = _compaction_http_exception(CompactionError("failure", code=code))
            self.assertEqual(error.status_code, COMPACTION_HTTP_STATUS[code])
            self.assertEqual(error.headers["x-sift-error-code"], code)

    def test_overflow_is_explicit_and_does_not_disable_other_rejections(self):
        data = {"model": "local", "messages": [{"role": "user", "content": "exact"}]}
        saved = copy.deepcopy(data)
        for policy in ("error", "passthrough"):
            for code, status in COMPACTION_HTTP_STATUS.items():
                with self.subTest(policy=policy, code=code):
                    hook = SiftLiteLLMHook({"local": 400}, on_overflow=policy)
                    error = _compaction_http_exception(CompactionError("failure", code=code))
                    with patch("litellm.proxy.proxy_server.llm_router", object()), patch.object(
                        hook, "_compact", side_effect=error,
                    ):
                        call = hook.async_pre_call_hook(None, None, data, "acompletion")
                        if policy == "passthrough" and code == "active_too_large":
                            self.assertIsNone(asyncio.run(call))
                        else:
                            with self.assertRaises(HTTPException) as caught:
                                asyncio.run(call)
                            self.assertIs(caught.exception, error)
                    self.assertEqual(data, saved)

    def test_policy_and_concurrency_validation(self):
        for value in (None, True, "anything", []):
            with self.subTest(policy=value), self.assertRaises(ValueError):
                SiftLiteLLMHook({"local": 400}, on_overflow=value)
        for value in (0, -1, True, 1.5, "2"):
            with self.subTest(concurrency=value), self.assertRaises(ValueError):
                SiftLiteLLMHook({"local": 400}, max_concurrency=value)
        hook = SiftLiteLLMHook({"local": 400}, max_concurrency=3)
        for _ in range(3):
            self.assertTrue(hook._slots.acquire(blocking=False))
        self.assertFalse(hook._slots.acquire(blocking=False))
        for _ in range(3):
            hook._slots.release()

    def test_diagnostics_preserve_detail_and_identify_protected_region(self):
        from sift import compact_messages
        cases = [
            ([{"role": "user", "content": "work " * 1000}], "instructions_and_active_turn"),
            ([{"role": "user", "content": "inspect"},
              {"role": "assistant", "content": None, "tool_calls": [{
                  "id": "a", "type": "function", "function": {"name": "read", "arguments": "{}"},
              }]},
              {"role": "tool", "tool_call_id": "a", "content": "result " * 1000}],
             "instructions_task_and_latest_tool_cycle"),
        ]
        counter = lambda messages: sum(len(str(m)) for m in messages) // 4
        for messages, region in cases:
            with self.assertRaises(CompactionError) as caught:
                compact_messages(messages, counter, target=400)
            error = caught.exception
            self.assertEqual(error.code, "active_too_large")
            self.assertEqual(error.target_tokens, 400)
            self.assertGreater(error.required_tokens, 400)
            self.assertEqual(error.protected_region, region)
            http = _compaction_http_exception(error)
            self.assertEqual(http.headers["x-sift-required-tokens"], str(error.required_tokens))
            self.assertEqual(http.headers["x-sift-target-tokens"], "400")
            self.assertEqual(http.headers["x-sift-protected-region"], region)
            self.assertEqual(http.detail, f"Sift: {error}")

    def test_dynamic_adapter_has_public_import(self):
        from sift.dynamic import compact_dynamic as implementation
        self.assertIs(compact_dynamic, implementation)
