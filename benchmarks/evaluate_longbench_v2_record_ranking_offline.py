"""Measure a frozen structured-record candidate on a LongBench sample offline.

The evaluator makes no network/API requests and never reads answer-key or
model-output fields. It records exact MiniMax-template token counts for full
context, default Sift, and a selectable candidate strategy. A separate review
packet contains only source context, question, choices, retained contexts, and
candidate audit so a reviewer can inspect evidence without gold answers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "benchmarks") not in sys.path:
    sys.path.insert(0, str(ROOT / "benchmarks"))

from sift import core  # noqa: E402
from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
)
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402


TARGET_TOKENS = 32_640
SAMPLE_SHA256 = "93d433cab778b1fc637fed6f9c9e6f277c03ce3cee42fb773bd03e322439e088"
CORE_SHA256 = "7e388eb135113e4b1e6ed54b63af4149a596267e9849020743a916c9feaf3316"
TOKENIZER_SHA256 = "bb1f1626cf01448f1e3b6036d0a061ffc66c91d9046aada14ea23a5441b5ad6e"
TEMPLATE_SHA256 = "11421244f67553498e5c8112dae02802025bcc4305ec45ad380af95c96f9fe64"
SAMPLE_DEFAULT = ROOT / "docs/evals/longbench-v2-record-ranking-sample-2026-10-18.json"
DATASET_DEFAULT = (
    Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
)
TOKENIZER_DEFAULT = ROOT / "tmp/minimax-m3-tokenizer.json"
TEMPLATE_DEFAULT = ROOT / "tmp/minimax-m3-chat-template.jinja"
OUTPUT_DEFAULT = ROOT / "docs/evals/longbench-v2-record-ranking-offline-2026-10-18.json"
REVIEW_DEFAULT = ROOT / ".runs/longbench-v2-record-ranking-review-packet-2026-10-18.json"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _message_hash(messages: list[dict[str, Any]]) -> str:
    rendered = render_minimax(messages)
    return _sha256_bytes(rendered.encode("utf-8"))


def _token_counter(tokenizer: Tokenizer):
    cache: dict[str, int] = {}

    def count(messages: list[dict[str, Any]]) -> int:
        rendered = render_minimax(messages)
        digest = _sha256_bytes(rendered.encode("utf-8"))
        if digest not in cache:
            cache[digest] = len(tokenizer.encode(rendered, add_special_tokens=False).ids)
        return cache[digest]

    return count


def _contexts(messages: list[dict[str, Any]]) -> tuple[str, str]:
    if (len(messages) < 3 or messages[0].get("role") != "system"
            or messages[-1].get("role") != "user"):
        raise ValueError("Unexpected frozen LongBench message layout")
    retained = "\n\n".join(
        f"[{message.get('role', 'unknown')}]\n{message.get('content', '')}"
        for message in messages[1:-1]
    )
    return retained, str(messages[-1]["content"])


def evaluate(
    sample_path: Path,
    dataset_path: Path,
    tokenizer_path: Path,
    template_path: Path,
    output_path: Path,
    review_path: Path,
    split: str,
    candidate_strategy: str = "complete_record_groups",
    expected_sample_sha256: str = SAMPLE_SHA256,
    expected_core_sha256: str = CORE_SHA256,
) -> dict[str, Any]:
    for path, label in (
        (sample_path, "frozen sample"),
        (dataset_path, "pinned LongBench dataset"),
        (tokenizer_path, "MiniMax tokenizer"),
        (template_path, "MiniMax template"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"Missing {label}: {path}")

    sample_sha = file_sha256(sample_path)
    if sample_sha != expected_sample_sha256:
        raise ValueError("Frozen sample SHA-256 mismatch")
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    method = sample.get("method", {})
    if method.get("dataset_revision") != DATASET_REVISION or method.get("dataset_sha256") != DATASET_SHA256:
        raise ValueError("Frozen sample does not bind to the pinned dataset")
    if method.get("target_tokens") != TARGET_TOKENS:
        raise ValueError("Frozen sample target differs from this evaluator")
    candidate_specs = {
        "complete_record_groups": (
            "separate opt-in use of core.compact_messages(..., complete_record_groups=True); "
            "whole-record relation closure across entities/concepts/labels maps; "
            "preserves other root members; no source changes are made by this selector",
            "complete_record_groups",
            "complete_record_groups=True",
        ),
        "query_directed_labels": (
            "separate opt-in use of core.compact_messages(..., query_directed_labels=True); "
            "preserves complete explicit QID choice records and adds only one-hop identity fields "
            "from typed relations[].object, instanceOf, and subclassOf references; absent optional "
            "identity labels are audited while original references stay in complete choice records",
            "query_directed_one_hop_identity_labels",
            "query_directed_labels=True",
        ),
    }
    if candidate_strategy not in candidate_specs:
        raise ValueError("Unsupported candidate strategy")
    expected_method_description, expected_audit_method, candidate_flag = candidate_specs[candidate_strategy]
    if method.get("candidate_under_study") != expected_method_description:
        raise ValueError("Frozen sample candidate description differs from selected strategy")
    if method.get("selector_builder_sha256") != file_sha256(Path(__file__).with_name("prepare_longbench_v2_record_ranking_sample.py")):
        raise ValueError("Frozen sample selector-builder SHA-256 mismatch")
    if method.get("dataset_reader_sha256") != file_sha256(ROOT / "benchmarks" / "prepare_longbench_v2.py"):
        raise ValueError("Frozen sample dataset-reader SHA-256 mismatch")
    if method.get("template_renderer_sha256") != file_sha256(ROOT / "benchmarks" / "prepare_longbench_v2_minimax.py"):
        raise ValueError("Frozen sample template-renderer SHA-256 mismatch")
    if method.get("candidate_core_sha256") != expected_core_sha256:
        raise ValueError("Frozen sample candidate-core SHA-256 mismatch")
    if file_sha256(ROOT / "src" / "sift" / "core.py") != expected_core_sha256:
        raise ValueError("Sift core SHA-256 differs from the frozen candidate")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise ValueError("LongBench dataset SHA-256 mismatch")
    if file_sha256(tokenizer_path) != TOKENIZER_SHA256:
        raise ValueError("MiniMax tokenizer SHA-256 mismatch")
    if file_sha256(template_path) != TEMPLATE_SHA256:
        raise ValueError("MiniMax chat-template SHA-256 mismatch")

    selected = sample.get("selected")
    if not isinstance(selected, list) or len(selected) != 20:
        raise ValueError("Expected the frozen 20-task sample")
    ids = [str(row["id"]) for row in selected]
    if len(ids) != len(set(ids)):
        raise ValueError("Frozen sample contains duplicate task IDs")
    expected_split_count = 10
    if sum(row.get("split") == "development" for row in selected) != expected_split_count:
        raise ValueError("Expected 10 development rows")
    if sum(row.get("split") == "held_out" for row in selected) != expected_split_count:
        raise ValueError("Expected 10 held-out rows")
    if split not in {"development", "held_out", "all"}:
        raise ValueError("split must be development, held_out, or all")
    selected_by_id = {
        str(row["id"]): row for row in selected
        if split == "all" or row.get("split") == split
    }

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    count_tokens = _token_counter(tokenizer)
    observed: dict[str, dict[str, Any]] = {}
    review_rows: list[dict[str, Any]] = []
    for source_row in iter_json_array(dataset_path):
        task_id = str(source_row["_id"])
        selected_row = selected_by_id.get(task_id)
        if selected_row is None:
            continue
        # make_messages consumes only context/question/choice_A-D. Deliberately
        # do not access, copy, hash, log, or serialize source_row['answer'].
        messages = make_messages(source_row)
        original_context, question = _contexts(messages)
        source_hash = _message_hash(messages)
        full_tokens = count_tokens(messages)
        default_result: core.CompactionResult | None = None
        default_error: dict[str, str] | None = None
        candidate_result: core.CompactionResult | None = None
        candidate_error: dict[str, str] | None = None
        try:
            raw_limit = max(1_000_000, full_tokens)
            default_result = core.compact_messages(
                messages, count_tokens, target=TARGET_TOKENS,
                raw_limit=raw_limit, protocol="openai",
            )
        except core.CompactionError as error:
            default_error = {"code": error.code or "compaction_error", "message": str(error)}
        try:
            candidate_kwargs = (
                {"complete_record_groups": True}
                if candidate_strategy == "complete_record_groups"
                else {"query_directed_labels": True}
            )
            candidate_result = core.compact_messages(
                messages, count_tokens, target=TARGET_TOKENS,
                raw_limit=raw_limit, protocol="openai", **candidate_kwargs,
            )
        except core.CompactionError as error:
            candidate_error = {"code": error.code or "compaction_error", "message": str(error)}

        default_tokens = (
            int(default_result.audit["forwarded_tokens"]) if default_result is not None else None
        )
        candidate_tokens = (
            int(candidate_result.audit["forwarded_tokens"]) if candidate_result is not None else None
        )
        candidate_method_ok = (
            candidate_result is not None
            and candidate_result.audit.get("method") == expected_audit_method
        )
        candidate_fits_target = candidate_tokens is not None and candidate_tokens <= TARGET_TOKENS
        growth_ok = (
            default_tokens is not None and candidate_tokens is not None
            and candidate_tokens * 10 <= default_tokens * 11
        )
        row_report: dict[str, Any] = {
            "id": task_id,
            "split": selected_row["split"],
            "structure": selected_row["structure"],
            "domain": selected_row["domain"],
            "difficulty": selected_row["difficulty"],
            "length": selected_row["length"],
            "prior_method_exposure": selected_row["prior_method_exposure"],
            "source_prompt_tokens": full_tokens,
            "raw_limit_tokens": raw_limit,
            "source_prompt_sha256": source_hash,
            "historical_route_context_eligible": full_tokens <= 524_288,
            "default_sift_tokens": default_tokens,
            "default_sift_prompt_sha256": (
                _message_hash(default_result.messages) if default_result is not None else None
            ),
            "default_sift_audit": default_result.audit if default_result is not None else None,
            "default_sift_error": default_error,
            "candidate_tokens": candidate_tokens,
            "candidate_prompt_sha256": (
                _message_hash(candidate_result.messages) if candidate_result is not None else None
            ),
            "candidate_audit": candidate_result.audit if candidate_result is not None else None,
            "candidate_error": candidate_error,
            "candidate_method_ok": candidate_method_ok,
            "candidate_fits_target": candidate_fits_target,
            "candidate_growth_within_10pct": growth_ok,
            "candidate_gate_pass": bool(candidate_method_ok and candidate_fits_target and growth_ok),
        }
        observed[task_id] = row_report
        candidate_context = (
            _contexts(candidate_result.messages)[0] if candidate_result is not None else None
        )
        default_context = (
            _contexts(default_result.messages)[0] if default_result is not None else None
        )
        review_rows.append({
            "id": task_id,
            "split": selected_row["split"],
            "structure": selected_row["structure"],
            "question_and_choices": question,
            "source_context": original_context,
            "default_sift_context": default_context,
            "candidate_context": candidate_context,
            "candidate_audit": candidate_result.audit if candidate_result is not None else None,
            "candidate_error": candidate_error,
        })
        if len(observed) == len(selected_by_id):
            break
    missing_ids = sorted(set(selected_by_id) - set(observed))
    if missing_ids:
        raise ValueError(f"Pinned dataset is missing selected sample IDs: {missing_ids}")

    rows = [observed[task_id] for task_id in selected_by_id]
    gate_rows = [row for row in rows if row["split"] == "held_out"]
    heldout_gate_evaluated = split in {"held_out", "all"}
    heldout_pass = (
        len(gate_rows) == 10 and all(row["candidate_gate_pass"] for row in gate_rows)
        if heldout_gate_evaluated else None
    )
    artifact = {
        "schema_version": 1,
        "title": "LongBench v2 answer-blind offline candidate evaluation",
        "status": "offline_only_no_model_requests",
        "split_evaluated": split,
        "network_calls": 0,
        "api_calls": 0,
        "answer_keys_read": False,
        "model_outputs_read": False,
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "sha256": file_sha256(dataset_path),
            "sample_sha256": sample_sha,
        },
        "model_tokenization": {
            "model_id": "minimax/minimax-m3",
            "tokenizer_sha256": file_sha256(tokenizer_path),
            "template_sha256": file_sha256(template_path),
            "renderer": "benchmarks/prepare_longbench_v2_minimax.py::render_minimax",
            "tokenizers_version": __import__("tokenizers").__version__,
        },
        "route_context_reference": {
            "provider": "minimax",
            "historical_prompt_limit_tokens": 524_288,
            "historical_observed_date": "2026-10-16",
            "live_route_verified": False,
            "note": "Offline full-prompt comparison only; refresh OpenRouter route metadata before any dispatch.",
        },
        "candidate": {
            "strategy": candidate_strategy,
            "flag": candidate_flag,
            "target_tokens": TARGET_TOKENS,
            "raw_limit_tokens": "max(1,000,000, exact full prompt tokens) for offline evaluation only; does not qualify oversized prompts for OpenRouter dispatch",
            "growth_gate": "candidate_tokens * 10 <= default_sift_tokens * 11",
            "core_sha256": expected_core_sha256,
            "evaluator_sha256": file_sha256(Path(__file__)),
        },
        "summary": {
            "rows": len(rows),
            "development_rows": sum(row["split"] == "development" for row in rows),
            "held_out_rows": sum(row["split"] == "held_out" for row in rows),
            "candidate_successes": sum(row["candidate_method_ok"] for row in rows),
            "candidate_gate_passes": sum(row["candidate_gate_pass"] for row in rows),
            "unresolved_optional_identity_labels": sum(
                int((row.get("candidate_audit") or {}).get("unresolved_identity_labels", 0))
                for row in rows
            ),
            "historical_route_context_eligible_rows": sum(
                row["historical_route_context_eligible"] for row in rows
            ),
            "historical_route_context_exceeded_rows": sum(
                not row["historical_route_context_eligible"] for row in rows
            ),
            "held_out_gate_evaluated": heldout_gate_evaluated,
            "held_out_gate_pass": heldout_pass,
        },
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review = {
        "title": "Answer-blind LongBench evidence retention review packet",
        "notice": "No answer keys or model outputs are included. Review original question/choices and context against retained records/relationships.",
        "sample_sha256": sample_sha,
        "candidate_flag": candidate_flag,
        "rows": review_rows,
    }
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=SAMPLE_DEFAULT)
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--review-packet", type=Path, default=REVIEW_DEFAULT)
    parser.add_argument("--split", choices=("development", "held_out", "all"), default="development")
    parser.add_argument("--candidate-strategy", choices=("complete_record_groups", "query_directed_labels"), default="complete_record_groups")
    parser.add_argument("--expected-sample-sha256", default=SAMPLE_SHA256)
    parser.add_argument("--expected-core-sha256", default=CORE_SHA256)
    args = parser.parse_args()
    artifact = evaluate(
        args.sample, args.dataset, args.tokenizer, args.template,
        args.output, args.review_packet, args.split,
        args.candidate_strategy, args.expected_sample_sha256,
        args.expected_core_sha256,
    )
    print(json.dumps({"output": str(args.output), "split": args.split,
                      "summary": artifact["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
