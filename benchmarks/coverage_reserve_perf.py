"""Compare selector CPU time on a synthetic 1M-token tool-cycle history.

The input is generated locally and never written to the report. This measures
selector process CPU only, not model prefill, cache behavior, or agent quality.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sift import compact_messages as candidate_compact  # noqa: E402


CYCLES = 72
LINES_PER_RESULT = 1_000
TARGET = 24_576


def estimate(messages: list[dict[str, Any]]) -> int:
    return (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4


def make_history() -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{
        "role": "user", "content": "Inspect the build archive and summarize the release status.",
    }]
    for cycle in range(CYCLES):
        call_id = f"perf_{cycle}"
        messages.append({
            "role": "assistant", "content": None,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": "Read", "arguments": json.dumps({"cycle": cycle})}}],
        })
        content = "\n".join(
            f"record {index:04d} status normal artifact processed cycle {cycle}"
            for index in range(LINES_PER_RESULT)
        )
        messages.append({"role": "tool", "tool_call_id": call_id, "content": content})
    return messages


def load_baseline(ref: str, directory: Path) -> tuple[Callable[..., Any], str]:
    source = subprocess.run(
        ["git", "show", f"{ref}:src/sift/core.py"], cwd=ROOT,
        check=True, capture_output=True,
    ).stdout
    path = directory / "core_baseline.py"
    path.write_bytes(source)
    name = "sift_coverage_reserve_baseline"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load baseline selector source")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.compact_messages, hashlib.sha256(source).hexdigest()


def run(baseline_ref: str, repeats: int) -> dict[str, Any]:
    messages = make_history()
    raw_tokens = estimate(messages)
    candidate_source = ROOT / "src" / "sift" / "core.py"
    candidate_hash = hashlib.sha256(candidate_source.read_bytes()).hexdigest()
    baseline_times: list[float] = []
    candidate_times: list[float] = []
    baseline_hash = ""
    with tempfile.TemporaryDirectory(prefix="sift-coverage-perf-") as directory:
        baseline, baseline_hash = load_baseline(baseline_ref, Path(directory))
        implementations = [("baseline", baseline), ("candidate", candidate_compact)]
        for _ in range(repeats):
            for name, compact in implementations:
                started = time.process_time()
                result = compact(messages, estimate, target=TARGET, protocol="openai")
                elapsed = time.process_time() - started
                if result.audit["forwarded_tokens"] > TARGET:
                    raise RuntimeError(f"{name} exceeded the configured budget")
                (baseline_times if name == "baseline" else candidate_times).append(elapsed)
    baseline_median = statistics.median(baseline_times)
    candidate_median = statistics.median(candidate_times)
    return {
        "schema_version": 1,
        "scope": "synthetic selector CPU comparison; no provider calls",
        "baseline_ref": baseline_ref,
        "baseline_core_sha256": baseline_hash,
        "candidate_core_sha256": candidate_hash,
        "raw_estimated_tokens": raw_tokens,
        "target_estimated_tokens": TARGET,
        "cycles": CYCLES,
        "lines_per_tool_result": LINES_PER_RESULT,
        "repeats": repeats,
        "counter": "ceil(len(json.dumps(messages, ensure_ascii=False))/4)",
        "selector_process_cpu_seconds": {
            "baseline": baseline_times,
            "candidate": candidate_times,
            "baseline_median": baseline_median,
            "candidate_median": candidate_median,
            "candidate_change_percent": 100 * (candidate_median / baseline_median - 1),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True,
                        help="Git ref whose src/sift/core.py is the frozen baseline")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats <= 0:
        parser.error("--repeats must be positive")
    report = run(args.baseline_ref, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["selector_process_cpu_seconds"], indent=2))


if __name__ == "__main__":
    main()
