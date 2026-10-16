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
from itertools import count
import logging
import os
import time

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
_selector = recency_compactor if ARM == "recency" else core.compact_messages
_logger = logging.getLogger("LiteLLM Proxy")
_request_sequence = count(1)
_current_request_sequence: ContextVar[int] = ContextVar("sift_benchmark_request_sequence", default=0)
_evidence_manifest = os.environ.get("SIFT_BENCH_EVIDENCE_MANIFEST")
_required_evidence = load_required_spans(_evidence_manifest) if _evidence_manifest else ()


def _evidence_status(messages, forwarded):
    if not _required_evidence:
        return ""
    states = audit_retention(messages, forwarded, _required_evidence)
    return ",".join(f"{span_id}:{state}" for span_id, state in states.items())


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
        _logger.info(
            "sift_benchmark_selection selector=%s request_seq=%d observed_utc_ns=%d target=%d status=failed error_type=%s wall_ms=%.3f thread_cpu_ms=%.3f",
            ARM, _current_request_sequence.get(), time.time_ns(), kwargs.get("target", TARGET), type(error).__name__,
            (time.perf_counter() - wall) * 1000, (time.thread_time() - cpu) * 1000,
        )
        raise
    _logger.info(
        "sift_benchmark_selection selector=%s request_seq=%d observed_utc_ns=%d target=%d status=ok input_tokens=%d forwarded_tokens=%d wall_ms=%.3f thread_cpu_ms=%.3f evidence=%s",
        ARM, _current_request_sequence.get(), time.time_ns(), kwargs.get("target", TARGET),
        result.audit["input_tokens"], result.audit["forwarded_tokens"],
        (time.perf_counter() - wall) * 1000, (time.thread_time() - cpu) * 1000,
        _evidence_status(messages, result.messages),
    )
    return result


# Process-wide, once at module import. Each experimental arm gets a fresh
# isolated container; requests cannot select or change the arm.
install_benchmark_counter_fix()
integration.compact_messages = observed_selection


class NativeBenchmarkHook(integration.SiftLiteLLMHook):
    async_post_call_response_headers_hook = integration.SiftLiteLLMHook.async_post_call_response_headers_hook

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if data.get("model") in {MODEL, FULL_MODEL}:
            for field in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                value = data.get(field)
                if value is not None and (type(value) is not int or not 0 < value <= OUTPUT_LIMIT):
                    raise HTTPException(422, detail="Native benchmark output limits must be positive integers at most 4096")
            sequence = next(_request_sequence)
            sequence_token = _current_request_sequence.set(sequence)
        else:
            sequence_token = None
        try:
            translated = qwen_instruction_prefix(data, call_type)
            if data.get("model") == FULL_MODEL and _required_evidence:
                messages = translated.get("messages", [])
                states = _evidence_status(messages, messages)
                _logger.info(
                    "sift_benchmark_selection selector=full request_seq=%d observed_utc_ns=%d status=ok evidence=%s",
                    _current_request_sequence.get(), time.time_ns(), states,
                )
            selected = await super().async_pre_call_hook(user_api_key_dict, cache, translated, call_type)
            if selected is not None:
                return selected
            return translated if translated is not data else None
        finally:
            if sequence_token is not None:
                _current_request_sequence.reset(sequence_token)


benchmark_hook = NativeBenchmarkHook({MODEL: TARGET}, raw_limit=1_000_000)
