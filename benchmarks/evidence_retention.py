"""Private, extractive evidence-retention checks for native-agent evals.

Gold spans are loaded from an opt-in manifest. Reports contain opaque IDs and
retention states only; neither source text nor prompt bodies are logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from collections.abc import Iterable
from typing import Any, Iterator


_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAX_SPANS = 64
_MAX_SPAN_CHARS = 2_048


@dataclass(frozen=True)
class RequiredSpan:
    span_id: str
    text: str


@dataclass(frozen=True)
class SelectionEvent:
    request_seq: int
    observed_utc_ns: int
    selector: str
    input_tokens: int | None
    forwarded_tokens: int | None
    states: dict[str, str]

    @property
    def compacted(self) -> bool:
        return (self.input_tokens is not None and self.forwarded_tokens is not None
                and self.forwarded_tokens < self.input_tokens)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def load_required_spans(manifest_path: str | Path) -> tuple[RequiredSpan, ...]:
    """Load validated character spans from agent_gold/<fixture>/evidence.json.

    Paths are confined to the matching agent_cases/<fixture> directory under
    the benchmark root. Hashes bind the annotation to exact source characters.
    """
    path = Path(manifest_path).resolve(strict=True)
    if path.name != "evidence.json" or path.parent.parent.name != "agent_gold":
        raise ValueError("evidence manifest must be agent_gold/<fixture>/evidence.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported evidence manifest schema")
    fixture = data.get("fixture")
    if not isinstance(fixture, str) or not _ID.fullmatch(fixture.replace("-", "_")):
        raise ValueError("invalid evidence fixture name")
    if path.parent.name != fixture:
        raise ValueError("evidence fixture does not match manifest directory")
    spans = data.get("required_spans")
    if not isinstance(spans, list) or not spans or len(spans) > _MAX_SPANS:
        raise ValueError("evidence manifest must contain 1 to 64 required spans")

    benchmark_root = path.parent.parent.parent.resolve(strict=True)
    source_root = (benchmark_root / "agent_cases" / fixture).resolve(strict=True)
    if not _within(source_root, benchmark_root):
        raise ValueError("evidence source root escapes benchmark directory")

    result: list[RequiredSpan] = []
    seen: set[str] = set()
    for item in spans:
        if not isinstance(item, dict):
            raise ValueError("invalid required evidence span")
        span_id, source, digest = item.get("id"), item.get("source"), item.get("sha256")
        if not isinstance(span_id, str) or not _ID.fullmatch(span_id) or span_id in seen:
            raise ValueError("invalid or duplicate evidence span ID")
        if not isinstance(source, dict):
            raise ValueError(f"{span_id}: source coordinates are required")
        relative = source.get("file")
        start, end = source.get("start_char"), source.get("end_char")
        if (not isinstance(relative, str) or Path(relative).is_absolute()
                or ".." in Path(relative).parts
                or type(start) is not int or type(end) is not int or start < 0 or end <= start):
            raise ValueError(f"{span_id}: invalid source coordinates")
        source_path = (source_root / relative).resolve(strict=True)
        if not _within(source_path, source_root) or not source_path.is_file():
            raise ValueError(f"{span_id}: source path escapes fixture")
        text = source_path.read_text(encoding="utf-8")
        if end > len(text):
            raise ValueError(f"{span_id}: source span is out of bounds")
        value = text[start:end]
        if not value.strip() or len(value) > _MAX_SPAN_CHARS:
            raise ValueError(f"{span_id}: source span must contain 1 to 2048 characters")
        actual = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or actual != digest:
            raise ValueError(f"{span_id}: source span hash mismatch")
        seen.add(span_id)
        result.append(RequiredSpan(span_id, value))
    return tuple(result)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _contains(messages: list[dict[str, Any]], text: str) -> bool:
    # Sift places excerpts inside JSON-quoted text. Check both the direct source
    # form and the escaped form actually emitted by that wrapper.
    escaped = json.dumps(text, ensure_ascii=False)[1:-1]
    return any(text in item or escaped in item for item in _strings(messages))


def audit_retention(
    messages: list[dict[str, Any]],
    forwarded: list[dict[str, Any]],
    spans: tuple[RequiredSpan, ...],
) -> dict[str, str]:
    """Report exact-span presence without returning or logging span text."""
    result: dict[str, str] = {}
    for span in spans:
        in_input = _contains(messages, span.text)
        in_forwarded = _contains(forwarded, span.text)
        if in_forwarded and not in_input:
            state = "forwarded_only"
        elif not in_input:
            state = "not_in_input"
        elif in_forwarded:
            state = "retained"
        else:
            state = "omitted"
        result[span.span_id] = state
    return result


def parse_selection_events(gateway_log: str | Iterable[str]) -> list[SelectionEvent]:
    """Read body-free selector events emitted by the native benchmark hook."""
    events: list[SelectionEvent] = []
    lines = gateway_log.splitlines() if isinstance(gateway_log, str) else gateway_log
    for line in lines:
        marker = "sift_benchmark_selection "
        if marker not in line:
            continue
        fields = dict(re.findall(r"([a-z_]+)=([^\s]+)", line.split(marker, 1)[1]))
        try:
            sequence = int(fields["request_seq"])
            observed = int(fields["observed_utc_ns"])
        except (KeyError, ValueError):
            continue
        try:
            input_tokens = int(fields["input_tokens"])
            forwarded_tokens = int(fields["forwarded_tokens"])
        except (KeyError, ValueError):
            input_tokens = forwarded_tokens = None
        states = {}
        for pair in fields.get("evidence", "").split(","):
            if ":" in pair:
                span_id, state = pair.split(":", 1)
                if _ID.fullmatch(span_id) and state in {
                    "retained", "omitted", "not_in_input", "forwarded_only",
                }:
                    states[span_id] = state
        events.append(SelectionEvent(
            sequence, observed, fields.get("selector", "unknown"),
            input_tokens, forwarded_tokens, states,
        ))
    return events


def _relative_tool_path(value: str, workspace: str | Path) -> str | None:
    path = value.replace("\\", "/").casefold().rstrip("/")
    root = str(workspace).replace("\\", "/").casefold().rstrip("/")
    if path.startswith(root + "/"):
        relative = path[len(root) + 1:]
    elif path.startswith("/") or re.match(r"^[a-z]:/", path):
        return None
    else:
        relative = path
    parts = [part for part in relative.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def first_direct_edit_timestamp_ns(
    trace_path: str | Path,
    workspace: str | Path,
    editable_paths: set[str],
) -> int | None:
    """Find the first Claude direct file-edit tool call to an allowed path.

    Shell-mediated edits and other client trace formats deliberately return no
    match. They need a client-specific parser before the ordering can be known.
    """
    editable = {path.replace("\\", "/").casefold().strip("/") for path in editable_paths}
    earliest: int | None = None
    with Path(trace_path).open(encoding="utf-8") as trace:
        for line in trace:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = row.get("message")
            timestamp = row.get("timestamp")
            if row.get("type") != "assistant" or not isinstance(message, dict):
                continue
            if not isinstance(timestamp, str):
                continue
            blocks = message.get("content")
            if not isinstance(blocks, list):
                continue
            paths = []
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") not in {"Edit", "Write", "MultiEdit"}:
                    continue
                arguments = block.get("input")
                if isinstance(arguments, dict) and isinstance(arguments.get("file_path"), str):
                    relative = _relative_tool_path(arguments["file_path"], workspace)
                    if relative in editable:
                        paths.append(relative)
            if not paths:
                continue
            try:
                instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                continue
            if instant.tzinfo is None:
                continue
            instant = instant.astimezone(timezone.utc)
            delta = instant - datetime(1970, 1, 1, tzinfo=timezone.utc)
            value = (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000
            earliest = value if earliest is None else min(earliest, value)
    return earliest


def assess_pre_edit_retention(
    events: list[SelectionEvent],
    first_edit_utc_ns: int | None,
    required_span_ids: set[str],
    *,
    selector: str = "sift",
) -> dict[str, Any]:
    """Require one compacted request from the expected selector before edit."""
    if first_edit_utc_ns is None:
        return {"status": "unknown_edit_time", "request_seq": None, "states": {}}
    prior = [event for event in events if event.observed_utc_ns < first_edit_utc_ns]
    if not prior:
        status = "after_edit" if events else "unknown_no_selection_events"
        return {"status": status, "request_seq": None, "states": {}}
    matching = [event for event in prior if event.selector == selector and event.compacted]
    if not matching:
        return {"status": "no_compaction_before_edit", "request_seq": None, "states": {}}
    event = max(matching, key=lambda item: item.observed_utc_ns)
    states = {span_id: event.states.get(span_id, "unknown")
              for span_id in sorted(required_span_ids)}
    if any(state == "unknown" for state in states.values()):
        status = "unknown_span_audit"
    elif any(state != "retained" for state in states.values()):
        status = "required_span_not_retained"
    else:
        status = "verified_before_edit"
    return {
        "status": status,
        "request_seq": event.request_seq,
        "input_tokens": event.input_tokens,
        "forwarded_tokens": event.forwarded_tokens,
        "states": states,
    }
