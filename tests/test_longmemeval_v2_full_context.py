"""Synthetic-only Full renderer invariants; no inference or token-fit claim."""

from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from benchmarks.longmemeval_v2_full_context import FullContextMemory, register_with_longmemeval
from benchmarks import longmemeval_v2_sift_adapter as sift_adapter


def trajectory(identifier, texts, image="state.png"):
    return {"id": identifier, "goal": "Generated goal", "states": [
        {"url": "https://fixture.invalid/page", "action": "read", "thought": "generated note",
         "accessibility_tree": text, "screenshot": image} for text in texts
    ]}


def memory_with_image(tmp_path):
    (tmp_path / "state.png").write_bytes(b"synthetic renderer-only image placeholder")
    return FullContextMemory({"trajectories_root_dir": str(tmp_path)})


def test_all_states_use_exact_sift_input_text_and_image_order(tmp_path, monkeypatch):
    full = memory_with_image(tmp_path)
    (tmp_path / "second.png").write_bytes(b"second generated image")
    reference = sift_adapter.SiftMemory({"trajectories_root_dir": str(tmp_path)})
    inputs = [trajectory("first", ["first state", "second state"]),
              trajectory("second", ["third state"], "second.png")]
    monkeypatch.setattr(sift_adapter, "compact_messages",
                        lambda *_args, **_kwargs: pytest.fail("Full must never compact"))
    for item in inputs:
        full.insert(item)
        reference.insert(item)

    context = full.query("ACTIVE_QUERY_MUST_NOT_BE_STORED", query_image="QUESTION_IMAGE")
    assert context == [
        {"type": "text", "value": "\n\n".join(row["content"] for row in reference.messages)},
        *({"type": "image", "value": path} for path in reference.screenshots_by_message.values()),
    ]
    assert [item["type"] for item in context] == ["text", "image", "image", "image"]
    assert "ACTIVE_QUERY_MUST_NOT_BE_STORED" not in context[0]["value"]
    assert all(item["value"] != "QUESTION_IMAGE" for item in context)


def test_repeated_ids_shared_images_and_large_text_are_never_deduplicated_or_shortened(tmp_path):
    memory = memory_with_image(tmp_path)
    text = "GENERATED_FULL_STATE " * 10_000
    item = trajectory("same-id", [text, "tail marker"])
    memory.insert(item)
    memory.insert(item)
    context = memory.query("different question")
    expected = sift_adapter._trajectory_states(item, trajectories_root_dir=tmp_path)
    assert context[0]["value"] == "\n\n".join(state[0] for state in [*expected, *expected])
    assert len(context) == 5
    assert [row["value"] for row in context[1:]] == [str((tmp_path / "state.png").resolve())] * 4


def test_legacy_fallback_matches_accepted_adapter_normalization(tmp_path):
    memory = memory_with_image(tmp_path)
    item = {"id": "legacy", "states": [], "metadata": {"original_goal": ["generated", "goal"]},
            "content": [{"url": "https://fixture.invalid/legacy", "action": None, "thoughts": "note",
                         "observation": {"text": "legacy text", "screenshot": "state.png"}}]}
    memory.insert(item)
    normalized = sift_adapter._trajectory_states(item, trajectories_root_dir=tmp_path)
    assert memory.query("question") == [{"type": "text", "value": normalized[0][0]},
                                        {"type": "image", "value": normalized[0][1]}]


@pytest.mark.parametrize("change", [{"screenshot": None}, {"screenshot": "missing.png"},
                                    {"accessibility_tree": None}, {"url": ""}, {"action": []}])
def test_invalid_later_state_rejects_entire_insertion_without_losing_prior_history(tmp_path, change):
    memory = memory_with_image(tmp_path)
    memory.insert(trajectory("previous", ["retained history"]))
    before = memory.query("question")
    broken = trajectory("rejected", ["must not partially insert", "invalid final state"])
    broken["states"][1].update(change)
    with pytest.raises(ValueError):
        memory.insert(broken)
    assert memory.query("question") == before


def test_input_output_and_config_mutation_cannot_rewrite_retained_history(tmp_path):
    memory = memory_with_image(tmp_path)
    item = trajectory("original", ["unchanged text"])
    memory.insert(item)
    expected = deepcopy(memory.query("question"))
    item["states"][0]["accessibility_tree"] = "mutated input"
    item["states"].clear()
    output = memory.query("question")
    output[0]["value"] = "mutated output"
    output.pop()
    config = memory.memory_config
    config["memory_params"]["trajectories_root_dir"] = "mutated config"
    assert memory.query("new question", query_image="not retained") == expected
    assert memory.memory_config["memory_params"]["trajectories_root_dir"] == str(tmp_path)


def test_lifecycle_and_empty_memory_do_not_insert_query_content(tmp_path):
    memory = FullContextMemory({})
    memory.configure_runtime(workspace_root=tmp_path)
    memory.set_query_context(query_invocation_id="generated-invocation")
    context = memory.query("active question", query_image="active-image.png")
    assert context == []
    assert memory.post_query_hook(query="active question", query_image="active-image.png",
                                  memory_context=context) is None
    assert memory.clear_query_context() is None
    assert memory.query("another question") == []
    for invalid in ("", "  ", None):
        with pytest.raises(ValueError):
            memory.query(invalid)
        with pytest.raises(ValueError):
            memory.set_query_context(query_invocation_id=invalid)


@pytest.mark.parametrize("params", [{"target_tokens": 1}, {"raw_limit": 1},
                                   {"trajectories_root_dir": " "}, {"trajectories_root_dir": False}])
def test_full_rejects_unsupported_limits_and_invalid_roots(params):
    with pytest.raises(ValueError):
        FullContextMemory(params)


def test_registration_is_explicit_and_uses_the_same_upstream_registry_contract(monkeypatch):
    registered = []
    module = ModuleType("memory_modules.memory")
    module.register_memory = lambda cls: registered.append(cls) or cls
    package = ModuleType("memory_modules")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "memory_modules", package)
    monkeypatch.setitem(sys.modules, "memory_modules.memory", module)
    assert registered == []
    register_with_longmemeval()
    assert registered == [FullContextMemory]


def test_pinned_upstream_message_helper_adds_active_question_and_image_once(tmp_path):
    # Optional local source cache only; never download upstream to run tests.
    from benchmarks.longmemeval_v2_synthetic_harness_smoke import _load_harness, _tiny_png

    source = Path(__file__).resolve().parents[1] / "tmp/longmemeval-synthetic-main/upstream/evaluation/harness.py"
    if not source.is_file():
        pytest.skip("optional hash-pinned upstream source cache is absent")
    for name in ("state.png", "question.png"):
        (tmp_path / name).write_bytes(_tiny_png())
    full = FullContextMemory({"trajectories_root_dir": str(tmp_path)})
    full.insert(trajectory("generated", ["state one", "state two"]))
    question_image = str(tmp_path / "question.png")
    context = full.query("UNIQUE_ACTIVE_QUESTION", query_image=question_image)
    # Reuse the accepted loader's stubs for unused registry/CLI/scoring imports;
    # only the actual pinned build_messages/to_data_url functions execute here.
    # Restore every import hook on success or failure.
    with patch.dict(sys.modules):
        harness = _load_harness(source)
        messages, log_messages = harness.build_messages("generated system", "UNIQUE_ACTIVE_QUESTION",
                                                         question_image, context)
    logged = log_messages[1]["content"]
    assert [part["image_path"] for part in logged if part["type"] == "image_path"] == [
        str((tmp_path / "state.png").resolve()), str((tmp_path / "state.png").resolve()), question_image]
    assert sum(part.get("text", "").count("UNIQUE_ACTIVE_QUESTION") for part in logged) == 1
    assert sum(part["type"] == "image_url" for part in messages[1]["content"]) == 3
    assert full.query("UNIQUE_ACTIVE_QUESTION", query_image=question_image) == context
