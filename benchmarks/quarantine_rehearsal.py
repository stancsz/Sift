"""Run a synthetic-only, network-disabled aggregate-output quarantine rehearsal.

No benchmark, model, provider, or host task data is loaded. Only the explicitly
allowlisted aggregate file is mounted back into the host.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parent
CONTEXT = ROOT / "quarantine_rehearsal"
PRIVATE_MARKERS = (
    "PRIVATE_TASK_ID_ALPHA",
    "PRIVATE_TASK_ID_BRAVO",
    "PRIVATE_TASK_OUTPUT_SENTINEL",
    "PRIVATE_ANSWER_KEY_SENTINEL",
    "PRIVATE_STDOUT_SENTINEL",
    "PRIVATE_STDERR_SENTINEL",
    "PRIVATE_REPORT_SENTINEL",
)
EXPECTED_KEYS = {"schema_version", "benchmark", "tasks_completed", "arms"}


def json_exact_match(actual, expected) -> bool:
    """Compare JSON shapes and values without Python's bool/int equivalence."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            json_exact_match(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            json_exact_match(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def docker(args: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout,
        check=False, encoding="utf-8", errors="replace",
    )


def main() -> int:
    if not shutil.which("docker"):
        print(json.dumps({"passed": False, "reason": "docker_not_found"}))
        return 2
    if not (CONTEXT / "Dockerfile").is_file() or not (CONTEXT / "runner.py").is_file():
        print(json.dumps({"passed": False, "reason": "rehearsal_context_incomplete"}))
        return 2

    tag = f"sift-quarantine-rehearsal:{uuid.uuid4().hex}"
    build = docker(["build", "--pull=false", "--tag", tag, str(CONTEXT)])
    if build.returncode != 0:
        print(json.dumps({"passed": False, "reason": "container_build_failed",
                          "exit_code": build.returncode}))
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="sift-quarantine-export-") as temporary:
            export = Path(temporary) / "export"
            export.mkdir()
            # Only /export is shared with the host. Task data, IDs, answer keys,
            # per-task reports, stdout, and stderr live in a private tmpfs.
            mount_source = str(export.resolve())
            mount = f"type=bind,source={mount_source},target=/export"
            run = docker([
                "run", "--rm", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "32", "--memory", "128m", "--cpus", "1",
                "--tmpfs", "/private:rw,noexec,nosuid,nodev,size=16m",
                "--mount", mount, tag,
            ], timeout=30)
            stdout, stderr = run.stdout, run.stderr
            if run.returncode != 0:
                print(json.dumps({"passed": False, "reason": "container_run_failed",
                                  "exit_code": run.returncode}))
                return 2
            if stdout != "quarantine rehearsal complete\n" or stderr:
                print(json.dumps({"passed": False, "reason": "unexpected_container_output"}))
                return 1

            exported = sorted(path.name for path in export.iterdir())
            if exported != ["aggregate.json"]:
                print(json.dumps({"passed": False, "reason": "unexpected_export_files",
                                  "file_count": len(exported)}))
                return 1
            raw = (export / "aggregate.json").read_text(encoding="utf-8")
            if any(marker in raw or marker in stdout or marker in stderr for marker in PRIVATE_MARKERS):
                print(json.dumps({"passed": False, "reason": "private_marker_leaked"}))
                return 1
            report = json.loads(raw)
            if set(report) != EXPECTED_KEYS:
                print(json.dumps({"passed": False, "reason": "aggregate_schema_mismatch"}))
                return 1
            expected_report = {
                "schema_version": 1,
                "benchmark": "synthetic-quarantine-rehearsal",
                "tasks_completed": 2,
                "arms": [
                    {"name": "full", "task_count": 2, "accepted_count": 1, "input_tokens": 2800},
                    {"name": "sift", "task_count": 2, "accepted_count": 2, "input_tokens": 1600},
                ],
            }
            if not json_exact_match(report, expected_report):
                print(json.dumps({"passed": False, "reason": "aggregate_values_mismatch"}))
                return 1
            cleanup = docker(["image", "rm", "--force", tag], timeout=30)
            if cleanup.returncode != 0 or docker(["image", "inspect", tag]).returncode == 0:
                print(json.dumps({"passed": False, "reason": "container_image_cleanup_failed"}))
                return 2
            print(json.dumps({
                "passed": True,
                "mode": "synthetic_only_no_inference",
                "container_network": "none",
                "private_scratch": "ephemeral_tmpfs",
                "host_export_allowlist": ["aggregate.json"],
                "private_markers_found_in_export_or_logs": 0,
                "container_image_removed": True,
                "aggregate_task_count": report["tasks_completed"],
                "arms": [arm["name"] for arm in report["arms"]],
            }, sort_keys=True))
            return 0
    finally:
        docker(["image", "rm", "--force", tag], timeout=30)


if __name__ == "__main__":
    raise SystemExit(main())
