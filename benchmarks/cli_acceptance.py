"""Opt-in native CLI acceptance through the installed Sift LiteLLM adapter.

Only synthetic fixture data is used. No shared gateway configuration is changed.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
from importlib.metadata import version
import json
import os
import re
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse


def inject_history(data: dict, lines: int = 8000) -> dict:
    """Add older synthetic evidence without changing current instructions/tools."""
    result = deepcopy(data)
    responses = "messages" not in result
    messages = result["input"] if responses else result["messages"]
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
        result["input"] = messages
    index = 0
    while index < len(messages) and messages[index].get("role") in {"system", "developer"}:
        index += 1
    history = [f"routine archive record {n}: completed ordinary build with no changes" for n in range(lines)]
    history[lines // 2] = "APPROVED deployment setting: acceptance_delay_seconds=37; retain this exact approved value."
    messages[index:index] = [
        {"role": "user", "content": "Archived deployment evidence:\n" + "\n".join(history)},
        {"role": "assistant", "content": "The archived deployment evidence is recorded."},
    ]
    return result


def native_evidence(client: str, events: list[dict]) -> dict:
    calls, completed = {}, {}
    outputs = {}
    shell_reads = {}
    terminal = False
    errors = []
    for index, event in enumerate(events):
        if event.get("type") == "error":
            errors.append(event.get("error", "native error"))
        if client == "claude":
            message = event.get("message") or {}
            for block in message.get("content", []) if isinstance(message, dict) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    calls[block["id"]] = {"name": block.get("name", ""), "input": block.get("input") or {}, "index": index}
                if block.get("type") == "tool_result":
                    completed[block["tool_use_id"]] = not block.get("is_error", False)
                    outputs[block["tool_use_id"]] = str(block.get("content", ""))
            if event.get("type") == "result":
                terminal = event.get("subtype") == "success" and not event.get("is_error", False)
        elif client == "codex":
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") == "command_execution":
                key = item["id"]
                command, output = item.get("command", ""), item.get("aggregated_output", "")
                calls[key] = {"name": "Bash", "input": {"command": command}, "index": index}
                completed[key] = item.get("exit_code") == 0
                outputs[key] = output
                # The native CLI exposes file reads as command executions.
                if completed[key] and re.search(r"Get-Content|\bcat\b|read_text", command):
                    for filename in ("task.py", "test_task.py", "expenses.csv"):
                        if re.search(r"(?<![\w.])" + re.escape(filename) + r"(?![\w.])", command):
                            shell_reads.setdefault(filename, index)
            if event.get("type") == "item.completed" and item.get("type") == "file_change":
                key = item["id"]
                calls[key] = {"name": "Edit", "input": {"paths": [c.get("path", "") for c in item.get("changes", [])]}, "index": index}
                completed[key] = item.get("status") == "completed"
            if event.get("type") == "turn.completed":
                terminal = True
            if event.get("type") == "turn.failed":
                terminal = False
                errors.append("turn.failed")
        else:
            part = event.get("part") or {}
            if event.get("type") == "tool_use" and part.get("type") == "tool":
                call_id = part.get("callID", part.get("id"))
                calls[call_id] = {"name": part.get("tool", ""), "input": (part.get("state") or {}).get("input") or {}, "index": index}
                state = part.get("state") or {}
                if state.get("status") in {"completed", "error"}:
                    exit_code = (state.get("metadata") or {}).get("exit")
                    completed[call_id] = state.get("status") == "completed" and exit_code in (None, 0)
                    outputs[call_id] = str(state.get("output", ""))
            if event.get("type") == "step_finish":
                terminal = part.get("reason") == "stop"
    successful = [calls[key]["name"] for key, ok in completed.items() if ok and key in calls]
    read_files, written_files, first_writes, baselines, finals = dict(shell_reads), {}, {}, [], []
    for key, call in calls.items():
        name, arguments, index = call["name"].lower(), call["input"], call["index"]
        paths = arguments.get("paths") or [arguments.get("file_path", arguments.get("filePath", arguments.get("path", "")))]
        for path in paths:
            filename = str(path).replace("\\", "/").rsplit("/", 1)[-1]
            if completed.get(key):
                if name == "read" and filename in {"task.py", "test_task.py", "expenses.csv"}:
                    read_files.setdefault(filename, index)
                if name in {"write", "edit"} and filename in {"task.py", "evidence.json", "daily-report.json"}:
                    written_files[filename] = index
                    first_writes.setdefault(filename, index)
        command = arguments.get("command", "")
        if isinstance(command, str):
            wrapper = re.fullmatch(r'''["'].*?(?:pwsh|powershell)\.exe["']\s+(?:-NoProfile\s+)?-Command\s+(["'])(.*)\1''', command, re.I | re.S)
            if wrapper:
                command = wrapper.group(2).strip()
        if name in {"bash", "powershell"} and isinstance(command, str) and re.fullmatch(
            r'\s*(?:&\s*)?(?:"[^"\r\n]+"|[^\s;&|]+)\s+-m\s+unittest\s+-q\s*', command,
        ):
            output = outputs.get(key, "")
            if key in completed and not completed[key] and "FAILED" in output:
                baselines.append(index)
            if completed.get(key) and "Ran 2 tests" in output and re.search(r"\bOK\b", output):
                finals.append(index)
    required_reads, required_writes = {"task.py", "test_task.py"}, {"task.py", "evidence.json"}
    ordered = (required_reads <= set(read_files) and required_writes <= set(written_files)
               and any(max(read_files[name] for name in required_reads) < baseline
                       < min(first_writes[name] for name in required_writes)
                       and max(written_files[name] for name in required_writes) < final
                       for baseline in baselines for final in finals))
    return {"terminal_success": terminal and not errors, "calls": len(calls),
            "completed": len(completed), "successful_tools": successful,
            "unmatched_results": len(set(completed) - set(calls)), "native_errors": len(errors),
            "read_files": sorted(read_files), "written_files": sorted(written_files),
            "baseline_failed": bool(baselines), "final_passed": bool(finals), "workflow_ordered": bool(ordered)}


def historical_gold_retained(messages: list[dict], source_index: int) -> bool:
    """Require the injected source's excerpt, never a later agent echo."""
    marker = f"[message {source_index} user] "
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(block.get("text", "") for block in content if isinstance(block, dict)
                                and block.get("type") in {"text", "input_text"})
        if (message.get("role") == "user" and isinstance(content, str)
                and content.startswith("Earlier conversation, lossily excerpted")):
            if any(line.startswith(marker) and "acceptance_delay_seconds=37" in line for line in content.splitlines()):
                return True
    return False


def classify_upstream_error(status: int, body: bytes):
    if status != 500:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else error
    if (isinstance(message, str)
            and message.startswith(("litellm.APIConnectionError:", "APIConnectionError:"))
            and "OpenrouterException - Connection closed." in message):
        return "provider_connection_closed"
    return None


class RouteCounter:
    def _count_pre_call_check_tokens(self, messages, input, request_kwargs):
        from litellm import Router
        return Router._count_pre_call_check_tokens(self, messages, input, request_kwargs)


def make_app(upstream: str, key: str, model: str, target: int, audits: list[dict], capture_directory: Path | None = None):
    import httpx
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse
    from sift.litellm_proxy import SiftLiteLLMHook
    app = FastAPI()
    hook = SiftLiteLLMHook({model: target})

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": model, "object": "model"}]}

    @app.post("/v1/{endpoint:path}")
    async def forward(endpoint: str, request: Request):
        from fastapi import HTTPException
        received_at = time.monotonic()
        if endpoint not in {"messages", "chat/completions", "responses"}:
            raise HTTPException(404, "Unsupported acceptance protocol")
        original = await request.json()
        data = inject_history(original)
        data["model"] = model
        call_type = {"messages": "anthropic_messages", "responses": "aresponses"}.get(endpoint, "acompletion")
        original_messages = original.get("messages", original.get("input", []))
        if isinstance(original_messages, str):
            original_messages = [{"role": "user", "content": original_messages}]
        shapes = [{"role": m.get("role", m.get("type")), "keys": sorted(m),
                   **({"type": m["type"]} if "type" in m else {})} for m in original_messages]
        try:
            compacted = await hook._compact(RouteCounter(), data, call_type=call_type, target=target)
        except HTTPException as error:
            audits.append({"protocol": call_type, "input_shapes": shapes,
                           "sift_error": (error.headers or {}).get("x-sift-error-code"),
                           "status": error.status_code})
            raise
        audit = compacted.pop("metadata", {}).get("sift", {})
        # LiteLLM may choose a different internal metadata bucket.
        audit = compacted.pop("litellm_metadata", {}).get("sift", audit)
        output_messages = compacted.get("messages", compacted.get("input", []))
        # The default core's excerpt indexes are relative to the eligible
        # historical span, after the immutable instruction prefix. Our
        # injected archive is always the first message in that span.
        history_index = 0
        original_sealed = [item for item in original_messages
                           if item.get("type") == "reasoning" and item.get("encrypted_content")]
        retained_sealed = [item for item in output_messages
                           if item.get("type") == "reasoning" and item.get("encrypted_content")]
        last_user = max((i for i, item in enumerate(original_messages) if item.get("role") == "user"), default=-1)
        active_sealed = [item for item in original_messages[last_user + 1:]
                         if item.get("type") == "reasoning" and item.get("encrypted_content")]
        entry = {**audit, "protocol": call_type, "input_shapes": shapes,
                       "request_received_at": received_at,
                       "request_sha256": hashlib.sha256((endpoint + "\0" + json.dumps(original, sort_keys=True)).encode("utf8")).hexdigest(),
                       "gold_retained": historical_gold_retained(output_messages, history_index),
                       "sealed_items_retained": len(retained_sealed),
                       "sealed_items_unchanged": all(item in original_sealed for item in retained_sealed),
                       "latest_active_sealed_retained": not active_sealed or active_sealed[-1] in retained_sealed,
                       "catalogs_unchanged": [item for item in original_messages if item.get("type") == "additional_tools"]
                       == [item for item in output_messages if item.get("type") == "additional_tools"],
                       "tool_results": sum(m.get("role") == "tool" or m.get("type") in {"function_call_output", "custom_tool_call_output"} or any(
                           isinstance(b, dict) and b.get("type") == "tool_result"
                           for b in (m.get("content") if isinstance(m.get("content"), list) else [])
                       ) for m in original_messages)}
        audits.append(entry)
        if capture_directory is not None and not entry["gold_retained"]:
            # Task-owned synthetic diagnostics only; never copy this raw
            # native fixture into a public report without minimizing it.
            capture_directory.mkdir(parents=True, exist_ok=True)
            (capture_directory / (entry["request_sha256"] + ".json")).write_text(json.dumps({
                "original": original, "compacted": compacted, "target": target,
                "call_type": call_type, "audit": entry}, ensure_ascii=False), encoding="utf8")
        headers = {"Authorization": f"Bearer {key}", "x-api-key": key,
                   "anthropic-version": request.headers.get("anthropic-version", "2023-06-01")}
        client = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), follow_redirects=False)
        try:
            response = await client.send(client.build_request(
                "POST", upstream.rstrip("/") + "/" + endpoint, json=compacted, headers=headers,
            ), stream=True)
        except BaseException:
            await client.aclose()
            raise
        entry["upstream_status"] = response.status_code

        async def body():
            error_prefix = bytearray()
            try:
                async for chunk in response.aiter_raw():
                    if response.status_code != 200:
                        error_prefix.extend(chunk[:max(0, 8192-len(error_prefix))])
                    yield chunk
            finally:
                entry["upstream_transport_error"] = classify_upstream_error(response.status_code, bytes(error_prefix))
                entry["response_finished_at"] = time.monotonic()
                await response.aclose()
                await client.aclose()

        return StreamingResponse(body(), status_code=response.status_code,
                                 media_type=response.headers.get("content-type", "application/json"))
    return app


def executable(client: str) -> str:
    if client == "codex":
        # Resolve the native binary behind the user's CLI, not a different
        # Desktop alpha binary that may also be present on PATH.
        shim = shutil.which("codex.cmd" if os.name == "nt" else "codex")
        if not shim:
            raise ValueError("codex is not installed")
        if os.name != "nt":
            return shim
        matches = list((Path(shim).parent / "node_modules/@openai/codex").glob("**/codex.exe"))
        if len(matches) != 1:
            raise ValueError("Cannot uniquely resolve the native binary behind codex.cmd")
        return str(matches[0])
    candidate = shutil.which(client + ".cmd" if os.name == "nt" else client)
    if not candidate:
        raise ValueError(f"{client} is not installed")
    if os.name == "nt":
        package = "opencode-ai" if client == "opencode" else "@anthropic-ai/claude-code"
        native = Path(candidate).parent / "node_modules" / package / "bin" / (client + ".exe")
        if not native.is_file():
            raise ValueError(f"Native client binary missing: {native}")
        return str(native)
    return candidate


def child_command(client: str, exe: str, home: Path, base: str, model: str, prompt: str,
                  *, persist: bool = False, session_id: str | None = None):
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(("OPENAI_", "ANTHROPIC_", "CLAUDE_", "OPENCODE_", "CODEX_"))
           and not any(word in name.upper() for word in ("KEY", "TOKEN", "SECRET"))}
    home.mkdir(exist_ok=persist)
    env.update({"HOME": str(home), "USERPROFILE": str(home),
                "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
                "XDG_CACHE_HOME": str(home / "cache"), "XDG_STATE_HOME": str(home / "state")})
    if client == "claude":
        env.update({"CLAUDE_CONFIG_DIR": str(home), "ANTHROPIC_API_KEY": "sift-loopback-only",
                    "ANTHROPIC_BASE_URL": base.removesuffix("/v1"), "ANTHROPIC_MODEL": model,
                    "CLAUDE_CODE_DISABLE_1M_CONTEXT": "1", "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "256000",
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096", "MAX_THINKING_TOKENS": "512",
                    "CLAUDE_CODE_MAX_RETRIES": "0", "API_TIMEOUT_MS": "90000"})
        for tier in ("SONNET", "OPUS", "HAIKU"):
            env[f"ANTHROPIC_DEFAULT_{tier}_MODEL"] = model
        command = [exe, "-p", "--bare", "--setting-sources", "", "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}', "--model", model,
                "--tools", "Read,Edit,Bash,PowerShell", "--allowedTools", "Read,Edit,Bash,PowerShell",
                "--permission-mode", "dontAsk", "--max-turns", "15", "--output-format", "stream-json",
                "--verbose"]
        command += ["--resume", session_id] if session_id else ([] if persist else ["--no-session-persistence"])
        return command + [prompt], env
    if client == "codex":
        # Windows' native restricted-token runner needs the real OS user
        # profile. Isolate Codex state with CODEX_HOME instead of pretending
        # that a fixture directory is a Windows user profile.
        env["USERPROFILE"] = os.environ.get("USERPROFILE", str(Path.home()))
        env["HOME"] = os.environ.get("HOME") or env["USERPROFILE"]
        # Reuse the already-provisioned Windows sandbox runtime; fresh homes
        # cannot launch its restricted-token helper on this host. Config is
        # ignored below and provider/catalog settings remain process-local.
        runtime_home = Path(env["USERPROFILE"]) / ".codex" if os.name == "nt" else home
        env.update({"CODEX_HOME": str(runtime_home), "SIFT_LOCAL_KEY": "sift-loopback-only"})
        catalog = home / "models.json"
        if not catalog.exists():
            bundled = json.loads(subprocess.check_output([exe, "debug", "models", "--bundled"], env=env, timeout=15))
            template = next((entry for entry in bundled["models"] if entry["slug"] == "gpt-5.6-luna"), bundled["models"][0])
            default = deepcopy(template)
            default.update(slug=model, display_name=model)
            bundled["models"].append(default)
            catalog.write_text(json.dumps(bundled), encoding="utf-8")
        settings = {
            "model_provider": "sift_acceptance", "model_catalog_json": str(catalog),
            "model_context_window": 256000, "model_auto_compact_token_limit": 240000,
            "approval_policy": "never", "features.shell_tool": True, "features.apps": False,
            "sandbox_mode": "workspace-write",
            "features.plugins": False, "features.multi_agent": False,
            "model_providers.sift_acceptance.name": "Sift acceptance",
            "model_providers.sift_acceptance.base_url": base,
            "model_providers.sift_acceptance.env_key": "SIFT_LOCAL_KEY",
            "model_providers.sift_acceptance.wire_api": "responses",
            "model_providers.sift_acceptance.requires_openai_auth": False,
            "model_providers.sift_acceptance.supports_websockets": False,
            "model_providers.sift_acceptance.request_max_retries": 0,
            "model_providers.sift_acceptance.stream_max_retries": 0,
        }
        if os.name == "nt":
            settings["windows.sandbox"] = "unelevated"
        command = [exe, "--cd", str(home.parent / "workspace"), "exec", "--ignore-user-config", "--ignore-rules"]
        if session_id:
            command += ["resume", session_id]
        else:
            command += ["--skip-git-repo-check", "--sandbox", "workspace-write"]
        command += ["--json", "--model", model]
        for name, value in settings.items():
            command += ["-c", name + "=" + json.dumps(value)]
        return command + [prompt], env
    config = {"$schema": "https://opencode.ai/config.json", "model": f"sift/{model}",
              "small_model": f"sift/{model}", "enabled_providers": ["sift"],
              "provider": {"sift": {"npm": "@ai-sdk/openai-compatible", "name": "Sift acceptance",
                  "options": {"baseURL": base, "apiKey": "sift-loopback-only"},
                  "models": {model: {"name": model, "limit": {"context": 256000, "output": 4096}}}}},
              "permission": {"*": "deny", "read": "allow", "edit": "allow", "write": "allow",
                             "bash": "allow", "glob": "allow", "grep": "allow"}}
    env.update({"OPENCODE_CONFIG_CONTENT": json.dumps(config), "OPENCODE_CONFIG_DIR": str(home),
                "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true"})
    command = [exe, "run", "--pure", "--format", "json", "--model", f"sift/{model}"]
    if session_id:
        command += ["--session", session_id]
    return command + [prompt], env


def codex_sandbox_readiness(exe, root, workspace, env):
    from types import SimpleNamespace
    from benchmarks.agents import sandbox_preflight
    return sandbox_preflight(SimpleNamespace(windows_sandbox="unelevated", timeout=20), exe, root, workspace, env)


def run(args) -> dict:
    import uvicorn
    parsed = urlparse(args.upstream_base_url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != 4000 or parsed.path != "/v1":
        raise ValueError("Live acceptance is restricted to http://127.0.0.1:4000/v1")
    key = os.environ[args.api_key_env]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / "workspace"
    workspace.mkdir()
    (workspace / "task.py").write_text("def clamp(value):\n    return value\n", encoding="utf-8")
    (workspace / "evidence.json").write_text("{}\n", encoding="utf-8")
    (workspace / "test_task.py").write_text(
        "import json, unittest\nfrom pathlib import Path\nfrom task import clamp\n"
        "class Checks(unittest.TestCase):\n"
        "    def test_bounds(self):\n        self.assertEqual([clamp(x) for x in [-5,0,3,100,105]], [0,0,3,100,100])\n"
        "    def test_evidence(self):\n        self.assertIsInstance(json.loads(Path('evidence.json').read_text())['acceptance_delay_seconds'], int)\n",
        encoding="utf-8")
    gold_hash = hashlib.sha256((workspace / "test_task.py").read_bytes()).hexdigest()
    baseline = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=workspace, capture_output=True, text=True)
    prompt = ("You are the leaf coding agent in an isolated synthetic acceptance workspace. Do not delegate or use network. "
              "Use the native Read tool separately on task.py and test_task.py, then run the baseline tests as a standalone shell tool call (failure is expected). Fix clamp to bound "
              "values inclusively to 0..100, and create evidence.json with acceptance_delay_seconds from the APPROVED "
              "archived deployment evidence in conversation history. Do not guess this value. Do not edit test_task.py. "
              "Use native Edit/Write tools for task.py and evidence.json, not shell redirection. "
              f"For BOTH baseline and final tests, run exactly \"{Path(sys.executable).as_posix()}\" -m unittest -q "
              "as its own shell call (PowerShell may prefix &). No cd, pipes, redirection, semicolons, or combined commands. "
              "The working directory is already correct. Read both files before the baseline, make edits after its failure, "
              "run final tests after writing both files, then report actual outcomes.")
    if args.client == "codex":
        prompt = prompt.replace("Use the native Read tool separately on", "Use native shell reads on")
        prompt = prompt.replace("Use native Edit/Write tools", "Use native apply_patch")
    elif args.client == "claude":
        prompt = prompt.replace("create evidence.json", "populate the existing evidence.json stub")
        prompt = prompt.replace("native Edit/Write tools", "native Edit tools (Read each file before Edit; Write is unavailable)")
    audits = []
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(make_app(args.upstream_base_url, key, args.model, args.target, audits),
                                         log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    process = None
    started = time.monotonic()
    stdout, stderr, timed_out = "", "", False
    sandbox_readiness = None
    try:
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(.02)
        if not server.started:
            raise RuntimeError("Acceptance proxy did not start")
        exe = executable(args.client)
        command, env = child_command(args.client, exe, output / "client-home", f"http://127.0.0.1:{port}/v1", args.model, prompt)
        if args.client == "codex":
            sandbox_readiness = codex_sandbox_readiness(exe, output, workspace, env)
            if not sandbox_readiness["passed"]:
                raise RuntimeError("Codex sandbox readiness failed before inference")
        client_version = subprocess.check_output([exe, "--version"], text=True, timeout=10).strip()
        process = subprocess.Popen(command, cwd=workspace, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        try:
            stdout, stderr = process.communicate(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.kill()
            stdout, stderr = process.communicate(timeout=15)
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()
    stdout, stderr = stdout.replace(key, "[REDACTED]"), stderr.replace(key, "[REDACTED]")
    (output / "native.jsonl").write_text(stdout, encoding="utf-8")
    (output / "native.stderr.txt").write_text(stderr, encoding="utf-8")
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except ValueError:
            pass
    native = native_evidence(args.client, events)
    final = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=workspace, capture_output=True, text=True, timeout=15)
    (output / "final-tests.txt").write_text(final.stdout + final.stderr, encoding="utf-8")
    try:
        evidence = json.loads((workspace / "evidence.json").read_text())
        gold_passed = isinstance(evidence, dict) and evidence.get("acceptance_delay_seconds") == 37
    except (OSError, ValueError):
        gold_passed = False
    compacted = [a for a in audits if a.get("compacted") is True]
    from sift import core, litellm_proxy
    passed = (not timed_out and process.returncode == 0 and baseline.returncode != 0 and final.returncode == 0
              and gold_passed and gold_hash == hashlib.sha256((workspace / "test_task.py").read_bytes()).hexdigest()
              and native["terminal_success"] and native["workflow_ordered"]
              and native["unmatched_results"] == 0 and native["completed"] == native["calls"] and bool(compacted)
              and any(a["tool_results"] for a in audits)
              and all(a["gold_retained"] and a["forwarded_tokens"] <= args.target for a in compacted)
              and all(a.get("sealed_items_unchanged") and a.get("latest_active_sealed_retained")
                      and a.get("catalogs_unchanged") for a in audits)
              and all(a.get("upstream_status") == 200 for a in audits))
    receipt = {"accepted": passed, "client": args.client, "client_version": client_version,
               "upstream": args.upstream_base_url, "model": args.model, "target": args.target,
               "native": native, "audits": audits, "baseline_exit": baseline.returncode,
               "final_tests_exit": final.returncode, "client_exit": process.returncode,
               "hidden_gold_passed": gold_passed,
               "sandbox_readiness": sandbox_readiness,
               "timed_out": timed_out, "elapsed_seconds": round(time.monotonic() - started, 2),
               "sift_version": version("sift-context"),
               "source_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in {
                   "benchmarks/cli_acceptance.py": Path(__file__).resolve(),
                   "sift/litellm_proxy.py": Path(litellm_proxy.__file__),
                   "sift/core.py": Path(core.__file__),
               }.items()}}
    (output / "result.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("claude", "opencode", "codex"), required=True)
    parser.add_argument("--upstream-base-url", default="http://127.0.0.1:4000/v1")
    parser.add_argument("--model", default="default")
    parser.add_argument("--api-key-env", default="SIFT_ACCEPTANCE_API_KEY")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", type=int, default=32768)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({key: value for key, value in result.items() if key not in {"audits", "source_sha256"}}, indent=2))
    raise SystemExit(0 if result["accepted"] else 1)


if __name__ == "__main__":
    main()
