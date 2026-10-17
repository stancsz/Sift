"""Offline Sift target sweep on the frozen 100-task MiniMax LongBench sample.

This operational audit makes no network or model/API requests. Its selective
JSON reader decodes only frozen task metadata and prompt fields; values in
answer, answer-key, and response fields are skipped without JSON decoding. It
reports mechanical token fit and local preprocessing time, not quality,
provider capability, or realized cost.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from collections import Counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from sift import core  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402


TOKENIZER_SHA256 = "bb1f1626cf01448f1e3b6036d0a061ffc66c91d9046aada14ea23a5441b5ad6e"
TEMPLATE_SHA256 = "11421244f67553498e5c8112dae02802025bcc4305ec45ad380af95c96f9fe64"
SAMPLE_SIZE = 100
PRIMARY_TARGET = 32_768
SAFETY_MARGIN = 128
DEFAULT_TARGETS = (16_384, 24_576, 32_768, 49_152, 65_536)
EXPECTED_CORE_SHA256 = "5a1d64474eea5d5ca6d599ab893411d40922dd7d12cc47e0ae33b9a097c86f1a"
EXPECTED_MANIFEST_SHA256 = "865e27c21fdd2a6ce4b629b283123f4bff66b62e3c17f39c3b8be842b00a6f18"
EXPECTED_PROMPT_BUILDER_SHA256 = "b913c0c89ed6bea2a7b74b54b64516bfcaad7f7894067ebbac9c5085e47ae069"
EXPECTED_RENDERER_SHA256 = "2eb34e08fbdb3d1acb69339505e1e228030b930e2d967b174e67490006adee77"

MANIFEST_DEFAULT = ROOT / "docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json"
DATASET_DEFAULT = (
    Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
)
TOKENIZER_DEFAULT = ROOT / "tmp/minimax-m3-tokenizer.json"
TEMPLATE_DEFAULT = ROOT / "tmp/minimax-m3-chat-template.jinja"
OUTPUT_DEFAULT = ROOT / "docs/evals/longbench-v2-target-sweep-current-2026-10-18.json"


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _skip_json_value(source: str, position: int) -> int:
    """Return the end of a JSON value without decoding or materializing it."""
    if position >= len(source):
        raise ValueError("Unexpected end while skipping a JSON value")
    first = source[position]
    if first == '"':
        position += 1
        escaped = False
        while position < len(source):
            character = source[position]
            position += 1
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                return position
        raise ValueError("Unterminated JSON string")
    if first in "[{":
        stack = ["]" if first == "[" else "}"]
        position += 1
        in_string = False
        escaped = False
        while position < len(source) and stack:
            character = source[position]
            position += 1
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == "[":
                stack.append("]")
            elif character == "{":
                stack.append("}")
            elif character in "]}":
                if not stack or character != stack.pop():
                    raise ValueError("Mismatched JSON delimiters")
        if stack or in_string:
            raise ValueError("Unterminated JSON container")
        return position
    start = position
    while position < len(source) and source[position] not in ",]} \t\r\n":
        position += 1
    if position == start:
        raise ValueError("Invalid JSON primitive")
    return position


def _selected_object(
    source: str,
    allowed_fields: set[str],
    *,
    nested_object_arrays: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    nested_object_arrays = nested_object_arrays or {}
    position = 0
    while position < len(source) and source[position].isspace():
        position += 1
    if position >= len(source) or source[position] != "{":
        raise ValueError("Expected a JSON object")
    position += 1
    selected: dict[str, Any] = {}
    while True:
        while position < len(source) and source[position] in " \t\r\n,":
            position += 1
        if position >= len(source):
            raise ValueError("Unterminated JSON object")
        if source[position] == "}":
            return selected
        key, key_end = decoder.raw_decode(source, position)
        if not isinstance(key, str):
            raise ValueError("JSON object key is not a string")
        if key in selected:
            raise ValueError("Duplicate allowlisted JSON object key")
        position = key_end
        while position < len(source) and source[position].isspace():
            position += 1
        if position >= len(source) or source[position] != ":":
            raise ValueError("Expected colon after JSON object key")
        position += 1
        while position < len(source) and source[position].isspace():
            position += 1
        nested_fields = nested_object_arrays.get(key)
        if key in allowed_fields and nested_fields is not None:
            selected[key], position = _selected_object_array(source, position, nested_fields)
        elif key in allowed_fields:
            selected[key], position = decoder.raw_decode(source, position)
        else:
            position = _skip_json_value(source, position)


def _selected_object_array(
    source: str, position: int, allowed_fields: set[str]
) -> tuple[list[dict[str, Any]], int]:
    if position >= len(source) or source[position] != "[":
        raise ValueError("Expected a JSON array")
    position += 1
    result: list[dict[str, Any]] = []
    while True:
        while position < len(source) and source[position] in " \t\r\n,":
            position += 1
        if position >= len(source):
            raise ValueError("Unterminated JSON array")
        if source[position] == "]":
            return result, position + 1
        end = _skip_json_value(source, position)
        result.append(_selected_object(source[position:end], allowed_fields))
        position = end


def iter_selected_dataset_rows(
    path: Path,
    selected_ids: set[str],
    allowed_fields: set[str],
    *,
    chunk_size: int = 2 * 1024 * 1024,
):
    """Stream rows, decode IDs first, then prompt fields for selected tasks only."""
    buffer = ""
    started = False
    item_started = False
    item_start = 0
    item_parts: list[str] = []
    depth = 0
    in_string = False
    escaped = False
    with path.open(encoding="utf-8") as source:
        while chunk := source.read(chunk_size):
            buffer += chunk
            if not started:
                opening = buffer.find("[")
                if opening < 0:
                    buffer = buffer[-1:]
                    continue
                buffer = buffer[opening + 1:]
                started = True
            position = 0
            while position < len(buffer):
                character = buffer[position]
                if not item_started:
                    if character in " \t\r\n,":
                        position += 1
                        continue
                    if character == "]":
                        return
                    if character != "{":
                        raise ValueError("Expected dataset array item to be an object")
                    item_started = True
                    item_start = position
                    depth = 0
                    in_string = False
                    escaped = False
                if in_string:
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == '"':
                        in_string = False
                elif character == '"':
                    in_string = True
                elif character in "[{":
                    depth += 1
                elif character in "]}":
                    depth -= 1
                    if depth == 0:
                        raw_object = "".join(item_parts) + buffer[item_start:position + 1]
                        identity = _selected_object(raw_object, {"_id"})
                        case_id = str(identity.get("_id", ""))
                        if case_id in selected_ids:
                            yield _selected_object(raw_object, allowed_fields)
                        item_parts = []
                        item_started = False
                position += 1
            if item_started:
                item_parts.append(buffer[item_start:])
                buffer = ""
                item_start = 0
            else:
                buffer = ""


def prepare_cases(
    manifest_path: Path,
    dataset_path: Path,
    tokenizer_path: Path,
    template_path: Path,
) -> tuple[Tokenizer, list[dict[str, Any]], dict[str, str]]:
    if file_sha256(manifest_path) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("Frozen sample manifest hash mismatch")
    if file_sha256(ROOT / "benchmarks/prepare_longbench_v2.py") != EXPECTED_PROMPT_BUILDER_SHA256:
        raise ValueError("Prompt-builder source hash mismatch")
    if file_sha256(ROOT / "benchmarks/prepare_longbench_v2_minimax.py") != EXPECTED_RENDERER_SHA256:
        raise ValueError("MiniMax renderer source hash mismatch")
    manifest = _selected_object(
        manifest_path.read_text(encoding="utf-8"),
        {"dataset", "model", "sift", "cases"},
        nested_object_arrays={
            "cases": {"id", "domain", "prompt_sha256", "m3_rendered_prompt_tokens"}
        },
    )
    dataset_meta = manifest.get("dataset", {})
    model_meta = manifest.get("model", {})
    if dataset_meta.get("revision") != DATASET_REVISION or dataset_meta.get("data_file_sha256") != DATASET_SHA256:
        raise ValueError("Frozen manifest is not bound to the pinned LongBench v2 dataset")
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise ValueError("LongBench v2 dataset hash mismatch")
    if file_sha256(tokenizer_path) != TOKENIZER_SHA256 or model_meta.get("tokenizer_sha256") != TOKENIZER_SHA256:
        raise ValueError("MiniMax tokenizer hash mismatch")
    if file_sha256(template_path) != TEMPLATE_SHA256 or model_meta.get("chat_template_sha256") != TEMPLATE_SHA256:
        raise ValueError("MiniMax chat-template hash mismatch")
    if manifest.get("model", {}).get("id") != "minimax/minimax-m3":
        raise ValueError("Frozen sample model ID mismatch")
    if manifest.get("sift", {}).get("primary_target_tokens") != PRIMARY_TARGET:
        raise ValueError("Frozen sample primary target mismatch")

    # Construct a strict metadata allowlist. In particular, do not copy or
    # serialize `answer_key`, even though it exists in the source manifest.
    frozen_cases: dict[str, dict[str, Any]] = {}
    for source in manifest.get("cases", []):
        case_id = str(source["id"])
        if case_id in frozen_cases:
            raise ValueError("Frozen manifest contains duplicate task IDs")
        frozen_cases[case_id] = {
            "id": case_id,
            "domain": str(source["domain"]),
            "prompt_sha256": str(source["prompt_sha256"]),
            "m3_rendered_prompt_tokens": int(source["m3_rendered_prompt_tokens"]),
        }
    if len(frozen_cases) != SAMPLE_SIZE:
        raise ValueError("Expected exactly 100 frozen LongBench task IDs")

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    dataset_fields = {"_id", "context", "question", "choice_A", "choice_B", "choice_C", "choice_D"}
    for source_row in iter_selected_dataset_rows(
        dataset_path, set(frozen_cases), dataset_fields
    ):
        case_id = str(source_row.get("_id", ""))
        frozen = frozen_cases.get(case_id)
        if frozen is None:
            continue
        if case_id in seen_ids:
            raise ValueError("Pinned dataset contains a duplicate selected task ID")
        seen_ids.add(case_id)
        # Only allowlisted prompt fields are ever decoded from source rows.
        messages = make_messages(source_row)
        if prompt_sha256(messages) != frozen["prompt_sha256"]:
            raise ValueError(f"Frozen prompt hash mismatch for task {case_id}")
        rendered_tokens = len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)
        if rendered_tokens != frozen["m3_rendered_prompt_tokens"]:
            raise ValueError(f"Frozen MiniMax token count mismatch for task {case_id}")
        cases.append({
            **frozen,
            "messages": messages,
            "full_prompt_tokens": rendered_tokens,
        })
        if len(cases) == SAMPLE_SIZE:
            break
    if len(cases) != SAMPLE_SIZE or seen_ids != set(frozen_cases):
        raise ValueError("Frozen LongBench rows are missing from the dataset")
    cases.sort(key=lambda item: item["id"])
    return tokenizer, cases, frozen_cases


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def run_sweep(
    manifest_path: Path,
    dataset_path: Path,
    tokenizer_path: Path,
    template_path: Path,
    targets: tuple[int, ...],
) -> dict[str, Any]:
    if not targets or any(target <= SAFETY_MARGIN for target in targets):
        raise ValueError("Every target must exceed the 128-token safety margin")
    tokenizer, cases, _ = prepare_cases(
        manifest_path, dataset_path, tokenizer_path, template_path
    )
    core_sha = file_sha256(ROOT / "src/sift/core.py")
    if core_sha != EXPECTED_CORE_SHA256:
        raise ValueError("Current Sift core hash differs from the frozen sweep preflight")

    def count_tokens(messages: list[dict[str, str]]) -> int:
        return len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)

    target_results: list[dict[str, Any]] = []
    for target in targets:
        successful_rows: list[dict[str, Any]] = []
        failed_rows: list[dict[str, str]] = []
        errors: Counter[str] = Counter()
        timings: list[float] = []
        for case in cases:
            started = time.perf_counter()
            try:
                result = core.compact_messages(
                    case["messages"],
                    count_tokens,
                    target=target - SAFETY_MARGIN,
                    raw_limit=1_000_000,
                    protocol="openai",
                )
            except core.CompactionError as error:
                error_code = str(error.code or "compaction_error")
                errors[error_code] += 1
                failed_rows.append({"id": case["id"], "domain": case["domain"], "error_code": error_code})
                continue
            elapsed_ms = (time.perf_counter() - started) * 1000
            timings.append(elapsed_ms)
            forwarded_tokens = count_tokens(result.messages)
            successful_rows.append({
                "id": case["id"],
                "domain": case["domain"],
                "full_prompt_tokens": case["full_prompt_tokens"],
                "forwarded_tokens": forwarded_tokens,
                "within_target": forwarded_tokens <= target - SAFETY_MARGIN,
                "passthrough": result.messages == case["messages"],
                "preprocessing_ms": round(elapsed_ms, 3),
                "selector_method": str(result.audit.get("method", "")),
            })

        sizes = [row["forwarded_tokens"] for row in successful_rows]
        result_ids = [row["id"] for row in successful_rows] + [row["id"] for row in failed_rows]
        if len(result_ids) != SAMPLE_SIZE or set(result_ids) != {case["id"] for case in cases}:
            raise ValueError(f"Target {target} did not account for each frozen task exactly once")
        total_tokens = sum(sizes)
        target_results.append({
            "target_tokens": target,
            "effective_target_after_safety_margin": target - SAFETY_MARGIN,
            "task_count": SAMPLE_SIZE,
            "compaction_completed_count": len(successful_rows),
            "target_fit_count": sum(row["within_target"] for row in successful_rows),
            "fail_closed_count": sum(errors.values()),
            "fail_closed_codes": dict(sorted(errors.items())),
            "failures": failed_rows,
            "prompt_tokens_total": total_tokens,
            "prompt_tokens_mean": total_tokens / len(sizes) if sizes else None,
            "prompt_tokens_median": _percentile(sizes, 0.5),
            "preprocessing_ms_median": _percentile(timings, 0.5),
            "preprocessing_ms_p95": _percentile(timings, 0.95),
            "passthrough_tasks": sum(row["passthrough"] for row in successful_rows),
            "target_violations": sum(not row["within_target"] for row in successful_rows),
            "candidate_forwarded_token_total_successes_only": True,
            "rows": successful_rows,
        })

    return {
        "schema_version": 1,
        "title": "LongBench v2 Sift target sensitivity on the current core",
        "status": "offline_operational_preflight_not_quality_evidence",
        "network_calls": 0,
        "api_calls": 0,
        "answer_key_and_response_values_decoded": False,
        "answer_keys_or_responses_used": False,
        "model_outputs_read": False,
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "sha256": file_sha256(dataset_path),
            "sample_size": SAMPLE_SIZE,
            "exposure": "frozen public training-split development sample; all task IDs were used in the prior 100-task evaluation",
        },
        "model_tokenization": {
            "model_id": "minimax/minimax-m3",
            "tokenizer_sha256": file_sha256(tokenizer_path),
            "template_sha256": file_sha256(template_path),
        },
        "inputs": {
            "dataset": repo_relative(dataset_path),
            "manifest": repo_relative(manifest_path),
            "manifest_sha256": file_sha256(manifest_path),
            "target_sweep_script": repo_relative(Path(__file__)),
            "target_sweep_script_sha256": file_sha256(Path(__file__)),
            "renderer_script": "benchmarks/prepare_longbench_v2_minimax.py",
            "renderer_script_sha256": EXPECTED_RENDERER_SHA256,
            "prompt_builder_script": "benchmarks/prepare_longbench_v2.py",
            "prompt_builder_script_sha256": EXPECTED_PROMPT_BUILDER_SHA256,
            "source_allowlists": {
                "manifest_root": ["dataset", "model", "sift", "cases"],
                "manifest": ["id", "domain", "prompt_sha256", "m3_rendered_prompt_tokens"],
                "dataset_row": ["_id", "context", "question", "choice_A", "choice_B", "choice_C", "choice_D"],
            },
        },
        "current_core_sha256": core_sha,
        "target_parameters": {
            "targets_tokens": list(targets),
            "safety_margin_tokens": SAFETY_MARGIN,
            "route_context_or_pricing_verified": False,
        },
        "targets": target_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_DEFAULT)
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument(
        "--targets",
        default=",".join(map(str, DEFAULT_TARGETS)),
        help="Comma-separated target sizes in tokens",
    )
    args = parser.parse_args()
    targets = tuple(int(value) for value in args.targets.split(","))
    result = run_sweep(
        args.manifest, args.dataset, args.tokenizer, args.template,
        targets,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "core_sha256": result["current_core_sha256"],
        "targets": [
            {key: value for key, value in row.items() if key != "rows"}
            for row in result["targets"]
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
