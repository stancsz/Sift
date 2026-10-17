"""Build a deterministic, offline census of the LongBench v2 field-pruning path.

This command reads only the pinned local LongBench JSON and the local MiniMax
tokenizer/template files. It does not download data, contact an API, or infer
answer quality. See --help for the default input and output paths.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
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
DATASET_DEFAULT = (
    Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
)
TOKENIZER_DEFAULT = ROOT / "tmp" / "minimax-m3-tokenizer.json"
TEMPLATE_DEFAULT = ROOT / "tmp" / "minimax-m3-chat-template.jinja"
OUTPUT_DEFAULT = ROOT / "docs" / "evals" / "longbench-v2-field-pruning-census-2026-10-17.json"
MANIFEST_DEFAULT = ROOT / "docs" / "evals" / "longbench-v2-minimax-m3-100-manifest-2026-10-16.json"
PILOT_RUNNER_DEFAULT = ROOT / "benchmarks" / "run_longbench_v2_minimax_field_pruning_pilot.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"{label} is unavailable at {path}. Supply its existing local path; "
            "this census intentionally does not download inputs."
        )


def _path_label(path: Path, *, logical: str) -> str:
    """Return a stable, non-user-specific source label for the artifact."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return logical


def _token_counter(tokenizer: Tokenizer):
    # Core calls the counter again on the original full prompt when it enters
    # compaction. Cache by the exact rendered request so each row's full prompt
    # is tokenizer-encoded once while still counting changed outputs exactly.
    full_render_counts: dict[str, int] = {}

    def count(messages: list[dict[str, Any]]) -> int:
        rendered = render_minimax(messages)
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        cached = full_render_counts.get(digest)
        if cached is not None:
            return cached
        value = len(tokenizer.encode(rendered, add_special_tokens=False).ids)
        full_render_counts[digest] = value
        return value

    return count


def _selector_probe(context: str, query: str) -> tuple[list[str], list[str]]:
    """Call the same root-JSON and explicit-CSV helpers used by core."""
    choices = core._prompt_choices(query)
    if not choices:
        return [], []
    hits: list[str] = []
    errors: list[str] = []
    try:
        if core._field_pruned_root_source(context, choices) is not None:
            hits.append("root_json")
    except core.CompactionError as exc:
        errors.append(f"root_json:{exc.code}")
    try:
        if core._csv_complete_groups(context, query, choices) is not None:
            hits.append("explicit_csv")
    except core.CompactionError as exc:
        errors.append(f"explicit_csv:{exc.code}")
    return hits, errors


def _grouped(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(row[key]) for row in rows)
    return {name: counts[name] for name in sorted(counts)}


def _pilot_ids_from_runner(path: Path) -> list[str]:
    """Read the runner's literal CASE_IDS without importing or executing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "CASE_IDS" for target in targets):
                value = ast.literal_eval(node.value)
                if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
                    return list(value)
    raise ValueError(f"Could not find a literal CASE_IDS tuple in {path}")


def census(
    dataset_path: Path,
    tokenizer_path: Path,
    template_path: Path,
    output_path: Path,
    manifest_path: Path,
    pilot_runner_path: Path,
) -> dict[str, Any]:
    for path, label in (
        (dataset_path, "Pinned LongBench v2 dataset"),
        (tokenizer_path, "MiniMax tokenizer"),
        (template_path, "MiniMax chat template"),
        (manifest_path, "Frozen LongBench 100-task manifest"),
        (pilot_runner_path, "Field-pruning pilot runner"),
    ):
        _require_file(path, label)
    observed_dataset_sha = file_sha256(dataset_path)
    if observed_dataset_sha != DATASET_SHA256:
        raise ValueError(
            "Pinned LongBench v2 dataset SHA-256 mismatch: "
            f"expected {DATASET_SHA256}, observed {observed_dataset_sha} at {dataset_path}"
        )

    frozen_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (frozen_manifest.get("dataset", {}).get("revision") != DATASET_REVISION
            or frozen_manifest.get("dataset", {}).get("data_file_sha256") != DATASET_SHA256):
        raise ValueError("Frozen 100-task manifest does not bind to the pinned dataset revision and SHA")
    expected_tokenizer_sha = frozen_manifest.get("model", {}).get("tokenizer_sha256")
    expected_template_sha = frozen_manifest.get("model", {}).get("chat_template_sha256")
    observed_tokenizer_sha = _sha256(tokenizer_path)
    observed_template_sha = _sha256(template_path)
    if observed_tokenizer_sha != expected_tokenizer_sha:
        raise ValueError(
            "Local MiniMax tokenizer SHA-256 differs from the frozen 100-task manifest: "
            f"expected {expected_tokenizer_sha}, observed {observed_tokenizer_sha}"
        )
    if observed_template_sha != expected_template_sha:
        raise ValueError(
            "Local MiniMax chat-template SHA-256 differs from the frozen 100-task manifest: "
            f"expected {expected_template_sha}, observed {observed_template_sha}"
        )
    manifest_cases = frozen_manifest.get("cases")
    if not isinstance(manifest_cases, list) or len(manifest_cases) != 100:
        raise ValueError(f"Expected exactly 100 cases in {manifest_path}")
    frozen_manifest_ids = [str(row["id"]) for row in manifest_cases]
    if len(set(frozen_manifest_ids)) != len(frozen_manifest_ids):
        raise ValueError("Frozen 100-task manifest contains duplicate IDs")
    pilot_ids = _pilot_ids_from_runner(pilot_runner_path)
    if len(pilot_ids) != 4 or len(set(pilot_ids)) != 4:
        raise ValueError(f"Expected four unique pilot CASE_IDS in {pilot_runner_path}")

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    count_tokens = _token_counter(tokenizer)
    rows: list[dict[str, Any]] = []
    disposition_counts: Counter[str] = Counter()
    selector_counts: Counter[str] = Counter()
    structural_ids: list[str] = []
    active_eligible_ids: list[str] = []
    selector_error_ids: list[str] = []

    for source_row in iter_json_array(dataset_path):
        messages = make_messages(source_row)
        context = messages[1]["content"]
        query = messages[-1]["content"]
        full_tokens = count_tokens(messages)
        hits, selector_errors = _selector_probe(context, query)
        for hit in hits:
            selector_counts[hit] += 1
        if hits:
            structural_ids.append(str(source_row["_id"]))
        if selector_errors:
            selector_error_ids.append(str(source_row["_id"]))

        default_tokens: int | None = None
        candidate_tokens: int | None = None
        candidate_method: str | None = None
        candidate_error: str | None = None
        eligible = False

        # The ordinary and candidate results are relevant only when compaction
        # is active. Below-target selector matches remain visible in the census.
        if full_tokens <= TARGET_TOKENS:
            if hits:
                disposition = "below_target_structural_selector_hit"
            elif selector_errors:
                disposition = "below_target_selector_error"
            else:
                disposition = "below_target_no_selector_hit"
        elif not hits:
            # Both production candidate branches are rooted in these exact
            # helper results. If neither helper finds a source, neither default
            # compaction nor the experimental branch is needed for eligibility.
            if selector_errors:
                disposition = "above_target_selector_error"
                candidate_error = ";".join(selector_errors)
            else:
                disposition = "above_target_no_selector_hit"
        else:
            try:
                default_result = core.compact_messages(
                    messages, count_tokens, target=TARGET_TOKENS,
                    raw_limit=1_000_000, protocol="openai",
                )
                default_tokens = int(default_result.audit["forwarded_tokens"])
            except core.CompactionError as exc:
                candidate_error = f"default_sift:{exc.code}"
                disposition = "above_target_default_sift_error"
            else:
                try:
                    candidate_result = core.compact_messages(
                        messages, count_tokens, target=TARGET_TOKENS,
                        raw_limit=1_000_000, protocol="openai", field_pruning=True,
                    )
                    candidate_method = str(candidate_result.audit.get("method", "")) or None
                    candidate_tokens = int(candidate_result.audit["forwarded_tokens"])
                    eligible = (
                        candidate_method == "field_pruning_candidate"
                        and candidate_tokens <= TARGET_TOKENS
                        and candidate_tokens * 10 <= default_tokens * 11
                    )
                    if eligible:
                        disposition = "active_eligible"
                        active_eligible_ids.append(str(source_row["_id"]))
                    elif candidate_method == "field_pruning_candidate":
                        disposition = "above_target_candidate_failed_token_or_growth_gate"
                    else:
                        disposition = "above_target_candidate_wrong_method"
                except core.CompactionError as exc:
                    candidate_error = exc.code
                    disposition = "above_target_candidate_error"

        disposition_counts[disposition] += 1
        record = {
            "id": str(source_row["_id"]),
            "domain": source_row.get("domain"),
            "sub_domain": source_row.get("sub_domain"),
            "difficulty": source_row.get("difficulty"),
            "length": source_row.get("length"),
            "full_prompt_tokens": full_tokens,
            "default_sift_tokens": default_tokens,
            "candidate_tokens": candidate_tokens,
            "candidate_method": candidate_method,
            "selector_hits": hits,
            "selector_errors": selector_errors,
            "candidate_error": candidate_error,
            "active_eligible": eligible,
            "disposition": disposition,
        }
        rows.append(record)

    if len(rows) != 503:
        raise ValueError(f"Expected exactly 503 pinned LongBench v2 rows; observed {len(rows)}")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Pinned LongBench v2 census contains duplicate row IDs")

    manifest_id_set = set(frozen_manifest_ids)
    pilot_id_set = set(pilot_ids)
    structural_set = set(structural_ids)
    eligible_set = set(active_eligible_ids)

    artifact = {
        "schema_version": 1,
        "evaluation": "offline LongBench v2 field-pruning selector eligibility census",
        "status": "offline census only; no API calls; no remote reads; no result-quality inference",
        "method": {
            "rows_scanned": len(rows),
            "target_tokens": TARGET_TOKENS,
            "candidate_definition": (
                "full prompt exceeds target; default Sift compaction succeeds; "
                "field_pruning=True returns method=field_pruning_candidate; "
                "candidate meets target; candidate tokens are at most 110% of default Sift tokens"
            ),
            "selector_probe": (
                "For every row, call core._field_pruned_root_source on the context and "
                "core._csv_complete_groups on the context plus explicit prompt, including "
                "rows already below target. These are the core candidate-path helpers."
            ),
            "compaction_scope": (
                "Run default and candidate compaction only for above-target rows "
                "with a direct root-JSON or explicit-CSV selector hit. All rows are "
                "still scanned and probed; non-hit/below-target compaction counts are null."
            ),
            "full_prompt_tokenization": "Each distinct rendered full prompt is tokenizer-encoded once; subsequent core counts of that unchanged prompt use a SHA-256-keyed exact-count cache.",
            "quality_note": "This artifact measures selector-path structure, token fit, and eligibility only; it does not call a model or inspect answer keys.",
        },
        "inputs": {
            "dataset_id": "zai-org/LongBench-v2",
            "dataset_revision": DATASET_REVISION,
            "dataset_split": "train",
            "dataset_rows_expected": 503,
            "dataset_sha256": observed_dataset_sha,
            "dataset_path_at_build": _path_label(
                dataset_path, logical=f"~/.cache/sift-longbench-v2/{DATASET_REVISION}/data.json"
            ),
            "tokenizer_path_at_build": _path_label(
                tokenizer_path, logical="local MiniMax tokenizer (path supplied to builder)"
            ),
            "tokenizer_sha256": observed_tokenizer_sha,
            "tokenizers_library_version": __import__("tokenizers").__version__,
            "template_path_at_build": _path_label(
                template_path, logical="local MiniMax chat template (path supplied to builder)"
            ),
            "template_sha256": observed_template_sha,
            "template_renderer": "benchmarks/prepare_longbench_v2_minimax.py::render_minimax",
            "template_renderer_sha256": _sha256(ROOT / "benchmarks" / "prepare_longbench_v2_minimax.py"),
            "core_path": "src/sift/core.py",
            "core_sha256": _sha256(ROOT / "src" / "sift" / "core.py"),
            "dataset_reader_path": "benchmarks/prepare_longbench_v2.py",
            "dataset_reader_sha256": _sha256(ROOT / "benchmarks" / "prepare_longbench_v2.py"),
            "builder_path": "benchmarks/census_longbench_v2_field_pruning.py",
            "builder_sha256": _sha256(Path(__file__).resolve()),
            "frozen_100_task_manifest_path": _path_label(
                manifest_path, logical="frozen 100-task manifest (path supplied to builder)"
            ),
            "frozen_100_task_manifest_sha256": _sha256(manifest_path),
            "field_pruning_pilot_runner_path": _path_label(
                pilot_runner_path, logical="field-pruning pilot runner (path supplied to builder)"
            ),
            "field_pruning_pilot_runner_sha256": _sha256(pilot_runner_path),
        },
        "summary": {
            "rows": len(rows),
            "full_prompts_at_or_below_target": sum(row["full_prompt_tokens"] <= TARGET_TOKENS for row in rows),
            "structural_selector_hits": len(structural_ids),
            "selector_hit_rows_by_path": {key: selector_counts[key] for key in sorted(selector_counts)},
            "selector_error_rows": len(selector_error_ids),
            "active_eligible_cases": len(active_eligible_ids),
            "dispositions": {key: disposition_counts[key] for key in sorted(disposition_counts)},
            "eligible_by_domain": _grouped([row for row in rows if row["active_eligible"]], "domain"),
            "eligible_by_sub_domain": _grouped([row for row in rows if row["active_eligible"]], "sub_domain"),
            "eligible_by_difficulty": _grouped([row for row in rows if row["active_eligible"]], "difficulty"),
        },
        "ids": {
            "structural_selector_hits": sorted(structural_ids),
            "active_eligible_cases": sorted(active_eligible_ids),
            "selector_error_rows": sorted(selector_error_ids),
        },
        "overlap": {
            "frozen_100_task_manifest": {
                "input_artifact": str(manifest_path.relative_to(ROOT)),
                "input_sha256": _sha256(manifest_path),
                "manifest_case_count": len(frozen_manifest_ids),
                "structural_selector_hit_intersection": sorted(structural_set & manifest_id_set),
                "active_eligible_intersection": sorted(eligible_set & manifest_id_set),
            },
            "field_pruning_four_task_pilot": {
                "input_artifact": str(pilot_runner_path.relative_to(ROOT)),
                "input_sha256": _sha256(pilot_runner_path),
                "pilot_case_ids_from_literal_CASE_IDS": sorted(pilot_id_set),
                "structural_selector_hit_intersection": sorted(structural_set & pilot_id_set),
                "active_eligible_intersection": sorted(eligible_set & pilot_id_set),
            },
        },
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--pilot-runner", type=Path, default=PILOT_RUNNER_DEFAULT)
    args = parser.parse_args()
    artifact = census(args.dataset, args.tokenizer, args.template, args.output,
                      args.manifest, args.pilot_runner)
    print(json.dumps({"output": str(args.output), "summary": artifact["summary"],
                      "ids": artifact["ids"], "overlap": artifact["overlap"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
