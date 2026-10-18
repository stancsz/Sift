"""Seed a frozen context packet as a historical Claude Code tool result.

This helper prepares, but does not compare, the full-context checkpoint used by
the native 500K+ agent experiment. It makes one bounded provider session and
persists it under an isolated Claude config directory for later forked arms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

try:
    from benchmarks.claude_usage import stream_request_usage
except ModuleNotFoundError:
    from claude_usage import stream_request_usage


CHUNK_BYTES = 48 * 1024


SERVER = r'''import hashlib, json, sys
from pathlib import Path
packet = Path(sys.argv[1]).read_bytes()
expected = sys.argv[2]
chunk_bytes = int(sys.argv[3])
if hashlib.sha256(packet).hexdigest() != expected:
    raise SystemExit("context packet hash mismatch")
chunks = []
start = 0
while start < len(packet):
    end = min(start + chunk_bytes, len(packet))
    while end < len(packet) and (packet[end] & 0xC0) == 0x80:
        end -= 1
    chunks.append(packet[start:end].decode("utf-8"))
    start = end
names = [f"load_context_chunk_{index:03d}" for index in range(len(chunks))]
for line in sys.stdin:
    request = json.loads(line)
    method, identifier = request.get("method"), request.get("id")
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "sift-context-seed", "version": "1.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": name,
                  "description": "Return this exact numbered segment of the frozen experiment context packet.",
                  "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}
                  for name in names]}
    elif method == "tools/call" and request.get("params", {}).get("name") in names:
        index = names.index(request["params"]["name"])
        result = {"content": [{"type": "text", "text": chunks[index]}], "isError": False}
    else:
        if identifier is None:
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": identifier,
                          "error": {"code": -32601, "message": "method not found"}}), flush=True)
        continue
    if identifier is not None:
        print(json.dumps({"jsonrpc": "2.0", "id": identifier, "result": result}), flush=True)
'''


def _chunk_packet(packet: bytes, chunk_bytes: int = CHUNK_BYTES) -> list[str]:
    """Split UTF-8 bytes without changing a single byte or exceeding the tool cap."""
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    chunks: list[str] = []
    start = 0
    while start < len(packet):
        end = min(start + chunk_bytes, len(packet))
        while end < len(packet) and (packet[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(packet[start:end].decode("utf-8"))
        start = end
    return chunks


def _verify_chunk_events(events: list[dict], packet: bytes) -> dict:
    """Require all bounded MCP results to be present verbatim in Claude's stream."""
    chunks = _chunk_packet(packet)
    expected_names = {f"mcp__sift_context__load_context_chunk_{i:03d}"
                      for i in range(len(chunks))}
    calls: dict[str, tuple[str, int]] = {}
    results: dict[str, str] = {}
    for event in events:
        message = event.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                name = block.get("name")
                if name in expected_names and isinstance(block.get("id"), str):
                    calls[block["id"]] = (name, len(calls))
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id")
                value = block.get("content")
                if isinstance(value, str):
                    content = value
                elif isinstance(value, list) and all(
                    isinstance(part, dict) and part.get("type") == "text"
                    and isinstance(part.get("text"), str) for part in value
                ):
                    content = "".join(part["text"] for part in value)
                else:
                    content = None
                if isinstance(tool_use_id, str) and content is not None:
                    results[tool_use_id] = content

    missing_calls = sorted(expected_names - {name for name, _ in calls.values()})
    if missing_calls:
        raise ValueError(f"missing_context_chunk_tool_calls:{len(missing_calls)}")
    chunks_by_index: dict[int, str] = {}
    for tool_use_id, (name, _) in calls.items():
        if tool_use_id not in results:
            raise ValueError("missing_context_chunk_tool_result")
        index = int(name.rsplit("_", 1)[1])
        chunks_by_index[index] = results[tool_use_id]
    reconstructed = "".join(chunks_by_index[index] for index in range(len(chunks)))
    reconstructed_bytes = reconstructed.encode("utf-8")
    digest = hashlib.sha256(reconstructed_bytes).hexdigest()
    expected_digest = hashlib.sha256(packet).hexdigest()
    if digest != expected_digest:
        raise ValueError("checkpoint_context_sha256_mismatch")
    return {
        "expected_chunk_count": len(chunks),
        "tool_call_count": len(calls),
        "tool_result_count": len(results),
        "checkpoint_context_bytes": len(reconstructed_bytes),
        "checkpoint_context_sha256": digest,
        "checkpoint_content_verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True, help="Frozen packet inside the case directory")
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--claude-config-dir", type=Path, required=True,
                        help="New isolated directory where Claude will persist the checkpoint")
    parser.add_argument("--base-url", required=True, help="OpenAI-compatible LiteLLM /v1 URL")
    parser.add_argument("--model", required=True, help="Full-context benchmark model alias")
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--max-budget-usd", type=float, required=True,
                        help="Claude Code client budget limit; not a provider-enforced hard spend cap")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--executable", help="Claude Code executable; defaults to PATH")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    key = os.environ.get(args.api_key_env)
    packet = args.packet.resolve()
    case = args.case.resolve()
    if not key:
        parser.error("Set the API key environment variable")
    if not args.base_url.rstrip("/").endswith("/v1") or args.timeout <= 0:
        parser.error("Use a positive timeout and an OpenAI-compatible /v1 base URL")
    if not 0 < args.max_budget_usd < float("inf"):
        parser.error("--max-budget-usd must be finite and positive")
    if not packet.is_relative_to(case) or not packet.is_file():
        parser.error("--packet must be an existing file inside --case")
    executable = args.executable or shutil.which("claude")
    if not executable:
        parser.error("Claude Code executable not found; supply --executable")
    session_id = str(uuid.uuid4())
    packet_bytes = packet.read_bytes()
    digest = hashlib.sha256(packet_bytes).hexdigest()
    chunks = _chunk_packet(packet_bytes)
    config_dir = args.claude_config_dir.resolve()
    if config_dir.is_relative_to(case) or case.is_relative_to(config_dir):
        parser.error("--claude-config-dir must be separate from the frozen case directory")
    report_path = args.report.resolve()
    if report_path.is_relative_to(case):
        parser.error("--report must be outside the frozen case directory")
    if config_dir.exists() and any(config_dir.iterdir()):
        parser.error("--claude-config-dir must be new or empty to keep session provenance isolated")
    config_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "phase": "preflight",
        "session_id": session_id,
        "packet": str(packet.relative_to(case).as_posix()),
        "packet_sha256": digest,
        "packet_bytes": packet.stat().st_size,
        "delivery": "bounded independent MCP chunk results saved as historical session context",
        "packet_chunk_bytes_max": CHUNK_BYTES,
        "packet_chunk_count": len(chunks),
        "base_url": args.base_url,
        "model": args.model,
        "spend_ceiling_usd": args.max_budget_usd,
        "provider_input_tokens": None,
        "route_input_tokens": None,
        "qualification": "pending; requires post-seed checkpoint request count and full-route callback evidence",
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    mcp_config = {"mcpServers": {"sift_context": {
        "command": sys.executable,
        "args": ["-c", SERVER, str(packet), digest, str(CHUNK_BYTES)],
    }}}
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(("OPENAI_", "ANTHROPIC_", "CLAUDE_"))
           and name not in {args.api_key_env, "PYTHONPATH", "PYTHONHOME"}}
    env.update({
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "ANTHROPIC_API_KEY": key,
        "ANTHROPIC_BASE_URL": args.base_url.rstrip("/")[:-3],
        "ANTHROPIC_CUSTOM_MODEL_OPTION": args.model,
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
        "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "95",
        # The model emits one parallel tool call per bounded packet segment.
        # 256 tokens truncates the call list; keep the response within the
        # gateway's explicit 4096-token cap while allowing all chunk calls.
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096",
        "CLAUDE_CODE_MAX_RETRIES": "0",
        "API_TIMEOUT_MS": str(min(90_000, args.timeout * 1000)),
    })
    command = [executable, "-p", "--bare", "--setting-sources", "", "--strict-mcp-config",
               "--mcp-config", json.dumps(mcp_config, separators=(",", ":")),
               "--tools", ",".join(f"mcp__sift_context__{name}" for name in
                                    (f"load_context_chunk_{i:03d}" for i in range(len(chunks)))), "--allowedTools",
               ",".join(f"mcp__sift_context__{name}" for name in
                         (f"load_context_chunk_{i:03d}" for i in range(len(chunks)))), "--permission-mode", "dontAsk",
               "--model", args.model, "--session-id", session_id, "--max-budget-usd",
               str(args.max_budget_usd), "--max-turns", "3", "--output-format", "stream-json",
               "--include-partial-messages", "--verbose"]
    tool_names = [f"mcp__sift_context__load_context_chunk_{index:03d}"
                  for index in range(len(chunks))]
    prompt = ("Call each of these tools exactly once, in numeric order, to add the complete frozen "
              "packet as historical tool-result context. Do not summarize or copy the contents. "
              "Tools: " + ", ".join(tool_names) +
              ". After all tool results return, reply with exactly CHECKPOINT_SEEDED.")
    try:
        completed = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                   cwd=case, env=env, timeout=args.timeout, check=False)
    except subprocess.TimeoutExpired as error:
        out = error.stdout.decode("utf-8", "replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
        err = error.stderr.decode("utf-8", "replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
        completed = None
        exit_code, stdout, stderr = None, out, err
        timed_out = True
    else:
        exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
        timed_out = False
    for secret in (key, json.dumps(key, ensure_ascii=False)[1:-1], json.dumps(key)[1:-1]):
        stdout = stdout.replace(secret, "[REDACTED]")
        stderr = stderr.replace(secret, "[REDACTED]")
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    try:
        checkpoint_audit = _verify_chunk_events(events, packet_bytes)
    except ValueError as error:
        checkpoint_audit = {"checkpoint_content_verified": False,
                            "checkpoint_verification_failure": str(error)}
    transcript_files = list(config_dir.rglob(f"{session_id}.jsonl"))
    transcript_audit = {"checkpoint_content_verified": False,
                        "checkpoint_verification_failure": "session_transcript_missing"}
    if len(transcript_files) == 1:
        try:
            transcript_events = [json.loads(line) for line in
                                 transcript_files[0].read_text(encoding="utf-8").splitlines()]
            transcript_audit = _verify_chunk_events(transcript_events, packet_bytes)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            transcript_audit = {"checkpoint_content_verified": False,
                                "checkpoint_verification_failure": type(error).__name__}
    elif len(transcript_files) > 1:
        transcript_audit = {"checkpoint_content_verified": False,
                            "checkpoint_verification_failure": "multiple_session_transcripts"}
    final = next((event for event in reversed(events) if event.get("type") == "result"), {})
    report.update({"phase": "seeded", "exit_code": exit_code, "timed_out": timed_out,
                   "stdout_characters": len(stdout), "stderr_characters": len(stderr),
                   "checkpoint_audit": checkpoint_audit,
                   "transcript_audit": transcript_audit,
                   "seed_tool_calls": checkpoint_audit.get("tool_call_count", 0),
                   "seed_acknowledged": "CHECKPOINT_SEEDED" in stdout,
                   "client_reported_usage": final.get("usage"),
                   "client_reported_request_usage": stream_request_usage(events),
                   "client_reported_cost_usd": final.get("total_cost_usd"),
                   "session_id": session_id})
    report["seeded"] = (exit_code == 0 and not timed_out and report["seed_acknowledged"]
                        and checkpoint_audit.get("checkpoint_content_verified") is True
                        and transcript_audit.get("checkpoint_content_verified") is True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["seeded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
