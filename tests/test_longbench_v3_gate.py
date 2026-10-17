from benchmarks.longbench_v3_gate import expansion_gate


def _gate(*, wins: int, candidate: int, default: int, **overrides):
    values = {
        "complete_pair_receipts": True,
        "no_candidate_fallbacks": True,
        "no_anomalies": True,
        "no_invalid_answers": True,
        "candidate_only_majorities": wins,
        "candidate_exact_correct": candidate,
        "default_exact_correct": default,
    }
    values.update(overrides)
    return expansion_gate(**values)


def test_one_candidate_only_majority_and_one_accuracy_win_passes():
    assert _gate(wins=1, candidate=10, default=9)["decision"] == "PASS"


def test_two_majorities_do_not_pass_without_strict_accuracy_improvement():
    assert _gate(wins=2, candidate=9, default=9)["decision"] == "FAIL"
    assert _gate(wins=2, candidate=8, default=9)["decision"] == "FAIL"


def test_one_majority_without_strict_accuracy_improvement_fails():
    assert _gate(wins=1, candidate=9, default=9)["decision"] == "FAIL"


def test_fallback_invalid_receipt_or_anomaly_blocks_expansion():
    assert _gate(wins=1, candidate=10, default=9,
                 no_candidate_fallbacks=False)["decision"] == "FAIL"
    assert _gate(wins=1, candidate=10, default=9,
                 no_invalid_answers=False)["decision"] == "FAIL"
    assert _gate(wins=1, candidate=10, default=9,
                 no_anomalies=False)["decision"] == "FAIL"
    assert _gate(wins=1, candidate=10, default=9,
                 complete_pair_receipts=False)["decision"] == "FAIL"
