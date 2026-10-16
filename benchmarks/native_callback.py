"""One selector, fixed at startup, in an isolated LiteLLM benchmark process.

This is temporary measurement instrumentation, not a product routing setting.
The private integration binding lets the selector arms share this checkout's
token counter, schema floor, Responses restore path and bounded execution
without copying them.
Never import this file into an existing production/staging gateway or switch its
selector per request. Retire this binding when the comparative experiment ends,
or replace it if a supported integration selection seam becomes available.
"""

from importlib.metadata import version
from contextvars import ContextVar
from datetime import date, datetime
from itertools import count
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Mapping

from fastapi import HTTPException

from sift import core
from sift import litellm_proxy as integration
from recency import compact_messages as recency_compactor
from evidence_retention import audit_retention, load_required_spans


if version("litellm") != "1.103.0":
    raise RuntimeError("The native benchmark requires LiteLLM 1.103.0")

ARM = os.environ.get("SIFT_BENCH_ARM", "sift")
if ARM not in {"full", "sift", "recency"}:
    raise RuntimeError("SIFT_BENCH_ARM must be full, sift or recency")
MODEL = os.environ.get("SIFT_BENCH_MODEL", "qwen3.8-27b")
FULL_MODEL = os.environ.get("SIFT_BENCH_FULL_MODEL", f"{MODEL}-full")
PROFILE = os.environ.get("SIFT_BENCH_PROFILE", "qwen")
if not MODEL or not FULL_MODEL or MODEL == FULL_MODEL:
    raise RuntimeError("SIFT_BENCH_MODEL and SIFT_BENCH_FULL_MODEL must be distinct aliases")
if PROFILE not in {"qwen", "passthrough"}:
    raise RuntimeError("SIFT_BENCH_PROFILE must be qwen or passthrough")
OUTPUT_LIMIT = 4_096
try:
    TARGET = int(os.environ.get("SIFT_BENCH_TARGET", "24576"))
except ValueError as error:
    raise RuntimeError("SIFT_BENCH_TARGET must be an integer") from error
MAX_TARGET = 1_000_000 if PROFILE == "passthrough" else 28_672
if not 0 < TARGET <= MAX_TARGET:
    raise RuntimeError(f"SIFT_BENCH_TARGET must be between 1 and {MAX_TARGET}")
try:
    MIN_RAW_TOKENS = int(os.environ.get("SIFT_BENCH_MIN_RAW_TOKENS", "0"))
except ValueError as error:
    raise RuntimeError("SIFT_BENCH_MIN_RAW_TOKENS must be an integer") from error
if not 0 <= MIN_RAW_TOKENS <= 1_000_000:
    raise RuntimeError("SIFT_BENCH_MIN_RAW_TOKENS must be between 0 and 1000000")
PREFLIGHT_ONLY = os.environ.get("SIFT_BENCH_PREFLIGHT_ONLY", "0").lower() in {"1", "true", "yes"}
RUN_ID = os.environ.get("SIFT_BENCH_RUN_ID", "")
if PREFLIGHT_ONLY and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", RUN_ID):
    raise RuntimeError("SIFT_BENCH_RUN_ID is required and must be 1-64 safe characters in preflight-only mode")
_selector = recency_compactor if ARM == "recency" else core.compact_messages
_logger = logging.getLogger("LiteLLM Proxy")
_request_sequence = count(1)
_current_request_sequence: ContextVar[int] = ContextVar("sift_benchmark_request_sequence", default=0)
_current_model: ContextVar[str] = ContextVar("sift_benchmark_model", default="")
_count_only_telemetry: ContextVar[bool] = ContextVar("sift_benchmark_count_only_telemetry", default=False)
_evidence_manifest = os.environ.get("SIFT_BENCH_EVIDENCE_MANIFEST")
_required_evidence = load_required_spans(_evidence_manifest) if _evidence_manifest else ()


def _evidence_status(messages, forwarded):
    if not _required_evidence:
        return ""
    states = audit_retention(messages, forwarded, _required_evidence)
    return ",".join(f"{span_id}:{state}" for span_id, state in states.items())


def _request_fingerprint(data):
    """Hash client-visible request fields while excluding model and route metadata."""
    if not isinstance(data, Mapping):
        raise HTTPException(422, detail="Native benchmark request must be an object")
    # LiteLLM adds proxy/runtime-only objects to the callback payload. Hash the
    # public chat request fields so those implementation objects do not make a
    # valid pair un-fingerprintable or pollute request identity.
    semantic_fields = {
        "messages", "system", "tools", "tool_choice", "functions", "function_call",
        "temperature", "top_p", "n", "stream", "stop", "max_tokens",
        "max_completion_tokens", "max_output_tokens", "presence_penalty",
        "frequency_penalty", "logit_bias", "user", "response_format", "seed",
        # LiteLLM can add arm-specific routing metadata between otherwise
        # identical requests. It does not enter the model prompt and is not
        # part of the pair's client-visible input semantics.
        "parallel_tool_calls", "reasoning_effort", "extra_body",
    }
    payload = {key: data[key] for key in semantic_fields if key in data}

    def json_safe(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Mapping):
            return {str(key): json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(item) for item in value]
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            return json_safe(dump(mode="json"))
        dump = getattr(value, "dict", None)
        if callable(dump):
            return json_safe(dump())
        raise TypeError(f"unsupported request value: {type(value).__name__}")

    try:
        serialized = json.dumps(json_safe(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        _logger.info("sift_benchmark_fingerprint status=failed error_type=%s", type(error).__name__)
        raise HTTPException(422, detail="Native benchmark request cannot be fingerprinted") from error
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def install_benchmark_counter_fix():
    """Keep native Router prechecks counting valid unconstrained arrays.

    LiteLLM 1.103.0's sync/async Router checks fail open when its formatter
    indexes omitted array items. Repair only this benchmark process's counter,
    without changing provider tools. Retire when the pinned formatter is fixed.
    """
    from litellm.litellm_core_utils import token_counter

    original = token_counter._format_type
    if getattr(original, "_sift_benchmark_array_items_fix", False):
        return

    def format_type(props, indent):
        if props.get("type") == "array" and "items" not in props:
            return "any[]"
        return original(props, indent)

    format_type._sift_benchmark_array_items_fix = True
    token_counter._format_type = format_type


def qwen_instruction_prefix(data, call_type):
    """Explicit template translation for this benchmark's Qwen Anthropic route.

    LiteLLM 1.103.0 preserves in-sequence instruction positions, which this
    backend template rejects. Preserve every object/role and within-group order,
    but deliberately move instructions before dialogue. This is a model profile,
    not Sift behavior or a general equivalence for mid-conversation instructions.
    Retire when the adapter or backend supports the required native placement.
    """
    if PROFILE != "qwen" or data.get("model") not in {MODEL, FULL_MODEL} or call_type not in {"anthropic_messages", "aanthropic_messages"}:
        return data
    messages = data.get("messages")
    if not isinstance(messages, list) or not all(isinstance(message, dict) for message in messages):
        return data
    instructions = [message for message in messages if message.get("role") in {"system", "developer"}]
    dialogue = [message for message in messages if message.get("role") not in {"system", "developer"}]
    if instructions + dialogue == messages:
        return data
    _logger.info("sift_benchmark_template_translation model=%s protocol=%s placement=initial_instruction_prefix", MODEL, call_type)
    return {**data, "messages": instructions + dialogue}


def observed_selection(messages, count_tokens, **kwargs):
    """Record selector work only; never log input bodies or exception text."""
    wall, cpu = time.perf_counter(), time.thread_time()
    try:
        result = _selector(messages, count_tokens, **kwargs)
    except Exception as error:
        if not _count_only_telemetry.get():
            _logger.info(
                "sift_benchmark_selection selector=%s request_seq=%d observed_utc_ns=%d target=%d status=failed error_type=%s wall_ms=%.3f thread_cpu_ms=%.3f",
                ARM, _current_request_sequence.get(), time.time_ns(), kwargs.get("target", TARGET), type(error).__name__,
                (time.perf_counter() - wall) * 1000, (time.thread_time() - cpu) * 1000,
            )
        raise
    raw_tokens = result.audit.get("input_tokens")
    if MIN_RAW_TOKENS and (type(raw_tokens) is not int or raw_tokens < MIN_RAW_TOKENS):
        _logger.info(
            "sift_benchmark_selection selector=%s model=%s request_seq=%d observed_utc_ns=%d target=%d status=below_raw_floor input_tokens=%s minimum_raw_tokens=%d",
            ARM, _current_model.get(), _current_request_sequence.get(), time.time_ns(),
            kwargs.get("target", TARGET), raw_tokens if raw_tokens is not None else "unknown", MIN_RAW_TOKENS,
        )
        raise HTTPException(422, detail=f"Native benchmark requires at least {MIN_RAW_TOKENS} raw input tokens")
    if _count_only_telemetry.get():
        return result
    _logger.info(
        "sift_benchmark_selection selector=%s model=%s request_seq=%d observed_utc_ns=%d target=%d status=ok input_tokens=%d forwarded_tokens=%d count_method=litellm_router_1_103_0 wall_ms=%.3f thread_cpu_ms=%.3f evidence=%s",
        ARM, _current_model.get(), _current_request_sequence.get(), time.time_ns(), kwargs.get("target", TARGET),
        result.audit["input_tokens"], result.audit["forwarded_tokens"],
        (time.perf_counter() - wall) * 1000, (time.thread_time() - cpu) * 1000,
        _evidence_status(messages, result.messages),
    )
    return result


def _provider_usage(response_obj):
    usage = getattr(response_obj, "usage", None)
    if usage is None and isinstance(response_obj, Mapping):
        usage = response_obj.get("usage")
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    if usage is None:
        return None
    if not isinstance(usage, Mapping):
        usage = {name: getattr(usage, name, None) for name in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens",
            "prompt_tokens", "prompt_tokens_details", "completion_tokens",
        )}
    names = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    values = {}
    for name in names:
        value = usage.get(name) if isinstance(usage, Mapping) else getattr(usage, name, None)
        if type(value) is int and value >= 0:
            values[name] = value
    if type(usage.get("prompt_tokens")) is int and usage["prompt_tokens"] >= 0:
        # OpenAI-compatible prompt_tokens includes cached input; do not add
        # cached counts on top of that total.
        values["input_tokens"] = usage["prompt_tokens"]
        details = usage.get("prompt_tokens_details")
        if isinstance(details, Mapping) and type(details.get("cached_tokens")) is int:
            values["cache_read_input_tokens"] = details["cached_tokens"]
        values["input_total_method"] = "prompt_tokens_includes_cached"
    elif "input_tokens" in values:
        values["input_total_method"] = "input_plus_cache_fields"
    if type(usage.get("completion_tokens")) is int and "output_tokens" not in values:
        values["output_tokens"] = usage["completion_tokens"]
    return values if "input_tokens" in values or "output_tokens" in values else None


def _benchmark_marker(kwargs):
    if not isinstance(kwargs, Mapping):
        return None
    for name in ("litellm_metadata", "metadata"):
        bucket = kwargs.get(name)
        if isinstance(bucket, Mapping) and isinstance(bucket.get("sift_benchmark"), Mapping):
            return bucket["sift_benchmark"]
    params = kwargs.get("litellm_params")
    if isinstance(params, Mapping):
        for name in ("litellm_metadata", "metadata"):
            bucket = params.get(name)
            if isinstance(bucket, Mapping) and isinstance(bucket.get("sift_benchmark"), Mapping):
                return bucket["sift_benchmark"]
    return None


# Process-wide, once at module import. Each experimental arm gets a fresh
# isolated container; requests cannot select or change the arm.
install_benchmark_counter_fix()
integration.compact_messages = observed_selection


class NativeBenchmarkHook(integration.SiftLiteLLMHook):
    async_post_call_response_headers_hook = integration.SiftLiteLLMHook.async_post_call_response_headers_hook

    def _run_preflight_only(self, router, data, translated, call_type, fingerprint):
        target = 1_000_000 if data.get("model") == FULL_MODEL else TARGET
        audited = integration.compact_proxy_request(
            router, translated, call_type=call_type, target=target, raw_limit=1_000_000,
        )
        audit = next((value.get("sift") for value in audited.values()
                      if isinstance(value, dict) and isinstance(value.get("sift"), dict)), None)
        if not isinstance(audit, dict):
            raise HTTPException(500, detail="Native benchmark preflight could not read route count")
        raw, forwarded = audit.get("input_tokens"), audit.get("forwarded_tokens")
        if type(raw) is not int or type(forwarded) is not int:
            raise HTTPException(500, detail="Native benchmark preflight received invalid route counts")
        arm = "full" if data.get("model") == FULL_MODEL else ARM
        status = "provider_blocked"
        if raw < MIN_RAW_TOKENS:
            status = "below_raw_floor"
        elif arm == "full" and forwarded != raw:
            status = "full_mutated"
        elif arm == "sift" and forwarded > TARGET:
            status = "above_target"
        _logger.info(
            "sift_benchmark_preflight run_id=%s arm=%s model=%s request_seq=%d fingerprint=%s raw_tokens=%d forwarded_tokens=%d target=%d minimum_raw_tokens=%d status=%s",
            RUN_ID, arm, data.get("model"), _current_request_sequence.get(), fingerprint,
            raw, forwarded, target if arm == "full" else TARGET, MIN_RAW_TOKENS, status,
        )
        if status != "provider_blocked":
            raise HTTPException(422, detail=f"Native benchmark preflight failed: {status}")
        # This hook runs before LiteLLM chooses or calls the provider.
        raise HTTPException(409, detail="Native benchmark preflight recorded; provider call blocked")

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        marker = _benchmark_marker(kwargs)
        usage = _provider_usage(response_obj)
        if usage is None and isinstance(kwargs, Mapping):
            usage = _provider_usage(kwargs.get("original_response"))
        if not isinstance(marker, Mapping) or usage is None:
            _logger.info(
                "sift_benchmark_provider_usage arm=%s model=%s request_seq=%s observed_utc_ns=%d status=unavailable response_type=%s has_marker=%s has_usage=%s",
                marker.get("arm", "unknown") if isinstance(marker, Mapping) else "unknown",
                marker.get("model", "unknown") if isinstance(marker, Mapping) else "unknown",
                marker.get("request_seq", "unknown") if isinstance(marker, Mapping) else "unknown",
                time.time_ns(), type(response_obj).__name__,
                str(isinstance(marker, Mapping)).lower(), str(usage is not None).lower(),
            )
            return
        _logger.info(
            "sift_benchmark_provider_usage arm=%s model=%s request_seq=%s observed_utc_ns=%d status=ok input_tokens=%s provider_reported_input_total=%s input_total_method=%s cache_creation_input_tokens=%s cache_read_input_tokens=%s output_tokens=%s",
            marker.get("arm", "unknown"), marker.get("model", "unknown"),
            marker.get("request_seq", "unknown"), time.time_ns(),
            usage.get("input_tokens", "unknown"), usage.get("input_tokens", "unknown"),
            usage.get("input_total_method", "unknown"),
            usage.get("cache_creation_input_tokens", "unknown"),
            usage.get("cache_read_input_tokens", "unknown"), usage.get("output_tokens", "unknown"),
        )

    def _measure_full_request(self, router, data, call_type):
        """Count a full-arm request through Sift's exact pinned LiteLLM route counter.

        The target is the profile's one-million-token raw ceiling, so a
        qualifying 500K-900K request is returned unchanged. The measured copy
        is discarded; the original full prompt is sent to the provider.
        """
        wall = time.perf_counter()
        count_only_token = _count_only_telemetry.set(True)
        try:
            audited = integration.compact_proxy_request(
                router, data, call_type=call_type, target=1_000_000, raw_limit=1_000_000,
            )
        except Exception as error:
            _logger.info(
                "sift_benchmark_selection selector=full model=%s request_seq=%d observed_utc_ns=%d target=none status=failed error_type=%s count_method=litellm_1_103_0 wall_ms=%.3f",
                FULL_MODEL, _current_request_sequence.get(), time.time_ns(), type(error).__name__,
                (time.perf_counter() - wall) * 1000,
            )
            raise
        finally:
            _count_only_telemetry.reset(count_only_token)
        audit = next((value.get("sift") for value in audited.values()
                      if isinstance(value, dict) and isinstance(value.get("sift"), dict)), None)
        if not isinstance(audit, dict):
            raise HTTPException(500, detail="Native benchmark could not read full-arm route count")
        raw = audit.get("input_tokens")
        forwarded = audit.get("forwarded_tokens")
        if type(raw) is not int or type(forwarded) is not int or raw != forwarded:
            raise HTTPException(500, detail="Native benchmark full-arm route count did not preserve input")
        if MIN_RAW_TOKENS and raw < MIN_RAW_TOKENS:
            _logger.info(
                "sift_benchmark_selection selector=full model=%s request_seq=%d observed_utc_ns=%d target=none status=below_raw_floor input_tokens=%d minimum_raw_tokens=%d",
                FULL_MODEL, _current_request_sequence.get(), time.time_ns(), raw, MIN_RAW_TOKENS,
            )
            raise HTTPException(422, detail=f"Native benchmark requires at least {MIN_RAW_TOKENS} raw input tokens")
        _logger.info(
            "sift_benchmark_selection selector=full model=%s request_seq=%d observed_utc_ns=%d target=none status=ok input_tokens=%d forwarded_tokens=%d count_method=litellm_router_1_103_0 wall_ms=%.3f evidence=%s",
            FULL_MODEL, _current_request_sequence.get(), time.time_ns(), raw, forwarded,
            (time.perf_counter() - wall) * 1000,
            _evidence_status(data.get("messages", []), data.get("messages", [])),
        )

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if PREFLIGHT_ONLY and data.get("model") not in {MODEL, FULL_MODEL}:
            raise HTTPException(403, detail="Preflight-only benchmark accepts only its two declared model aliases")
        if data.get("model") in {MODEL, FULL_MODEL}:
            for field in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                value = data.get(field)
                if value is not None and (type(value) is not int or not 0 < value <= OUTPUT_LIMIT):
                    raise HTTPException(422, detail="Native benchmark output limits must be positive integers at most 4096")
            sequence = next(_request_sequence)
            sequence_token = _current_request_sequence.set(sequence)
            model_token = _current_model.set(data["model"])
            metadata_key, metadata = integration.get_or_create_metadata_bucket(data)
            data[metadata_key] = {**metadata, "sift_benchmark": {
                "arm": ARM, "model": data["model"], "request_seq": sequence,
            }}
            fingerprint = None
        else:
            sequence_token = None
            model_token = None
            fingerprint = None
        try:
            if PREFLIGHT_ONLY:
                fingerprint = _request_fingerprint(data)
            translated = qwen_instruction_prefix(data, call_type)
            if PREFLIGHT_ONLY:
                from litellm.proxy import proxy_server

                router = proxy_server.llm_router
                if router is None:
                    raise HTTPException(503, detail="Native benchmark route counter is unavailable")
                self._run_preflight_only(router, data, translated, call_type, fingerprint)
            if data.get("model") == FULL_MODEL:
                from litellm.proxy import proxy_server

                router = proxy_server.llm_router
                if router is None:
                    raise HTTPException(503, detail="Native benchmark route counter is unavailable")
                self._measure_full_request(router, translated, call_type)
            selected = await super().async_pre_call_hook(user_api_key_dict, cache, translated, call_type)
            if selected is not None:
                return selected
            return translated if translated is not data else None
        finally:
            if model_token is not None:
                _current_model.reset(model_token)
            if sequence_token is not None:
                _current_request_sequence.reset(sequence_token)


benchmark_hook = NativeBenchmarkHook({MODEL: TARGET}, raw_limit=1_000_000)
