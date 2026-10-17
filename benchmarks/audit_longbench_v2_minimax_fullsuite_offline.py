"""Answer-blind, zero-network Full/default-Sift MiniMax planning audit.

Reads only the pinned dataset ID/domain and prompt fields. The answer field is
skipped by the selective JSON parser and is never decoded or serialized.
Route, price, and token-projection inputs are dated planning assumptions only.
This audit creates no evaluation sample, does not authorize spend, and cannot
dispatch requests.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Iterator

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_BYTES,
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    make_messages,
)
from audit_longbench_v2_target_sweep import _selected_object  # noqa: E402
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from run_longbench_v2_minimax import (  # noqa: E402
    MAX_FULL_LOCAL_TOKENS,
    OPENROUTER_REQUEST_TOKEN_LIMIT,
    OUTPUT_TOKENS,
    PROVIDER_CONTEXT_ESTIMATE_FACTOR,
    SAFETY_MARGIN,
)
from sift import compact_messages  # noqa: E402


DEFAULT_DATASET = ROOT / ".runs" / "longbench-v2-data-pinned.json"
DEFAULT_TOKENIZER = ROOT / "tmp" / "minimax-m3-tokenizer.json"
DEFAULT_TEMPLATE = ROOT / "tmp" / "minimax-m3-chat-template.jinja"
DEFAULT_ROUTE_SNAPSHOT = ROOT / "docs/evals/longbench-v2-minimax-stage2-route-2026-10-17.json"
CONFIGURED_TARGET = 32_768
EFFECTIVE_TARGET = CONFIGURED_TARGET - SAFETY_MARGIN
INPUT_COST_SAFETY_FACTOR = 1.5
INPUT_PRICE_PER_MILLION = 0.30
OUTPUT_PRICE_PER_MILLION = 1.20
PROMPT_FIELDS = {
    "_id", "domain", "context", "question",
    "choice_A", "choice_B", "choice_C", "choice_D",
}


def iter_answer_blind_rows(path: Path, *, chunk_size: int = 2 * 1024 * 1024) -> Iterator[dict[str, Any]]:
    """Stream rows while decoding only ID/domain/prompt allowlisted fields.

    The parser scans source text to find row boundaries. For each row,
    _selected_object decodes only PROMPT_FIELDS and cursor-skips every other
    JSON value, including answer.
    """
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
                        yield _selected_object(raw_object, PROMPT_FIELDS)
                        item_parts = []
                        item_started = False
                position += 1
            if item_started:
                item_parts.append(buffer[item_start:])
                buffer = ""
                item_start = 0
            else:
                buffer = ""
    if item_started:
        raise ValueError("Dataset ended inside a row")


def reserve_usd(input_tokens: int, repeats: int, input_rate: float, output_rate: float) -> float:
    """Historical planning reserve: 1.5x local input plus fixed output cap."""
    raw = repeats * (
        INPUT_COST_SAFETY_FACTOR * input_tokens * input_rate
        + OUTPUT_TOKENS * output_rate
    ) / 1_000_000
    return round(raw, 10)


def build_report(dataset: Path, tokenizer_path: Path, template_path: Path,
                 route_snapshot_path: Path) -> dict[str, Any]:
    if file_sha256(dataset) != DATASET_SHA256 or dataset.stat().st_size != DATASET_BYTES:
        raise ValueError("Pinned dataset SHA-256 or size mismatch")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    core_hash = file_sha256(ROOT / "src/sift/core.py")
    source_hashes = {
        "dataset_sha256": file_sha256(dataset),
        "tokenizer_sha256": file_sha256(tokenizer_path),
        "chat_template_sha256": file_sha256(template_path),
        "core_sha256": core_hash,
        "prompt_builder_sha256": file_sha256(ROOT / "benchmarks/prepare_longbench_v2.py"),
        "renderer_sha256": file_sha256(ROOT / "benchmarks/prepare_longbench_v2_minimax.py"),
        "runner_sha256": file_sha256(ROOT / "benchmarks/run_longbench_v2_minimax.py"),
        "audit_script_sha256": file_sha256(Path(__file__)),
        "route_snapshot_sha256": file_sha256(route_snapshot_path),
    }
    route_snapshot = json.loads(route_snapshot_path.read_text(encoding="utf-8"))
    route_assumptions = {
        "snapshot_path": route_snapshot_path.relative_to(ROOT).as_posix(),
        "checked_utc": route_snapshot.get("checked_utc"),
        "requested_model": route_snapshot.get("requested_model"),
        "provider": route_snapshot.get("provider"),
        "endpoint_model_id": route_snapshot.get("endpoint_model_id"),
        "max_prompt_tokens": route_snapshot.get("max_prompt_tokens"),
        "input_usd_per_million": INPUT_PRICE_PER_MILLION,
        "output_usd_per_million": OUTPUT_PRICE_PER_MILLION,
        "rates_snapshot": route_snapshot.get("pricing_usd_per_token"),
        "status": "dated_historical_planning_assumption_only_refresh_before_any_dispatch",
    }
    if route_assumptions["requested_model"] != "minimax/minimax-m3":
        raise ValueError("Unexpected route snapshot model")
    if int(route_assumptions["max_prompt_tokens"]) != OPENROUTER_REQUEST_TOKEN_LIMIT:
        raise ValueError("Documented route limit differs from frozen runner assumption")
    if float(route_assumptions["rates_snapshot"]["prompt"]) * 1_000_000 != INPUT_PRICE_PER_MILLION:
        raise ValueError("Documented route input price differs from frozen runner assumption")
    if float(route_assumptions["rates_snapshot"]["completion"]) * 1_000_000 != OUTPUT_PRICE_PER_MILLION:
        raise ValueError("Documented route output price differs from frozen runner assumption")
    input_rate = INPUT_PRICE_PER_MILLION
    output_rate = OUTPUT_PRICE_PER_MILLION
    route_limit = int(route_assumptions["max_prompt_tokens"])

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    compact_failures: Counter[str] = Counter()
    started = time.perf_counter()
    for row in iter_answer_blind_rows(dataset):
        case_id = str(row.get("_id", ""))
        if not case_id or case_id in seen:
            raise ValueError("Missing or duplicate task ID")
        seen.add(case_id)
        messages = make_messages(row)
        full_rendered = render_minimax(messages)
        full_tokens = len(tokenizer.encode(full_rendered, add_special_tokens=False).ids)
        full_projected = math.ceil(full_tokens * PROVIDER_CONTEXT_ESTIMATE_FACTOR)
        try:
            sift_result = compact_messages(
                messages,
                lambda candidate: len(tokenizer.encode(
                    render_minimax(candidate), add_special_tokens=False
                ).ids),
                target=EFFECTIVE_TARGET,
                raw_limit=1_000_000,
                protocol="openai",
            )
            sift_tokens = len(tokenizer.encode(
                render_minimax(sift_result.messages), add_special_tokens=False
            ).ids)
            sift_error = None
            sift_target_fit = sift_tokens <= EFFECTIVE_TARGET
            sift_projected = math.ceil(sift_tokens * PROVIDER_CONTEXT_ESTIMATE_FACTOR)
            compact_method = str(sift_result.audit.get("method", ""))
        except Exception as error:
            code = str(getattr(error, "code", None) or type(error).__name__)
            compact_failures[code] += 1
            sift_tokens = None
            sift_error = code
            sift_target_fit = False
            sift_projected = None
            compact_method = None
        full_projection_fit = full_projected <= route_limit
        full_runner_local_fit = full_tokens <= MAX_FULL_LOCAL_TOKENS
        sift_route_fit = sift_projected is not None and sift_projected <= route_limit
        paired_route_fit = full_projection_fit and full_runner_local_fit and sift_route_fit and sift_target_fit
        rows.append({
            "id": case_id,
            "domain": str(row.get("domain", "")),
            "full_local_prompt_tokens": full_tokens,
            "full_projected_provider_prompt_tokens": full_projected,
            "full_historical_route_projection_fit": full_projection_fit,
            "full_runner_local_cap_fit": full_runner_local_fit,
            "default_sift_local_prompt_tokens": sift_tokens,
            "default_sift_projected_provider_prompt_tokens": sift_projected,
            "default_sift_target_fit": sift_target_fit,
            "default_sift_historical_route_projection_fit": sift_route_fit,
            "default_sift_compaction_method": compact_method,
            "default_sift_fail_closed_code": sift_error,
            "matched_pair_historical_dispatch_eligible": paired_route_fit,
            "full_one_repeat_reserve_usd": reserve_usd(full_tokens, 1, input_rate, output_rate),
            "default_sift_one_repeat_reserve_usd": (
                reserve_usd(sift_tokens, 1, input_rate, output_rate) if sift_tokens is not None else None
            ),
        })
        if len(rows) % 50 == 0:
            print(f"prepared {len(rows)}/503 rows", flush=True)

    if len(rows) != 503:
        raise ValueError(f"Expected 503 rows, found {len(rows)}")
    if file_sha256(ROOT / "src/sift/core.py") != core_hash:
        raise ValueError("Sift core changed during audit")
    matched = [r for r in rows if r["matched_pair_historical_dispatch_eligible"]]
    full_tokens_total = sum(r["full_local_prompt_tokens"] for r in rows)
    sift_measured = [r for r in rows if r["default_sift_local_prompt_tokens"] is not None]
    sift_tokens_total = sum(r["default_sift_local_prompt_tokens"] for r in sift_measured)

    def reserve_summary(items: list[dict[str, Any]], arm: str, repeats: int) -> float:
        tokkey = "full_local_prompt_tokens" if arm == "full" else "default_sift_local_prompt_tokens"
        valid = [r for r in items if r[tokkey] is not None]
        total = sum(r[tokkey] for r in valid)
        return reserve_usd(total, repeats, input_rate, output_rate) if valid else 0.0

    duration = time.perf_counter() - started
    return {
        "schema_version": 1,
        "status": "offline_answer_blind_full_suite_cost_and_route_planning_audit",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "actual_dispatch_started": False,
        "network_calls": 0,
        "answers_decoded": False,
        "model_responses_read": False,
        "evaluation_claim": "No accuracy or quality evidence; this is token/eligibility/cost planning only.",
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "split": "train",
            "row_count": len(rows),
            "sha256": source_hashes["dataset_sha256"],
        },
        "configuration": {
            "model": "minimax/minimax-m3",
            "configured_target_tokens": CONFIGURED_TARGET,
            "safety_margin_tokens": SAFETY_MARGIN,
            "effective_target_tokens": EFFECTIVE_TARGET,
            "full_runner_local_prompt_cap": MAX_FULL_LOCAL_TOKENS,
            "route_projection_factor": PROVIDER_CONTEXT_ESTIMATE_FACTOR,
            "route_projection_factor_status": "historical local-to-provider projection from frozen runner; modeled, not a current provider guarantee",
            "output_cap_tokens": OUTPUT_TOKENS,
            "cost_reserve_formula": "repeats * (1.5 * local_input_tokens * input_usd_per_million + output_cap_tokens * output_usd_per_million) / 1e6",
            "cost_safety_factor": INPUT_COST_SAFETY_FACTOR,
            "route_assumptions": route_assumptions,
            "route_assumptions_authorize_dispatch": False,
        },
        "source_hashes": source_hashes,
        "summary": {
            "rows": len(rows),
            "full_input_local_token_total_all_rows": full_tokens_total,
            "default_sift_successful_row_count": len(sift_measured),
            "default_sift_fail_closed_count": len(rows) - len(sift_measured),
            "default_sift_fail_closed_codes": dict(sorted(compact_failures.items())),
            "default_sift_local_token_total_successful_rows_only": sift_tokens_total,
            "full_route_projection_fit_count": sum(r["full_historical_route_projection_fit"] for r in rows),
            "full_runner_local_cap_fit_count": sum(r["full_runner_local_cap_fit"] for r in rows),
            "full_and_runner_cap_fit_count": sum(r["full_historical_route_projection_fit"] and r["full_runner_local_cap_fit"] for r in rows),
            "default_sift_target_fit_count": sum(r["default_sift_target_fit"] for r in rows),
            "default_sift_route_projection_fit_count": sum(r["default_sift_historical_route_projection_fit"] for r in rows),
            "matched_pair_historical_dispatch_eligible_count": len(matched),
            "matched_pair_ineligible_count": len(rows) - len(matched),
            "matched_pair_exclusions": {
                "full_projection_or_local_cap_failure": sum(not (r["full_historical_route_projection_fit"] and r["full_runner_local_cap_fit"]) for r in rows),
                "default_sift_compaction_failure": sum(r["default_sift_fail_closed_code"] is not None for r in rows),
                "default_sift_projection_failure": sum(r["default_sift_fail_closed_code"] is None and not r["default_sift_historical_route_projection_fit"] for r in rows),
                "default_sift_target_failure": sum(not r["default_sift_target_fit"] for r in rows),
            },
            "all_rows_planning_reserve_usd": {
                "full_one_repeat": reserve_summary(rows, "full", 1),
                "default_sift_one_repeat_successful_rows_only": reserve_summary(rows, "sift", 1),
                "full_three_repeats": reserve_summary(rows, "full", 3),
                "default_sift_three_repeats_successful_rows_only": reserve_summary(rows, "sift", 3),
            },
            "matched_pair_route_fit_planning_reserve_usd": {
                "two_arms_one_repeat": round(reserve_summary(matched, "full", 1) + reserve_summary(matched, "sift", 1), 10),
                "two_arms_three_repeats": round(reserve_summary(matched, "full", 3) + reserve_summary(matched, "sift", 3), 10),
                "task_count": len(matched),
            },
            "runtime_seconds_local_only": round(duration, 3),
        },
        "rows": rows,
        "limitations": [
            "Route limit and rates are from the dated 2026-10-17 endpoint snapshot and must be refreshed before dispatch.",
            "Provider-token projection uses the runner historical 3.25 factor; measured local tokenizer counts are not provider usage receipts.",
            "The 1.5x input reserve and 16-token output cap are historical runner planning assumptions, not an invoice, cap, or spend authorization.",
            "Rows excluded by the historical local cap or route projection are not priced as dispatchable requests in the matched-pair reserve.",
            "This audit does not select or freeze an evaluation sample, examine answers, score responses, or override the active 100-task pilot gates.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--route-snapshot", type=Path, default=DEFAULT_ROUTE_SNAPSHOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.dataset, args.tokenizer, args.template, args.route_snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": report["summary"], "source_hashes": report["source_hashes"]}, indent=2))


if __name__ == "__main__":
    main()
