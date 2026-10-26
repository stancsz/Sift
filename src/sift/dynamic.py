"""Pure dynamic compaction adapter.

Chooses a token target from the caller's context budget, then delegates to the
existing :func:`sift.core.compact_messages` compactor so every existing
guarantee (deterministic selection, verbatim recent turns, protocol handling)
is preserved unchanged.
"""

from __future__ import annotations

from typing import Any, Callable

from .core import CompactionError, CompactionResult, Protocol, compact_messages

__all__ = ["compact_dynamic"]

DEFAULT_CONTEXT_WINDOW = 69_632
DEFAULT_OUTPUT_RESERVE = 4_096
DEFAULT_MIN_TARGET = 24_576
DEFAULT_MAX_TARGET = 65_536
DEFAULT_PREFERRED_TARGET = 32_768
DEFAULT_RAW_LIMIT = 1_050_000

TokenCounter = Callable[[list[dict[str, Any]]], int]


def _require_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CompactionError(f"{name} must be an integer >= {minimum}",
                              code="invalid")
    return value


def compact_dynamic(
    messages: list[dict[str, Any]],
    count_tokens: TokenCounter,
    *,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    output_reserve: int = DEFAULT_OUTPUT_RESERVE,
    min_target: int = DEFAULT_MIN_TARGET,
    max_target: int = DEFAULT_MAX_TARGET,
    preferred_target: int = DEFAULT_PREFERRED_TARGET,
    fixed_tokens: int = 0,
    raw_limit: int = DEFAULT_RAW_LIMIT,
    protocol: Protocol = "openai",
) -> CompactionResult:
    """Compact `messages` into a budget-derived target.

    The available budget is ``context_window - output_reserve - fixed_tokens``.
    If that budget cannot hold at least ``min_target`` tokens the call fails
    closed with :class:`sift.CompactionError` instead of emitting an
    under-budget request. Otherwise the chosen target is
    ``min(preferred_target, max_target, available)`` clamped up to
    ``min_target``, and compaction is delegated to
    :func:`sift.core.compact_messages` with the caller's ``protocol``.
    """
    _require_int("context_window", context_window, minimum=1)
    _require_int("output_reserve", output_reserve, minimum=0)
    _require_int("min_target", min_target, minimum=1)
    _require_int("max_target", max_target, minimum=1)
    _require_int("preferred_target", preferred_target, minimum=1)
    _require_int("fixed_tokens", fixed_tokens, minimum=0)
    _require_int("raw_limit", raw_limit, minimum=1)

    available = context_window - output_reserve - fixed_tokens
    if available < min_target:
        raise CompactionError(
            "available budget below min_target", code="insufficient_budget")
    if protocol not in {"openai", "anthropic"}:
        raise CompactionError("unsupported protocol", code="unsupported_protocol")
    if max_target < min_target:
        raise CompactionError("max_target below min_target", code="invalid")

    target = min(preferred_target, max_target, available)
    if target < min_target:
        target = min_target
    if raw_limit < target:
        raise CompactionError("raw_limit below target", code="invalid")

    result = compact_messages(messages, count_tokens, target=target,
                              raw_limit=raw_limit, protocol=protocol)
    audit = dict(result.audit)
    audit["target_tokens"] = target
    audit["context_window"] = context_window
    audit["output_reserve"] = output_reserve
    audit["fixed_tokens"] = fixed_tokens
    return CompactionResult(result.messages, audit)
