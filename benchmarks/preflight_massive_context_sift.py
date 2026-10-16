"""Run a provider-free 500K+ compaction preflight on the frozen swarm packet."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time
from typing import Any

import litellm
from litellm import Router

PINNED_LITELLM = "1.103.0"
TASK_REQUEST = (
    "Implement a backwards-compatible webhook delivery reliability change across the intake API, "
    "delivery worker, SQLite migration, and operator telemetry/runbook. Use tenant-scoped "
    "(tenant_id, event_id) idempotency, canonical-payload conflict protection, HMAC freshness, "
    "2xx-only success, bounded retries and Retry-After, lease/crash recovery, endpoint rotation, "
    "privacy-safe persisted metrics, and a fully reconciled, rerunnable migration of every legacy "
    "snapshot row, including identical-row aliases and changed-payload conflict quarantine. "
    "Delegate read-only investigations to four named agents covering API, worker, migration, "
    "and operations; the parent agent is the only writer. Read the supplied contracts and "
    "incident evidence, run the full test suite, and report unresolved assumptions."
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "benchmarks"))
from sift.litellm_proxy import compact_proxy_request
from evidence_retention import audit_retention, load_required_spans


def _chunks(packet: bytes, size: int = 48 * 1024) -> list[str]:
    chunks = []
    start = 0
    while start < len(packet):
        end = min(start + size, len(packet))
        while end < len(packet) and packet[end] & 0xC0 == 0x80:
            end -= 1
        chunks.append(packet[start:end].decode("utf-8"))
        start = end
    return chunks


def _messages(packet: bytes, task_request: str = TASK_REQUEST) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for index, chunk in enumerate(_chunks(packet)):
        call_id = f"load_{index:03d}"
        name = f"load_context_chunk_{index:03d}"
        messages.append({
            "role": "assistant",
            "content": [{"type": "tool_use", "id": call_id, "name": name, "input": {}}],
        })
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": call_id,
                         "content": chunk, "is_error": False}],
        })
    messages.append({
        "role": "user",
        "content": [{"type": "text", "text": task_request}],
    })
    return messages


def preflight(packet_path: Path, gold_dir: Path, model: str, targets: list[int],
              task_request: str = TASK_REQUEST) -> dict[str, Any]:
    installed_litellm = version("litellm")
    if installed_litellm != PINNED_LITELLM:
        raise RuntimeError(f"requires LiteLLM {PINNED_LITELLM}; found {installed_litellm}")
    packet = packet_path.read_bytes()
    evidence_manifest = gold_dir / "evidence.json"
    spans = load_required_spans(evidence_manifest) if evidence_manifest.is_file() else ()
    messages = _messages(packet, task_request)
    router = Router(model_list=[
        {"model_name": alias, "litellm_params": {"model": model, "api_key": "offline-count-only"}}
        for alias in ("minimax-m3-full", "minimax-m3-sift")
    ])
    base_request = {
        "model": "minimax-m3-full",
        "messages": messages,
        "system": "You are a coding agent investigating a production incident. Use source evidence and preserve uncertainty.",
        "tools": [],
        "max_tokens": 4096,
    }
    full = compact_proxy_request(router, base_request, call_type="anthropic_messages",
                                 target=1_000_000, raw_limit=1_000_000)
    full_audit = full["metadata"]["sift"]
    rows = []
    for target in targets:
        started = time.perf_counter()
        sift_request = compact_proxy_request(
            router, {**base_request, "model": "minimax-m3-sift"},
            call_type="anthropic_messages", target=target, raw_limit=1_000_000,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        audit = sift_request["metadata"]["sift"]
        retained = (audit_retention(messages, sift_request["messages"], spans)
                    if spans else None)
        retained_count = (sum(state == "retained" for state in retained.values())
                          if retained is not None else None)
        scale_and_budget_passed = (
            audit["input_tokens"] >= 500_000
            and audit["forwarded_tokens"] <= target
        )
        rows.append({
            "target_tokens": target,
            "audit": audit,
            "elapsed_ms": round(elapsed_ms, 3),
            "required_span_states": retained,
            "exact_span_retention_diagnostic": ({
                "retained": retained_count,
                "total": len(retained),
                "all_retained": retained_count == len(retained),
            } if retained is not None else None),
            "scale_and_budget_passed": scale_and_budget_passed,
        })
    return {
        "schema_version": 1,
        "kind": "provider_free_synthetic_anthropic_request_preflight",
        "qualified_agent_comparison": False,
        "task_request_sha256": hashlib.sha256(task_request.encode("utf-8")).hexdigest(),
        "task_request_chars": len(task_request),
        "token_counter": f"LiteLLM Router._count_pre_call_check_tokens {installed_litellm} {model}",
        "packet": {
            "path": str(packet_path),
            "bytes": len(packet),
            "sha256": hashlib.sha256(packet).hexdigest(),
            "historical_tool_result_chunks": len(_chunks(packet)),
            "fixture": gold_dir.name,
            "required_evidence_spans": len(spans),
        },
        "raw_message_tokens": full_audit["input_tokens"],
        "full_arm_forwarded_tokens": full_audit["forwarded_tokens"],
        "targets": rows,
        "notes": [
            "Counts a constructed Anthropic Messages tool-cycle transcript, not a captured Claude Code request.",
            "Omits Claude Code system prompt and active tool schemas; the deployed route must qualify each real request.",
            "Exact source-span retention is diagnostic only; the agent may retrieve omitted source facts from the same workspace.",
            "Preflight pass means only that the constructed request reached the raw scale floor and Sift stayed within target; it is not agent acceptance or provider-ingestion evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=REPOSITORY_ROOT / "benchmarks/agent_cases/webhook_swarm_500k/swarm_context.md")
    parser.add_argument("--gold", type=Path, default=REPOSITORY_ROOT / "benchmarks/agent_gold/webhook_swarm_500k")
    parser.add_argument("--model", default="openrouter/minimax/minimax-m3")
    parser.add_argument("--task-request-file", type=Path,
                        help="use a frozen task request from a UTF-8 file instead of the built-in request")
    parser.add_argument("--target", type=int, action="append", dest="targets",
                        help="Sift target in tokens; repeat to compare several targets (default: 64000 and 32000)")
    args = parser.parse_args()
    targets = args.targets or [64_000, 32_000]
    if any(target <= 0 or target > 1_000_000 for target in targets):
        parser.error("targets must be between 1 and 1000000")
    try:
        task_request = (args.task_request_file.read_text(encoding="utf-8")
                        if args.task_request_file else TASK_REQUEST)
        result = preflight(args.packet, args.gold, args.model, targets, task_request)
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__,
                          "error": str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all(row["scale_and_budget_passed"] for row in result["targets"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
