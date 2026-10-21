from copy import deepcopy

import pytest

from benchmarks.longmemeval_v2_minimax_request_policy import (
    MODEL,
    MiniMaxRequestPolicyError,
    pin_minimax_reader_request,
    wrap_minimax_reader_request_builder,
)


def _request():
    return {"model": MODEL, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Synthetic question only."},
    ]}], "max_tokens": 64, "temperature": 0.0, "top_p": 1.0,
        "timeout": 37.0, "extra_body": {"usage": {"include": True}}}


def test_pin_preserves_supported_fields_and_does_not_mutate_nested_inputs():
    request = _request()
    original = deepcopy(request)
    result = pin_minimax_reader_request(request)
    assert result["extra_body"]["provider"] == {
        "only": ["minimax"], "allow_fallbacks": False, "require_parameters": True,
    }
    assert result["extra_body"]["usage"] == {"include": True}
    assert {k: v for k, v in result.items() if k != "extra_body"} == {
        k: v for k, v in original.items() if k != "extra_body"
    }
    result["messages"][0]["content"][0]["text"] = "changed result"
    result["extra_body"]["usage"]["include"] = False
    result["extra_body"]["provider"]["only"].append("other")
    assert request == original


def test_compatible_pin_is_idempotent_and_independent():
    request = _request()
    request["extra_body"]["provider"] = {"only": ["minimax"], "allow_fallbacks": False}
    first = pin_minimax_reader_request(request)
    second = pin_minimax_reader_request(first)
    assert second == first
    assert second is not first
    assert second["messages"] is not first["messages"]


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "64", None])
def test_invalid_max_tokens_are_rejected_without_echoing_message(value):
    request = _request()
    request["max_tokens"] = value
    with pytest.raises(MiniMaxRequestPolicyError) as error:
        pin_minimax_reader_request(request)
    assert "Synthetic question" not in str(error.value)


@pytest.mark.parametrize("field,value", [
    ("model", "openrouter/auto"), ("model", [MODEL]),
    ("models", [MODEL, "other"]), ("route", "fallback"),
    ("provider", {"only": ["other"]}), ("fallbacks", ["other"]),
    ("stream", True), ("stream", 0), ("stream_options", {"include_usage": True}),
    ("max_completion_tokens", 64),
])
def test_conflicting_top_level_settings_are_rejected(field, value):
    request = _request()
    request[field] = value
    with pytest.raises(MiniMaxRequestPolicyError):
        pin_minimax_reader_request(request)


@pytest.mark.parametrize("provider", [
    {"only": ["other"]}, {"only": ["minimax", "other"]},
    {"allow_fallbacks": True}, {"allow_fallbacks": 0},
    {"require_parameters": False}, {"require_parameters": 1},
    {"order": ["minimax"]}, None,
])
def test_conflicting_provider_pin_is_rejected(provider):
    request = _request()
    request["extra_body"]["provider"] = provider
    with pytest.raises(MiniMaxRequestPolicyError):
        pin_minimax_reader_request(request)


@pytest.mark.parametrize("key,value", [
    ("model", MODEL), ("messages", []), ("stream", False),
    ("max_tokens", 64), ("max_completion_tokens", 64),
    ("temperature", 0.0), ("seed", 1), ("models", [MODEL]),
    ("route", "fallback"), ("extra_body", {}), ("timeout", 37),
])
def test_extra_body_cannot_shadow_controls_even_when_identical_or_absent(key, value):
    request = _request()
    request["extra_body"][key] = value
    with pytest.raises(MiniMaxRequestPolicyError):
        pin_minimax_reader_request(request)


def test_factory_applies_policy_to_the_actual_builder_result():
    calls = []
    request = _request()

    def original_builder(args, messages):
        calls.append((args, messages))
        return request

    builder = wrap_minimax_reader_request_builder(original_builder)
    messages = request["messages"]
    result = builder("synthetic-args", messages)
    assert calls == [("synthetic-args", messages)]
    assert result["extra_body"]["provider"]["only"] == ["minimax"]
    assert "provider" not in request["extra_body"]
