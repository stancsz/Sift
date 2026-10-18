import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.seed_claude_checkpoint import CHUNK_BYTES, SERVER
from benchmarks import seed_claude_checkpoint as checkpoint


class ClaudeCheckpointSeedTests(unittest.TestCase):
    def test_mcp_tool_returns_frozen_packet_verbatim(self):
        packet = "one\nlarge-context canary: exact bytes\n".encode()
        digest = hashlib.sha256(packet).hexdigest()
        with tempfile.TemporaryDirectory(prefix="sift-context-seed-") as temporary:
            path = Path(temporary) / "packet.md"
            path.write_bytes(packet)
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "load_context_chunk_000", "arguments": {}}},
            ]
            result = subprocess.run(
                [sys.executable, "-c", SERVER, str(path), digest, str(CHUNK_BYTES)],
                input="".join(json.dumps(item) + "\n" for item in requests),
                text=True, capture_output=True, check=True)
        messages = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual("2024-11-05", messages[0]["result"]["protocolVersion"])
        self.assertEqual("load_context_chunk_000", messages[1]["result"]["tools"][0]["name"])
        self.assertEqual(packet.decode(), messages[2]["result"]["content"][0]["text"])
        self.assertFalse(messages[2]["result"]["isError"])

    def test_mcp_server_rejects_packet_hash_drift(self):
        with tempfile.TemporaryDirectory(prefix="sift-context-seed-") as temporary:
            path = Path(temporary) / "packet.md"
            path.write_text("changed", encoding="utf-8")
            result = subprocess.run([sys.executable, "-c", SERVER, str(path), "0" * 64,
                                     str(CHUNK_BYTES)],
                                    input="", text=True, capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("context packet hash mismatch", result.stderr)

    def test_seed_report_requires_real_tool_call_and_acknowledgment(self):
        with tempfile.TemporaryDirectory(prefix="sift-checkpoint-run-") as temporary:
            root = Path(temporary)
            case = root / "case"
            case.mkdir()
            packet = case / "packet.md"
            packet.write_text("frozen fixture", encoding="utf-8")
            config = root / "claude-home"
            report = root / "seed.json"
            stdout = "\n".join([
                json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "call_1", "name": "mcp__sift_context__load_context_chunk_000"} ]}}),
                json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "frozen fixture"} ]}}),
                json.dumps({"type": "result", "subtype": "success", "is_error": False,
                            "total_cost_usd": 0.1}),
                "CHECKPOINT_SEEDED",
            ])
            def fake_run(command, **kwargs):
                session_id = command[command.index("--session-id") + 1]
                transcript = config / "projects" / "fixture" / f"{session_id}.jsonl"
                transcript.parent.mkdir(parents=True)
                transcript.write_text("\n".join(line for line in stdout.splitlines()
                                                 if line.startswith("{")), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout, "")
            argv = ["seed", "--packet", str(packet), "--case", str(case),
                    "--claude-config-dir", str(config), "--base-url", "http://local/v1",
                    "--model", "full", "--api-key-env", "SIFT_TEST_KEY",
                    "--max-budget-usd", "1", "--report", str(report)]
            with patch.object(sys, "argv", argv), patch.dict("os.environ", {"SIFT_TEST_KEY": "secret-value"}), \
                    patch.object(checkpoint.shutil, "which", return_value="claude.exe"), \
                    patch.object(checkpoint.subprocess, "run", side_effect=fake_run) as run, patch("builtins.print"):
                self.assertEqual(0, checkpoint.main())
            saved = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(saved["seeded"])
            self.assertEqual(1, saved["seed_tool_calls"])
            self.assertTrue(saved["checkpoint_audit"]["checkpoint_content_verified"])
            self.assertTrue(saved["transcript_audit"]["checkpoint_content_verified"])
            self.assertEqual("pending; requires post-seed checkpoint request count and full-route callback evidence",
                             saved["qualification"])
            self.assertNotIn("secret-value", report.read_text(encoding="utf-8"))
            command = run.call_args.args[0]
            self.assertIn("--session-id", command)
            self.assertNotIn("--no-session-persistence", command)

    def test_seed_report_rejects_ack_without_context_tool_call(self):
        with tempfile.TemporaryDirectory(prefix="sift-checkpoint-run-") as temporary:
            root = Path(temporary)
            case = root / "case"
            case.mkdir()
            packet = case / "packet.md"
            packet.write_text("frozen fixture", encoding="utf-8")
            argv = ["seed", "--packet", str(packet), "--case", str(case),
                    "--claude-config-dir", str(root / "claude-home"), "--base-url", "http://local/v1",
                    "--model", "full", "--api-key-env", "SIFT_TEST_KEY",
                    "--max-budget-usd", "1", "--report", str(root / "seed.json")]
            output = json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "call_1", "name": "mcp__sift_context__load_context_chunk_000"}]}}) + "\n"
            output += json.dumps({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "frozen fixture"}]}}) + "\n"
            output += json.dumps({"type": "result", "subtype": "success", "is_error": False}) + "\nCHECKPOINT_SEEDED"
            with patch.object(sys, "argv", argv), patch.dict("os.environ", {"SIFT_TEST_KEY": "secret-value"}), \
                    patch.object(checkpoint.shutil, "which", return_value="claude.exe"), \
                    patch.object(checkpoint.subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, output, "")), patch("builtins.print"):
                self.assertEqual(1, checkpoint.main())
            saved = json.loads((root / "seed.json").read_text(encoding="utf-8"))
            self.assertFalse(saved["seeded"])

    def test_seed_rejects_incomplete_or_reordered_chunks(self):
        packet = ("one\n" + "界" * CHUNK_BYTES + "\nlast\n").encode()
        chunks = checkpoint._chunk_packet(packet)
        self.assertEqual(packet, "".join(chunks).encode())
        self.assertTrue(all(len(chunk.encode()) <= CHUNK_BYTES for chunk in chunks))
        events = []
        for index, chunk in enumerate(chunks):
            identifier = f"call_{index}"
            events.extend([
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": identifier,
                     "name": f"mcp__sift_context__load_context_chunk_{index:03d}"}]}},
                {"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": identifier, "content": chunk}]}},
            ])
        audit = checkpoint._verify_chunk_events(events, packet)
        self.assertTrue(audit["checkpoint_content_verified"])
        self.assertEqual(hashlib.sha256(packet).hexdigest(), audit["checkpoint_context_sha256"])
        corrupted = list(events)
        corrupted[-1] = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"call_{len(chunks)-1}", "content": "changed"}]}}
        with self.assertRaisesRegex(ValueError, "sha256_mismatch"):
            checkpoint._verify_chunk_events(corrupted, packet)


if __name__ == "__main__":
    unittest.main()
