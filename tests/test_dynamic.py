import json
import unittest
from sift import CompactionError
from sift.dynamic import compact_dynamic


def estimate(messages):
    return (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4


def message(role, content, **extra):
    return {"role": role, "content": content, **extra}


def topic_history():
    history = [message("system", "Keep recorded facts exact.")]
    for index in range(20):
        record = f"PAYMENT invoice billing PAYMENT_FACT_{index:02d} settled; "
        history.append(message("user", f"Record {index}: " + record * 200))
    return history


class DynamicCompactionTests(unittest.TestCase):
    def test_small_input_is_noop_with_budget_audit(self):
        source = [message("system", "policy"), message("user", "hello")]
        result = compact_dynamic(source, estimate, context_window=69632)
        self.assertEqual(result.messages, source)
        self.assertFalse(result.audit["compacted"])
        self.assertEqual(result.audit["target_tokens"], 32768)
        self.assertEqual(result.audit["context_window"], 69632)
        self.assertEqual(result.audit["output_reserve"], 4096)
        self.assertEqual(result.audit["fixed_tokens"], 0)

    def test_target_prefers_preferred_within_budget(self):
        history = topic_history()
        result = compact_dynamic(history, estimate, context_window=69632)
        self.assertTrue(result.audit["compacted"])
        self.assertEqual(result.audit["target_tokens"], 32768)
        self.assertLessEqual(result.audit["forwarded_tokens"], 32768)
        self.assertGreater(result.audit["input_tokens"], result.audit["forwarded_tokens"])

    def test_max_target_bounds_preferred(self):
        history = topic_history()
        result = compact_dynamic(history, estimate, context_window=69632,
                                 preferred_target=60000, max_target=20000,
                                 min_target=1000)
        self.assertEqual(result.audit["target_tokens"], 20000)

    def test_available_budget_bounds_target(self):
        history = topic_history()
        result = compact_dynamic(history, estimate, context_window=30000,
                                 output_reserve=0, min_target=1000,
                                 max_target=60000, preferred_target=32768)
        self.assertEqual(result.audit["target_tokens"], 30000)

    def test_fixed_tokens_overhead_reduces_target(self):
        history = topic_history()
        result = compact_dynamic(history, estimate, context_window=40000,
                                 output_reserve=1000, fixed_tokens=5000,
                                 min_target=1000, max_target=60000,
                                 preferred_target=60000)
        self.assertEqual(result.audit["target_tokens"], 34000)
        self.assertEqual(result.audit["fixed_tokens"], 5000)

    def test_insufficient_budget_fails_closed(self):
        history = topic_history()
        with self.assertRaises(CompactionError) as ctx:
            compact_dynamic(history, estimate, context_window=20000,
                            output_reserve=4096, min_target=24576)
        self.assertEqual(ctx.exception.code, "insufficient_budget")

    def test_reserve_alone_can_exhaust_budget(self):
        with self.assertRaises(CompactionError) as ctx:
            compact_dynamic([message("user", "hi")], estimate,
                            context_window=30000, output_reserve=30000,
                            min_target=1000)
        self.assertEqual(ctx.exception.code, "insufficient_budget")

    def test_malformed_configuration_is_rejected(self):
        source = [message("user", "hi")]
        for kwargs in (
            {"context_window": 0},
            {"context_window": 69632.0},
            {"context_window": True},
            {"output_reserve": -1},
            {"min_target": 0},
            {"max_target": 0},
            {"preferred_target": -5},
            {"fixed_tokens": -1},
            {"fixed_tokens": 1.5},
            {"raw_limit": 0},
            {"protocol": "grpc"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(CompactionError):
                    compact_dynamic(source, estimate, **kwargs)

    def test_max_target_below_min_target_is_rejected(self):
        with self.assertRaises(CompactionError):
            compact_dynamic([message("user", "hi")], estimate,
                            min_target=24576, max_target=100)

    def test_raw_limit_below_target_is_rejected(self):
        with self.assertRaises(CompactionError):
            compact_dynamic([message("user", "hi")], estimate,
                            raw_limit=100, context_window=69632,
                            preferred_target=32768)

    def test_anthropic_tool_groups_compact_with_real_compactor(self):
        history = [message("system", "policy")]
        for index in range(6):
            tag = str(index)
            history.append(message("user", "question " + tag + " PAYMENT fact. " * 60))
            history.append(message("assistant", [
                {"type": "tool_use", "id": "t" + tag, "name": "Read",
                 "input": {"path": "f" + tag + ".txt"}}]))
            history.append(message("user", [
                {"type": "tool_result", "tool_use_id": "t" + tag,
                 "content": "result body " * 30}]))
        history.append(message("user", "final question"))
        result = compact_dynamic(history, estimate, protocol="anthropic",
                                 context_window=69632, preferred_target=1200,
                                 max_target=2000, min_target=400)
        self.assertTrue(result.audit["compacted"])
        self.assertEqual(result.audit["target_tokens"], 1200)
        self.assertLessEqual(result.audit["forwarded_tokens"], 1200)
        self.assertEqual(result.messages[-1]["role"], "user")
        tool_ids = set()
        used_ids = set()
        for item in result.messages:
            content = item.get("content")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        tool_ids.add(block["tool_use_id"])
                    if block.get("type") == "tool_use":
                        used_ids.add(block["id"])
        self.assertTrue(tool_ids <= used_ids)

    def test_anthropic_tool_group_noop_preserves_content(self):
        source = [
            message("system", "policy"),
            message("user", "hello"),
        ]
        result = compact_dynamic(source, estimate, protocol="anthropic")
        self.assertEqual(result.messages, source)
        self.assertFalse(result.audit["compacted"])


if __name__ == "__main__":
    unittest.main()
