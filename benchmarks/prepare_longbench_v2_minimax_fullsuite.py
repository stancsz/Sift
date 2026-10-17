"""Prepare a deterministic, answer-key-separated LongBench v2 MiniMax schedule.

This command is offline-only. It reads the pinned dataset and local MiniMax M3
tokenizer/template assets, reconstructs every Full/Sift request, and writes a
hash-bound one-repeat-per-arm schedule. Prompt bodies are deliberately not
serialized; the dataset, source hashes, prompt hashes, and body hashes allow a
future runner to reconstruct each one exactly. Scoring keys live in a separate
map and are never included in request bodies.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import random
import sys
from typing import Any

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import (  # noqa: E402
    HF_TEMPLATE_URL,
    HF_TOKENIZER_URL,
    MODEL_ID,
    render_minimax,
)
from sift import CompactionError, compact_messages  # noqa: E402

DATASET_DEFAULT = ROOT / ".runs/longbench-v2-data-pinned.json"
TOKENIZER_DEFAULT = ROOT / "tmp/minimax-m3-tokenizer.json"
TEMPLATE_DEFAULT = ROOT / "tmp/minimax-m3-chat-template.jinja"
OUTPUT_DEFAULT = ROOT / ".runs/longbench-v2-minimax-fullsuite-one-repeat.json.gz"
EXPECTED_ROWS = 503
EXPECTED_DATASET_SHA256 = DATASET_SHA256
EXPECTED_TOKENIZER_SHA256 = "bb1f1626cf01448f1e3b6036d0a061ffc66c91d9046aada14ea23a5441b5ad6e"
EXPECTED_TEMPLATE_SHA256 = "11421244f67553498e5c8112dae02802025bcc4305ec45ad380af95c96f9fe64"
DEFAULT_TARGET_TOKENS = 32_768
DEFAULT_SAFETY_MARGIN_TOKENS = 128
DEFAULT_RAW_LIMIT_TOKENS = 1_000_000
DEFAULT_OUTPUT_TOKENS = 64
MINIMAX_PROVIDER_INPUT_CAP = 524_288
PROVIDER_SLUG = "minimax"
DEFAULT_SEED = 20261022
INPUT_LIMIT_CHARACTERS = 16_777_216
INPUT_LIMIT_NODES = 250_000


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def file_hashes(paths: dict[str, Path]) -> dict[str, str]:
    return {name: file_sha256(path) for name, path in sorted(paths.items())}


def _body(*, messages: list[dict[str, str]], seed: int,
          output_tokens: int) -> dict[str, Any]:
    """Match the repository's frozen MiniMax OpenRouter request protocol."""
    return {
        "model": MODEL_ID,
        "messages": messages,
        "temperature": 0.1,
        "top_p": 0.8,
        "seed": seed,
        "max_tokens": output_tokens,
        "reasoning": {"enabled": False},
        "stream": True,
        "stream_options": {"include_usage": True},
        "provider": {"only": [PROVIDER_SLUG], "allow_fallbacks": False},
    }


def _route_status(prompt_tokens: int, input_cap: int) -> dict[str, Any]:
    if prompt_tokens > input_cap:
        return {
            "status": "ineligible",
            "reason": "provider_input_cap",
            "local_prompt_tokens": prompt_tokens,
            "provider_input_cap_tokens": input_cap,
        }
    return {
        "status": "eligible_by_local_token_estimate",
        "reason": None,
        "local_prompt_tokens": prompt_tokens,
        "provider_input_cap_tokens": input_cap,
    }


def prepare(
    dataset_path: Path,
    tokenizer_path: Path,
    template_path: Path,
    output_path: Path,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    safety_margin_tokens: int = DEFAULT_SAFETY_MARGIN_TOKENS,
    raw_limit_tokens: int = DEFAULT_RAW_LIMIT_TOKENS,
    output_tokens: int = DEFAULT_OUTPUT_TOKENS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Build the full 503-row schedule without networking or credential access."""
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen schedule: {output_path}")
    for label, value in (
        ("target_tokens", target_tokens),
        ("output_tokens", output_tokens),
        ("raw_limit_tokens", raw_limit_tokens),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{label} must be a positive integer")
    if type(safety_margin_tokens) is not int or safety_margin_tokens < 0:
        raise ValueError("safety_margin_tokens must be a nonnegative integer")
    effective_target = target_tokens - safety_margin_tokens
    if effective_target <= 0 or raw_limit_tokens < effective_target:
        raise ValueError("effective Sift target must be positive and no larger than raw_limit")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")

    for path in (dataset_path, tokenizer_path, template_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    actual_hashes = {
        "dataset": file_sha256(dataset_path),
        "tokenizer": file_sha256(tokenizer_path),
        "chat_template": file_sha256(template_path),
    }
    expected_hashes = {
        "dataset": EXPECTED_DATASET_SHA256,
        "tokenizer": EXPECTED_TOKENIZER_SHA256,
        "chat_template": EXPECTED_TEMPLATE_SHA256,
    }
    if actual_hashes != expected_hashes:
        raise ValueError(
            "Pinned data/tokenizer/template SHA-256 mismatch: "
            + json.dumps({"expected": expected_hashes, "actual": actual_hashes}, sort_keys=True)
        )

    tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def count_messages(messages: list[dict[str, str]]) -> int:
        rendered = render_minimax(messages)
        return len(tokenizer.encode(rendered, add_special_tokens=False).ids)

    runner_path = Path(__file__).resolve()
    data_reader_path = ROOT / "benchmarks/prepare_longbench_v2.py"
    renderer_path = ROOT / "benchmarks/prepare_longbench_v2_minimax.py"
    sift_path = ROOT / "src/sift/core.py"
    source_hashes = file_hashes({
        "dataset": dataset_path,
        "dataset_reader": data_reader_path,
        "renderer": renderer_path,
        "sift_core": sift_path,
        "runner": runner_path,
        "tokenizer": tokenizer_path,
        "chat_template": template_path,
    })

    cases: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    scoring_keys: dict[str, str] = {}
    seen_ids: set[str] = set()
    sift_failure_counts: Counter[str] = Counter()
    arm_status_counts: Counter[str] = Counter()
    schedule_rng = random.Random(seed)

    for row_index, row in enumerate(iter_json_array(dataset_path)):
        case_id = row.get("_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"Dataset row {row_index} has no valid _id")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate LongBench question ID: {case_id}")
        seen_ids.add(case_id)
        answer = row.get("answer")
        if answer not in {"A", "B", "C", "D"}:
            raise ValueError(f"Dataset row {case_id} has an invalid answer key")

        messages = make_messages(row)
        full_tokens = count_messages(messages)
        full_prompt_hash = prompt_sha256(messages)
        pair_seed = seed + row_index + 1
        full_body = _body(
            messages=messages,
            seed=pair_seed,
            output_tokens=output_tokens,
        )
        full_status = _route_status(full_tokens, MINIMAX_PROVIDER_INPUT_CAP)
        full_job = {
            "case_id": case_id,
            "arm": "full",
            "repeat": 1,
            "seed": pair_seed,
            "prompt_sha256": full_prompt_hash,
            "body_sha256": canonical_sha256(full_body),
            "local_prompt_tokens": full_tokens,
            "eligibility": full_status,
        }
        arm_status_counts[f"full:{full_status['status']}"] += 1

        sift_status: dict[str, Any]
        sift_job: dict[str, Any]
        sift_audit: dict[str, Any] | None = None
        try:
            result = compact_messages(
                messages,
                count_messages,
                target=effective_target,
                raw_limit=raw_limit_tokens,
                max_input_characters=INPUT_LIMIT_CHARACTERS,
                max_input_nodes=INPUT_LIMIT_NODES,
                protocol="openai",
            )
            sift_messages = result.messages
            sift_tokens = result.audit["forwarded_tokens"]
            sift_prompt_hash = prompt_sha256(sift_messages)
            sift_body = _body(
                messages=sift_messages,
                seed=pair_seed,
                output_tokens=output_tokens,
            )
            sift_status = _route_status(sift_tokens, MINIMAX_PROVIDER_INPUT_CAP)
            sift_job = {
                "case_id": case_id,
                "arm": "sift",
                "repeat": 1,
                "seed": pair_seed,
                "prompt_sha256": sift_prompt_hash,
                "body_sha256": canonical_sha256(sift_body),
                "local_prompt_tokens": sift_tokens,
                "eligibility": sift_status,
            }
            sift_audit = {
                key: result.audit.get(key)
                for key in (
                    "compacted", "input_tokens", "forwarded_tokens",
                    "omitted_estimated_tokens", "preserved_recent_turns",
                    "preserved_recent_tool_cycles", "selected_excerpts", "method",
                )
                if key in result.audit
            }
        except CompactionError as error:
            reason = error.code if error.code == "raw_limit" else "compaction_error"
            sift_failure_counts[reason] += 1
            sift_status = {
                "status": "ineligible",
                "reason": reason,
                "error_code": error.code,
            }
            sift_job = {
                "case_id": case_id,
                "arm": "sift",
                "repeat": 1,
                "seed": pair_seed,
                "prompt_sha256": None,
                "body_sha256": None,
                "local_prompt_tokens": full_tokens,
                "eligibility": sift_status,
            }
        arm_status_counts[f"sift:{sift_status['status']}"] += 1

        # Randomize within each matched pair, deterministically; both arms use
        # the same provider seed so token/quality differences are paired.
        pair = [full_job, sift_job]
        if schedule_rng.getrandbits(1):
            pair.reverse()
        jobs.extend(pair)
        scoring_keys[case_id] = answer
        cases.append({
            "case_id": case_id,
            "dataset_index": row_index,
            "domain": row.get("domain"),
            "sub_domain": row.get("sub_domain"),
            "difficulty": row.get("difficulty"),
            "length": row.get("length"),
            "full": {
                "prompt_sha256": full_prompt_hash,
                "local_prompt_tokens": full_tokens,
                "eligibility": full_status,
            },
            "sift": {
                "local_prompt_tokens": sift_job["local_prompt_tokens"],
                "prompt_sha256": sift_job["prompt_sha256"],
                "eligibility": sift_status,
                "audit": sift_audit,
            },
        })

    if len(seen_ids) != EXPECTED_ROWS or len(cases) != EXPECTED_ROWS:
        raise ValueError(
            f"Pinned dataset must contain exactly {EXPECTED_ROWS} unique rows; "
            f"observed {len(cases)} rows and {len(seen_ids)} unique IDs"
        )
    if len(jobs) != EXPECTED_ROWS * 2 or set(scoring_keys) != seen_ids:
        raise AssertionError("Full-suite schedule or scoring-key coverage is incomplete")

    eligible_pairs = sum(
        case["full"]["eligibility"]["status"] == "eligible_by_local_token_estimate"
        and case["sift"]["eligibility"]["status"] == "eligible_by_local_token_estimate"
        for case in cases
    )
    pair_categories: Counter[str] = Counter()
    for case in cases:
        full_ok = case["full"]["eligibility"]["status"] == "eligible_by_local_token_estimate"
        sift_eligibility = case["sift"]["eligibility"]
        sift_ok = sift_eligibility["status"] == "eligible_by_local_token_estimate"
        if full_ok and sift_ok:
            pair_categories["both_arms_eligible"] += 1
        elif not full_ok and sift_ok:
            pair_categories["sift_only"] += 1
        elif full_ok and not sift_ok:
            pair_categories["full_only"] += 1
        elif sift_eligibility.get("reason") == "raw_limit":
            pair_categories["excluded_sift_raw_limit"] += 1
        else:
            pair_categories["excluded_other"] += 1
    content: dict[str, Any] = {
        "schema_version": 1,
        "status": "prepared_only_no_dispatch",
        "dispatch_authorized": False,
        "evidence_class": "public_exposed_longbench_v2_train_development_set",
        "preparation_is_offline_only": True,
        "network_calls": 0,
        "credential_access": False,
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "split": "train",
            "expected_rows": EXPECTED_ROWS,
            "observed_rows": len(cases),
            "sha256": actual_hashes["dataset"],
        },
        "model_and_tokenizer": {
            "model_id": MODEL_ID,
            "tokenizer_source": HF_TOKENIZER_URL,
            "tokenizer_sha256": actual_hashes["tokenizer"],
            "chat_template_source": HF_TEMPLATE_URL,
            "chat_template_sha256": actual_hashes["chat_template"],
            "renderer": "benchmarks/prepare_longbench_v2_minimax.py:render_minimax",
            "rendering_note": (
                "Prompt counts and hashes use the repository's current MiniMax M3 renderer "
                "and pinned tokenizer. The template file is hash-verified; the renderer is "
                "the exact local implementation used to reproduce the frozen M3 format."
            ),
        },
        "provider_route_assumption": {
            "requested_model": MODEL_ID,
            "provider_slug": PROVIDER_SLUG,
            "fallbacks_allowed": False,
            "input_cap_tokens": MINIMAX_PROVIDER_INPUT_CAP,
            "cap_source": "existing authorized MiniMax route limit; not refreshed by this offline preparer",
            "eligibility_rule": "local rendered prompt tokens <= 524288 input-token cap; output cap is recorded separately",
        },
        "protocol": {
            "arms": ["full", "sift"],
            "repeats_per_arm": 1,
            "planned_jobs": EXPECTED_ROWS * 2,
            "temperature": 0.1,
            "top_p": 0.8,
            "reasoning": {"enabled": False},
            "max_output_tokens": output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "matched_seed_formula": "seed + dataset_index + 1; same seed for both arms of each question",
            "seed": seed,
            "request_order": "pinned dataset row order; deterministic random arm order within each pair",
            "sift_configured_target_tokens": target_tokens,
            "sift_safety_margin_tokens": safety_margin_tokens,
            "sift_effective_target_tokens": effective_target,
            "sift_raw_limit_tokens": raw_limit_tokens,
            "sift_max_input_characters": INPUT_LIMIT_CHARACTERS,
            "sift_max_input_nodes": INPUT_LIMIT_NODES,
            "choice_scoring_rule": "exact uppercase A/B/C/D after trimming; scoring keys kept separately",
        },
        "coverage": {
            "dataset_ids_represented": len(seen_ids),
            "jobs_scheduled_including_ineligible": len(jobs),
            "eligible_paired_questions_by_local_estimate": eligible_pairs,
            "question_pair_categories": dict(sorted(pair_categories.items())),
            "arm_status_counts": dict(sorted(arm_status_counts.items())),
            "sift_failure_counts": dict(sorted(sift_failure_counts.items())),
            "ineligibility_is_explicit": True,
            "ineligible_jobs_are_retained_in_schedule": True,
        },
        "source_hashes": source_hashes,
        "cases": cases,
        "schedule": jobs,
        "schedule_sha256": canonical_sha256(jobs),
        "scoring_keys": scoring_keys,
        "scoring_keys_separate_from_request_bodies": True,
        "request_bodies_serialized": False,
        "request_reconstruction": (
            "Rebuild each body from its case_id/arm using the pinned dataset, renderer, "
            "tokenizer, Sift source, and protocol; verify prompt_sha256 and body_sha256 "
            "before dispatch. Ineligible jobs remain present and must not be dispatched."
        ),
    }
    content["manifest_sha256"] = canonical_sha256(content)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with output_path.open("xb") as raw_output:
        with gzip.GzipFile(fileobj=raw_output, mode="wb", filename="", mtime=0, compresslevel=9) as compressed:
            compressed.write(encoded)
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--target-tokens", type=int, default=DEFAULT_TARGET_TOKENS)
    parser.add_argument("--safety-margin-tokens", type=int, default=DEFAULT_SAFETY_MARGIN_TOKENS)
    parser.add_argument("--raw-limit-tokens", type=int, default=DEFAULT_RAW_LIMIT_TOKENS)
    parser.add_argument("--output-tokens", type=int, default=DEFAULT_OUTPUT_TOKENS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    report = prepare(
        args.dataset,
        args.tokenizer,
        args.template,
        args.output,
        target_tokens=args.target_tokens,
        safety_margin_tokens=args.safety_margin_tokens,
        raw_limit_tokens=args.raw_limit_tokens,
        output_tokens=args.output_tokens,
        seed=args.seed,
    )
    print(json.dumps({
        "output": str(args.output),
        "manifest_sha256": report["manifest_sha256"],
        "schedule_sha256": report["schedule_sha256"],
        "coverage": report["coverage"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
