import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


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
                })
                script = (
                    "import native_callback as c; "
                    f"assert c.benchmark_hook.model_targets == {{'minimax-m3-sift': {target}}}; "
                    "assert c.FULL_MODEL not in c.benchmark_hook.model_targets; "
                    "assert c.MODEL != c.FULL_MODEL; "
                    "assert c.PROFILE == 'passthrough'; "
                    f"assert c._selector.__module__ == {selector_module!r}; "
                    "import asyncio; "
                    "assert asyncio.run(c.benchmark_hook.async_pre_call_hook(None, None, "
                    "{'model': c.FULL_MODEL, 'messages': [{'role': 'user', 'content': 'same input'}]}, "
                    "'acompletion')) is None; "
                    "assert c.qwen_instruction_prefix({'model': c.MODEL, 'messages': []}, 'anthropic_messages')['messages'] == []"
                )
                result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                        text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_qwen_profile_still_rejects_a_target_larger_than_its_model_budget(self):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT / "benchmarks") + os.pathsep + env.get("PYTHONPATH", ""),
            "SIFT_BENCH_ARM": "sift",
            "SIFT_BENCH_TARGET": "65536",
        })
        result = subprocess.run([sys.executable, "-c", "import native_callback"], cwd=ROOT,
                                env=env, text=True, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SIFT_BENCH_TARGET must be between 1 and 28672", result.stderr)


if __name__ == "__main__":
    unittest.main()
