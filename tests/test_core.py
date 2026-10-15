import copy
import json
import unittest

from sift import CompactionError, compact_messages


def estimate(messages):
    return (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4


def message(role, content, **extra):
    return {"role": role, "content": content, **extra}


class CompactionTests(unittest.TestCase):
    def test_small_input_is_unchanged_and_audited(self):
        source = [message("system", "Follow project policy"), message("user", "hello")]
        result = compact_messages(source, estimate, target=200)
        self.assertEqual(result.messages, source)
        self.assertIsNot(result.messages, source)
        self.assertFalse(result.audit["compacted"])
        self.assertEqual(result.audit["input_tokens"], estimate(source))
        self.assertEqual(result.audit["forwarded_tokens"], estimate(source))

    def test_middle_relevant_evidence_beats_noise(self):
        lines = ["ordinary build progress line " + str(i) for i in range(400)]
        lines[201] = "MIDDLE_KEY: azure-73; this is the deployment setting"
        source = [message("system", "Be accurate"), message("user", "\n".join(lines)),
                  message("assistant", "Log received"),
                  message("user", "What was the MIDDLE_KEY deployment setting?")]
        result = compact_messages(source, estimate, target=500)
        self.assertTrue(result.audit["compacted"])
        self.assertLessEqual(result.audit["forwarded_tokens"], 500)
        self.assertEqual(result.messages[0], source[0])
        self.assertEqual(result.messages[-1], source[-1])
        self.assertIn("azure-73", result.messages[1]["content"])
        self.assertIn("untrusted", result.messages[1]["content"].lower())

    def test_selected_failure_keeps_neighboring_diagnostic(self):
        lines = [f"routine build output {i}" for i in range(1_000)]
        lines[500] = "FAILED test_invoice_total"
        lines[501] = "rounding_mode=HALF_EVEN; observed +0.01 versus Decimal expected"
        source = [message("user", "\n".join(lines)),
                  message("assistant", "Build log received"),
                  message("user", "What caused FAILED test_invoice_total?")]
        result = compact_messages(source, estimate, target=700)
        evidence = str(result.messages)
        self.assertIn("FAILED test_invoice_total", evidence)
        self.assertIn("rounding_mode=HALF_EVEN", evidence)
        self.assertLessEqual(result.audit["forwarded_tokens"], 700)

    def test_current_tool_chain_and_prior_complete_turn_survive(self):
        prior = [message("user", "Run tests"),
                 message("assistant", None, tool_calls=[{"id": "x", "function": {"name": "test", "arguments": "{}"}}]),
                 message("tool", "FAILED: test_gateway", tool_call_id="x"),
                 message("assistant", "Need repair")]
        current = [message("user", "Fix test_gateway"), message("assistant", "Checking")]
        source = [message("system", "Safety"), message("user", "noise " * 2500),
                  message("assistant", "old"), *prior, *current]
        saved = copy.deepcopy(source)
        result = compact_messages(source, estimate, target=700)
        self.assertEqual(source, saved)
        self.assertEqual(result.messages[-6:], prior + current)
        self.assertLessEqual(result.audit["forwarded_tokens"], 700)
        self.assertGreaterEqual(result.audit["preserved_recent_turns"], 1)

    def test_anthropic_tool_result_does_not_reanchor_current_turn(self):
        current = [message("user", "Fix the bug"),
                   message("assistant", [{"type": "tool_use", "id": "x", "name": "Read", "input": {}}]),
                   message("user", [{"type": "tool_result", "tool_use_id": "x", "content": "error here"}])]
        source = [message("user", "noise " * 2000), message("assistant", "old"), *current]
        result = compact_messages(source, estimate, target=500, protocol="anthropic")
        self.assertEqual(result.messages[-3:], current)

    def test_long_single_claude_tool_turn_compacts_older_cycles(self):
        task = message("user", "Fix the booking timezone tests and keep the original requirement.")
        cycles = []
        for index in range(24):
            cycles.extend([
                message("assistant", [{"type": "tool_use", "id": f"tool_{index}",
                                       "name": "PowerShell", "input": {"command": "python -m unittest"}}]),
                message("user", [{"type": "tool_result", "tool_use_id": f"tool_{index}",
                                  "content": f"test run {index}: " + "verbose output " * 70}]),
            ])
        cycles[-1]["content"][0]["content"] += "\nFAILED: test_dst_gap"
        source = [message("system", "Follow project rules"), task, *cycles]
        result = compact_messages(source, estimate, target=1_400, protocol="anthropic")
        self.assertLessEqual(result.audit["forwarded_tokens"], 1_400)
        self.assertEqual(result.messages[0], source[0])
        self.assertIn(task, result.messages)
        self.assertEqual(result.messages[-2:], cycles[-2:])
        self.assertIn("test_dst_gap", str(result.messages[-1]))
        self.assertTrue(result.audit["compacted"])

    def test_old_thinking_is_omitted_while_current_thinking_is_exact(self):
        source = [
            message("user", "Find the failure"),
            message("assistant", [
                {"type": "thinking", "thinking": "private prior reasoning", "signature": "sig-old"},
                {"type": "tool_use", "id": "old", "name": "Read", "input": {}},
            ]),
            message("user", [{"type": "tool_result", "tool_use_id": "old",
                              "content": "FAILED: test_policy " + "noise " * 1000}]),
            message("assistant", [
                {"type": "thinking", "thinking": "private current reasoning", "signature": "sig-new"},
                {"type": "tool_use", "id": "new", "name": "Read", "input": {}},
            ]),
            message("user", [{"type": "tool_result", "tool_use_id": "new",
                              "content": "Current file content"}]),
        ]
        result = compact_messages(source, estimate, target=600, protocol="anthropic")
        self.assertEqual(result.messages[-2:], source[-2:])
        self.assertNotIn("private prior reasoning", str(result.messages))
        self.assertIn("private current reasoning", str(result.messages))

    def test_long_openai_tool_loop_keeps_latest_call_and_result(self):
        task = message("user", "Finish the ledger reconciliation")
        cycles = []
        for index in range(18):
            cycles.extend([
                message("assistant", None, tool_calls=[{"id": f"call_{index}", "type": "function",
                    "function": {"name": "run", "arguments": "{}"}}]),
                message("tool", f"result {index}: " + "routine output " * 70,
                        tool_call_id=f"call_{index}"),
            ])
        source = [task, *cycles]
        result = compact_messages(source, estimate, target=1_200, protocol="openai")
        self.assertIn(task, result.messages)
        self.assertEqual(result.messages[-2:], cycles[-2:])
        self.assertLessEqual(result.audit["forwarded_tokens"], 1_200)

    def test_completed_early_tool_epoch_keeps_stable_excerpt_prefix(self):
        task = message("user", "Investigate invoice replay failure")
        cycles = []
        for index in range(15):
            cycles.extend([
                message("assistant", None, tool_calls=[{"id": f"call_{index}", "type": "function",
                    "function": {"name": "run", "arguments": "{}"}}]),
                message("tool", f"invoice replay diagnostic {index}: " + "log output " * 95,
                        tool_call_id=f"call_{index}"),
            ])
        first = compact_messages([task, *cycles[:-2]], estimate, target=4_000)
        second = compact_messages([task, *cycles], estimate, target=4_000)
        self.assertGreater(first.audit["stable_epoch_excerpts"], 0)
        self.assertEqual(first.audit["stable_epoch_excerpts"], second.audit["stable_epoch_excerpts"])
        def early_lines(result):
            return [line for line in result.messages[1]["content"].splitlines()
                    if line.startswith("[message ") and int(line.split()[1]) <= 12]
        self.assertEqual(early_lines(first), early_lines(second))
        self.assertLessEqual(second.audit["forwarded_tokens"], 4_000)

    def test_tool_cycles_append_without_rewriting_prefix_inside_barrier(self):
        task = message("user", "Find the newest failing test")
        cycles = []
        for index in range(20):
            cycles.extend([
                message("assistant", None, tool_calls=[{"id": f"x{index}", "type": "function",
                    "function": {"name": "Read", "arguments": "{}"}}]),
                message("tool", f"FAILED test_{index} " + "log output " * 80,
                        tool_call_id=f"x{index}"),
            ])
        results = [compact_messages([task, *cycles[:2 * count]], estimate, target=3_000)
                   for count in (18, 19, 20)]
        for earlier, later in zip(results, results[1:]):
            self.assertTrue(earlier.audit["compacted"])
            self.assertLessEqual(later.audit["forwarded_tokens"], 3_000)
            self.assertEqual(later.messages[:len(earlier.messages)], earlier.messages)
        self.assertEqual(results[-1].messages[-1], cycles[-1])

    def test_named_test_failures_survive_a_fixed_tool_epoch(self):
        task = message("user", "Implement the incremental build planner")
        cycles = []
        failures = tuple(f"ERROR: test_case_{index}" for index in range(10)) + (
            "FAIL: test_rejects_cycle", "FAILED tests/test_build.py::test_missing_input",
        )
        for index in range(20):
            log = "build planner routine output " * 20
            if index == 5:
                log = "\n".join(failures)
            cycles.extend([
                message("assistant", [{"type": "tool_use", "id": f"x{index}",
                                       "name": "PowerShell", "input": {"command": "test"}}]),
                message("user", [{"type": "tool_result", "tool_use_id": f"x{index}",
                                  "content": log}]),
            ])
        results = [compact_messages([task, *cycles[:2 * count]], estimate,
                                    target=3_000, protocol="anthropic")
                   for count in (18, 19, 20)]
        for result in results:
            self.assertTrue(all(failure in str(result.messages) for failure in failures))
            self.assertLessEqual(result.audit["forwarded_tokens"], 3_000)
        for earlier, later in zip(results, results[1:]):
            self.assertEqual(later.messages[:len(earlier.messages)], earlier.messages)

    def test_limits_and_unsupported_media_fail_closed(self):
        source = [message("user", "old " * 1000), message("assistant", "old"),
                  message("user", "new " * 1000)]
        with self.assertRaisesRegex(CompactionError, "raw_limit"):
            compact_messages(source, estimate, target=100, raw_limit=200)
        with self.assertRaisesRegex(CompactionError, "active"):
            compact_messages(source, estimate, target=100)
        media = [message("user", "old " * 1000), message("user", [{"type": "image", "data": "x"}])]
        with self.assertRaisesRegex(CompactionError, "content"):
            compact_messages(media, estimate, target=100)

    def test_late_instruction_is_not_silently_moved(self):
        source = [message("user", "old " * 2000), message("system", "late"), message("user", "now")]
        with self.assertRaisesRegex(CompactionError, "instruction"):
            compact_messages(source, estimate, target=300)

    def test_deterministic_selection_and_no_mutation(self):
        source = [message("user", "\n".join(f"item {i}: {i*i}" for i in range(600))),
                  message("assistant", "received"), message("user", "What is item 317?")]
        before = copy.deepcopy(source)
        a = compact_messages(source, estimate, target=400)
        b = compact_messages(source, estimate, target=400)
        self.assertEqual(a, b)
        self.assertEqual(source, before)
        self.assertIn("item 317", a.messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
