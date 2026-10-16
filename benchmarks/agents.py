"""Opt-in native Claude Code/Codex acceptance against copied local fixtures.

The caller configures gateway routing and Sift policy. This runner makes no
provider HTTP calls itself. Gold tests are copied only after the client exits.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid


SANDBOX_READY = "SIFT_SANDBOX_READY"
TOOL_TEST_PYTHON = "python" if os.name == "nt" else "python3"
SANDBOX_PROBE = """from pathlib import Path
import errno
import sys
inside, outside = (Path(name) for name in sys.argv[1:])
inside.write_text("sift readiness", encoding="utf-8")
inside.unlink()
try:
    outside.write_text("sift readiness", encoding="utf-8")
except OSError as error:
    if error.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
        raise
    print("SIFT_SANDBOX_READY")
else:
    outside.unlink()
    raise SystemExit("Sandbox permitted a write outside the workspace")
"""


def executable_for(client: str, explicit: str | None) -> str:
    candidate = explicit or shutil.which(client + (".exe" if os.name == "nt" else "")) or shutil.which(client)
    if not candidate:
        raise ValueError("Native client executable not found; supply --executable")
    path = Path(candidate).resolve()
    if os.name == "nt" and path.suffix.lower() != ".exe":
        # npm's Windows shim is not the sandboxed native executable.
        package = path.parent / "node_modules" / ("@openai/codex" if client == "codex" else "@anthropic-ai/claude-code")
        if client == "claude" and (package / "bin" / "claude.exe").is_file():
            return str(package / "bin" / "claude.exe")
        matches = list(package.glob("**/" + client + ".exe")) if package.is_dir() else []
        if len(matches) != 1:
            raise ValueError("Supply --executable pointing to the native .exe")
        path = matches[0]
    if not path.is_file():
        raise ValueError("Client executable does not exist")
    return str(path)


class WindowsJob:
    """Keep descendants owned even when the CLI exits before its children.

    Suspend before assignment so no child can escape the job during launch.
    All APIs are documented Windows kernel APIs, used only on Windows.
    """

    def __init__(self):
        import ctypes
        from ctypes import wintypes as w
        self.ctypes, self.w = ctypes, w
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
            "Thread32First": ([w.HANDLE, ctypes.c_void_p], w.BOOL),
            "Thread32Next": ([w.HANDLE, ctypes.c_void_p], w.BOOL),
            "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "ResumeThread": ([w.HANDLE], w.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            getattr(self.api, name).argtypes, getattr(self.api, name).restype = arguments, result

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", w.DWORD), ("minimum_ws", ctypes.c_size_t),
                        ("maximum_ws", ctypes.c_size_t), ("active_processes", w.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io_counters", ctypes.c_ulonglong * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def attach_and_resume(self, process):
        ctypes, w = self.ctypes, self.w
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

        class ThreadEntry(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("thread_id", w.DWORD),
                        ("owner_pid", w.DWORD), ("base_priority", w.LONG),
                        ("delta_priority", w.LONG), ("flags", w.DWORD)]

        snapshot_handle = self.api.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if snapshot_handle == w.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            present = self.api.Thread32First(snapshot_handle, ctypes.byref(entry))
            while present:
                if entry.owner_pid == process.pid:
                    thread = self.api.OpenThread(0x2, False, entry.thread_id)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if self.api.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        return
                    finally:
                        self.api.CloseHandle(thread)
                present = self.api.Thread32Next(snapshot_handle, ctypes.byref(entry))
            raise RuntimeError("Suspended client's initial thread not found")
        finally:
            self.api.CloseHandle(snapshot_handle)

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.api.CloseHandle(handle):
                raise self.ctypes.WinError(self.ctypes.get_last_error())


def terminate_tree(process: subprocess.Popen, job=None) -> None:
    if os.name == "nt":
        try:
            if process.poll() is None:
                killed = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                        capture_output=True, timeout=15)
                if killed.returncode and process.poll() is None:
                    raise RuntimeError("Could not terminate owned client process tree")
        finally:
            if job is not None:
                job.close()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_process(command: list[str], directory: Path, env: dict[str, str],
                *, text: str | None = None, timeout: int = 30) -> dict:
    started = time.perf_counter()
    start_utc = datetime.now(timezone.utc).isoformat()
    job = WindowsJob() if os.name == "nt" else None
    process = None
    try:
        process = subprocess.Popen(command, cwd=directory, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", errors="replace", start_new_session=os.name != "nt",
                                   creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 0x4)
                                   if os.name == "nt" else 0)  # CREATE_SUSPENDED before job assignment
        if job is not None:
            job.attach_and_resume(process)
    except BaseException:
        if job is not None:
            job.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=15)
        raise
    timed_out = False
    try:
        stdout, stderr = process.communicate(text, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_tree(process, job)
        stdout, stderr = process.communicate(timeout=15)
    except BaseException:
        terminate_tree(process, job)
        process.communicate(timeout=15)
        raise
    finally:
        if job is not None:
            job.close()
        elif os.name != "nt":
            terminate_tree(process)
    return {"exit_code": 124 if timed_out else process.returncode,
            "timed_out": timed_out, "seconds": time.perf_counter() - started,
            "start_utc": start_utc, "end_utc": datetime.now(timezone.utc).isoformat(),
            "stdout": stdout, "stderr": stderr}


def snapshot(directory: Path) -> dict[str, str]:
    result = {}
    for path in directory.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            result[path.relative_to(directory).as_posix()] = "symlink"
        elif path.is_file():
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify_frozen_manifest(case: Path, gold: Path, manifest_path: Path) -> dict:
    """Verify a predeclared case and post-run test set before client execution."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_case = manifest.get("input_sha256")
    expected_gold = manifest.get("acceptance_sha256")
    expected_evidence = manifest.get("evidence_sha256")
    if not isinstance(expected_case, dict) or not isinstance(expected_gold, dict):
        raise ValueError("Manifest needs input_sha256 and acceptance_sha256 maps")
    actual_case = snapshot(case)
    actual_gold = {
        path.relative_to(gold).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in gold.rglob("test_*.py")
        if path.is_file()
    }
    if actual_case != expected_case:
        raise ValueError("Case files do not match the frozen input_sha256 manifest")
    if actual_gold != expected_gold:
        raise ValueError("Gold tests do not match the frozen acceptance_sha256 manifest")
    evidence_path = gold / "evidence.json"
    actual_evidence = None
    if expected_evidence is not None:
        if not isinstance(expected_evidence, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_evidence):
            raise ValueError("evidence_sha256 must be one lowercase SHA-256 digest")
        if not evidence_path.is_file():
            raise ValueError("Frozen evidence annotations are missing")
        actual_evidence = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        if actual_evidence != expected_evidence:
            raise ValueError("Evidence annotations do not match the frozen evidence_sha256")
    elif evidence_path.exists():
        raise ValueError("Evidence annotations must be pinned in the frozen manifest")
    return {
        "frozen_at_utc": manifest.get("frozen_at_utc"),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "input_sha256": actual_case,
        "acceptance_sha256": actual_gold,
        "evidence_sha256": actual_evidence,
    }


def unit_tests(directory: Path, env: dict[str, str]) -> dict:
    result = run_process([sys.executable, "-m", "unittest", "discover", "-q"], directory, env)
    result["tests_observed"] = bool(re.search(r"Ran [1-9]\d* tests?", result["stdout"] + result["stderr"]))
    result["passed"] = result["exit_code"] == 0 and result["tests_observed"]
    return result


def sandbox_preflight(args, executable: str, root: Path, workspace: Path, env: dict[str, str]) -> dict:
    """Exercise native workspace permissions without a model or credentials."""
    outside_directory = root / "sandbox-outside"
    outside_directory.mkdir()
    identifier = uuid.uuid4().hex
    inside = workspace / (".sift-readiness-" + identifier)
    outside = outside_directory / (identifier + ".txt")
    command = [executable, "sandbox", "--permission-profile", ":workspace", "-C", str(workspace)]
    if os.name == "nt":
        command.extend(["-c", "windows.sandbox=" + json.dumps(args.windows_sandbox)])
    command.extend(["--", sys.executable, "-c", SANDBOX_PROBE, str(inside), str(outside)])
    probe_env = {name: value for name, value in env.items() if name not in {"SIFT_AGENT_API_KEY", "ANTHROPIC_API_KEY"}}
    try:
        result = run_process(command, workspace, probe_env, timeout=min(20, args.timeout))
        result["passed"] = (result["exit_code"] == 0 and not result["timed_out"]
                            and result["stdout"].strip() == SANDBOX_READY
                            and not inside.exists() and not outside.exists())
        return result
    finally:
        for path in (inside, outside):
            if path.is_file() or path.is_symlink():
                path.unlink()


def client_command(args, executable: str, editable: list[str]) -> list[str]:
    if args.client == "claude":
        shell = "PowerShell" if os.name == "nt" else "Bash"
        allowed = ["Read(./**)", *(f"Edit(./{name})" for name in editable),
                   f"{shell}({TOOL_TEST_PYTHON} -m unittest:*)",
                   f"{shell}({TOOL_TEST_PYTHON} reconcile.py:*)"]
        if "audit.py" in editable:
            allowed.append(f"{shell}({TOOL_TEST_PYTHON} audit.py:*)")
        return [executable, "-p", "--bare", "--no-session-persistence", "--setting-sources", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disable-slash-commands",
                "--tools", f"Read,Edit,{shell}", "--allowedTools", ",".join(allowed),
                "--permission-mode", "dontAsk", "--model", args.model, "--max-turns", "80",
                "--output-format", "stream-json", "--include-partial-messages", "--verbose"]
    settings = {
        "model_provider": "sift_eval", "model_context_window": 1_000_000,
        "model_auto_compact_token_limit": 950_000, "approval_policy": "never", "web_search": "disabled",
        "model_reasoning_effort": "low", "features.apps": False, "features.plugins": False,
        "features.multi_agent": False, "skills.max_context_tokens": 512,
        "shell_environment_policy.exclude": ["SIFT_AGENT_API_KEY"],
        "model_providers.sift_eval.name": "Sift evaluation endpoint",
        "model_providers.sift_eval.base_url": args.base_url,
        "model_providers.sift_eval.env_key": "SIFT_AGENT_API_KEY",
        "model_providers.sift_eval.wire_api": "responses",
        "model_providers.sift_eval.requires_openai_auth": False,
        "model_providers.sift_eval.supports_websockets": False,
        "model_providers.sift_eval.request_max_retries": 0,
        "model_providers.sift_eval.stream_max_retries": 0,
    }
    if os.name == "nt":
        settings["windows.sandbox"] = args.windows_sandbox
    command = [executable, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json",
               "--color", "never", "--skip-git-repo-check", "--sandbox", "workspace-write", "--model", args.model]
    for key, value in settings.items():
        command.extend(["-c", key + "=" + json.dumps(value)])
    return command + ["-"]


def unittest_command(command: str) -> bool:
    if not isinstance(command, str):
        return False
    command = command.strip()
    wrapper = re.fullmatch(
        r'''["']?(?:[A-Za-z]:[\\/][^"']*[\\/])?(?:powershell|pwsh)(?:\.exe)?["']?\s+(?:-NoProfile\s+)?-Command\s+(["'])(.*)\1''',
        command, re.I)
    if wrapper:
        command = wrapper.group(2).strip()
    else:
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        if len(parts) == 3 and parts[0] in {"bash", "/bin/bash", "sh", "/bin/sh"} and parts[1] in {"-c", "-lc"}:
            command = parts[2].strip()
    return re.fullmatch(
        r"(?:python(?:3(?:\.\d+)?)?(?:\.exe)?|py(?:\.exe)?)(?:\s+-3)?\s+-m\s+unittest"
        r"(?:\s+(?:-q|-v|discover))*(?:\s+2>&1)?",
        command) is not None


def event_evidence(client: str, stdout: str) -> dict:
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except json.JSONDecodeError:
            pass
    test_runs, calls, ttft, decode_tps = [], {}, [], []
    if client == "claude":
        active_stream = None
        for event in events:
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                    calls[block.get("id")] = block
                if block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
                    call = calls.get(block.get("tool_use_id"), {})
                    arguments = call.get("input")
                    if call.get("name") in ("Bash", "PowerShell") and isinstance(arguments, dict) and unittest_command(arguments.get("command")):
                        result = event.get("tool_use_result")
                        output = "\n".join(str(result.get(name, "")) for name in ("stdout", "stderr")) if isinstance(result, dict) else str(block.get("content", ""))
                        normal = isinstance(result, dict) and result.get("interrupted") is False
                        code = result.get("exit_code") if isinstance(result, dict) else None
                        prefix = re.match(r"Exit code (\d+)(?:\r?\n|$)", str(block.get("content", "")))
                        if prefix:
                            code = int(prefix.group(1))
                        test_runs.append((output, type(code) is int and code != 0 and block.get("is_error") is True,
                                          normal and block.get("is_error") is False
                                          and (code is None or type(code) is int and code == 0)))
            value = event.get("ttft_ms")
            detail = event.get("event")
            if event.get("type") == "stream_event" and isinstance(detail, dict):
                stream_type = detail.get("type")
                if stream_type == "message_start":
                    if type(value) in (float, int) and value >= 0:
                        ttft.append(value)
                    active_stream = {"first_delta": None, "last_delta": None, "output_tokens": None}
                elif active_stream is not None:
                    timestamp = event.get("timestamp")
                    instant = None
                    if isinstance(timestamp, str):
                        try:
                            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            if parsed.tzinfo is not None:
                                instant = parsed.astimezone(timezone.utc).timestamp()
                        except ValueError:
                            pass
                    if stream_type == "content_block_delta":
                        delta = detail.get("delta")
                        if isinstance(delta, dict) and any(
                            isinstance(delta.get(name), str) and delta.get(name)
                            for name in ("text", "thinking", "partial_json")
                        ) and instant is not None:
                            if active_stream["first_delta"] is None:
                                active_stream["first_delta"] = instant
                            active_stream["last_delta"] = instant
                    elif stream_type == "message_delta":
                        usage_detail = detail.get("usage")
                        output_count = usage_detail.get("output_tokens") if isinstance(usage_detail, dict) else None
                        if type(output_count) is int and output_count >= 0:
                            active_stream["output_tokens"] = output_count
                    elif stream_type == "message_stop":
                        first_delta, last_delta, output_count = (
                            active_stream["first_delta"], active_stream["last_delta"],
                            active_stream["output_tokens"],
                        )
                        if (first_delta is not None and last_delta is not None and
                                type(output_count) is int and output_count > 0 and last_delta > first_delta):
                            decode_tps.append(output_count / (last_delta - first_delta))
                        active_stream = None
        final = next((event for event in reversed(events) if event.get("type") == "result"), {})
        terminal = final.get("subtype") == "success" and final.get("is_error") is False
        usage = final.get("usage")
        cost = final.get("total_cost_usd")
        cost_source = ("Claude Code result.total_cost_usd"
                       if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0 else None)
        if cost_source is None:
            model_usage = final.get("modelUsage")
            if isinstance(model_usage, dict):
                costs = [item.get("costUSD") for item in model_usage.values()
                         if isinstance(item, dict) and type(item.get("costUSD")) in (int, float)
                         and math.isfinite(item["costUSD"]) and item["costUSD"] >= 0]
                if costs:
                    cost, cost_source = sum(costs), "Claude Code result.modelUsage.costUSD"
        if cost_source is None:
            cost = None
    else:
        for event in events:
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            if event.get("type") == "item.completed" and item.get("type") == "command_execution" and unittest_command(item.get("command", "")):
                code = item.get("exit_code")
                output = item.get("aggregated_output")
                test_runs.append((output if isinstance(output, str) else "",
                                  item.get("status") in ("completed", "failed") and type(code) is int and code != 0,
                                  item.get("status") == "completed" and type(code) is int and code == 0))
        terminal = any(event.get("type") == "turn.completed" for event in events) and not any(
            event.get("type") in ("turn.failed", "error") for event in events)
        usage = [event.get("usage") for event in events if event.get("type") == "turn.completed"]
        cost = None
        cost_source = None
    failed = False
    loop = False
    for output, native_failure, native_success in test_runs:
        if native_failure and "FAILED" in output and re.search(r"Ran [1-9]\d* tests?", output):
            failed = True
        if failed and native_success and re.search(r"(?m)^OK\s*$", output) and re.search(r"Ran [1-9]\d* tests?", output):
            loop = True
    return {"native_terminal_success": terminal, "test_tool_calls": len(test_runs),
            "observed_test_loop": loop if test_runs else None,
            "client_reported_usage": usage, "client_reported_ttft_ms": ttft,
            "mean_client_reported_ttft_ms": sum(ttft) / len(ttft) if ttft else None,
            "client_reported_decode_tokens_per_second": decode_tps,
            "mean_client_reported_decode_tokens_per_second": sum(decode_tps) / len(decode_tps) if decode_tps else None,
            "client_reported_cost_usd": cost, "client_reported_cost_source": cost_source}


def redact(value, secrets: list[str]):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {redact(name, secrets): redact(item, secrets) for name, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    return value


def save_report(directory: Path, report: dict, secrets: list[str]) -> str:
    serialized = json.dumps(redact(report, secrets), indent=2)
    (directory / "result.json").write_text(serialized + "\n", encoding="utf-8")
    return serialized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("claude", "codex"), required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True, help="Independent tests, copied after the client exits")
    parser.add_argument("--manifest", type=Path, help="Optional frozen fixture manifest to verify before client execution")
    parser.add_argument("--editable", action="append", required=True, help="Allowed relative existing file; repeat as needed")
    parser.add_argument("--allowed-output", action="append", default=[],
                        help="Predeclared relative file the client may create; repeat as needed")
    parser.add_argument("--base-url", required=True, help="OpenAI-compatible /v1 base URL; Claude uses its parent")
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--claude-max-output-tokens", type=int, default=4096,
                        help="Claude Code response cap; must not exceed the benchmark gateway cap")
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--executable")
    parser.add_argument("--windows-sandbox", choices=("elevated", "unelevated"))
    args = parser.parse_args()
    if args.client == "claude" and not 0 < args.claude_max_output_tokens <= 4096:
        parser.error("--claude-max-output-tokens must be between 1 and 4096")
    case, gold = args.case.resolve(), args.gold.resolve()
    key = os.environ.get(args.api_key_env)
    if not key or args.timeout <= 0 or not args.base_url.rstrip("/").endswith("/v1"):
        parser.error("Set the key environment variable, a positive timeout, and a /v1 base URL")
    if os.name == "nt" and args.client == "codex" and args.windows_sandbox is None:
        parser.error("Windows Codex requires explicit --windows-sandbox elevated|unelevated")
    if not case.is_dir() or not gold.is_dir() or gold.is_relative_to(case) or case.is_relative_to(gold):
        parser.error("Case and gold must be separate, nonoverlapping directories")
    if not (case / "README.md").is_file() or not any(gold.rglob("test_*.py")):
        parser.error("Case needs README.md and gold needs independent test_*.py files")
    if any(path.is_symlink() for directory in (case, gold) for path in directory.rglob("*")):
        parser.error("Fixture symlinks are unsupported")
    try:
        fixture_integrity = verify_frozen_manifest(case, gold, args.manifest.resolve()) if args.manifest else None
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"Frozen fixture verification failed: {error}")
    editable = []
    for name in args.editable:
        path = (case / name).resolve()
        if not path.is_relative_to(case) or not path.is_file() or path.suffix == ".py" and path.name.startswith("test_"):
            parser.error("Editable files must exist inside the case and cannot be test modules")
        editable.append(path.relative_to(case).as_posix())
    allowed_outputs = []
    for name in args.allowed_output:
        path = (case / name).resolve()
        if not path.is_relative_to(case) or path.exists():
            parser.error("Allowed outputs must be new files inside the case")
        relative = path.relative_to(case).as_posix()
        if relative in editable or relative in allowed_outputs:
            parser.error("Allowed outputs must be unique and cannot also be editable inputs")
        allowed_outputs.append(relative)
    gold_modules = list(gold.rglob("test_*.py"))
    if any((case / path.relative_to(gold)).exists() for path in gold_modules):
        parser.error("Gold filenames must not overwrite case files")
    executable = executable_for(args.client, args.executable)
    # A system-temp sibling can legitimately be writable under native policy.
    # Keep evidence and the sibling-denial probe outside those implicit roots.
    cache = Path.home() / ".cache" / "sift-agent-runs"
    cache.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="sift-agent-", dir=cache))
    workspace = root / "workspace"
    shutil.copytree(case, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "client-home").mkdir()
    env = {name: value for name, value in os.environ.items() if not name.startswith(("OPENAI_", "ANTHROPIC_", "CLAUDE_", "CODEX_"))
           and name not in {args.api_key_env, "SIFT_AGENT_API_KEY", "PYTHONPATH", "PYTHONHOME"}}
    test_env = dict(env)
    if args.client == "codex":
        env.update({"SIFT_AGENT_API_KEY": key, "CODEX_HOME": str(root / "client-home")})
    else:
        env.update({"CLAUDE_CONFIG_DIR": str(root / "client-home"), "ANTHROPIC_API_KEY": key,
                    "ANTHROPIC_BASE_URL": args.base_url.rstrip("/")[:-3],
                    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
                    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "95",
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(args.claude_max_output_tokens),
                    "MAX_THINKING_TOKENS": "512", "CLAUDE_CODE_MAX_RETRIES": "0",
                    "API_TIMEOUT_MS": str(min(90_000, args.timeout * 1000))})
    version_result = run_process([executable, "--version"], root, env, timeout=10)
    before = snapshot(workspace)
    # Baseline tests may create the task's deliverable. Keep those side effects
    # out of the agent's starting workspace and out of change accounting.
    baseline_workspace = root / "baseline-check"
    shutil.copytree(workspace, baseline_workspace)
    baseline = unit_tests(baseline_workspace, test_env)
    report = {"client": args.client, "model": args.model, "client_version": version_result["stdout"].strip(),
              "python_version": sys.version, "timeout": args.timeout, "workspace": str(workspace),
              "client_output_limit_tokens": args.claude_max_output_tokens if args.client == "claude" else None,
              "editable": editable, "allowed_outputs": allowed_outputs,
              "baseline_workspace": str(baseline_workspace), "fixture_integrity": fixture_integrity,
              "baseline": baseline, "accepted": False,
              "usage_note": "Client-reported usage and TTFT are not independently verified provider measurements."}
    secrets = list({key, json.dumps(key, ensure_ascii=False)[1:-1], json.dumps(key)[1:-1]})
    save_report(root, report, secrets)  # Preflight persistence before a paid native run.
    if args.client == "codex" and version_result["exit_code"] == 0 and not baseline["passed"] and baseline["tests_observed"] and not baseline["timed_out"]:
        try:
            report["sandbox_preflight"] = sandbox_preflight(args, executable, root, workspace, env)
        except Exception as error:
            report["sandbox_preflight"] = {"passed": False, "error_type": type(error).__name__, "error": str(error)}
        save_report(root, report, secrets)
    if baseline["passed"] or not baseline["tests_observed"] or baseline["timed_out"]:
        report["failure"] = "Fixture must have an observed failing baseline before client execution"
    elif version_result["exit_code"] != 0:
        report["failure"] = "Native client version check failed"
    elif args.client == "codex" and not report["sandbox_preflight"]["passed"]:
        report["failure"] = "Model-free native sandbox readiness failed; model execution was not started"
    else:
        prompt = (case / "README.md").read_text(encoding="utf-8") + "\n\nEdit only: " + ", ".join(editable)
        if allowed_outputs:
            prompt += "\nYou may create these declared output files: " + ", ".join(allowed_outputs)
        if "audit.py" in editable and "report.json" in allowed_outputs:
            prompt += (f"\nAfter the final test run, execute `{TOOL_TEST_PYTHON} audit.py` as a separate tool command "
                       "to create the required report.json in the workspace, then verify that it exists.")
        prompt += (f"\nUse {TOOL_TEST_PYTHON} for Python test commands on this host. "
                   f"Before editing and after editing, submit exactly `{TOOL_TEST_PYTHON} -m unittest -q` "
                   "as its own tool command. Use the tool's workdir field when available; the current directory is already the workspace. "
                   "Do not combine that command with cd, echo, cat, pipes, semicolons, &&, ||, or exit-status wrappers. "
                   "The baseline test failure is expected: preserve its native nonzero exit status and continue the task. "
                   "Preserve all other files. Report actual test outcomes.")
        native = run_process(client_command(args, executable, editable), workspace, env, text=prompt, timeout=args.timeout)
        report["native"] = native
        report["phase"] = "native_completed"
        (root / "native.stdout.jsonl").write_text(redact(native["stdout"], secrets), encoding="utf-8")
        (root / "native.stderr").write_text(redact(native["stderr"], secrets), encoding="utf-8")
        save_report(root, report, secrets)  # Keep native evidence before parsing or tests can fail.
        try:
            report.update(event_evidence(args.client, native["stdout"]))
        except Exception as error:
            report["harness_failure"] = {"stage": "parse_native_events", "type": type(error).__name__, "message": str(error)}
            report.update({"native_terminal_success": None, "observed_test_loop": None,
                           "client_reported_usage": None, "client_reported_ttft_ms": [],
                           "mean_client_reported_ttft_ms": None,
                           "client_reported_decode_tokens_per_second": [],
                           "mean_client_reported_decode_tokens_per_second": None,
                           "client_reported_cost_usd": None,
                           "client_reported_cost_source": None})
            report["phase"] = "harness_failed"
            save_report(root, report, secrets)
        after = snapshot(workspace)
        changed = sorted(name for name in editable if before[name] != after.get(name))
        unauthorized = sorted(name for name in before if name not in editable and after.get(name) != before[name])
        created_outputs = sorted(name for name in allowed_outputs if name in after and name not in before)
        missing_outputs = sorted(set(allowed_outputs) - set(created_outputs))
        extra = sorted(after.keys() - before.keys() - set(allowed_outputs))
        symlinks = sorted(name for name, value in after.items() if value == "symlink")
        report.update({"changed_files": changed, "created_outputs": created_outputs,
                       "missing_outputs": missing_outputs, "unauthorized_changes": unauthorized, "extra_files": extra,
                       "symlinks": symlinks, "artifact_hashes_before_redaction": after})
        # Test separate snapshots, so tests cannot repair the delivered artifact.
        if symlinks:
            report.update({"visible": {"passed": False}, "gold": {"passed": False}})
        else:
            visible_copy = root / "visible-check"
            shutil.copytree(workspace, visible_copy)
            report["visible"] = unit_tests(visible_copy, test_env)
            gold_copy = root / "gold-check"
            shutil.copytree(workspace, gold_copy)
            for source in gold_modules:
                destination = gold_copy / source.relative_to(gold)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            report["gold"] = unit_tests(gold_copy, test_env)
        report["accepted"] = (not report.get("harness_failure") and native["exit_code"] == 0 and report["native_terminal_success"]
                              and bool(changed) and not missing_outputs and not unauthorized and not extra and not symlinks
                              and report["observed_test_loop"] is True
                              and report["visible"]["passed"] and report["gold"]["passed"])
    # Trace files and report are outside the agent workspace and never enter tests.
    redacted_files = []
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            clean = data
            for secret in secrets:
                clean = clean.replace(secret.encode(), b"[REDACTED]")
            if data != clean:
                redacted_files.append(path.relative_to(root).as_posix())
                path.write_bytes(clean)
    report["redacted_files"] = redacted_files
    if any(name.startswith("workspace/") for name in redacted_files):
        report["accepted"] = False
        report["failure"] = "Credential found in delivered workspace; artifact was redacted"
    serialized = save_report(root, report, secrets)
    print(serialized)
    print("evidence", root)
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
