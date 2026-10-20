"""Exercise LongMemEval's pinned prompt-building path with synthetic images only.

This is a smoke check, not an evaluation. It calls the upstream
``build_prompt_row`` from a separately checked out harness source file, while
stubbing upstream registry/scoring imports and processor token counting.
It never loads benchmark data or calls a model.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import pathlib
import struct
import sys
import tempfile
import types
import zlib

PINNED_HARNESS_GIT_BLOB = "6a7182440a2cdd3ace6286dd966f7953fc383e8e"


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _one_pixel_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x20\x40\x60"))
        + _png_chunk(b"IEND", b"")
    )


def _load_harness(path: pathlib.Path):
    source = path.read_bytes()
    actual = hashlib.sha1(
        b"blob " + str(len(source)).encode("ascii") + b"\0" + source
    ).hexdigest()
    if actual != PINNED_HARNESS_GIT_BLOB:
        raise SystemExit(
            f"Harness Git blob mismatch: expected {PINNED_HARNESS_GIT_BLOB}, got {actual}"
        )

    # Stub only imports not needed by build_prompt_row; the function under test
    # remains the source from the hash-pinned upstream harness.
    memory_package = types.ModuleType("memory_modules")
    memory_package.__path__ = []
    memory_module = types.ModuleType("memory_modules.memory")

    class Memory:
        pass

    memory_module.Memory = Memory
    memory_module.MemoryContextItem = dict
    for name in ("build_memory", "load_memory", "load_memory_config", "save_memory"):
        setattr(memory_module, name, lambda *args, **kwargs: None)
    sys.modules["memory_modules"] = memory_package
    sys.modules["memory_modules.memory"] = memory_module

    # These upstream imports are used only by the full CLI/generation paths,
    # neither of which this prompt-construction smoke invokes.
    openai_module = types.ModuleType("openai")

    class AsyncOpenAI:
        pass

    class BadRequestError(Exception):
        pass

    openai_module.AsyncOpenAI = AsyncOpenAI
    openai_module.BadRequestError = BadRequestError
    sys.modules["openai"] = openai_module
    tqdm_module = types.ModuleType("tqdm")
    tqdm_module.tqdm = lambda *args, **kwargs: None
    sys.modules["tqdm"] = tqdm_module

    evaluation_package = types.ModuleType("evaluation")
    evaluation_package.__path__ = []
    metrics_module = types.ModuleType("evaluation.qa_eval_metrics")
    for name in (
        "eval_from_spec",
        "eval_name",
        "extract_boxed_answer",
        "is_unknown",
        "score_to_bool",
    ):
        setattr(metrics_module, name, lambda *args, **kwargs: None)
    sys.modules["evaluation"] = evaluation_package
    sys.modules["evaluation.qa_eval_metrics"] = metrics_module

    spec = importlib.util.spec_from_file_location("longmemeval_harness_pinned", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load harness source: {path}")
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    return harness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("harness", type=pathlib.Path, help="path to pinned evaluation/harness.py")
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    try:
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise SystemExit("Pillow is required to decode the synthetic screenshot fixtures") from exc

    harness = _load_harness(args.harness)

    class TokenIds:
        shape = (1, 1)

    class Processor:
        def apply_chat_template(self, messages, **kwargs):
            assert kwargs == {"tokenize": False, "add_generation_prompt": False}
            assert messages and messages[0]["role"] == "user"
            return "synthetic-only token counter input"

        def __call__(self, *, text, images, return_tensors):
            assert text == "synthetic-only token counter input"
            assert images and all(image.mode == "RGB" for image in images)
            assert return_tensors == "pt"
            return {"input_ids": TokenIds()}

    harness.get_memory_context_processor = lambda: Processor()
    from benchmarks.longmemeval_v2_sift_adapter import SiftMemory

    image_bytes = _one_pixel_png()
    with tempfile.TemporaryDirectory(prefix="sift-longmemeval-smoke-") as temp_dir:
        fixture_dir = pathlib.Path(temp_dir)
        state_image = fixture_dir / "state.png"
        question_image = fixture_dir / "question.png"
        state_image.write_bytes(image_bytes)
        question_image.write_bytes(image_bytes)

        memory = SiftMemory(
            {
                "target_tokens": 20_000,
                "raw_limit": 100_000,
                "trajectories_root_dir": str(fixture_dir),
            }
        )
        memory.insert(
            {
                "id": "synthetic-trajectory",
                "goal": "Read a synthetic settings page",
                "states": [
                    {
                        "url": "https://fixture.invalid/settings",
                        "action": "open settings",
                        "thought": None,
                        "accessibility_tree": "The backup delay is 25 seconds.",
                        "screenshot": "state.png",
                    }
                ],
            }
        )
        row = harness.build_prompt_row(
            {
                "question_id": "synthetic-question",
                "query_invocation_id": "synthetic-query",
                "question_text": "What is the backup delay?",
                "question_image": str(question_image),
                "eval_name": "exact_match",
            },
            haystack_ids=["synthetic-trajectory"],
            memory=memory,
            system_prompt="Synthetic test only. Do not call a model.",
            memory_context_max_tokens=4096,
        )

    assert row["memory_context"]
    assert row["memory_context_token_count"] == 1
    assert "25 seconds" in row["memory_context"][0]["value"]
    user_content = row["messages"][1]["content"]
    image_parts = [part for part in user_content if part.get("type") == "image_url"]
    assert len(image_parts) == 2
    encoded = [part["image_url"]["url"].split(",", 1)[1] for part in image_parts]
    assert all(base64.b64decode(value, validate=True) == image_bytes for value in encoded)
    assert row["prompt_messages"][1]["content"][-1] == {
        "type": "image_path",
        "image_path": str(question_image),
    }
    print("pinned_official_harness_prompt_build=PASS")
    print("synthetic_images=2; context_token_counter=stubbed; model_calls=0; benchmark_data=0")


if __name__ == "__main__":
    main()
