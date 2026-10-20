from __future__ import annotations

import sys
from types import ModuleType
from pathlib import Path

import pytest

from benchmarks import longmemeval_v2_sift_adapter as adapter
from sift.core import CompactionError


def _trajectory(trajectory_id: str, text: str, screenshot: str | None) -> dict[str, object]:
    return {
        "id": trajectory_id,
        "goal": "Inspect a synthetic settings page",
        "states": [{
            "url": "https://fixture.invalid/settings",
            "action": "open settings",
            "thought": None,
            "accessibility_tree": text,
            "screenshot": screenshot,
        }],
    }


def test_official_state_shape_preserves_text_and_associated_screenshot(tmp_path: Path) -> None:
    screenshot = tmp_path / "fixture.png"
    screenshot.write_bytes(b"synthetic image placeholder")
    memory = adapter.SiftMemory({
        "target_tokens": 20_000,
        "trajectories_root_dir": str(tmp_path),
    })
    memory.insert(_trajectory("fixture-1", "The backup delay is 25 seconds.", "fixture.png"))

    context = memory.query(
        "What is the backup delay?",
        query_image=str(tmp_path / "question-image-is-appended-by-harness.png"),
    )

    assert len(context) == 2
    assert context[0]["type"] == "text"
    assert "25 seconds" in context[0]["value"]
    assert context[1] == {"type": "image", "value": str(screenshot.resolve())}


def test_legacy_content_shape_maps_observation_text_and_image(tmp_path: Path) -> None:
    screenshot = tmp_path / "legacy.png"
    screenshot.write_bytes(b"synthetic image placeholder")
    memory = adapter.SiftMemory({"trajectories_root_dir": str(tmp_path)})
    memory.insert({
        "id": "legacy-1",
        "metadata": {"original_goal": ["Read", "the synthetic page"]},
        "content": [{
            "url": "https://fixture.invalid/legacy",
            "action": "read the page",
            "thoughts": "fixture note",
            "observation": {"text": "The retry window is 14 seconds.", "screenshot": "legacy.png"},
        }],
    })

    context = memory.query("What is the retry window?")

    assert "14 seconds" in context[0]["value"]
    assert context[1]["value"] == str(screenshot.resolve())


def test_empty_states_falls_back_to_legacy_content(tmp_path: Path) -> None:
    screenshot = tmp_path / "legacy-fallback.png"
    screenshot.write_bytes(b"synthetic image placeholder")
    memory = adapter.SiftMemory({"trajectories_root_dir": str(tmp_path)})
    memory.insert({
        "id": "legacy-fallback",
        "states": [],
        "content": [{
            "url": "https://fixture.invalid/legacy-fallback",
            "action": "read the page",
            "observation": {"text": "The color theme is amber.", "screenshot": "legacy-fallback.png"},
        }],
    })

    context = memory.query("What is the color theme?")

    assert "amber" in context[0]["value"]
    assert context[1]["value"] == str(screenshot.resolve())


def test_registration_hook_registers_adapter_with_official_style_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    memory_module = ModuleType("memory_modules.memory")
    registered: list[type[object]] = []
    memory_module.register_memory = lambda memory_cls: registered.append(memory_cls) or memory_cls
    package_module = ModuleType("memory_modules")
    package_module.__path__ = []
    monkeypatch.setitem(sys.modules, "memory_modules", package_module)
    monkeypatch.setitem(sys.modules, "memory_modules.memory", memory_module)

    adapter.register_with_longmemeval()

    assert registered == [adapter.SiftMemory]


def test_missing_or_unresolvable_screenshot_fails_closed() -> None:
    memory = adapter.SiftMemory({})
    with pytest.raises(ValueError, match="require trajectories_root_dir"):
        memory.insert(_trajectory("fixture-1", "text", "relative.png"))

    missing = adapter.SiftMemory({})
    with pytest.raises(ValueError, match="non-empty path"):
        missing.insert(_trajectory("fixture-1", "text", None))

    rooted = adapter.SiftMemory({"trajectories_root_dir": "."})
    with pytest.raises(ValueError, match="does not exist"):
        rooted.insert(_trajectory("fixture-1", "text", "missing-fixture.png"))


@pytest.mark.parametrize(
    ("params", "expected_code"),
    [
        ({"target_tokens": 10, "raw_limit": 12}, "raw_limit"),
        ({"max_input_characters": 32}, "input_size_limit"),
        ({"max_input_nodes": 1}, "input_size_limit"),
    ],
)
def test_documented_sift_bounds_reject_oversized_history(
    tmp_path: Path, params: dict[str, int], expected_code: str,
) -> None:
    screenshot = tmp_path / "fixture.png"
    screenshot.write_bytes(b"synthetic image placeholder")
    memory = adapter.SiftMemory({**params, "trajectories_root_dir": str(tmp_path)})
    memory.insert(_trajectory("fixture-1", "An old synthetic fact.", "fixture.png"))

    with pytest.raises(CompactionError) as error:
        memory.query("What was the fact?")
    assert error.value.code == expected_code


def test_compacted_summary_keeps_image_links_for_selected_source_messages(tmp_path: Path) -> None:
    selected_image = tmp_path / "selected.png"
    omitted_image = tmp_path / "omitted.png"
    selected_image.write_bytes(b"selected synthetic image")
    omitted_image.write_bytes(b"omitted synthetic image")
    memory = adapter.SiftMemory({
        "target_tokens": 400,
        "raw_limit": 10_000,
        "trajectories_root_dir": str(tmp_path),
    })
    memory.insert(_trajectory("fixture-selected", "The backup delay is 25 seconds. " * 8, "selected.png"))
    memory.insert({
        **_trajectory("fixture-omitted", "zebra quartz meadow. " * 30, "omitted.png"),
        "goal": "Review the package inventory",
    })

    context = memory.query("What is the backup delay?")

    assert "Earlier conversation, lossily excerpted" in context[0]["value"]
    assert "25 seconds" in context[0]["value"]
    image_values = [item["value"] for item in context if item["type"] == "image"]
    assert str(selected_image.resolve()) in image_values
    source_indices = {
        int(index) for index in adapter._SUMMARY_SOURCE.findall(context[0]["value"])
    }
    expected_images = [
        memory.screenshots_by_message[index]
        for index in sorted(source_indices)
        if index in memory.screenshots_by_message
    ]
    assert image_values == expected_images
