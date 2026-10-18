"""Freeze all remaining full-fit, above-target LongBench v2 QA cases.

This is an evaluation-only extension of the original public sample. It makes
tokenizer requests only; it does not call the model or change Sift.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from prepare_longbench_v2 import (
    DATASET_REVISION,
    DATASET_SHA256,
    FULL_INPUT_LIMIT,
    MAX_CHARS_FOR_FULL_FIT_SCAN,
    MODEL_CONTEXT,
    OUTPUT_RESERVE,
    SIFT_TARGET,
    CONTEXT_PREFIX,
    CONTEXT_SUFFIX,
    QUESTION_SUFFIX,
    SYSTEM_PROMPT,
    exact_prompt_tokens,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)


def freeze_extension(
    dataset_path: Path,
    original_manifest_path: Path,
    tokenizer_url: str,
    output_path: Path,
) -> dict:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen extension: {output_path}")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise ValueError("LongBench v2 data.json SHA-256 did not match the pinned file")
    original = json.loads(original_manifest_path.read_text(encoding="utf-8"))
    if original["dataset"]["revision"] != DATASET_REVISION:
        raise ValueError("Original manifest uses a different LongBench v2 revision")
    if original["dataset"]["data_file_sha256"] != DATASET_SHA256:
        raise ValueError("Original manifest uses a different LongBench v2 data hash")
    excluded_ids = {case["id"] for case in original["cases"]}

    cases = []
    scanned = 0
    skipped_long = 0
    candidates = 0
    for row in iter_json_array(dataset_path):
        scanned += 1
        if len(row["context"]) > MAX_CHARS_FOR_FULL_FIT_SCAN:
            skipped_long += 1
            continue
        messages = make_messages(row)
        count = exact_prompt_tokens(tokenizer_url, messages)
        if count <= FULL_INPUT_LIMIT:
            candidates += 1
        if row["_id"] in excluded_ids or not (SIFT_TARGET < count <= FULL_INPUT_LIMIT):
            continue
        cases.append({
            "id": row["_id"],
            "domain": row["domain"],
            "sub_domain": row["sub_domain"],
            "difficulty": row["difficulty"],
            "length": row["length"],
            "answer_key": row["answer"],
            "context_chars": len(row["context"]),
            "exact_full_prompt_tokens": count,
            "prompt_sha256": prompt_sha256(messages),
        })
    if scanned != 503:
        raise ValueError(f"Expected 503 LongBench v2 rows, observed {scanned}")
    cases.sort(key=lambda case: (case["domain"], case["id"]))
    if not cases:
        raise ValueError("No remaining above-target cases fit the full input limit")

    wrapper = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": CONTEXT_PREFIX + "<CONTEXT>" + CONTEXT_SUFFIX},
        {"role": "assistant", "content": "Ready."},
        {"role": "user", "content": "<QUESTION_AND_CHOICES>" + QUESTION_SUFFIX},
    ]
    report = {
        "schema_version": 1,
        "status": "frozen public benchmark extension; no generations made during preparation",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "data_file_sha256": DATASET_SHA256,
            "dataset_card": "https://huggingface.co/datasets/zai-org/LongBench-v2",
        },
        "extension_of": {
            "manifest": str(original_manifest_path),
            "manifest_sha256": file_sha256(original_manifest_path),
            "excluded_original_case_ids": sorted(excluded_ids),
        },
        "source": {
            "sift_core_sha256": hashlib.sha256(Path("src/sift/core.py").read_bytes()).hexdigest(),
            "model": "qwen3.8-27b, local llama.cpp",
            "tokenizer_endpoint": tokenizer_url.rstrip("/"),
            "model_context_tokens": MODEL_CONTEXT,
            "output_reserve_tokens": OUTPUT_RESERVE,
            "full_input_limit_exact_tokens": FULL_INPUT_LIMIT,
            "sift_target_estimated_tokens": SIFT_TARGET,
            "wrapper_sha256": prompt_sha256(wrapper),
            "wrapper_note": "Same LongBench chat wrapper as the original sample; exact case prompt hashes are stored per case.",
        },
        "selection": {
            "policy": "Include every pinned-dataset row not in the original manifest whose exact full prompt exceeds the Sift target and fits the full-input limit; no manual row exclusions.",
            "scan_rows": scanned,
            "skipped_contexts_over_char_prefilter": skipped_long,
            "full_fit_candidates": candidates,
            "extension_count": len(cases),
            "extension_by_domain": dict(Counter(case["domain"] for case in cases)),
        },
        "execution_protocol": {
            "arms": ["full", "sift", "recency"],
            "repeats_per_case_arm": 3,
            "generation_seed_base": 20261019,
            "randomize_arm_order": True,
            "temperature": 0.1,
            "top_p": 0.8,
            "top_k": 20,
            "max_output_tokens": 16,
            "thinking": False,
            "cache_prompt": False,
            "retries": 0,
            "scoring": "Strict JSON-schema choice; only normal terminal responses with exactly one A/B/C/D choice count correct. Repeats aggregate to one strict-majority task result; ties count incorrect and are retained.",
        },
        "cases": cases,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--original-manifest", type=Path, required=True)
    parser.add_argument("--tokenizer-url", default="http://127.0.0.1:8088")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = freeze_extension(args.dataset, args.original_manifest, args.tokenizer_url, args.output)
    print(json.dumps({"selection": result["selection"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
