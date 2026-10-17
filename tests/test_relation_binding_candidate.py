"""Behavioral boundary tests for the opt-in research relation closure."""

import json
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from sift import core
from relation_binding_candidate import (
    CandidateError, compact_messages as benchmark_compact_messages,
)


class BenchmarkRelationBindingCandidateTests(unittest.TestCase):
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

        compacted, audit = benchmark_compact_messages(messages, count_tokens, target=520)
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
            benchmark_compact_messages(messages, lambda prompt: 100, target=10)


class ResearchRelationClosureTests(unittest.TestCase):
    @staticmethod
    def count_text(messages):
        return sum(len(message.get("content", ""))
                   for message in messages
                   if isinstance(message.get("content"), str))

    def test_opt_in_closes_only_explicitly_bound_verbatim_rows(self):
        records = [
            {
                "unit_id": "UNIT-7",
                "equipment": "Ranger maintenance unit",
                "site": "remote site seven",
            },
            {
                "equipment_id": "UNIT-7",
                "serial_code": "ZX-9274",
                "notes": "Assigned after the maintenance audit.",
            },
            {
                "serial_code": "SUP-2931",
                "notes": "Weekly supply inventory record.",
            },
        ]
        source = json.dumps(records, indent=2)
        messages = [
            {"role": "system", "content": "Answer only from the historical records."},
            {"role": "tool", "content": source},
            {"role": "user", "content": (
                "Which serial code is assigned to the Ranger maintenance unit "
                "at remote site seven?"
            )},
        ]
        original = json.loads(json.dumps(messages))

        prefix, suffix, exact_records = core._research_json_array(source)
        expected = json.loads(json.dumps(messages))
        expected[1]["content"] = prefix + "[\n" + ",\n".join(
            item[0] for item in exact_records[:2]) + "\n]" + suffix
        target = self.count_text(expected)
        result = core.compact_messages(
            messages, self.count_text, target=target,
            research_relation_closure=True,
        )

        self.assertLessEqual(result.audit["forwarded_tokens"], target)
        self.assertEqual(result.audit["method"], "research_relation_closure")
        self.assertEqual(result.messages[0], messages[0])
        self.assertEqual(result.messages[-1], messages[-1])
        selected_source = result.messages[1]["content"]
        for exact_source, _ in exact_records[:2]:
            self.assertIn(exact_source, selected_source)
        self.assertNotIn(exact_records[2][0], selected_source)
        self.assertEqual(messages, original)

    def test_named_kg_entities_keep_complete_queried_attribute_objects(self):
        concepts = {
            "Q102": {
                "name": "Newark",
                "attributes": [
                    {"property": "population", "value": 311549},
                    {"property": "area", "value": 67.1},
                ],
            },
            "Q105": {
                "name": "Trenton",
                "attributes": [
                    {"property": "population", "value": 90871},
                    {"property": "area", "value": 21.2},
                ],
            },
            "Q110": {
                "name": "Camden",
                "attributes": [
                    {"property": "population", "value": 71791},
                    {"property": "area", "value": 26.9},
                ],
            },
        }
        source = json.dumps({"source": "gazetteer", "concepts": concepts}, indent=2)
        messages = [
            {"role": "tool", "content": source},
            {"role": "user", "content": (
                "Which New Jersey city with under 350000 population has the larger area, "
                "Newark or Trenton?"
            )},
        ]
        parsed = core._research_concept_map(source)
        self.assertIsNotNone(parsed)
        prefix, suffix, exact_entities = parsed
        expected = json.loads(json.dumps(messages))
        expected[0]["content"] = prefix + "{\n" + ",\n".join(
            entry for entry, _, entity_id in exact_entities if entity_id in {"Q102", "Q105"}
        ) + "\n}" + suffix
        target = self.count_text(expected)

        result = core.compact_messages(
            messages, self.count_text, target=target,
            research_relation_closure=True,
        )

        self.assertLessEqual(result.audit["forwarded_tokens"], target)
        self.assertEqual(result.audit["requested_comparison_groups"], 2)
        self.assertEqual(result.audit["selected_comparison_groups"], 2)
        self.assertTrue(result.audit["comparison_groups_complete"])
        output = result.messages[0]["content"]
        for entry, entity, entity_id in exact_entities:
            if entity_id in {"Q102", "Q105"}:
                self.assertIn(entry, output)
                self.assertIn("population", output)
                self.assertIn("area", output)
        self.assertNotIn("Q110", output)

    def test_longbench_style_historical_user_context_keeps_prefix_and_suffix(self):
        records = [
            {
                "city_id": "CITY-1",
                "name": "Newark",
                "population": 311549,
                "area": 67.1,
            },
            {
                "city_id": "CITY-2",
                "name": "Trenton",
                "population": 90871,
                "area": 21.2,
            },
        ]
        prefix = "LongBench v2 historical context begins.\n"
        suffix = "\nLongBench v2 historical context ends."
        source = prefix + json.dumps(records, indent=2) + suffix
        messages = [
            {"role": "user", "content": source},
            {"role": "assistant", "content": "Use the cited historical facts."},
            {"role": "user", "content": (
                "Which of Newark and Trenton has the larger area, considering population?"
            )},
        ]
        _, _, exact_records = core._research_json_array(source)
        expected = json.loads(json.dumps(messages))
        expected[0]["content"] = prefix + "[\n" + ",\n".join(
            text for text, _ in exact_records) + "\n]" + suffix
        target = self.count_text(expected)

        result = core.compact_messages(
            messages, self.count_text, target=target,
            research_relation_closure=True,
        )

        self.assertLessEqual(result.audit["forwarded_tokens"], target)
        self.assertEqual(result.messages[-1], messages[-1])
        self.assertEqual(result.messages[1], messages[1])
        self.assertTrue(result.messages[0]["content"].startswith(prefix))
        self.assertTrue(result.messages[0]["content"].endswith(suffix))
        selected = json.loads(result.messages[0]["content"][
            len(prefix):len(result.messages[0]["content"]) - len(suffix)
        ])
        self.assertEqual(selected, records)
        self.assertIn("population", result.messages[0]["content"])
        self.assertIn("area", result.messages[0]["content"])

    def test_entities_map_drops_large_glossary_and_keeps_four_named_groups(self):
        names = ["Newark", "Trenton", "Camden", "Edison"]
        entities = {}
        for index, name in enumerate(names, start=1):
            entities[f"Q{100 + index}"] = {
                "name": name,
                "attributes": [
                    {"key": "population", "value": 100000 + index * 1000},
                    {"key": "area", "value": 20.5 + index},
                ],
                "description": f"Complete source entity for {name} with census facts.",
            }
        entities["Q999"] = {
            "name": "New Jersey region",
            "attributes": [
                {"key": "population", "value": 9_000_000},
                {"key": "area", "value": 22_591},
            ],
            "description": "Incidental geography record, not one of the answer choices.",
        }
        glossary = {
            f"QGLOSSARY{index}": {
                "name": f"Unrelated concept {index}",
                "definition": "Reference-only glossary data that does not answer the question.",
            }
            for index in range(794)
        }
        prefix = "LongBench v2 data context:\n"
        suffix = "\nEnd of archived source material."
        source = prefix + json.dumps(
            {"concepts": glossary, "entities": entities, "metadata": {"edition": "v2"}},
            indent=2,
        ) + suffix
        messages = [
            {"role": "user", "content": source},
            {"role": "user", "content": (
                "Which New Jersey city has the largest area among Newark (Q101), "
                "Trenton (Q102), Camden (Q103), and Edison (Q104), considering "
                "each population?"
            )},
        ]
        parsed = core._research_entity_map(source)
        self.assertIsNotNone(parsed)
        expected_prefix, expected_suffix, exact_entities = parsed
        expected = json.loads(json.dumps(messages))
        expected[0]["content"] = expected_prefix + "{\n" + ",\n".join(
            entry for entry, _, entity_id in exact_entities
            if entity_id in {"Q101", "Q102", "Q103", "Q104"}
        ) + "\n}" + expected_suffix
        incidental_length = next(
            len(entry) for entry, _, entity_id in exact_entities if entity_id == "Q999")
        target = self.count_text(expected) + incidental_length + 10

        result = core.compact_messages(
            messages, self.count_text, target=target,
            research_relation_closure=True,
        )

        self.assertLessEqual(result.audit["forwarded_tokens"], target)
        self.assertEqual(result.audit["requested_comparison_groups"], 4)
        self.assertEqual(result.audit["selected_comparison_groups"], 4)
        self.assertEqual(result.audit["unfit_comparison_groups"], 0)
        self.assertTrue(result.audit["comparison_groups_complete"])
        output = result.messages[0]["content"]
        self.assertTrue(output.startswith(prefix + '{"entities": {'))
        self.assertTrue(output.endswith("}}" + suffix))
        self.assertNotIn("concepts", output)
        self.assertNotIn("QGLOSSARY", output)
        for entry, entity, entity_id in exact_entities:
            if entity_id in {"Q101", "Q102", "Q103", "Q104"}:
                self.assertIn(entry, output)
                self.assertIn(entity["name"], output)
            self.assertIn("population", output)
            self.assertIn("area", output)
        self.assertNotIn("Q999", output)

    def test_query_qids_seed_required_entity_groups_without_name_mentions(self):
        identifiers = ["Q25395", "Q138578", "Q138367", "Q985592"]
        entities = {
            identifier: {
                "name": f"Candidate City {index}",
                "attributes": [
                    {"key": "population", "value": 120000 + index},
                    {"key": "area", "value": 35.5 + index},
                ],
            }
            for index, identifier in enumerate(identifiers, start=1)
        }
        source = json.dumps({"entities": entities}, indent=2)
        messages = [
            {"role": "user", "content": source},
            {"role": "user", "content": (
                "Which candidate has the largest area? Choices: "
                + ", ".join(identifiers)
            )},
        ]
        parsed = core._research_entity_map(source)
        self.assertIsNotNone(parsed)
        prefix, suffix, exact_entities = parsed
        expected = json.loads(json.dumps(messages))
        expected[0]["content"] = prefix + "{\n" + ",\n".join(
            entry for entry, _, _ in exact_entities) + "\n}" + suffix
        target = self.count_text(expected)

        result = core.compact_messages(
            messages, self.count_text, target=target,
            research_relation_closure=True,
        )

        self.assertEqual(result.audit["requested_comparison_groups"], 4)
        self.assertEqual(result.audit["selected_comparison_groups"], 4)
        self.assertEqual(result.audit["unfit_comparison_groups"], 0)
        self.assertTrue(result.audit["comparison_groups_complete"])
        output = result.messages[0]["content"]
        for entry, entity, _ in exact_entities:
            self.assertIn(entry, output)
            self.assertIn(entity["name"], output)

    def test_missing_query_qid_is_counted_unfit(self):
        entities = {
            "Q1": {"name": "Candidate One", "area": 45},
            "Q2": {"name": "Candidate Two", "area": 32},
        }
        source = json.dumps({"entities": entities}, indent=2)
        messages = [
            {"role": "user", "content": source},
            {"role": "user", "content": "Which is largest among Q1, Q2, and Q3?"},
        ]
        prefix, suffix, exact_entities = core._research_entity_map(source)
        expected = json.loads(json.dumps(messages))
        expected[0]["content"] = prefix + "{\n" + ",\n".join(
            entry for entry, _, _ in exact_entities) + "\n}" + suffix
        target = self.count_text(expected)

        result = core.compact_messages(
            messages, self.count_text, target=target,
            research_relation_closure=True,
        )

        self.assertEqual(result.audit["requested_comparison_groups"], 3)
        self.assertEqual(result.audit["selected_comparison_groups"], 2)
        self.assertEqual(result.audit["unfit_comparison_groups"], 1)
        self.assertFalse(result.audit["comparison_groups_complete"])

    def test_comparison_audit_reports_a_group_that_cannot_fit(self):
        records = [
            {"account_id": "ACCT-1", "balance": 810, "note": "first requested account",
             "attributes": [{"key": "population", "value": 810}]},
            {"account_id": "ACCT-2", "balance": 920, "note": "second requested account",
             "attributes": [{"key": "population", "value": 920}]},
        ]
        messages = [
            {"role": "tool", "content": json.dumps(records)},
            {"role": "user", "content": "Compare ACCT-1 vs ACCT-2 and report both balances."},
        ]
        base = json.loads(json.dumps(messages))
        base[0]["content"] = "[]"
        one_record = "[\n" + json.dumps(records[0]) + "\n]"
        target = self.count_text(base) + len(one_record) - len("[]")

        result = core.compact_messages(
            messages, self.count_text, target=target,
            research_relation_closure=True,
        )

        self.assertEqual(result.audit["requested_comparison_groups"], 2)
        self.assertEqual(result.audit["selected_comparison_groups"], 1)
        self.assertEqual(result.audit["unfit_comparison_groups"], 1)
        self.assertFalse(result.audit["comparison_groups_complete"])
        selected = json.loads(result.messages[0]["content"])
        self.assertEqual(selected, [records[0]])
        self.assertLessEqual(self.count_text(result.messages), target)

    def test_default_and_explicitly_disabled_path_are_identical(self):
        messages = [
            {"role": "user", "content": "Old topic: inventory serial ZX-9274. " * 10},
            {"role": "assistant", "content": "The recorded serial is ZX-9274."},
            {"role": "user", "content": "Now?"},
        ]
        default = core.compact_messages(messages, self.count_text, target=450)
        disabled = core.compact_messages(
            messages, self.count_text, target=450,
            research_relation_closure=False,
        )
        self.assertEqual(default, disabled)
        self.assertNotEqual(default.audit.get("method"), "research_relation_closure")

    def test_rejects_opt_in_when_no_explicit_json_tool_records_exist(self):
        messages = [
            {"role": "tool", "content": "not structured data"},
            {"role": "user", "content": "What happened?"},
        ]
        with self.assertRaises(core.CompactionError) as context:
            core.compact_messages(
                messages, self.count_text, target=4,
                research_relation_closure=True,
            )
        self.assertEqual(context.exception.code, "research_relation_unsupported")


if __name__ == "__main__":
    unittest.main()
