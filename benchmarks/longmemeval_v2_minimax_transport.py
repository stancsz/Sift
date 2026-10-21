"""Optional, explicit MiniMax reader transport; importing this module sends nothing.

The factory matches the upstream ``client.chat.completions.create``/``close``
surface. It disables SDK retries and HTTP redirects and permanently stops the
client after any dispatched request fails validation or transport. Raw JSON is
checked before SDK coercion. Caps and Decimal costs cover one returned request,
not an aggregate budget, authorization, invoice or endpoint-acceptance claim.
There is no credential discovery or command-line dispatch entrypoint.

Rates default to the repository's dated 2026-10-20 MiniMax snapshot ($0.30/M
input, $1.20/M output); this uncached calculation is separate from optional
OpenRouter ``usage.cost`` and ``usage.cost_details.upstream_inference_cost``.
Those reported amounts remain separate, including a zero OpenRouter cost with
positive upstream cost on BYOK. Both reported amounts may be absent or null
(unknown), and null cost_details is treated as absent. This follows the nullable
optional-cost shape in the official response reference:
https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
import inspect
import ipaddress
import json
import math
from types import SimpleNamespace
from urllib.parse import urlsplit

from benchmarks.longmemeval_v2_minimax_request_policy import MODEL, pin_minimax_reader_request


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
FIXTURE_API_KEY = "SIFT_LOOPBACK_FIXTURE_ONLY"
_MILLION = Decimal(1_000_000)
_REQUEST_FIELDS = frozenset({"model", "messages", "max_tokens", "stream", "timeout",
                             "temperature", "top_p", "extra_body"})


class MiniMaxTransportError(RuntimeError):
    """Sanitized failure; never includes prompts, API keys or response bodies."""


@dataclass(frozen=True)
class ReaderCaps:
    max_prompt_tokens: int
    max_completion_tokens: int
    max_total_tokens: int

    def __post_init__(self):
        for value in (self.max_prompt_tokens, self.max_completion_tokens, self.max_total_tokens):
            if type(value) is not int or value <= 0:
                raise ValueError("reader caps must be positive integers")
        if max(self.max_prompt_tokens, self.max_completion_tokens) > self.max_total_tokens:
            raise ValueError("component caps must not exceed total cap")


@dataclass(frozen=True)
class TokenRates:
    input_usd_per_million: Decimal = Decimal("0.30")
    output_usd_per_million: Decimal = Decimal("1.20")

    def __post_init__(self):
        for value in (self.input_usd_per_million, self.output_usd_per_million):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("token rates must be finite nonnegative Decimals")


@dataclass(frozen=True)
class UsageReport:
    """Own-rate estimate plus two independent optional response-reported amounts.

    ``openrouter_reported_cost_usd`` comes from ``usage.cost``;
    ``upstream_inference_cost_usd`` comes from OpenRouter's
    ``usage.cost_details.upstream_inference_cost``. Neither is an account
    balance or invoice; no total combines these two reported amounts.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    own_input_cost_usd: Decimal
    own_output_cost_usd: Decimal
    own_cost_usd: Decimal
    openrouter_reported_cost_usd: Decimal | None
    upstream_inference_cost_usd: Decimal | None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response JSON field")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("nonfinite response JSON value")


def _optional_cost(container: dict, key: str) -> Decimal | None:
    if key not in container or container[key] is None:
        return None
    cost = container[key]
    if type(cost) not in (int, Decimal):
        raise ValueError("invalid optional reported cost")
    cost = Decimal(cost)
    if not cost.is_finite() or cost < 0:
        raise ValueError("invalid optional reported cost")
    return cost


def _validate_response(content: bytes, caps: ReaderCaps, rates: TokenRates) -> UsageReport:
    body = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
                      parse_float=Decimal)
    if not isinstance(body, dict) or body.get("model") != MODEL:
        raise ValueError("returned model mismatch")
    provider = body.get("provider")
    if not isinstance(provider, str) or provider.casefold() != "minimax":
        raise ValueError("returned provider mismatch")
    if (not isinstance(body.get("id"), str) or not body["id"]
            or body.get("object") != "chat.completion"
            or type(body.get("created")) is not int or body["created"] < 0):
        raise ValueError("invalid completion identity")
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("expected one nonstream choice")
    choice = choices[0]
    message = choice.get("message")
    if (type(choice.get("index")) is not int or choice["index"] != 0
            or choice.get("finish_reason") not in {"stop", "length"}
            or not isinstance(message, dict) or message.get("role") != "assistant"
            or not isinstance(message.get("content"), str) or not message["content"].strip()
            or message.get("tool_calls") or message.get("function_call")):
        raise ValueError("invalid text completion")
    usage = body.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("missing returned usage")
    values = [usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("returned usage must contain nonnegative integers")
    prompt, completion, total = values
    if prompt <= 0 or total != prompt + completion:
        raise ValueError("returned usage is inconsistent")
    if (prompt > caps.max_prompt_tokens or completion > caps.max_completion_tokens
            or total > caps.max_total_tokens):
        raise ValueError("returned usage exceeds per-request caps")
    openrouter_cost = _optional_cost(usage, "cost")
    cost_details = usage.get("cost_details", {})
    if cost_details is None:
        cost_details = {}
    if not isinstance(cost_details, dict):
        raise ValueError("invalid optional cost details")
    upstream_cost = _optional_cost(cost_details, "upstream_inference_cost")
    own_input = Decimal(prompt) * rates.input_usd_per_million / _MILLION
    own_output = Decimal(completion) * rates.output_usd_per_million / _MILLION
    return UsageReport(prompt, completion, total, own_input, own_output, own_input + own_output,
                       openrouter_cost, upstream_cost)


class MiniMaxReaderClient:
    """Narrow upstream-compatible surface; a failed dispatch poisons this client.

    Calls are serialized so queued work cannot race past a failed request. A
    new client would bypass this local latch; callers still need a run policy.
    ``last_usage`` describes the most recent successful call, or None after a
    failure. Returned counters do not independently attest provider billing.
    """

    def __init__(self, sdk, caps: ReaderCaps, rates: TokenRates, timeout_seconds: float):
        self._sdk = sdk
        self._caps = caps
        self._rates = rates
        self._timeout = timeout_seconds
        self._lock = asyncio.Lock()
        self._poisoned = False
        self._closed = False
        self.last_usage: UsageReport | None = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    async def _create(self, **request):
        async with self._lock:
            if self._closed or self._poisoned:
                raise MiniMaxTransportError("reader client is closed or stopped after a failed dispatch")
            self.last_usage = None
            pinned = pin_minimax_reader_request(request)
            if set(pinned) - _REQUEST_FIELDS or set(pinned["extra_body"]) != {"provider"}:
                raise ValueError("unsupported transport request fields")
            if pinned["max_tokens"] != self._caps.max_completion_tokens:
                raise ValueError("request output limit must equal the configured completion cap")
            timeout = pinned.get("timeout", self._timeout)
            if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                    or not 0 < timeout <= self._timeout):
                raise ValueError("request timeout must fit the configured finite timeout")
            try:
                raw = await self._sdk.chat.completions.with_raw_response.create(**pinned)
                if raw.http_response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                    raise ValueError("expected a JSON completion response")
                report = _validate_response(raw.http_response.content, self._caps, self._rates)
                parsed = raw.parse()
                if inspect.isawaitable(parsed):
                    parsed = await parsed
                if (parsed.model != MODEL or parsed.usage.prompt_tokens != report.prompt_tokens
                        or parsed.usage.completion_tokens != report.completion_tokens
                        or parsed.usage.total_tokens != report.total_tokens):
                    raise ValueError("SDK response disagrees with checked raw usage")
                self.last_usage = report
                return parsed
            except BaseException as error:
                # Includes cancellation after an unknown remote outcome. Never
                # give an upstream retry or queued task another wire attempt.
                self._poisoned = True
                self.last_usage = None
                # The pinned harness closes only its successful path. Release
                # this owned client's resources here even if the caller exits
                # without reaching close(). Cleanup cannot authorize a retry.
                try:
                    await self._sdk.close()
                except BaseException:
                    # Preserve the original failure/cancellation and keep the
                    # poisoned latch. An explicit later close may try cleanup.
                    pass
                else:
                    self._closed = True
                if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                    raise
                raise MiniMaxTransportError("reader dispatch failed; client stopped, outcome may be unknown") from None

    async def close(self):
        async with self._lock:
            if not self._closed:
                self._closed = True
                await self._sdk.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        await self.close()


def create_minimax_reader_client(*, base_url: str, api_key: str, caps: ReaderCaps,
                                 rates: TokenRates = TokenRates(), timeout_seconds: float = 60,
                                 loopback_fixture: bool = False) -> MiniMaxReaderClient:
    """Construct only; dispatch requires a separate explicit create call.

    The external destination is pinned exactly. Fixture mode accepts only an
    HTTP literal loopback /v1 endpoint and the public fixture placeholder key.
    No keys, accounts or environment credentials are inspected by this helper.
    Existence of this optional helper grants no permission for real dispatch.
    """
    if not isinstance(caps, ReaderCaps) or not isinstance(rates, TokenRates):
        raise ValueError("explicit ReaderCaps and TokenRates are required")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0 or type(loopback_fixture) is not bool):
        raise ValueError("invalid transport settings")
    if not isinstance(api_key, str) or not api_key.strip() or any(c in api_key for c in "\r\n"):
        raise ValueError("an explicit API key is required")
    if not isinstance(base_url, str):
        raise ValueError("an explicit endpoint is required")
    if loopback_fixture:
        parts = urlsplit(base_url)
        try:
            literal_loopback = ipaddress.ip_address(parts.hostname).is_loopback
            port = parts.port
        except (ValueError, TypeError):
            literal_loopback, port = False, None
        if (parts.scheme != "http" or not literal_loopback or port is None
                or parts.username is not None or parts.password is not None
                or parts.path != "/v1" or parts.query or parts.fragment or api_key != FIXTURE_API_KEY):
            raise ValueError("fixture mode requires a literal loopback HTTP /v1 URL and fixture key")
    elif base_url != OPENROUTER_BASE_URL or api_key == FIXTURE_API_KEY:
        raise ValueError("external transport requires the exact pinned endpoint and explicit service key")

    # Optional SDK imports are intentionally lazy; no dependency installation.
    import httpx
    from openai import AsyncOpenAI

    http = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=timeout_seconds)
    sdk = AsyncOpenAI(base_url=base_url, api_key=api_key, organization="", project="",
                      max_retries=0, timeout=timeout_seconds, http_client=http)
    return MiniMaxReaderClient(sdk, caps, rates, timeout_seconds)
