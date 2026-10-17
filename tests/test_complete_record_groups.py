"""Focused checks for opt-in all-or-nothing structured record retention."""

from copy import deepcopy
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sift import CompactionError, compact_messages, core


def count_text(messages):
    return sum(len(message.get("content", ""))
               for message in messages
               if isinstance(message.get("content"), str))


class CompleteRecordGroupTests(unittest.TestCase):
    def test_field_pruning_is_default_off_and_preserves_linked_results(self):
        source_object = {
            "meta": {"run": "held-out"},
            "round_results": [
                {"responses": ["p1", "p2", "p3", "p4"],
                 "winner_id": f"p{index % 4 + 1}", "round_number": index}
                for index in range(1, 9)
            ],
            "participants": [
                {"id": f"p{index}", "record": [index, index + 1, index + 2],
                 "utility": [index * 2, index * 3, index * 4],
                 "prompt": [{"role": "user", "content": "verbose history " * 25},
                            {"role": "assistant", "content": "verbose answer " * 25}]}
                for index in range(1, 8)
            ],
        }
        messages = [
            {"role": "tool", "content": json.dumps(source_object, indent=2)},
            {"role": "user", "content": (
                "Which participant won most often?\nChoices:\n"
                "(A) p1\n(B) p2\n(C) p3\n(D) p4"
            )},
        ]
        original = deepcopy(messages)
        baseline = compact_messages(messages, count_text, target=2_200)
        disabled = compact_messages(messages, count_text, target=2_200,
                                    field_pruning=False)
        candidate = compact_messages(
            messages, count_text, target=2_200, field_pruning=True,
        )

        self.assertEqual(baseline, disabled)
        self.assertNotEqual(candidate.messages, baseline.messages)
        self.assertLessEqual(candidate.audit["forwarded_tokens"], 2_200)
        self.assertLessEqual(candidate.audit["forwarded_tokens"] * 10,
                             baseline.audit["forwarded_tokens"] * 11)
        compacted = json.loads(candidate.messages[0]["content"])
        self.assertEqual(compacted["round_results"], source_object["round_results"])
        self.assertEqual([row["id"] for row in compacted["participants"]],
                         ["p1", "p2", "p3", "p4"])
        for row in compacted["participants"]:
            self.assertTrue(row["record"])
            self.assertTrue(row["utility"])
            self.assertNotIn("prompt", row)
        self.assertEqual(messages, original)

    def test_field_pruning_growth_limit_rejects_candidate_over_ten_percent(self):
        messages = [
            {"role": "tool", "content": json.dumps({
                "rounds": [{"round": index, "winner": index % 4}
                           for index in range(1, 9)],
                "players": [
                    {"id": f"p{index}", "score": list(range(20)),
                     "prompt": [{"role": "user", "content": "verbose " * 100}]}
                    for index in range(1, 5)
                ],
            })},
            {"role": "user", "content": (
                "Who won?\nChoices:\n(A) p1\n(B) p2\n(C) p3\n(D) p4"
            )},
        ]
        target = 2_200
        baseline = compact_messages(messages, count_text, target=target)
        over_limit = (baseline.audit["forwarded_tokens"] * 11 // 10) + 1
        proposal = core.CompactionResult(
            deepcopy(messages), {"forwarded_tokens": over_limit},
        )

        with patch.object(core, "_field_pruning_compact", return_value=proposal):
            with self.assertRaises(CompactionError) as context:
                compact_messages(messages, count_text, target=target,
                                 field_pruning=True)

        self.assertEqual(context.exception.code, "field_pruning_growth_limit")

    def test_field_pruning_skips_unrelated_partial_choice_array(self):
        messages = [
            {"role": "tool", "content": json.dumps({
                "old_rows": [{"id": "p1", "score": [9, 9]}],
                "other": [{"id": "old", "value": 1}],
            })},
            {"role": "tool", "content": json.dumps({
                "summary": [{"round": 1, "winner": 2},
                            {"round": 2, "winner": 3}],
                "players": [
                    {"id": f"p{index}", "score": [index, index + 1],
                     "prompt": [{"role": "user", "content": "noise " * 30}]}
                    for index in range(1, 5)
                ],
            })},
            {"role": "user", "content": (
                "Who won?\nChoices:\n(A) p1\n(B) p2\n(C) p3\n(D) p4"
            )},
        ]

        result = compact_messages(messages, count_text, target=1_500,
                                  field_pruning=True)

        self.assertEqual(result.messages[0]["content"], messages[0]["content"])
        selected = json.loads(result.messages[1]["content"])
        self.assertEqual([row["id"] for row in selected["players"]],
                         ["p1", "p2", "p3", "p4"])
        self.assertTrue(selected["summary"])

    def test_field_pruning_fails_closed_when_shared_summary_is_missing(self):
        messages = [
            {"role": "tool", "content": json.dumps({
                "players": [
                    {"id": "p1", "score": [1, 2], "prompt": [
                        {"role": "user", "content": "long " * 40}]},
                    {"id": "p2", "score": [2, 1], "prompt": [
                        {"role": "user", "content": "long " * 40}]},
                ],
            })},
            {"role": "user", "content": "Who won?\nChoices:\n(A) p1\n(B) p2"},
        ]
        with self.assertRaises(CompactionError) as context:
            compact_messages(messages, count_text, target=500,
                             field_pruning=True)
        self.assertEqual(context.exception.code, "field_pruning_summary_missing")

    def test_field_pruning_fails_closed_on_ambiguous_choice_arrays(self):
        players = [
            {"id": "p1", "score": [1, 2]},
            {"id": "p2", "score": [2, 1]},
        ]
        messages = [
            {"role": "tool", "content": json.dumps({
                "first": players, "second": players,
                "round_results": [{"winner": "p1"}],
            })},
            {"role": "user", "content": "Who won?\nChoices:\n(A) p1\n(B) p2"},
        ]
        with self.assertRaises(CompactionError) as context:
            compact_messages(messages, count_text, target=100,
                             field_pruning=True)
        self.assertEqual(context.exception.code, "field_pruning_ambiguous")

    def test_field_pruning_rejects_csv_decoy_choice_column(self):
        messages = [
            {"role": "tool", "content": (
                "<text>\nartist,album,notes\n"
                "Acme,Widget,Widget\nAcme,Gadget,notes\n"
                "Beta,Spring,Spring\nBeta,Coil,notes\n</text>"
            )},
            {"role": "user", "content": (
                "Which item is lowest by its artist?\nChoices:\n"
                "(A) Widget\n(B) Spring"
            )},
        ]
        with self.assertRaises(CompactionError) as context:
            compact_messages(messages, count_text, target=100,
                             field_pruning=True)
        self.assertEqual(context.exception.code, "complete_group_unresolved")

    def test_root_object_choice_arrays_keep_only_complete_matching_rows(self):
        source_object = {
            "metadata": {"source": "held-out fixture"},
            "event_log": [{"event_id": index, "detail": "noise"}
                          for index in range(12)],
            "competitors": [
                {"competitor_code": "vendor-1", "name": "Acme",
                 "history": [{"period": 1, "score": 7}, {"period": 2, "score": 4}]},
                {"competitor_code": "vendor-2", "name": "Beta",
                 "history": [{"period": 1, "score": 9}]},
                {"competitor_code": "vendor-3", "name": "Coda",
                 "history": [{"period": 1, "score": 2}]},
            ],
        }
        source = json.dumps(source_object, indent=2)
        messages = [
            {"role": "tool", "content": source},
            {"role": "user", "content": (
                "Which competitor code is the answer?\nChoices:\n"
                "(A) vendor-1\n(B) vendor-2\n(C) vendor-3"
            )},
        ]
        original = deepcopy(messages)
        expected_root = deepcopy(source_object)
        expected_root["event_log"] = []
        expected_root["competitors"] = source_object["competitors"]
        expected_source = json.dumps(expected_root, indent=2)
        target = count_text([
            {"role": "tool", "content": expected_source}, messages[-1],
        ])

        result = compact_messages(
            messages, count_text, target=target,
            complete_record_groups=True,
        )

        compacted = json.loads(result.messages[0]["content"])
        self.assertEqual(compacted["competitors"], source_object["competitors"])
        self.assertEqual(compacted["event_log"], [])
        self.assertEqual(compacted["metadata"], source_object["metadata"])
        self.assertTrue(result.audit["complete_groups"])
        self.assertEqual(result.audit["group_selection_scope"], "explicit_root_array_choices")
        self.assertLessEqual(result.audit["forwarded_tokens"], target)
        self.assertEqual(messages, original)

    def test_unrelated_partial_choice_array_is_skipped_for_later_source(self):
        unrelated = json.dumps({
            "history": [{"id": "vendor-1", "note": "old unrelated record"}],
            "noise": [{"id": "other", "note": "unrelated"}],
        })
        source = json.dumps({
            "meta": {"origin": "current source"},
            "options": [
                {"entity_id": "vendor-1", "observations": [1, 2]},
                {"entity_id": "vendor-2", "observations": [3, 4]},
                {"entity_id": "vendor-3", "observations": [5, 6]},
            ],
            "noise": [{"noise_id": f"n{index}", "value": index}
                      for index in range(10)],
        })
        messages = [
            {"role": "tool", "content": unrelated},
            {"role": "tool", "content": source},
            {"role": "user", "content": (
                "Which entity matches?\nChoices:\n"
                "(A) vendor-1\n(B) vendor-2\n(C) vendor-3"
            )},
        ]

        result = compact_messages(
            messages, count_text, target=700,
            complete_record_groups=True,
        )

        self.assertEqual(result.messages[0]["content"], unrelated)
        selected = json.loads(result.messages[1]["content"])
        self.assertEqual([item["entity_id"] for item in selected["options"]],
                         ["vendor-1", "vendor-2", "vendor-3"])
        self.assertEqual(selected["noise"], [])

    def test_csv_choices_expand_to_every_complete_row_for_group(self):
        source = (
            "<text>\nvendor,item,price\n"
            "Acme,Widget,10\nAcme,Gadget,12\n"
            "Beta,Spring,8\nBeta,Coil,9\nCoda,Valve,7\n</text>"
        )
        messages = [
            {"role": "tool", "content": source},
            {"role": "user", "content": (
                "Which item has the lowest price by its vendor?\nChoices:\n"
                "(A) Widget\n(B) Spring"
            )},
        ]
        expected = (
            "<text>\nvendor,item,price\nAcme,Widget,10\nAcme,Gadget,12\n"
            "Beta,Spring,8\nBeta,Coil,9\n</text>"
        )
        target = count_text([
            {"role": "tool", "content": expected}, messages[-1],
        ])

        result = compact_messages(
            messages, count_text, target=target,
            complete_record_groups=True,
        )

        self.assertEqual(result.messages[0]["content"], expected)
        self.assertEqual(result.audit["group_selection_scope"], "explicit_csv_group")
        self.assertTrue(result.audit["complete_groups"])
        self.assertLessEqual(result.audit["forwarded_tokens"], target)

    def test_default_behavior_is_unchanged_on_root_array_choice_case(self):
        messages = [
            {"role": "tool", "content": json.dumps({
                "meta": {"run": "held-out"},
                "scores": [
                    {"player_id": "player_1", "values": [1, 2, 3],
                     "detail": "historic score evidence " * 30},
                    {"player_id": "player_2", "values": [3, 2, 1],
                     "detail": "historic score evidence " * 30},
                    {"player_id": "player_3", "values": [5, 5, 5],
                     "detail": "historic score evidence " * 30},
                ],
                "rounds": [{"round_id": index, "note": "extra" * 8}
                           for index in range(10)],
            }, indent=2)},
            {"role": "user", "content": (
                "Which player has the most points?\nChoices:\n"
                "(A) player_1\n(B) player_2\n(C) player_3"
            )},
        ]
        default = compact_messages(messages, count_text, target=1_200)
        disabled = compact_messages(
            messages, count_text, target=1_200,
            complete_record_groups=False,
        )

        self.assertEqual(default, disabled)
        with self.assertRaises(CompactionError) as context:
            compact_messages(messages, count_text, target=1_200,
                             complete_record_groups=True)
        self.assertEqual(context.exception.code, "complete_group_too_large")

    def test_nested_message_list_arrays_remain_explicitly_unsupported(self):
        messages = [
            {"role": "tool", "content": json.dumps([
                [{"role": "user", "content": "Question with choices"},
                 {"role": "assistant", "content": "A"}],
                [{"role": "user", "content": "Another question"},
                 {"role": "assistant", "content": "B"}],
            ])},
            {"role": "user", "content": (
                "What is the answer?\nChoices:\n(A) first\n(B) second"
            )},
        ]

        with self.assertRaises(CompactionError) as context:
            compact_messages(
                messages, count_text, target=30,
                complete_record_groups=True,
            )

        self.assertEqual(context.exception.code, "research_relation_unsupported")

    def test_aggregate_table_is_kept_as_one_complete_group(self):
        records = [
            {"team_id": "TEAM-1", "period": "round-1", "points": 17},
            {"team_id": "TEAM-2", "period": "round-1", "points": 14},
            {"team_id": "TEAM-1", "period": "round-2", "points": 8},
            {"team_id": "TEAM-2", "period": "round-2", "points": 11},
        ]
        source = json.dumps(records, indent=2)
        messages = [
            {"role": "tool", "content": source},
            {"role": "user", "content": (
                "Which team had the highest total points across all rounds?"
            )},
        ]
        original = deepcopy(messages)
        prefix, suffix, exact_records = core._research_json_array(source)
        compact_array = prefix + "[\n" + ",\n".join(
            exact_text for exact_text, _ in exact_records
        ) + "\n]" + suffix
        expected = [
            {"role": "tool", "content": compact_array},
            messages[-1],
        ]
        target = count_text(expected)

        result = compact_messages(
            messages, count_text, target=target,
            complete_record_groups=True,
        )

        self.assertLessEqual(result.audit["forwarded_tokens"], target)
        self.assertEqual(json.loads(result.messages[0]["content"]), records)
        self.assertEqual(result.audit["group_selection_scope"], "aggregate_arrays")
        self.assertEqual(result.audit["requested_complete_groups"], 1)
        self.assertEqual(result.audit["selected_complete_groups"], 1)
        self.assertTrue(result.audit["complete_groups"])
        self.assertEqual(messages, original)

    def test_named_linked_entities_keep_whole_requested_groups(self):
        entities = {
            "Q101": {
                "name": "Newark",
                "population": 311549,
                "area": 67.1,
                "source_id": "CENSUS-2020",
            },
            "Q102": {
                "name": "Trenton",
                "population": 90871,
                "area": 21.2,
                "source_id": "CENSUS-2020",
            },
            "Q103": {
                "name": "Camden",
                "population": 71791,
                "area": 26.9,
            },
        }
        source = json.dumps({"entities": entities}, indent=2)
        messages = [
            {"role": "tool", "content": source},
            {"role": "user", "content": (
                "Compare Newark and Trenton by population and area."
            )},
        ]
        original = deepcopy(messages)
        parsed = core._research_entity_map(source)
        self.assertIsNotNone(parsed)
        prefix, suffix, entries = parsed
        compacted_map = prefix + "{\n" + ",\n".join(
            entry for entry, _, identifier in entries if identifier in {"Q101", "Q102"}
        ) + "\n}" + suffix
        target = count_text([
            {"role": "tool", "content": compacted_map}, messages[-1],
        ])

        result = compact_messages(
            messages, count_text, target=target,
            complete_record_groups=True,
        )

        compact_entities = core._research_entity_map(result.messages[0]["content"])[2]
        self.assertEqual({identifier for _, _, identifier in compact_entities}, {"Q101", "Q102"})
        self.assertEqual(result.audit["group_selection_scope"], "linked_or_named_records")
        self.assertEqual(result.audit["requested_complete_groups"], 1)
        self.assertEqual(result.audit["selected_complete_groups"], 1)
        self.assertTrue(result.audit["complete_groups"])
        self.assertLessEqual(result.audit["forwarded_tokens"], target)
        self.assertEqual(messages, original)

    def test_aggregate_array_fails_closed_when_complete_table_does_not_fit(self):
        records = [
            {"player_id": f"PLAYER-{index}", "round": index,
             "points": index, "note": "historical score detail " * 8}
            for index in range(1, 13)
        ]
        messages = [
            {"role": "tool", "content": json.dumps(records, indent=2)},
            {"role": "user", "content": "What was the total points across all rounds?"},
        ]

        with self.assertRaises(CompactionError) as context:
            compact_messages(
                messages, count_text, target=500,
                complete_record_groups=True,
            )

        self.assertEqual(context.exception.code, "complete_group_too_large")

    def test_default_behavior_is_unchanged_on_repeated_aggregation_history(self):
        records = [
            {"player_id": f"PLAYER-{index:02d}", "round": index,
             "score": (index * 7) % 19, "note": "round result"}
            for index in range(1, 25)
        ]
        messages = [
            {"role": "tool", "content": json.dumps(records, indent=2)},
            {"role": "user", "content": (
                "Which player had the highest total score across all rounds?"
            )},
        ]
        original = deepcopy(messages)
        default = compact_messages(messages, count_text, target=1_500)
        explicitly_disabled = compact_messages(
            messages, count_text, target=1_500,
            complete_record_groups=False,
        )

        self.assertEqual(default, explicitly_disabled)
        self.assertEqual(messages, original)
        self.assertLessEqual(default.audit["forwarded_tokens"], 1_500)

        with self.assertRaises(CompactionError) as context:
            compact_messages(
                messages, count_text, target=1_500,
                complete_record_groups=True,
            )
        self.assertEqual(context.exception.code, "complete_group_too_large")


if __name__ == "__main__":
    unittest.main()
