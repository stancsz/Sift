"""Audit source evidence and gold-key consistency for selected LongBench rows.

This is a read-only evaluation utility. It verifies the pinned public data file,
recomputes facts from the source context, and reports official-key scores plus
case-exclusion sensitivities without changing labels or benchmark outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    exact_prompt_tokens,
    iter_json_array,
    make_messages,
)
from sift import compact_messages  # noqa: E402


AUDIT_CASES = ("6713066fbb02136c067d3214", "6719bce5bb02136c067d4447")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def player_log_facts(context: str) -> dict[str, Any]:
    data = json.loads(context)
    round_four_bids: dict[str, int] = {}
    received_totals: dict[str, int] = {}
    for player in data.get("player_data", []):
        player_id = player.get("id")
        messages = player.get("prompt", [])
        receipts = []
        for index, message in enumerate(messages):
            content = message.get("content", "")
            if message.get("role") == "user" and isinstance(content, str):
                receipt = re.search(r"You received (\d+) golds", content)
                if receipt:
                    receipts.append(int(receipt.group(1)))
                if "Game Results for Round 4:" in content:
                    for later in messages[index + 1:]:
                        if later.get("role") == "assistant":
                            try:
                                bid = json.loads(later.get("content", "")).get("bid_amount")
                            except (json.JSONDecodeError, AttributeError):
                                bid = None
                            if bid is not None:
                                round_four_bids[player_id] = int(bid)
                            break
                        if later.get("role") == "user":
                            break
        if player_id is not None and receipts:
            received_totals[player_id] = sum(receipts)

    records = data.get("round_records", [])
    round_four_record = records[3] if len(records) >= 4 else None
    return {
        "player_count": len(data.get("player_data", [])),
        "round_four_player_log_bids": round_four_bids,
        "round_four_player_log_highest": max(round_four_bids, key=round_four_bids.get)
        if round_four_bids else None,
        "round_four_player_log_highest_bid": max(round_four_bids.values())
        if round_four_bids else None,
        "player_log_received_totals": received_totals,
        "round_record_fields": sorted(round_four_record) if round_four_record else [],
        "round_four_record_responses": round_four_record.get("responses")
        if round_four_record else None,
        "round_four_record_has_player_ids": bool(
            round_four_record and any("player" in key.lower() for key in round_four_record)
        ),
    }


def score_sensitivity(report: dict[str, Any]) -> dict[str, Any]:
    cases = {case["id"]: case for case in report["cases"]}
    above = {
        case_id for case_id, case in cases.items()
        if case["full_exact_input_tokens"] > report["sift_target_estimated_tokens"]
    }
    output: dict[str, Any] = {}
    for excluded_name, excluded in (
        ("none", set()),
        ("exclude_second_case", {AUDIT_CASES[1]}),
        ("exclude_both_audited_cases", set(AUDIT_CASES)),
    ):
        eligible = above - excluded
        output[excluded_name] = {}
        for arm in ("full", "sift"):
            samples = [
                sample for sample in report["samples"]
                if sample["arm"] == arm and sample["case_id"] in eligible
            ]
            output[excluded_name][arm] = {
                "correct": sum(sample.get("correct") is True for sample in samples),
                "runs": len(samples),
                "distinct_cases": len({sample["case_id"] for sample in samples}),
            }
    return output


def paired_task_majority_sensitivity(report: dict[str, Any]) -> dict[str, Any]:
    """Summarize paired task outcomes using majority over existing repeats.

    This is a post-hoc diagnostic, not the preregistered answer-level score or
    an inferential test. Tasks, not repeats, are the reported units.
    """
    cases = {case["id"]: case for case in report["cases"]}
    above = {
        case_id for case_id, case in cases.items()
        if case["full_exact_input_tokens"] > report["sift_target_estimated_tokens"]
    }
    output: dict[str, Any] = {}
    exclusions = (
        ("none", set()),
        ("exclude_second_case", {AUDIT_CASES[1]}),
        ("exclude_both_audited_cases", set(AUDIT_CASES)),
    )
    for name, excluded in exclusions:
        eligible = sorted(above - excluded)
        outcomes = {"both_correct": 0, "full_only": 0, "sift_only": 0, "neither": 0}
        details = []
        for case_id in eligible:
            arm_majority = {}
            repeat_counts = {}
            for arm in ("full", "sift"):
                samples = [
                    sample for sample in report["samples"]
                    if sample["arm"] == arm and sample["case_id"] == case_id
                ]
                if not samples or len(samples) % 2 == 0:
                    raise ValueError(
                        f"Task-majority diagnostic requires an odd, nonempty repeat count: "
                        f"{case_id}/{arm}"
                    )
                correct = sum(sample.get("correct") is True for sample in samples)
                arm_majority[arm] = correct > len(samples) // 2
                repeat_counts[arm] = {"correct": correct, "runs": len(samples)}
            if arm_majority["full"] and arm_majority["sift"]:
                outcome = "both_correct"
            elif arm_majority["full"]:
                outcome = "full_only"
            elif arm_majority["sift"]:
                outcome = "sift_only"
            else:
                outcome = "neither"
            outcomes[outcome] += 1
            details.append({"case_id": case_id, "outcome": outcome, "repeats": repeat_counts})
        output[name] = {
            "tasks": len(eligible),
            "aggregation": "strict majority of the three existing repeats; exploratory, post-hoc",
            "outcomes": outcomes,
            "cases": details,
        }
    return output


def selected_snippets(compacted_text: str) -> list[str]:
    snippets = []
    for line in compacted_text.splitlines():
        match = re.match(r"^\[message \d+ \w+\] (.+)$", line)
        if match:
            try:
                snippets.append(json.loads(match.group(1)))
            except json.JSONDecodeError:
                continue
    return snippets


def round_record_source_spans(context: str) -> list[str]:
    position = context.index('"round_records"')
    position = context.index("[", position) + 1
    decoder = json.JSONDecoder()
    spans = []
    while True:
        while position < len(context) and context[position] in " \t\r\n,":
            position += 1
        if position >= len(context) or context[position] == "]":
            return spans
        start = position
        _, position = decoder.raw_decode(context, position)
        spans.append(context[start:position])


def audit(data_path: Path, result_path: Path, tokenizer_url: str) -> dict[str, Any]:
    actual_hash = sha256_file(data_path)
    if actual_hash != DATASET_SHA256:
        raise ValueError(f"Dataset hash mismatch: {actual_hash}")
    report = json.loads(result_path.read_text(encoding="utf-8"))
    if report.get("dataset_revision") != DATASET_REVISION:
        raise ValueError("Result report uses a different LongBench v2 revision")
    if report.get("dataset_sha256") != DATASET_SHA256:
        raise ValueError("Result report uses a different LongBench v2 data file")

    needed = set(AUDIT_CASES)
    rows = {}
    for row in iter_json_array(data_path):
        if row.get("_id") in needed:
            rows[row["_id"]] = row
            if len(rows) == len(needed):
                break
    if set(rows) != needed:
        raise ValueError("Pinned dataset does not contain both audit rows")

    case_reports = []
    for case_id in AUDIT_CASES:
        row = rows[case_id]
        scored_case = next(case for case in report["cases"] if case["id"] == case_id)
        if row["answer"] != scored_case["answer_key"]:
            raise ValueError(f"Scored answer key changed for {case_id}")
        offered = {letter: row[f"choice_{letter}"].strip() for letter in "ABCD"}
        facts = player_log_facts(row["context"])
        facts["logged_receipts_for_offered_choices"] = {
            letter: facts["player_log_received_totals"].get(player_id)
            for letter, player_id in offered.items()
        }
        compacted = compact_messages(
            make_messages(row),
            lambda messages: exact_prompt_tokens(tokenizer_url, messages),
            target=report["sift_target_estimated_tokens"],
            raw_limit=1_000_000,
            protocol="openai",
        )
        snippets = selected_snippets(compacted.messages[1]["content"])
        round_spans = round_record_source_spans(row["context"])
        facts["reconstructed_sift"] = {
            "forwarded_tokens": compacted.audit["forwarded_tokens"],
            "report_forwarded_tokens": next(
                sample["preparation"]["exact_qwen_input_tokens"]
                for sample in report["samples"]
                if sample["case_id"] == case_id and sample["arm"] == "sift"
            ),
            "selected_excerpts": compacted.audit["selected_excerpts"],
            "whole_round_records_preserved_in_single_excerpt": sum(
                span in snippet for span in round_spans for snippet in snippets
            ),
        }
        if case_id == AUDIT_CASES[0]:
            facts["reconstructed_sift"]["player_7_id_and_round_four_bid_40_in_same_excerpt"] = any(
                '"id": "player_7"' in snippet
                and '\\"bid_amount\\": \\"40\\"' in snippet
                for snippet in snippets
            )
        samples = {
            arm: [
                sample["choice"] for sample in report["samples"]
                if sample["case_id"] == case_id and sample["arm"] == arm
            ]
            for arm in ("full", "sift")
        }
        case_reports.append({
            "id": case_id,
            "question": row["question"],
            "official_answer_key": row["answer"],
            "offered_choices": offered,
            "source_facts": facts,
            "full_choices_by_repeat": samples["full"],
            "sift_choices_by_repeat": samples["sift"],
            "official_key_correct_counts": {
                arm: sum(choice == row["answer"] for choice in choices if choice is not None)
                for arm, choices in samples.items()
            },
            "label_status": (
                "official key agrees with per-player Round 4 bids; round_records has no player IDs"
                if case_id == AUDIT_CASES[0]
                else "official key unresolved: the largest logged receipt total belongs to player_2, who is not offered"
            ),
        })
    return {
        "schema_version": 1,
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": actual_hash,
        "result_file": str(result_path),
        "result_file_sha256": sha256_file(result_path),
        "scoring_note": "Official keys and outputs are unchanged; sensitivity counts are diagnostics, not rescoring.",
        "case_audits": case_reports,
        "above_target_score_sensitivity": score_sensitivity(report),
        "above_target_paired_task_majority_sensitivity": paired_task_majority_sensitivity(report),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Pinned LongBench v2 data.json")
    parser.add_argument("--results", type=Path, required=True, help="Structured Qwen result JSON")
    parser.add_argument("--output", type=Path, required=True, help="Audit JSON output path")
    parser.add_argument("--tokenizer-url", default="http://127.0.0.1:8088")
    args = parser.parse_args()
    result = audit(args.data, args.results, args.tokenizer_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "dataset_sha256": result["dataset_sha256"],
        "case_count": len(result["case_audits"]),
        "above_target_score_sensitivity": result["above_target_score_sensitivity"],
        "above_target_paired_task_majority_sensitivity": result[
            "above_target_paired_task_majority_sensitivity"
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
