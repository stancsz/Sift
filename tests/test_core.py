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
