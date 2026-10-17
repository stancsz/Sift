"""Focused contract tests for opt-in, one-hop LongBench label projection."""

from copy import deepcopy
import json
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sift import CompactionError, compact_messages, core
from unittest.mock import patch


def count_text(messages):
    """Generous deterministic stand-in for a tokenizer in these fixtures."""
    return sum(len(message.get("content", ""))
               for message in messages
               if isinstance(message.get("content"), str))


def _messages(*, unresolved=False, colliding=False, malformed_field=None,
              selected_detail_repetitions=0, missing_label=False):
    relation_target = "Q404" if missing_label else "Q1001"
    alpha = {
        "name": "Choice Alpha",
        "rank": 1,
        "relations": [{"property": "P31", "object": relation_target}],
        "instanceOf": "Q1003",
        "subclassOf": "Q1002",
        "notes": {"paragraph": "Q999 is merely prose, not a typed relation."},
    }
    beta = {
        "name": "Choice Beta",
        "rank": 2,
        "relations": [{"property": "P31", "object": "Q1001"}],
        "instanceOf": "Q1003",
        "subclassOf": "Q1002",
    }
    if selected_detail_repetitions:
        alpha["required_detail"] = "complete choice detail " * selected_detail_repetitions
        beta["required_detail"] = "complete choice detail " * selected_detail_repetitions
    if malformed_field == "relations":
        alpha["relations"][0]["object"] = "not-a-qid"
    elif malformed_field in {"instanceOf", "subclassOf"}:
        alpha[malformed_field] = "not-a-qid"
    entities = {
        "Q101": alpha,
        "Q102": beta,
        "Q800": {"name": "Unselected archive", "payload": "unused " * 350},
    }
    concepts = {
        "Q1001": {
            "name": "Category",
            "label": "category label",
            "subclassOf": "Q1004",
            "instanceOf": "Q1005",
            "description": "unrelated detail " * 100,
            "metadata": {"nested": "Q777"},
        },
        "Q1002": {"name": "Subclass", "description": "unrelated detail " * 100},
        "Q1004": {"name": "Do not recurse", "description": "deep " * 100},
        "Q1005": {"name": "Do not recurse type", "description": "deep " * 100},
    }
    if colliding:
        concepts["q1001"] = {"name": "Case-colliding category"}
    source = json.dumps({
        "source": "synthetic typed-identity fixture",
        "entities": entities,
        "concepts": concepts,
        "labels": {
            "Q1003": {"name": "Type", "label": "type label", "details": "unused " * 100},
            "Q900": {"name": "Unused label", "details": "unused " * 100},
        },
    }, indent=2)
    return [
        {"role": "tool", "content": source},
        {"role": "user", "content": (
            "Compare the two candidates by their typed category and type.\n"
            + ("Choices:\n(A) Q101\n(B) Q404" if unresolved else
               "Choices:\n(A) Q101\n(B) Q102")
        )},
    ]


def _entry_slice(source, map_name, record_id):
    """Return the exact source slice for a map entry, including its key."""
    root = json.loads(source)
    map_value = root[map_name]
    assert record_id in map_value
    marker = json.dumps(record_id) + ": "
    start = source.index(marker, source.index(json.dumps(map_name) + ":"))
    value_start = start + len(marker)
    _, end = json.JSONDecoder().raw_decode(source, value_start)
    return source[start:end]


class QueryDirectedLabelTests(unittest.TestCase):
    def test_qid_choices_keep_full_records_and_project_only_one_hop_identities(self):
        messages = _messages()
        original = deepcopy(messages)
        source = messages[0]["content"]

        result = compact_messages(
            messages, count_text, target=4_000,
            query_directed_labels=True,
        )

        rendered = result.messages[0]["content"]
        compacted = json.loads(rendered)
        for record_id in ("Q101", "Q102"):
            self.assertEqual(
                _entry_slice(rendered, "entities", record_id),
                _entry_slice(source, "entities", record_id),
                f"complete choice entry {record_id} must remain byte-for-byte unchanged",
            )

        identities = compacted["__sift_identity_labels"]
        self.assertEqual(set(identities), {"Q1001", "Q1002", "Q1003"})
        self.assertEqual(identities["Q1001"]["name"], "Category")
        self.assertEqual(identities["Q1002"]["name"], "Subclass")
        self.assertEqual(identities["Q1003"]["name"], "Type")

        allowed_identity_fields = {
            "name", "label", "title", "type", "category", "kind",
            "instanceOf", "subclassOf",
        }
        for identity in identities.values():
            if isinstance(identity, dict):
                self.assertLessEqual(set(identity), allowed_identity_fields)
        self.assertNotIn("Q1004", identities)
        self.assertNotIn("Q1005", identities)
        self.assertNotIn("Q999", identities)
        self.assertNotIn("Q777", identities)
        self.assertNotIn("Q900", identities)
        self.assertNotIn("description", rendered)
        self.assertNotIn("unused ", rendered)
        self.assertEqual(messages, original)

    def test_unresolved_typed_reference_fails_closed(self):
        messages = _messages(unresolved=True)
        with self.assertRaises(CompactionError) as context:
            compact_messages(messages, count_text, target=4_000,
                             query_directed_labels=True)
        self.assertEqual(context.exception.code, "query_directed_label_unresolved")

    def test_missing_optional_relation_label_is_audited_while_ref_is_retained(self):
        messages = _messages(missing_label=True)
        result = compact_messages(messages, count_text, target=4_000,
                                  query_directed_labels=True)
        compacted = json.loads(result.messages[0]["content"])
        self.assertEqual(result.audit["unresolved_identity_ids"], "Q404")
        self.assertEqual(result.audit["unresolved_identity_labels"], 1)
        self.assertNotIn("Q404", compacted["__sift_identity_labels"])
        self.assertEqual(
            compacted["entities"]["Q101"]["relations"][0]["object"], "Q404",
        )

    def test_malformed_typed_reference_fails_closed(self):
        for field in ("relations", "instanceOf", "subclassOf"):
            with self.subTest(field=field):
                messages = _messages(malformed_field=field)
                with self.assertRaises(CompactionError) as context:
                    compact_messages(messages, count_text, target=4_000,
                                     query_directed_labels=True)
                self.assertEqual(context.exception.code, "research_relation_unsupported")

    def test_case_colliding_id_sources_fail_closed(self):
        messages = _messages(colliding=True)
        with self.assertRaises(CompactionError) as context:
            compact_messages(messages, count_text, target=4_000,
                             query_directed_labels=True)
        self.assertEqual(context.exception.code, "query_directed_label_ambiguous")

    def test_projected_records_over_exact_target_fail_closed(self):
        messages = _messages()
        with self.assertRaises(CompactionError) as context:
            compact_messages(messages, count_text, target=900,
                             query_directed_labels=True)
        self.assertEqual(context.exception.code, "query_directed_label_target")

    def test_projection_over_ten_percent_growth_fails_closed(self):
        messages = _messages()
        baseline = compact_messages(messages, count_text, target=4_000)
        over_limit = (baseline.audit["forwarded_tokens"] * 11 // 10) + 1
        proposal = core.CompactionResult(
            deepcopy(messages), {"forwarded_tokens": over_limit},
        )

        with self.assertRaises(CompactionError) as context:
            with patch.object(core, "_query_directed_label_compact",
                              return_value=proposal):
                compact_messages(messages, count_text, target=4_000,
                                 query_directed_labels=True)
        self.assertEqual(context.exception.code, "query_directed_label_growth_limit")

    def test_default_call_matches_explicit_false(self):
        messages = _messages()
        baseline = compact_messages(messages, count_text, target=4_000)
        explicitly_disabled = compact_messages(
            messages, count_text, target=4_000, query_directed_labels=False,
        )
        self.assertEqual(explicitly_disabled, baseline)


if __name__ == "__main__":
    unittest.main()
