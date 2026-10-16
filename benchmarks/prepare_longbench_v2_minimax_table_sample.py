"""Freeze a fresh random sample of remaining LongBench v2 Table QA tasks.

This public development sample is restricted to Table QA cases not present in
the previously published Qwen and MiniMax manifests. It performs no model
generation and refuses to overwrite an existing manifest.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random

from tokenizers import Tokenizer

from prepare_longbench_v2 import (
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import (
    HF_TEMPLATE_URL,
    HF_TOKENIZER_URL,
    MODEL_ID,
    SIFT_TARGETS,
    render_minimax,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
DEFAULT_TOKENIZER = ROOT / "tmp" / "minimax-m3-tokenizer.json"
DEFAULT_TEMPLATE = ROOT / "tmp" / "minimax-m3-chat-template.jinja"
EXCLUDED_MANIFESTS = (
    ROOT / "docs/evals/longbench-v2-qwen-screen-2026-10-16.json",
    ROOT / "docs/evals/longbench-v2-qwen-extension-2026-10-16.json",
    ROOT / "docs/evals/longbench-v2-minimax-m3-sift-screen-2026-10-16.json",
)
SEED = 20261017
SAMPLE_SIZE = 6
MIN_FULL_TOKENS = 24_577
MAX_FULL_TOKENS = 900_000


def prepare(dataset: Path, tokenizer_path: Path, template_path: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite frozen sample: {output}")
    if file_sha256(dataset) != DATASET_SHA256:
        raise ValueError("LongBench v2 data.json SHA-256 differs from the pinned revision")
    for path in (*EXCLUDED_MANIFESTS, tokenizer_path, template_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    excluded: set[str] = set()
    excluded_receipts = []
    for path in EXCLUDED_MANIFESTS:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("dataset", {}).get("revision") != DATASET_REVISION:
            raise ValueError(f"Prior manifest uses a different dataset revision: {path}")
        ids = {case["id"] for case in manifest["cases"]}
        overlap_count = len(excluded.intersection(ids))
        excluded.update(ids)
        excluded_receipts.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": file_sha256(path),
            "case_count": len(ids),
            "overlap_with_prior_manifests": overlap_count,
        })

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    eligible = []
    scanned = 0
    for row in iter_json_array(dataset):
        scanned += 1
        if (row["domain"] != "Long Structured Data Understanding"
                or row["sub_domain"] != "Table QA"
                or row["_id"] in excluded):
            continue
        messages = make_messages(row)
        prompt_tokens = len(tokenizer.encode(
            render_minimax(messages), add_special_tokens=False,
        ).ids)
        if MIN_FULL_TOKENS <= prompt_tokens <= MAX_FULL_TOKENS:
            eligible.append({
                "id": row["_id"],
                "domain": row["domain"],
                "sub_domain": row["sub_domain"],
                "difficulty": row["difficulty"],
                "length": row["length"],
                "answer_key": row["answer"],
                "context_chars": len(row["context"]),
                "m3_rendered_prompt_tokens": prompt_tokens,
                "prompt_sha256": prompt_sha256(messages),
            })
    if scanned != 503:
        raise ValueError(f"Expected 503 dataset rows, observed {scanned}")
    if len(eligible) < SAMPLE_SIZE:
        raise ValueError(f"Expected at least {SAMPLE_SIZE} eligible unused Table QA cases")

    random.Random(SEED).shuffle(eligible)
    cases = sorted(eligible[:SAMPLE_SIZE], key=lambda case: case["id"])
    source_hash = hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest()
    report = {
        "schema_version": 1,
        "status": "frozen public development sample; no generations made during preparation",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "blinding_note": (
            "The dataset is public and the sample author can inspect it; this is not a blind or independently authored holdout. "
            "Case IDs were sampled before reviewing their prompts or any outputs for this selector revision."
        ),
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "split": "train (503 public rows)",
            "data_file_sha256": file_sha256(dataset),
            "license": "apache-2.0",
        },
        "model": {
            "id": MODEL_ID,
            "context_tokens": 1_048_576,
            "tokenizer_source": HF_TOKENIZER_URL,
            "tokenizer_sha256": file_sha256(tokenizer_path),
            "chat_template_source": HF_TEMPLATE_URL,
            "chat_template_sha256": file_sha256(template_path),
            "counting_note": "Counts use the published MiniMax tokenizer and frozen chat renderer with reasoning disabled. Provider-reported counts remain authoritative.",
        },
        "sift": {
            "core_sha256": source_hash,
            "git_commit": "e7e1f4f",
            "targets": list(SIFT_TARGETS),
            "safety_margin_tokens": 128,
        },
        "harness": {
            "preparation_script_sha256": file_sha256(Path(__file__)),
            "runner_path": "benchmarks/run_longbench_v2_minimax.py",
            "runner_sha256": file_sha256(ROOT / "benchmarks/run_longbench_v2_minimax.py"),
        },
        "selection": {
            "seed": SEED,
            "excluded_prior_manifests": excluded_receipts,
            "excluded_case_count": len(excluded),
            "domain": "Long Structured Data Understanding",
            "sub_domain": "Table QA",
            "eligible_full_prompt_tokens": [MIN_FULL_TOKENS, MAX_FULL_TOKENS],
            "eligible_case_count": len(eligible),
            "sample_size": SAMPLE_SIZE,
            "policy": "Uniform deterministic random sample from unused Table QA rows whose full M3-rendered prompt exceeds 24,576 tokens and is at most 900,000 tokens; no manual case substitutions.",
            "selected_by_length": dict(Counter(case["length"] for case in cases)),
        },
        "execution_protocol": {
            "arms": ["full", "sift"],
            "repeats_per_case": 1,
            "runner_seed_argument": 20261026,
            "request_order_seed": 20261027,
            "generation_seed": 20261028,
            "randomize_arm_order": True,
            "temperature": 0.1,
            "top_p": 0.8,
            "reasoning": False,
            "cache_prompt": False,
            "max_output_tokens": 16,
            "retries": 0,
            "provider": "OpenRouter minimax/minimax-m3, throughput sort, fallbacks enabled",
            "scoring": "Only normal terminal output containing exactly one A/B/C/D letter counts correct; all failed, invalid, or missing outcomes remain incorrect.",
        },
        "cases": cases,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "docs/evals/longbench-v2-minimax-m3-table-fresh-2026-10-16.json",
    )
    args = parser.parse_args()
    result = prepare(args.dataset, args.tokenizer, args.template, args.output)
    print(json.dumps({
        "eligible_case_count": result["selection"]["eligible_case_count"],
        "cases": result["cases"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
