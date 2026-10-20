import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
# Fresh Windows imports of LiteLLM's proxy modules can take over 30 seconds, and
# can exceed 60 seconds when the full Python 3.14 suite is under load. These tests
# intentionally launch clean processes to verify import-time configuration.
PROCESS_TIMEOUT = 120


class NativeMiniMaxProfileTests(unittest.TestCase):
    def test_m3_full_and_compacted_aliases_share_route_and_one_million_context(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is needed to inspect the native benchmark config")

        config = yaml.safe_load((ROOT / "benchmarks/native_litellm_minimax_m3.yaml").read_text())
        models = {item["model_name"]: item for item in config["model_list"]}
        full = models["minimax-m3-full"]
        sift = models["minimax-m3-sift"]
        self.assertEqual(full["litellm_params"], sift["litellm_params"])
        self.assertEqual(full["litellm_params"]["model"], "openrouter/minimax/minimax-m3")
        self.assertEqual(full["litellm_params"]["stream_options"], {"include_usage": True})
        self.assertEqual(full["model_info"]["context_window"], 1_048_576)
        self.assertEqual(full["model_info"], sift["model_info"])
        self.assertEqual(config["router_settings"]["num_retries"], 0)

    def test_full_sift_and_recency_alias_dispatch_is_fixed_at_process_start(self):
        for arm, selector_module, target in (
            ("full", "sift.core", 65536),
            ("sift", "sift.core", 65536),
            ("recency", "recency", 65536),
        ):
            with self.subTest(arm=arm):
                env = os.environ.copy()
                env.update({
                    "PYTHONPATH": str(ROOT / "benchmarks") + os.pathsep + env.get("PYTHONPATH", ""),
                    "SIFT_BENCH_ARM": arm,
                    "SIFT_BENCH_MODEL": "minimax-m3-sift",
                    "SIFT_BENCH_FULL_MODEL": "minimax-m3-full",
                    "SIFT_BENCH_PROFILE": "passthrough",
                    "SIFT_BENCH_TARGET": str(target),
                    "SIFT_BENCH_MIN_RAW_TOKENS": "500000",
                })
                script = (
                    "import native_callback as c; "
                    f"assert c.benchmark_hook.model_targets == {{'minimax-m3-sift': {target}}}; "
                    "assert c.FULL_MODEL not in c.benchmark_hook.model_targets; "
                    "assert c.MODEL != c.FULL_MODEL; "
                    "assert c.PROFILE == 'passthrough'; "
                    f"assert c._selector.__module__ == {selector_module!r}; "
                    "import asyncio, logging; logging.basicConfig(level=logging.INFO); "
                    "from litellm.proxy import proxy_server; proxy_server.llm_router = object(); "
                    "c.integration.compact_proxy_request = lambda router, data, **kw: "
                    "{'metadata': {'sift': {'input_tokens': 500001, 'forwarded_tokens': 500001}}}; "
                    "assert asyncio.run(c.benchmark_hook.async_pre_call_hook(None, None, "
                    "{'model': c.FULL_MODEL, 'messages': [{'role': 'user', 'content': 'same input'}]}, "
                    "'acompletion')) is None; "
                    "from types import SimpleNamespace; "
                    "assert c._provider_usage({'usage': {'prompt_tokens': 32, 'completion_tokens': 7, "
                    "'prompt_tokens_details': {'cached_tokens': 9}}})['input_tokens'] == 32; "
                    "assert c._provider_usage({'usage': {'prompt_tokens': 32, 'completion_tokens': 7, "
                    "'prompt_tokens_details': {'cached_tokens': 9}}})['cache_read_input_tokens'] == 9; "
                    "asyncio.run(c.benchmark_hook.async_log_success_event("
                    "{'model': c.FULL_MODEL, 'litellm_metadata': {'sift_benchmark': "
                    "{'arm': 'full', 'model': c.FULL_MODEL, 'request_seq': 7}}}, "
                    "SimpleNamespace(usage=SimpleNamespace(input_tokens=9, cache_creation_input_tokens=3, "
                    "cache_read_input_tokens=2, output_tokens=4)), None, None)); "
                    "assert c.qwen_instruction_prefix({'model': c.MODEL, 'messages': []}, 'anthropic_messages')['messages'] == []"
                )
                result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                        text=True, capture_output=True, timeout=PROCESS_TIMEOUT)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("selector=full", result.stderr)
                self.assertIn("input_tokens=500001 forwarded_tokens=500001", result.stderr)
                self.assertIn("sift_benchmark_provider_usage", result.stderr)
                self.assertIn("request_seq=7", result.stderr)
                self.assertIn("cache_read_input_tokens=2", result.stderr)
                self.assertNotIn("same input", result.stderr)

    def test_sift_arm_rejects_sub_floor_request_before_provider_routing(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "benchmarks") + os.pathsep + env.get("PYTHONPATH", ""),
            "SIFT_BENCH_ARM": "sift",
            "SIFT_BENCH_PROFILE": "passthrough",
            "SIFT_BENCH_TARGET": "32000",
            "SIFT_BENCH_MIN_RAW_TOKENS": "500000",
        })
        script = "\n".join((
            "import native_callback as c",
            "from types import SimpleNamespace",
            "from fastapi import HTTPException",
            "c._selector = lambda messages, count_tokens, **kwargs: SimpleNamespace(",
            "    messages=messages, audit={'input_tokens': 499999, 'forwarded_tokens': 32000})",
            "try:",
            "    c.observed_selection([], lambda value: 0, target=32000)",
            "except HTTPException as error:",
            "    assert error.status_code == 422",
            "else:",
            "    raise AssertionError('sub-floor request was not rejected')",
        ))
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=PROCESS_TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_arm_rejects_sub_floor_request_before_provider_routing(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "benchmarks") + os.pathsep + env.get("PYTHONPATH", ""),
            "SIFT_BENCH_ARM": "full",
            "SIFT_BENCH_PROFILE": "passthrough",
            "SIFT_BENCH_TARGET": "32000",
            "SIFT_BENCH_MIN_RAW_TOKENS": "500000",
        })
        script = "\n".join((
            "import asyncio",
            "import native_callback as c",
            "from fastapi import HTTPException",
            "from litellm.proxy import proxy_server",
            "proxy_server.llm_router = object()",
            "c.integration.compact_proxy_request = lambda router, data, **kw: {'metadata': {'sift': {'input_tokens': 499999, 'forwarded_tokens': 499999}}}",
            "try:",
            "    asyncio.run(c.benchmark_hook.async_pre_call_hook(None, None, {'model': c.FULL_MODEL, 'messages': [{'role': 'user', 'content': 'small'}]}, 'acompletion'))",
            "except HTTPException as error:",
            "    assert error.status_code == 422",
            "else:",
            "    raise AssertionError('sub-floor request was not rejected')",
        ))
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=PROCESS_TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preflight_only_fingerprints_identical_client_model_aliases(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "benchmarks") + os.pathsep + env.get("PYTHONPATH", ""),
            "SIFT_BENCH_ARM": "sift",
            "SIFT_BENCH_PROFILE": "passthrough",
            "SIFT_BENCH_TARGET": "32000",
            "SIFT_BENCH_MIN_RAW_TOKENS": "500000",
            "SIFT_BENCH_PREFLIGHT_ONLY": "1",
            "SIFT_BENCH_RUN_ID": "pair-20261016",
        })
        script = "\n".join((
            "import native_callback as c",
            "base = {'messages': [{'role': 'user', 'content': 'same task'}], 'temperature': 0}",
            "full = {**base, 'model': c.MODEL, 'metadata': {'sift_benchmark': {'arm': 'full'}}}",
            "sift = {**base, 'model': c.MODEL, 'metadata': {'sift_benchmark': {'arm': 'sift'}}}",
            "assert c._request_fingerprint(full) == c._request_fingerprint(sift)",
            "assert len(c._request_fingerprint(full)) == 64",
            "assert c._request_fingerprint_components(full) == c._request_fingerprint_components(sift)",
            "assert len(c._request_fingerprint_components(full)['messages']) == 64",
            "changed = {**base, 'messages': [{'role': 'user', 'content': 'different task'}]}",
            "assert c._request_fingerprint(full) != c._request_fingerprint(changed)",
        ))
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=PROCESS_TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fixed_full_arm_can_use_the_same_client_model_alias_as_sift(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "benchmarks") + os.pathsep + env.get("PYTHONPATH", ""),
            "SIFT_BENCH_ARM": "full",
            "SIFT_BENCH_MODEL": "minimax-m3-shared",
            "SIFT_BENCH_FULL_MODEL": "minimax-m3-full",
            "SIFT_BENCH_PROFILE": "passthrough",
            "SIFT_BENCH_TARGET": "32000",
            "SIFT_BENCH_MIN_RAW_TOKENS": "500000",
        })
        script = "\n".join((
            "import asyncio, logging",
            "logging.basicConfig(level=logging.INFO)",
            "import native_callback as c",
            "from litellm.proxy import proxy_server",
            "proxy_server.llm_router = object()",
            "assert c._is_full_request(c.MODEL)",
            "assert c.benchmark_hook.model_targets == {c.MODEL: c.TARGET}",
            "assert c._is_full_request(c.FULL_MODEL)",
            "async def forbidden_selector(*args, **kwargs):",
            "    raise AssertionError('full arm invoked the Sift selector')",
            "c.integration.SiftLiteLLMHook.async_pre_call_hook = forbidden_selector",
            "def count(router, data, **kwargs):",
            "    return {'metadata': {'sift': {'input_tokens': 550000, 'forwarded_tokens': 550000}}}",
            "c.integration.compact_proxy_request = count",
            "assert asyncio.run(c.benchmark_hook.async_pre_call_hook(None, None, {'model': c.MODEL, 'messages': [{'role': 'user', 'content': 'task'}]}, 'acompletion')) is None",
        ))
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=PROCESS_TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selector=full", result.stderr)
        self.assertIn("input_tokens=550000 forwarded_tokens=550000", result.stderr)

    def test_preflight_only_sift_logs_count_and_blocks_before_provider(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "benchmarks") + os.pathsep + env.get("PYTHONPATH", ""),
            "SIFT_BENCH_ARM": "sift",
            "SIFT_BENCH_PROFILE": "passthrough",
            "SIFT_BENCH_TARGET": "32000",
            "SIFT_BENCH_MIN_RAW_TOKENS": "500000",
            "SIFT_BENCH_PREFLIGHT_ONLY": "1",
            "SIFT_BENCH_RUN_ID": "pair-20261016",
        })
        script = "\n".join((
            "import asyncio, logging",
            "logging.basicConfig(level=logging.INFO)",
            "import native_callback as c",
            "from fastapi import HTTPException",
            "from litellm.proxy import proxy_server",
            "proxy_server.llm_router = object()",
            "c.integration.compact_proxy_request = lambda router, data, **kw: {'metadata': {'sift': {'input_tokens': 550000, 'forwarded_tokens': 31000}}}",
            "payload = {'model': c.MODEL, 'messages': [{'role': 'user', 'content': 'secret body not logged'}]}",
            "try:",
            "    asyncio.run(c.benchmark_hook.async_pre_call_hook(None, None, payload, 'acompletion'))",
            "except HTTPException as error:",
            "    assert error.status_code == 409",
            "else:",
            "    raise AssertionError('preflight-only request was not blocked')",
        ))
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=PROCESS_TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sift_benchmark_preflight run_id=pair-20261016", result.stderr)
        self.assertIn("arm=sift", result.stderr)
        self.assertIn("raw_tokens=550000 forwarded_tokens=31000", result.stderr)
        self.assertIn("status=provider_blocked", result.stderr)
        self.assertNotIn("secret body not logged", result.stderr)

    def test_default_gateway_profile_sets_500k_raw_floor(self):
        compose = (ROOT / "benchmarks/compose.native.yaml").read_text(encoding="utf-8")
        self.assertIn("SIFT_BENCH_MIN_RAW_TOKENS: ${SIFT_BENCH_MIN_RAW_TOKENS:-500000}", compose)
        self.assertIn("SIFT_BENCH_PREFLIGHT_ONLY: ${SIFT_BENCH_PREFLIGHT_ONLY:-0}", compose)

    def test_qwen_profile_still_rejects_a_target_larger_than_its_model_budget(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "benchmarks") + os.pathsep + env.get("PYTHONPATH", ""),
            "SIFT_BENCH_ARM": "sift",
            "SIFT_BENCH_TARGET": "65536",
        })
        result = subprocess.run([sys.executable, "-c", "import native_callback"], cwd=ROOT,
                                env=env, text=True, capture_output=True, timeout=PROCESS_TIMEOUT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SIFT_BENCH_TARGET must be between 1 and 28672", result.stderr)


if __name__ == "__main__":
    unittest.main()
