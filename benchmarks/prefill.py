"""Sequential, opt-in prefill measurements through LiteLLM's streaming SDK.

Cases are JSONL objects with name/document/question/expected string fields.
No cases or provider credentials are bundled. The caller owns gateway policy.
This measures client-observed timing, not server decode throughput or dollars.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from importlib.metadata import version
import json
import os
from pathlib import Path
import random
import statistics
import time
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from sift import compact_messages


SYSTEM = "Answer only from supplied earlier records. Reply with the requested label only."
VARIANTS = ("full", "sift", "head_tail")
OMITTED = "\n[historical document omitted]\n"


def make_messages(case: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": case["document"]},
        {"role": "assistant", "content": "Received the earlier records."},
        {"role": "user", "content": case["question"]},
    ]


def head_tail_messages(
    messages: list[dict[str, str]], target: int,
    count_tokens: Callable[[list[dict[str, str]]], int],
) -> list[dict[str, str]]:
    """Trim only the historical document, preserving the other messages exactly."""
    result = deepcopy(messages)
    if count_tokens(result) <= target:
        return result
    document = messages[1]["content"]

    def candidate(chars: int) -> list[dict[str, str]]:
        head = chars // 4
        tail = chars - head
        result[1]["content"] = document[:head] + OMITTED + (document[-tail:] if tail else "")
        return result

    if count_tokens(candidate(0)) > target:
        raise ValueError("Head/tail essential messages and omission marker exceed target")
    best = 0
    low, high = 1, len(document) - 1
    while low <= high:
        middle = (low + high) // 2
        if count_tokens(candidate(middle)) <= target:
            best, low = middle, middle + 1
        else:
            high = middle - 1
    candidate(best)
    if count_tokens(result) > target:
        raise ValueError("Head/tail token counter did not produce an admissible result")
    return result


def _get(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _usage(usage: Any) -> dict[str, int | None]:
    prompt_details = _get(usage, "prompt_tokens_details")
    completion_details = _get(usage, "completion_tokens_details")
    values = {
        "input_tokens": _get(usage, "prompt_tokens"),
        "output_tokens": _get(usage, "completion_tokens"),
        "reasoning_tokens": _get(completion_details, "reasoning_tokens"),
        "cached_tokens": _get(prompt_details, "cached_tokens"),
    }
    return {key: value if type(value) is int and value >= 0 else None
            for key, value in values.items()}


def _failure(error: Exception, stage: str) -> dict[str, Any]:
    # Exception strings can contain credentials or echoed request documents.
    status = getattr(error, "status_code", None)
    return {"stage": stage, "type": type(error).__name__,
            "http_status": status if type(status) is int else None}


def _label(text: str) -> str:
    return text.strip(" \t\r\n`")


def _redact(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


def _native_stream_evidence(stream: Any) -> tuple[Any, dict[str, int | None], bool]:
    """Inspect the pinned synchronous OpenAI wrapper, never synthesized output.

    In LiteLLM 1.103.0, received_finish_reason is set from the provider chunk.
    chunks contains provider-processed chunks before usage stripping; the SDK's
    synthesized terminal and estimated final usage are not appended there.
    Recheck this private contract before supporting another version or adapter.
    """
    usage = _usage(None)
    if (version("litellm") != "1.103.0"
            or type(stream).__module__ != "litellm.litellm_core_utils.streaming_handler"
            or type(stream).__name__ != "CustomStreamWrapper"
            or getattr(stream, "custom_llm_provider", None) != "openai"
            or not isinstance(getattr(stream, "chunks", None), list)):
        return None, usage, False
    for chunk in stream.chunks:
        native = _get(chunk, "usage")
        if native is not None:
            usage.update({key: value for key, value in _usage(native).items() if value is not None})
    # This version normalizes omitted top-level counts to zero. With nonempty
    # benchmark prompts/answers, zero is not reliable native token evidence.
    for key in ("input_tokens", "output_tokens"):
        if usage[key] == 0:
            usage[key] = None
    return stream.received_finish_reason, usage, True


def _stream_sample(completion: Callable[..., Any], messages: list[dict[str, str]],
                   *, model: str, base_url: str, api_key: str,
                   max_output_tokens: int = 768) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "ttft_ms": None, "first_visible_text_ms": None,
        "finish_reason": None, "failure": None,
        "usage": _usage(None), "sdk_usage": _usage(None),
    }
    started = time.perf_counter()
    stream = None
    answer: list[str] = []
    try:
        stream = completion(
            model="openai/" + model, api_base=base_url, api_key=api_key,
            messages=messages, stream=True, stream_options={"include_usage": True},
            temperature=0, seed=773, max_tokens=max_output_tokens, num_retries=0,
            timeout=90, extra_body={"cache_prompt": False},
        )
        for chunk in stream:
            usage = _get(chunk, "usage")
            if usage is not None:
                sample["sdk_usage"].update({key: value for key, value in _usage(usage).items()
                                            if value is not None})
            for choice in _get(chunk, "choices") or []:
                delta = _get(choice, "delta")
                text = _get(delta, "content")
                reasoning = _get(delta, "reasoning_content")
                elapsed_ms = (time.perf_counter() - started) * 1000
                if ((isinstance(text, str) and text) or
                        (isinstance(reasoning, str) and reasoning)) and sample["ttft_ms"] is None:
                    sample["ttft_ms"] = elapsed_ms
                if isinstance(text, str) and text:
                    if sample["first_visible_text_ms"] is None:
                        sample["first_visible_text_ms"] = elapsed_ms
                    answer.append(text)
                finish = _get(choice, "finish_reason")
                if finish is not None:
                    sample["finish_reason"] = finish
    except Exception as error:
        sample["failure"] = _failure(error, "stream")
    finally:
        if stream is not None and callable(getattr(stream, "close", None)):
            try:
                stream.close()
            except Exception as error:
                if sample["failure"] is None:
                    sample["failure"] = _failure(error, "close")
        sample["total_ms"] = (time.perf_counter() - started) * 1000
    native_finish, native_usage, supported = _native_stream_evidence(stream)
    sample["native_finish_reason"] = native_finish
    sample["native_provenance_supported"] = supported
    sample["usage"] = native_usage
    sample["usage_source"] = "provider_chunk" if any(value is not None for value in native_usage.values()) else "unknown"
    sample["sdk_usage_source"] = "normalized_or_estimated_unverified"
    sample["normal"] = (sample["failure"] is None and sample["finish_reason"] == "stop"
                        and native_finish == "stop")
    sample["answer"] = "".join(answer)
    cached = sample["usage"]["cached_tokens"]
    sample["cold_status"] = "verified" if cached == 0 else "not_cold" if cached is not None else "unknown"
    return sample


def _summary(samples: list[dict[str, Any]], expected_count: int | None = None) -> dict[str, Any]:
    summaries = {}
    for variant in VARIANTS:
        rows = [row for row in samples if row["variant"] == variant]
        comparable = [row for row in rows if row["normal"] and row["correct"]
                      and row["cold_status"] == "verified"]
        summary: dict[str, Any] = {
            "count": len(rows), "correct": sum(row["correct"] for row in rows),
            "normal": sum(row["normal"] for row in rows),
            "cold_verified": sum(row["cold_status"] == "verified" for row in rows),
            "comparable_count": len(comparable),
            "all_valid": bool(rows) and len(comparable) == len(rows)
                         and (expected_count is None or len(rows) == expected_count),
        }
        for prefix, cohort in (("", rows), ("comparable_", comparable)):
            for output in ("ttft_ms", "first_visible_text_ms", "total_ms",
                           "end_to_end_ms", "prompt_tokens", "prep_cpu_ms", "prep_wall_ms"):
                values = [row["usage"]["input_tokens"] if output == "prompt_tokens"
                          else row.get(output) for row in cohort]
                observed = [value for value in values if value is not None]
                summary[prefix + "mean_" + output] = statistics.fmean(observed) if observed else None
                summary[prefix + output + "_observations"] = len(observed)
        summaries[variant] = summary
    return summaries


def run_cases(cases: list[dict[str, str]], *, base_url: str, model: str,
              output: str | Path | None = None, target: int = 6000,
              repeats: int = 2, api_key_env: str = "SIFT_BENCH_API_KEY",
              max_output_tokens: int = 768) -> dict[str, Any]:
    """Run sequential samples; gateway routing/compaction policy is caller-owned.

    Returns a report and optionally writes it after every completed sample.
    Importing this module and calling the baseline helpers never contacts a provider.
    """
    if target <= 0 or repeats <= 0 or max_output_tokens <= 0:
        raise ValueError("target, repeats, and max_output_tokens must be positive")
    for case in cases:
        if not all(isinstance(case.get(key), str) and case[key]
                   for key in ("name", "document", "question", "expected")):
            raise ValueError("Each case needs nonempty name/document/question/expected strings")
    if not cases:
        raise ValueError("At least one case is required")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ValueError("Required API-key environment variable is unset")
    import litellm

    if version("litellm") != "1.103.0":
        raise ValueError("This benchmark requires LiteLLM 1.103.0 for native stream provenance")

    counter = lambda messages: litellm.token_counter(model="openai/" + model, messages=messages)
    parsed = urlsplit(base_url)
    safe_base = urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
    report: dict[str, Any] = {
        "model": model, "base_url": safe_base, "target": target, "repeats": repeats,
        "max_output_tokens": max_output_tokens,
        "requested_samples": len(cases) * repeats * len(VARIANTS),
        "litellm_version": version("litellm"),
        "seed": 773, "cache_prompt_requested": False,
        "notes": ["Client-observed streaming timing; TTFT includes reasoning when exposed.",
                  "TTFT and total_ms start at the SDK call; end_to_end_ms adds transformation preparation only.",
                  "Raw/prepared token counts used solely for reporting are excluded from preparation timing.",
                  "Provider terminal/usage provenance uses pinned LiteLLM 1.103.0 synchronous OpenAI wrapper attributes.",
                  "sdk_usage is normalized or estimated, unverified, and never establishes provider usage or cold status.",
                  "Cold status is verified only by provider-reported cached_tokens == 0.",
                  "Gateway policy must preserve the prepared requests for a valid comparison.",
                  "All-row means include failures; comparable means require correct, normal, verified-cold samples.",
                  "Partial comparable cohorts may contain different cases and do not establish an equivalent-quality speedup.",
                  "full_vs_sift_comparison_valid excludes head/tail, whose quality failures remain reported.",
                  "No dollar savings or server decode throughput is inferred."],
        "samples": [],
    }

    def save() -> None:
        report["summary"] = _summary(report["samples"], len(cases) * repeats)
        report["comparison_valid"] = all(report["summary"][variant]["all_valid"] for variant in VARIANTS)
        report["full_vs_sift_comparison_valid"] = all(
            report["summary"][variant]["all_valid"] for variant in ("full", "sift"))
        if output is not None:
            # Defense in depth: remove the credential even if it occurs in generated text.
            serialized = json.dumps(_redact(report, api_key), indent=2, ensure_ascii=False)
            Path(output).write_text(serialized + "\n", encoding="utf-8")

    if output is not None:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
    save()  # Verify the destination before any provider call and expose incomplete runs.
    rng = random.Random(773)
    for case in cases:
        for repeat in range(repeats):
            order = list(VARIANTS)
            rng.shuffle(order)
            for variant in order:
                messages = make_messages(case)
                row: dict[str, Any] = {
                    "case": case["name"], "repeat": repeat + 1, "variant": variant,
                    "correct": False, "normal": False, "cold_status": "unknown",
                    "usage": {key: None for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")},
                }
                try:
                    raw_tokens = counter(messages)
                    row["raw_estimated_tokens"] = raw_tokens
                    wall_started = time.perf_counter()
                    started = time.process_time()
                    try:
                        if variant == "sift":
                            prepared = compact_messages(messages, counter, target=target,
                                                        raw_limit=1_000_000, protocol="openai").messages
                        elif variant == "head_tail":
                            prepared = head_tail_messages(messages, target, counter)
                        else:
                            prepared = messages
                    finally:
                        row["prep_cpu_ms"] = (time.process_time() - started) * 1000
                        row["prep_wall_ms"] = (time.perf_counter() - wall_started) * 1000
                    row["prepared_estimated_tokens"] = counter(prepared)
                except Exception as error:
                    row["failure"] = _failure(error, "prepare")
                if "failure" not in row:
                    row.update(_stream_sample(litellm.completion, prepared, model=model,
                                              base_url=base_url, api_key=api_key,
                                              max_output_tokens=max_output_tokens))
                    answer = row.pop("answer")
                    row["correct"] = row["normal"] and _label(answer) == _label(case["expected"])
                    row["expected"] = case["expected"].replace(api_key, "[redacted]")
                    row["answer_preview"] = answer.replace(api_key, "[redacted]")[:256]
                row["end_to_end_ms"] = (row["prep_wall_ms"] + row["total_ms"]
                                        if "prep_wall_ms" in row and "total_ms" in row else None)
                report["samples"].append(row)
                save()
    # The returned object follows the same credential-redaction rule as the file.
    return _redact(report, api_key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="JSONL name/document/question/expected cases")
    parser.add_argument("--base-url", required=True, help="Gateway OpenAI-compatible base URL, including /v1")
    parser.add_argument("--model", required=True, help="Public gateway model alias")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", type=int, default=6000)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--max-output-tokens", type=int, default=768,
                        help="Output cap including reasoning; use a new report for a changed cap")
    parser.add_argument("--api-key-env", default="SIFT_BENCH_API_KEY")
    args = parser.parse_args()
    if args.max_output_tokens <= 0:
        parser.error("--max-output-tokens must be positive")
    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = run_cases(cases, base_url=args.base_url, model=args.model, output=args.output,
                       target=args.target, repeats=args.repeats, api_key_env=args.api_key_env,
                       max_output_tokens=args.max_output_tokens)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
