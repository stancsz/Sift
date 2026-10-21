"""Pin synthetic LongMemEval reader request construction to MiniMax M3.

This pure policy creates no SDK client and performs no network request. It does
not verify endpoint availability, usage receipts, live token limits or budget,
and does not authorize dispatch. Provider semantics follow the official guide:
https://openrouter.ai/docs/guides/routing/provider-selection
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from functools import wraps
from typing import Any


MODEL = "minimax/minimax-m3"
_PROVIDER_PIN = {"only": ["minimax"], "allow_fallbacks": False, "require_parameters": True}
_ROUTING_ALIASES = frozenset({"models", "route", "provider", "fallbacks"})
# SDK extra_body is merged into the wire body. These reader controls must never
# be shadowed there, including when the top-level request did not supply them.
_READER_CONTROLS = frozenset({
    "model", "messages", "stream", "stream_options", "max_tokens",
    "max_completion_tokens", "timeout", "temperature", "top_p", "presence_penalty",
    "frequency_penalty", "reasoning_effort", "stop", "n", "seed", "extra_body",
})


class MiniMaxRequestPolicyError(ValueError):
    """The requested reader settings conflict with the pinned construction policy."""


def pin_minimax_reader_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return an independent request with one model, one provider and no fallback.

    ``max_tokens`` must be a positive integer; live endpoint and run-budget bounds
    must be checked separately before dispatch. Only absent/false nonstream mode
    is accepted. Existing provider settings may contain any subset of the exact
    pin; unrecognized routing settings fail rather than being silently changed.
    """
    if not isinstance(request, Mapping):
        raise MiniMaxRequestPolicyError("reader request must be a mapping")
    if request.get("model") != MODEL:
        raise MiniMaxRequestPolicyError("reader model must be the pinned MiniMax model")
    if _ROUTING_ALIASES.intersection(request):
        raise MiniMaxRequestPolicyError("top-level routing aliases are not supported")
    max_tokens = request.get("max_tokens")
    if type(max_tokens) is not int or max_tokens <= 0:
        raise MiniMaxRequestPolicyError("max_tokens must be a positive integer")
    if "max_completion_tokens" in request:
        raise MiniMaxRequestPolicyError("use only max_tokens for the compatible reader endpoint")
    if "stream" in request and request["stream"] is not False:
        raise MiniMaxRequestPolicyError("reader response plumbing requires nonstream mode")
    if "stream_options" in request:
        raise MiniMaxRequestPolicyError("stream options are not supported in nonstream mode")
    if not isinstance(request.get("messages"), list) or not request["messages"]:
        raise MiniMaxRequestPolicyError("reader messages must be a non-empty list")

    extra = request.get("extra_body")
    if extra is None:
        extra = {}
    if not isinstance(extra, Mapping):
        raise MiniMaxRequestPolicyError("extra_body must be a mapping")
    forbidden = (_READER_CONTROLS | (_ROUTING_ALIASES - {"provider"})).intersection(extra)
    # Cover any additional SDK field that would otherwise be overwritten by
    # an identically named extra_body member.
    collisions = (set(request) - {"extra_body"}).intersection(extra)
    if forbidden or collisions:
        raise MiniMaxRequestPolicyError("extra_body may not override reader controls or routing")
    provider = extra.get("provider", {})
    if not isinstance(provider, Mapping) or set(provider) - set(_PROVIDER_PIN):
        raise MiniMaxRequestPolicyError("provider settings must match the MiniMax-only pin")
    for key, value in provider.items():
        expected = _PROVIDER_PIN[key]
        if type(value) is not type(expected) or value != expected:
            raise MiniMaxRequestPolicyError("provider settings conflict with the MiniMax-only pin")

    result = deepcopy(dict(request))
    result["extra_body"] = deepcopy(dict(extra))
    result["extra_body"]["provider"] = deepcopy(_PROVIDER_PIN)
    return result


def wrap_minimax_reader_request_builder(builder: Callable[..., Mapping[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Wrap the official request builder without constructing or invoking a client."""
    @wraps(builder)
    def pinned_builder(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return pin_minimax_reader_request(builder(*args, **kwargs))

    return pinned_builder
