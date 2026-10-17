from benchmarks.run_longbench_v2_minimax_relation_followup_v3 import runtime_receipt_issues


def _usage():
    return {
        "is_byok": True,
        "prompt_tokens": 100,
        "completion_tokens": 5,
        "cost": 0.0,
        "prompt_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 0},
        "cost_details": {
            "upstream_inference_cost": 0.00004,
            "upstream_inference_prompt_cost": 0.000034,
            "upstream_inference_completions_cost": 0.000006,
        },
    }


def test_complete_byok_cost_and_cache_receipt_is_accepted():
    assert runtime_receipt_issues(_usage()) == []


def test_missing_cost_components_stop_as_operational_receipt_failure():
    usage = _usage()
    del usage["cost_details"]["upstream_inference_completions_cost"]
    assert "invalid_upstream_cost_components" in runtime_receipt_issues(usage)


def test_cost_component_mismatch_stops_as_operational_receipt_failure():
    usage = _usage()
    usage["cost_details"]["upstream_inference_prompt_cost"] = 0.00003
    assert "upstream_cost_components_do_not_reconcile" in runtime_receipt_issues(usage)


def test_missing_or_impossible_cache_counts_stop_as_operational_receipt_failure():
    usage = _usage()
    del usage["prompt_tokens_details"]["cache_write_tokens"]
    assert "invalid_cache_token_details" in runtime_receipt_issues(usage)
    usage = _usage()
    usage["prompt_tokens_details"]["cached_tokens"] = 101
    assert "invalid_cache_token_details" in runtime_receipt_issues(usage)
