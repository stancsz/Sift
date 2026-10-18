"""Answer-blind, zero-network census of experimental Sift retention modes.

Reads only the pinned LongBench v2 prompt fields. The dataset answer field is
cursor-skipped by the shared selective parser. No model or network calls are
made; scores here describe local token counts, mode eligibility, and whether
the produced prompt differs from default Sift, not answer quality.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from audit_longbench_v2_minimax_fullsuite_offline import (  # noqa: E402
    CONFIGURED_TARGET,
    DEFAULT_DATASET,
    DEFAULT_TOKENIZER,
    EFFECTIVE_TARGET,
    PROMPT_FIELDS,
    iter_answer_blind_rows,
)
from prepare_longbench_v2 import DATASET_BYTES, DATASET_SHA256, file_sha256, make_messages  # noqa: E402
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from sift import CompactionError, compact_messages  # noqa: E402


MODES: dict[str, dict[str, bool]] = {
    "default": {},
    "research_relation_closure": {"research_relation_closure": True},
    "complete_record_groups": {"complete_record_groups": True},
    "query_directed_labels": {"query_directed_labels": True},
    "field_pruning": {"field_pruning": True},
}
RAW_LIMIT = 1_000_000


def canonical_messages_hash(messages: list[dict[str, Any]]) -> str:
    body = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def count_rendered(tokenizer: Tokenizer, messages: list[dict[str, Any]]) -> int:
    return len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)


def _mode_result(messages: list[dict[str, Any]], counter: Any,
                 flags: dict[str, bool]) -> tuple[
                     list[dict[str, Any]] | None, int | None, str | None, str | None
                 ]:
    try:
        result = compact_messages(
            messages,
            counter,
            target=EFFECTIVE_TARGET,
            raw_limit=RAW_LIMIT,
            protocol="openai",
            **flags,
        )
    except CompactionError as error:
        return None, None, error.code, None
    forwarded = counter(result.messages)
    if forwarded > EFFECTIVE_TARGET:
        raise RuntimeError(
            f"{result.audit.get('method', 'unknown')} exceeded the fixed effective target"
        )
    method = str(result.audit.get("method", "no_op"))
    return result.messages, forwarded, None, method


def build_report(dataset: Path, tokenizer_path: Path) -> dict[str, Any]:
    if dataset.stat().st_size != DATASET_BYTES or file_sha256(dataset) != DATASET_SHA256:
        raise ValueError("Pinned LongBench v2 dataset size or SHA-256 mismatch")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    core_path = ROOT / "src/sift/core.py"
    source_paths = {
        "dataset": dataset,
        "tokenizer": tokenizer_path,
        "core": core_path,
        "shared_answer_blind_audit": ROOT / "benchmarks/audit_longbench_v2_minimax_fullsuite_offline.py",
        "prompt_builder": ROOT / "benchmarks/prepare_longbench_v2.py",
        "renderer": ROOT / "benchmarks/prepare_longbench_v2_minimax.py",
        "this_runner": Path(__file__),
    }
    source_hashes = {name: file_sha256(path) for name, path in source_paths.items()}
    if set(PROMPT_FIELDS) != {
        "_id", "domain", "context", "question",
        "choice_A", "choice_B", "choice_C", "choice_D",
    }:
        raise ValueError("Answer-blind field allowlist changed unexpectedly")

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    accum: dict[str, dict[str, Any]] = {
        name: {"tokens": [], "errors": Counter(), "changed_vs_default": 0,
               "successes": 0, "no_op_inputs": 0}
        for name in MODES
    }
    paired_deltas: dict[str, list[int]] = {name: [] for name in MODES if name != "default"}

    for index, row in enumerate(iter_answer_blind_rows(dataset), start=1):
        case_id = str(row.get("_id", ""))
        if not case_id or case_id in seen_ids:
            raise ValueError("Missing or duplicate LongBench v2 task ID")
        seen_ids.add(case_id)
        messages = make_messages(row)
        count_cache: dict[str, int] = {}

        def counter(candidate: list[dict[str, Any]]) -> int:
            rendered = render_minimax(candidate)
            key = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
            if key not in count_cache:
                count_cache[key] = len(
                    tokenizer.encode(rendered, add_special_tokens=False).ids
                )
            return count_cache[key]

        raw_tokens = counter(messages)
        case: dict[str, Any] = {
            "id": case_id,
            "domain": str(row.get("domain", "")),
            "raw_prompt_tokens": raw_tokens,
            "already_within_target": raw_tokens <= EFFECTIVE_TARGET,
            "modes": {},
        }
        outputs: dict[str, tuple[
            list[dict[str, Any]] | None, int | None, str | None, str | None
        ]] = {}
        for mode_name, flags in MODES.items():
            output, tokens, error, method = _mode_result(messages, counter, flags)
            outputs[mode_name] = (output, tokens, error, method)
            item = accum[mode_name]
            if error:
                item["errors"][error] += 1
            else:
                assert output is not None and tokens is not None
                item["successes"] += 1
                item["tokens"].append(tokens)
                if case["already_within_target"]:
                    item["no_op_inputs"] += 1
            case["modes"][mode_name] = {
                "completed_successfully": error is None,
                "candidate_eligible_above_target": (
                    error is None and not case["already_within_target"]
                ),
                "error_code": error,
                "forwarded_prompt_tokens": tokens,
                "forwarded_messages_sha256": (
                    canonical_messages_hash(output) if output is not None else None
                ),
                "audit_method": method,
            }

        default_output, default_tokens, default_error, _ = outputs["default"]
        for mode_name, (output, tokens, error, _) in outputs.items():
            if error is not None or output is None or default_error is not None or default_output is None:
                continue
            changed = canonical_messages_hash(output) != canonical_messages_hash(default_output)
            case["modes"][mode_name]["changed_vs_default"] = changed
            if changed:
                accum[mode_name]["changed_vs_default"] += 1
            if (mode_name != "default" and tokens is not None and default_tokens is not None
                    and not case["already_within_target"]):
                paired_deltas[mode_name].append(default_tokens - tokens)
        rows.append(case)
        if index % 25 == 0:
            print(f"audited {index}/503 answer-blind rows", flush=True)

    if len(rows) != 503 or len(seen_ids) != 503:
        raise ValueError(f"Expected 503 distinct rows, found {len(rows)}")
    for name, path in source_paths.items():
        if file_sha256(path) != source_hashes[name]:
            raise ValueError(f"Source changed during audit: {name}")

    summary: dict[str, Any] = {}
    for mode_name, stats in accum.items():
        tokens = stats["tokens"]
        deltas = paired_deltas.get(mode_name, [])
        summary[mode_name] = {
            "eligible_rows_above_target": stats["successes"] - stats["no_op_inputs"],
            "completed_rows_including_no_op": stats["successes"],
            "failed_rows": 503 - stats["successes"],
            "failure_codes": dict(sorted(stats["errors"].items())),
            "already_within_target_no_op_rows": stats["no_op_inputs"],
            "outputs_changed_vs_default": stats["changed_vs_default"],
            "forwarded_prompt_tokens": {
                "median": percentile(tokens, 0.50),
                "p90": percentile(tokens, 0.90),
                "mean": round(statistics.fmean(tokens), 2) if tokens else None,
            },
            "paired_token_savings_vs_default": {
                "paired_success_rows": len(deltas),
                "median_tokens_saved": percentile(deltas, 0.50),
                "mean_tokens_saved": round(statistics.fmean(deltas), 2) if deltas else None,
                "rows_with_lower_token_count": sum(delta > 0 for delta in deltas),
                "rows_with_higher_token_count": sum(delta < 0 for delta in deltas),
                "rows_with_equal_token_count": sum(delta == 0 for delta in deltas),
            } if mode_name != "default" else None,
        }

    return {
        "schema_version": 1,
        "status": "complete_answer_blind_zero_network_offline_census",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation": "LongBench v2 prompt-retention mode census",
        "network_calls": 0,
        "actual_dispatch_started": False,
        "answers_decoded": False,
        "model_responses_read": False,
        "answer_field_handling": "Only the pinned prompt-field allowlist is decoded; the shared streaming parser skips all other values, including answer.",
        "scope": {
            "dataset_rows": len(rows),
            "unique_ids": len(seen_ids),
            "target_tokens": CONFIGURED_TARGET,
            "safety_margin_tokens": CONFIGURED_TARGET - EFFECTIVE_TARGET,
            "effective_target_tokens": EFFECTIVE_TARGET,
            "raw_limit_tokens": RAW_LIMIT,
            "modes": {name: dict(flags) for name, flags in MODES.items()},
            "interpretation": "Eligibility, token counts, and prompt changes only; no answer quality or task-success inference.",
        },
        "source_hashes": source_hashes,
        "rendering": {
            "renderer_source_sha256": source_hashes["renderer"],
            "external_template_file_loaded": False,
            "note": "Token counting uses the checked-in render_minimax implementation; no external template file is loaded.",
        },
        "summary": summary,
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.dataset, args.tokenizer)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": report["status"],
        "rows": report["scope"]["dataset_rows"],
        "target_tokens": report["scope"]["target_tokens"],
        "effective_target_tokens": report["scope"]["effective_target_tokens"],
        "summary": report["summary"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
