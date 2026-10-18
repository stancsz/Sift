from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from benchmarks import dispatch_longbench_v2_minimax_fullsuite as runner


def _responses(*, tag="minimax/fp8", prompt_rate="0.0000003",
               output_rate="0.0000012", max_prompt=524_288,
               max_completion=512_000, key_data=None):
    endpoint = {
        "model_id": runner.MODEL,
        "provider_name": "Minimax",
        "tag": tag,
        "max_prompt_tokens": max_prompt,
        "max_completion_tokens": max_completion,
        "pricing": {"prompt": prompt_rate, "completion": output_rate},
    }
    return [
        Mock(status_code=200, json=lambda: {"data": {"endpoints": [endpoint]}}),
        Mock(status_code=200, json=lambda: {"data": {"total_credits": 10}}),
        Mock(status_code=200, json=lambda: {"data": key_data or {
            "is_management_key": False, "include_byok_in_limit": False,
        }}),
    ]


def _call(*, local_prompt_tokens=100, **changes):
    manifest = {"provider_route_assumption": {
        "requested_model": runner.MODEL, "provider_slug": "minimax",
        "fallbacks_allowed": False,
    }, "protocol": {"max_output_tokens": 16}}
    jobs = [{"local_prompt_tokens": local_prompt_tokens}]
    options = {
        "no_unsettled_attested": True,
        "provider_headroom_attested": True,
        "provider_balance_unverified_authorized": False,
    }
    options.update(changes)
    return runner.live_account_route_preflight(
        "test-key", manifest, jobs, 1,
        **options,
    )


def test_live_preflight_records_route_pricing_and_byok_diagnostics():
    responses = _responses()
    with patch("requests.get", side_effect=responses) as get:
        result = _call()
    assert result["route_tag"] == "minimax/fp8"
    assert result["input_usd_per_million"] == pytest.approx(0.3)
    assert result["openrouter_credits_response"].startswith("ok; diagnostics only")
    assert result["selected_prefix_reserve_usd"] < 1
    assert get.call_count == 3


def test_live_preflight_requires_unsettled_request_reconciliation_before_network():
    with patch("requests.get") as get, pytest.raises(runner.DispatchError, match="reconcile"):
        _call(no_unsettled_attested=False)
    get.assert_not_called()


def test_live_preflight_rejects_changed_route_and_insufficient_live_rate_cap():
    with patch("requests.get", side_effect=_responses(tag="minimax/int4")) as get, \
            patch("requests.post") as post, pytest.raises(
            runner.DispatchError, match="missing, ambiguous"):
        _call()
    assert get.call_count == 3
    post.assert_not_called()
    with patch("requests.get", side_effect=_responses(prompt_rate="1.0")), pytest.raises(
            runner.DispatchError, match="live-route selected-prefix reserve"):
        _call()


def test_live_preflight_requires_upstream_headroom_attestation_or_explicit_unverified_authorization():
    with patch("requests.get") as get, pytest.raises(runner.DispatchError, match="billing headroom"):
        _call(provider_headroom_attested=False)
    get.assert_not_called()
    responses = _responses()
    with patch("requests.get", side_effect=responses):
        result = _call(provider_headroom_attested=False,
                       provider_balance_unverified_authorized=True)
    assert result["provider_balance_unverified_authorized"] is True


def test_live_preflight_rejects_ambiguous_minimax_route():
    responses = _responses()
    endpoint = responses[0].json()["data"]["endpoints"][0]
    responses[0].json = lambda: {"data": {"endpoints": [endpoint, dict(endpoint, tag="minimax/int4")]}}
    with patch("requests.get", side_effect=responses), pytest.raises(
            runner.DispatchError, match="ambiguous"):
        _call()


@pytest.mark.parametrize("key_data", [
    {"include_byok_in_limit": False},
    {"is_management_key": True, "include_byok_in_limit": False},
    {"is_management_key": False, "include_byok_in_limit": True},
])
def test_live_preflight_rejects_key_metadata_drift(key_data):
    with patch("requests.get", side_effect=_responses(key_data=key_data)), pytest.raises(
            runner.DispatchError, match="key|BYOK"):
        _call()


@pytest.mark.parametrize("prompt_rate,max_prompt,max_completion", [
    ("nan", 524_288, 512_000),
    ("0.0000003", None, 512_000),
    ("0.0000003", 524_288, 8),
])
def test_live_preflight_rejects_invalid_prices_or_limits(prompt_rate, max_prompt, max_completion):
    with patch("requests.get", side_effect=_responses(
            prompt_rate=prompt_rate, max_prompt=max_prompt,
            max_completion=max_completion)), pytest.raises(runner.DispatchError):
        _call()


def test_live_preflight_rejects_boolean_pricing_values():
    with patch("requests.get", side_effect=_responses(output_rate=True)), pytest.raises(
            runner.DispatchError, match="pricing is malformed"):
        _call()


def test_live_preflight_rejects_prompt_over_live_limit():
    with patch("requests.get", side_effect=_responses(max_prompt=99)), pytest.raises(
            runner.DispatchError, match="prompt limit"):
        _call(local_prompt_tokens=100)
