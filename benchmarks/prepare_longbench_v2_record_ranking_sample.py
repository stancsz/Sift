"""Freeze an answer-blind 20-row record-ranking development/holdout sample.

The sample is limited to above-target, structured contexts recognized by the
existing whole-record relation-closure parser. It deliberately excludes every
case exposed by the field-pruning screen and never reads task answer keys.
"""

from __future__ import annotations

from collections import defaultdict
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
    CONTEXT_PREFIX,
    CONTEXT_SUFFIX,
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
)


TARGET_TOKENS = 32_640
SALT = "sift-longbench-v2-record-ranking-2026-10-18-v1"
DATASET_DEFAULT = (
    Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
)
CENSUS_DEFAULT = ROOT / "docs" / "evals" / "longbench-v2-field-pruning-census-2026-10-17.json"
OUTPUT_DEFAULT = ROOT / "docs" / "evals" / "longbench-v2-record-ranking-sample-2026-10-18.json"
PRIOR_RELATION_MANIFEST_DEFAULT = ROOT / "docs" / "evals" / "longbench-v2-minimax-relation-stage1-v3-manifest-2026-10-17.json"
EXPOSED_IDS = (
    "66f2b5ec821e116aacb2b1ec",
    "6719b96abb02136c067d4358",
    "671b080abb02136c067d4dde",
    "671b170cbb02136c067d4f4a",
    "671b17d5bb02136c067d4f7d",
    "671b2b57bb02136c067d508b",
    "671b2c05bb02136c067d50c8",
    "671b2c67bb02136c067d50f7",
    "671b3cabbb02136c067d5252",
)
PREVIOUSLY_EXPOSED_RELATION_IDS = (
    "672494e5bb02136c067d7697",
    "67249705bb02136c067d76d1",
    "6724c1d4bb02136c067d77ec",
    "67285e1dbb02136c067d901b",
    "67286036bb02136c067d9092",
    "6724c4aabb02136c067d78a6",
)


def _hash_key(group: str, task_id: str) -> str:
    return hashlib.sha256(f"{SALT}|{group}|{task_id}".encode("utf-8")).hexdigest()


def _structure(context: str) -> str | None:
    # Use only source-context shape. Do not inspect the question, choices,
    # official answer, model outputs, or prior quality scores for selection.
    if core._research_entity_map(context) is not None or core._research_concept_map(context) is not None:
        return "entity_or_concept_map"
    if core._research_json_array(context) is not None:
        return "json_array"
    return None


def _choose_hash_order(rows: list[dict[str, Any]], group: str, count: int) -> list[dict[str, Any]]:
    if len(rows) < count:
        raise ValueError(f"Selection stratum {group!r} has {len(rows)} rows; need {count}")
    return sorted(rows, key=lambda row: (_hash_key(group, row["id"]), row["id"]))[:count]


def build(
    dataset_path: Path,
    census_path: Path,
    prior_relation_manifest_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise ValueError("Pinned LongBench v2 dataset SHA-256 mismatch")
    census = json.loads(census_path.read_text(encoding="utf-8"))
    if census.get("inputs", {}).get("dataset_revision") != DATASET_REVISION:
        raise ValueError("Census dataset revision mismatch")
    if census.get("inputs", {}).get("dataset_sha256") != DATASET_SHA256:
        raise ValueError("Census dataset SHA-256 mismatch")
    census_rows = {row["id"]: row for row in census.get("rows", [])}
    if len(census_rows) != 503:
        raise ValueError("Expected exactly 503 census rows")
    if set(EXPOSED_IDS) != {
        row["id"] for row in census_rows.values() if row["active_eligible"]
    }:
        raise ValueError("Frozen exposed-ID list differs from the 9-task census eligibility set")
    prior_manifest = json.loads(prior_relation_manifest_path.read_text(encoding="utf-8"))
    prior_ids = prior_manifest.get("protocol", {}).get("task_ids")
    if prior_ids != list(PREVIOUSLY_EXPOSED_RELATION_IDS):
        raise ValueError("Prior relation-screen IDs differ from the frozen Stage 1 manifest")
    if prior_manifest.get("protocol", {}).get("candidate", {}).get("selector") != "research_relation_closure":
        raise ValueError("The prior manifest does not bind to the relation-closure method under study")

    candidate_pool: list[dict[str, Any]] = []
    for source_row in iter_json_array(dataset_path):
        task_id = str(source_row["_id"])
        census_row = census_rows[task_id]
        if task_id in EXPOSED_IDS or census_row["full_prompt_tokens"] <= TARGET_TOKENS:
            continue
        context = CONTEXT_PREFIX + source_row["context"].strip() + CONTEXT_SUFFIX
        source_structure = _structure(context)
        if source_structure is None:
            continue
        candidate_pool.append({
            "id": task_id,
            "structure": source_structure,
            "domain": census_row["domain"],
            "sub_domain": census_row["sub_domain"],
            "difficulty": census_row["difficulty"],
            "length": census_row["length"],
            "full_prompt_tokens": census_row["full_prompt_tokens"],
        })

    if len(candidate_pool) != 24:
        raise ValueError(f"Expected pinned structural candidate pool size 24; got {len(candidate_pool)}")
    by_structure: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_pool:
        by_structure[row["structure"]].append(row)
    arrays = by_structure["json_array"]
    maps = by_structure["entity_or_concept_map"]
    if len(arrays) != 9 or len(maps) != 15:
        raise ValueError(
            "Pinned parser strata changed: expected 9 JSON arrays and 15 entity/concept maps; "
            f"found {len(arrays)} and {len(maps)}"
        )
    exposed_relation = {row["id"] for row in candidate_pool} & set(PREVIOUSLY_EXPOSED_RELATION_IDS)
    if exposed_relation != set(PREVIOUSLY_EXPOSED_RELATION_IDS):
        raise ValueError("Prior relation-screen IDs are not all present in the structured candidate pool")
    fresh_maps = [row for row in maps if row["id"] not in PREVIOUSLY_EXPOSED_RELATION_IDS]
    if len(fresh_maps) != 9:
        raise ValueError(f"Expected 9 fresh entity/concept-map rows after prior exposure exclusion; got {len(fresh_maps)}")

    # All six tasks previously used in the relation-matrix model screen stay
    # in development. The clean held-out set contains only tasks never used in
    # that candidate screen. Four additional fresh tasks provide current
    # development examples; remaining fresh parser hits are unused.
    array_by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in arrays:
        array_by_domain[row["domain"]].append(row)
    code_arrays = _choose_hash_order(
        array_by_domain["Code Repository Understanding"], "fresh-array|code", 5
    )
    translation_arrays = array_by_domain["Long In-context Learning"]
    if len(translation_arrays) != 2:
        raise ValueError("Expected two fresh translation JSON-array rows")
    code_ordered = sorted(code_arrays, key=lambda row: (_hash_key("split-array|code", row["id"]), row["id"]))
    translation_ordered = sorted(translation_arrays, key=lambda row: (_hash_key("split-array|translation", row["id"]), row["id"]))
    array_dev = [code_ordered[0], translation_ordered[0]]
    array_holdout = [*code_ordered[1:], translation_ordered[1]]

    fresh_map_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in fresh_maps:
        fresh_map_groups[(row["difficulty"], row["length"])].append(row)
    map_dev: list[dict[str, Any]] = []
    map_holdout: list[dict[str, Any]] = []
    for stratum, dev_quota, holdout_quota in (
        (("easy", "long"), 1, 1),
        (("easy", "medium"), 0, 3),
        (("hard", "medium"), 1, 1),
    ):
        quota = dev_quota + holdout_quota
        chosen = _choose_hash_order(
            fresh_map_groups[stratum], "fresh-map|" + "|".join(stratum), quota
        )
        ordered = sorted(chosen, key=lambda row: (_hash_key("split-map|" + "|".join(stratum), row["id"]), row["id"]))
        map_dev.extend(ordered[:dev_quota])
        map_holdout.extend(ordered[dev_quota:])
    if len(map_dev) != 2 or len(map_holdout) != 5:
        raise ValueError("Expected 2 fresh map development and 5 held-out rows")

    selected = [
        *({**row, "split": "development", "prior_method_exposure": "relation_matrix_model_screen"}
          for row in candidate_pool if row["id"] in PREVIOUSLY_EXPOSED_RELATION_IDS),
        *({**row, "split": "development", "prior_method_exposure": None} for row in array_dev),
        *({**row, "split": "development", "prior_method_exposure": None} for row in map_dev),
        *({**row, "split": "held_out", "prior_method_exposure": None} for row in array_holdout),
        *({**row, "split": "held_out", "prior_method_exposure": None} for row in map_holdout),
    ]
    selected.sort(key=lambda row: (row["split"], row["structure"], row["id"]))
    ids = [row["id"] for row in selected]
    if (len(selected) != 20 or len(set(ids)) != 20 or set(ids) & set(EXPOSED_IDS)
            or set(ids) - set(candidate_pool[i]["id"] for i in range(len(candidate_pool)))):
        raise ValueError("Sample size, uniqueness, or exposure exclusion invariant failed")
    if sum(row["split"] == "development" for row in selected) != 10:
        raise ValueError("Expected 10 development rows")
    if sum(row["split"] == "held_out" for row in selected) != 10:
        raise ValueError("Expected 10 held-out rows")
    if any(row["prior_method_exposure"] for row in selected if row["split"] == "held_out"):
        raise ValueError("Held-out rows must not include prior relation-screen cases")

    artifact = {
        "schema_version": 1,
        "title": "LongBench v2 answer-blind whole-record ranking sample",
        "status": "frozen offline screening sample; no answer keys or model outputs used; no API calls",
        "method": {
            "dataset_id": "zai-org/LongBench-v2",
            "dataset_revision": DATASET_REVISION,
            "dataset_sha256": DATASET_SHA256,
            "selector_builder_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "selector_builder_sha256": file_sha256(Path(__file__).resolve()),
            "dataset_reader_path": "benchmarks/prepare_longbench_v2.py",
            "dataset_reader_sha256": file_sha256(ROOT / "benchmarks" / "prepare_longbench_v2.py"),
            "template_renderer_path": "benchmarks/prepare_longbench_v2_minimax.py",
            "template_renderer_sha256": file_sha256(ROOT / "benchmarks" / "prepare_longbench_v2_minimax.py"),
            "candidate_core_path": "src/sift/core.py",
            "candidate_core_sha256": file_sha256(ROOT / "src" / "sift" / "core.py"),
            "census_path": census_path.resolve().relative_to(ROOT).as_posix(),
            "census_sha256": file_sha256(census_path),
            "prior_relation_screen_manifest_path": prior_relation_manifest_path.resolve().relative_to(ROOT).as_posix(),
            "prior_relation_screen_manifest_sha256": file_sha256(prior_relation_manifest_path),
            "target_tokens": TARGET_TOKENS,
            "pool": "all above-target tasks outside the 9 exposed field-pruning-eligible IDs whose context is parsed by the existing exact whole-record relation-closure parsers",
            "selection_inputs": ["context structure", "domain", "difficulty", "length", "pinned full-prompt token count used only for above-target eligibility"],
            "selection_exclusions": ["official answer values", "question/choice semantics", "model outputs", "candidate outputs", "prior quality scores"],
            "salt": SALT,
            "strata_and_quotas": {
                "prior_relation_screen": "all six earlier relation-matrix tasks are labeled prior_method_exposure and kept in development only",
                "json_array": "2 fresh tasks in development (one Code Repository and one Long In-context Learning) and 5 fresh tasks held-out (four Code Repository and one Long In-context Learning), selected by salted hash",
                "entity_or_concept_map": "2 fresh development tasks (one easy/long and one hard/medium) plus 5 held-out tasks (one easy/long, three easy/medium, one hard/medium), selected by salted hash",
            },
            "candidate_under_study": "separate opt-in use of core.compact_messages(..., complete_record_groups=True); whole-record relation closure across entities/concepts/labels maps; preserves other root members; no source changes are made by this selector",
            "interpretation": "mechanism and evidence-retention screen only; not a representative LongBench sample or answer-quality result",
        },
        "exposed_ids_excluded": list(EXPOSED_IDS),
        "prior_relation_screen_ids_development_only": list(PREVIOUSLY_EXPOSED_RELATION_IDS),
        "candidate_pool_counts": {name: len(rows) for name, rows in sorted(by_structure.items())},
        "selected_count": len(selected),
        "development_count": 10,
        "held_out_count": 10,
        "selected": selected,
    }
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--census", type=Path, default=CENSUS_DEFAULT)
    parser.add_argument("--prior-relation-manifest", type=Path, default=PRIOR_RELATION_MANIFEST_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    args = parser.parse_args()
    result = build(args.dataset, args.census, args.prior_relation_manifest, args.output)
    print(json.dumps({
        "output": args.output.resolve().relative_to(ROOT).as_posix(),
        "selected": result["selected_count"],
        "development": result["development_count"],
        "held_out": result["held_out_count"],
        "pool": result["candidate_pool_counts"],
    }, indent=2))
