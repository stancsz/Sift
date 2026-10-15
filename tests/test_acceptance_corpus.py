"""Domain-spanning retrieval checks for query-aware extractive compaction."""

import json
import unittest

from sift import compact_messages


def estimate(messages):
    return (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4


class CorpusTests(unittest.TestCase):
    def test_middle_facts_across_domains(self):
        cases = [
            ("Which test failed in build B42?", "build B42: FAILED test_policy_snapshot"),
            ("What was the charge ID for account oak?", "account oak charge ID CHG-771"),
            ("When is appointment APPT-42?", "appointment APPT-42 begins 2026-11-03T15:30Z"),
            ("Which file caused error E731?", "error E731 in src/relay.py line 88"),
            ("What DOI supports the finding?", "finding supported by DOI 10.7777/sift.42"),
        ]
        for question, fact in cases:
            with self.subTest(question=question):
                log = [f"routine progress step {i}" for i in range(600)]
                log[300] = fact
                source = [{"role": "user", "content": "\n".join(log)},
                          {"role": "assistant", "content": "noted"},
                          {"role": "user", "content": question}]
                result = compact_messages(source, estimate, target=450)
                self.assertIn(fact, result.messages[0]["content"])
                self.assertLessEqual(result.audit["forwarded_tokens"], 450)

    def test_repeated_noise_does_not_displace_specific_fact(self):
        text = "noise line\n" * 400 + "ERROR CODE R97: missing index\n" + "noise line\n" * 400
        source = [{"role": "user", "content": text},
                  {"role": "assistant", "content": "noted"},
                  {"role": "user", "content": "What caused ERROR CODE R97?"}]
        result = compact_messages(source, estimate, target=350)
        self.assertIn("missing index", result.messages[0]["content"])
        self.assertLessEqual(result.audit["selected_excerpts"], 96)

    def test_old_and_new_conflicting_facts_are_quoted_in_order(self):
        lines = ["filler " + str(i) for i in range(400)]
        lines[100] = "deployment EAST status: pending"
        lines[300] = "deployment EAST status: complete"
        source = [{"role": "user", "content": "\n".join(lines)},
                  {"role": "assistant", "content": "received"},
                  {"role": "user", "content": "What is deployment EAST status?"}]
        result = compact_messages(source, estimate, target=500)
        summary = result.messages[0]["content"]
        self.assertIn("status: pending", summary)
        self.assertIn("status: complete", summary)
        self.assertLess(summary.index("status: pending"), summary.index("status: complete"))


if __name__ == "__main__":
    unittest.main()
