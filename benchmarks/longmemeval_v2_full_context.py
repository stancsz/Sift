"""All-state Full reference renderer for the prospective local comparison.

Uses the Sift adapter's exact trajectory normalization and image resolution.
No selection, summarization, token counting or truncation occurs here. Every
inserted state contributes its text and image, including repeated IDs/paths.
The upstream harness owns adding the active question and its image once.
This renderer does not establish token fit, data rights or dispatch readiness.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.longmemeval_v2_sift_adapter import _trajectory_states


class FullContextMemory:
    """Duck-typed sequential memory lifecycle; no save/load or runtime services."""

    memory_type = "sift_full_context_reference"

    def __init__(self, memory_params: dict[str, object]) -> None:
        if not isinstance(memory_params, dict) or set(memory_params) - {"trajectories_root_dir"}:
            raise ValueError("Full supports only trajectories_root_dir; no token or selection limits")
        self.memory_params = dict(memory_params)
        root = self.memory_params.get("trajectories_root_dir")
        if root is not None and (not isinstance(root, str) or not root.strip()):
            raise ValueError("trajectories_root_dir must be a non-empty path when provided")
        self.trajectories_root_dir = Path(root).resolve() if isinstance(root, str) else None
        self._states: list[tuple[str, str]] = []

    def insert(self, trajectory: dict[str, object]) -> None:
        if not isinstance(trajectory, dict):
            raise ValueError("trajectory must be an object")
        # The shared helper validates the entire trajectory before returning;
        # a malformed later state cannot partially insert earlier states.
        inserted = _trajectory_states(trajectory, trajectories_root_dir=self.trajectories_root_dir)
        self._states.extend(inserted)

    @property
    def memory_config(self) -> dict[str, object]:
        return {"memory_type": self.memory_type, "memory_params": dict(self.memory_params)}

    def configure_runtime(self, **kwargs: object) -> None:
        """Accept the upstream lifecycle's unused workspace/runtime arguments."""
        _ = kwargs

    def set_query_context(self, *, query_invocation_id: str) -> None:
        if not isinstance(query_invocation_id, str) or not query_invocation_id.strip():
            raise ValueError("query_invocation_id must be non-empty text")

    def clear_query_context(self) -> None:
        return None

    def post_query_hook(self, *, query: str, query_image: str | None,
                        memory_context: list[dict[str, str]]) -> None:
        _ = (query, query_image, memory_context)

    def query(self, query: str, query_image: str | None = None) -> list[dict[str, str]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be non-empty text")
        _ = query_image  # Appended by the common harness, never retained here.
        if not self._states:
            return []
        return [
            {"type": "text", "value": "\n\n".join(text for text, _image in self._states)},
            *({"type": "image", "value": image} for _text, image in self._states),
        ]


def register_with_longmemeval() -> None:
    """Explicit optional registration only; importing this module registers nothing."""
    from memory_modules.memory import register_memory

    register_memory(FullContextMemory)
