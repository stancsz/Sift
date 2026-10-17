#!/usr/bin/env python3
"""Build a conservative, answer-blind LongBench v2 task-ID manifest.

Only LongBench task IDs and JSON object keys are decoded from source artifacts.
All other JSON values are skipped lexically; prompt, answer, and model-output
values are never passed to a JSON decoder. The output contains IDs and source
metadata only. This tool performs no network or model calls.

By default the manifest is written to stdout. Use --output to persist it.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = Path("docs/evals/longbench-v2-field-pruning-census-current-2026-10-18.json")
DEFAULT_SAMPLE = 100
DEFAULT_SEED = "sift-longbench-v2-minimax-confirmatory-id-only-v1"
ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")

# Outcome files are enumerated by exact current filenames from docs/results.
# This excludes large local dataset snapshots and derived run logs by default.
# The exact discovered names and SHA-256 values are recorded in the manifest.
OUTCOME_DIRECTORY = Path("docs/results")
OUTCOME_PREFIX = "longbench-v2-"
OUTCOME_SUFFIXES = (".json", ".json.gz")

# Explicit, bounded sample/manifest sources for candidate and mechanism
# exposure. Other possible logs are a documented coverage gap, so the output
# cannot be mistaken for an exhaustive or untouched holdout.
CANDIDATE_FILES = (
    "docs/evals/longbench-v2-candidate-census-union-2026-10-18.json",
    "docs/evals/longbench-v2-record-ranking-sample-2026-10-18.json",
    "docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json",
    "docs/evals/longbench-v2-minimax-relation-stage1-manifest-2026-10-16.json",
    "docs/evals/longbench-v2-minimax-relation-stage1-v2-manifest-2026-10-17.json",
    "docs/evals/longbench-v2-minimax-relation-stage1-v3-manifest-2026-10-17.json",
    "docs/evals/longbench-v2-minimax-field-pruning-pilot-preflight-2026-10-17.json",
    "docs/evals/longbench-v2-minimax-m3-csv-candidate-manifest-2026-10-16.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_source(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return handle.read()


def skip_value(source: str, position: int) -> int:
    """Advance over one JSON value without decoding any scalar value."""
    while position < len(source) and source[position].isspace():
        position += 1
    if position >= len(source):
        raise ValueError("unexpected end of JSON")
    first = source[position]
    if first in "[{":
        stack = ["]" if first == "[" else "}"]
        position += 1
        in_string = False
        escaped = False
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
                if not stack or char != stack.pop():
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


class IdOnlyScanner:
    """Selective parser that materializes only keys and allowlisted ID values."""

    def __init__(self, source: str):
        self.source = source
        self.decoder = json.JSONDecoder()
        self.ids: set[str] = set()
        self.keys: set[str] = set()

    def _ws(self, position: int) -> int:
        while position < len(self.source) and self.source[position].isspace():
            position += 1
        return position

    def _id_scalar(self, position: int) -> int:
        position = self._ws(position)
        if position >= len(self.source):
            raise ValueError("missing ID value")
        if self.source[position] == '"':
            value, end = self.decoder.raw_decode(self.source, position)
            if isinstance(value, str) and ID_RE.fullmatch(value):
                self.ids.add(value.lower())
            return end
        return skip_value(self.source, position)

    def _array(self, position: int, capture_ids: bool, depth: int) -> int:
        if depth > 256:
            raise ValueError("JSON nesting exceeds 256 levels")
        position = self._ws(position)
        if self.source[position] != "[":
            return self._value(position, depth + 1)
        position += 1
        while True:
            position = self._ws(position)
            while position < len(self.source) and self.source[position] == ",":
                position = self._ws(position + 1)
            if position >= len(self.source):
                raise ValueError("unterminated JSON array")
            if self.source[position] == "]":
                return position + 1
            if capture_ids and self.source[position] == '"':
                position = self._id_scalar(position)
            else:
                position = self._value(position, depth + 1)

    def _object(self, position: int, depth: int) -> int:
        if depth > 256:
            raise ValueError("JSON nesting exceeds 256 levels")
        position = self._ws(position)
        if self.source[position] != "{":
            return self._value(position, depth + 1)
        position += 1
        while True:
            position = self._ws(position)
            while position < len(self.source) and self.source[position] == ",":
                position = self._ws(position + 1)
            if position >= len(self.source):
                raise ValueError("unterminated JSON object")
            if self.source[position] == "}":
                return position + 1
            key, position = self.decoder.raw_decode(self.source, position)
            if not isinstance(key, str):
                raise ValueError("JSON object key must be a string")
            self.keys.add(key)
            # Some census artifacts store IDs as map keys rather than in an
            # explicit `id` field. Keys are decoded by JSON traversal already;
            # retain only values matching the LongBench task-ID shape.
            if ID_RE.fullmatch(key):
                self.ids.add(key.lower())
            position = self._ws(position)
            if position >= len(self.source) or self.source[position] != ":":
                raise ValueError("expected colon after JSON object key")
            position = self._ws(position + 1)
            normalized_key = key.lower().replace("-", "_")
            if normalized_key == "id" or normalized_key.endswith("_id"):
                position = self._id_scalar(position)
            elif normalized_key == "ids" or normalized_key.endswith("_ids"):
                position = self._array(position, capture_ids=True, depth=depth + 1)
            elif any(marker in key.lower() for marker in ("eligible", "union", "development", "held_out")):
                # Candidate censuses use descriptive field names for arrays of
                # task IDs. Only exact 24-hex strings are retained; non-ID
                # values and all unrelated content remain unmaterialized.
                position = self._array(position, capture_ids=True, depth=depth + 1)
            else:
                position = self._value(position, depth + 1)

    def _value(self, position: int, depth: int) -> int:
        if depth > 256:
            raise ValueError("JSON nesting exceeds 256 levels")
        position = self._ws(position)
        if position >= len(self.source):
            raise ValueError("missing JSON value")
        token = self.source[position]
        if token == "{":
            return self._object(position, depth + 1)
        if token == "[":
            return self._array(position, capture_ids=False, depth=depth + 1)
        return skip_value(self.source, position)

    def scan(self) -> set[str]:
        end = self._object(self._ws(0), 0)
        if self._ws(end) != len(self.source):
            raise ValueError("trailing data after JSON document")
        return self.ids


def scan_ids(path: Path) -> set[str]:
    return IdOnlyScanner(read_source(path)).scan()


def scan_census_rows_ids(path: Path) -> set[str]:
    """Read exactly root.rows[*].id, skipping every other JSON value."""
    source = read_source(path)
    scanner = IdOnlyScanner(source)
    decoder = scanner.decoder
    position = scanner._ws(0)
    if position >= len(source) or source[position] != "{":
        raise ValueError("census root must be a JSON object")
    position += 1
    rows_found = False
    ids: set[str] = set()
    while True:
        position = scanner._ws(position)
        while position < len(source) and source[position] == ",":
            position = scanner._ws(position + 1)
        if position >= len(source):
            raise ValueError("unterminated census object")
        if source[position] == "}":
            break
        key, position = decoder.raw_decode(source, position)
        if not isinstance(key, str):
            raise ValueError("census object key must be a string")
        position = scanner._ws(position)
        if position >= len(source) or source[position] != ":":
            raise ValueError("expected colon in census object")
        position = scanner._ws(position + 1)
        if key != "rows":
            position = skip_value(source, position)
            continue
        if rows_found:
            raise ValueError("duplicate rows key in census")
        rows_found = True
        if source[position] != "[":
            raise ValueError("census rows must be an array")
        position += 1
        while True:
            position = scanner._ws(position)
            while position < len(source) and source[position] == ",":
                position = scanner._ws(position + 1)
            if position >= len(source):
                raise ValueError("unterminated census rows")
            if source[position] == "]":
                position += 1
                break
            if source[position] != "{":
                position = skip_value(source, position)
                continue
            row_start = position
            row_end = skip_value(source, row_start)
            row = source[row_start:row_end]
            row_position = 1
            while True:
                while row_position < len(row) and row[row_position].isspace():
                    row_position += 1
                while row_position < len(row) and row[row_position] == ",":
                    row_position += 1
                    while row_position < len(row) and row[row_position].isspace():
                        row_position += 1
                if row_position >= len(row):
                    raise ValueError("unterminated census row")
                if row[row_position] == "}":
                    break
                row_key, row_position = decoder.raw_decode(row, row_position)
                while row_position < len(row) and row[row_position].isspace():
                    row_position += 1
                if row_position >= len(row) or row[row_position] != ":":
                    raise ValueError("expected colon in census row")
                row_position += 1
                while row_position < len(row) and row[row_position].isspace():
                    row_position += 1
                if row_key == "id":
                    id_value, row_position = decoder.raw_decode(row, row_position)
                    if isinstance(id_value, str) and ID_RE.fullmatch(id_value):
                        ids.add(id_value.lower())
                else:
                    row_position = skip_value(row, row_position)
            position = row_end
    if not rows_found:
        raise ValueError("census has no root rows array")
    return ids


def outcome_files() -> list[Path]:
    folder = ROOT / OUTCOME_DIRECTORY
    return sorted(
        (p.resolve() for p in folder.iterdir()
         if p.is_file() and p.name.startswith(OUTCOME_PREFIX)
         and p.name.endswith(OUTCOME_SUFFIXES) and not p.name.endswith(".tmp")),
        key=lambda p: p.relative_to(ROOT).as_posix(),
    )


def candidate_files() -> list[Path]:
    return [(ROOT / item).resolve() for item in CANDIDATE_FILES if (ROOT / item).is_file()]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE.as_posix(), help="census JSON with rows[*].id")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--output", help="output JSON path; defaults to stdout")
    args = parser.parse_args()
    if args.sample_size < 1:
        parser.error("--sample-size must be positive")

    universe_path = (ROOT / args.universe).resolve()
    if not universe_path.is_file() or not universe_path.is_relative_to(ROOT):
        parser.error("universe must be an existing file within the repository")
    # The universe is constrained to root.rows[*].id; every other value is
    # skipped without JSON decoding.
    universe = scan_census_rows_ids(universe_path)
    # A fail-closed count check prevents silently substituting a partial census.
    if len(universe) != 503:
        raise SystemExit(f"Expected 503 unique universe IDs from {rel(universe_path)}, got {len(universe)}")

    outcome_paths = outcome_files()
    candidate_paths = candidate_files()
    outcome_ids: set[str] = set()
    candidate_ids: set[str] = set()
    source_records: list[dict[str, Any]] = [{
        "category": "universe_census",
        "path": rel(universe_path),
        "sha256": sha256_file(universe_path),
        "ids_found": len(universe),
        "id_scope": "rows[*].id only; all other values skipped",
    }]

    for category, paths, accumulator in (
        ("prior_outcome_or_execution_exposure", outcome_paths, outcome_ids),
        ("candidate_or_mechanism_exposure", candidate_paths, candidate_ids),
    ):
        for path in paths:
            ids = scan_ids(path)
            accumulator.update(ids)
            source_records.append({
                "category": category,
                "path": rel(path),
                "sha256": sha256_file(path),
                "ids_found": len(ids),
                "id_scope": "24-hex object keys or values under id/task_id/question_id/ids/task_ids/selected_ids/exposed_ids; all other values skipped",
            })

    # Conservative exclusion: candidate/mechanism evidence and known outcomes
    # are reported separately but their union is never eligible for selection.
    exposed_union = outcome_ids | candidate_ids
    eligible = sorted(universe - exposed_union)
    ranked = sorted(
        eligible,
        key=lambda task_id: hashlib.sha256(f"{args.seed}\0{task_id}".encode("utf-8")).hexdigest(),
    )
    selected = ranked[: args.sample_size]
    if len(selected) != args.sample_size:
        raise SystemExit(f"Requested {args.sample_size} IDs but only {len(selected)} eligible IDs remain")

    # Coverage is intentionally provisional: the repository may contain
    # outcome-bearing artifacts outside the explicit filename globs, ignored
    # files, logs, or untracked local artifacts. This tool does not assert an
    # untouched or preregistered test set.
    output = {
        "schema_version": 1,
        "evaluation": "LongBench v2",
        "provider_plan": "OpenRouter MiniMax",
        "status": "provisional_non_preregistered",
        "exposure_claim": "ID-disjoint from the inventoried sources only; not untouched",
        "method": {
            "universe": "the 503 unique task IDs in the pinned census rows[*].id allowlist",
            "selection": "sort eligible IDs by SHA-256(seed + NUL + lowercase task ID), take first sample_size",
            "seed": args.seed,
            "sample_size": args.sample_size,
            "decoded_value_policy": "only JSON object keys and 24-hex task ID values are decoded; all other JSON values are skipped",
            "excluded_set": "union of IDs in the prior outcome/execution and candidate/mechanism source categories",
            "network_calls": 0,
        },
        "counts": {
            "universe": len(universe),
            "prior_outcome_or_execution_ids_in_universe": len(outcome_ids & universe),
            "candidate_or_mechanism_ids_in_universe": len(candidate_ids & universe),
            "union_excluded_ids_in_universe": len(exposed_union & universe),
            "eligible_ids": len(eligible),
            "selected_ids": len(selected),
            "outcome_ids_outside_universe": len(outcome_ids - universe),
            "candidate_or_mechanism_ids_outside_universe": len(candidate_ids - universe),
        },
        "coverage_gaps": [
            "Outcome sources are current files in docs/results whose names start with longbench-v2- and end in .json or .json.gz; .runs artifacts are not exhaustively inventoried.",
            "Candidate/mechanism sources are the exact source list in this script; other manifests, local logs, untracked, ignored, archived, or external artifacts may contain unrecorded exposure.",
            "The candidate/mechanism category includes some dry-run or analysis manifests; it is intentionally conservative and may exclude IDs without outcome exposure.",
            "This manifest is provisional and must not be described as untouched or preregistered.",
        ],
        "sources": source_records,
        "selected_ids": selected,
    }
    serialized = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        output_path = (ROOT / args.output).resolve()
        if not output_path.is_relative_to(ROOT):
            parser.error("--output must be within the repository")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
