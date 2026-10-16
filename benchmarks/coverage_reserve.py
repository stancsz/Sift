"""Replay the public weak-overlap development cases against the current Sift source.

This is a deterministic selector screen, not an agent-task or model-quality
benchmark. It records fixture and source hashes so baseline/candidate reports
can be compared without exposing private traces or calling a provider.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sift import compact_messages  # noqa: E402


FIXTURE = ROOT / "benchmarks" / "coverage_reserve_cases.json"
TARGET = 4_000
TOOL_CYCLES = 9
LINES_PER_RESULT = 90


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def estimate(messages: list[dict[str, Any]]) -> int:
    """Stable serialized-character estimate; not a provider tokenizer."""
    return (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4


def make_messages(case: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": case["task"]}]
    query_words = " ".join(case["task"].replace(".", "").replace(",", "").split())
    for cycle in range(TOOL_CYCLES):
        call_id = f"archive_read_{cycle}"
        messages.append({
            "role": "assistant", "content": None,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": "ReadArchive", "arguments": json.dumps({"batch": cycle})}}],
        })
        lines = [
            f"archive heartbeat batch {cycle} record {line:03d} status normal artifact processed"
            for line in range(LINES_PER_RESULT)
        ]
        if cycle < 4 and cycle != case["fact_cycle"]:
            # Distractors repeat the task wording without containing its answer.
            for offset in range(8, 24):
                lines[offset] = (
                    f"archive index batch {cycle}-{offset}: {query_words}; "
                    "reference only, no value or instruction recorded"
                )
        if cycle == case["fact_cycle"]:
            lines[45] = case["required_span"]
        messages.append({"role": "tool", "tool_call_id": call_id,
                         "content": "\n".join(lines)})
    return messages


def _load_core_ref(ref: str, directory: Path) -> tuple[Callable[..., Any], str]:
    source = subprocess.run(
        ["git", "show", f"{ref}:src/sift/core.py"], cwd=ROOT,
        check=True, capture_output=True,
    ).stdout
    path = directory / "core_reference.py"
    path.write_bytes(source)
    name = "sift_coverage_reference"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load reference selector source")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.compact_messages, hashlib.sha256(source).hexdigest()


def run(core_ref: str | None = None) -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    encoded_cases = _canonical(fixture)
    generated = [make_messages(case) for case in cases]
    encoded_inputs = _canonical(generated)
    core_path = ROOT / "src" / "sift" / "core.py"
    core_hash = hashlib.sha256(core_path.read_bytes()).hexdigest()
    if core_ref:
        with tempfile.TemporaryDirectory(prefix="sift-coverage-core-") as directory:
            compact, core_hash = _load_core_ref(core_ref, Path(directory))
            rows = _evaluate(cases, generated, compact)
    else:
        rows = _evaluate(cases, generated, compact_messages)
    return {
        "schema_version": 1,
        "evaluation": "public synthetic selector development screen; no provider calls",
        "target_estimated_tokens": TARGET,
        "counter": "ceil(len(json.dumps(messages, ensure_ascii=False))/4)",
        "fixture_sha256": hashlib.sha256(encoded_cases).hexdigest(),
        "generated_inputs_sha256": hashlib.sha256(encoded_inputs).hexdigest(),
        "core_sha256": core_hash,
        "core_ref": core_ref,
        "aggregate": {
            "exact_spans": sum(row["span_retained"] for row in rows),
            "required_spans": len(rows),
            "complete_cases": sum(row["complete_case"] for row in rows),
            "cases": len(rows),
            "budget_passes": sum(row["forwarded_estimated_tokens"] <= TARGET for row in rows),
            "protected_task_passes": sum(row["protected_task_exact"] for row in rows),
            "latest_cycle_passes": sum(row["latest_tool_cycle_exact"] for row in rows),
            "immutable_input_passes": sum(row["input_unchanged"] for row in rows),
        },
        "cases": rows,
    }


def _evaluate(cases: list[dict[str, Any]], generated: list[list[dict[str, Any]]],
              compact: Callable[..., Any]) -> list[dict[str, Any]]:
    rows = []
    for case, messages in zip(cases, generated):
        original = deepcopy(messages)
        result = compact(messages, estimate, target=TARGET, protocol="openai")
        span_retained = case["required_span"] in json.dumps(result.messages, ensure_ascii=False)
        rows.append({
            "name": case["name"],
            "raw_estimated_tokens": result.audit["input_tokens"],
            "forwarded_estimated_tokens": result.audit["forwarded_tokens"],
            "selected_excerpts": result.audit["selected_excerpts"],
            "method": result.audit["method"],
            "span_retained": span_retained,
            "complete_case": span_retained,
            "required_spans": 1,
            "protected_task_exact": case["task"] in [
                message.get("content") for message in result.messages
                if message.get("role") == "user" and isinstance(message.get("content"), str)
            ],
            "latest_tool_cycle_exact": result.messages[-2:] == messages[-2:],
            "input_unchanged": messages == original,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--core-ref", help="optional Git ref for a frozen baseline selector")
    args = parser.parse_args()
    report = run(args.core_ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({"core_sha256": report["core_sha256"],
                      "fixture_sha256": report["fixture_sha256"],
                      "aggregate": report["aggregate"]}, indent=2))


if __name__ == "__main__":
    main()
