"""Score the frozen historical Full/default-Sift rows for candidate IDs only."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRACE_DEFAULT = ROOT / "docs/evals/longbench-v2-candidate-trace-metadata-audit-2026-10-18.json"
RUN_DEFAULT = ROOT / "docs/results/longbench-v2-minimax-m3-100-2026-10-16.json"
OUTPUT_DEFAULT = ROOT / "docs/evals/longbench-v2-candidate-subset-retrospective-2026-10-17.json"
BOOTSTRAP_SAMPLES = 20_000
BOOTSTRAP_SEED = 20261029


class AnalysisError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def analyze(trace: dict[str, Any], run: dict[str, Any], run_sha256: str,
            trace_sha256: str, generator_sha256: str) -> dict[str, Any]:
    sources = trace.get("sources")
    if not isinstance(sources, list):
        raise AnalysisError("trace has no source list")
    source = next((row for row in sources if isinstance(row, dict)
                   and row.get("source") == "docs/results/longbench-v2-minimax-m3-100-2026-10-16.json"), None)
    if source is None or source.get("sha256") != run_sha256:
        raise AnalysisError("run result does not match the trace audit's frozen source hash")
    per_id = trace.get("per_id")
    if not isinstance(per_id, list):
        raise AnalysisError("trace has no per-task metadata")
    selected_ids = sorted(
        row["case_id"] for row in per_id
        if isinstance(row, dict)
        and row.get("historical_full_default_matched_repeats") == ["1", "2", "3"]
    )
    if len(selected_ids) != 14 or len(set(selected_ids)) != 14:
        raise AnalysisError(f"expected 14 frozen historical-pair IDs, found {len(selected_ids)}")

    samples = run.get("samples")
    if not isinstance(samples, list):
        raise AnalysisError("run has no samples")
    selected = [row for row in samples if isinstance(row, dict)
                and row.get("case_id") in set(selected_ids)]
    if len(selected) != 84:
        raise AnalysisError(f"expected 84 selected historical responses, found {len(selected)}")

    by_task: dict[str, dict[str, dict[int, dict[str, Any]]]] = {
        case_id: {arm: {} for arm in ("full", "sift")} for case_id in selected_ids
    }
    for row in selected:
        case_id, arm, repeat = row.get("case_id"), row.get("arm"), row.get("repeat")
        if arm not in ("full", "sift") or type(repeat) is not int or repeat not in (1, 2, 3):
            raise AnalysisError("selected response has an invalid arm or repeat")
        if row.get("http_status") != 200 or row.get("model") != "minimax/minimax-m3":
            raise AnalysisError(f"non-200 or unexpected model for a selected response")
        if str(row.get("provider", "")).casefold() != "minimax":
            raise AnalysisError("selected response is not from the pinned MiniMax provider")
        if row.get("allow_fallbacks") is True:
            raise AnalysisError("fallback-enabled response in selected result")
        normal, choice, expected = row.get("normal"), row.get("choice"), row.get("expected")
        valid_choice = choice in {"A", "B", "C", "D"}
        scored_correct = normal is True and valid_choice and choice == expected
        if row.get("correct") is not scored_correct:
            raise AnalysisError("stored correctness flag disagrees with the frozen exact-choice rule")
        usage = row.get("usage")
        if not isinstance(usage, dict):
            raise AnalysisError("selected response has no usage receipt")
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        prompt_details = usage.get("prompt_tokens_details")
        cost_details = usage.get("cost_details")
        if (type(prompt_tokens) is not int or type(completion_tokens) is not int
                or not isinstance(prompt_details, dict) or not isinstance(cost_details, dict)):
            raise AnalysisError("selected response has incomplete usage metadata")
        if (type(prompt_details.get("cached_tokens")) is not int
                or not isinstance(cost_details.get("upstream_inference_cost"), (int, float))):
            raise AnalysisError("selected response has incomplete cache/cost metadata")
        task_arms = by_task[case_id]
        if repeat in task_arms[arm]:
            raise AnalysisError("duplicate selected task/arm/repeat response")
        task_arms[arm][repeat] = row

    for case_id, arms in by_task.items():
        if any(set(arms[arm]) != {1, 2, 3} for arm in ("full", "sift")):
            raise AnalysisError(f"incomplete Full/default pair for task {case_id}")
        for repeat in (1, 2, 3):
            full, sift = arms["full"][repeat], arms["sift"][repeat]
            if full.get("expected") != sift.get("expected"):
                raise AnalysisError(f"paired answer key differs for task {case_id}")
            if full.get("generation_seed") != sift.get("generation_seed"):
                raise AnalysisError(f"paired generation seed differs for task {case_id}")

    arm_summary: dict[str, Any] = {}
    task_majorities: dict[str, dict[str, bool]] = {arm: {} for arm in ("full", "sift")}
    for arm in ("full", "sift"):
        rows = [by_task[case_id][arm][repeat]
                for case_id in selected_ids for repeat in (1, 2, 3)]
        correct = sum(row.get("correct") is True for row in rows)
        for case_id in selected_ids:
            task_majorities[arm][case_id] = sum(
                by_task[case_id][arm][repeat].get("correct") is True
                for repeat in (1, 2, 3)
            ) >= 2
        prompt_tokens = sum(row["usage"]["prompt_tokens"] for row in rows)
        cached_tokens = sum(row["usage"]["prompt_tokens_details"]["cached_tokens"] for row in rows)
        cost = sum(float(row["usage"]["cost_details"]["upstream_inference_cost"])
                   for row in rows)
        arm_summary[arm] = {
            "exact_correct": correct,
            "responses": len(rows),
            "exact_accuracy": correct / len(rows),
            "task_majorities_correct": sum(task_majorities[arm].values()),
            "tasks": len(selected_ids),
            "provider_prompt_tokens": prompt_tokens,
            "cached_prompt_tokens": cached_tokens,
            "cached_prompt_share": cached_tokens / prompt_tokens if prompt_tokens else None,
            "upstream_reported_cost_usd": round(cost, 8),
        }

    paired = {"both_correct": 0, "full_only": 0, "sift_only": 0, "neither": 0}
    differences: list[int] = []
    for case_id in selected_ids:
        full_ok = task_majorities["full"][case_id]
        sift_ok = task_majorities["sift"][case_id]
        if full_ok and sift_ok:
            paired["both_correct"] += 1
        elif full_ok:
            paired["full_only"] += 1
        elif sift_ok:
            paired["sift_only"] += 1
        else:
            paired["neither"] += 1
        differences.append(int(sift_ok) - int(full_ok))

    rng = random.Random(BOOTSTRAP_SEED)
    draws = [sum(differences[rng.randrange(len(differences))]
                 for _ in differences) / len(differences)
             for _ in range(BOOTSTRAP_SAMPLES)]
    difference = statistics.fmean(differences)
    paired.update({
        "sift_minus_full_task_majority_difference": difference,
        "task_cluster_bootstrap_95_percent_interval": [
            _percentile(draws, 0.025), _percentile(draws, 0.975),
        ],
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
    })
    full_tokens = arm_summary["full"]["provider_prompt_tokens"]
    sift_tokens = arm_summary["sift"]["provider_prompt_tokens"]
    full_cost = arm_summary["full"]["upstream_reported_cost_usd"]
    sift_cost = arm_summary["sift"]["upstream_reported_cost_usd"]
    return {
        "schema_version": 1,
        "status": "complete_retrospective_subset_analysis",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "14-task post-census retrospective subset of the existing 100-task Full/default run; not a candidate-arm evaluation, holdout, or full-suite result",
        "additional_model_requests_made": False,
        "source_run": "docs/results/longbench-v2-minimax-m3-100-2026-10-16.json",
        "source_run_sha256": run_sha256,
        "source_trace_audit": "docs/evals/longbench-v2-candidate-trace-metadata-audit-2026-10-18.json",
        "source_trace_sha256": trace_sha256,
        "selected_task_count": len(selected_ids),
        "selected_task_ids_sha256": hashlib.sha256(
            ("\n".join(selected_ids) + "\n").encode("utf-8")
        ).hexdigest(),
        "repeats_per_task_arm": 3,
        "arms": arm_summary,
        "paired_task_majority": paired,
        "descriptive_differences": {
            "provider_prompt_token_reduction_fraction": (full_tokens - sift_tokens) / full_tokens,
            "upstream_reported_cost_reduction_fraction": (full_cost - sift_cost) / full_cost,
        },
        "analysis_script": "benchmarks/analyze_longbench_v2_candidate_subset.py",
        "analysis_script_sha256": generator_sha256,
        "limitations": [
            "All task IDs were exposed by prior prompt/label census work; this selected subset is not untouched validation.",
            "The tasks were selected by prior answer-blind candidate mechanisms and this retrospective subset is not representative of LongBench v2.",
            "Historical Full/default responses are a baseline-only comparison; no field-pruning, record-ranking, or query-directed candidate arm was evaluated here.",
            "The cluster-bootstrap interval is exploratory with only 14 selected tasks.",
            "Provider-reported cost and cache shares are specific to these historical requests and do not establish general savings.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=TRACE_DEFAULT)
    parser.add_argument("--run", type=Path, default=RUN_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--check", action="store_true", help="compare against an existing report")
    args = parser.parse_args()
    trace_path, run_path = args.trace.resolve(), args.run.resolve()
    run = json.loads(run_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    result = analyze(trace, run, _sha256(run_path), _sha256(trace_path),
                     _sha256(Path(__file__).resolve()))
    if args.check:
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        for key in ("status", "source_run_sha256", "source_trace_sha256", "selected_task_count",
                    "selected_task_ids_sha256", "repeats_per_task_arm", "arms", "paired_task_majority",
                    "descriptive_differences", "analysis_script_sha256", "limitations"):
            if existing.get(key) != result.get(key):
                raise AnalysisError(f"report differs at {key}")
        print(json.dumps({"status": "verified", "output": str(args.output),
                          "selected_task_count": result["selected_task_count"],
                          "arms": result["arms"],
                          "paired_task_majority": result["paired_task_majority"]}, indent=2))
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "selected_task_count": result["selected_task_count"],
                      "arms": result["arms"],
                      "paired_task_majority": result["paired_task_majority"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
