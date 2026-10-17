"""Lossless option-aligned rendering for the LongBench v2 relation screen.

Research-only benchmark helper. It reorders already-selected complete entity
records by answer option and adds source paths; it does not discard fields or
change the question, choices, or any other message.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any


_OPTION_IDS = re.compile(r"Q\d+")
_OPEN = "<text>\n"
_CLOSE = "\n</text>"
_SCHEMA = ["schema", ["kind", "options", "entity_id", "source_path", "record"]]


class MatrixError(ValueError):
    """The selected context cannot be represented without loss or ambiguity."""


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unwrap_context(content: str) -> tuple[str, str, dict[str, Any]]:
    if not content.startswith(_OPEN):
        raise MatrixError("selected context is missing the <text> wrapper")
    end = content.rfind(_CLOSE)
    if end < len(_OPEN) or content[end + len(_CLOSE):].strip():
        raise MatrixError("selected context has a malformed <text> wrapper")
    try:
        value = json.loads(content[len(_OPEN):end])
    except (json.JSONDecodeError, RecursionError) as error:
        raise MatrixError("selected context is not valid JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("entities"), dict):
        raise MatrixError("selected context must contain an entities object")
    if not all(isinstance(entity, dict) for entity in value["entities"].values()):
        raise MatrixError("every selected entity must be an object")
    return content[:len(_OPEN)], content[end:], value


def _choice_entities(choices: dict[str, str], entity_ids: set[str]) -> dict[str, list[str]]:
    if set(choices) != {"A", "B", "C", "D"}:
        raise MatrixError("choices must contain exactly A, B, C, and D")
    result: dict[str, list[str]] = {}
    for letter in "ABCD":
        value = choices[letter]
        if not isinstance(value, str) or not value.strip():
            raise MatrixError(f"choice {letter} must be nonempty text")
        ids = list(dict.fromkeys(_OPTION_IDS.findall(value)))
        if not ids:
            raise MatrixError(f"choice {letter} contains no explicit entity ID")
        missing = [entity_id for entity_id in ids if entity_id not in entity_ids]
        if missing:
            raise MatrixError(f"choice {letter} entity record(s) missing: {missing}")
        result[letter] = ids
    return result


def render_matrix(context: dict[str, Any], choices: dict[str, str]) -> tuple[str, dict[str, Any]]:
    """Render all selected entities in option-first order and prove round-trip."""
    if not isinstance(context, dict) or not isinstance(context.get("entities"), dict):
        raise MatrixError("context must contain an entities object")
    entities = context["entities"]
    option_ids = _choice_entities(choices, set(entities))
    lines = [json.dumps(_SCHEMA, ensure_ascii=False, separators=(",", ":"))]
    root_fields = {key: value for key, value in context.items() if key != "entities"}
    lines.append(json.dumps(
        ["root", "$", None, None, root_fields],
        ensure_ascii=False, separators=(",", ":"),
    ))

    entity_options: dict[str, list[str]] = {}
    for letter in "ABCD":
        for entity_id in option_ids[letter]:
            entity_options.setdefault(entity_id, []).append(letter)

    for entity_id, letters in entity_options.items():
        lines.append(json.dumps(
            ["option_entity", letters, entity_id,
             f"$.entities[{json.dumps(entity_id, ensure_ascii=False)}]", entities[entity_id]],
            ensure_ascii=False, separators=(",", ":"),
        ))

    supporting_ids = [entity_id for entity_id in entities if entity_id not in entity_options]
    for entity_id in supporting_ids:
        lines.append(json.dumps(
            ["supporting_entity", None, entity_id,
             f"$.entities[{json.dumps(entity_id, ensure_ascii=False)}]", entities[entity_id]],
            ensure_ascii=False, separators=(",", ":"),
        ))

    serialized = "\n".join(lines) + "\n"
    rebuilt_root: dict[str, Any] = {}
    rebuilt_entities: dict[str, dict[str, Any]] = {}
    for line in lines[1:]:
        kind, _path, entity_id, _source_path, value = json.loads(line)
        if kind == "root":
            if rebuilt_root:
                raise MatrixError("duplicate root record")
            rebuilt_root = value
        elif kind in {"option_entity", "supporting_entity"}:
            if entity_id in rebuilt_entities and rebuilt_entities[entity_id] != value:
                raise MatrixError(f"conflicting duplicate entity record: {entity_id}")
            rebuilt_entities[entity_id] = value
        else:
            raise MatrixError(f"unexpected matrix record type: {kind}")
    rebuilt = {**rebuilt_root, "entities": rebuilt_entities}
    if rebuilt != context or set(rebuilt_entities) != set(entities):
        raise MatrixError("matrix failed exact selected-context reconstruction")
    if _canonical_hash(rebuilt) != _canonical_hash(context):
        raise MatrixError("matrix round-trip hash mismatch")

    audit = {
        "method": "option_aligned_complete_entity_matrix_v3",
        "selected_entity_count": len(entities),
        "option_entity_rows": len(entity_options),
        "distinct_option_entity_count": len(entity_options),
        "supporting_entity_count": len(supporting_ids),
        "option_entities": option_ids,
        "all_selected_entities_preserved": True,
        "all_entity_fields_preserved": True,
        "source_context_sha256": _canonical_hash(context),
        "reconstructed_context_sha256": _canonical_hash(rebuilt),
        "matrix_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "predicate_fields_filtered": False,
    }
    return serialized, audit


def matrix_messages(
    messages: list[dict[str, Any]], choices: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replace exactly one historical wrapped context, preserving other turns."""
    if not isinstance(messages, list) or len(messages) < 2:
        raise MatrixError("messages must include context and question turns")
    matches = [
        index for index, message in enumerate(messages[:-1])
        if isinstance(message, dict)
        and isinstance(message.get("content"), str)
        and message["content"].startswith(_OPEN)
        and _CLOSE in message["content"]
    ]
    if len(matches) != 1:
        raise MatrixError(f"expected exactly one historical wrapped context, found {len(matches)}")
    index = matches[0]
    prefix, suffix, context = _unwrap_context(messages[index]["content"])
    serialized, audit = render_matrix(context, choices)
    result = deepcopy(messages)
    result[index]["content"] = prefix + serialized.rstrip("\n") + suffix
    if any(result[other] != messages[other] for other in range(len(messages)) if other != index):
        raise MatrixError("matrix changed a non-context message")
    audit.update({
        "context_message_index": index,
        "other_messages_unchanged": True,
        "original_message_sha256": _canonical_hash(messages[index]),
        "matrix_message_sha256": _canonical_hash(result[index]),
    })
    return result, audit
