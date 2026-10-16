"""Research-only whole-record selector for the relation-binding pilot.

This candidate changes the selection unit from Sift's bounded excerpts to
complete JSON objects. It is not a runtime or LiteLLM integration path.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
from typing import Any, Callable

from sift import core


TokenCounter = Callable[[list[dict[str, Any]]], int]


class CandidateError(ValueError):
    """The frozen candidate cannot safely represent this fixture."""


@dataclass(frozen=True)
class _Record:
    index: int
    start: int
    end: int
    text: str


def _array_records(text: str) -> tuple[str, str, str, list[_Record]]:
    """Return prefix, suffix, array delimiters, and original top-level objects."""
    decoder = json.JSONDecoder()
    start = text.find("[")
    if start < 0:
        raise CandidateError("historical tool content must contain a JSON array")
    try:
        decoded, array_end = decoder.raw_decode(text, start)
    except (json.JSONDecodeError, RecursionError) as error:
        raise CandidateError("historical tool content has invalid JSON") from error
    if not isinstance(decoded, list) or not all(isinstance(item, dict) for item in decoded):
        raise CandidateError("historical JSON array must contain only record objects")

    records: list[_Record] = []
    cursor = start + 1
    for index, expected in enumerate(decoded):
        while cursor < array_end and (text[cursor].isspace() or text[cursor] == ","):
            cursor += 1
        if cursor >= array_end or text[cursor] != "{":
            raise CandidateError("record boundaries do not match the JSON array")
        record_start = cursor
        try:
            parsed, cursor = decoder.raw_decode(text, cursor)
        except (json.JSONDecodeError, RecursionError) as error:
            raise CandidateError("record boundaries do not match the JSON array") from error
        if parsed != expected or not isinstance(parsed, dict):
            raise CandidateError("record order or contents changed while parsing")
        records.append(_Record(index, record_start, cursor, text[record_start:cursor]))
    while cursor < array_end and (text[cursor].isspace() or text[cursor] == ","):
        cursor += 1
    if cursor != array_end - 1 or text[cursor] != "]":
        raise CandidateError("unexpected content after final JSON record")
    return text[:start], text[array_end:], text[start:array_end], records


def _rank_records(records: list[_Record], messages: list[dict[str, Any]],
                  query: str) -> list[_Record]:
    """Apply Sift's query, rarity, signal, recency, bridge and tie-break rules.

    Only the indivisible candidate boundary differs: each parsed record gets a
    single score instead of scoring its bounded excerpts independently.
    """
    terms = core._query_terms(query)
    frequencies, total = core._term_frequencies(messages, terms)
    base_scores: dict[int, float] = {}
    for record in records:
        matching = terms.intersection(
            term.lower() for term in core._TERMS.findall(record.text)
        )
        score = sum(
            100 * math.log1p(total / (1 + frequencies[term]))
            for term in matching
        )
        if core._SIGNALS.search(record.text):
            score += 8
        score += 2 * (record.index + 1) / max(1, len(records))
        if record.index == 0:
            score += 3
        base_scores[record.index] = score

    primary = sorted(records, key=lambda item: (-base_scores[item.index], item.index))
    query_ids = {value.casefold() for value in core._LINK_IDS.findall(query)}
    bridge_ids: list[str] = []
    seen: set[str] = set()
    for record in primary[:8]:
        for value in core._LINK_IDS.findall(record.text):
            key = value.casefold()
            if key not in query_ids and key not in seen:
                bridge_ids.append(value)
                seen.add(key)
                if len(bridge_ids) == 4:
                    break
        if len(bridge_ids) == 4:
            break

    ranked: list[_Record] = []
    ranked_indexes: set[int] = set()

    def add(record: _Record) -> None:
        if record.index not in ranked_indexes:
            ranked_indexes.add(record.index)
            ranked.append(record)

    for record in primary[:2]:
        add(record)
    if bridge_ids:
        bridge_pattern = re.compile(
            r"\b(?:" + "|".join(map(re.escape, bridge_ids)) + r")\b",
            re.IGNORECASE,
        )
        linked = sorted(
            records,
            key=lambda item: (
                -(base_scores[item.index] + (120 if bridge_pattern.search(item.text) else 0)),
                item.index,
            ),
        )
        for record in linked:
            if bridge_pattern.search(record.text):
                add(record)
                if len(ranked) == 5:
                    break
    for record in primary:
        add(record)
    return ranked


def compact_messages(messages: list[dict[str, Any]], count_tokens: TokenCounter,
                     *, target: int = 24_576) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select whole tool-result JSON records under the caller's exact budget."""
    if type(target) is not int or target <= 0:
        raise CandidateError("target must be a positive integer")
    if not isinstance(messages, list) or not messages or not all(
        isinstance(message, dict) for message in messages
    ):
        raise CandidateError("messages must be a nonempty list of objects")
    raw_count = core._count(count_tokens, messages)
    if raw_count <= target:
        return deepcopy(messages), {
            "compacted": False,
            "input_tokens": raw_count,
            "forwarded_tokens": raw_count,
            "selected_records": 0,
        }

    latest_user = next((index for index in range(len(messages) - 1, -1, -1)
                        if core._real_user(messages[index], "openai")), -1)
    instruction_end = 0
    while instruction_end < len(messages) and messages[instruction_end].get("role") in {
        "system", "developer"
    }:
        instruction_end += 1
    if latest_user <= instruction_end:
        raise CandidateError("a current user question must follow historical content")

    tool_indexes = [index for index in range(instruction_end, latest_user)
                    if messages[index].get("role") == "tool"]
    if len(tool_indexes) != 1:
        raise CandidateError("pilot input must contain exactly one historical tool message")
    tool_index = tool_indexes[0]
    source = messages[tool_index].get("content")
    if not isinstance(source, str):
        raise CandidateError("historical tool content must be plain text")
    prefix, suffix, _, records = _array_records(source)
    if not records:
        raise CandidateError("historical tool JSON array has no records")

    query = core._render(messages[latest_user])
    old_history = messages[instruction_end:latest_user]
    ranked = _rank_records(records, old_history, query)

    protected = deepcopy(messages)
    protected[tool_index]["content"] = prefix + "[]" + suffix
    protected_count = core._count(count_tokens, protected)
    if protected_count > target:
        raise CandidateError("protected messages exceed the candidate target")

    selected: list[_Record] = []
    result = deepcopy(protected)
    for record in ranked:
        trial = sorted(selected + [record], key=lambda item: item.index)
        array_text = "[\n" + ",\n".join(item.text for item in trial) + "\n]"
        candidate = deepcopy(protected)
        candidate[tool_index]["content"] = prefix + array_text + suffix
        if core._count(count_tokens, candidate) <= target:
            selected = trial
            result = candidate

    forwarded = core._count(count_tokens, result)
    if forwarded > target:
        raise CandidateError("candidate exceeded the exact caller token budget")
    for index, (before, after) in enumerate(zip(messages, result)):
        if index != tool_index and before != after:
            raise CandidateError("candidate changed a protected message")
    return result, {
        "compacted": True,
        "input_tokens": raw_count,
        "forwarded_tokens": forwarded,
        "selected_records": len(selected),
        "total_records": len(records),
    }
