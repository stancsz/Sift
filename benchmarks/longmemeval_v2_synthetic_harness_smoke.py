"""Exercise the pinned LongMemEval prompt path with synthetic images only.

This bounded smoke calls upstream ``build_prompt_row`` and the actual pinned
Qwen reader processor on generated fixtures. It stubs unused registry/scoring
imports only. It loads tokenizer/processor metadata, never model weights or
benchmark data, and never calls a model.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.util
import os
import pathlib
import struct
import sys
import tempfile
import types
import zlib
from types import SimpleNamespace

PINNED_HARNESS_GIT_BLOB = "6a7182440a2cdd3ace6286dd966f7953fc383e8e"
READER_MODEL = "Qwen/Qwen3.5-9B"
READER_REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
READER_METADATA_SHA256 = {
    "chat_template.jinja": "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715",
    "config.json": "d0883072e01861ed0b2d47be3c16c36a8e81c224c7ffaa310c6558fb3f932b05",
    "merges.txt": "a9d356d7bdf1ef4949e3e748e95b8e10ad9d4e2e838eddc38a0a7b6b94d1db8d",
    "preprocessor_config.json": "27225450ac9c6529872ee1924fcb0962ff5634834f817040f444118116f4e516",
    "tokenizer.json": "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42",
    "tokenizer_config.json": "316230d6a809701f4db5ea8f8fc862bc3a6f3229c937c174e674ff3ca0a64ac8",
    "video_preprocessor_config.json": "7768af27c1fafa9cc9011c1dc20067e03f8915e03b63504550e11d5066986d13",
    "vocab.json": "ce99b4cb2983d118806ce0a8b777a35b093e2000a503ebde25853284c9dfa003",
}


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _tiny_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x20\x40\x60\x80\xa0\xc0"))
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


def _verify_reader_metadata(path: pathlib.Path) -> None:
    if not path.is_dir():
        raise SystemExit(f"Pinned reader metadata directory is missing: {path}")
    visible_files = {item.name for item in path.iterdir() if item.is_file() and not item.name.startswith(".")}
    if visible_files != set(READER_METADATA_SHA256):
        raise SystemExit("Reader snapshot must contain only the eight pinned processor/tokenizer metadata files")
    for name, expected in READER_METADATA_SHA256.items():
        digest = hashlib.sha256((path / name).read_bytes()).hexdigest()
        if digest != expected:
            raise SystemExit(f"Pinned reader metadata hash mismatch: {name}")
    if any(any(path.rglob(pattern)) for pattern in ("*.safetensors", "*.bin", "*.pt", "*.gguf")):
        raise SystemExit("Reader snapshot unexpectedly contains model weights")


class _SyntheticContextMemory:
    def __init__(self, items: list[dict[str, str]]) -> None:
        self.items = items
        self.last_query_image: str | None = None
        self.lifecycle: list[str] = []

    def set_query_context(self, *, query_invocation_id: str) -> None:
        assert query_invocation_id == "synthetic-pressure-query"
        self.lifecycle.append("set")

    def query(self, _query: str, query_image: str | None = None) -> list[dict[str, str]]:
        self.last_query_image = query_image
        self.lifecycle.append("query")
        return [dict(item) for item in self.items]

    def post_query_hook(self, *, query: str, query_image: str | None,
                        memory_context: list[dict[str, str]]) -> dict[str, str]:
        assert query == "Which fixture fact should be retained?"
        assert query_image == self.last_query_image
        self.lifecycle.append("post")
        return {"context_items": str(len(memory_context))}

    def clear_query_context(self) -> None:
        self.lifecycle.append("clear")


def _exercise_context_pressure(harness, state_image: pathlib.Path,
                               question_image: pathlib.Path) -> tuple[dict, dict, int, int]:
    items = [
        {"type": "text", "value": "Synthetic prefix marker: BLUE LANTERN."},
        {"type": "image", "value": str(state_image)},
        {"type": "text", "value": ("Synthetic tail that should be dropped under token pressure. " * 900)},
        {"type": "image", "value": str(question_image)},
    ]
    loaded = harness.load_memory_context_images(items)
    prefix_two_tokens = harness.count_memory_context_tokens(items[:2], loaded[:2])
    prefix_three_tokens = harness.count_memory_context_tokens(items[:3], loaded[:3])
    full_tokens = harness.count_memory_context_tokens(items, loaded)
    assert prefix_two_tokens > 1
    assert prefix_three_tokens > prefix_two_tokens
    assert full_tokens >= prefix_three_tokens

    question = {
        "question_id": "synthetic-pressure",
        "query_invocation_id": "synthetic-pressure-query",
        "question_text": "Which fixture fact should be retained?",
        "question_image": str(question_image),
        "eval_name": "exact_match",
    }
    memory = _SyntheticContextMemory(items)
    kept = harness.build_prompt_row(
        question, haystack_ids=["synthetic-trajectory"], memory=memory,
        system_prompt="Synthetic token pressure only.",
        memory_context_max_tokens=prefix_two_tokens,
    )
    assert kept["memory_context"] == items[:2]
    assert kept["memory_context_original_token_count"] == full_tokens
    assert kept["memory_context_token_count"] == prefix_two_tokens
    assert kept["memory_context_token_count"] <= prefix_two_tokens
    assert kept["memory_context_was_truncated"] is True
    assert memory.lifecycle == ["set", "query", "post", "clear"]
    assert memory.last_query_image == str(question_image)
    kept_image_paths = [part["image_path"] for part in kept["prompt_messages"][1]["content"]
                        if part.get("type") == "image_path"]
    assert kept_image_paths == [str(state_image), str(question_image)]

    repeated_memory = _SyntheticContextMemory(items)
    repeated = harness.build_prompt_row(
        question, haystack_ids=["synthetic-trajectory"], memory=repeated_memory,
        system_prompt="Synthetic token pressure only.",
        memory_context_max_tokens=prefix_two_tokens,
    )
    assert repeated["memory_context"] == kept["memory_context"]
    assert repeated["memory_context_token_count"] == kept["memory_context_token_count"]
    repeated_image_paths = [part["image_path"] for part in repeated["prompt_messages"][1]["content"]
                            if part.get("type") == "image_path"]
    assert repeated_image_paths == kept_image_paths

    empty_memory = _SyntheticContextMemory(items)
    empty = harness.build_prompt_row(
        question, haystack_ids=["synthetic-trajectory"], memory=empty_memory,
        system_prompt="Synthetic empty-context case.", memory_context_max_tokens=1,
    )
    assert empty["memory_context"] == []
    assert empty["memory_context_original_token_count"] == full_tokens
    assert empty["memory_context_token_count"] == 0
    assert empty["memory_context_token_count"] <= 1
    assert empty["memory_context_was_truncated"] is True
    assert empty_memory.last_query_image == str(question_image)
    empty_log = empty["prompt_messages"][1]["content"]
    assert any(part.get("type") == "text" and "(empty)" in part.get("text", "") for part in empty_log)
    empty_image_paths = [part["image_path"] for part in empty_log if part.get("type") == "image_path"]
    assert empty_image_paths == [str(question_image)]
    return kept, empty, full_tokens, prefix_two_tokens


def _exercise_fake_minimax_reader(harness, messages: list[dict]) -> None:
    args = argparse.Namespace(
        model="minimax/minimax-m3",
        base_url="http://minimax.synthetic.invalid/v1",
        timeout_seconds=37.0,
        max_completion_tokens=64,
        reasoning_effort=None,
        temperature=0.0,
        top_p=1.0,
        presence_penalty=0.0,
        top_k=40,
        repetition_penalty=1.05,
        reader_enable_thinking=False,
    )
    expected_request = harness.build_reader_request(args, messages)
    assert expected_request == {
        "model": "minimax/minimax-m3",
        "messages": messages,
        "timeout": 37.0,
        "max_tokens": 64,
        "temperature": 0.0,
        "top_p": 1.0,
        "presence_penalty": 0.0,
        "extra_body": {"top_k": 40, "repetition_penalty": 1.05},
    }
    assert "max_completion_tokens" not in expected_request

    class FakeCompletions:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Synthetic MiniMax answer."))],
                usage=SimpleNamespace(prompt_tokens=321, completion_tokens=7, total_tokens=328),
            )

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    answer, usage = asyncio.run(harness.call_reader_model_async(client, args, messages))
    assert answer == "Synthetic MiniMax answer."
    assert usage == {"prompt_tokens": 321, "completion_tokens": 7, "total_tokens": 328}
    assert completions.calls == [expected_request]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("harness", type=pathlib.Path, help="path to pinned evaluation/harness.py")
    parser.add_argument(
        "--processor-dir",
        type=pathlib.Path,
        help="local metadata-only snapshot of the pinned official Qwen reader processor",
    )
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    scratch = root / "tmp" / "longmemeval-synthetic-harness"
    processor_dir = args.processor_dir or scratch / f"qwen3.5-9b-{READER_REVISION}"
    _verify_reader_metadata(processor_dir)
    # Keep all Hugging Face state in the bounded scratch directory and ensure
    # the actual processor load cannot reach the network or fetch model weights.
    os.environ["HF_HOME"] = str(scratch / "hf-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    sys.path.insert(0, str(scratch / "site-packages"))
    sys.path.insert(0, str(root))

    try:
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise SystemExit("Pillow is required to decode the synthetic screenshot fixtures") from exc

    try:
        from transformers import AutoProcessor
    except ImportError as exc:
        raise SystemExit("The existing transformers runtime is required; this smoke installs nothing") from exc
    processor = AutoProcessor.from_pretrained(str(processor_dir), local_files_only=True)
    harness = _load_harness(args.harness)
    harness.get_memory_context_processor = lambda: processor
    from benchmarks.longmemeval_v2_sift_adapter import SiftMemory

    image_bytes = _tiny_png()
    fixture_root = scratch / "fixtures"
    fixture_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sift-longmemeval-smoke-", dir=fixture_root) as temp_dir:
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
        actual_count = harness.count_memory_context_tokens(
            row["memory_context"],
            harness.load_memory_context_images(row["memory_context"]),
        )
        pressure_kept, pressure_empty, pressure_original, pressure_limit = (
            _exercise_context_pressure(harness, state_image, question_image)
        )
        _exercise_fake_minimax_reader(harness, pressure_kept["messages"])

    assert row["memory_context"]
    assert row["memory_context_token_count"] == actual_count
    assert row["memory_context_token_count"] > 1
    assert row["memory_context_original_token_count"] == actual_count
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
    print(f"reader_processor={READER_MODEL}@{READER_REVISION}; processor_class={type(processor).__name__}")
    print(f"reader_context_tokens={actual_count}; synthetic_images=2; model_weights=0; model_calls=0; benchmark_data=0")
    empty_question_images = [
        part for part in pressure_empty["prompt_messages"][1]["content"]
        if part.get("type") == "image_path"
    ]
    print(
        "context_pressure=PASS; kept_items=2/4; dropped_tail_text=1; dropped_tail_image=1; "
        f"empty_context_items={len(pressure_empty['memory_context'])}; "
        f"question_image_preserved={len(empty_question_images) == 1}; "
        f"original_tokens={pressure_original}; kept_tokens={pressure_limit}"
    )
    print("fake_minimax_reader_plumbing=PASS; request_is_not_provider_dispatch_ready=no_minimax_route_injection; provider_requests=0")


if __name__ == "__main__":
    main()
