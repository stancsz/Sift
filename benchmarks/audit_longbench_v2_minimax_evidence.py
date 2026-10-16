"""Offline evidence-retention audit for two objective MiniMax QA cases.

The gold evidence is derived from the pinned source data without reading any
arm outputs. It checks exact CSV-comment preservation for a distinct-count
question and complete contribution-vector preservation for an aggregate game
question. It makes no model requests.
"""

from __future__ import annotations

import csv
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "benchmarks")]

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import (  # noqa: E402
    MODEL_ID,
    SIFT_TARGETS,
    render_minimax,
)
from sift import compact_messages  # noqa: E402
from sift import core as sift_core  # noqa: E402


MANIFEST = ROOT / "docs/evals/longbench-v2-minimax-m3-sift-screen-2026-10-16.json"
DATASET = Path.home() / ".cache/sift-longbench-v2" / DATASET_REVISION / "data.json"
TOKENIZER = ROOT / "tmp/minimax-m3-tokenizer.json"
TEMPLATE = ROOT / "tmp/minimax-m3-chat-template.jinja"
CASE_CSV = "66f2a46d821e116aacb2a41a"
CASE_GAME = "671b2c05bb02136c067d50c8"
SAFETY_MARGIN = 128


@contextmanager
def selector_variant(*, csv_record_retention: bool):
    """Reproduce a local CSV-feature ablation without adding a runtime option."""
    if csv_record_retention:
        yield
        return
    original_csv_pieces = sift_core._csv_pieces
    original_quoted_bonus = sift_core._QUOTED_QUERY_BONUS
    sift_core._csv_pieces = lambda _text: None
    sift_core._QUOTED_QUERY_BONUS = 0
    try:
        yield
    finally:
        sift_core._csv_pieces = original_csv_pieces
        sift_core._QUOTED_QUERY_BONUS = original_quoted_bonus


def exact_count(tokenizer: Tokenizer, messages: list[dict[str, Any]]) -> int:
    rendered = render_minimax(messages)
    return len(tokenizer.encode(rendered, add_special_tokens=False).ids)


def _case_rows(dataset_path: Path, ids: set[str]) -> dict[str, dict[str, Any]]:
    found = {}
    for row in iter_json_array(dataset_path):
        if row["_id"] in ids:
            found[row["_id"]] = row
            if len(found) == len(ids):
                break
    if set(found) != ids:
        raise ValueError("Frozen MiniMax benchmark cases are missing from pinned dataset")
    return found


def _csv_evidence(context: str) -> dict[str, Any]:
    physical_lines = context.splitlines(keepends=True)
    reader = csv.reader(physical_lines)
    header = next(reader)
    text_index = header.index("text")
    id_index = header.index("review_id")
    end_line = reader.line_num
    matches = []
    for record in reader:
        next_line = reader.line_num
        raw_record = "".join(physical_lines[end_line:next_line])
        end_line = next_line
        if (len(record) > max(text_index, id_index)
                and re.search(r"mexican", record[text_index], re.IGNORECASE)):
            matches.append((record[id_index], record[text_index], raw_record))
    # The dataset task says comments count as identical only when the text is
    # exactly identical. Do not case-fold or normalize punctuation/whitespace.
    unique = sorted(set(text for _, text, _ in matches))
    raw_by_text: dict[str, set[str]] = {}
    for _, text, raw in matches:
        raw_by_text.setdefault(text, set()).add(raw)
    return {
        "kind": "complete_unique_csv_field_values",
        "matching_comment_rows": len(matches),
        "unique_exact_comment_count": len(unique),
        "unique_comment_sha256": [
            hashlib.sha256(text.encode("utf-8")).hexdigest() for text in unique
        ],
        "matching_review_ids": sorted(review_id for review_id, _, _ in matches),
        "required_unique_comment_texts": unique,
        "required_unique_comment_raw_records": [
            {"text": text, "records": sorted(raw_by_text[text])} for text in unique
        ],
    }


def _game_evidence(context: str) -> dict[str, Any]:
    source = json.loads(context)
    records = source["round_records"]
    player_count = source["meta"]["player_num"]
    if len(records) != source["meta"]["round_id"]:
        raise ValueError("Round-record count differs from game round_id")
    totals = [0] * player_count
    for record in records:
        contributions = record["responses"]
        if len(contributions) != player_count:
            raise ValueError("A game round has the wrong number of player contributions")
        totals = [total + value for total, value in zip(totals, contributions)]
    evidence = [
        {"round": index + 1, "responses": record["responses"]}
        for index, record in enumerate(records)
    ]
    return {
        "kind": "all_round_contribution_vectors",
        "round_count": len(records),
        "player_totals": totals,
        "max_total": max(totals),
        "tied_top_player_indices_zero_based": [i for i, value in enumerate(totals) if value == max(totals)],
        "required_round_vectors": evidence,
    }


def _retention(evidence: dict[str, Any], forwarded_messages: list[dict[str, Any]]) -> dict[str, Any]:
    retained = []
    for message in forwarded_messages:
        content = message.get("content")
        if not isinstance(content, str):
            continue
        retained.append(content)
        for line in content.splitlines():
            if not line.startswith("[message ") or "] " not in line:
                continue
            try:
                excerpt = json.loads(line.split("] ", 1)[1])
            except json.JSONDecodeError:
                continue
            if isinstance(excerpt, str):
                retained.append(excerpt)
    content = "\n".join(retained)
    if evidence["kind"] == "complete_unique_csv_field_values":
        kept = sum(
            any(record in content for record in item["records"])
            for item in evidence["required_unique_comment_raw_records"]
        )
        required = evidence["unique_exact_comment_count"]
    else:
        # Compare ordered vectors as complete JSON values, not scattered digits.
        compact = re.sub(r"\s+", "", content)
        vectors = [json.dumps(item["responses"], separators=(",", ":")) for item in evidence["required_round_vectors"]]
        available: dict[str, int] = {}
        for vector in vectors:
            available[vector] = compact.count(vector)
        used: dict[str, int] = {}
        kept = 0
        for vector in vectors:
            used[vector] = used.get(vector, 0) + 1
            if used[vector] <= available[vector]:
                kept += 1
        required = evidence["round_count"]
    return {"retained_evidence_items": kept, "required_evidence_items": required,
            "complete_evidence_set": kept == required}


def run(dataset_path: Path = DATASET, manifest_path: Path = MANIFEST,
        tokenizer_path: Path = TOKENIZER, template_path: Path = TEMPLATE) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["dataset"]["revision"] != DATASET_REVISION or manifest["dataset"]["data_file_sha256"] != DATASET_SHA256:
        raise ValueError("Manifest does not use the pinned LongBench v2 revision")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise ValueError("LongBench v2 dataset SHA-256 mismatch")
    if file_sha256(tokenizer_path) != manifest["model"]["tokenizer_sha256"]:
        raise ValueError("MiniMax tokenizer SHA-256 mismatch")
    if file_sha256(template_path) != manifest["model"]["chat_template_sha256"]:
        raise ValueError("MiniMax chat-template SHA-256 mismatch")
    core_hash = hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest()
    if core_hash != manifest["sift"]["core_sha256"]:
        raise ValueError("Sift core changed since the MiniMax experiment was frozen")

    rows = _case_rows(dataset_path, {CASE_CSV, CASE_GAME})
    frozen = {case["id"]: case for case in manifest["cases"]}
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    results = []
    for case_id, evidence_fn in ((CASE_CSV, _csv_evidence), (CASE_GAME, _game_evidence)):
        row = rows[case_id]
        messages = make_messages(row)
        if prompt_sha256(messages) != frozen[case_id]["prompt_sha256"]:
            raise ValueError(f"Frozen prompt hash mismatch for {case_id}")
        full_count = exact_count(tokenizer, messages)
        if full_count != frozen[case_id]["m3_rendered_prompt_tokens"]:
            raise ValueError(f"Frozen MiniMax token count mismatch for {case_id}")
        evidence = evidence_fn(row["context"])
        case_result = {
            "case_id": case_id,
            "domain": row["domain"],
            "full_prompt_tokens": full_count,
            "question_sha256": hashlib.sha256(row["question"].encode("utf-8")).hexdigest(),
            "source_evidence": {key: value for key, value in evidence.items()
                                if key not in {"required_unique_comment_texts", "required_unique_comment_raw_records", "required_round_vectors"}},
            "arms": [{"arm": "full", "target_tokens": None,
                      "retention": _retention(evidence, messages)}],
        }
        for target in SIFT_TARGETS:
            if full_count <= target - SAFETY_MARGIN:
                case_result["arms"].append({"arm": "sift", "target_tokens": target,
                                             "applicable": False,
                                             "reason": "Original prompt already fits this target"})
                continue
            result = compact_messages(
                messages, lambda value: exact_count(tokenizer, value),
                target=target - SAFETY_MARGIN, raw_limit=1_000_000, protocol="openai",
            )
            case_result["arms"].append({
                "arm": "sift",
                "target_tokens": target,
                "applicable": True,
                "forwarded_tokens": exact_count(tokenizer, result.messages),
                "selected_excerpts": result.audit["selected_excerpts"],
                "retention": _retention(evidence, result.messages),
            })
        results.append(case_result)
    return {
        "schema_version": 1,
        "evaluation": "blinded source-derived evidence-retention audit; no model outputs read and no provider calls",
        "model_context": MODEL_ID,
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "manifest_sha256": file_sha256(manifest_path),
        "sift_core_sha256": core_hash,
        "method": "Decode Sift's JSON-quoted excerpts; compare complete original CSV row alternatives for every exact unique comment and complete per-round contribution vectors. No paraphrase or answer correctness adjudication.",
        "cases": results,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER)
    parser.add_argument("--template", type=Path, default=TEMPLATE)
    parser.add_argument("--disable-csv-record-retention", action="store_true",
                        help="Run the selector ablation without atomic CSV rows or quoted-anchor boost")
    args = parser.parse_args()
    with selector_variant(csv_record_retention=not args.disable_csv_record_retention):
        report = run(args.dataset, args.manifest, args.tokenizer, args.template)
    report["selector_variant"] = (
        "csv_record_retention" if not args.disable_csv_record_retention
        else "csv_retention_disabled_ablation"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({case["case_id"]: {
        f"{arm['arm']}:{arm.get('target_tokens')}": arm.get("retention")
        for arm in case["arms"]
    } for case in report["cases"]}, ensure_ascii=False, indent=2))
