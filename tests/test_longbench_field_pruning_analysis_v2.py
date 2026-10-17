import json

import pytest

from benchmarks.analyze_longbench_v2_minimax_field_pruning_pilot_v2 import parse_raw_sse


def _event(content=None, finish_reason=None, usage=None):
    choice = {"index": 0, "delta": {}}
    if content is not None:
        choice["delta"]["content"] = content
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    result = {"choices": [choice]}
    if usage is not None:
        result["usage"] = usage
    return json.dumps(result)


def test_accepts_duplicate_identical_terminal_stop_from_usage_chunk():
    events = [
        _event('{"answer":"B"}'),
        _event(content="", finish_reason="stop"),
        _event(content="", finish_reason="stop", usage={"prompt_tokens": 7}),
        "[DONE]",
    ]
    assert parse_raw_sse(events) == "B"


def test_accepts_one_terminal_stop():
    assert parse_raw_sse([
        _event('{"answer":"C"}'), _event(content="", finish_reason="stop"), "[DONE]"
    ]) == "C"


@pytest.mark.parametrize("events", [
    [_event('{"answer":"A"}'), "[DONE]"],
    [_event('{"answer":"A"}'), _event(content="", finish_reason="length"), "[DONE]"],
    [_event('{"answer":"A"}'), _event(content="", finish_reason="stop"),
     _event(content="extra"), "[DONE]"],
    [_event('{"answer":"A"}'), _event(content="", finish_reason="stop"),
     json.dumps({"choices":[{"index":0,"delta":{"content":"","role":"assistant"},"finish_reason":"stop","native_finish_reason":"length"}]}), "[DONE]"],
    [_event('{"answer":"A"}'), _event(content="", finish_reason="stop"),
     json.dumps({"choices":[],"usage":{"prompt_tokens":1}}), "[DONE]"],
    [_event('{"answer":"A"}'), _event(content="", finish_reason="stop"), "[DONE]",
     _event('{"answer":"B"}')],
    [_event('{"answer":"A"}'), _event(content="", finish_reason="stop"), "not-json", "[DONE]"],
])
def test_rejects_missing_conflicting_or_nonterminal_streams(events):
    assert parse_raw_sse(events) is None


def test_rejects_non_a_to_d_or_extra_json_keys():
    for answer in ['{"answer":"E"}', '{"answer":"A","reason":"x"}', 'A']:
        assert parse_raw_sse([
            _event(answer), _event(content="", finish_reason="stop"), "[DONE]"
        ]) is None
