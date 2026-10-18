import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import log_settings


ROOT = Path(__file__).resolve().parents[2] / "agent_cases" / "log_rotation_migration"
DEFAULTS = {
    "file": "var/log/service.log",
    "level": "INFO",
    "max_bytes": 10_485_760,
    "backup_count": 5,
    "compress": False,
}
KEYS = ("file", "level", "max_bytes", "backup_count", "compress")


class LogSettingsGold(unittest.TestCase):
    def test_defaults_file_legacy_and_canonical_precedence_is_per_key(self):
        result = log_settings.resolve_settings(
            {"file": "from-file.log", "level": "warning", "max_bytes": 2048,
             "backup_count": 6, "compress": True},
            {"LOG_FILE": "legacy.log", "APP_LOG_FILE": "canonical.log",
             "LOG_LEVEL": "debug", "APP_LOG_MAX_BYTES": "4096",
             "LOG_BACKUPS": "7", "APP_LOG_BACKUP_COUNT": "8",
             "LOG_COMPRESS": "false"},
        )
        self.assertEqual(result, {
            "file": "canonical.log", "level": "DEBUG", "max_bytes": 4096,
            "backup_count": 8, "compress": False,
        })
        self.assertEqual(log_settings.resolve_settings({}, {}), DEFAULTS)

    def test_all_canonical_and_legacy_names_are_supported_case_sensitively(self):
        aliases = {
            "LOG_FILE": "old.log", "LOG_LEVEL": "error", "LOG_MAX_BYTES": "17",
            "LOG_BACKUPS": "0", "LOG_COMPRESS": "TRUE",
        }
        self.assertEqual(log_settings.resolve_settings({}, aliases), {
            "file": "old.log", "level": "ERROR", "max_bytes": 17,
            "backup_count": 0, "compress": True,
        })
        canonical = {
            "APP_LOG_FILE": "new.log", "APP_LOG_LEVEL": "critical",
            "APP_LOG_MAX_BYTES": "18", "APP_LOG_BACKUP_COUNT": "99",
            "APP_LOG_COMPRESS": "false", "app_log_level": "TRACE",
        }
        self.assertEqual(log_settings.resolve_settings({}, canonical), {
            "file": "new.log", "level": "CRITICAL", "max_bytes": 18,
            "backup_count": 99, "compress": False,
        })

    def test_invalid_explicit_values_fail_without_fallback(self):
        bad = [
            ({"level": "INFO"}, {"LOG_LEVEL": "TRACE"}),
            ({}, {"LOG_LEVEL": ""}),
            ({"max_bytes": 1024}, {"APP_LOG_MAX_BYTES": "0"}),
            ({}, {"APP_LOG_MAX_BYTES": "1.0"}),
            ({"backup_count": 2}, {"LOG_BACKUPS": "100"}),
            ({}, {"APP_LOG_BACKUP_COUNT": "-1"}),
            ({"compress": False}, {"APP_LOG_COMPRESS": "yes"}),
            ({"file": "valid.log"}, {"APP_LOG_FILE": ""}),
        ]
        for config, environ in bad:
            with self.subTest(config=config, environ=environ):
                with self.assertRaises(ValueError):
                    log_settings.resolve_settings(config, environ)
        with self.assertRaises(ValueError):
            log_settings.resolve_settings({"max_bytes": True}, {})
        with self.assertRaises(ValueError):
            log_settings.resolve_settings({"backup_count": -1}, {})
        with self.assertRaises(ValueError):
            log_settings.resolve_settings({"compress": "false"}, {})

    def test_unknown_config_keys_and_non_objects_are_rejected(self):
        for config in (None, [], {"extra": 1}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                log_settings.resolve_settings(config, {})

    def test_json_duplicate_keys_and_bad_wrappers_are_rejected(self):
        contents = [
            '{"logging":{"file":"a.log","file":"b.log"}}',
            '{"logging":{"file":"a.log"},"service":{"x":1,"x":2}}',
            '{"service":{}}',
            '{"logging":[]}',
            '{"logging":{"compress":"true"}}',
            '{"logging":{"max_bytes":NaN}}',
        ]
        with tempfile.TemporaryDirectory() as temporary:
            for index, content in enumerate(contents):
                source = Path(temporary) / f"bad-{index}.json"
                output = Path(temporary) / f"out-{index}.json"
                source.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    log_settings.migrate_file(source, output, environ={})
                self.assertFalse(output.exists())

    def test_stable_artifact_bytes_expected_values_and_no_environment_mutation(self):
        config = ROOT / "examples" / "legacy-logging.json"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "effective.json"
            env = {"LOG_LEVEL": "error", "APP_LOG_COMPRESS": "false"}
            before = dict(env)
            first = log_settings.migrate_file(config, output, environ=env)
            expected = {"file": "var/log/worker.log", "level": "ERROR",
                        "max_bytes": 5_242_880, "backup_count": 7,
                        "compress": False}
            self.assertEqual(first, expected)
            expected_bytes = (json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n").encode()
            self.assertEqual(output.read_bytes(), expected_bytes)
            self.assertEqual(set(first), set(KEYS))
            log_settings.migrate_file(config, output, environ=env)
            self.assertEqual(output.read_bytes(), expected_bytes)
            self.assertEqual(env, before)

    def test_cli_emits_valid_artifact_and_errors_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "effective.json"
            env = dict(os.environ)
            env.update({"APP_LOG_LEVEL": "warning", "APP_LOG_BACKUP_COUNT": "0"})
            ok = subprocess.run(
                [sys.executable, str(ROOT / "log_settings.py"), "--config",
                 str(ROOT / "examples" / "legacy-logging.json"), "--output", str(output)],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {
                "file": "var/log/worker.log", "level": "WARNING",
                "max_bytes": 5_242_880, "backup_count": 0, "compress": True,
            })

            env["APP_LOG_BACKUP_COUNT"] = "bad"
            bad = subprocess.run(
                [sys.executable, str(ROOT / "log_settings.py"), "--config",
                 str(ROOT / "examples" / "legacy-logging.json"), "--output",
                 str(Path(temporary) / "bad.json")],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(bad.returncode, 0)
            self.assertTrue(bad.stderr.strip())


if __name__ == "__main__":
    unittest.main()
