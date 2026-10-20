"""Synthetic-only payload for the aggregate quarantine boundary rehearsal."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile


PRIVATE_MARKERS = (
    "PRIVATE_TASK_ID_ALPHA",
    "PRIVATE_TASK_ID_BRAVO",
    "PRIVATE_TASK_OUTPUT_SENTINEL",
    "PRIVATE_ANSWER_KEY_SENTINEL",
    "PRIVATE_STDOUT_SENTINEL",
    "PRIVATE_STDERR_SENTINEL",
    "PRIVATE_REPORT_SENTINEL",
)
EXPORT_KEYS = {"schema_version", "benchmark", "tasks_completed", "arms"}


def main() -> int:
    private = Path("/private")
    export = Path("/export")
    if not private.is_dir() or not export.is_dir():
        return 20
    if any(export.iterdir()):
        return 21

    # These are synthetic fixtures generated only inside the container. The
    # host receives no task IDs, outputs, answer keys, or runner logs.
    tasks = [
        {"task_id": "PRIVATE_TASK_ID_ALPHA", "full": True, "sift": True,
         "full_tokens": 1200, "sift_tokens": 700},
        {"task_id": "PRIVATE_TASK_ID_BRAVO", "full": False, "sift": True,
         "full_tokens": 1600, "sift_tokens": 900},
    ]
    raw_report = {
        "individual": {
            row["task_id"]: {
                "full_pass": row["full"], "sift_pass": row["sift"],
                "answer_key": "PRIVATE_ANSWER_KEY_SENTINEL",
                "output": "PRIVATE_TASK_OUTPUT_SENTINEL",
            }
            for row in tasks
        },
        "private_note": "PRIVATE_REPORT_SENTINEL",
    }
    (private / "task-workspace").mkdir(parents=True)
    (private / "task-workspace" / "task.md").write_text(
        "PRIVATE_TASK_ID_ALPHA PRIVATE_TASK_OUTPUT_SENTINEL", encoding="utf-8")
    (private / "task-workspace" / "answer-key.txt").write_text(
        "PRIVATE_ANSWER_KEY_SENTINEL", encoding="utf-8")
    (private / "task-workspace" / "runner.stdout").write_text(
        "PRIVATE_STDOUT_SENTINEL", encoding="utf-8")
    (private / "task-workspace" / "runner.stderr").write_text(
        "PRIVATE_STDERR_SENTINEL", encoding="utf-8")
    (private / "task-report.json").write_text(
        json.dumps(raw_report), encoding="utf-8")

    result = {
        "schema_version": 1,
        "benchmark": "synthetic-quarantine-rehearsal",
        "tasks_completed": len(tasks),
        "arms": [
            {
                "name": arm,
                "task_count": len(tasks),
                "accepted_count": sum(bool(row[arm]) for row in tasks),
                "input_tokens": sum(row[f"{arm}_tokens"] for row in tasks),
            }
            for arm in ("full", "sift")
        ],
    }
    if set(result) != EXPORT_KEYS:
        return 22
    serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if any(marker in serialized for marker in PRIVATE_MARKERS):
        return 23

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=export, prefix=".aggregate-", delete=False
    ) as output:
        temporary = Path(output.name)
        output.write(serialized + "\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(export / "aggregate.json")
    print("quarantine rehearsal complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
