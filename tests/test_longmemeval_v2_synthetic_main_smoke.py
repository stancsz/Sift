"""Small regressions for the generated main-flow probe; no upstream/runtime required."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.longmemeval_v2_synthetic_main_smoke import (
    strip_script_import_directory,
    verify_sources,
)


class SyntheticMainPrerequisitesTests(unittest.TestCase):
    def test_script_directory_cannot_shadow_official_agents_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script_dir = root / "benchmarks"
            script_dir.mkdir()
            (script_dir / "agents.py").write_text("raise RuntimeError('shadow')\n")
            installed = root / "site-packages"
            installed.mkdir()
            paths = [str(script_dir), str(script_dir / "."), str(installed), str(root)]

            self.assertEqual(
                strip_script_import_directory(paths, script_dir),
                [str(installed), str(root)],
            )
            self.assertEqual(len(paths), 4, "caller import paths must not be mutated")

    def test_unrelated_import_paths_are_preserved_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [str(root / "one"), str(root / "two"), str(root / "one")]
            self.assertEqual(strip_script_import_directory(paths, root / "benchmarks"), paths)

    def test_missing_pinned_source_fails_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "Pinned upstream source mismatch"):
                verify_sources(Path(directory))

    def test_changed_pinned_source_fails_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("print('changed')\n")
            with patch("benchmarks.longmemeval_v2_synthetic_main_smoke.SOURCE_SHA256",
                       {"source.py": "0" * 64}):
                with self.assertRaisesRegex(RuntimeError, "Pinned upstream source mismatch: source.py"):
                    verify_sources(root)


if __name__ == "__main__":
    unittest.main()
