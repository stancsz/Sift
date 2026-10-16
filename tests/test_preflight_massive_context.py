"""Offline protocol checks for the 500K+ Sift selector preflight."""

import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks import preflight_massive_context_sift as preflight


class MassiveContextPreflightTests(unittest.TestCase):
    def test_chunking_preserves_every_utf8_byte_with_bounded_results(self):
        packet = ("incident-id: CHG-88421\n" * 7000).encode("utf-8")
        chunks = preflight._chunks(packet, size=1024)
        self.assertEqual(packet, "".join(chunks).encode("utf-8"))
        self.assertTrue(all(len(chunk.encode("utf-8")) <= 1024 for chunk in chunks))

    def test_message_fixture_contains_a_matching_tool_result_for_each_chunk(self):
        packet = ("record-0123456789\n" * 5000).encode("utf-8")
        chunks = preflight._chunks(packet)
        messages = preflight._messages(packet)
        tool_calls = [block for message in messages if message["role"] == "assistant"
                      for block in message["content"] if block["type"] == "tool_use"]
        tool_results = [block for message in messages if message["role"] == "user"
                        for block in message["content"] if block.get("type") == "tool_result"]
        self.assertEqual(len(chunks), len(tool_calls))
        self.assertEqual(len(chunks), len(tool_results))
        self.assertEqual([call["id"] for call in tool_calls],
                         [block["tool_use_id"] for block in tool_results])
        self.assertEqual(chunks, [block["content"] for block in tool_results])

    def test_frozen_webhook_fixture_has_loadable_bounded_gold_spans(self):
        root = Path(__file__).resolve().parents[1]
        gold = root / "benchmarks/agent_gold/webhook_swarm_500k/evidence.json"
        spans = preflight.load_required_spans(gold)
        self.assertEqual(16, len(spans))
        self.assertTrue(all(0 < len(span.text) <= 2048 for span in spans))
        self.assertTrue(any(span.span_id == "migration_schema_contract" for span in spans))

    def test_task_request_is_the_multi_workstream_webhook_task(self):
        self.assertIn("tenant-scoped", preflight.TASK_REQUEST)
        self.assertIn("migration", preflight.TASK_REQUEST)
        self.assertIn("four named agents", preflight.TASK_REQUEST)
        self.assertIn("parent agent is the only writer", preflight.TASK_REQUEST)

    def test_refuses_to_report_counts_from_an_unpinned_litellm(self):
        with patch.object(preflight, "version", return_value="1.100.1"):
            with self.assertRaisesRegex(RuntimeError, "requires LiteLLM 1.103.0"):
                preflight.preflight(None, None, "openrouter/minimax/minimax-m3", [64_000])


if __name__ == "__main__":
    unittest.main()
