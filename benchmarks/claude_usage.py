"""Extract body-free per-response usage from Claude Code stream-json events."""

from __future__ import annotations

from typing import Any, Iterable


_USAGE_FIELDS = (
    "input_tokens", "cache_creation_input_tokens",
    "cache_read_input_tokens", "output_tokens",
)


def _usage_values(value: Any) -> dict[str, int | None]:
    if not isinstance(value, dict):
        return {name: None for name in _USAGE_FIELDS}
    return {
        name: value.get(name) if type(value.get(name)) is int and value[name] >= 0 else None
        for name in _USAGE_FIELDS
    }


def _merge_usage(current: dict[str, int | None], value: Any) -> None:
    if not isinstance(value, dict):
        return
    for name in _USAGE_FIELDS:
        if name not in value:
            continue
        candidate = value[name]
        current[name] = candidate if type(candidate) is int and candidate >= 0 else None


def stream_request_usage(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one sanitized usage record per completed Claude API stream.

    Claude's final `result.usage` aggregates the whole client session. These
    records preserve the individual message response usage, including cache
    fields, while excluding prompt text and generated content.
    """
    records: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for event in events:
        if event.get("type") != "stream_event":
            continue
        detail = event.get("event")
        if not isinstance(detail, dict):
            continue
        kind = detail.get("type")
        if kind == "message_start":
            message = detail.get("message")
            if not isinstance(message, dict):
                active = None
                continue
            active = {
                "message_id": message.get("id") if isinstance(message.get("id"), str) else None,
                "model": message.get("model") if isinstance(message.get("model"), str) else None,
                "usage": _usage_values(message.get("usage")),
                "started_at": event.get("timestamp") if isinstance(event.get("timestamp"), str) else None,
            }
        elif kind == "message_delta" and active is not None:
            _merge_usage(active["usage"], detail.get("usage"))
        elif kind == "message_stop" and active is not None:
            usage = active["usage"]
            fields = {name: usage[name] for name in _USAGE_FIELDS}
            observed_input_fields = [
                usage[name] for name in _USAGE_FIELDS[:3] if type(usage[name]) is int
            ]
            records.append({
                "stream_index": len(records) + 1,
                "message_id": active["message_id"],
                "model": active["model"],
                **fields,
                "provider_reported_input_total": sum(observed_input_fields)
                if len(observed_input_fields) == 3 else None,
                "input_total_method": "input+cache_creation+cache_read" if len(observed_input_fields) == 3 else None,
                "started_at": active["started_at"],
                "finished_at": event.get("timestamp") if isinstance(event.get("timestamp"), str) else None,
            })
            active = None
    return records
