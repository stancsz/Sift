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

    def test_exact_span_loss_is_diagnostic_not_a_scale_or_budget_failure(self):
        def compact(_router, request, *, target, **_kwargs):
            raw = 560_000
            forwarded = raw if target == 1_000_000 else 31_000
            return {"metadata": {"sift": {"input_tokens": raw,
                                             "forwarded_tokens": forwarded}},
                    "messages": request["messages"]}

        with (patch.object(preflight, "version", return_value="1.103.0"),
              patch.object(preflight, "Router"),
              patch.object(Path, "read_bytes", return_value=b"packet"),
              patch.object(Path, "is_file", return_value=True),
              patch.object(preflight, "load_required_spans", return_value=(object(),)),
              patch.object(preflight, "compact_proxy_request", side_effect=compact),
              patch.object(preflight, "audit_retention", return_value={"gold_fact": "omitted"})):
            result = preflight.preflight(Path("packet"), Path("gold"),
                                         "openrouter/minimax/minimax-m3", [32_000])

        row = result["targets"][0]
        self.assertTrue(row["scale_and_budget_passed"])
        self.assertEqual({"retained": 0, "total": 1, "all_retained": False},
                         row["exact_span_retention_diagnostic"])

    def test_task_without_span_manifest_still_gets_scale_and_budget_preflight(self):
        def compact(_router, request, *, target, **_kwargs):
            raw = 560_000
            return {"metadata": {"sift": {"input_tokens": raw,
                                             "forwarded_tokens": 31_000}},
                    "messages": request["messages"]}

        with (patch.object(preflight, "version", return_value="1.103.0"),
              patch.object(preflight, "Router"),
              patch.object(Path, "read_bytes", return_value=b"packet"),
              patch.object(preflight, "compact_proxy_request", side_effect=compact)):
            result = preflight.preflight(Path("packet"), Path("missing-gold"),
                                         "openrouter/minimax/minimax-m3", [32_000])

        row = result["targets"][0]
        self.assertTrue(row["scale_and_budget_passed"])
        self.assertIsNone(row["exact_span_retention_diagnostic"])

    def test_each_swarm_task_reaches_500k_raw_before_sift_targets(self):
        root = Path(__file__).resolve().parents[1]
        cases = (
            ("webhook_swarm_500k", preflight.TASK_REQUEST),
            ("multi_domain_incident_swarm_500k", None),
        )
        for fixture, task_request in cases:
            with self.subTest(fixture=fixture):
                case = root / "benchmarks/agent_cases" / fixture
                gold = root / "benchmarks/agent_gold" / fixture
                kwargs = {}
                if task_request is None:
                    kwargs["task_request"] = (case / "task.md").read_text(encoding="utf-8")
                result = preflight.preflight(
                    case / "swarm_context.md", gold, "openrouter/minimax/minimax-m3",
                    [64_000, 48_000, 32_000, 24_000, 16_000], **kwargs,
                )

                self.assertGreaterEqual(result["raw_message_tokens"], 500_000)
                self.assertEqual(result["raw_message_tokens"], result["full_arm_forwarded_tokens"])
                self.assertEqual([64_000, 48_000, 32_000, 24_000, 16_000],
                                 [row["target_tokens"] for row in result["targets"]])
                self.assertTrue(all(row["scale_and_budget_passed"] for row in result["targets"]))
                self.assertTrue(all(row["audit"]["input_tokens"] >= 500_000
                                    for row in result["targets"]))



if __name__ == "__main__":
    unittest.main()
