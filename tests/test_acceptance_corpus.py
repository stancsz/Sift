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

    def test_distant_identifier_join_retains_both_evidence_lines(self):
        cases = [
            ("Which timezone governs invoice INV-42?",
             "invoice INV-42 belongs to corridor C7",
             "corridor C7 settlement timezone America/Denver"),
            ("When is retry permitted for webhook d-42?",
             "webhook d-42 assigned policy P7",
             "policy P7 retry_after 2026-10-15T18:00Z"),
            ("Which digest verifies package pkg42?",
             "package pkg42 maps to artifact A9",
             "artifact A9 sha256 4b7a43deadbeef"),
        ]
        for question, first, second in cases:
            with self.subTest(question=question):
                lines = [f"normal processing record {index} payload ok"
                         for index in range(1_200)]
                lines[170], lines[940] = first, second
                source = [{"role": "user", "content": "\n".join(lines)},
                          {"role": "assistant", "content": "received"},
                          {"role": "user", "content": question}]
                result = compact_messages(source, estimate, target=400)
                evidence = str(result.messages)
                self.assertIn(first, evidence)
                self.assertIn(second, evidence)
                self.assertLessEqual(result.audit["forwarded_tokens"], 400)

    def test_changed_mapping_keeps_old_and_current_join_paths(self):
        lines = [f"normal processing record {index} payload ok"
                 for index in range(1_200)]
        facts = (
            "webhook d-42 assigned policy P7 (superseded)",
            "policy P7 retry_after 2026-10-15T18:00Z",
            "webhook d-42 assigned policy P8 (current)",
            "policy P8 retry_after 2026-10-16T18:00Z",
        )
        for index, fact in zip((100, 200, 750, 900), facts):
            lines[index] = fact
        source = [{"role": "user", "content": "\n".join(lines)},
                  {"role": "assistant", "content": "received"},
                  {"role": "user", "content":
                   "When is retry currently permitted for webhook d-42?"}]
        result = compact_messages(source, estimate, target=400)
        evidence = str(result.messages)
        self.assertTrue(all(fact in evidence for fact in facts))
        self.assertLess(evidence.index(facts[0]), evidence.index(facts[2]))
        self.assertLess(evidence.index(facts[1]), evidence.index(facts[3]))

    def test_repeated_query_terms_do_not_hide_rare_joined_evidence(self):
        lines = [f"normal webhook d-42 heartbeat seq={index} status=ok"
                 for index in range(6_000)]
        mapping = "webhook d-42 assigned policy P8 (current)"
        deadline = "policy P8 retry_after 2026-10-16T18:00Z"
        lines[1_500], lines[4_500] = mapping, deadline
        source = [{"role": "user", "content": "\n".join(lines)},
                  {"role": "assistant", "content": "received"},
                  {"role": "user", "content": "When may webhook d-42 retry?"}]
        result = compact_messages(source, estimate, target=800)
        evidence = str(result.messages)
        self.assertIn(mapping, evidence)
        self.assertIn(deadline, evidence)
        self.assertLessEqual(result.audit["forwarded_tokens"], 800)


if __name__ == "__main__":
    unittest.main()
