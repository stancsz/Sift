"""Combine answer-blind LongBench candidate census summaries.

This script reads only the structural/token-count census reports. It does not
read the dataset, prompts, answers, answer keys, or model outputs. The union is
mechanical eligibility across separate opt-in modes, not a supported combined
dispatcher or evidence of answer quality.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIELD_DEFAULT = ROOT / "docs/evals/longbench-v2-field-pruning-census-current-2026-10-18.json"
QUERY_DEFAULT = ROOT / "docs/evals/longbench-v2-query-directed-labels-census-2026-10-18.json"
MANIFEST_DEFAULT = ROOT / "docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json"
OUTPUT_DEFAULT = ROOT / "docs/evals/longbench-v2-candidate-census-union-2026-10-18.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def build(field_path: Path, query_path: Path, manifest_path: Path,
          output_path: Path) -> dict[str, Any]:
    field = load(field_path)
    query = load(query_path)
    manifest = load(manifest_path)
    field_inputs = field.get("inputs", {})
    query_inputs = query.get("inputs", {})
    manifest_dataset = manifest.get("dataset", {})
    field_method = field.get("method", {})
    query_method = query.get("method", {})
    for name, report in (("field-pruning", field), ("query-directed", query)):
        status = report.get("status")
        if report.get("schema_version") != 1 or not isinstance(status, str) \
                or "offline" not in status.casefold():
            raise ValueError(f"Unexpected {name} census schema/status")

    if field_method.get("target_tokens") != 32_640 \
            or field_method.get("rows_scanned") != 503 \
            or query_method.get("target_tokens") != 32_640:
        raise ValueError("Both censuses must use 503 rows and the 32,640-token target")

    shared = {
        "dataset_id": (field_inputs.get("dataset_id"), query_inputs.get("dataset_id")),
        "dataset_revision": (field_inputs.get("dataset_revision"),
                             query_inputs.get("dataset_revision")),
        "dataset_sha256": (field_inputs.get("dataset_sha256"),
                           query_inputs.get("dataset_sha256")),
        "tokenizer_sha256": (field_inputs.get("tokenizer_sha256"),
                             query_inputs.get("tokenizer_sha256")),
        "template_sha256": (field_inputs.get("template_sha256"),
                            query_inputs.get("template_sha256")),
        "core_sha256": (field_inputs.get("core_sha256"),
                        query_inputs.get("sift_core_sha256")),
    }
    mismatches = [name for name, pair in shared.items()
                  if not pair[0] or pair[0] != pair[1]]
    if mismatches:
        raise ValueError(f"Census inputs differ or are missing: {mismatches}")
    if field_inputs.get("dataset_id") != manifest_dataset.get("id") \
            or field_inputs.get("dataset_revision") != manifest_dataset.get("revision") \
            or field_inputs.get("dataset_sha256") != manifest_dataset.get("data_file_sha256") \
            or not str(manifest_dataset.get("split", "")).startswith("train"):
        raise ValueError("Census and baseline manifest dataset identity/split differ")

    field_rows = field.get("rows")
    query_rows = query.get("rows")
    if not isinstance(field_rows, list) or not isinstance(query_rows, list):
        raise ValueError("Both census reports must contain row metadata")
    expected = 503
    if len(field_rows) != expected or len(query_rows) != expected:
        raise ValueError("Both census reports must contain exactly 503 rows")
    def row_ids(rows: list[dict[str, Any]], label: str) -> set[str]:
        values = [str(row.get("id", "")) for row in rows]
        if any(not re.fullmatch(r"[0-9a-f]{24}", value) for value in values):
            raise ValueError(f"{label} report contains an invalid task ID")
        if len(set(values)) != expected:
            raise ValueError(f"{label} report has duplicate IDs")
        return set(values)

    field_universe = row_ids(field_rows, "Field-pruning")
    query_universe = row_ids(query_rows, "Query-directed")
    if field_universe != query_universe:
        raise ValueError("Census row ID universes do not match")
    field_by_id = {str(row["id"]): row for row in field_rows}
    query_by_id = {str(row["id"]): row for row in query_rows}
    for task_id in field_universe:
        if (field_by_id[task_id].get("domain"), field_by_id[task_id].get("sub_domain")) != (
                query_by_id[task_id].get("domain"), query_by_id[task_id].get("sub_domain")):
            raise ValueError(f"Census metadata differs for task {task_id}")

    field_eligible = {
        str(row["id"]): row for row in field_rows
        if row.get("active_eligible") is True
    }
    query_eligible = {
        str(row["id"]): row for row in query_rows
        if row.get("candidate_gate_pass") is True
    }
    field_ids = set(field_eligible)
    query_ids = set(query_eligible)
    shared_ids = field_ids & query_ids
    union_ids = field_ids | query_ids
    all_rows = query_by_id

    def domain_counts(ids: set[str]) -> dict[str, int]:
        counts = Counter(all_rows[task_id]["domain"] for task_id in ids)
        return dict(sorted(counts.items()))

    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 100:
        raise ValueError("Expected exactly 100 cases in the baseline manifest")
    baseline_ids = {str(case.get("id", "")) for case in cases
                    if isinstance(case, dict)}
    if len(baseline_ids) != 100:
        raise ValueError("Baseline manifest IDs are missing or duplicated")
    if any(not re.fullmatch(r"[0-9a-f]{24}", task_id) for task_id in baseline_ids):
        raise ValueError("Baseline manifest contains an invalid task ID")
    field_pilot = set(field.get("overlap", {}).get(
        "field_pruning_four_task_pilot", {}).get("pilot_case_ids_from_literal_CASE_IDS", []))
    query_splits = Counter(query_eligible[task_id].get("split", "unknown")
                           for task_id in query_ids)
    artifact = {
        "schema_version": 1,
        "evaluation": "LongBench v2 answer-blind candidate census comparison",
        "status": "coverage_only_no_dispatcher_no_accuracy_evidence",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "field_census": field_path.relative_to(ROOT).as_posix(),
            "field_census_sha256": sha256(field_path),
            "query_census": query_path.relative_to(ROOT).as_posix(),
            "query_census_sha256": sha256(query_path),
            "baseline_manifest": manifest_path.relative_to(ROOT).as_posix(),
            "baseline_manifest_sha256": sha256(manifest_path),
            "comparison_script": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "comparison_script_sha256": sha256(Path(__file__).resolve()),
            "dataset_revision": field_inputs["dataset_revision"],
            "dataset_sha256": field_inputs["dataset_sha256"],
            "tokenizer_sha256": field_inputs["tokenizer_sha256"],
            "template_sha256": field_inputs["template_sha256"],
            "core_sha256": field_inputs["core_sha256"],
            "target_tokens": 32_640,
            "row_count": expected,
        },
        "summary": {
            "field_pruning_eligible": len(field_ids),
            "query_directed_eligible": len(query_ids),
            "overlap": len(shared_ids),
            "mechanical_union_upper_bound": len(union_ids),
            "field_pruning_domains": domain_counts(field_ids),
            "query_directed_domains": domain_counts(query_ids),
            "union_domains": domain_counts(union_ids),
            "field_eligible_in_original_100_task_sample": len(field_ids & baseline_ids),
            "query_eligible_in_original_100_task_sample": len(query_ids & baseline_ids),
            "union_in_original_100_task_sample": len(union_ids & baseline_ids),
            "field_eligible_in_field_pruning_pilot": len(field_ids & field_pilot),
            "query_eligible_by_frozen_query_sample_split": dict(sorted(query_splits.items())),
        },
        "ids": {
            "field_pruning": sorted(field_ids),
            "query_directed": sorted(query_ids),
            "overlap": sorted(shared_ids),
            "mechanical_union_upper_bound": sorted(union_ids),
            "union_already_in_original_100_task_sample": sorted(union_ids & baseline_ids),
            "field_pruning_pilot_exposure": sorted(field_ids & field_pilot),
        },
        "interpretation": [
            "The two opt-in selectors remain mutually exclusive in Sift; this union is not a validated combined dispatcher.",
            "Mechanical target fit and structure coverage do not establish answer quality, noninferiority, or savings.",
            "The query census processed frozen development and held-out prompt text answer-blind; those rows are not untouched confirmatory evidence.",
            "The current eligible population is too small and too exposed to support a 100-task active-candidate MiniMax study. Do not dispatch paid candidate evaluation from this report.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--field-census", type=Path, default=FIELD_DEFAULT)
    parser.add_argument("--query-census", type=Path, default=QUERY_DEFAULT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()
    artifact = build(args.field_census, args.query_census, args.manifest, args.output)
    print(json.dumps({"output": str(args.output), "summary": artifact["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
