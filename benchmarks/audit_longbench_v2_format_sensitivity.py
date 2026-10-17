"""Recompute a narrow output-format sensitivity for a completed LongBench run.

The primary score remains the run's frozen `correct` field. The secondary
sensitivity additionally counts only a full-string parenthesized choice that
matches the recorded gold choice. This script emits aggregate metrics only; it
never copies or prints response text or answer keys.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Any


PAREN_CHOICE = re.compile(r"\(([ABCD])\)")
ARMS = ("full", "sift")


def read_source(path: Path) -> tuple[bytes, str]:
    raw_bytes = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return raw_bytes, hashlib.sha256(raw_bytes).hexdigest()


def analyze(path: Path) -> dict[str, Any]:
    raw_bytes, raw_sha256 = read_source(path)
    source = json.loads(raw_bytes)
    rows = source.get("samples")
    if source.get("status") != "complete" or not isinstance(rows, list):
        raise ValueError("Expected a completed result with a samples array")
    if len(rows) != 600:
        raise ValueError(f"Expected 600 matched responses, got {len(rows)}")

    task_ids = {str(row["case_id"]) for row in rows}
    if len(task_ids) != 100:
        raise ValueError(f"Expected 100 unique tasks, got {len(task_ids)}")

    report: dict[str, Any] = {
        "schema_version": 1,
        "title": "LongBench v2 MiniMax output-format sensitivity audit",
        "status": "secondary_sensitivity_only",
        "source_result": path.as_posix(),
        "source_sha256": raw_sha256,
        "dataset_revision": source.get("dataset_revision"),
        "manifest_sha256": source.get("manifest_sha256"),
        "primary_rule": "Use the frozen per-response correct field; exact A-D answer parser from the original run.",
        "sensitivity_rule": "In addition to primary correctness, count an answer only when the entire stripped answer is (A), (B), (C), or (D) and its letter equals the recorded expected choice.",
        "rows": len(rows),
        "task_count": len(task_ids),
        "arms": {},
        "primary_task_majority_pairs": {},
    }

    majority_by_arm: dict[str, dict[str, bool]] = {}
    task_ids_by_arm: dict[str, set[str]] = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row.get("arm") == arm]
        if len(arm_rows) != 300:
            raise ValueError(f"Expected 300 {arm} responses, got {len(arm_rows)}")
        primary_by_task: dict[str, list[bool]] = defaultdict(list)
        sensitivity_by_task: dict[str, list[bool]] = defaultdict(list)
        formats: Counter[str] = Counter()
        primary_correct = 0
        sensitivity_correct = 0
        truncated = 0

        for row in arm_rows:
            answer = str(row.get("answer") or "").strip()
            expected = str(row.get("expected") or "").strip()
            if re.fullmatch(r"[ABCD]", answer):
                formats["single_letter"] += 1
            elif PAREN_CHOICE.fullmatch(answer):
                formats["parenthesized_letter"] += 1
            elif answer:
                formats["other_nonempty"] += 1
            else:
                formats["empty"] += 1

            primary = bool(row.get("correct"))
            parsed = PAREN_CHOICE.fullmatch(answer)
            secondary = primary or bool(parsed and parsed.group(1) == expected)
            case_id = str(row["case_id"])
            primary_by_task[case_id].append(primary)
            sensitivity_by_task[case_id].append(secondary)
            primary_correct += primary
            sensitivity_correct += secondary
            truncated += row.get("finish_reason") == "length"

        if any(len(values) != 3 for values in primary_by_task.values()):
            raise ValueError(f"{arm} arm does not have three repeats for each task")
        if set(primary_by_task) != task_ids or any(
            {row.get("repeat") for row in arm_rows if str(row["case_id"]) == task} != {1, 2, 3}
            for task in task_ids
        ):
            raise ValueError(f"{arm} arm does not contain the same three repeats for every task")
        primary_majorities = {
            task: sum(values) >= 2 for task, values in primary_by_task.items()
        }
        sensitivity_majorities = {
            task: sum(values) >= 2 for task, values in sensitivity_by_task.items()
        }
        majority_by_arm[arm] = primary_majorities
        task_ids_by_arm[arm] = set(primary_by_task)
        report["arms"][arm] = {
            "responses": len(arm_rows),
            "primary_correct_responses": primary_correct,
            "sensitivity_correct_responses": sensitivity_correct,
            "primary_task_majorities": sum(primary_majorities.values()),
            "sensitivity_task_majorities": sum(sensitivity_majorities.values()),
            "answer_format_counts": dict(sorted(formats.items())),
            "finish_reason_length": truncated,
        }

    if task_ids_by_arm["full"] != task_ids_by_arm["sift"]:
        raise ValueError("Full and Sift arms do not share the same task IDs")

    pairs = Counter()
    for task in task_ids:
        full = majority_by_arm["full"][task]
        sift = majority_by_arm["sift"][task]
        key = "both" if full and sift else "full_only" if full else "sift_only" if sift else "neither"
        pairs[key] += 1
    report["primary_task_majority_pairs"] = dict(sorted(pairs.items()))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "result",
        nargs="?",
        type=Path,
        default=Path("docs/results/longbench-v2-minimax-m3-100-2026-10-16.json.gz"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/evals/longbench-v2-minimax-m3-100-format-sensitivity-2026-10-16.json"),
    )
    args = parser.parse_args()
    report = analyze(args.result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "arms": report["arms"], "pairs": report["primary_task_majority_pairs"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
