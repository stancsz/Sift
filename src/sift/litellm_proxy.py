"""Optional LiteLLM Proxy callback for Sift's bounded chat compaction.

Configure an instance after any callback that resolves the public model alias.
The core package remains independent of LiteLLM until this module is imported.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import threading
from typing import Any, Mapping

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger
from litellm.litellm_core_utils.core_helpers import get_or_create_metadata_bucket

from .core import CompactionError, compact_messages


_PROTOCOLS = {
    "completion": "openai",
    "acompletion": "openai",
    "anthropic_messages": "anthropic",
    "aanthropic_messages": "anthropic",
}


def _countable_tools(tools: Any) -> list[dict[str, Any]] | None:
    """Work around LiteLLM 1.103.0's missing-array-items counter error.

    The repaired schema is used for counting only; provider input stays exact.
    Remove this when the deployed LiteLLM counter accepts such schemas.
    """
    if not isinstance(tools, list):
        return None
    cloned = deepcopy(tools)
    pending: list[Any] = [cloned]
    changed = False
    visited = 0
    while pending:
        node = pending.pop()
        visited += 1
        if visited > 10_000:
            raise HTTPException(422, detail="tool schema is too large to count")
        if isinstance(node, dict):
            if node.get("type") == "array" and "items" not in node:
                node["items"] = {"type": "string"}
                changed = True
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return cloned if changed else None


def compact_proxy_request(
    router: Any, data: dict[str, Any], *, call_type: str,
    target: int, raw_limit: int = 1_000_000,
) -> dict[str, Any]:
    """Return request messages plus a server-owned Sift audit.

    Uses the proxy router's deployed pre-call counter so tools and route
    metadata count against the same budget as LiteLLM's own capacity check.
    """
    protocol = _PROTOCOLS.get(call_type)
    if protocol is None:
        raise HTTPException(422, detail="Sift supports Chat Completions and Anthropic Messages only")
    messages = data.get("messages")
    if not isinstance(messages, list) or not all(isinstance(msg, dict) for msg in messages):
        raise HTTPException(400, detail="Sift requires chat messages")
    counting_data = data
    repaired_tool_count = False

    def count(candidate: list[dict[str, Any]]) -> int:
        nonlocal counting_data, repaired_tool_count
        try:
            return router._count_pre_call_check_tokens(
                messages=candidate, input=data.get("input"),
                request_kwargs={**counting_data, "messages": candidate},
            )
        except KeyError as error:
            if error.args != ("items",) or repaired_tool_count:
                raise
            tools = _countable_tools(data.get("tools"))
            if tools is None:
                raise
            counting_data = {**data, "tools": tools}
            repaired_tool_count = True
            return router._count_pre_call_check_tokens(
                messages=candidate, input=data.get("input"),
                request_kwargs={**counting_data, "messages": candidate},
            )

    try:
        result = compact_messages(
            messages, count, target=target, raw_limit=raw_limit, protocol=protocol,
        )
    except CompactionError as error:
        status = {
            "raw_limit": 413, "active_too_large": 413,
            "unsupported_content": 422, "unsupported_protocol": 422,
            "late_instruction": 422,
        }.get(error.code, 400)
        raise HTTPException(status, detail=f"Sift: {error}") from error
    output = {**data, "messages": result.messages if result.audit["compacted"] else messages}
    key, metadata = get_or_create_metadata_bucket(output)
    output[key] = {**metadata, "sift": {
        **result.audit, "counting_tool_schema_items_filled": repaired_tool_count,
    }}
    return output


class SiftLiteLLMHook(CustomLogger):
    """LiteLLM Proxy callback for explicitly configured chat model names."""

    def __init__(self, model_targets: Mapping[str, int], *, raw_limit: int = 1_000_000) -> None:
        super().__init__()
        if not model_targets or any(
            not isinstance(name, str) or not name or type(target) is not int or target <= 0
            for name, target in model_targets.items()
        ) or type(raw_limit) is not int or raw_limit < max(model_targets.values()):
            raise ValueError("invalid Sift model targets or raw limit")
        self.model_targets = dict(model_targets)
        self.raw_limit = raw_limit
        self._slots = threading.BoundedSemaphore(2)

    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any,
                                  data: dict, call_type: str) -> dict | None:
        model = data.get("model")
        target = self.model_targets.get(model) if isinstance(model, str) else None
        if target is None:
            return None
        from litellm.proxy import proxy_server

        router = proxy_server.llm_router
        if router is None:
            raise HTTPException(503, detail="Sift token counter is unavailable")

        def run() -> dict[str, Any]:
            if not self._slots.acquire(timeout=1):
                raise HTTPException(429, detail="Sift is busy")
            try:
                return compact_proxy_request(
                    router, data, call_type=call_type,
                    target=target, raw_limit=self.raw_limit,
                )
            finally:
                self._slots.release()

        return await asyncio.to_thread(run)

    async def async_post_call_response_headers_hook(
        self, data: dict, user_api_key_dict: Any, response: object,
        request_headers: dict[str, str] | None = None,
        litellm_call_info: dict[str, object] | None = None,
    ) -> dict[str, str] | None:
        model = data.get("model")
        if not isinstance(model, str) or model not in self.model_targets:
            return None
        metadata = data.get("litellm_metadata") or data.get("metadata") or {}
        audit = metadata.get("sift") if isinstance(metadata, dict) else None
        if not isinstance(audit, dict) or type(audit.get("compacted")) is not bool:
            return None
        return {
            "x-sift-compacted": str(audit["compacted"]).lower(),
            "x-sift-estimated-input-tokens": str(audit["input_tokens"]),
            "x-sift-estimated-forwarded-tokens": str(audit["forwarded_tokens"]),
        }
