"""Offline protocol checks for the 500K+ Sift selector preflight."""

import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks import preflight_massive_context_sift as preflight
from benchmarks import agents as native_agents


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

    def test_multi_domain_fixture_has_hashed_evidence_spans_across_all_domains(self):
        root = Path(__file__).resolve().parents[1]
        gold = root / "benchmarks/agent_gold/multi_domain_incident_swarm_500k/evidence.json"
        spans = preflight.load_required_spans(gold)
        self.assertEqual(8, len(spans))
        self.assertEqual({"dep_000000", "iam_inc_003001", "net_005999", "pay_008997",
                          "tic_011999", "run_012000", "dep_017999", "dash_88421"},
                         {span.span_id for span in spans})

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
        cases = ("webhook_swarm_500k", "multi_domain_incident_swarm_500k")
        for fixture in cases:
            with self.subTest(fixture=fixture):
                case = root / "benchmarks/agent_cases" / fixture
                gold = root / "benchmarks/agent_gold" / fixture
                task_request = preflight.resolve_task_request(case / "swarm_context.md")
                self.assertGreater(len(task_request), 100)
                result = preflight.preflight(
                    case / "swarm_context.md", gold, "openrouter/minimax/minimax-m3",
                    [64_000, 48_000, 32_000, 24_000, 16_000], task_request,
                )

                self.assertGreaterEqual(result["raw_message_tokens"], 500_000)
                self.assertEqual(result["raw_message_tokens"], result["full_arm_forwarded_tokens"])
                self.assertEqual([64_000, 48_000, 32_000, 24_000, 16_000],
                                 [row["target_tokens"] for row in result["targets"]])
                self.assertTrue(all(row["scale_and_budget_passed"] for row in result["targets"]))
                self.assertTrue(all(row["audit"]["input_tokens"] >= 500_000
                                    for row in result["targets"]))
                if fixture == "multi_domain_incident_swarm_500k":
                    self.assertTrue(all(row["exact_span_retention_diagnostic"]["all_retained"]
                                        for row in result["targets"]))

    def test_cli_defaults_to_existing_multidomain_fixture_and_its_task(self):
        self.assertEqual(preflight.DEFAULT_CASE / "swarm_context.md",
                         preflight.REPOSITORY_ROOT / "benchmarks/agent_cases/multi_domain_incident_swarm_500k/swarm_context.md")
        self.assertEqual(preflight.DEFAULT_GOLD,
                         preflight.REPOSITORY_ROOT / "benchmarks/agent_gold/multi_domain_incident_swarm_500k")
        task = (preflight.DEFAULT_CASE / "task.md").read_text(encoding="utf-8")
        self.assertIn("cross-domain swarm task", task)
        self.assertIn("four distinct agent calls", task)

    def test_task_resolver_prefers_frozen_task_then_case_readme(self):
        root = Path(__file__).resolve().parents[1] / "benchmarks/agent_cases"
        webhook = root / "webhook_swarm_500k"
        incident = root / "multi_domain_incident_swarm_500k"
        self.assertEqual((webhook / "README.md").read_text(encoding="utf-8"),
                         preflight.resolve_task_request(webhook / "swarm_context.md"))
        self.assertEqual((incident / "task.md").read_text(encoding="utf-8"),
                         preflight.resolve_task_request(incident / "swarm_context.md"))

    def test_multidomain_preflight_prompt_matches_native_runner_prompt_byte_for_byte(self):
        case = preflight.DEFAULT_CASE
        task_text = preflight.resolve_task_request(case / "swarm_context.md")
        expected = native_agents.build_initial_prompt(
            task_text,
            editable=[],
            allowed_outputs=["incident_report.json", "remediation_plan.md"],
            require_agent_calls=4,
            max_agent_calls=4,
            profile=native_agents.SWARM_PROFILES["multi-domain-incident"],
            test_python=native_agents.TOOL_TEST_PYTHON,
        )
        actual = preflight.build_experiment_prompt(case / "swarm_context.md", task_text)
        self.assertEqual(expected.encode("utf-8"), actual.encode("utf-8"))
        self.assertEqual(
            hashlib.sha256(expected.encode("utf-8")).hexdigest(),
            hashlib.sha256(actual.encode("utf-8")).hexdigest(),
        )
        for required in (
            "canonical claim sentences",
            "exact_payload_received_by_external_sink",
            "deployment_auditor, identity_auditor, network_payment_auditor, response_auditor",
            "incident_report.json, remediation_plan.md",
            f"{native_agents.TOOL_TEST_PYTHON} -m unittest -q",
        ):
            self.assertIn(required, actual)



if __name__ == "__main__":
    unittest.main()
