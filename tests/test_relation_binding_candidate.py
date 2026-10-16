"""Behavioral boundary tests for the research-only whole-record candidate."""

import json
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from relation_binding_candidate import CandidateError, compact_messages


class RelationBindingCandidateTests(unittest.TestCase):
    def test_keeps_a_complete_relevant_record_and_protected_messages(self):
        irrelevant = {
            "case": "old-log",
            "description": "Routine receipt for the weekly supply inventory.",
            "amount": 2931,
            "code": "SUP-2931",
            "notes": "A routine record with no relation to the requested serial code.",
        }
        relevant = {
            "case": "Ranger-7",
            "equipment": "Ranger maintenance unit",
            "site": "remote site seven",
            "serial_code": "ZX-9274",
            "notes": "Assigned after the maintenance audit.",
        }
        tool_content = json.dumps([irrelevant, relevant], indent=2)
        messages = [
            {"role": "system", "content": "Answer from the historical records."},
            {"role": "user", "content": "Fetch the maintenance inventory."},
            {"role": "assistant", "tool_calls": [{"id": "call-1", "type": "function",
                                                       "function": {"name": "fetch", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": tool_content},
            {"role": "user", "content": "Which serial code is assigned to the Ranger maintenance unit at remote site seven?"},
        ]
        original = json.loads(json.dumps(messages))

        def count_tokens(prompt):
            return sum(len(message.get("content", "")) for message in prompt)

        compacted, audit = compact_messages(messages, count_tokens, target=520)
        self.assertLessEqual(audit["forwarded_tokens"], 520)
        self.assertGreater(audit["input_tokens"], 520)
        self.assertEqual(compacted[0], messages[0])
        self.assertEqual(compacted[-1], messages[-1])
        self.assertEqual(compacted[1:3], messages[1:3])
        self.assertEqual(compacted[4], messages[4])
        selected = json.loads(compacted[3]["content"])
        self.assertIn(relevant, selected)
        self.assertNotIn(irrelevant, selected)
        self.assertEqual(audit["selected_records"], 1)
        self.assertEqual(messages, original)

    def test_fails_closed_when_required_tool_array_is_missing(self):
        messages = [
            {"role": "tool", "content": "not json"},
            {"role": "user", "content": "What happened?"},
        ]
        with self.assertRaises(CandidateError):
            compact_messages(messages, lambda prompt: 100, target=10)


if __name__ == "__main__":
    unittest.main()
