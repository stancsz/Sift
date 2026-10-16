"""Run a frozen MiniMax M3 LongBench sample through OpenRouter in parallel."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import threading
import time
from typing import Any

import requests
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import (  # noqa: E402
    MODEL_ID,
    SIFT_TARGETS,
    render_minimax,
)
from sift import compact_messages  # noqa: E402


API_URL = "https://openrouter.ai/api/v1/chat/completions"
OUTPUT_TOKENS = 16
MAX_WORKERS = 4
SAFETY_MARGIN = 128
class EvaluationError(RuntimeError):
    pass


def count_prompt(tokenizer: Tokenizer, messages: list[dict[str, str]]) -> int:
    rendered = render_minimax(messages)
    return len(tokenizer.encode(rendered, add_special_tokens=False).ids)


def load_cases(manifest_path: Path, dataset_path: Path, tokenizer_path: Path, template_path: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["dataset"]["revision"] != DATASET_REVISION or manifest["dataset"]["data_file_sha256"] != DATASET_SHA256:
        raise EvaluationError("Frozen sample does not use the pinned LongBench v2 dataset")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise EvaluationError("Local LongBench v2 file SHA-256 mismatch")
    if file_sha256(tokenizer_path) != manifest["model"]["tokenizer_sha256"]:
        raise EvaluationError("MiniMax tokenizer hash differs from frozen manifest")
    if file_sha256(template_path) != manifest["model"]["chat_template_sha256"]:
        raise EvaluationError("MiniMax chat template hash differs from frozen manifest")
    core_hash = hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest()
    if core_hash != manifest["sift"]["core_sha256"]:
        raise EvaluationError("Sift core changed after sample freeze")
    expected = {case["id"]: case for case in manifest["cases"]}
    rows = {}
    for row in iter_json_array(dataset_path):
        if row["_id"] in expected:
            rows[row["_id"]] = row
            if len(rows) == len(expected):
                break
    if set(rows) != set(expected):
        raise EvaluationError("Frozen LongBench rows are missing")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    prepared = []
    for frozen in manifest["cases"]:
        row = rows[frozen["id"]]
        messages = make_messages(row)
        if row["answer"] != frozen["answer_key"] or prompt_sha256(messages) != frozen["prompt_sha256"]:
            raise EvaluationError(f"Frozen prompt or answer changed: {frozen['id']}")
        actual_count = count_prompt(tokenizer, messages)
        if actual_count != frozen["m3_rendered_prompt_tokens"]:
            raise EvaluationError(f"MiniMax tokenizer count changed: {frozen['id']}")
        prepared.append({"frozen": frozen, "messages": messages, "full_count": actual_count})
    return manifest, tokenizer, prepared


def make_jobs(cases: list[dict], tokenizer: Tokenizer, seed: int, repeat: int) -> list[dict]:
    jobs = []
    for case in cases:
        frozen = case["frozen"]
        case_id = frozen["id"]
        full_count = case["full_count"]
        jobs.append({
            "case_id": case_id,
            "domain": frozen["domain"],
            "expected": frozen["answer_key"],
            "arm": "full",
            "target": None,
            "messages": deepcopy(case["messages"]),
            "estimated_tokens": full_count,
            "selector_audit": None,
            "repeat": repeat,
            "generation_seed": seed + repeat + 1,
        })
        for target in SIFT_TARGETS:
            effective_target = target - SAFETY_MARGIN
            if full_count <= effective_target:
                continue
            result = compact_messages(
                case["messages"], lambda value: count_prompt(tokenizer, value),
                target=effective_target, raw_limit=1_000_000, protocol="openai",
            )
            measured = count_prompt(tokenizer, result.messages)
            if measured > effective_target:
                raise EvaluationError(f"Sift prompt exceeds target for {case_id} at {target}")
            jobs.append({
                "case_id": case_id,
                "domain": frozen["domain"],
                "expected": frozen["answer_key"],
                "arm": "sift",
                "target": target,
                "messages": result.messages,
                "estimated_tokens": measured,
                "selector_audit": result.audit,
                "repeat": repeat,
                "generation_seed": seed + repeat + 1,
            })
    random.Random(seed + repeat).shuffle(jobs)
    return jobs


def parse_choice(text: str) -> str | None:
    choice = text.strip()
    return choice if choice in {"A", "B", "C", "D"} else None


def call_openrouter(job: dict, *, api_key: str, seed: int) -> dict:
    started = time.perf_counter()
    first_content = None
    text_parts: list[str] = []
    usage = None
    finish_reason = None
    provider = None
    status = None
    payload = {
        "model": MODEL_ID,
        "messages": job["messages"],
        "temperature": 0.1,
        "top_p": 0.8,
        "seed": seed,
        "max_tokens": OUTPUT_TOKENS,
        "reasoning": {"enabled": False},
        "stream": True,
        "stream_options": {"include_usage": True},
        "provider": {"sort": "throughput", "allow_fallbacks": True},
    }
    try:
        with requests.post(
            API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            stream=True,
            timeout=(30, 600),
        ) as response:
            status = response.status_code
            if status != 200:
                body = response.text[:2_000]
                return {"http_status": status, "normal": False, "failure": body,
                        "end_to_end_ms": (time.perf_counter() - started) * 1000}
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    break
                chunk = json.loads(value)
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                provider = chunk.get("provider") or provider
                for choice in chunk.get("choices", []):
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    visible = delta.get("content")
                    if isinstance(visible, str) and visible:
                        if first_content is None:
                            first_content = time.perf_counter()
                        text_parts.append(visible)
    except (requests.RequestException, json.JSONDecodeError) as error:
        return {"http_status": status, "normal": False, "failure": type(error).__name__,
                "end_to_end_ms": (time.perf_counter() - started) * 1000}

    ended = time.perf_counter()
    text = "".join(text_parts)
    choice = parse_choice(text)
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    elapsed_after_first = ended - first_content if first_content is not None else None
    return {
        "http_status": status,
        "normal": finish_reason == "stop" and first_content is not None,
        "finish_reason": finish_reason,
        "answer": text[:500],
        "choice": choice,
        "valid_structured_choice": choice is not None,
        "ttft_ms": (first_content - started) * 1000 if first_content is not None else None,
        "end_to_end_ms": (ended - started) * 1000,
        "completion_tokens_per_second": (
            completion_tokens / elapsed_after_first
            if type(completion_tokens) is int and elapsed_after_first and elapsed_after_first > 0 else None
        ),
        "provider": provider,
        "usage": usage,
    }


def run(manifest_path: Path, dataset_path: Path, tokenizer_path: Path,
        template_path: Path, output_path: Path, repeats: int, seed: int, workers: int) -> dict:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite report: {output_path}")
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if repeats != 1:
        raise ValueError("this frozen development screen is preregistered for exactly one repeat")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise EvaluationError("OPENROUTER_API_KEY is required")
    manifest, tokenizer, cases = load_cases(manifest_path, dataset_path, tokenizer_path, template_path)
    jobs = []
    for repeat in range(1, repeats + 1):
        jobs.extend(make_jobs(cases, tokenizer, seed, repeat))
    report = {
        "schema_version": 1,
        "status": "in_progress",
        "evaluation": "public LongBench v2 MiniMax M3 development screen; not a holdout or model-to-model comparison",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": file_sha256(manifest_path),
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "sift_core_sha256": hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest(),
        "model": MODEL_ID,
        "route": "OpenRouter, throughput-sorted provider routing with fallbacks enabled",
        "execution": {
            "arms": ["full", "sift"], "sift_targets": list(SIFT_TARGETS),
            "repeats": repeats, "concurrency": workers,
            "request_order": "seeded shuffle across cases, arms, targets, and repeats",
            "temperature": 0.1, "top_p": 0.8, "reasoning": "disabled",
            "max_output_tokens": OUTPUT_TOKENS, "retries": 0,
            "answer_format": "exactly one option letter; only exact A/B/C/D outputs are scorable",
            "provider_usage_is_authoritative": True,
        },
        "preparation": {
            "tokenizer_count": "MiniMax published tokenizer over published rendered chat template",
            "provider_count_note": "Per-request OpenRouter usage is authoritative; local token counts include a 128-token safety margin for Sift targets.",
        },
        "samples": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_jobs = {
            pool.submit(call_openrouter, job, api_key=api_key, seed=job["generation_seed"]): job
            for job in jobs
        }
        for future in as_completed(future_jobs):
            job = future_jobs[future]
            try:
                result = future.result()
            except Exception as error:  # preserve every failed attempt in the denominator
                result = {"normal": False, "failure": type(error).__name__}
            result.update({
                "case_id": job["case_id"], "domain": job["domain"], "arm": job["arm"],
                "target_tokens": job["target"], "repeat": job["repeat"],
                "expected": job["expected"],
                "correct": result.get("normal") is True and result.get("choice") == job["expected"],
                "local_rendered_prompt_tokens": job["estimated_tokens"],
                "selector_audit": job["selector_audit"],
            })
            with lock:
                report["samples"].append(result)
                output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["status"] = "complete"
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-path", type=Path, default=(Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"))
    parser.add_argument("--tokenizer", type=Path, default=ROOT / "tmp" / "minimax-m3-tokenizer.json")
    parser.add_argument("--template", type=Path, default=ROOT / "tmp" / "minimax-m3-chat-template.jinja")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    result = run(args.manifest, args.dataset_path, args.tokenizer, args.template, args.output,
                 args.repeats, args.seed, args.workers)
    print(json.dumps({"status": result["status"], "samples": len(result["samples"]),
                      "output": str(args.output)}, indent=2))
