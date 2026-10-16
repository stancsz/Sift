"""Freeze a balanced 100-case LongBench v2 sample for MiniMax M3.

This local-only preparation step reads the already pinned public dataset,
MiniMax tokenizer, and published chat-template file. It makes no network or
provider calls and refuses to overwrite an existing manifest.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

from tokenizers import Tokenizer

from prepare_longbench_v2 import (
    DATASET_REVISION,
    DATASET_SHA256,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)
from prepare_longbench_v2_minimax import (
    HF_TEMPLATE_URL,
    HF_TOKENIZER_URL,
    MODEL_ID,
    render_minimax,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = (
    Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
)
DEFAULT_TOKENIZER = ROOT / "tmp" / "minimax-m3-tokenizer.json"
DEFAULT_TEMPLATE = ROOT / "tmp" / "minimax-m3-chat-template.jinja"
DEFAULT_OUTPUT = ROOT / "docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json"

# Hash pins match the local assets used by the earlier M3 preparations. The
# preparer does not fetch or update any of them.
PINNED_DATASET_SHA256 = DATASET_SHA256
PINNED_TOKENIZER_SHA256 = "bb1f1626cf01448f1e3b6036d0a061ffc66c91d9046aada14ea23a5441b5ad6e"
PINNED_TEMPLATE_SHA256 = "11421244f67553498e5c8112dae02802025bcc4305ec45ad380af95c96f9fe64"

SEED = 20261021
SAMPLE_SIZE = 100
SIFT_TARGET = 32_768
MAX_LOCAL_PROMPT_TOKENS = 150_000
COUNT_ONLY_SCAN_LIMIT = 160_000
MODEL_CONTEXT_TOKENS = 1_048_576
OBSERVED_PROVIDER_REQUEST_LIMIT = 524_288
CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO = 3.25
INPUT_PRICE_PER_MILLION = 0.30
OUTPUT_PRICE_PER_MILLION = 1.20
RESTARTS = 128

TOKEN_STRATA = (
    (32_769, 65_536, "32-64k"),
    (65_537, 98_304, "64-96k"),
    (98_305, MAX_LOCAL_PROMPT_TOKENS, "96-150k"),
)


def token_stratum(count: int) -> str:
    for lower, upper, label in TOKEN_STRATA:
        if lower <= count <= upper:
            return label
    raise ValueError(f"Token count falls outside configured strata: {count}")


def marginal_targets(candidates: list[dict], size: int) -> dict[str, dict[str, int]]:
    """Make near-equal targets, respecting each observed category's capacity."""
    targets: dict[str, dict[str, int]] = {}
    dimensions = {
        "domain": [row["domain"] for row in candidates],
        "difficulty": [row["difficulty"] for row in candidates],
        "length": [row["length"] for row in candidates],
        "m3_token_stratum": [row["m3_token_stratum"] for row in candidates],
    }
    for dimension, values in dimensions.items():
        capacities = Counter(values)
        quotas = {value: 0 for value in sorted(capacities)}
        remaining = size
        active = list(quotas)
        while remaining:
            if not active:
                raise ValueError(f"Cannot allocate {size} slots across {dimension}")
            base, extra = divmod(remaining, len(active))
            allocation = {
                value: min(capacities[value] - quotas[value], base + (i < extra))
                for i, value in enumerate(active)
            }
            used = sum(allocation.values())
            if not used:
                raise ValueError(f"Cannot satisfy marginal quotas for {dimension}")
            for value, amount in allocation.items():
                quotas[value] += amount
            remaining -= used
            active = [value for value in active if quotas[value] < capacities[value]]
        targets[dimension] = quotas
    return targets


def _objective(counts: dict[str, Counter], targets: dict[str, dict[str, int]]) -> float:
    total = 0.0
    for dimension, quota in targets.items():
        for value, expected in quota.items():
            # Scale every dimension comparably and avoid large classes
            # dominating merely because their quota is larger.
            difference = counts[dimension][value] - expected
            total += difference * difference / max(1, expected)
    return total


def balanced_selection(candidates: list[dict], seed: int, size: int) -> tuple[list[dict], dict]:
    if len(candidates) < size:
        raise ValueError(
            f"Need {size} eligible candidates in the 32,769-150,000 range; found {len(candidates)}"
        )
    targets = marginal_targets(candidates, size)
    dimensions = tuple(targets)
    best: list[dict] | None = None
    best_objective = float("inf")

    # Deterministic multistart greedy marginal balancing handles sparse
    # domain/difficulty/length combinations while ensuring a reproducible
    # global optimum among the recorded restart attempts.
    for restart in range(RESTARTS):
        order = list(candidates)
        random.Random(seed + restart).shuffle(order)
        picked: list[dict] = []
        counts = {dimension: Counter() for dimension in dimensions}
        remaining = list(order)
        while len(picked) < size:
            best_index = -1
            best_next_objective = float("inf")
            for index, row in enumerate(remaining):
                for dimension in dimensions:
                    counts[dimension][row[dimension]] += 1
                score = _objective(counts, targets)
                for dimension in dimensions:
                    counts[dimension][row[dimension]] -= 1
                if score < best_next_objective:
                    best_next_objective = score
                    best_index = index
            chosen = remaining.pop(best_index)
            picked.append(chosen)
            for dimension in dimensions:
                counts[dimension][chosen[dimension]] += 1
        score = _objective(counts, targets)
        tie_key = tuple(row["id"] for row in sorted(picked, key=lambda row: row["id"]))
        if (score < best_objective or
                (score == best_objective and best is not None and
                 tie_key < tuple(row["id"] for row in sorted(best, key=lambda row: row["id"])) )):
            best, best_objective = picked, score

    assert best is not None
    selected = sorted(best, key=lambda row: (row["domain"], row["difficulty"], row["length"], row["id"]))
    observed = {
        dimension: dict(Counter(row[dimension] for row in selected))
        for dimension in dimensions
    }
    return selected, {
        "balanced_marginal_targets": targets,
        "selected_marginals": observed,
        "weighted_squared_deviation": best_objective,
        "deterministic_greedy_restarts": RESTARTS,
    }


def prepare(dataset_path: Path, tokenizer_path: Path, template_path: Path,
            output_path: Path, seed: int = SEED) -> dict:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen selection: {output_path}")
    for path in (dataset_path, tokenizer_path, template_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    actual_dataset_hash = file_sha256(dataset_path)
    actual_tokenizer_hash = file_sha256(tokenizer_path)
    actual_template_hash = file_sha256(template_path)
    if actual_dataset_hash != PINNED_DATASET_SHA256:
        raise ValueError("Local LongBench v2 data.json does not match the pinned SHA-256")
    if actual_tokenizer_hash != PINNED_TOKENIZER_SHA256:
        raise ValueError("Local MiniMax M3 tokenizer does not match the pinned SHA-256")
    if actual_template_hash != PINNED_TEMPLATE_SHA256:
        raise ValueError("Local MiniMax M3 chat template does not match the pinned SHA-256")

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    candidates = []
    scanned = 0
    above_target = 0
    for row in iter_json_array(dataset_path):
        scanned += 1
        messages = make_messages(row)
        count = len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)
        if count > SIFT_TARGET:
            above_target += 1
        if SIFT_TARGET < count <= MAX_LOCAL_PROMPT_TOKENS:
            candidates.append({
                "id": row["_id"],
                "domain": row["domain"],
                "sub_domain": row["sub_domain"],
                "difficulty": row["difficulty"],
                "length": row["length"],
                "answer_key": row["answer"],
                "context_chars": len(row["context"]),
                "m3_rendered_prompt_tokens": count,
                "m3_token_stratum": token_stratum(count),
                "prompt_sha256": prompt_sha256(messages),
            })
    if scanned != 503:
        raise ValueError(f"Expected exactly 503 LongBench v2 rows, observed {scanned}")
    if not candidates:
        raise ValueError("No LongBench rows satisfy the strict 32K-150K rendered-token bounds")
    eligible_by_stratum = dict(Counter(row["m3_token_stratum"] for row in candidates))
    if len(candidates) < SAMPLE_SIZE:
        raise ValueError(
            f"Only {len(candidates)} candidates meet strict 32,768 < M3 tokens <= "
            f"{MAX_LOCAL_PROMPT_TOKENS}; stratum counts: {eligible_by_stratum}"
        )

    selected, balance = balanced_selection(candidates, seed, SAMPLE_SIZE)
    counts = [row["m3_rendered_prompt_tokens"] for row in selected]
    if len(selected) != SAMPLE_SIZE or min(counts) <= SIFT_TARGET:
        raise AssertionError("Selected sample failed the exact size or above-target audit")
    if max(counts) > MAX_LOCAL_PROMPT_TOKENS:
        raise AssertionError("Selected sample exceeds the conservative local-token cap")
    if max(counts) >= MODEL_CONTEXT_TOKENS:
        raise AssertionError("Selected sample exceeds MiniMax M3's published context")
    if "long" not in Counter(row["length"] for row in selected):
        length_coverage_note = (
            "Zero LongBench length=long cases are represented: the pinned dataset has no "
            "length=long candidates in this strict >32,768 to <=150,000 M3-token eligibility range."
        )
    else:
        length_coverage_note = "LongBench length=long cases are represented in the selected sample."
    per_case_full_projection = [
        math.ceil(row["m3_rendered_prompt_tokens"] * CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO) + 16
        for row in selected
    ]
    max_full_request_projected_tokens = max(per_case_full_projection)
    max_sift_request_projected_tokens = (
        math.ceil((SIFT_TARGET - 128) * CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO) + 16
    )
    total_full_tokens = sum(counts)
    three_repeat_input_projected_tokens = (
        (total_full_tokens + SAMPLE_SIZE * SIFT_TARGET) * 3 * 4
    )
    three_repeat_output_tokens = SAMPLE_SIZE * 2 * 3 * 16
    input_cost_estimate = (
        three_repeat_input_projected_tokens * INPUT_PRICE_PER_MILLION / 1_000_000
    )
    output_cost_estimate = (
        three_repeat_output_tokens * OUTPUT_PRICE_PER_MILLION / 1_000_000
    )

    wrapper = [
        {"role": "system", "content": "<frozen system prompt>"},
        {"role": "user", "content": "<frozen context message>"},
        {"role": "assistant", "content": "Ready."},
        {"role": "user", "content": "<frozen question and choices>"},
    ]
    report = {
        "schema_version": 1,
        "status": "frozen public LongBench v2 development sample; no generations made during preparation",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "blinding_note": (
            "Public training-split sample, not a blind or independently authored holdout. "
            "Selection is mechanically seeded from tokenizer counts and metadata; no manual case substitutions."
        ),
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "split": "train (503 public rows)",
            "data_file": dataset_path.name,
            "data_file_sha256": actual_dataset_hash,
            "license": "apache-2.0",
        },
        "model": {
            "id": MODEL_ID,
            "context_tokens": MODEL_CONTEXT_TOKENS,
            "tokenizer_source": HF_TOKENIZER_URL,
            "tokenizer_sha256": actual_tokenizer_hash,
            "chat_template_source": HF_TEMPLATE_URL,
            "chat_template_sha256": actual_template_hash,
            "reasoning_mode": "disabled",
            "counting_note": (
                "Counts use the pinned MiniMax tokenizer on the frozen text-only M3 template "
                "renderer with reasoning disabled. Counts are local estimates; the provider's "
                "reported prompt usage remains authoritative during execution."
            ),
        },
        "provider_endpoint": {
            "provider_slug": "minimax",
            "provider_name": "Minimax",
            "model_endpoint_id": "minimax/minimax-m3-20260531",
            "metadata_source": "https://openrouter.ai/api/v1/models/minimax/minimax-m3/endpoints",
            "metadata_checked_date": "2026-10-16",
            "endpoint_context_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT,
            "max_prompt_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT,
            "max_completion_tokens": 512000,
            "input_price_per_million_usd": INPUT_PRICE_PER_MILLION,
            "output_price_per_million_usd": OUTPUT_PRICE_PER_MILLION,
            "request_provider_policy": {"only": ["minimax"], "allow_fallbacks": False},
            "note": "Provider family is pinned and fallbacks are disabled. Endpoint metadata can change; verify again immediately before the run.",
        },
        "sift": {
            "core_sha256": hashlib.sha256((ROOT / "src/sift/core.py").read_bytes()).hexdigest(),
            "primary_target_tokens": SIFT_TARGET,
            "safety_margin_tokens": 128,
        },
        "harness": {
            "preparation_script": "benchmarks/prepare_longbench_v2_minimax_100.py",
            "preparation_script_sha256": file_sha256(Path(__file__).resolve()),
            "runner_path": "benchmarks/run_longbench_v2_minimax.py",
            "runner_sha256": file_sha256(ROOT / "benchmarks/run_longbench_v2_minimax.py"),
        },
        "selection": {
            "seed": seed,
            "scanned_rows": scanned,
            "eligible_strictly_above_32768": above_target,
            "eligible_under_150000_cap": len(candidates),
            "eligible_by_m3_token_stratum": eligible_by_stratum,
            "selected_count": len(selected),
            "selected_min_m3_tokens": min(counts),
            "selected_max_m3_tokens": max(counts),
            "selected_by_domain": dict(Counter(row["domain"] for row in selected)),
            "selected_by_difficulty": dict(Counter(row["difficulty"] for row in selected)),
            "selected_by_length": dict(Counter(row["length"] for row in selected)),
            "selected_by_m3_token_stratum": dict(Counter(row["m3_token_stratum"] for row in selected)),
            "length_label_coverage_note": length_coverage_note,
            "policy": (
                "Eligible prompts have strictly more than 32,768 and no more than 150,000 "
                "locally rendered MiniMax M3 tokens. Select 100 with seeded multistart greedy "
                "balancing across LongBench domain, difficulty, benchmark length, and M3 token-length "
                "strata. The 150K ceiling is a conservative local cap based on the verified MiniMax "
                "endpoint's 524,288-token prompt limit and the 3.25x request-size projection."
            ),
            **balance,
        },
        "rendering": {
            "message_wrapper_sha256": prompt_sha256(wrapper),
            "renderer": "benchmarks/prepare_longbench_v2_minimax.py:render_minimax",
            "template_file_sha256": actual_template_hash,
        },
        "execution_preflight": {
            "planned_arms": ["full", "sift"],
            "planned_repeats": 3,
            "primary_sift_target_tokens": SIFT_TARGET,
            "sift_effective_input_upper_bound_tokens_after_128_safety_margin": SIFT_TARGET - 128,
            "max_output_tokens_per_request": 16,
            "observed_provider_request_limit_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT,
            "provider_to_local_context_projection_ratio": CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO,
            "max_selected_full_local_prompt_tokens": max(counts),
            "max_selected_full_request_projected_tokens_including_output": max_full_request_projected_tokens,
            "max_selected_full_request_headroom_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT - max_full_request_projected_tokens,
            "max_sift_request_projected_tokens_including_output": max_sift_request_projected_tokens,
            "max_sift_request_headroom_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT - max_sift_request_projected_tokens,
            "input_price_per_million_usd": INPUT_PRICE_PER_MILLION,
            "input_cost_reserve_multiplier": 4,
            "output_price_per_million_usd": OUTPUT_PRICE_PER_MILLION,
            "total_full_local_input_tokens": total_full_tokens,
            "full_plus_32k_sift_input_tokens_per_repeat": total_full_tokens + SAMPLE_SIZE * SIFT_TARGET,
            "three_repeat_input_tokens_after_4x_projection": three_repeat_input_projected_tokens,
            "three_repeat_output_tokens_at_max_output": three_repeat_output_tokens,
            "three_repeat_projected_input_cost_usd": input_cost_estimate,
            "three_repeat_projected_output_cost_usd": output_cost_estimate,
            "three_repeat_projected_total_cost_usd": input_cost_estimate + output_cost_estimate,
            "20_usd_ceiling_covers_three_repeats": input_cost_estimate + output_cost_estimate <= 20,
            "note": "Planning estimate only; actual provider-reported usage and pricing govern. No API calls were made during preparation.",
        },
        "cases": selected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def count_cap_candidates(dataset_path: Path, tokenizer_path: Path, template_path: Path) -> dict:
    """Count the narrower proposed caps without freezing or writing a manifest."""
    for path in (dataset_path, tokenizer_path, template_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    if file_sha256(dataset_path) != PINNED_DATASET_SHA256:
        raise ValueError("Local LongBench v2 data.json does not match the pinned SHA-256")
    if file_sha256(tokenizer_path) != PINNED_TOKENIZER_SHA256:
        raise ValueError("Local MiniMax M3 tokenizer does not match the pinned SHA-256")
    if file_sha256(template_path) != PINNED_TEMPLATE_SHA256:
        raise ValueError("Local MiniMax M3 chat template does not match the pinned SHA-256")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    eligible = []
    scanned = 0
    for row in iter_json_array(dataset_path):
        scanned += 1
        count = len(tokenizer.encode(
            render_minimax(make_messages(row)), add_special_tokens=False,
        ).ids)
        if SIFT_TARGET < count <= COUNT_ONLY_SCAN_LIMIT:
            eligible.append({
                "id": row["_id"], "domain": row["domain"],
                "sub_domain": row["sub_domain"],
                "difficulty": row["difficulty"], "length": row["length"],
                "tokens": count,
            })
    if scanned != 503:
        raise ValueError(f"Expected exactly 503 LongBench v2 rows, observed {scanned}")
    result = {"scanned_rows": scanned, "eligible_by_cap": {}, "marginals_by_cap": {}}
    for cap in (120_000, 130_000, 150_000, 155_000, 160_000):
        rows = [row for row in eligible if row["tokens"] <= cap]
        result["eligible_by_cap"][str(cap)] = len(rows)
        result["marginals_by_cap"][str(cap)] = {
            "token_strata": dict(Counter(
                "32-64k" if row["tokens"] <= 65_536 else
                "64-96k" if row["tokens"] <= 98_304 else
                f"96-{cap // 1000}k"
                for row in rows
            )),
            "domain": dict(Counter(row["domain"] for row in rows)),
            "sub_domain": dict(Counter(row["sub_domain"] for row in rows)),
            "difficulty": dict(Counter(row["difficulty"] for row in rows)),
            "length": dict(Counter(row["length"] for row in rows)),
        }
    result["balanced_100_case_projections"] = {}
    for cap in (120_000, 150_000, 155_000, 160_000):
        cap_rows = [row for row in eligible if row["tokens"] <= cap]
        normalized = []
        for row in cap_rows:
            label = (
                "32-64k" if row["tokens"] <= 65_536 else
                "64-96k" if row["tokens"] <= 98_304 else
                f"96-{cap // 1000}k"
            )
            normalized.append({
                "id": row["id"], "domain": row["domain"],
                "sub_domain": row["sub_domain"], "difficulty": row["difficulty"],
                "length": row["length"], "answer_key": "?",
                "context_chars": 0,
                "m3_rendered_prompt_tokens": row["tokens"],
                "m3_token_stratum": label, "prompt_sha256": "",
            })
        if len(normalized) >= SAMPLE_SIZE:
            sample, balance = balanced_selection(normalized, SEED, SAMPLE_SIZE)
            counts = [row["m3_rendered_prompt_tokens"] for row in sample]
            full_plus_sift_per_repeat = sum(counts) + SAMPLE_SIZE * SIFT_TARGET
            projected_tokens = full_plus_sift_per_repeat * 3 * 4
            output_tokens = SAMPLE_SIZE * 2 * 3 * 16
            full_request_max = math.ceil(max(counts) * CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO) + 16
            sift_request_max = math.ceil((SIFT_TARGET - 128) * CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO) + 16
            result["balanced_100_case_projections"][str(cap)] = {
                "selected_min_tokens": min(counts),
                "selected_median_tokens": statistics.median(counts),
                "selected_max_tokens": max(counts),
                "total_full_m3_tokens": sum(counts),
                "full_plus_32768_sift_tokens_per_repeat": full_plus_sift_per_repeat,
                "three_repeat_tokens_before_4x_projection": full_plus_sift_per_repeat * 3,
                "three_repeat_tokens_after_4x_projection": projected_tokens,
                "conservative_input_cost_usd_at_0_30_per_million": projected_tokens * 0.30 / 1_000_000,
                "estimated_output_tokens_three_repeats": output_tokens,
                "estimated_output_cost_usd_at_endpoint_price": output_tokens * OUTPUT_PRICE_PER_MILLION / 1_000_000,
                "estimated_input_plus_output_cost_usd": (
                    projected_tokens * INPUT_PRICE_PER_MILLION / 1_000_000
                    + output_tokens * OUTPUT_PRICE_PER_MILLION / 1_000_000
                ),
                "observed_provider_request_limit_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT,
                "provider_to_local_context_projection_ratio": CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO,
                "max_selected_full_request_projected_tokens_including_16_output": full_request_max,
                "max_selected_full_request_headroom_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT - full_request_max,
                "max_sift_request_projected_tokens_including_16_output": sift_request_max,
                "max_sift_request_headroom_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT - sift_request_max,
                "per_case_request_context_projection": [
                    {
                        "id": row["id"],
                        "local_full_prompt_tokens": row["m3_rendered_prompt_tokens"],
                        "projected_full_request_tokens_including_16_output": (
                            math.ceil(row["m3_rendered_prompt_tokens"] * CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO) + 16
                        ),
                        "full_request_headroom_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT - (
                            math.ceil(row["m3_rendered_prompt_tokens"] * CONSERVATIVE_PROVIDER_TO_LOCAL_RATIO) + 16
                        ),
                        "local_sift_prompt_upper_bound_tokens": SIFT_TARGET - 128,
                        "projected_sift_request_tokens_including_16_output": sift_request_max,
                        "sift_request_headroom_tokens": OBSERVED_PROVIDER_REQUEST_LIMIT - sift_request_max,
                    }
                    for row in sample
                ],
                "selected_by_domain": dict(Counter(row["domain"] for row in sample)),
                "selected_by_sub_domain": dict(Counter(row["sub_domain"] for row in sample)),
                "selected_by_difficulty": dict(Counter(row["difficulty"] for row in sample)),
                "selected_by_length": dict(Counter(row["length"] for row in sample)),
                "selected_by_m3_token_stratum": dict(Counter(row["m3_token_stratum"] for row in sample)),
                "balance": balance,
            }
        else:
            result["balanced_100_case_projections"][str(cap)] = {
                "eligible_count": len(normalized),
                "not_enough_for_100": True,
            }
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--count-proposed-caps", action="store_true",
        help="Count 120K, 130K, and 150K eligible cases only; do not select or write a manifest.",
    )
    args = parser.parse_args()
    if args.count_proposed_caps:
        print(json.dumps(count_cap_candidates(args.dataset, args.tokenizer, args.template), indent=2))
        return
    result = prepare(args.dataset, args.tokenizer, args.template, args.output, args.seed)
    print(json.dumps({
        "selection": result["selection"],
        "eligible_by_m3_token_stratum": result["selection"]["eligible_by_m3_token_stratum"],
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
