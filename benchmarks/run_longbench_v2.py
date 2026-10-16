"""Run the frozen LongBench v2 QA sample against local Qwen and Sift arms.

LLMLingua-2 is an optional, evaluation-only CPU dependency. This script sends
all inference requests directly to the local llama.cpp OpenAI-compatible API;
it measures the selector algorithms, not LiteLLM transport behavior.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import time
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_SHA256,
    DATASET_REVISION,
    MODEL_CONTEXT,
    OUTPUT_RESERVE,
    SIFT_TARGET,
    exact_prompt_tokens,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from recency import compact_messages as compact_recency  # noqa: E402
from sift import compact_messages  # noqa: E402


MODEL = "qwen3.8-27b"
LLMLINGUA_MODEL = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"
LLMLINGUA_REVISION = "ebaba9b0e874dadd3003ffcff828e4397e568089"
LLMLINGUA_START_TARGET = 18_000
LLMLINGUA_MAX_ATTEMPTS = 4
OUTPUT_TOKENS = 16
REPEATS = 3
SEED = 20261016
ARMS = ("full", "sift", "recency", "llmlingua2_text_only")
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"choice": {"type": "string", "enum": ["A", "B", "C", "D"]}},
    "required": ["choice"],
    "additionalProperties": False,
}


class EvaluationError(RuntimeError):
    pass


def load_frozen_cases(manifest_path: Path, dataset_path: Path, tokenizer_url: str):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["dataset"]["revision"] != DATASET_REVISION:
        raise EvaluationError("Frozen selection uses a different dataset revision")
    if manifest["dataset"]["data_file_sha256"] != DATASET_SHA256:
        raise EvaluationError("Frozen selection has a different dataset data hash")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise EvaluationError("Local LongBench v2 data does not match the pinned SHA-256")
    source_hash = hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest()
    if manifest["source"]["sift_core_sha256"] != source_hash:
        raise EvaluationError("Sift core changed after the sample was frozen")

    needed = {case["id"]: case for case in manifest["cases"]}
    rows = {}
    for row in iter_json_array(dataset_path):
        if row["_id"] in needed:
            rows[row["_id"]] = row
            if len(rows) == len(needed):
                break
    if set(rows) != set(needed):
        raise EvaluationError("Pinned dataset is missing a frozen case ID")

    session = requests.Session()
    prepared = []
    for frozen in manifest["cases"]:
        row = rows[frozen["id"]]
        if row["answer"] != frozen["answer_key"]:
            raise EvaluationError(f"Answer key changed for case {frozen['id']}")
        messages = make_messages(row)
        if prompt_sha256(messages) != frozen["prompt_sha256"]:
            raise EvaluationError(f"Prompt hash changed for case {frozen['id']}")
        exact = exact_prompt_tokens(tokenizer_url, messages)
        if exact != frozen["exact_full_prompt_tokens"]:
            raise EvaluationError(f"Tokenizer count changed for case {frozen['id']}")
        prepared.append({"frozen": frozen, "row": row, "messages": messages, "full_exact": exact})
    return manifest, prepared


def messages_for_arm(case: dict, arm: str, tokenizer_url: str,
                     compressor=None, target_tokens: int = SIFT_TARGET) -> tuple[list[dict], dict]:
    original = case["messages"]
    prep_started = time.perf_counter()
    cpu_started = time.process_time()
    details: dict[str, Any] = {}
    try:
        if arm == "full":
            output = deepcopy(original)
        elif arm == "sift":
            result = compact_messages(
                original, lambda value: exact_prompt_tokens(tokenizer_url, value),
                target=target_tokens, raw_limit=1_000_000, protocol="openai",
            )
            output = result.messages
            details["selector_audit"] = result.audit
        elif arm == "recency":
            result = compact_recency(
                original, lambda value: exact_prompt_tokens(tokenizer_url, value),
                target=target_tokens, raw_limit=1_000_000, protocol="openai",
            )
            output = result.messages
            details["selector_audit"] = result.audit
        elif arm == "llmlingua2_text_only":
            if compressor is None:
                raise EvaluationError("LLMLingua-2 compressor is not initialized")
            context = original[1]["content"].removeprefix("<text>\n").removesuffix("\n</text>")
            question = original[-1]["content"]
            llm_target = LLMLINGUA_START_TARGET
            output = deepcopy(original)
            attempts = []
            for _ in range(LLMLINGUA_MAX_ATTEMPTS):
                compressed = compressor.compress_prompt(
                    context=[context], question=question,
                    target_token=llm_target, concate_question=False,
                )
                output = deepcopy(original)
                output[1]["content"] = "<text>\n" + compressed["compressed_prompt"].strip() + "\n</text>"
                count = exact_prompt_tokens(tokenizer_url, output)
                attempts.append({
                    "target_tokens": llm_target,
                    "reported_tokens": compressed.get("compressed_tokens"),
                    "exact_qwen_tokens": count,
                })
                if count <= target_tokens:
                    break
                llm_target = max(1_000, int(llm_target * target_tokens / count * 0.9))
            details["llmlingua_attempts"] = attempts
            details["llmlingua_model"] = LLMLINGUA_MODEL
            details["llmlingua_revision"] = LLMLINGUA_REVISION
        else:
            raise EvaluationError(f"Unknown evaluation arm {arm}")
    finally:
        details["preprocess_wall_ms"] = (time.perf_counter() - prep_started) * 1000
        details["preprocess_cpu_ms"] = (time.process_time() - cpu_started) * 1000
    details["exact_qwen_input_tokens"] = exact_prompt_tokens(tokenizer_url, output)
    details["fits_arm_limit"] = details["exact_qwen_input_tokens"] <= (
        MODEL_CONTEXT - OUTPUT_RESERVE if arm == "full" else target_tokens
    )
    return output, details


def extract_choice(text: str) -> str | None:
    try:
        answer = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(answer, dict) or set(answer) != {"choice"}:
        return None
    choice = answer["choice"]
    return choice if choice in {"A", "B", "C", "D"} else None


def validate_arms(arms: list[str] | None) -> tuple[str, ...]:
    selected = tuple(ARMS if arms is None else arms)
    if not selected or len(set(selected)) != len(selected):
        raise EvaluationError("Arms must be a nonempty list without duplicates")
    unknown = set(selected) - set(ARMS)
    if unknown:
        raise EvaluationError(f"Unknown arms: {', '.join(sorted(unknown))}")
    if not {"full", "sift"}.issubset(selected):
        raise EvaluationError("A comparison must include both full and sift arms")
    return selected


def generate(messages: list[dict], *, server_url: str, seed: int) -> dict:
    started = time.perf_counter()
    first_text = None
    text_parts = []
    usage = None
    finish_reason = None
    status_code = None
    request_payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.1,
        "top_p": 0.8,
        "top_k": 20,
        "seed": seed,
        "max_tokens": OUTPUT_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "mcqa_choice",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            },
        },
        "cache_prompt": False,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    try:
        with requests.post(
            server_url.rstrip("/") + "/v1/chat/completions",
            json=request_payload,
            stream=True,
            timeout=(30, 600),
        ) as response:
            status_code = response.status_code
            if status_code != 200:
                return {
                    "http_status": status_code,
                    "normal": False,
                    "failure": "non_200_response",
                    "end_to_end_ms": (time.perf_counter() - started) * 1000,
                }
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    break
                chunk = json.loads(value)
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                for choice in chunk.get("choices", []):
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    visible = delta.get("content")
                    if isinstance(visible, str) and visible:
                        if first_text is None:
                            first_text = time.perf_counter()
                        text_parts.append(visible)
    except (requests.RequestException, json.JSONDecodeError) as error:
        return {
            "http_status": status_code,
            "normal": False,
            "failure": type(error).__name__,
            "end_to_end_ms": (time.perf_counter() - started) * 1000,
        }

    ended = time.perf_counter()
    text = "".join(text_parts)
    ttft = (first_text - started) * 1000 if first_text is not None else None
    elapsed_after_first = ended - first_text if first_text is not None else None
    output_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    return {
        "http_status": status_code,
        "normal": finish_reason == "stop" and first_text is not None,
        "finish_reason": finish_reason,
        "answer": text[:500],
        "choice": extract_choice(text),
        "valid_structured_choice": extract_choice(text) is not None,
        "ttft_ms": ttft,
        "end_to_end_ms": (ended - started) * 1000,
        "output_tokens": output_tokens,
        "client_decode_tokens_per_second": (
            output_tokens / elapsed_after_first
            if type(output_tokens) is int and elapsed_after_first and elapsed_after_first > 0
            else None
        ),
        "usage": usage,
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(manifest_path: Path, dataset_path: Path, output_path: Path,
        tokenizer_url: str, server_url: str, repeats: int, seed: int,
        case_ids: list[str] | None = None,
        arms: list[str] | None = None,
        target_tokens: int = SIFT_TARGET) -> dict:
    if type(target_tokens) is not int or target_tokens <= 0:
        raise ValueError("target_tokens must be a positive integer")
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite evaluation report: {output_path}")
    selected_arms = validate_arms(arms)
    frozen, cases = load_frozen_cases(manifest_path, dataset_path, tokenizer_url)
    if case_ids:
        selected = [case for case in cases if case["frozen"]["id"] in set(case_ids)]
        if len(selected) != len(set(case_ids)):
            raise EvaluationError("Requested case IDs do not match distinct frozen cases")
        cases = selected
    compressor = None
    if "llmlingua2_text_only" in selected_arms:
        try:
            from llmlingua import PromptCompressor
        except ImportError as error:
            raise EvaluationError(
                "Install the optional locked LLMLingua-2 development environment before this evaluation"
            ) from error

    report = {
        "schema_version": 1,
        "status": "in_progress",
        "evaluation": "public LongBench v2 QA screen; external benchmark, not a blind holdout or agent-task acceptance test",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_manifest_sha256": file_sha256(manifest_path),
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "sift_core_sha256": hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model": MODEL,
        "model_context_tokens": MODEL_CONTEXT,
        "output_reserve_tokens": OUTPUT_RESERVE,
        "sift_target_estimated_tokens": target_tokens,
        "exact_tokenizer": tokenizer_url.rstrip("/") + "/v1/chat/completions/input_tokens",
        "prompt_semantics": "LongBench question adapted to historical context plus final user question; all arms get identical system, role sequence, choices and question.",
        "execution": {
            "arms": list(selected_arms),
            "repeats_per_case_arm": repeats,
            "arm_order": "randomized within each case and repeat",
            "random_seed": seed,
            "temperature": 0.1,
            "top_p": 0.8,
            "top_k": 20,
            "max_output_tokens": OUTPUT_TOKENS,
            "response_format": {
                "type": "json_schema",
                "schema": RESPONSE_SCHEMA,
                "strict": True,
            },
            "thinking": False,
            "cache_prompt": False,
            "retries": 0,
            "provider_api_spend": 0,
        },
        "llmlingua2": {
            "model": LLMLINGUA_MODEL,
            "revision": LLMLINGUA_REVISION,
            "target_start_tokens": LLMLINGUA_START_TARGET,
            "scope": "compress historical context only; preserve all message roles and the final question",
        },
        "cases": [],
        "samples": [],
    }
    if case_ids:
        report["selected_case_ids"] = case_ids
    write_report(output_path, report)

    if "llmlingua2_text_only" in selected_arms:
        compressor = PromptCompressor(
            model_name=LLMLINGUA_MODEL,
            model_config={"revision": LLMLINGUA_REVISION},
            use_llmlingua2=True,
            device_map="cpu",
        )
    rng = random.Random(seed)
    for case in cases:
        frozen_case = case["frozen"]
        report["cases"].append({
            "id": frozen_case["id"],
            "domain": frozen_case["domain"],
            "sub_domain": frozen_case["sub_domain"],
            "difficulty": frozen_case["difficulty"],
            "length": frozen_case["length"],
            "answer_key": frozen_case["answer_key"],
            "full_exact_input_tokens": case["full_exact"],
        })
        prompts = {}
        prep = {}
        for arm in selected_arms:
            prompts[arm], prep[arm] = messages_for_arm(
                case, arm, tokenizer_url, compressor, target_tokens,
            )
        for arm in selected_arms:
            if not prep[arm]["fits_arm_limit"]:
                report["samples"].append({
                    "case_id": frozen_case["id"],
                    "arm": arm,
                    "repeat": 0,
                    "normal": False,
                    "correct": False,
                    "preparation": prep[arm],
                    "failure": "prepared_prompt_exceeds_arm_input_limit",
                })
        for repeat in range(1, repeats + 1):
            arm_order = list(selected_arms)
            rng.shuffle(arm_order)
            for arm in arm_order:
                if not prep[arm]["fits_arm_limit"]:
                    continue
                result = generate(prompts[arm], server_url=server_url, seed=seed + repeat)
                result.update({
                    "case_id": frozen_case["id"],
                    "domain": frozen_case["domain"],
                    "arm": arm,
                    "repeat": repeat,
                    "expected": frozen_case["answer_key"],
                    "correct": result.get("normal") is True and result.get("choice") == frozen_case["answer_key"],
                    "preparation": prep[arm],
                })
                report["samples"].append(result)
                write_report(output_path, report)
    report["status"] = "complete"
    write_report(output_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-path", type=Path, default=(
        Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
    ))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tokenizer-url", default="http://127.0.0.1:8088")
    parser.add_argument("--server-url", default="http://127.0.0.1:8088")
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--target", type=int, default=SIFT_TARGET,
                        help="Estimated input-token ceiling for Sift and other compacted arms.")
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--arm", action="append", choices=ARMS,
                        help="Comparison arm; repeat this flag to select arms. Defaults to all arms.")
    args = parser.parse_args()
    report = run(args.manifest, args.dataset_path, args.output,
                 args.tokenizer_url, args.server_url, args.repeats, args.seed,
                 args.case_ids, args.arm, args.target)
    summary = {
        arm: {
            "n": sum(row.get("arm") == arm for row in report["samples"]),
            "correct": sum(row.get("arm") == arm and row.get("correct") is True for row in report["samples"]),
        }
        for arm in report["execution"]["arms"]
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
