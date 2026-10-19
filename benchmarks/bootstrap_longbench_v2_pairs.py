#!/usr/bin/env python3
"""Question-level paired bootstrap for the sanitized LongBench v2 aggregate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(
    "docs/results/longbench-v2-minimax-m3-fullsuite-paired-aggregate-2026-10-17.json"
)
DEFAULT_TASK_MAJORITY_INPUT = Path("docs/results/longbench-v2-minimax-600-2026-10-17.json")


def percentile(sorted_values: list[float], probability: float) -> float:
    """Linear-interpolated percentile, matching the common type-7 definition."""
    position = (len(sorted_values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def load_rows(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    rows = data.get("paired_rows")
    if data.get("status") != "incomplete_checkpoint" or not isinstance(rows, list) or not rows:
        raise ValueError("Expected an incomplete-checkpoint aggregate with paired_rows")
    summary = data["paired_summary"]
    cells = data["paired_correctness_cells"]
    expected = {
        "both_correct": 0,
        "full_only_correct": 0,
        "sift_only_correct": 0,
        "neither_correct": 0,
    }
    for row in rows:
        full = row["full"]
        sift = row["sift"]
        if not isinstance(full["correct"], bool) or not isinstance(sift["correct"], bool):
            raise ValueError("Correctness fields must be boolean")
        if any(not isinstance(arm["prompt_tokens"], int) or arm["prompt_tokens"] < 0 for arm in (full, sift)):
            raise ValueError("Prompt token counts must be nonnegative integers")
        if full["correct"] and sift["correct"]:
            cell = "both_correct"
        elif full["correct"]:
            cell = "full_only_correct"
        elif sift["correct"]:
            cell = "sift_only_correct"
        else:
            cell = "neither_correct"
        expected[cell] += 1
    if expected != cells:
        raise ValueError("Paired rows do not match the aggregate correctness cells")
    for arm in ("full", "sift"):
        if sum(row[arm]["correct"] for row in rows) != summary[arm]["correct"]:
            raise ValueError(f"Paired rows do not match the {arm} correct total")
        if sum(row[arm]["prompt_tokens"] for row in rows) != summary[arm]["prompt_tokens"]:
            raise ValueError(f"Paired rows do not match the {arm} prompt-token total")
    return data, rows, hashlib.sha256(raw).hexdigest()


def analyze(data: dict[str, Any], rows: list[dict[str, Any]], source_sha256: str,
            replicates: int = 20_000, seed: int = 20261018) -> dict[str, Any]:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    rng = random.Random(seed)
    n = len(rows)
    accuracy_deltas: list[float] = []
    token_reductions: list[float] = []
    for _ in range(replicates):
        full_correct = sift_correct = full_tokens = sift_tokens = 0
        for _ in range(n):
            row = rows[rng.randrange(n)]
            full_correct += row["full"]["correct"]
            sift_correct += row["sift"]["correct"]
            full_tokens += row["full"]["prompt_tokens"]
            sift_tokens += row["sift"]["prompt_tokens"]
        accuracy_deltas.append(100 * (sift_correct - full_correct) / n)
        token_reductions.append(100 * (1 - sift_tokens / full_tokens) if full_tokens else 0.0)
    accuracy_deltas.sort()
    token_reductions.sort()
    full = data["paired_summary"]["full"]
    sift = data["paired_summary"]["sift"]
    return {
        "schema_version": 1,
        "study": data["study"],
        "evidence_class": "exposed_development_sample",
        "source_aggregate_sha256": source_sha256,
        "paired_questions": n,
        "bootstrap": {"method": "paired question-level percentile bootstrap", "replicates": replicates, "seed": seed},
        "accuracy_delta_sift_minus_full_percentage_points": round(
            100 * (sift["accuracy"] - full["accuracy"]), 4
        ),
        "accuracy_delta_95_percentile_interval_percentage_points": [
            round(percentile(accuracy_deltas, 0.025), 4),
            round(percentile(accuracy_deltas, 0.975), 4),
        ],
        "prompt_token_reduction_percent": round(
            100 * (1 - sift["prompt_tokens"] / full["prompt_tokens"]), 4
        ),
        "prompt_token_reduction_95_percentile_interval_percent": [
            round(percentile(token_reductions, 0.025), 4),
            round(percentile(token_reductions, 0.975), 4),
        ],
        "interpretation_limit": (
            "Intervals describe resampling variability conditional on both arms being scoreable "
            "for these 446 exposed questions; they do not cover unscoreable or unresolved slots, "
            "and do not establish holdout performance, parity, non-inferiority, or generalization."
        ),
    }


def analyze_task_majorities(data: dict[str, Any], source_sha256: str,
                            replicates: int = 20_000, seed: int = 20261018) -> dict[str, Any]:
    """Bootstrap paired task-majority cells, keeping the question as the unit."""
    cells = data["scores"]["paired_task_majorities"]
    labels = ("both_correct", "full_only", "sift_only", "neither_correct")
    counts = [cells[label] for label in labels]
    n = sum(counts)
    expected_n = data["schedule"]["distinct_questions"]
    if n != expected_n or n < 1:
        raise ValueError("Task-majority cells must cover every scheduled question")
    if data["scores"]["full_context"]["tasks_with_scorable_responses"] != n:
        raise ValueError("Full task-majority denominator does not cover every question")
    if data["scores"]["sift"]["tasks_with_scorable_responses"] != n:
        raise ValueError("Sift task-majority denominator does not cover every question")
    if replicates < 1:
        raise ValueError("replicates must be positive")

    full_only, sift_only = cells["full_only"], cells["sift_only"]
    differences: list[float] = []
    rng = random.Random(seed)
    for _ in range(replicates):
        sample = rng.choices(labels, weights=counts, k=n)
        differences.append(100 * (sample.count("sift_only") - sample.count("full_only")) / n)
    differences.sort()
    discordant = full_only + sift_only
    tail = sum(math.comb(discordant, i) for i in range(min(full_only, sift_only) + 1)) / (2**discordant)
    exact_mcnemar_p = min(1.0, 2 * tail)
    full_correct = cells["both_correct"] + full_only
    sift_correct = cells["both_correct"] + sift_only
    return {
        "paired_questions": n,
        "source_aggregate_sha256": source_sha256,
        "bootstrap": {"method": "paired task-majority percentile bootstrap", "replicates": replicates, "seed": seed},
        "full_task_majorities_correct": full_correct,
        "sift_task_majorities_correct": sift_correct,
        "task_majority_delta_sift_minus_full_percentage_points": round(100 * (sift_correct - full_correct) / n, 4),
        "task_majority_delta_95_percentile_interval_percentage_points": [
            round(percentile(differences, 0.025), 4),
            round(percentile(differences, 0.975), 4),
        ],
        "exact_mcnemar_two_sided_p_descriptive": round(exact_mcnemar_p, 6),
        "interpretation_limit": (
            "One unit is a paired question-level majority, not a response. The exposed selected "
            "cohort's interval describes task-sampling uncertainty and does not establish holdout "
            "performance, parity, non-inferiority, or generalization."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aggregate", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--task-majority-aggregate", type=Path, default=DEFAULT_TASK_MAJORITY_INPUT)
    parser.add_argument("--replicates", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=20261018)
    args = parser.parse_args()
    data, rows, source_sha256 = load_rows(args.aggregate)
    majority_raw = args.task_majority_aggregate.read_bytes()
    majority_data = json.loads(majority_raw)
    output = {
        "schema_version": 1,
        "matched_scoreable_pairs": analyze(data, rows, source_sha256, args.replicates, args.seed),
        "three_repeat_task_majorities": analyze_task_majorities(
            majority_data, hashlib.sha256(majority_raw).hexdigest(), args.replicates, args.seed
        ),
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
