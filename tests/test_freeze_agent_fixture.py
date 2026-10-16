from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks import agents, freeze_agent_fixture


class FixtureFreezeTests(unittest.TestCase):
    def make_fixture(self, root: Path):
        case = root / "case"
        gold = root / "gold"
        case.mkdir()
        gold.mkdir()
        (case / "README.md").write_text("Implement the report.\n", encoding="utf-8")
        (case / "audit.py").write_text("raise NotImplementedError()\n", encoding="utf-8")
        (case / "__pycache__").mkdir()
        (case / "__pycache__" / "ignored.pyc").write_bytes(b"compiled")
        (gold / "test_gold.py").write_text("def test_contract(): pass\n", encoding="utf-8")
        return case, gold

    def test_below_range_does_not_write_a_freeze_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case, gold = self.make_fixture(root)
            manifest = gold / "manifest.json"
            with patch.object(freeze_agent_fixture, "count_tokens", return_value=99):
                with self.assertRaisesRegex(ValueError, "outside the required range"):
                    freeze_agent_fixture.create_manifest(
                        case, gold, manifest, tokenizer_url="http://tokenizer",
                        min_source_tokens=100, max_source_tokens=200,
                    )
            self.assertFalse(manifest.exists())

    def test_written_manifest_passes_native_runner_and_excludes_pycache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case, gold = self.make_fixture(root)
            manifest_path = gold / "manifest.json"
            with patch.object(freeze_agent_fixture, "count_tokens", return_value=150):
                manifest = freeze_agent_fixture.create_manifest(
                    case, gold, manifest_path, tokenizer_url="http://tokenizer",
                    min_source_tokens=100, max_source_tokens=200,
                )
            self.assertEqual(set(manifest["input_sha256"]), {"README.md", "audit.py"})
            self.assertEqual(manifest["source_prompt_tokens"], 150)
            verified = agents.verify_frozen_manifest(case, gold, manifest_path)
            self.assertEqual(verified["input_sha256"], manifest["input_sha256"])
            self.assertEqual(verified["acceptance_sha256"], manifest["acceptance_sha256"])

    def test_existing_manifest_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case, gold = self.make_fixture(root)
            manifest_path = gold / "manifest.json"
            manifest_path.write_text('{"frozen": true}\n', encoding="utf-8")
            original = manifest_path.read_bytes()
            with patch.object(freeze_agent_fixture, "count_tokens") as counter:
                with self.assertRaises(FileExistsError):
                    freeze_agent_fixture.create_manifest(
                        case, gold, manifest_path, tokenizer_url="http://tokenizer",
                        min_source_tokens=1, max_source_tokens=200,
                    )
            counter.assert_not_called()
            self.assertEqual(manifest_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
