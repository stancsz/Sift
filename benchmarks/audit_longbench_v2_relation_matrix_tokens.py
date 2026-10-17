"""Measure the v3 complete-record matrix on the six frozen relation cases.

This offline audit measures rendered M3 prompt size only. It neither scores
answers nor makes a quality claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from prepare_longbench_v2 import file_sha256, iter_json_array  # noqa: E402
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from relation_matrix_candidate import matrix_messages  # noqa: E402

CASE_IDS = (
    "672494e5bb02136c067d7697",
    "67249705bb02136c067d76d1",
    "6724c1d4bb02136c067d77ec",
    "67285e1dbb02136c067d901b",
    "67286036bb02136c067d9092",
    "6724c4aabb02136c067d78a6",
)
V2_RESULT = ROOT / "docs/results/longbench-v2-minimax-relation-stage1-v2-2026-10-17.json"
DEFAULT_DATASET = (
    Path.home() / ".cache/sift-longbench-v2/2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9/data.json"
)
DEFAULT_TOKENIZER = ROOT / "tmp/minimax-m3-tokenizer.json"
DEFAULT_OUTPUT = ROOT / "docs/evals/longbench-v2-minimax-relation-matrix-offline-2026-10-17.json"
EXPECTED_DATASET_SHA256 = "15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2"
EXPECTED_TOKENIZER_SHA256 = "bb1f1626cf01448f1e3b6036d0a061ffc66c91d9046aada14ea23a5441b5ad6e"


def audit(dataset_path: Path, tokenizer_path: Path, output_path: Path) -> dict:
    dataset_sha = file_sha256(dataset_path)
    tokenizer_sha = file_sha256(tokenizer_path)
    if dataset_sha != EXPECTED_DATASET_SHA256:
        raise ValueError("LongBench dataset SHA-256 differs from the frozen revision")
    if tokenizer_sha != EXPECTED_TOKENIZER_SHA256:
        raise ValueError("MiniMax tokenizer SHA-256 differs from the frozen tokenizer")
    historical = json.loads(V2_RESULT.read_text(encoding="utf-8"))
    dataset = {
        row["_id"]: row for row in iter_json_array(dataset_path)
        if row.get("_id") in CASE_IDS
    }
    if set(dataset) != set(CASE_IDS):
        raise ValueError("Frozen LongBench rows do not cover all six relation-screen IDs")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    samples = historical.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Stopped v2 result has no samples array")

    rows = []
    for case_id in CASE_IDS:
        prior = next((row for row in samples if row.get("case_id") == case_id
                      and row.get("repeat") == 1
                      and row.get("arm") == "sift_relation_followup"), None)
        if not isinstance(prior, dict):
            raise ValueError(f"Missing stopped-v2 candidate prompt for {case_id}")
        messages = prior.get("request", {}).get("messages")
        choices = {letter: dataset[case_id][f"choice_{letter}"] for letter in "ABCD"}
        if not isinstance(messages, list):
            raise ValueError(f"Missing original request messages for {case_id}")
        matrix, matrix_audit = matrix_messages(messages, choices)
        original_tokens = len(tokenizer.encode(
            render_minimax(messages), add_special_tokens=False
        ).ids)
        matrix_tokens = len(tokenizer.encode(
            render_minimax(matrix), add_special_tokens=False
        ).ids)
        rows.append({
            "case_id": case_id,
            "source_v2_repeat": 1,
            "original_m3_prompt_tokens": original_tokens,
            "matrix_m3_prompt_tokens": matrix_tokens,
            "token_delta": matrix_tokens - original_tokens,
            "matrix_audit": matrix_audit,
        })

    original_total = sum(row["original_m3_prompt_tokens"] for row in rows)
    matrix_total = sum(row["matrix_m3_prompt_tokens"] for row in rows)
    report = {
        "schema_version": 1,
        "title": "LongBench v2 option-aligned complete-entity matrix offline size audit",
        "status": "complete_offline_prompt_size_only",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Six frozen candidate prompts from the stopped v2 diagnostic; not an answer-quality result or LongBench aggregate.",
        "method": "Replace only the relation-candidate context with a deterministic option-first JSONL matrix. Each selected entity record is serialized exactly once; records are complete, supporting selected records are retained, and all non-context messages remain byte-for-byte equivalent as parsed JSON objects.",
        "source_hashes": {
            "v2_diagnostic_sha256": file_sha256(V2_RESULT),
            "dataset_sha256": dataset_sha,
            "tokenizer_sha256": tokenizer_sha,
            "matrix_module_sha256": file_sha256(ROOT / "benchmarks/relation_matrix_candidate.py"),
            "renderer_sha256": file_sha256(ROOT / "benchmarks/prepare_longbench_v2_minimax.py"),
        },
        "per_case": rows,
        "totals": {
            "case_count": len(rows),
            "original_m3_prompt_tokens": original_total,
            "matrix_m3_prompt_tokens": matrix_total,
            "token_delta": matrix_total - original_total,
            "reduction_percent": round((original_total - matrix_total) / original_total * 100, 4),
        },
        "limitations": [
            "This compares prompt representation only; it does not measure answer accuracy, inference cost, or time.",
            "The six tasks were selected as relation-closure successes and have already informed matrix development; this is exploratory development evidence, not a holdout.",
            "Complete entity fields are preserved, so this audit does not validate removing any fields or relations.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(audit(args.dataset, args.tokenizer, args.output)["totals"], indent=2))
