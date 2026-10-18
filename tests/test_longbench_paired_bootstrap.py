import json

from benchmarks.bootstrap_longbench_v2_pairs import analyze, load_rows


def _aggregate():
    rows = [
        {"full": {"correct": True, "prompt_tokens": 100}, "sift": {"correct": True, "prompt_tokens": 50}},
        {"full": {"correct": True, "prompt_tokens": 100}, "sift": {"correct": False, "prompt_tokens": 50}},
        {"full": {"correct": False, "prompt_tokens": 100}, "sift": {"correct": True, "prompt_tokens": 50}},
        {"full": {"correct": False, "prompt_tokens": 100}, "sift": {"correct": False, "prompt_tokens": 50}},
    ]
    return {
        "status": "incomplete_checkpoint",
        "study": "synthetic test aggregate",
        "paired_summary": {
            "full": {"correct": 2, "accuracy": 0.5, "prompt_tokens": 400},
            "sift": {"correct": 2, "accuracy": 0.5, "prompt_tokens": 200},
        },
        "paired_correctness_cells": {
            "both_correct": 1,
            "full_only_correct": 1,
            "sift_only_correct": 1,
            "neither_correct": 1,
        },
        "paired_rows": rows,
    }


def test_bootstrap_is_paired_deterministic_and_aggregate_only(tmp_path):
    source = tmp_path / "aggregate.json"
    source.write_text(json.dumps(_aggregate()), encoding="utf-8")
    data, rows, digest = load_rows(source)

    result = analyze(data, rows, digest, replicates=200, seed=7)

    assert result["accuracy_delta_sift_minus_full_percentage_points"] == 0
    assert result["prompt_token_reduction_percent"] == 50
    assert result["prompt_token_reduction_95_percentile_interval_percent"] == [50, 50]
    assert "paired_rows" not in result
    assert result == analyze(data, rows, digest, replicates=200, seed=7)


def test_bootstrap_rejects_aggregate_mismatch(tmp_path):
    aggregate = _aggregate()
    aggregate["paired_correctness_cells"]["full_only_correct"] = 2
    source = tmp_path / "bad-aggregate.json"
    source.write_text(json.dumps(aggregate), encoding="utf-8")

    try:
        load_rows(source)
    except ValueError as exc:
        assert "correctness cells" in str(exc)
    else:
        raise AssertionError("Expected mismatched aggregate to fail validation")
