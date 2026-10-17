"""Single source of truth for the exploratory LongBench v3 expansion gate."""

from __future__ import annotations

from typing import Any


def expansion_gate(
    *,
    complete_pair_receipts: bool,
    no_candidate_fallbacks: bool,
    no_anomalies: bool,
    no_invalid_answers: bool,
    candidate_only_majorities: int,
    candidate_exact_correct: int,
    default_exact_correct: int,
) -> dict[str, Any]:
    """Evaluate frozen v3 criteria and return explicit criteria plus decision."""
    criteria = {
        "all_36_rows_receipt_usage_route_target_valid": complete_pair_receipts is True,
        "no_relation_matrix_candidate_fallback_occurred": no_candidate_fallbacks is True,
        "no_route_usage_cost_target_anomalies": no_anomalies is True,
        "no_invalid_answers": no_invalid_answers is True,
        "at_least_one_candidate_only_majority_vs_concurrent_default": (
            candidate_only_majorities >= 1
        ),
        "strictly_more_exact_choice_correct_than_default": (
            candidate_exact_correct > default_exact_correct
        ),
    }
    return {"decision": "PASS" if all(criteria.values()) else "FAIL", "criteria": criteria}
