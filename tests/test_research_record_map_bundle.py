from __future__ import annotations

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sift.core import _research_record_map_bundle


def test_bundle_retains_exact_entity_concept_and_label_source_slices() -> None:
    source = (
        'prefix { "metadata" : { "source" : "fixture", "n": [1, 2] }, '
        '"entities" : { "Q1" : { "name" : "Ada", "relations" : [ {"object":"Q2"} ] }, '
        '"Q2": {"name":"Bob"} }, '
        '"concepts" : { "C1" : { "name" : "person", "subclassOf" : ["C0"] } }, '
        '"labels" : { "Q1" : "Ada (label)", "Q2" : "Bob" } } suffix'
    )

    bundle = _research_record_map_bundle(source)

    assert bundle is not None
    prefix, suffix, template, maps = bundle
    assert prefix == "prefix "
    assert suffix == " suffix"
    assert [name for name, _, _ in maps] == ["entities", "concepts", "labels"]

    expected_entries = {
        "entities": [
            ('"Q1" : { "name" : "Ada", "relations" : [ {"object":"Q2"} ] }', "Q1"),
            ('"Q2": {"name":"Bob"}', "Q2"),
        ],
        "concepts": [
            ('"C1" : { "name" : "person", "subclassOf" : ["C0"] }', "C1"),
        ],
        "labels": [
            ('"Q1" : "Ada (label)"', "Q1"),
            ('"Q2" : "Bob"', "Q2"),
        ],
    }
    for name, marker, entries in maps:
        assert [raw for raw, _, _ in entries] == [raw for raw, _ in expected_entries[name]]
        assert [record_id for _, _, record_id in entries] == [
            record_id for _, record_id in expected_entries[name]
        ]
        assert all(isinstance(value, (dict, str)) for _, value, _ in entries)
        assert marker in template

    # Root members outside the recognized maps retain their source spelling,
    # whitespace, and punctuation in the template.
    assert template.startswith('{ "metadata" : { "source" : "fixture", "n": [1, 2] }, ')
    assert template.endswith(" }")
    assert template.count("__SIFT_RECORD_MAP_") == 3


@pytest.mark.parametrize(
    "source",
    [
        '{"entities": []}',
        '{"concepts": {"C1": null}}',
        '{"labels": ["not", "a", "map"]}',
        '{"entities": {"Q1": []}}',
    ],
)
def test_malformed_or_unsupported_recognized_maps_fail_closed(source: str) -> None:
    with pytest.raises(ValueError):
        _research_record_map_bundle(source)


@pytest.mark.parametrize(
    "source",
    [
        '{"entities": {"Q1": {"name": "first"}}, "entities": {"Q2": {"name": "second"}}}',
        '{"metadata": 1, "labels": {"Q1": "first"}, "labels": {"Q2": "second"}}',
    ],
)
def test_duplicate_or_ambiguous_root_keys_fail_closed(source: str) -> None:
    with pytest.raises(ValueError):
        _research_record_map_bundle(source)


def test_non_object_root_and_unrecognized_object_return_none() -> None:
    assert _research_record_map_bundle("[]") is None
    assert _research_record_map_bundle('{"metadata": {"source": "fixture"}}') is None
