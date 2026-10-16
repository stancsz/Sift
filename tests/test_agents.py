"""Agent harness event compatibility and paid-run evidence recovery boundaries."""

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "sift_benchmark_agents", Path(__file__).resolve().parents[1] / "benchmarks" / "agents.py")
agents = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agents)


class AgentEvidenceTests(unittest.TestCase):
    def test_unittest_command_accepts_only_supported_command_with_terminal_stderr_redirect(self):
        for command in (
            "python -m unittest -q 2>&1",
            "python3 -m unittest discover -v 2>&1",
            "py -3 -m unittest -q",
            "/bin/bash -lc 'python -m unittest -q 2>&1'",
        ):
            with self.subTest(command=command):
                self.assertTrue(agents.unittest_command(command))
        for command in (
            "python -m unittest -q 2>&1 && python audit.py",
            "python -m unittest -q; python audit.py",
            "python -m unittest -q 2>&1 | tee tests.log",
            "python -c 'import unittest'",
        ):
            with self.subTest(command=command):
                self.assertFalse(agents.unittest_command(command))

    def test_predeclared_fixture_hashes_survive_checkout(self):
        base = Path(__file__).resolve().parents[1] / "benchmarks"
        manifest = json.loads((base / "agent_gold" / "manifest.json").read_text(encoding="utf-8"))
        for name, expected in manifest["sha256"].items():
            with self.subTest(fixture=name):
                self.assertEqual(hashlib.sha256((base / name).read_bytes()).hexdigest(), expected)
        build = json.loads((base / "agent_gold" / "build_planner" / "manifest.json").read_text(encoding="utf-8"))
        roots = {"case": base / "agent_cases" / "build_planner", "gold": base / "agent_gold" / "build_planner"}
        for name, expected in build["sha256"].items():
            category, relative = name.split("/", 1)
            with self.subTest(fixture=name):
                self.assertEqual(hashlib.sha256((roots[category] / relative).read_bytes()).hexdigest(), expected)

    def test_frozen_manifest_pins_case_and_postrun_acceptance_files(self):
        with tempfile.TemporaryDirectory(prefix="sift-frozen-fixture-") as temporary:
            root = Path(temporary)
            case, gold = root / "case", root / "gold"
            case.mkdir()
            gold.mkdir()
            (case / "README.md").write_text("task", encoding="utf-8")
            (case / "input.csv").write_text("id\n1\n", encoding="utf-8")
            (gold / "test_gold.py").write_text("import unittest\n", encoding="utf-8")
            def digest(path):
                return hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "frozen_at_utc": "2026-10-15T00:00:00Z",
                "input_sha256": {name: digest(case / name) for name in ("README.md", "input.csv")},
                "acceptance_sha256": {"test_gold.py": digest(gold / "test_gold.py")},
            }), encoding="utf-8")
            verified = agents.verify_frozen_manifest(case, gold, manifest)
            self.assertEqual(verified["input_sha256"]["input.csv"], digest(case / "input.csv"))
            self.assertEqual(verified["acceptance_sha256"]["test_gold.py"], digest(gold / "test_gold.py"))

            (gold / "test_gold.py").write_text("# changed after freeze\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "acceptance_sha256"):
                agents.verify_frozen_manifest(case, gold, manifest)

    def test_frozen_manifest_pins_evidence_annotations_when_present(self):
        with tempfile.TemporaryDirectory(prefix="sift-frozen-evidence-") as temporary:
            root = Path(temporary)
            case, gold = root / "agent_cases" / "fixture_one", root / "agent_gold" / "fixture_one"
            case.mkdir(parents=True)
            gold.mkdir(parents=True)
            (case / "README.md").write_text("task", encoding="utf-8")
            (gold / "test_gold.py").write_text("import unittest\n", encoding="utf-8")
            evidence = gold / "evidence.json"
            evidence.write_text('{"schema_version":1}\n', encoding="utf-8")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "input_sha256": {"README.md": digest(case / "README.md")},
                "acceptance_sha256": {"test_gold.py": digest(gold / "test_gold.py")},
                "evidence_sha256": digest(evidence),
            }), encoding="utf-8")

            verified = agents.verify_frozen_manifest(case, gold, manifest)
            self.assertEqual(verified["evidence_sha256"], digest(evidence))
            evidence.write_text('{"schema_version":1,"changed":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence_sha256"):
                agents.verify_frozen_manifest(case, gold, manifest)
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            manifest_data.pop("evidence_sha256")
            manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be pinned"):
                agents.verify_frozen_manifest(case, gold, manifest)

    def test_tampered_frozen_manifest_stops_before_native_client_setup(self):
        with tempfile.TemporaryDirectory(prefix="sift-frozen-preflight-") as temporary:
            root = Path(temporary)
            case, gold = root / "case", root / "gold"
            case.mkdir()
            gold.mkdir()
            (case / "README.md").write_text("task", encoding="utf-8")
            (case / "solution.py").write_text("pass\n", encoding="utf-8")
            gold_test = gold / "test_gold.py"
            gold_test.write_text("import unittest\n", encoding="utf-8")
            def digest(path):
                return hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "input_sha256": {name: digest(case / name) for name in ("README.md", "solution.py")},
                "acceptance_sha256": {"test_gold.py": digest(gold_test)},
            }), encoding="utf-8")
            gold_test.write_text("# changed after freeze\n", encoding="utf-8")
            argv = ["agents.py", "--client", "claude", "--case", str(case), "--gold", str(gold),
                    "--manifest", str(manifest), "--editable", "solution.py",
                    "--base-url", "http://unused.invalid/v1", "--model", "offline",
                    "--api-key-env", "SIFT_OFFLINE_KEY"]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"SIFT_OFFLINE_KEY": "offline"}), \
                    patch.object(agents, "executable_for", side_effect=AssertionError("client setup must not run")), \
                    patch.object(agents, "run_process", side_effect=AssertionError("no subprocess may run")), \
                    redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
                agents.main()
            self.assertEqual(error.exception.code, 2)

    def test_claude_can_run_fixture_cli_but_python_one_liners_remain_denied(self):
        command = agents.client_command(
            SimpleNamespace(client="claude", model="offline"), "claude", ["reconcile.py", "audit.py"])
        allowed = command[command.index("--allowedTools") + 1]
        shell = "PowerShell" if os.name == "nt" else "Bash"
        self.assertIn(f"{shell}({agents.TOOL_TEST_PYTHON} reconcile.py:*)", allowed)
        self.assertIn(f"{shell}({agents.TOOL_TEST_PYTHON} audit.py:*)", allowed)
        self.assertNotIn(f"{shell}({agents.TOOL_TEST_PYTHON} -c:*)", allowed)

        restricted = agents.client_command(
            SimpleNamespace(client="claude", model="offline"), "claude", ["implementation.py"])
        restricted_allowed = restricted[restricted.index("--allowedTools") + 1]
        self.assertNotIn(f"{shell}({agents.TOOL_TEST_PYTHON} audit.py:*)", restricted_allowed)

    def test_claude_output_cap_cannot_exceed_gateway_limit(self):
        argv = ["agents.py", "--client", "claude", "--case", "case", "--gold", "gold",
                "--editable", "solution.py", "--base-url", "http://127.0.0.1:4010/v1",
                "--model", "qwen3.8-27b", "--api-key-env", "SIFT_AGENT_API_KEY",
                "--claude-max-output-tokens", "4097"]
        with patch.object(sys, "argv", argv), self.assertRaises(SystemExit) as error:
            agents.main()
        self.assertEqual(error.exception.code, 2)

    def test_readonly_filesystem_is_a_valid_denial_but_unrelated_io_errors_are_not(self):
        with tempfile.TemporaryDirectory(prefix="sift-probe-errno-") as temporary:
            base = Path(temporary)
            inside, outside = base / "inside.txt", base / "outside.txt"
            original = Path.write_text

            def write(error_number):
                def attempt(path, *args, **kwargs):
                    if path == outside:
                        raise OSError(error_number, "injected filesystem outcome")
                    return original(path, *args, **kwargs)
                return attempt

            for error_number in (errno.EACCES, errno.EPERM, errno.EROFS):
                with self.subTest(errno=error_number), patch.object(sys, "argv", ["-c", str(inside), str(outside)]), \
                        patch.object(Path, "write_text", write(error_number)), redirect_stdout(io.StringIO()) as output:
                    exec(compile(agents.SANDBOX_PROBE, "<native-sandbox-readiness>", "exec"), {})
                    self.assertEqual(output.getvalue().strip(), agents.SANDBOX_READY)
                    self.assertFalse(inside.exists())
                    self.assertFalse(outside.exists())
            with patch.object(sys, "argv", ["-c", str(inside), str(outside)]), \
                    patch.object(Path, "write_text", write(errno.ENOSPC)), redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(OSError) as error:
                    exec(compile(agents.SANDBOX_PROBE, "<native-sandbox-readiness>", "exec"), {})
                self.assertEqual(error.exception.errno, errno.ENOSPC)
                self.assertEqual(output.getvalue(), "")

    def test_unknown_nested_event_shapes_do_not_discard_valid_client_evidence(self):
        unknown = [{"type": "system", "message": "native status message"},
                   {"type": "assistant", "message": ["unknown"]},
                   {"type": "stream_event", "event": "unknown", "ttft_ms": 900},
                   {"type": "item.completed", "item": "unknown"},
                   {"type": "item.completed", "item": {"type": "command_execution", "command": {}, "status": []}},
                   {"type": "assistant", "message": {"content": [
                       {"type": "tool_use", "id": [], "name": "Bash", "input": "unknown"},
                       {"type": "tool_result", "tool_use_id": []}]}}]
        failed = "Ran 2 tests in 0.1s\nFAILED (failures=1)"
        passed = "Ran 2 tests in 0.1s\nOK\n"
        claude = []
        codex = []
        for number, (output, code) in enumerate(((failed, 1), (passed, 0))):
            claude.extend([
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": str(number),
                 "name": "Bash", "input": {"command": "python -m unittest -q"}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": str(number),
                 "content": "Exit code 1\n" + output if code else output, "is_error": bool(code)}]},
                 "tool_use_result": output if code else {"stdout": output, "stderr": "", "interrupted": False}}])
            codex.append({"type": "item.completed", "item": {"type": "command_execution",
                          "command": "/bin/bash -lc 'python -m unittest -q'", "aggregated_output": output,
                          "exit_code": code, "status": "failed" if code else "completed"}})
        claude.extend([{"type": "stream_event", "event": {"type": "message_start"}, "ttft_ms": 17.5},
                       {"type": "result", "subtype": "success", "is_error": False, "usage": {"input_tokens": 12}}])
        codex.append({"type": "turn.completed", "usage": {"input_tokens": 12}})
        for client, events in (("claude", claude), ("codex", codex)):
            with self.subTest(client=client):
                stdout = "\n".join(map(json.dumps, unknown + events))
                result = agents.event_evidence(client, stdout)
                self.assertTrue(result["native_terminal_success"])
                self.assertTrue(result["observed_test_loop"])
                self.assertEqual(result["test_tool_calls"], 2)
                self.assertEqual(result["client_reported_ttft_ms"], [17.5] if client == "claude" else [])

    def test_claude_stream_reports_decode_rate_and_labeled_client_cost(self):
        events = [
            {"type": "stream_event", "timestamp": "2026-10-16T12:00:00.000Z",
             "event": {"type": "message_start"}, "ttft_ms": 250.0},
            {"type": "stream_event", "timestamp": "2026-10-16T12:00:00.250Z",
             "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}}},
            {"type": "stream_event", "timestamp": "2026-10-16T12:00:00.750Z",
             "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}}},
            {"type": "stream_event", "timestamp": "2026-10-16T12:00:00.800Z",
             "event": {"type": "message_delta", "usage": {"output_tokens": 20}}},
            {"type": "stream_event", "timestamp": "2026-10-16T12:00:00.810Z",
             "event": {"type": "message_stop"}},
            {"type": "result", "subtype": "success", "is_error": False,
             "usage": {"input_tokens": 100, "output_tokens": 20}, "total_cost_usd": 0.0123},
        ]

        result = agents.event_evidence("claude", "\n".join(map(json.dumps, events)))

        self.assertEqual(result["client_reported_ttft_ms"], [250.0])
        self.assertEqual(result["client_reported_decode_tokens_per_second"], [40.0])
        self.assertEqual(result["mean_client_reported_decode_tokens_per_second"], 40.0)
        self.assertEqual(result["client_reported_cost_usd"], 0.0123)
        self.assertEqual(result["client_reported_cost_source"], "Claude Code result.total_cost_usd")

    def test_decode_rate_is_unknown_without_stream_timestamps(self):
        events = [
            {"type": "stream_event", "event": {"type": "message_start"}, "ttft_ms": 50},
            {"type": "stream_event", "event": {"type": "content_block_delta",
             "delta": {"type": "text_delta", "text": "generated"}}},
            {"type": "stream_event", "event": {"type": "message_delta", "usage": {"output_tokens": 10}}},
            {"type": "stream_event", "event": {"type": "message_stop"}},
            {"type": "result", "subtype": "success", "is_error": False, "usage": {}},
        ]
        result = agents.event_evidence("claude", "\n".join(map(json.dumps, events)))
        self.assertEqual(result["client_reported_decode_tokens_per_second"], [])
        self.assertIsNone(result["mean_client_reported_decode_tokens_per_second"])

    def test_parser_failure_preserves_redacted_native_checkpoint_and_post_checks(self):
        with tempfile.TemporaryDirectory(prefix="sift-agent-regression-") as temporary:
            base = Path(temporary)
            case, gold, run = (base / name for name in ("case", "gold", "run"))
            for directory in (case, gold, run):
                directory.mkdir()
            (case / "README.md").write_text("Produce the correct findings artifact.", encoding="utf-8")
            (gold / "README.md").write_text("External gold provenance.", encoding="utf-8")
            (case / "findings.json").write_text("{}", encoding="utf-8")
            test = ('import json,unittest\nfrom pathlib import Path\nclass Check(unittest.TestCase):\n'
                    ' def test_answer(self): self.assertEqual(json.loads((Path(__file__).parent/"findings.json").read_text()),{"answer":"ok"})\n')
            (case / "test_visible.py").write_text(test, encoding="utf-8")
            (gold / "test_independent_gold.py").write_text(test, encoding="utf-8")
            key = 'offline-quote"secret'
            native_stdout = json.dumps({"type": "system", "message": "status", "debug": key}) + "\n"
            original = agents.run_process

            def process(command, directory, env, **kwargs):
                if command[0] != "fake-native":
                    return original(command, directory, env, **kwargs)
                home = env.get("CLAUDE_CONFIG_DIR") or env.get("CODEX_HOME")
                self.assertEqual(Path(home), run / "client-home")
                self.assertTrue(Path(home).is_dir(), "Owned client home must exist before version and native startup")
                result = {"exit_code": 0, "timed_out": False, "seconds": 0.5, "stdout": "fake-native 1.0", "stderr": ""}
                if "--version" not in command:
                    (directory / "findings.json").write_text('{"answer":"ok"}', encoding="utf-8")
                    result.update({"stdout": native_stdout, "stderr": key})
                return result

            def parse_failure(client, stdout):
                # These must already exist when interpretation of paid output starts.
                checkpoint = json.loads((run / "result.json").read_text(encoding="utf-8"))
                self.assertEqual(checkpoint["phase"], "native_completed")
                self.assertEqual(checkpoint["native"]["exit_code"], 0)
                self.assertEqual(checkpoint["native"]["seconds"], 0.5)
                self.assertIn("[REDACTED]", (run / "native.stdout.jsonl").read_text(encoding="utf-8"))
                self.assertEqual((run / "native.stderr").read_text(encoding="utf-8"), "[REDACTED]")
                raise TypeError("simulated parser failure " + key)

            argv = ["agents.py", "--client", "claude", "--case", str(case), "--gold", str(gold),
                    "--editable", "findings.json", "--base-url", "http://unused.invalid/v1",
                    "--model", "offline", "--api-key-env", "SIFT_OFFLINE_KEY"]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"SIFT_OFFLINE_KEY": key}), \
                    patch.object(agents.Path, "home", return_value=base), \
                    patch.object(agents.tempfile, "mkdtemp", return_value=str(run)), \
                    patch.object(agents, "executable_for", return_value="fake-native"), \
                    patch.object(agents, "run_process", side_effect=process), \
                    patch.object(agents, "event_evidence", side_effect=parse_failure), redirect_stdout(io.StringIO()):
                self.assertEqual(agents.main(), 1)
            report = json.loads((run / "result.json").read_text(encoding="utf-8"))
            self.assertFalse(report["accepted"])
            self.assertEqual(report["harness_failure"]["stage"], "parse_native_events")
            self.assertEqual(report["harness_failure"]["type"], "TypeError")
            self.assertEqual(report["native"]["exit_code"], 0)
            self.assertTrue(report["visible"]["passed"])
            self.assertTrue(report["gold"]["passed"])
            self.assertEqual(report["changed_files"], ["findings.json"])
            self.assertEqual((run / "workspace" / "findings.json").read_text(), '{"answer":"ok"}')
            self.assertEqual((case / "findings.json").read_text(), "{}")
            for name in ("native.stdout.jsonl", "native.stderr", "result.json"):
                saved = (run / name).read_text(encoding="utf-8")
                self.assertNotIn(key, saved)
                self.assertNotIn(json.dumps(key)[1:-1], saved)

    def test_generated_output_is_isolated_from_baseline_and_allowed_when_declared(self):
        with tempfile.TemporaryDirectory(prefix="sift-agent-output-regression-") as temporary:
            base = Path(temporary)
            case, gold, run = (base / name for name in ("case", "gold", "run"))
            for directory in (case, gold, run):
                directory.mkdir()
            (case / "README.md").write_text("Generate report.json by editing implementation.py.", encoding="utf-8")
            implementation = case / "implementation.py"
            implementation.write_text(
                'from pathlib import Path\nimport json\nPath("report.json").write_text(json.dumps({"ok": False}))\n',
                encoding="utf-8")
            check = (
                'import json, subprocess, sys, unittest\nfrom pathlib import Path\n'
                'ROOT=Path(__file__).parent\n'
                'class Check(unittest.TestCase):\n'
                ' def test_report(self):\n'
                '  subprocess.run([sys.executable,str(ROOT/"implementation.py")],check=True,cwd=ROOT)\n'
                '  self.assertEqual(json.loads((ROOT/"report.json").read_text()),{"ok":True})\n')
            (case / "test_visible.py").write_text(check, encoding="utf-8")
            (gold / "test_gold.py").write_text(check, encoding="utf-8")
            key = "offline-key"
            original_run_process = agents.run_process

            def process(command, directory, env, **kwargs):
                if command[0] != "fake-native":
                    return original_run_process(command, directory, env, **kwargs)
                if "--version" in command:
                    return {"exit_code": 0, "timed_out": False, "seconds": 0.1,
                            "stdout": "fake-native 1.0", "stderr": ""}
                self.assertFalse((directory / "report.json").exists(),
                                 "a baseline test's generated artifact must not leak into the client workspace")
                (directory / "implementation.py").write_text(
                    'from pathlib import Path\nimport json\nPath("report.json").write_text(json.dumps({"ok": True}))\n',
                    encoding="utf-8")
                subprocess.run([sys.executable, str(directory / "implementation.py")], check=True, cwd=directory)
                return {"exit_code": 0, "timed_out": False, "seconds": 0.2, "stdout": "{}\n", "stderr": ""}

            argv = ["agents.py", "--client", "claude", "--case", str(case), "--gold", str(gold),
                    "--editable", "implementation.py", "--allowed-output", "report.json",
                    "--base-url", "http://unused.invalid/v1", "--model", "offline",
                    "--api-key-env", "SIFT_OFFLINE_KEY"]
            successful_events = {"native_terminal_success": True, "observed_test_loop": True,
                                 "test_tool_calls": 2, "client_reported_usage": None,
                                 "client_reported_ttft_ms": [], "mean_client_reported_ttft_ms": None}
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"SIFT_OFFLINE_KEY": key}), \
                    patch.object(agents.Path, "home", return_value=base), \
                    patch.object(agents.tempfile, "mkdtemp", return_value=str(run)), \
                    patch.object(agents, "executable_for", return_value="fake-native"), \
                    patch.object(agents, "run_process", side_effect=process), \
                    patch.object(agents, "event_evidence", return_value=successful_events), redirect_stdout(io.StringIO()):
                status = agents.main()
            report = json.loads((run / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(status, 0, json.dumps(report, indent=2))
            self.assertTrue(report["accepted"])
            self.assertEqual(report["baseline"]["exit_code"], 1)
            self.assertTrue((run / "baseline-check" / "report.json").is_file())
            self.assertEqual(report["created_outputs"], ["report.json"])
            self.assertEqual(report["missing_outputs"], [])
            self.assertEqual(report["extra_files"], [])
            self.assertTrue(report["visible"]["passed"])
            self.assertTrue(report["gold"]["passed"])

    def test_codex_owned_home_exists_before_version_and_native_startup(self):
        with tempfile.TemporaryDirectory(prefix="sift-codex-home-regression-") as temporary:
            base = Path(temporary)
            case, gold, run = (base / name for name in ("case", "gold", "run"))
            for directory in (case, gold, run):
                directory.mkdir()
            (case / "README.md").write_text("Produce findings.json.", encoding="utf-8")
            (case / "findings.json").write_text("{}", encoding="utf-8")
            (gold / "test_gold.py").write_text("import unittest\n", encoding="utf-8")
            invocations = []

            def process(command, directory, env, **kwargs):
                if command[0] != "fake-native":
                    self.fail("Unexpected subprocess in isolated home startup regression")
                home = Path(env["CODEX_HOME"])
                self.assertEqual(home, run / "client-home")
                self.assertTrue(home.is_dir())
                self.assertNotIn("CLAUDE_CONFIG_DIR", env)
                phase = "version" if "--version" in command else "sandbox" if command[1] == "sandbox" else "native"
                invocations.append(phase)
                if phase == "sandbox":
                    self.assertNotIn("SIFT_AGENT_API_KEY", env)
                    return {"exit_code": 0, "timed_out": False, "seconds": 0.1,
                            "stdout": agents.SANDBOX_READY, "stderr": ""}
                return {"exit_code": 1, "timed_out": False, "seconds": 0.1,
                        "stdout": "fake-native 1.0", "stderr": "deliberate offline startup failure"}

            # Version succeeds, then the native startup deliberately fails; both
            # callbacks must observe the already-created isolated home.
            def native_process(command, directory, env, **kwargs):
                result = process(command, directory, env, **kwargs)
                if "--version" in command:
                    result["exit_code"] = 0
                return result

            baseline = {"exit_code": 1, "timed_out": False, "tests_observed": True, "passed": False}
            argv = ["agents.py", "--client", "codex", "--case", str(case), "--gold", str(gold),
                    "--editable", "findings.json", "--base-url", "http://unused.invalid/v1",
                    "--model", "offline", "--api-key-env", "SIFT_OFFLINE_KEY",
                    "--windows-sandbox", "unelevated"]
            with patch.object(sys, "argv", argv), patch.dict(os.environ, {"SIFT_OFFLINE_KEY": "offline-secret"}), \
                    patch.object(agents.Path, "home", return_value=base), \
                    patch.object(agents.tempfile, "mkdtemp", return_value=str(run)), \
                    patch.object(agents, "executable_for", return_value="fake-native"), \
                    patch.object(agents, "run_process", side_effect=native_process), \
                    patch.object(agents, "unit_tests", return_value=baseline), redirect_stdout(io.StringIO()):
                self.assertEqual(agents.main(), 1)
            self.assertEqual(invocations, ["version", "sandbox", "native"])
            report = json.loads((run / "result.json").read_text(encoding="utf-8"))
            self.assertFalse(report["accepted"])
            self.assertEqual(report["native"]["exit_code"], 1)
            self.assertIn("deliberate offline startup failure", report["native"]["stderr"])

    def test_failed_sandbox_preflight_preserves_report_and_never_starts_model(self):
        for label, code, timed_out, output in (("error", 1, False, ""),
                                             ("timeout", 124, True, ""),
                                             ("boundary", 0, False, "OUTSIDE_WRITE_ALLOWED")):
            with self.subTest(reason=label), tempfile.TemporaryDirectory(prefix="sift-readiness-regression-") as temporary:
                base = Path(temporary)
                case, gold, run = (base / name for name in ("case", "gold", "run"))
                for directory in (case, gold, run):
                    directory.mkdir()
                (case / "README.md").write_text("Produce findings.json.", encoding="utf-8")
                (case / "findings.json").write_text("{}", encoding="utf-8")
                (gold / "test_gold.py").write_text("import unittest\n", encoding="utf-8")
                invocations = []

                def process(command, directory, env, **kwargs):
                    if "--version" in command:
                        invocations.append("version")
                        return {"exit_code": 0, "timed_out": False, "seconds": 0.1,
                                "stdout": "fake-native 1.0", "stderr": ""}
                    self.assertEqual(command[1], "sandbox", "Model exec must not follow a failed readiness check")
                    invocations.append("sandbox")
                    self.assertLessEqual(kwargs["timeout"], 20)
                    self.assertNotIn("SIFT_AGENT_API_KEY", env)
                    self.assertNotIn("ANTHROPIC_API_KEY", env)
                    return {"exit_code": code, "timed_out": timed_out, "seconds": 0.1,
                            "stdout": output, "stderr": "native readiness diagnostic"}

                baseline = {"exit_code": 1, "timed_out": False, "tests_observed": True, "passed": False}
                argv = ["agents.py", "--client", "codex", "--case", str(case), "--gold", str(gold),
                        "--editable", "findings.json", "--base-url", "http://unused.invalid/v1",
                        "--model", "offline", "--api-key-env", "SIFT_OFFLINE_KEY",
                        "--windows-sandbox", "unelevated"]
                with patch.object(sys, "argv", argv), patch.dict(os.environ, {"SIFT_OFFLINE_KEY": "offline-secret"}), \
                        patch.object(agents.Path, "home", return_value=base), \
                        patch.object(agents.tempfile, "mkdtemp", return_value=str(run)), \
                        patch.object(agents, "executable_for", return_value="fake-native"), \
                        patch.object(agents, "run_process", side_effect=process), \
                        patch.object(agents, "unit_tests", return_value=baseline), redirect_stdout(io.StringIO()):
                    self.assertEqual(agents.main(), 1)
                self.assertEqual(invocations, ["version", "sandbox"])
                report = json.loads((run / "result.json").read_text(encoding="utf-8"))
                self.assertFalse(report["accepted"])
                self.assertFalse(report["sandbox_preflight"]["passed"])
                self.assertEqual(report["sandbox_preflight"]["exit_code"], code)
                self.assertEqual(report["sandbox_preflight"]["stdout"], output)
                self.assertNotIn("native", report)
                self.assertIn("model execution was not started", report["failure"])


if __name__ == "__main__":
    unittest.main()
