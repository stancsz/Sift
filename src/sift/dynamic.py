"""Pure dynamic compaction adapter.

Chooses a request-adaptive token target from the caller's context budget and
the request's own native size, then delegates to the existing
:func:`sift.core.compact_messages` compactor so every existing guarantee
(deterministic selection, verbatim recent turns, protocol handling) is
preserved unchanged.

Policy (deterministic; no keyword guessing, no VRAM telemetry):

``available = context_window - output_reserve - fixed_tokens``
``ceiling   = min(max_target, available)``
``raw       = count_tokens(messages)``  (native full-request size)

* ``raw <= preferred_target`` -> the request already fits the anchor working
  set, so it is forwarded unchanged with
  ``target = min(preferred_target, ceiling)``.
* otherwise the working set grows with the request:
  ``target = clamp(ceil(raw / compression_ratio), min_target, ceiling)``.

The ratio is the transparent, configurable compression assumption: how much
larger a raw history may be than the working set Sift keeps. ``raw / 8`` is
the default. The floor is ``min_target`` and the ceiling is the smaller of
``max_target`` and the tokens actually available in the window, so a target
never exceeds what the model window can accept.

This adapter chooses a *budget*. It does not choose content: selection stays
inside :func:`sift.core.compact_messages`, which keeps the immutable system
and active turn, never splits a protected tool group, and fails closed when
mandatory content cannot fit the chosen target.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from .core import (
    CompactionError, CompactionResult, Protocol, compact_messages,
    DEFAULT_MAX_INPUT_CHARACTERS, DEFAULT_MAX_INPUT_NODES,
    _check_precount_size, _count,
)

__all__ = ["compact_dynamic"]

DEFAULT_CONTEXT_WINDOW = 69_632
DEFAULT_OUTPUT_RESERVE = 4_096
DEFAULT_MIN_TARGET = 24_576
DEFAULT_MAX_TARGET = 65_536
DEFAULT_PREFERRED_TARGET = 32_768
DEFAULT_RAW_LIMIT = 1_050_000
DEFAULT_COMPRESSION_RATIO = 8.0

TokenCounter = Callable[[list[dict[str, Any]]], int]


def _require_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CompactionError(f"{name} must be an integer >= {minimum}",
                              code="invalid")
    return value


def _require_ratio(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompactionError("compression_ratio must be a positive number",
                              code="invalid")
    try:
        ratio = float(value)
    except OverflowError as error:
        raise CompactionError("compression_ratio must be finite", code="invalid") from error
    if not math.isfinite(ratio) or ratio < 1:
        raise CompactionError("compression_ratio must be finite and >= 1",
                              code="invalid")
    return ratio


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
    compression_ratio: float = DEFAULT_COMPRESSION_RATIO,
    protocol: Protocol = "openai",
) -> CompactionResult:
    """Compact `messages` into a request-adaptive budget-derived target.

    The available budget is ``context_window - output_reserve - fixed_tokens``.
    If that budget cannot hold at least ``min_target`` tokens the call fails
    closed with :class:`sift.CompactionError` instead of emitting an
    under-budget request. The chosen target is the anchor
    ``preferred_target`` for a request that already fits it, and otherwise
    ``ceil(raw / compression_ratio)`` bounded below by ``min_target`` and
    above by ``min(max_target, available)``. The target therefore varies with
    the size of the request under one unchanged configuration.

    Compaction is delegated to :func:`sift.core.compact_messages` with the
    caller's ``protocol``; selection, protected-content rules and the
    fail-closed behaviour of mandatory content are unchanged.
    """
    _require_int("context_window", context_window, minimum=1)
    _require_int("output_reserve", output_reserve, minimum=0)
    _require_int("min_target", min_target, minimum=1)
    _require_int("max_target", max_target, minimum=1)
    _require_int("preferred_target", preferred_target, minimum=1)
    _require_int("fixed_tokens", fixed_tokens, minimum=0)
    _require_int("raw_limit", raw_limit, minimum=1)
    ratio = _require_ratio(compression_ratio)

    available = context_window - output_reserve - fixed_tokens
    if available < min_target:
        raise CompactionError(
            "available budget below min_target", code="insufficient_budget")
    if protocol not in {"openai", "anthropic"}:
        raise CompactionError("unsupported protocol", code="unsupported_protocol")
    if max_target < min_target:
        raise CompactionError("max_target below min_target", code="invalid")

    ceiling = min(max_target, available)
    if ceiling < min_target:
        raise CompactionError(
            "available budget below min_target", code="insufficient_budget")

    # Apply the same resource guards as compact_messages BEFORE native I/O.
    if not isinstance(messages, list) or not all(isinstance(msg, dict) for msg in messages):
        raise CompactionError("messages must be a list of objects")
    _check_precount_size(messages, max_characters=DEFAULT_MAX_INPUT_CHARACTERS,
                         max_nodes=DEFAULT_MAX_INPUT_NODES)
    raw = _count(count_tokens, messages)
    if raw > raw_limit:
        raise CompactionError("request exceeds raw_limit", code="raw_limit")

    if raw <= preferred_target:
        target = min(preferred_target, ceiling)
    else:
        target = math.ceil(raw / ratio)
        if target < min_target:
            target = min_target
        if target > ceiling:
            target = ceiling
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
    audit["raw_native_tokens"] = raw
    audit["available_tokens"] = available
    audit["ceiling_tokens"] = ceiling
    audit["anchor_tokens"] = preferred_target
    audit["compression_ratio"] = ratio
    audit["budget_policy"] = "request_adaptive_ratio"
    return CompactionResult(result.messages, audit)
