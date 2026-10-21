"""Run pinned LongMemEval main/file/scoring flows on generated fixtures only.

The official registry, normalization, processor and deterministic scorer are
real; only the reader client is replaced with an in-memory generated response.
A missing registry dependency produces a truthful blocked result, not a stub.
No source, dataset, package, model weight or inference is downloaded here.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import importlib.metadata
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace


UPSTREAM_REVISION = "2cc8c540bdb87fe6761629b585e727e1c4704520"
SOURCE_SHA256 = {
    "evaluation/__init__.py": "3bb49daf05b8ee42f69333da407f6a987adc81ee23f523839036f700d82ee8a4",
    "evaluation/harness.py": "93fe5855a74ad46d7e8b489cebac24de38a9b30ba7ec1de2dd8708bd4aeebdb6",
    "evaluation/qa_eval_metrics.py": "f8ba659e237c4282a07a92538090ea500ce8483820b390b1d19af187c01417ac",
    "memory_modules/__init__.py": "29eb4729405989c468a7a2b3171b620ffa4645098fcc348cadc56fc56cfb8044",
    "memory_modules/agentrunbook_c.py": "18b30338c847f246734d116d6830967894867598b7b0b73c71070db3ad5dcea3",
    "memory_modules/agentrunbook_c_v2.py": "1bea5dc2b80f9589d68e2b0c8c1c11d161df433383c4bbfd57b8d52420442922",
    "memory_modules/agentrunbook_online_learning.py": "06c429c1712da03b96ab6b081dc12a1a91a5e86189381bc761e7321b804131b2",
    "memory_modules/agentrunbook_r.py": "7e96c0f386224bf13ad2a694f35bc6546738bf3b99de09c89fcc3a85509fb8f8",
    "memory_modules/assets/agentrunbook_c/scripts/inspect_trajectory.py": "9d7df382c6ae3bf04155b62cfd6fdfd91b20568987620f1888c61b03882a830f",
    "memory_modules/assets/agentrunbook_c/scripts/render_trajectory_summary.py": "ab20519d302b5f12f25a25e743da0acdee2c98a1e10c0e1c212a53202351c337",
    "memory_modules/codex.py": "3d7c248f3c91a49dd7f8c15d564d41c0ecf26ad0bbc7645883757223780722e7",
    "memory_modules/memory.py": "607ca21320067df2abc3583b80debeb819781e90955776bdea4313a8b93a0586",
    "memory_modules/no_retrieval.py": "a5b5fb0baef4314469556aec5cc2ab28ab23b283f544e8130b380d86c7c27307",
    "memory_modules/oai_agents_sdk.py": "170baea7903f32f7f5aad33520e7e918bf90e2e49a1123d8ba57b254d9f3887a",
    "memory_modules/rag.py": "f5fed6692cf1b6b1d4baa3896a9cd323df65b31b649ceba1922c1a2b97a402ae",
    "memory_modules/support.py": "66e1bb68ae42f0467e24cde0444b88f2d08c991ad9fd22ceda9920cf4b9d0f53",
    "memory_modules/trajectory_store.py": "437b825499000f7ae774f948a5e62a2ff9f455367491f97d0382431965ce594c",
}


def verify_sources(upstream: Path) -> None:
    for relative, expected in SOURCE_SHA256.items():
        path = upstream / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Pinned upstream source mismatch: {relative}")


def load_standalone_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load pinned source module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def strip_script_import_directory(paths: list[str], script_dir: Path) -> list[str]:
    """Avoid shadowing the real Agents SDK with benchmarks/agents.py."""
    return [entry for entry in paths if Path(entry or ".").resolve() != script_dir.resolve()]


def _loopback_host(host) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextmanager
def block_external_connections():
    """Permit only asyncio's loopback infrastructure; never a provider endpoint."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    observed = {"loopback_connections": 0, "blocked_external_attempts": 0}

    def check_address(address):
        if not isinstance(address, tuple) or not _loopback_host(address[0]):
            observed["blocked_external_attempts"] += 1
            raise RuntimeError("Synthetic main probe forbids external connections")
        observed["loopback_connections"] += 1

    def connect(sock, address):
        check_address(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check_address(address)
        return original_connect_ex(sock, address)

    def getaddrinfo(host, *args, **kwargs):
        if not _loopback_host(host):
            observed["blocked_external_attempts"] += 1
            raise RuntimeError("Synthetic main probe forbids external DNS")
        return original_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    try:
        yield observed
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.getaddrinfo = original_getaddrinfo


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def run_partial_probes(upstream: Path, run_dir: Path) -> dict:
    from benchmarks.longmemeval_v2_synthetic_harness_smoke import _tiny_png

    store = load_standalone_module("sift_pinned_trajectory_store", upstream / "memory_modules/trajectory_store.py")
    scoring = load_standalone_module("sift_pinned_qa_metrics", upstream / "evaluation/qa_eval_metrics.py")
    image = run_dir / "generated-state.png"
    image.write_bytes(_tiny_png())
    common_state = {"url": "https://fixture.invalid/settings", "action": "read setting"}
    public = {
        "id": "synthetic-public", "goal": "Read generated setting", "start_url": common_state["url"],
        "states": [{**common_state, "accessibility_tree": "Generated choice is A.", "screenshot": str(image)}],
    }
    legacy = {
        "id": "synthetic-legacy", "metadata": {"original_goal": "Read generated setting"},
        "content": [{**common_state, "observation": {"text": "Generated choice is A.", "screenshot": str(image)}}],
    }
    normalized = []
    for label, trajectory in (("public", public), ("legacy", legacy)):
        prepared = store.prepare_trajectory_insert(trajectory, trajectories_root_dir=run_dir)
        normalized_dir = run_dir / label
        store.materialize_prepared_trajectory(prepared, normalized_dir)
        assert len(prepared.simplified["states"]) == prepared.screenshot_count == 1
        state = prepared.simplified["states"][0]
        assert state["text"] == "Generated choice is A."
        assert (normalized_dir / state["screenshot"]).read_bytes() == image.read_bytes()
        assert prepared.fingerprint == store.logical_trajectory_fingerprint_from_simplified(prepared.simplified)
        row = deepcopy(prepared.simplified)
        for normalized_state in row["states"]:
            normalized_state["screenshot"] = str(normalized_dir / normalized_state["screenshot"])
        normalized.append(row)
    save_json(run_dir / "trajectories.json", normalized)
    parsed = scoring.extract_boxed_answer(r"Synthetic response: \boxed{A}")
    scores = [scoring.score_to_bool(scoring.eval_from_spec("mc_choice_match", parsed, answer))
              for answer in ("A", "B")]
    assert scores == [True, False]
    return {"normalization": {"public": "PASS", "legacy": "PASS", "generated_images": 1},
            "deterministic_scoring": {"function": "mc_choice_match", "positive": scores[0],
                                       "negative": scores[1]}}


def run_main_flows(harness, run_dir: Path, root: Path) -> dict:
    from benchmarks.longmemeval_v2_minimax_request_policy import wrap_minimax_reader_request_builder
    from benchmarks.longmemeval_v2_sift_adapter import SiftMemory, register_with_longmemeval
    from benchmarks.longmemeval_v2_synthetic_harness_smoke import READER_REVISION, _verify_reader_metadata
    from transformers import AutoProcessor

    register_with_longmemeval()
    metadata = root / "tmp/longmemeval-synthetic-harness" / f"qwen3.5-9b-{READER_REVISION}"
    _verify_reader_metadata(metadata)
    processor = AutoProcessor.from_pretrained(str(metadata), local_files_only=True)
    original_processor = harness.get_memory_context_processor
    original_client = harness.create_async_client
    original_builder = harness.build_reader_request
    original_argv = sys.argv
    question_image = str(run_dir / "generated-state.png")
    questions = [{
        "id": f"synthetic-question-{index}", "question_type": category,
        "question": {"text": "Which generated fixture code is shown?", "image": question_image},
        "answer": answer, "eval_function": "mc_choice_match",
    } for index, (category, answer) in enumerate((("static-environment", "A"), ("dynamic-environment", "B")))]
    save_json(run_dir / "questions.json", questions)
    save_json(run_dir / "memory_config.json", {
        "memory_type": SiftMemory.memory_type,
        "memory_params": {"target_tokens": 20_000, "raw_limit": 100_000,
                          "trajectories_root_dir": str(run_dir)},
    })
    run_results = {}
    try:
        harness.get_memory_context_processor = lambda: processor
        harness.build_reader_request = wrap_minimax_reader_request_builder(original_builder)
        for branch in ("shared", "per_question"):
            calls = []
            closed = []

            class FakeCompletions:
                async def create(self, **request):
                    assert request["model"] == "minimax/minimax-m3"
                    assert request["max_tokens"] == 64
                    assert request["extra_body"]["provider"] == {
                        "only": ["minimax"], "allow_fallbacks": False, "require_parameters": True,
                    }
                    calls.append(request)
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=r"\boxed{A}"))],
                        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=3, total_tokens=103),
                    )

            class FakeClient:
                def __init__(self):
                    self.chat = SimpleNamespace(completions=FakeCompletions())

                async def close(self):
                    closed.append(True)

            def fake_client(base_url, api_key_env, api_key_file):
                assert base_url == "http://synthetic.invalid/v1"
                assert api_key_env == "SIFT_SYNTHETIC_UNSET_KEY" and api_key_file is None
                return FakeClient()

            harness.create_async_client = fake_client
            mapping = {question["id"]: (["synthetic-public", "synthetic-legacy"] if branch == "shared"
                                       else [["synthetic-public"], ["synthetic-legacy"]][index])
                       for index, question in enumerate(questions)}
            haystack_path = run_dir / f"haystacks-{branch}.json"
            save_json(haystack_path, mapping)
            output_dir = run_dir / f"output-{branch}"
            sys.argv = [str(harness.__file__), "--domain", "web", "--questions-path", str(run_dir / "questions.json"),
                        "--haystack-path", str(haystack_path), "--trajectories-path", str(run_dir / "trajectories.json"),
                        "--memory-config-path", str(run_dir / "memory_config.json"), "--output-dir", str(output_dir),
                        "--model", "minimax/minimax-m3", "--base-url", "http://synthetic.invalid/v1",
                        "--api-key-env", "SIFT_SYNTHETIC_UNSET_KEY", "--evaluator-api-key-env", "SIFT_SYNTHETIC_UNSET_KEY",
                        "--max-completion-tokens", "64", "--memory-context-max-tokens", "4096",
                        "--reader-max-concurrent-requests", "1", "--prompt-build-max-workers", "1",
                        "--temperature", "0", "--top-p", "1", "--timeout-seconds", "37", "--shuffle-questions-seed", "11"]
            harness.main()
            records = [json.loads(line) for line in (output_dir / "per_question.jsonl").read_text().splitlines()]
            prompts = [json.loads(line) for line in (output_dir / "prompt_rows.jsonl").read_text().splitlines()]
            metrics = json.loads((output_dir / "aggregated_metrics.json").read_text())
            summary = json.loads((output_dir / "prompt_build_summary.json").read_text())
            assert len(records) == len(prompts) == len(calls) == summary["prompt_row_count"] == 2
            assert len(closed) == 1
            assert {row["question_id"] for row in records} == set(mapping)
            assert {row["question_id"]: row["score_bool"] for row in records} == {
                questions[0]["id"]: True, questions[1]["id"]: False,
            }
            assert metrics["overall"]["count_all_questions"] == 2
            assert metrics["overall"]["overall_full_set"] == 0.5
            assert metrics["shared_haystack"] is (branch == "shared")
            assert metrics["tokens"]["prompt_tokens"] == 200
            assert metrics["tokens"]["completion_tokens"] == 6
            for row in prompts:
                assert row["haystack_ids"] == mapping[row["question_id"]]
                assert 0 < row["memory_context_token_count"] <= 4096
                content = row["prompt_messages"][1]["content"]
                assert content[-1] == {"type": "image_path", "image_path": question_image}
                assert any(part.get("type") == "text" and questions[0]["question"]["text"] in part["text"] for part in content)
                assert len([part for part in content if part.get("type") == "image_path"]) == (3 if branch == "shared" else 2)
            run_results[branch] = {"status": "PASS", "questions": 2, "synthetic_reader_calls": len(calls),
                                   "expected_generated_score": 0.5, "synthetic_usage_prompt_tokens": 200,
                                   "synthetic_usage_completion_tokens": 6,
                                   "memory_context_tokens": [row["memory_context_token_count"] for row in prompts]}
    finally:
        harness.get_memory_context_processor = original_processor
        harness.create_async_client = original_client
        harness.build_reader_request = original_builder
        sys.argv = original_argv
    return run_results


def main(network_guard: dict | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    scratch = root / "tmp/longmemeval-synthetic-main"
    upstream = (args.upstream or scratch / "upstream").resolve()
    verify_sources(upstream)
    scratch.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="prerequisite-", dir=scratch))
    script_dir = Path(__file__).resolve().parent
    sys.path[:] = strip_script_import_directory(sys.path, script_dir)
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tmp/longmemeval-synthetic-harness/site-packages"))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
    result = {"upstream_revision": UPSTREAM_REVISION, "source_files_verified": len(SOURCE_SHA256),
              **run_partial_probes(upstream, run_dir), "model_calls": 0, "benchmark_records": 0,
              "full_main_exercised": False}
    sys.path.insert(0, str(upstream))
    try:
        # Import the untouched real registry, including its eager backend
        # dependency closure. Never replace missing modules with successful stubs.
        registry = importlib.import_module("memory_modules.memory")
        harness = importlib.import_module("evaluation.harness")
    except ModuleNotFoundError as error:
        result.update({"status": "BLOCKED_BEFORE_MAIN", "missing_dependency": error.name})
        if error.name == "agents":
            result["dependency_hint"] = (
                "The real upstream registry requires the official openai-agents SDK. "
                "This probe was exercised with openai-agents==0.24.0 in the dedicated "
                "tmp/longmemeval-synthetic-main/.venv; use that interpreter. "
                "No dependency is installed automatically."
            )
    else:
        result.update({"main_flows": run_main_flows(harness, run_dir, root), "status": "PASS",
                       "full_main_exercised": True, "registered_backends": sorted(registry.MEMORY_TYPES),
                       "runtime_versions": {name: importlib.metadata.version(name) for name in
                                            ("openai-agents", "openai", "transformers", "torch", "Pillow")},
                       "scope": "generated sequential shared/per-question main; fake reader; deterministic choice scorer"})
    result["result_path"] = str(run_dir / "prerequisite_result.json")
    if network_guard is not None:
        result["network_guard"] = dict(network_guard)
    (run_dir / "prerequisite_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    with block_external_connections() as guard:
        raise SystemExit(main(guard))
