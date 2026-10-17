"""Answer-blind, offline eligibility census for query-directed identity labels.

The census scans the pinned 503-row LongBench v2 training split, builds only
the prompt fields used by the benchmark, and records structural/token-fit
metadata. Census code never selects, reads, uses, hashes, or serializes
answer/key values or model outputs, and it never writes prompt text or
compacted messages. The generic JSON iterator materializes each whole row in
memory before the allowlist is applied. No network or model/API calls are
made. Processing the frozen held-out task text mechanically is not an accuracy
evaluation and must not be treated as held-out quality evidence.

Example (run only under the evaluation protocol):
    python benchmarks/census_longbench_v2_query_directed_labels.py
"""

from __future__ import annotations

import argparse
from collections import Counter
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
HISTORICAL_ROUTE_PROMPT_LIMIT = 524_288
HISTORICAL_ROUTE_OBSERVED_DATE = "2026-10-16"
EXPECTED_CORE_SHA256 = "5a1d64474eea5d5ca6d599ab893411d40922dd7d12cc47e0ae33b9a097c86f1a"
EXPECTED_TOKENIZER_SHA256 = "bb1f1626cf01448f1e3b6036d0a061ffc66c91d9046aada14ea23a5441b5ad6e"
EXPECTED_TEMPLATE_SHA256 = "11421244f67553498e5c8112dae02802025bcc4305ec45ad380af95c96f9fe64"
EXPECTED_SAMPLE_SHA256 = "8a9b7fde5c3e6f854be95f124187495222b484770cd685c34fdddd56087c3a3e"
EXPECTED_DATASET_READER_SHA256 = "b913c0c89ed6bea2a7b74b54b64516bfcaad7f7894067ebbac9c5085e47ae069"
EXPECTED_TEMPLATE_RENDERER_SHA256 = "2eb34e08fbdb3d1acb69339505e1e228030b930e2d967b174e67490006adee77"
EXPECTED_SELECTOR_BUILDER_SHA256 = "2e2ac40ed0fe5695a07654052fc72f99d20c91578f841e4b3658697c1771157d"
EXPECTED_CANDIDATE_DESCRIPTION = (
    "separate opt-in use of core.compact_messages(..., query_directed_labels=True); "
    "preserves complete explicit QID choice records and adds only one-hop identity fields "
    "from typed relations[].object, instanceOf, and subclassOf references; absent optional "
    "identity labels are audited while original references stay in complete choice records"
)

DATASET_DEFAULT = (
    Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
)
TOKENIZER_DEFAULT = ROOT / "tmp" / "minimax-m3-tokenizer.json"
TEMPLATE_DEFAULT = ROOT / "tmp" / "minimax-m3-chat-template.jinja"
SAMPLE_DEFAULT = ROOT / "docs/evals/longbench-v2-query-directed-labels-dev-v2-sample-2026-10-18.json"
OUTPUT_DEFAULT = ROOT / "docs/evals/longbench-v2-query-directed-labels-census-2026-10-18.json"

# Deliberately narrow projection: these are the only source-row fields the
# prompt builder and report builder may read. In particular, answer/key and
# model-output fields are never selected, copied, serialized, or hashed.
PROMPT_FIELDS = ("context", "question", "choice_A", "choice_B", "choice_C", "choice_D")
METADATA_FIELDS = ("_id", "domain", "sub_domain", "difficulty", "length")


def _sha256(path: Path) -> str:
    return file_sha256(path)


def _stable_path(path: Path, logical: str) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return logical


def _prompt_row(source_row: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Copy only the allowlisted prompt/metadata fields from a dataset row."""
    if not isinstance(source_row, dict):
        raise ValueError("Expected a LongBench row object")
    # Do not pass source_row to a serializer or generic reporting helper.
    prompt_row = {key: source_row[key] for key in PROMPT_FIELDS}
    metadata = {key: source_row[key] for key in METADATA_FIELDS}
    if not all(isinstance(prompt_row[key], str) for key in PROMPT_FIELDS):
        raise ValueError("Prompt fields must be strings")
    if not isinstance(metadata["_id"], (str, int)):
        raise ValueError("Task ID must be a string or integer")
    return prompt_row, metadata


def _token_counter(tokenizer: Tokenizer):
    cache: dict[str, int] = {}

    def count(messages: list[dict[str, Any]]) -> int:
        rendered = render_minimax(messages)
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        if digest not in cache:
            cache[digest] = len(
                tokenizer.encode(rendered, add_special_tokens=False).ids
            )
        return cache[digest]

    return count


def _prompt_structure(context: str) -> str:
    """Classify source shape without retaining any source text in the report."""
    try:
        if core._research_record_map_bundle(context) is not None:
            return "record_map"
        if core._research_json_array(context) is not None:
            return "json_array"
    except (TypeError, ValueError):
        return "malformed_structured_source"
    return "other"


def _choice_shape(query: str) -> tuple[bool, bool]:
    """Return (supported QID choices, duplicate QID choices), without text."""
    choices = core._prompt_choices(query)
    if len(choices) < 2:
        return False, False
    identifiers: list[str] = []
    for choice in choices:
        found = list(dict.fromkeys(core._LINK_IDS.findall(choice)))
        if len(found) != 1:
            return False, False
        identifiers.append(found[0])
    folded = [identifier.casefold() for identifier in identifiers]
    return True, len(set(folded)) != len(folded)


def _candidate_disposition(
    error_code: str | None,
    *,
    supported_choices: bool,
    duplicate_choices: bool,
    candidate_method_ok: bool,
    candidate_tokens: int | None,
    default_tokens: int | None,
) -> str:
    if duplicate_choices:
        return "ambiguous_records_or_choices"
    if error_code == "query_directed_label_unresolved":
        return "missing_records" if supported_choices else "unsupported_format_or_choices"
    if error_code == "query_directed_label_ambiguous":
        return "ambiguous_records_or_choices"
    if error_code == "research_relation_unsupported":
        return "malformed_refs_or_unsupported_record"
    if error_code == "query_directed_label_target":
        return "target_failure"
    if error_code == "query_directed_label_growth_limit":
        return "growth_failure"
    if error_code is not None:
        return "candidate_failure"
    if not candidate_method_ok:
        return "candidate_wrong_method"
    if candidate_tokens is None or candidate_tokens > TARGET_TOKENS:
        return "target_failure"
    if default_tokens is None:
        return "default_sift_failure"
    if candidate_tokens * 10 > default_tokens * 11:
        return "growth_failure"
    return "candidate_eligible"


def census(
    dataset_path: Path,
    tokenizer_path: Path,
    template_path: Path,
    sample_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    inputs = (
        (dataset_path, "Pinned LongBench v2 dataset"),
        (tokenizer_path, "MiniMax tokenizer"),
        (template_path, "MiniMax chat template"),
        (sample_path, "Frozen query-directed sample manifest"),
    )
    for path, label in inputs:
        if not path.is_file():
            raise FileNotFoundError(f"{label} is unavailable at {path}")

    dataset_sha = _sha256(dataset_path)
    tokenizer_sha = _sha256(tokenizer_path)
    template_sha = _sha256(template_path)
    sample_sha = _sha256(sample_path)
    core_path = ROOT / "src" / "sift" / "core.py"
    core_sha_before = _sha256(core_path)
    reader_path = ROOT / "benchmarks" / "prepare_longbench_v2.py"
    renderer_path = ROOT / "benchmarks" / "prepare_longbench_v2_minimax.py"
    selector_builder_path = ROOT / "benchmarks" / "prepare_longbench_v2_record_ranking_sample.py"

    if dataset_sha != DATASET_SHA256:
        raise ValueError("Pinned LongBench v2 dataset SHA-256 mismatch")
    if tokenizer_sha != EXPECTED_TOKENIZER_SHA256:
        raise ValueError("MiniMax tokenizer SHA-256 differs from the frozen evaluation pin")
    if template_sha != EXPECTED_TEMPLATE_SHA256:
        raise ValueError("MiniMax template SHA-256 differs from the frozen evaluation pin")
    if sample_sha != EXPECTED_SAMPLE_SHA256:
        raise ValueError("Frozen query-directed sample SHA-256 mismatch")
    if core_sha_before != EXPECTED_CORE_SHA256:
        raise ValueError("Sift core SHA-256 differs from the frozen candidate pin")

    reader_sha = _sha256(reader_path)
    renderer_sha = _sha256(renderer_path)
    selector_builder_sha = _sha256(selector_builder_path)
    if reader_sha != EXPECTED_DATASET_READER_SHA256:
        raise ValueError("LongBench dataset reader differs from the frozen evaluation pin")
    if renderer_sha != EXPECTED_TEMPLATE_RENDERER_SHA256:
        raise ValueError("MiniMax template renderer differs from the frozen evaluation pin")
    if selector_builder_sha != EXPECTED_SELECTOR_BUILDER_SHA256:
        raise ValueError("Frozen sample selector builder differs from its expected pin")

    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    sample_method = sample.get("method", {})
    if sample_method.get("dataset_revision") != DATASET_REVISION:
        raise ValueError("Frozen sample dataset revision mismatch")
    if sample_method.get("dataset_sha256") != DATASET_SHA256:
        raise ValueError("Frozen sample dataset SHA-256 mismatch")
    if sample_method.get("candidate_core_sha256") != EXPECTED_CORE_SHA256:
        raise ValueError("Frozen sample does not bind to the pinned Sift core")
    if sample_method.get("target_tokens") != TARGET_TOKENS:
        raise ValueError("Frozen sample target token count differs from this census")
    if sample_method.get("candidate_under_study") != EXPECTED_CANDIDATE_DESCRIPTION:
        raise ValueError("Frozen sample candidate description differs from this census")
    if sample_method.get("dataset_reader_sha256") != reader_sha:
        raise ValueError("Frozen sample dataset-reader hash differs from the current file")
    if sample_method.get("dataset_reader_sha256") != EXPECTED_DATASET_READER_SHA256:
        raise ValueError("Frozen sample dataset-reader hash differs from the expected pin")
    if sample_method.get("template_renderer_sha256") != renderer_sha:
        raise ValueError("Frozen sample template-renderer hash differs from the current file")
    if sample_method.get("template_renderer_sha256") != EXPECTED_TEMPLATE_RENDERER_SHA256:
        raise ValueError("Frozen sample template-renderer hash differs from the expected pin")
    if sample_method.get("selector_builder_sha256") != selector_builder_sha:
        raise ValueError("Frozen sample selector-builder hash differs from the current file")
    if sample_method.get("selector_builder_sha256") != EXPECTED_SELECTOR_BUILDER_SHA256:
        raise ValueError("Frozen sample selector-builder hash differs from the expected pin")
    selected = sample.get("selected")
    if not isinstance(selected, list) or len(selected) != 20:
        raise ValueError("Expected exactly 20 rows in the frozen sample manifest")
    split_by_id: dict[str, str] = {}
    structure_by_id: dict[str, str] = {}
    for item in selected:
        if not isinstance(item, dict):
            raise ValueError("Malformed frozen sample row")
        task_id = str(item["id"])
        split = item.get("split")
        if split not in {"development", "held_out"} or task_id in split_by_id:
            raise ValueError("Frozen sample has invalid or duplicate split metadata")
        split_by_id[task_id] = split
        # This value is metadata only; the sample manifest contains no task text.
        structure_by_id[task_id] = str(item.get("structure", "unknown"))
    if sum(value == "development" for value in split_by_id.values()) != 10:
        raise ValueError("Frozen sample development split count changed")
    if sum(value == "held_out" for value in split_by_id.values()) != 10:
        raise ValueError("Frozen sample held-out split count changed")

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    count_tokens = _token_counter(tokenizer)
    rows: list[dict[str, Any]] = []
    for source_row in iter_json_array(dataset_path):
        prompt_row, metadata = _prompt_row(source_row)
        task_id = str(metadata["_id"])
        context = prompt_row["context"]
        messages = make_messages(prompt_row)
        full_tokens = count_tokens(messages)
        raw_limit = max(1_000_000, full_tokens)
        split = split_by_id.get(task_id, "not_in_frozen_sample")
        structure = _prompt_structure(messages[1]["content"])
        question = messages[-1]["content"]
        supported_choices, duplicate_choices = _choice_shape(question)

        default_tokens: int | None = None
        default_error_code: str | None = None
        candidate_tokens: int | None = None
        candidate_method: str | None = None
        candidate_error_code: str | None = None
        candidate_projected_labels: int | None = None
        candidate_unresolved_labels: int | None = None
        candidate_prompt_sha256: str | None = None

        try:
            default_result = core.compact_messages(
                messages,
                count_tokens,
                target=TARGET_TOKENS,
                raw_limit=raw_limit,
                protocol="openai",
            )
            default_tokens = int(default_result.audit["forwarded_tokens"])
        except core.CompactionError as error:
            default_error_code = error.code or "compaction_error"

        disposition: str
        if full_tokens <= TARGET_TOKENS:
            # Default Sift is still measured above; the query-directed path is
            # intentionally not invoked for rows where compaction is inactive.
            disposition = "below_target"
        else:
            try:
                candidate_result = core.compact_messages(
                    messages,
                    count_tokens,
                    target=TARGET_TOKENS,
                    raw_limit=raw_limit,
                    protocol="openai",
                    query_directed_labels=True,
                )
                candidate_tokens = int(candidate_result.audit["forwarded_tokens"])
                candidate_method = str(candidate_result.audit.get("method", "")) or None
                candidate_projected_labels = int(
                    candidate_result.audit.get("projected_identity_labels", 0)
                )
                candidate_unresolved_labels = int(
                    candidate_result.audit.get("unresolved_identity_labels", 0)
                )
                rendered_candidate = render_minimax(candidate_result.messages)
                candidate_prompt_sha256 = hashlib.sha256(
                    rendered_candidate.encode("utf-8")
                ).hexdigest()
            except core.CompactionError as error:
                candidate_error_code = error.code or "compaction_error"

            disposition = _candidate_disposition(
                candidate_error_code,
                supported_choices=supported_choices,
                duplicate_choices=duplicate_choices,
                candidate_method_ok=(candidate_method == "query_directed_one_hop_identity_labels"),
                candidate_tokens=candidate_tokens,
                default_tokens=default_tokens,
            )
            if default_error_code is not None and disposition == "candidate_eligible":
                disposition = "default_sift_failure"

        growth_ok = (
            candidate_tokens is not None
            and default_tokens is not None
            and candidate_tokens * 10 <= default_tokens * 11
        ) if full_tokens > TARGET_TOKENS else None
        candidate_gate = (
            disposition == "candidate_eligible"
            and candidate_method == "query_directed_one_hop_identity_labels"
            and candidate_tokens is not None
            and candidate_tokens <= TARGET_TOKENS
            and growth_ok is True
        ) if full_tokens > TARGET_TOKENS else None

        rows.append({
            "id": task_id,
            "split": split,
            "structure": structure,
            "frozen_sample_structure": structure_by_id.get(task_id),
            "domain": metadata["domain"],
            "sub_domain": metadata["sub_domain"],
            "difficulty": metadata["difficulty"],
            "length": metadata["length"],
            "full_prompt_tokens": full_tokens,
            "raw_limit_tokens_offline_only": raw_limit,
            "default_sift_tokens": default_tokens,
            "default_sift_error_code": default_error_code,
            "candidate_tokens": candidate_tokens,
            "candidate_method": candidate_method,
            "candidate_projected_identity_label_count": candidate_projected_labels,
            "candidate_unresolved_optional_identity_label_count": candidate_unresolved_labels,
            "candidate_error_code": candidate_error_code,
            "candidate_disposition": disposition,
            "candidate_growth_within_10pct_of_default": growth_ok,
            "candidate_gate_pass": candidate_gate,
            "full_context_within_historical_route_cap": full_tokens <= HISTORICAL_ROUTE_PROMPT_LIMIT,
            "default_sift_within_historical_route_cap": (
                default_tokens <= HISTORICAL_ROUTE_PROMPT_LIMIT if default_tokens is not None else None
            ),
            "candidate_within_historical_route_cap": (
                candidate_tokens <= HISTORICAL_ROUTE_PROMPT_LIMIT
                if candidate_tokens is not None else None
            ),
            "historical_route_cap_source_date": HISTORICAL_ROUTE_OBSERVED_DATE,
            "live_route_verified": False,
            "source_prompt_sha256": hashlib.sha256(
                render_minimax(messages).encode("utf-8")
            ).hexdigest(),
            "candidate_prompt_sha256": candidate_prompt_sha256,
        })

    if len(rows) != 503:
        raise ValueError(f"Expected 503 pinned LongBench rows, observed {len(rows)}")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Dataset contains duplicate task IDs")
    if set(split_by_id) - {row["id"] for row in rows}:
        raise ValueError("Frozen sample contains IDs absent from the pinned dataset")

    # Detect mutation of any pinned input or implementation during the scan.
    post_run_hashes = {
        "dataset": _sha256(dataset_path),
        "tokenizer": _sha256(tokenizer_path),
        "template": _sha256(template_path),
        "sample": _sha256(sample_path),
        "dataset_reader": _sha256(reader_path),
        "template_renderer": _sha256(renderer_path),
        "selector_builder": _sha256(selector_builder_path),
    }
    expected_post_run_hashes = {
        "dataset": dataset_sha,
        "tokenizer": tokenizer_sha,
        "template": template_sha,
        "sample": sample_sha,
        "dataset_reader": reader_sha,
        "template_renderer": renderer_sha,
        "selector_builder": selector_builder_sha,
    }
    changed_inputs = sorted(
        name for name, expected in expected_post_run_hashes.items()
        if post_run_hashes[name] != expected
    )
    if changed_inputs:
        raise ValueError(
            "Pinned census inputs changed during the scan: " + ", ".join(changed_inputs)
        )
    core_sha_after = _sha256(core_path)
    if core_sha_after != core_sha_before:
        raise ValueError("Sift core changed while the census was running")

    disposition_counts = Counter(row["candidate_disposition"] for row in rows)
    route_fit_counts = {
        field: sum(row[field] is True for row in rows)
        for field in (
            "full_context_within_historical_route_cap",
            "default_sift_within_historical_route_cap",
            "candidate_within_historical_route_cap",
        )
    }
    by_split: dict[str, dict[str, int]] = {}
    by_structure: dict[str, dict[str, int]] = {}
    by_domain: dict[str, dict[str, int]] = {}
    for group_field, destination in (
        ("split", by_split),
        ("structure", by_structure),
        ("domain", by_domain),
    ):
        groups = sorted({str(row[group_field]) for row in rows})
        for group in groups:
            members = [row for row in rows if str(row[group_field]) == group]
            destination[group] = dict(Counter(row["candidate_disposition"] for row in members))

    artifact = {
        "schema_version": 1,
        "title": "LongBench v2 query-directed labels answer-blind eligibility census",
        "status": "offline mechanical census only; no model/API calls; no accuracy or quality inference",
        "safeguards": {
            "answer_blind": True,
            "model_outputs_accessed": False,
            "network_calls": 0,
            "api_calls": 0,
            "row_field_allowlist": list(PROMPT_FIELDS + METADATA_FIELDS),
            "answer_or_key_fields_selected_or_serialized": False,
            "prompt_text_or_candidate_messages_written": False,
            "note": "The dataset parser decodes each row as JSON, but application code copies only the allowlisted prompt and metadata fields; census code never selects, reads, uses, hashes, or serializes answer/key values or model outputs.",
            "held_out_note": "Frozen held-out task text is processed mechanically for structural/token eligibility only. This is not an accuracy evaluation and provides no held-out quality evidence.",
        },
        "method": {
            "dataset_rows_expected": 503,
            "target_tokens": TARGET_TOKENS,
            "candidate_strategy": "core.compact_messages(..., query_directed_labels=True)",
            "per_row_work": "Count the full MiniMax-rendered prompt and run default Sift on every row; only rows over target run query-directed candidate compaction.",
            "candidate_gate": "Candidate uses the expected one-hop identity-label method, fits target, and is at most 110% of default Sift tokens.",
            "raw_limit": "max(1,000,000, exact full prompt token count), used only to permit offline compaction analysis; this does not qualify a prompt for live dispatch.",
            "historical_route_cap": {
                "tokens": HISTORICAL_ROUTE_PROMPT_LIMIT,
                "observed_date": HISTORICAL_ROUTE_OBSERVED_DATE,
                "live_route_verified": False,
                "interpretation": "Historical context-fit flags only; refresh current OpenRouter route metadata before any dispatch decision.",
            },
            "output_policy": "Per-row metadata, task/prompt hashes, token counts, booleans, method names, and error/disposition codes only; no source or candidate prompt text.",
        },
        "inputs": {
            "dataset_id": "zai-org/LongBench-v2",
            "dataset_revision": DATASET_REVISION,
            "dataset_sha256": dataset_sha,
            "dataset_path": _stable_path(dataset_path, "pinned LongBench v2 dataset"),
            "tokenizer_id": "MiniMaxAI/MiniMax-M3 tokenizer",
            "tokenizer_sha256": tokenizer_sha,
            "tokenizer_path": _stable_path(tokenizer_path, "MiniMax tokenizer"),
            "template_sha256": template_sha,
            "template_path": _stable_path(template_path, "MiniMax chat template"),
            "template_renderer_path": "benchmarks/prepare_longbench_v2_minimax.py",
            "template_renderer_sha256": renderer_sha,
            "dataset_reader_path": "benchmarks/prepare_longbench_v2.py",
            "dataset_reader_sha256": reader_sha,
            "selector_builder_path": "benchmarks/prepare_longbench_v2_record_ranking_sample.py",
            "selector_builder_sha256": selector_builder_sha,
            "frozen_sample_path": _stable_path(sample_path, "frozen query-directed sample manifest"),
            "frozen_sample_sha256": sample_sha,
            "sift_core_path": "src/sift/core.py",
            "sift_core_sha256": core_sha_before,
            "census_script_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "census_script_sha256": _sha256(Path(__file__).resolve()),
            "tokenizers_version": __import__("tokenizers").__version__,
        },
        "summary": {
            "rows": len(rows),
            "candidate_runs": sum(row["full_prompt_tokens"] > TARGET_TOKENS for row in rows),
            "below_target_rows": sum(row["candidate_disposition"] == "below_target" for row in rows),
            "candidate_eligible_rows": disposition_counts["candidate_eligible"],
            "dispositions": {key: disposition_counts[key] for key in sorted(disposition_counts)},
            "historical_route_fit_rows": route_fit_counts,
            "historical_route_cap_live_verified": False,
            "by_split": by_split,
            "by_structure": by_structure,
            "by_domain": by_domain,
        },
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--sample", type=Path, default=SAMPLE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()
    artifact = census(
        args.dataset,
        args.tokenizer,
        args.template,
        args.sample,
        args.output,
    )
    print(json.dumps({"output": str(args.output), "summary": artifact["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
