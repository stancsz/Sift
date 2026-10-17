"""Offline, hash-bound gate for the default-off field-pruning prototype.

This audits four pinned LongBench v2 prompts using the local MiniMax M3
tokenizer and the repository's frozen MiniMax message template. It performs no
network requests. The prototype is shape-based and experimental; passing this
small audit does not establish general benchmark quality or model-answer
accuracy after compaction.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    iter_json_array,
    make_messages,
)
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from run_longbench_v2_minimax_relation_followup_v3 import (  # noqa: E402
    _json_object_messages,
)
from sift import CompactionError, compact_messages  # noqa: E402
from sift import core  # noqa: E402


TARGET_TOKENS = 32_640
MAX_GROWTH_NUMERATOR = 11
MAX_GROWTH_DENOMINATOR = 10
CASE_IDS = (
    "66f2b5ec821e116aacb2b1ec",
    "6719b96abb02136c067d4358",
    "671b080abb02136c067d4dde",
    "671b3cabbb02136c067d5252",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def token_counter(tokenizer: Tokenizer):
    def count(messages: list[dict[str, Any]]) -> int:
        rendered = render_minimax(messages)
        return len(tokenizer.encode(rendered, add_special_tokens=False).ids)
    return count


def _json_from_wrapped_context(context: str) -> dict[str, Any]:
    start = context.find("{")
    if start < 0:
        raise ValueError("Expected a root JSON object in the pinned game context")
    value, end = json.JSONDecoder().raw_decode(context, start)
    if not isinstance(value, dict):
        raise ValueError("Expected root JSON object context")
    if context[end:].strip() not in {"", "</text>"}:
        raise ValueError("Unexpected material after root JSON context")
    return value


def _csv_records(context: str) -> tuple[list[str], list[list[str]]]:
    pieces = core._csv_pieces(context)
    if pieces is None:
        raise ValueError("Pinned table context did not pass the bounded CSV parser")
    import csv

    header_line = pieces[0].prefix.splitlines(keepends=True)[-1]
    header = next(csv.reader([header_line], strict=True))
    records = [next(csv.reader(piece.text.splitlines(keepends=True), strict=True))
               for piece in pieces]
    if any(len(record) != len(header) for record in records):
        raise ValueError("CSV row width differs from its header")
    return header, records


def _derive_csv_answer(row: dict[str, Any], choices: list[str]) -> dict[str, Any]:
    import csv

    header, records = _csv_records(row["context"])
    columns = {name.strip().casefold(): index for index, name in enumerate(header)}
    artist_index, album_index, rating_index = (
        columns["artist"], columns["album"], columns["rating"])
    normalized_choices = [choice.strip().casefold() for choice in choices]
    option_ratings: dict[str, float] = {}
    eligible: list[tuple[float, int]] = []
    for option_index, album in enumerate(normalized_choices):
        matches = [record for record in records
                   if record[album_index].strip().casefold() == album]
        if len(matches) != 1:
            raise ValueError(f"Choice album must map to exactly one CSV row: {choices[option_index]}")
        selected = matches[0]
        artist = selected[artist_index].strip().casefold()
        rating = float(selected[rating_index].strip())
        option_ratings[choices[option_index]] = rating
        sibling_rows = [record for record in records
                        if record[artist_index].strip().casefold() == artist]
        has_higher_sibling = any(
            float(record[rating_index].strip()) > 80
            and record[album_index].strip().casefold() != album
            for record in sibling_rows
        )
        if has_higher_sibling:
            eligible.append((rating, option_index))
    if not eligible:
        raise ValueError("No option satisfies the question's artist/rating constraints")
    lowest = min(score for score, _ in eligible)
    winners = [index for score, index in eligible if score == lowest]
    if len(winners) != 1:
        raise ValueError("Derived CSV answer is tied")
    return {
        "answer_letter": "ABCD"[winners[0]],
        "derived_metric": "lowest option rating among artists with another rating above 80",
        "option_ratings": option_ratings,
        "qualifying_option_indexes": [index for _, index in eligible],
    }


def _derive_game_answer(row: dict[str, Any], choices: list[str]) -> dict[str, Any]:
    context = _json_from_wrapped_context(row["context"])
    question = row["question"].casefold()
    players = context.get("player_data")
    rounds = context.get("round_records")
    if not isinstance(players, list) or not isinstance(rounds, list) or len(rounds) != 20:
        raise ValueError("Expected player records and the complete 20-round summary")
    player_by_id = {str(player.get("id")): player for player in players}
    if len(player_by_id) != len(players):
        raise ValueError("Player identifiers are missing or duplicated")
    if any(choice not in player_by_id for choice in choices):
        raise ValueError("At least one option does not identify a source player")

    if "utility" in question or "gold" in question:
        metrics = {
            choice: sum(player_by_id[choice].get("utility", []))
            for choice in choices
        }
        direction = "min" if any(term in question for term in ("least", "lowest")) else "max"
        best = min(metrics.values()) if direction == "min" else max(metrics.values())
        candidates = [choice for choice, value in metrics.items() if value == best]
        metric = f"{direction} sum of per-round utility"
    elif "most times" in question or "most often" in question:
        metrics = {}
        for choice in choices:
            values = player_by_id[choice].get("records")
            if not isinstance(values, list) or len(values) != len(rounds):
                raise ValueError(f"Missing full per-round records for {choice}")
            metrics[choice] = sum(
                value == round_record.get("winner")
                for value, round_record in zip(values, rounds)
            )
        best = max(metrics.values())
        candidates = [choice for choice, value in metrics.items() if value == best]
        metric = "count of per-player records matching each round winner"
    else:
        raise ValueError("No source-backed derivation rule matches this game question")
    if len(candidates) != 1:
        raise ValueError("Derived game answer is tied")
    winner = candidates[0]
    return {
        "answer_letter": "ABCD"[choices.index(winner)],
        "derived_metric": metric,
        "option_metrics": metrics,
        "shared_round_count": len(rounds),
    }


def _conversation_array(value: Any) -> bool:
    return (
        isinstance(value, list) and bool(value)
        and all(isinstance(item, dict) for item in value)
        and all(
            any(key.casefold() in {"role", "speaker"} for key in item)
            and any(key.casefold() in {"content", "parts", "text"} for key in item)
            for item in value
        )
    )


def _verify_retained_case(
    row: dict[str, Any], choices: list[str], output_context: str,
) -> dict[str, Any]:
    if row["_id"] == CASE_IDS[0]:
        import csv

        source_pieces = core._csv_pieces(row["context"])
        output_pieces = core._csv_pieces(output_context)
        if source_pieces is None or output_pieces is None:
            raise ValueError("CSV source/output failed the bounded CSV parser")
        header = next(csv.reader([source_pieces[0].prefix.splitlines(keepends=True)[-1]], strict=True))
        columns = [name.strip().casefold() for name in header]
        artist_index, album_index = columns.index("artist"), columns.index("album")
        source_rows = [next(csv.reader(piece.text.splitlines(keepends=True), strict=True))
                       for piece in source_pieces]
        output_rows = [next(csv.reader(piece.text.splitlines(keepends=True), strict=True))
                       for piece in output_pieces]
        choice_values = {choice.strip().casefold() for choice in choices}
        groups = {source[artist_index].strip().casefold() for source in source_rows
                  if source[album_index].strip().casefold() in choice_values}
        expected = [piece.text for piece, source in zip(source_pieces, source_rows)
                    if source[artist_index].strip().casefold() in groups]
        output_text = [piece.text for piece in output_pieces]
        choice_hits = [sum(choice.strip().casefold() in [cell.strip().casefold() for cell in output]
                           for output in output_rows) for choice in choices]
        if any(hit != 1 for hit in choice_hits):
            raise ValueError("Every CSV choice must remain in exactly one complete output row")
        if output_text != expected:
            raise ValueError("CSV output does not equal the complete required sibling rows")
        return {
            "required_choice_rows": len(choices),
            "required_choice_rows_retained": sum(hit == 1 for hit in choice_hits),
            "artist_groups": len(groups),
            "required_sibling_rows": len(expected),
            "required_sibling_rows_retained": sum(record in output_text for record in expected),
            "source_rows": len(source_rows),
            "output_rows": len(output_rows),
        }

    source = _json_from_wrapped_context(row["context"])
    output = _json_from_wrapped_context(output_context)
    for key, value in source.items():
        if key != "player_data" and output.get(key) != value:
            raise ValueError(f"Shared root field changed during pruning: {key}")
    source_players = {str(player["id"]): player for player in source["player_data"]}
    output_players = {str(player["id"]): player for player in output["player_data"]}
    if set(output_players) != set(choices):
        raise ValueError("Output must retain exactly the four option-linked player rows")
    for choice in choices:
        original = source_players[choice]
        retained = output_players[choice]
        expected_fields = {
            key: value for key, value in original.items()
            if not _conversation_array(value)
        }
        if retained != expected_fields:
            raise ValueError(f"Non-narrative source fields changed for {choice}")
        if retained.get("records") != original.get("records"):
            raise ValueError(f"Per-round records changed for {choice}")
        if retained.get("utility") != original.get("utility"):
            raise ValueError(f"Per-round utility changed for {choice}")
        if len(retained.get("records", [])) != 20 or len(retained.get("utility", [])) not in (0, 20):
            raise ValueError(f"Required result vectors are incomplete for {choice}")
    if output.get("round_records") != source.get("round_records"):
        raise ValueError("Shared 20-round outcome summary was changed")
    if len(output["round_records"]) != 20:
        raise ValueError("Shared output round summary is not complete")
    return {
        "required_choice_rows": len(choices),
        "required_choice_rows_retained": len(output_players),
        "player_records_exact": True,
        "player_utilities_exact": True,
        "shared_round_count": len(output["round_records"]),
        "shared_round_summary_exact": True,
    }


def audit(dataset_path: Path, tokenizer_path: Path) -> dict[str, Any]:
    dataset_hash = sha256_file(dataset_path)
    if dataset_hash != DATASET_SHA256:
        raise ValueError(f"Dataset SHA-256 mismatch: expected {DATASET_SHA256}, got {dataset_hash}")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    count_tokens = token_counter(tokenizer)
    selected: dict[str, dict[str, Any]] = {}
    for row in iter_json_array(dataset_path):
        if row.get("_id") in CASE_IDS:
            selected[row["_id"]] = row
    if set(selected) != set(CASE_IDS):
        raise ValueError("Pinned dataset is missing one or more required LongBench IDs")

    cases = []
    for case_id in CASE_IDS:
        row = selected[case_id]
        messages = _json_object_messages(make_messages(row))
        original_messages = copy.deepcopy(messages)
        choices = core._prompt_choices(messages[-1]["content"])
        if len(choices) != 4:
            raise ValueError(f"Expected four parsed choices in {case_id}")
        baseline = compact_messages(
            messages, count_tokens, target=TARGET_TOKENS,
            raw_limit=1_000_000,
        )
        candidate = compact_messages(
            messages, count_tokens, target=TARGET_TOKENS,
            raw_limit=1_000_000, field_pruning=True,
        )
        if messages != original_messages:
            raise ValueError(f"Compaction mutated the source messages for {case_id}")
        baseline_tokens = int(baseline.audit["forwarded_tokens"])
        candidate_tokens = int(candidate.audit["forwarded_tokens"])
        if candidate_tokens > TARGET_TOKENS:
            raise ValueError(f"Candidate exceeded target for {case_id}")
        if candidate_tokens * MAX_GROWTH_DENOMINATOR > baseline_tokens * MAX_GROWTH_NUMERATOR:
            raise ValueError(f"Candidate exceeded 10% growth ceiling for {case_id}")
        source_choices = _derive_csv_answer(row, choices) if case_id == CASE_IDS[0] else None
        derived = source_choices if source_choices is not None else _derive_game_answer(row, choices)
        official_gold = str(row["answer"]).strip().upper()
        if derived["answer_letter"] != official_gold:
            raise ValueError(
                f"Independently derived gold {derived['answer_letter']} does not match official key "
                f"{official_gold} for {case_id}"
            )
        evidence = _verify_retained_case(
            row, choices, candidate.messages[1]["content"])
        if candidate.audit.get("complete_groups") is not True:
            raise ValueError(f"Candidate did not report complete groups for {case_id}")
        cases.append({
            "id": case_id,
            "domain": row.get("domain"),
            "sub_domain": row.get("sub_domain"),
            "question": row.get("question"),
            "official_gold": official_gold,
            "derived_gold": derived,
            "target_tokens": TARGET_TOKENS,
            "baseline_default_tokens": baseline_tokens,
            "candidate_tokens": candidate_tokens,
            "growth_percent": round((candidate_tokens / baseline_tokens - 1) * 100, 4),
            "within_target": candidate_tokens <= TARGET_TOKENS,
            "within_10_percent_growth": candidate_tokens * 10 <= baseline_tokens * 11,
            "candidate_method": candidate.audit.get("method"),
            "candidate_audit": candidate.audit,
            "retention_checks": evidence,
            "source_messages_unchanged": True,
        })

    report = {
        "status": "passed",
        "audit_kind": "offline_field_pruning_prototype_gate",
        "experimental_shape_based_pruning": True,
        "default_behavior_changed": False,
        "network_calls": 0,
        "dataset_revision": DATASET_REVISION,
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": dataset_hash,
        "tokenizer_path": str(tokenizer_path.resolve()),
        "tokenizer_sha256": sha256_file(tokenizer_path),
        "target_tokens": TARGET_TOKENS,
        "growth_gate": "candidate <= 110% of default forwarded tokens for each case",
        "core_sha256": sha256_file(ROOT / "src" / "sift" / "core.py"),
        "audit_script_sha256": sha256_file(Path(__file__).resolve()),
        "template_source_sha256": sha256_file(ROOT / "benchmarks" / "prepare_longbench_v2_minimax.py"),
        "cases": cases,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    canonical_body = json.dumps(report, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":"))
    report["audit_body_sha256"] = hashlib.sha256(
        canonical_body.encode("utf-8")).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path,
                        help="Local pinned LongBench v2 data.json")
    parser.add_argument("--tokenizer", required=True, type=Path,
                        help="Local MiniMax M3 tokenizer.json")
    parser.add_argument("--output", required=True, type=Path,
                        help="Path for the hash-bound JSON audit result")
    args = parser.parse_args()
    report = audit(args.dataset, args.tokenizer)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "output": str(args.output.resolve()),
        "dataset_sha256": report["dataset_sha256"],
        "tokenizer_sha256": report["tokenizer_sha256"],
        "core_sha256": report["core_sha256"],
        "cases": [{"id": case["id"], "baseline": case["baseline_default_tokens"],
                   "candidate": case["candidate_tokens"],
                   "growth_percent": case["growth_percent"]}
                  for case in report["cases"]],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
