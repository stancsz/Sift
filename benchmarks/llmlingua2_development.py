"""Compare Sift with LLMLingua-2 on the public selector development cases.

This is a text-only, local Qwen answer probe, not a held-out agent-task or
competitive-quality benchmark. LLMLingua-2 is an optional benchmark dependency;
it is not part of Sift's runtime requirements.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import random
import sys
import time
from typing import Any
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from coverage_reserve import FIXTURE, make_messages  # noqa: E402
from recency import compact_messages as compact_recency  # noqa: E402
from sift import compact_messages  # noqa: E402
from llmlingua import PromptCompressor  # noqa: E402


SERVER = "http://127.0.0.1:8088"
MODEL = "qwen3.8-27b"
TARGET = 4_096
LLMLINGUA_TARGET = 2_800
MODEL_REVISION = "ebaba9b0e874dadd3003ffcff828e4397e568089"
MODEL_NAME = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"
SYSTEM = (
    "Answer the task using only the supplied archive evidence. "
    "If it is not stated, say you cannot determine it. Be concise."
)


def post_json(url: str, payload: dict[str, Any], timeout: float = 600) -> dict[str, Any]:
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def get_json(url: str, timeout: float = 30) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def exact_tokens(messages: list[dict[str, Any]]) -> int:
    result = post_json(f"{SERVER}/v1/chat/completions/input_tokens",
                       {"messages": messages,
                        "chat_template_kwargs": {"enable_thinking": False}},
                       timeout=120)
    return int(result["input_tokens"])


def make_prompt(task: str, history: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Task: {task}\n\nArchive evidence:\n{history}"},
    ]


def flatten_history(messages: list[dict[str, Any]], task: str) -> str:
    chunks = []
    for index, message in enumerate(messages):
        content = message.get("content")
        if message.get("role") == "user" and content == task:
            continue
        if message.get("role") == "tool" and isinstance(content, str):
            chunks.append(f"[message {index} tool]\n{content}")
        elif message.get("role") == "user" and isinstance(content, str):
            chunks.append(content)
    return "\n\n".join(chunks)


def markers(case_name: str, answer: str) -> bool:
    text = answer.casefold()
    if case_name == "deployment_cadence":
        return ("three rings" in text or "3 rings" in text) and "ledger" in text
    if case_name == "refund_retention":
        return "18 months" in text or "eighteen months" in text
    if case_name == "temperature_adjustment":
        return "c2" in text and "1.7" in text and ("negative" in text or "-1.7" in text)
    if case_name == "international_refund_route":
        return "r4" in text and "daily settlement" in text
    if case_name == "trial_export_path":
        return "archive/clients/{id}/staging" in text and "live profile" in text
    if case_name == "timezone_precedence":
        return "calendar zone" in text and ("operating system" in text or "os default" in text)
    raise ValueError(f"unknown case: {case_name}")


def answer(prompt: list[dict[str, str]]) -> dict[str, Any]:
    response = post_json(f"{SERVER}/v1/chat/completions", {
        "model": MODEL,
        "messages": prompt,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "seed": 20261016,
        "max_tokens": 256,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": False,
    }, timeout=600)
    choice = response["choices"][0]
    return {
        "text": choice["message"].get("content", ""),
        "finish_reason": choice.get("finish_reason"),
        "usage": response.get("usage"),
    }


def summarize_source(label: str, messages: list[dict[str, Any]], task: str) -> str:
    del label
    return flatten_history(messages, task)


def run(output: Path) -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    compressor = PromptCompressor(
        model_name=MODEL_NAME,
        device_map="cpu",
        model_config={"revision": MODEL_REVISION},
        use_llmlingua2=True,
    )
    model_rows = get_json(f"{SERVER}/v1/models").get("data", [])
    local_model = next((row for row in model_rows if row.get("id") == MODEL), {})
    rng = random.Random(20261016)
    rows = []
    total_calls = 0

    def make_report(status: str) -> dict[str, Any]:
        aggregates = {}
        for arm in ("full", "sift", "recency", "llmlingua2_text_only"):
            completed = [row["arms"][arm] for row in rows
                         if row["arms"][arm]["status"] == "completed"]
            aggregates[arm] = {
                "marker_checks_passed": sum(item["accepted"] for item in completed),
                "completed_cases": len(completed),
                "required_spans_retained": sum(item["required_span_retained"] for item in completed),
            }
        return {
            "schema_version": 1,
            "status": status,
            "evaluation": "posthoc public synthetic development QA probe; not held-out or agent-task acceptance",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "model": MODEL,
            "target_qwen_exact_input_tokens": TARGET,
            "sift_core_sha256": hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest(),
            "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "generator_sha256": hashlib.sha256((ROOT / "benchmarks/coverage_reserve.py").read_bytes()).hexdigest(),
            "llmlingua": {
                "package_version": importlib.metadata.version("llmlingua"),
                "model": MODEL_NAME,
                "model_revision": MODEL_REVISION,
                "device": "cpu",
                "token_budget": LLMLINGUA_TARGET,
                "scope": "historical tool text only; flattened into the same QA prompt wrapper",
            },
            "runtime": {
                "python": platform.python_version(),
                "torch": importlib.metadata.version("torch"),
                "transformers": importlib.metadata.version("transformers"),
                "tokenizers": importlib.metadata.version("tokenizers"),
                "tiktoken": importlib.metadata.version("tiktoken"),
                "lock_file": "benchmarks/llmlingua2-development.lock",
                "lock_sha256": hashlib.sha256((ROOT / "benchmarks/llmlingua2-development.lock").read_bytes()).hexdigest(),
                "downstream_model_metadata": local_model.get("meta", {}),
            },
            "execution": {
                "generation_calls": total_calls,
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 20,
                "seed": 20261016,
                "max_output_tokens": 256,
                "chat_template_kwargs": {"enable_thinking": False},
                "provider_api_spend": 0,
                "scoring": "case-specific required-marker checks; no blinded human scoring",
                "prompt_semantics": "text-only archive QA wrapper; not a native-agent protocol test",
            },
            "aggregate": aggregates,
            "cases": rows,
        }

    for case in fixture["cases"]:
        messages = make_messages(case)
        original = deepcopy(messages)
        task = case["task"]
        raw_history = summarize_source("full", messages, task)
        full_prompt = make_prompt(task, raw_history)

        sift_start = time.perf_counter()
        sift_result = compact_messages(
            messages, exact_tokens, target=TARGET, raw_limit=1_000_000,
            protocol="openai",
        )
        sift_wall = time.perf_counter() - sift_start
        sift_history = summarize_source("sift", sift_result.messages, task)
        sift_prompt = make_prompt(task, sift_history)

        recent_start = time.perf_counter()
        recency_result = compact_recency(
            messages, exact_tokens, target=TARGET, raw_limit=1_000_000,
            protocol="openai",
        )
        recency_wall = time.perf_counter() - recent_start
        recent_history = summarize_source("recency", recency_result.messages, task)
        recency_prompt = make_prompt(task, recent_history)

        contexts = [message["content"] for message in messages
                    if message.get("role") == "tool" and isinstance(message.get("content"), str)]
        lingua_start = time.perf_counter()
        lingua_result = compressor.compress_prompt(
            context=contexts,
            question=task,
            target_token=LLMLINGUA_TARGET,
            concate_question=False,
        )
        lingua_wall = time.perf_counter() - lingua_start
        lingua_history = lingua_result["compressed_prompt"]
        lingua_prompt = make_prompt(task, lingua_history)

        prompts = {
            "full": full_prompt,
            "sift": sift_prompt,
            "recency": recency_prompt,
            "llmlingua2_text_only": lingua_prompt,
        }
        arm_order = list(prompts)
        rng.shuffle(arm_order)
        arm_rows = {}
        for arm in arm_order:
            prompt = prompts[arm]
            input_tokens = exact_tokens(prompt)
            arm_limit = 28_672 if arm == "full" else TARGET
            if input_tokens > arm_limit:
                arm_rows[arm] = {
                    "accepted": False,
                    "status": "over_target_no_inference",
                    "exact_input_tokens": input_tokens,
                    "limit": arm_limit,
                }
                continue
            result = answer(prompt)
            total_calls += 1
            arm_rows[arm] = {
                "accepted": markers(case["name"], result["text"]),
                "status": "completed",
                "exact_input_tokens": input_tokens,
                "required_span_retained": case["required_span"] in prompt[-1]["content"],
                "answer": result["text"],
                "finish_reason": result["finish_reason"],
                "usage": result["usage"],
            }

        if messages != original:
            raise AssertionError("selector mutated the source case")
        rows.append({
            "case": case["name"],
            "raw_protocol_input_exact_tokens": exact_tokens(messages),
            "arm_order": arm_order,
            "sift_selection_wall_seconds": sift_wall,
            "recency_selection_wall_seconds": recency_wall,
            "llmlingua2_compression_wall_seconds": lingua_wall,
            "llmlingua2_reported_tokens": lingua_result.get("compressed_tokens"),
            "arms": arm_rows,
        })
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(make_report("in_progress"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    result = make_report("complete")
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/results/llmlingua2-development-2026-10-16.json"
    report = run(destination)
    print(json.dumps({"output": str(destination), "aggregate": report["aggregate"]}, indent=2))
