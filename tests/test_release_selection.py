"""Release rehearsal selection must not open a development publish path."""

import sys
from pathlib import Path
import unittest

import yaml


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_release_selection import validate_release_selection


class ReleaseSelectionTests(unittest.TestCase):
    def test_current_dev_version_allows_tagless_dry_run(self):
        validate_release_selection("0.11.0.dev0", dry_run=True, tag="")

    def test_matching_stable_tag_allows_rehearsal_or_publish(self):
        validate_release_selection("0.11.0", dry_run=True, tag="v0.11.0")
        validate_release_selection("0.11.0", dry_run=False, tag="v0.11.0")

    def test_development_version_cannot_publish_even_with_matching_dev_tag(self):
        with self.assertRaisesRegex(ValueError, "stable vX.Y.Z package version"):
            validate_release_selection("0.11.0.dev0", dry_run=False, tag="v0.11.0.dev0")

    def test_tagless_dry_run_requires_development_version(self):
        with self.assertRaisesRegex(ValueError, "requires a .devN version"):
            validate_release_selection("0.11.0", dry_run=True, tag="")

    def test_publish_requires_exact_stable_tag_and_version(self):
        for version, tag in (("0.11.0", ""), ("0.11.0", "v0.11.1"), ("0.11.0rc1", "v0.11.0rc1")):
            with self.subTest(version=version, tag=tag), self.assertRaises(ValueError):
                validate_release_selection(version, dry_run=False, tag=tag)


class PublishWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish.yml"
        cls.workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        cls.jobs = cls.workflow["jobs"]
        cls.build_steps = cls.jobs["build"]["steps"]

    def test_manual_dispatch_defaults_to_non_publishing_dry_run_and_optional_tag(self):
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["dry_run"]["default"], "true")
        self.assertEqual(inputs["dry_run"]["required"], "true")
        self.assertEqual(inputs["tag"]["required"], "false")

    def test_build_only_runs_from_main_and_fetches_full_history_without_tag_checkout(self):
        build = self.jobs["build"]
        self.assertEqual(build["if"], "${{ github.ref == 'refs/heads/main' }}")
        checkout = next(step for step in self.build_steps if step.get("uses", "").startswith("actions/checkout@"))
        self.assertEqual(checkout["with"]["fetch-depth"], "0")
        self.assertNotIn("ref", checkout.get("with", {}))

    def test_validate_before_optional_tag_checkout_then_check_main_ancestry(self):
        names = [step.get("name", "") for step in self.build_steps]
        validate_idx = names.index("Validate release selection")
        tag_checkout_idx = names.index("Checkout selected stable release tag")
        ancestry_idx = names.index("Check release tag belongs to main")
        self.assertLess(validate_idx, tag_checkout_idx)
        self.assertLess(tag_checkout_idx, ancestry_idx)
        self.assertIn("scripts/validate_release_selection.py", self.build_steps[validate_idx]["run"])
        self.assertIn('git checkout --detach "refs/tags/${RELEASE_TAG}"', self.build_steps[tag_checkout_idx]["run"])
        self.assertIn("git merge-base --is-ancestor", self.build_steps[ancestry_idx]["run"])
        self.assertIn('refs/remotes/origin/main', self.build_steps[ancestry_idx]["run"])
        self.assertEqual(self.build_steps[tag_checkout_idx]["if"], "${{ inputs.tag != '' }}")
        self.assertEqual(self.build_steps[ancestry_idx]["if"], "${{ inputs.tag != '' }}")

    def test_publish_requires_successful_build_main_ref_and_explicit_non_dry_run(self):
        publish = self.jobs["publish"]
        self.assertEqual(publish["needs"], "build")
        self.assertEqual(publish["if"], "${{ github.ref == 'refs/heads/main' && inputs.dry_run == false }}")
        self.assertEqual(publish["environment"]["name"], "pypi")
        upload = next(step for step in self.build_steps if step.get("uses", "").startswith("actions/upload-artifact@"))
        download = next(step for step in publish["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
        self.assertEqual(upload["with"]["name"], "python-distributions")
        self.assertEqual(download["with"]["name"], "python-distributions")


if __name__ == "__main__":
    unittest.main()
