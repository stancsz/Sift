"""Dependency-free smoke checks for the published static site."""

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class _SiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.fragment_refs = []
        self.local_assets = []
        self.elements_by_id = {}
        self.data_demo_buttons = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.ids.append(element_id)
            self.elements_by_id[element_id] = (tag, attributes)

        href = attributes.get("href", "")
        if href.startswith("#"):
            self.fragment_refs.append(href[1:])
        elif href and not href.startswith(("http:", "https:", "mailto:", "tel:", "data:")):
            self.local_assets.append(href.split("#", 1)[0])

        src = attributes.get("src", "")
        if src and not src.startswith(("http:", "https:", "data:")):
            self.local_assets.append(src.split("#", 1)[0])

        if "data-demo-view" in attributes:
            self.data_demo_buttons.append(attributes)

    def handle_data(self, data):
        self.text.append(data)


class SiteSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (SITE / "index.html").read_text(encoding="utf-8")
        cls.parser = _SiteParser()
        cls.parser.feed(cls.html)

    def test_local_links_and_assets_resolve(self):
        duplicates = [element_id for element_id, count in Counter(self.parser.ids).items() if count > 1]
        self.assertEqual(duplicates, [])
        missing_fragments = sorted(set(self.parser.fragment_refs) - set(self.parser.ids))
        self.assertEqual(missing_fragments, [])
        for asset in self.parser.local_assets:
            self.assertTrue((SITE / asset).is_file(), asset)

    def test_interactive_demo_starts_on_compacted_view_with_matching_panel(self):
        buttons = {item.get("data-demo-view"): item for item in self.parser.data_demo_buttons}
        self.assertEqual(set(buttons), {"full", "sift"})
        self.assertEqual(buttons["full"].get("aria-pressed"), "false")
        self.assertEqual(buttons["sift"].get("aria-pressed"), "true")
        self.assertIn("hidden", self.parser.elements_by_id["try-full"][1])
        self.assertNotIn("hidden", self.parser.elements_by_id["try-sift"][1])

        text = " ".join(self.parser.text)
        self.assertIn("ONE OF 14 SELECTED EXCERPTS", text)
        self.assertIn("UTF-8/2 estimate", text)
        self.assertIn("not model tokens or answer-quality evidence", text)

    def test_readme_links_directly_to_interactive_site_sample(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://stancsz.github.io/sift/#try", readme)

    def test_quick_start_uses_the_verified_ollama_demo_model(self):
        self.assertIn("ollama pull qwen3.5:9b", self.html)
        self.assertIn("ollama_compaction_demo.py --model qwen3.5:9b", self.html)
        self.assertNotIn("qwen3.5:4b", self.html)

    def test_evidence_section_reports_quality_tradeoff_and_subroute_cost_limits(self):
        text = " ".join(self.parser.text)
        self.assertIn("59.7%", text.replace(" ", ""))
        self.assertIn("−5.25", text)
        self.assertIn("950,401", text)
        self.assertIn("32,502 input / 6 output", text)
        self.assertIn("37,003 input / 41 output", text)
        self.assertIn("rejected before inference", text)
        self.assertIn("API-rate estimates", text)
        self.assertNotIn("Opus", text)


if __name__ == "__main__":
    unittest.main()
