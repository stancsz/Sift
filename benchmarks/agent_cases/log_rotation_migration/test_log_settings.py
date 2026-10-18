import json
import tempfile
import unittest
from pathlib import Path

import log_settings


class LogSettingsMigrationTests(unittest.TestCase):
    def test_defaults_and_per_setting_precedence_with_legacy_compatibility(self):
        result = log_settings.resolve_settings(
            {"file": "file.log", "level": "debug", "max_bytes": 4096},
            {
                "LOG_FILE": "old.log",
                "APP_LOG_FILE": "new.log",
                "LOG_BACKUPS": "2",
                "APP_LOG_COMPRESS": "TRUE",
            },
        )
        self.assertEqual(result, {
            "file": "new.log", "level": "DEBUG", "max_bytes": 4096,
            "backup_count": 2, "compress": True,
        })

    def test_all_legacy_names_and_canonical_per_setting_override(self):
        result = log_settings.resolve_settings(
            {},
            {"LOG_FILE": "old.log", "LOG_LEVEL": "warning",
             "LOG_MAX_BYTES": "2048", "LOG_BACKUPS": "4", "LOG_COMPRESS": "false",
             "APP_LOG_BACKUP_COUNT": "8"},
        )
        self.assertEqual(result, {
            "file": "old.log", "level": "WARNING", "max_bytes": 2048,
            "backup_count": 8, "compress": False,
        })

    def test_invalid_higher_precedence_values_raise_instead_of_falling_back(self):
        cases = [
            ({"level": "INFO"}, {"APP_LOG_LEVEL": "TRACE"}),
            ({"max_bytes": 1024}, {"LOG_MAX_BYTES": "0"}),
            ({"backup_count": 5}, {"APP_LOG_BACKUP_COUNT": "100"}),
            ({"compress": False}, {"APP_LOG_COMPRESS": "yes"}),
            ({"file": "ok.log"}, {"LOG_FILE": ""}),
        ]
        for config, environ in cases:
            with self.subTest(config=config, environ=environ):
                with self.assertRaises(ValueError):
                    log_settings.resolve_settings(config, environ)

    def test_bad_file_shapes_keys_and_duplicate_keys_are_rejected(self):
        for value in ([], {"unknown": 3}, {"max_bytes": True}, {"compress": "true"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                log_settings.resolve_settings(value)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "duplicate.json"
            source.write_text('{"logging":{"file":"a.log","file":"b.log"}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                log_settings.migrate_file(source, Path(temporary) / "out.json", environ={})

    def test_resolution_does_not_mutate_environment_and_is_deterministic(self):
        environ = {"LOG_BACKUPS": "3"}
        before = dict(environ)
        first = log_settings.resolve_settings({"level": "error"}, environ)
        second = log_settings.resolve_settings({"level": "error"}, environ)
        self.assertEqual(environ, before)
        self.assertEqual(first, second)

    def test_migration_writes_sorted_deterministic_artifact_and_creates_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "app.json"
            output = Path(temporary) / "nested" / "effective.json"
            source.write_text(json.dumps({"logging": {"level": "warning"}}), encoding="utf-8")
            result = log_settings.migrate_file(source, output, environ={})
            expected = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
            self.assertEqual(output.read_text(encoding="utf-8"), expected)
            before = output.read_bytes()
            log_settings.migrate_file(source, output, environ={})
            self.assertEqual(output.read_bytes(), before)

    def test_failed_migration_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.json"
            output = Path(temporary) / "effective.json"
            source.write_text('{"logging":{"file":"ok.log"}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                log_settings.migrate_file(source, output, environ={"APP_LOG_LEVEL": "TRACE"})
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
