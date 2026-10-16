"""Whole-unit recency control for the isolated native-agent benchmark.

This deliberately uses Sift 0.9.1's private rendering and turn boundaries.
It shares validation/counting with the tested selector, but performs no ranking,
identifier joins, diagnostic retention, or generated/extracted summaries.
The budget is a ceiling. Whole units can leave unused capacity; never pad them.
"""

from copy import deepcopy
from typing import Any

from sift.core import (
    DEFAULT_MAX_INPUT_CHARACTERS, DEFAULT_MAX_INPUT_NODES,
    CompactionError, CompactionResult, Protocol, TokenCounter,
    _check_precount_size, _count, _real_user, _render, _starts_tool_cycle,
)


def compact_messages(
    messages: list[dict[str, Any]], count_tokens: TokenCounter, *,
    target: int = 24_576, raw_limit: int = 1_000_000,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    max_input_nodes: int = DEFAULT_MAX_INPUT_NODES,
    protocol: Protocol = "openai",
) -> CompactionResult:
    """Keep the newest fitting suffix of complete turns or active tool cycles.

    Leading instructions and the latest real user request are immutable. If
    its whole turn does not fit, the latest complete tool cycle is essential.
    Earlier human turns are only eligible as whole turns, so their tool results
    cannot survive independently. Responses inspection views already group
    pending parallel calls through Sift's installed Responses adapter.
    """
    if type(target) is not int or type(raw_limit) is not int or target <= 0 or raw_limit < target:
        raise CompactionError("invalid target or raw_limit")
    if not isinstance(messages, list) or not all(isinstance(message, dict) for message in messages):
        raise CompactionError("messages must be a list of objects")
    _check_precount_size(messages, max_characters=max_input_characters,
                         max_nodes=max_input_nodes)
    raw = _count(count_tokens, messages)
    if raw > raw_limit:
        raise CompactionError("request exceeds raw_limit", code="raw_limit")

    def result(selected, forwarded, *, turns=0, cycles=0):
        return CompactionResult(deepcopy(selected), {
            "compacted": raw > target, "input_tokens": raw,
            "forwarded_tokens": forwarded,
            "omitted_estimated_tokens": max(0, raw - forwarded),
            "preserved_recent_turns": turns,
            "preserved_recent_tool_cycles": cycles,
            "selected_excerpts": 0, "method": "whole_unit_recency",
        })

    if raw <= target:
        return result(messages, raw)
    if protocol not in {"openai", "anthropic"}:
        raise CompactionError("unsupported protocol", code="unsupported_protocol")
    for message in messages:
        _render(message)
    instruction_end = 0
    while instruction_end < len(messages) and messages[instruction_end].get("role") in {"system", "developer"}:
        instruction_end += 1
    if any(message.get("role") in {"system", "developer"} for message in messages[instruction_end:]):
        raise CompactionError("late instruction cannot be compacted", code="late_instruction")
    users = [index for index in range(instruction_end, len(messages))
             if _real_user(messages[index], protocol)]
    if not users:
        raise CompactionError("no active user turn", code="active_too_large")
    latest_user = users[-1]
    cycles = [index for index in range(latest_user + 1, len(messages))
              if _starts_tool_cycle(messages[index], protocol)]
    # A start before the active user retains complete human turns. A start
    # after it retains complete active tool cycles, with the original task pinned.
    starts = users + cycles
    prefix = messages[:instruction_end]

    def build(start):
        return prefix + ([] if start <= latest_user else [messages[latest_user]]) + messages[start:]

    essential = build(starts[-1])
    essential_count = _count(count_tokens, essential)
    if essential_count > target:
        raise CompactionError("active task or latest tool cycle exceeds target", code="active_too_large")
    # As with the core selector, fitting is checked using the caller's counter.
    # Search whole-unit boundaries rather than repeatedly tokenizing every unit.
    low, high = 0, len(starts) - 1
    selected_start, selected, forwarded = starts[-1], essential, essential_count
    while low <= high:
        middle = (low + high) // 2
        candidate = build(starts[middle])
        count = _count(count_tokens, candidate)
        if count <= target:
            selected_start, selected, forwarded = starts[middle], candidate, count
            high = middle - 1
        else:
            low = middle + 1
    return result(
        selected, forwarded,
        turns=sum(selected_start <= index < latest_user for index in users),
        cycles=sum(index >= selected_start for index in cycles),
    )
