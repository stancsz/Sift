"""Conservative sample-size planning for paired task acceptance.

This exact binomial sensitivity check bounds the probability that full context
passes while Sift fails. It ignores Sift-only wins, so it is conservative for
the paired acceptance-rate difference. It is a planning aid, not the primary
paired-risk-difference analysis.
"""

from __future__ import annotations

import argparse
import json
import math

MARGIN = 0.02
ALPHA = 0.05
TARGET_POWER = 0.80
MAX_TASKS = 10_000


def _lower_tail(n: int, probability: float, maximum: int) -> float:
    """Return P(X <= maximum) for X ~ Binomial(n, probability)."""
    if maximum < 0:
        return 0.0
    if probability == 0:
        return 1.0
    if maximum >= n:
        return 1.0

    complement = 1.0 - probability
    mass = math.exp(n * math.log1p(-probability))
    total = mass
    for k in range(maximum):
        mass *= ((n - k) / (k + 1)) * (probability / complement)
        total += mass
    return total


def critical_harm_count(n: int) -> tuple[int, float]:
    """Largest harm count whose exact null lower-tail probability is <= alpha."""
    complement = 1.0 - MARGIN
    mass = math.exp(n * math.log1p(-MARGIN))
    cumulative = mass
    critical = 0 if cumulative <= ALPHA else -1
    for k in range(n):
        mass *= ((n - k) / (k + 1)) * (MARGIN / complement)
        candidate = cumulative + mass
        if candidate > ALPHA:
            break
        cumulative = candidate
        critical = k + 1
    return critical, cumulative if critical >= 0 else 0.0


def plan_sample_size(
    assumed_harm_rate: float,
    *,
    max_tasks: int = MAX_TASKS,
) -> dict[str, float | int]:
    """Find the smallest n with target power for an exact lower-tail test."""
    if not 0 <= assumed_harm_rate < MARGIN:
        raise ValueError(f"Require 0 <= assumed_harm_rate < the fixed margin {MARGIN}")
    if not 1 <= max_tasks <= MAX_TASKS:
        raise ValueError(f"max_tasks must be between 1 and {MAX_TASKS}")

    for n in range(1, max_tasks + 1):
        critical, null_probability = critical_harm_count(n)
        power = _lower_tail(n, assumed_harm_rate, critical)
        if power >= TARGET_POWER:
            return {
                "tasks": n,
                "critical_harmful_discordances": critical,
                "type_i_probability": null_probability,
                "power": power,
                "assumed_harm_rate": assumed_harm_rate,
                "margin": MARGIN,
                "alpha": ALPHA,
                "target_power": TARGET_POWER,
            }
    raise ValueError(f"Target power not reached by {max_tasks} tasks")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harm-rates", type=float, nargs="+", default=[0.0, 0.005, 0.01, 0.015],
        help="Assumed full-pass/Sift-fail task rates for planning sensitivity",
    )
    parser.add_argument("--max-tasks", type=int, default=10_000)
    args = parser.parse_args()
    results = [
        plan_sample_size(
            rate, max_tasks=args.max_tasks,
        )
        for rate in args.harm_rates
    ]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
