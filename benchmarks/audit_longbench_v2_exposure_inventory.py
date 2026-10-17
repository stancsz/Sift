#!/usr/bin/env python3
"""Create a reproducible, ID-only inventory of local LongBench v2 exposure.

The scanner walks .runs, docs/evals, and docs/results (including ignored and
untracked files), hashes every JSON-family file, and decodes only JSON keys
and values in allowlisted LongBench task-ID fields. All other values are
skipped lexically; prompts, answers, and model responses are never decoded or
written to the report. The pinned source dataset is hashed as bytes, without
parsing its JSON content for exposure IDs.

No network or model calls are made.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RELATIVE_ROOTS = (Path(".runs"), Path("docs/evals"), Path("docs/results"))
PINNED_DATASET = Path(".runs/longbench-v2-data-pinned.json")
ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
SINGLE_ID_FIELDS = {"id", "task_id", "question_id"}
ARRAY_ID_FIELDS = {
    "ids", "task_ids", "question_ids", "selected_ids", "exposed_ids",
    "candidate_ids", "eligible_ids", "development_ids", "held_out_ids",
    "holdout_ids", "universe_ids", "excluded_ids", "sample_ids",
}
EXCLUDED_ID_FIELD_PARTS = ("provider", "request", "response", "commit", "run", "trace", "span")
JSON_SUFFIXES = {".json", ".jsonl", ".ndjson", ".gz"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_opener(path: Path):
    return gzip.open if path.suffix.lower() == ".gz" else open


def is_json_family(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() in JSON_SUFFIXES or name.endswith((".json.tmp", ".jsonl.tmp", ".ndjson.tmp"))


def skip_value(source: str, position: int) -> int:
    """Skip one JSON value without decoding scalar contents."""
    while position < len(source) and source[position].isspace():
        position += 1
    if position >= len(source):
        raise ValueError("unexpected end of JSON")
    first = source[position]
    if first in "[{":
        stack = ["]" if first == "[" else "}"]
        position += 1
        in_string = escaped = False
        while position < len(source) and stack:
            char = source[position]
            position += 1
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "[":
                stack.append("]")
            elif char == "{":
                stack.append("}")
            elif char in "]}":
                if char != stack.pop():
                    raise ValueError("mismatched JSON delimiters")
        if stack or in_string:
            raise ValueError("unterminated JSON container")
        return position
    if first == '"':
        position += 1
        escaped = False
        while position < len(source):
            char = source[position]
            position += 1
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                return position
        raise ValueError("unterminated JSON string")
    while position < len(source) and source[position] not in ",]} \t\r\n":
        position += 1
    return position


def string_end(source: str, position: int) -> int:
    """Return the end of a JSON string token without decoding it."""
    if position >= len(source) or source[position] != '"':
        raise ValueError("expected JSON string")
    position += 1
    escaped = False
    while position < len(source):
        char = source[position]
        position += 1
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return position
    raise ValueError("unterminated JSON string")


class TaskIdScanner:
    """Decode JSON object keys and allowlisted 24-hex LongBench ID values only."""

    def __init__(self, source: str, allow_generic_id: bool = False):
        self.source = source
        self.decoder = json.JSONDecoder()
        self.ids: set[str] = set()
        self.allow_generic_id = allow_generic_id

    def ws(self, position: int) -> int:
        while position < len(self.source) and self.source[position].isspace():
            position += 1
        return position

    def is_id_field(self, key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        if any(part in normalized for part in EXCLUDED_ID_FIELD_PARTS):
            return False
        if normalized == "id":
            return self.allow_generic_id
        return normalized in (SINGLE_ID_FIELDS - {"id"}) or normalized in ARRAY_ID_FIELDS

    def capture_string_id(self, position: int) -> int:
        position = self.ws(position)
        end = string_end(self.source, position)
        # LongBench v2 task IDs are plain 24-hex ASCII tokens. Avoid decoding
        # arbitrary long strings even when they occur under an ID-shaped key.
        token = self.source[position:end]
        if len(token) == 26:
            value, decoded_end = self.decoder.raw_decode(self.source, position)
            if decoded_end == end and isinstance(value, str) and ID_RE.fullmatch(value):
                self.ids.add(value.lower())
        return end

    def value(self, position: int, depth: int = 0, capture_array_ids: bool = False) -> int:
        if depth > 256:
            raise ValueError("JSON nesting exceeds 256 levels")
        position = self.ws(position)
        if position >= len(self.source):
            raise ValueError("missing JSON value")
        token = self.source[position]
        if token == "{":
            return self.object(position, depth + 1)
        if token == "[":
            return self.array(position, depth + 1, capture_array_ids)
        if token == '"':
            if capture_array_ids:
                return self.capture_string_id(position)
            return skip_value(self.source, position)
        return skip_value(self.source, position)

    def array(self, position: int, depth: int, capture_ids: bool) -> int:
        position += 1
        while True:
            position = self.ws(position)
            if position < len(self.source) and self.source[position] == ",":
                position = self.ws(position + 1)
            if position >= len(self.source):
                raise ValueError("unterminated JSON array")
            if self.source[position] == "]":
                return position + 1
            position = self.value(position, depth + 1, capture_array_ids=capture_ids)

    def object(self, position: int, depth: int) -> int:
        position += 1
        while True:
            position = self.ws(position)
            if position < len(self.source) and self.source[position] == ",":
                position = self.ws(position + 1)
            if position >= len(self.source):
                raise ValueError("unterminated JSON object")
            if self.source[position] == "}":
                return position + 1
            key, position = self.decoder.raw_decode(self.source, position)
            if not isinstance(key, str):
                raise ValueError("JSON object key must be a string")
            position = self.ws(position)
            if position >= len(self.source) or self.source[position] != ":":
                raise ValueError("expected colon after JSON key")
            position = self.ws(position + 1)
            position = self.value(position, depth + 1, capture_array_ids=self.is_id_field(key))

    def scan(self) -> set[str]:
        end = self.value(self.ws(0))
        if self.ws(end) != len(self.source):
            raise ValueError("trailing data after JSON document")
        return self.ids


def source_category(relative: str, ids: set[str]) -> tuple[str, str | None]:
    low = relative.lower()
    if relative == PINNED_DATASET.as_posix():
        return "universe_source", "canonical pinned source dataset; hashed as bytes, not parsed for IDs or counted as exposure"
    census_name = any(marker in low for marker in (
        "field-pruning-census", "query-directed-labels-census",
        "field-pruning-current-hash", "query-labels-current-hash",
    ))
    if census_name:
        return "prompt_census_exposure", "full-universe prompt/label census; excluded from clean-sample eligibility"
    if low.startswith("docs/results/") and ids:
        return "model_outcome_or_execution", "result-root artifact containing LongBench task-ID fields"
    if low.startswith(".runs/") and ids:
        name = Path(low).name
        if any(marker in name for marker in ("dryrun", "dry-run", "preflight", "manifest", "projection", "census", "sample", "screen", "audit")):
            return "selector_or_mechanism_exposure", "local preparation, dry-run, selector, or audit artifact; conservatively excluded"
        if any(marker in name for marker in ("result", "partial", "complete", "attempt", "outcome", "pilot", "stage")):
            return "model_outcome_or_execution", "run artifact indicating execution or partial/completed model output"
        if "longbench" in low:
            return "selector_or_mechanism_exposure", "LongBench-related local artifact; conservatively excluded"
    if low.startswith("docs/evals/") and ids:
        return "selector_or_mechanism_exposure", "evaluation manifest, analysis, or selection artifact; conservatively excluded"
    if ids:
        return "selector_or_mechanism_exposure", "ambiguous ID-bearing artifact in an inventoried root; conservatively classified as mechanism exposure"
    return "no_task_ids_found", None


def allow_generic_id_for_path(relative: str) -> bool:
    """Bare `id` is accepted only in clearly task-specific LongBench artifacts."""
    low = relative.lower()
    return (
        "longbench" in low
        or "context-budget-qwen-" in low
        or low.startswith("docs/results/relation-binding-public-development-")
        or low.startswith("docs/results/relation-preserving-budget-development-")
        or "question_evidence_matrix" in low
    )


def scan_file(path: Path, relative: str, audit_output_path: str) -> dict[str, Any]:
    size = path.stat().st_size
    if relative == audit_output_path:
        return {
            "path": relative, "bytes": size, "sha256": None,
            "category": "audit_output_excluded", "task_id_count": 0,
            "task_ids": [], "scan_status": "skipped",
            "skipped_reason": "exact generated report output excluded from input scanning to prevent self-ingestion; a self-referential SHA-256 cannot be recorded",
        }
    digest = sha256_file(path)
    if relative == PINNED_DATASET.as_posix():
        return {
            "path": relative, "bytes": size, "sha256": digest,
            "category": "universe_source", "task_id_count": 503,
            "task_ids": [], "scan_status": "skipped",
            "skipped_reason": "canonical 465 MB pinned dataset snapshot; hashed as bytes but not parsed for IDs; 503-task universe count is established by the census artifacts",
        }
    opener = json_opener(path)
    ids: set[str] = set()
    try:
        if path.suffix.lower() in {".jsonl", ".ndjson"} or path.name.lower().endswith((".jsonl.tmp", ".ndjson.tmp")):
            with opener(path, "rt", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    scanner = TaskIdScanner(line, allow_generic_id=allow_generic_id_for_path(relative))
                    try:
                        ids.update(scanner.scan())
                    except Exception as exc:
                        raise ValueError(f"line {line_number}: {exc}") from exc
        else:
            with opener(path, "rt", encoding="utf-8") as handle:
                source = handle.read()
            ids = TaskIdScanner(source, allow_generic_id=allow_generic_id_for_path(relative)).scan()
        category, reason = source_category(relative, ids)
        return {
            "path": relative, "bytes": size, "sha256": digest,
            "category": category, "task_id_count": len(ids),
            "task_ids": sorted(ids), "scan_status": "scanned",
            "skipped_reason": reason,
        }
    except Exception as exc:
        return {
            "path": relative, "bytes": size, "sha256": digest,
            "category": "unresolved_scan_error", "task_id_count": len(ids),
            "task_ids": sorted(ids), "scan_status": "error",
            "skipped_reason": f"scan failed closed: {type(exc).__name__}: {str(exc)[:240]}",
        }


def inventory(audit_output_path: str) -> dict[str, Any]:
    paths: list[Path] = []
    for relative_root in RELATIVE_ROOTS:
        root = ROOT / relative_root
        if not root.exists():
            continue
        paths.extend(path for path in root.rglob("*") if path.is_file() and is_json_family(path))
    entries = [scan_file(path, path.relative_to(ROOT).as_posix(), audit_output_path) for path in sorted(set(paths))]
    category_ids: dict[str, set[str]] = {
        "model_outcome_or_execution": set(),
        "selector_or_mechanism_exposure": set(),
        "prompt_census_exposure": set(),
        "unresolved_scan_error": set(),
    }
    for entry in entries:
        category = entry["category"]
        if category in category_ids:
            category_ids[category].update(entry["task_ids"])
    universe_ids = category_ids["prompt_census_exposure"]
    if len(universe_ids) != 503:
        raise RuntimeError(f"Expected exactly 503 census task IDs, found {len(universe_ids)}")
    outcomes = category_ids["model_outcome_or_execution"]
    mechanisms = category_ids["selector_or_mechanism_exposure"]
    outcome_mechanism_union = outcomes | mechanisms
    eligible = universe_ids - outcome_mechanism_union
    # There may be multiple full-universe census files. Their task-ID union is
    # used as the universe, while every such ID remains prompt-census exposed.
    if len(eligible) != 253:
        raise RuntimeError(f"Expected 253 outcome/mechanism-ID-disjoint IDs, found {len(eligible)}")
    return {
        "schema_version": 1,
        "evaluation": "LongBench v2",
        "generated_by": "benchmarks/audit_longbench_v2_exposure_inventory.py",
        "scope": [path.as_posix() for path in RELATIVE_ROOTS],
        "policy": {
            "id_fields_only": sorted(SINGLE_ID_FIELDS | ARRAY_ID_FIELDS),
            "provider_request_commit_and_other_generic_ids": "excluded; the bare `id` field is accepted only from explicitly LongBench-named artifacts and the listed legacy LongBench context-budget/relation artifacts",
            "non_id_json_values": "skipped lexically and never decoded",
            "pinned_dataset": "hashed as raw bytes as the universe source; JSON content is not parsed for IDs or counted as an outcome/exposure artifact",
            "incomplete_sources": [
                "Non-JSON text logs and artifacts outside the three inventoried roots were not parsed.",
                "External provider histories were not inspected.",
                "Census artifacts establish prompt/label work across all 503 tasks, so this is not an untouched holdout.",
            ],
        },
        "counts": {
            "files_inventoried": len(entries),
            "files_scanned": sum(entry["scan_status"] == "scanned" for entry in entries),
            "files_skipped": sum(entry["scan_status"] == "skipped" for entry in entries),
            "audit_output_excluded_files": sum(entry["category"] == "audit_output_excluded" for entry in entries),
            "files_with_scan_errors": sum(entry["scan_status"] == "error" for entry in entries),
            "universe_task_ids": 503,
            "model_outcome_or_execution_task_ids": len(outcomes),
            "selector_or_mechanism_task_ids": len(mechanisms),
            "outcome_or_mechanism_union_task_ids": len(outcome_mechanism_union),
            "outcome_or_mechanism_id_disjoint_task_ids": len(eligible),
            "prompt_census_exposure_task_ids": len(universe_ids),
            "untouched_task_ids": 0,
        },
        "sets": {
            "model_outcome_or_execution_ids": sorted(outcomes),
            "selector_or_mechanism_exposure_ids": sorted(mechanisms),
            "outcome_or_mechanism_union_ids": sorted(outcome_mechanism_union),
            "outcome_or_mechanism_id_disjoint_ids": sorted(eligible),
            "prompt_census_exposure_ids": sorted(universe_ids),
        },
        "interpretation": (
            "253 IDs are disjoint only from the inventoried model outcome/execution and selector/mechanism ID sets. "
            "They are not untouched: prompt/label census work covered all 503 LongBench v2 tasks."
        ),
        "sources": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/evals/longbench-v2-exposure-inventory-2026-10-18.json")
    args = parser.parse_args()
    output_path = (ROOT / args.output).resolve()
    if not output_path.is_relative_to(ROOT):
        parser.error("--output must be within the repository")
    report = inventory(output_path.relative_to(ROOT).as_posix())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": output_path.relative_to(ROOT).as_posix(), "counts": report["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
