from __future__ import annotations

import json

import pytest

from benchmarks.relation_matrix_candidate import MatrixError, matrix_messages, render_matrix


def _context() -> dict:
    return {
        "metadata": {"source": "fixture"},
        "entities": {
            "Q10": {
                "name": "Club A",
                "relations": [{"object": "Q20", "direction": "backward",
                               "qualifiers": {"season": [2020]},
                               "relation": "member of sports team"}],
            },
            "Q20": {
                "name": "Ada Example",
                "attributes": [{"key": "height", "value": {"value": 181},
                                "qualifiers": {"unit": "cm"}}],
                "relations": [{"object": "Q10", "direction": "forward",
                               "qualifiers": {"season": [2020]},
                               "relation": "member of sports team"}],
            },
            "Q30": {"name": "Comparator", "other": [1, {"x": True}]},
        },
    }


def test_render_matrix_roundtrips_every_selected_field_and_compound_choice() -> None:
    context = _context()
    choices = {"A": "Q20", "B": "Q30", "C": "Q20 and Q30", "D": "Q10"}

    serialized, audit = render_matrix(context, choices)

    records = [json.loads(line) for line in serialized.splitlines()]
    assert records[0][0] == "schema"
    assert [row[1:3] for row in records if row[0] == "option_entity"] == [
        [["A", "C"], "Q20"], [["B", "C"], "Q30"], [["D"], "Q10"],
    ]
    assert audit["all_selected_entities_preserved"] is True
    assert audit["all_entity_fields_preserved"] is True
    assert audit["option_entities"]["C"] == ["Q20", "Q30"]
    assert audit["source_context_sha256"] == audit["reconstructed_context_sha256"]
    assert any(
        "qualifiers" in relation
        for row in records if row[0] == "option_entity"
        for relation in row[-1].get("relations", [])
    )


def test_matrix_messages_changes_only_the_historical_wrapped_context() -> None:
    messages = [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "<text>\n" + json.dumps(_context()) + "\n</text>"},
        {"role": "assistant", "content": "Ready."},
        {"role": "user", "content": "Question and choices unchanged"},
    ]

    result, audit = matrix_messages(
        messages, {"A": "Q20", "B": "Q30", "C": "Q20 and Q30", "D": "Q10"}
    )

    assert result[0] == messages[0]
    assert result[2:] == messages[2:]
    assert result[1]["content"].startswith("<text>\n")
    assert result[1]["content"].endswith("\n</text>")
    assert audit["other_messages_unchanged"] is True
    assert audit["all_selected_entities_preserved"] is True


def test_missing_option_record_fails_closed() -> None:
    with pytest.raises(MatrixError, match=r"record\(s\) missing"):
        render_matrix(
            _context(), {"A": "Q20", "B": "Q30", "C": "Q20 and Q99", "D": "Q10"}
        )


def test_choice_without_explicit_entity_id_fails_closed() -> None:
    with pytest.raises(MatrixError, match="no explicit entity ID"):
        render_matrix(_context(), {"A": "unknown", "B": "Q30", "C": "Q20", "D": "Q10"})
