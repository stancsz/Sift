"""Historical source evidence must survive competing task vocabulary."""
import json
import unittest

from sift import compact_messages


def estimate(messages):
    return (len(json.dumps(messages)) + 3) // 4


def history(fact, position=150):
    lines = [f"routine archive record {i}: ordinary completed work" for i in range(300)]
    lines[position] = fact
    messages = [{"role": "user", "content": "Archive:\n" + "\n".join(lines)}]
    for i in range(12):
        messages.extend([
            {"role": "user", "content": f"Task stage {i}: implement parser currency totals rounding validation report. " * 12},
            {"role": "assistant", "content": f"Stage {i} parser currency totals rounding validation report completed. " * 12},
        ])
    return messages


class HistoryRecallTests(unittest.TestCase):
    def test_old_source_fact_survives_verbose_task_echoes(self):
        fact = "Recorded renewal setting: renewal_window_days=41; retain this exact setting."
        messages = history(fact)
        active = {"role": "user", "content": "Implement parser currency totals rounding validation report; also retrieve the earlier recorded configuration value."}
        messages.append(active)
        result = compact_messages(messages, estimate, target=1200)
        historical = "\n".join(m["content"] for m in result.messages
                               if m["role"] == "user" and m["content"].startswith("Earlier conversation"))
        self.assertIn(fact, historical)
        self.assertIn("[message 0 user]", historical)
        self.assertIn("untrusted historical data", historical)
        self.assertEqual(result.messages[-1], active)
        self.assertLessEqual(estimate(result.messages), 1200)

    def test_retention_signal_survives_topic_changes_at_different_positions_and_budgets(self):
        fact = "Storage policy: retain records for 93 days before shredding."
        active = {"role": "user", "content": "Continue the parser currency totals rounding validation report."}
        for position in (10, 150, 290):
            for target in (1200, 1600):
                with self.subTest(position=position, target=target):
                    messages = history(fact, position) + [active]
                    result = compact_messages(messages, estimate, target=target)
                    self.assertIn(fact, json.dumps(result.messages))
                    self.assertEqual(result.messages[-1], active)
                    self.assertLessEqual(estimate(result.messages), target)

    def test_identifier_query_still_selects_the_source_value(self):
        fact = "Recorded renewal setting: renewal_window_days=41; retain this exact setting."
        active = {"role": "user", "content": "Retrieve renewal_window_days from the earlier recorded configuration."}
        result = compact_messages(history(fact) + [active], estimate, target=1200)
        self.assertIn(fact, json.dumps(result.messages))
        self.assertEqual(result.messages[-1], active)
        self.assertLessEqual(estimate(result.messages), 1200)

    def diagnostic_history(self):
        fact = "Storage policy: retain records for 93 days before shredding."
        messages = history(fact)
        messages[1:1] = [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "check", "type": "function",
                "function": {"name": "check", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "check", "content": "ERROR: test_evidence\nFAIL: test_behavior"},
        ]
        active = {"role": "user", "content": "Continue the parser currency totals rounding validation report."}
        return messages + [active], active, fact

    def test_source_signal_and_prior_diagnostic_survive_together(self):
        messages, active, fact = self.diagnostic_history()
        result = compact_messages(messages, estimate, target=1800)
        quoted = "\n".join(m["content"] for m in result.messages if isinstance(m.get("content"), str))
        self.assertIn(fact, quoted)
        self.assertIn("ERROR: test_evidence", quoted)
        self.assertIn("[message 0 user]", quoted)
        self.assertIn("[message 2 tool]", quoted)
        self.assertEqual(result.messages[-1], active)
        self.assertLessEqual(estimate(result.messages), 1800)

    def test_tight_anchor_budget_keeps_diagnostic_priority(self):
        messages, active, _ = self.diagnostic_history()
        result = compact_messages(messages, estimate, target=800)
        self.assertIn("ERROR: test_evidence", json.dumps(result.messages))
        self.assertEqual(result.messages[-1], active)
        self.assertLessEqual(estimate(result.messages), 800)


if __name__ == "__main__":
    unittest.main()
