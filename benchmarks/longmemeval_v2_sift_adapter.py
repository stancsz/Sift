"""Synthetic-only bridge from the LongMemEval-V2 memory contract to Sift.

This prototype intentionally uses a UTF-8 size estimate. It exercises the
adapter contract; it is not suitable for a LongMemEval score or a leaderboard
submission, which needs a reader-compatible token counter and a frozen run
protocol.
"""

from __future__ import annotations

from math import ceil
from pathlib import Path
import re
from typing import Any

from sift.core import (
    DEFAULT_MAX_INPUT_CHARACTERS,
    DEFAULT_MAX_INPUT_NODES,
    CompactionError,
    compact_messages,
)


_SUMMARY_SOURCE = re.compile(r"\[message (\d+) tool\]")
_STATE_NAME = re.compile(r"^sift_state_(\d+)$")


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Return a UTF-8 request-size estimate, not model tokens."""
    import json

    encoded = json.dumps(
        {"model": "longmemeval-synthetic", "messages": messages},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return ceil(len(encoded) / 2)


def _resolve_screenshot(value: Any, root: Path | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("trajectory screenshot must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        if root is None:
            raise ValueError("relative screenshot paths require trajectories_root_dir")
        candidates = (root / path, root / "screenshots" / path)
        path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"trajectory screenshot does not exist: {path}")
    return str(path)


def _trajectory_states(
    trajectory: dict[str, Any],
    *,
    trajectories_root_dir: Path | None,
) -> list[tuple[str, str]]:
    trajectory_id = trajectory.get("id")
    if not isinstance(trajectory_id, str) or not trajectory_id.strip():
        raise ValueError("trajectory id must be a non-empty string")
    goal = trajectory.get("goal")
    if not isinstance(goal, str):
        metadata = trajectory.get("metadata")
        raw_goal = metadata.get("original_goal") if isinstance(metadata, dict) else None
        if isinstance(raw_goal, str):
            goal = raw_goal
        elif isinstance(raw_goal, list):
            goal = " ".join(part for part in raw_goal if isinstance(part, str))
        else:
            goal = ""

    states = trajectory.get("states")
    legacy = False
    if not isinstance(states, list) or not states:
        states = trajectory.get("content")
        legacy = True
    if not isinstance(states, list) or not states:
        raise ValueError(f"trajectory {trajectory_id!r} must contain non-empty states/content")

    output: list[tuple[str, str]] = []
    for index, state in enumerate(states):
        if not isinstance(state, dict):
            raise ValueError(f"trajectory {trajectory_id!r} state {index} must be an object")
        if legacy:
            observation = state.get("observation")
            if not isinstance(observation, dict):
                raise ValueError(f"trajectory {trajectory_id!r} state {index} needs an observation object")
            text = observation.get("text")
            screenshot = observation.get("screenshot")
            thoughts = state.get("thoughts")
        else:
            text = state.get("accessibility_tree", state.get("text"))
            screenshot = state.get("screenshot")
            thoughts = state.get("thought", state.get("thoughts"))
        url = state.get("url")
        action = state.get("action")
        if not isinstance(text, str):
            raise ValueError(f"trajectory {trajectory_id!r} state {index} needs text/accessibility_tree")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"trajectory {trajectory_id!r} state {index} needs a URL")
        if action is not None and not isinstance(action, str):
            raise ValueError(f"trajectory {trajectory_id!r} state {index} action must be text or null")
        if thoughts is not None and not isinstance(thoughts, str):
            raise ValueError(f"trajectory {trajectory_id!r} state {index} thoughts must be text or null")
        image_path = _resolve_screenshot(screenshot, trajectories_root_dir)
        content = (
            f"Trajectory goal: {goal}\n"
            f"Trajectory: {trajectory_id}\n"
            f"State: {index}\n"
            f"Page URL: {url}\n"
            f"Action: {action or ''}\n"
            f"Notes: {thoughts or ''}\n"
            f"Accessibility text:\n{text}"
        )
        output.append((content, image_path))
    return output


class SiftMemory:
    """Duck-typed LongMemEval memory backend for offline adapter checks."""

    memory_type = "sift_synthetic_adapter"

    def __init__(self, memory_params: dict[str, object]) -> None:
        self.memory_params = dict(memory_params)
        self.target_tokens = self._positive_int("target_tokens", 32_768)
        self.raw_limit = self._positive_int("raw_limit", 1_000_000)
        self.max_input_characters = self._positive_int(
            "max_input_characters", DEFAULT_MAX_INPUT_CHARACTERS
        )
        self.max_input_nodes = self._positive_int("max_input_nodes", DEFAULT_MAX_INPUT_NODES)
        root = self.memory_params.get("trajectories_root_dir")
        if root is not None and (not isinstance(root, str) or not root.strip()):
            raise ValueError("trajectories_root_dir must be a non-empty path when provided")
        self.trajectories_root_dir = Path(root).resolve() if isinstance(root, str) else None
        self.messages: list[dict[str, Any]] = []
        self.screenshots_by_message: dict[int, str] = {}

    def _positive_int(self, key: str, default: int) -> int:
        value = self.memory_params.get(key, default)
        if type(value) is not int or value <= 0:
            raise ValueError(f"{key} must be a positive integer")
        return value

    def insert(self, trajectory: dict[str, object]) -> None:
        if not isinstance(trajectory, dict):
            raise ValueError("trajectory must be an object")
        inserted = _trajectory_states(
            trajectory,
            trajectories_root_dir=self.trajectories_root_dir,
        )
        first_index = len(self.messages)
        for offset, (content, image_path) in enumerate(inserted):
            message_index = first_index + offset
            self.messages.append({
                "role": "tool",
                "name": f"sift_state_{message_index}",
                "content": content,
            })
            if image_path is not None:
                self.screenshots_by_message[message_index] = image_path

    @property
    def memory_config(self) -> dict[str, object]:
        return {"memory_type": self.memory_type, "memory_params": dict(self.memory_params)}

    def configure_runtime(self, **kwargs: object) -> None:
        """Match the benchmark lifecycle; this adapter has no runtime services."""
        _ = kwargs

    def set_query_context(self, *, query_invocation_id: str) -> None:
        if not isinstance(query_invocation_id, str) or not query_invocation_id.strip():
            raise ValueError("query_invocation_id must be non-empty text")

    def clear_query_context(self) -> None:
        return None

    def post_query_hook(
        self,
        *,
        query: str,
        query_image: str | None,
        memory_context: list[dict[str, str]],
    ) -> None:
        _ = (query, query_image, memory_context)

    def query(
        self,
        query: str,
        query_image: str | None = None,
    ) -> list[dict[str, str]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be non-empty text")
        # The official harness adds query_image to the reader prompt after this
        # call. Sift's text selector does not use it to rank stored states.
        _ = query_image
        result = compact_messages(
            [*self.messages, {"role": "user", "content": query}],
            _estimate_tokens,
            target=self.target_tokens,
            raw_limit=self.raw_limit,
            max_input_characters=self.max_input_characters,
            max_input_nodes=self.max_input_nodes,
        )
        if (
            not result.messages
            or result.messages[-1].get("role") != "user"
            or result.messages[-1].get("content") != query
        ):
            raise RuntimeError("Sift output did not preserve the active query as its final message")
        texts: list[str] = []
        selected_indices: set[int] = set()
        for message in result.messages[:-1]:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            texts.append(content)
            name = message.get("name")
            match = _STATE_NAME.fullmatch(name) if isinstance(name, str) else None
            if match:
                selected_indices.add(int(match.group(1)))
            selected_indices.update(int(index) for index in _SUMMARY_SOURCE.findall(content))

        context: list[dict[str, str]] = []
        combined_text = "\n\n".join(texts).strip()
        if combined_text:
            context.append({"type": "text", "value": combined_text})
        for message_index in sorted(selected_indices):
            path = self.screenshots_by_message.get(message_index)
            if path is not None:
                context.append({"type": "image", "value": path})
        return context


def register_with_longmemeval() -> None:
    """Register this backend after importing LongMemEval's memory registry."""
    from memory_modules.memory import register_memory

    register_memory(SiftMemory)
