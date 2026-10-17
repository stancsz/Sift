import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_longbench_v2_minimax_hybrid_stage2 as analyzer
import run_longbench_v2_minimax_relation_followup_v3 as v3
import run_longbench_v2_minimax_hybrid_stage2 as stage2_runner


class Stage2AnalyzerIntegrityTests(unittest.TestCase):
    def _stage_row(self, answer_text='{"answer":"A"}'):
        choice = v3._json_choice(answer_text)
        answer_validity = choice in {"A", "B", "C", "D"}
        usage = {"prompt_tokens": 4, "completion_tokens": 3, "cost": 0,
                 "is_byok": True, "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                 "cost_details": {"upstream_inference_cost": 0.0000036,
                                  "upstream_inference_prompt_cost": 0.0000012,
                                  "upstream_inference_completions_cost": 0.0000024}}
        chunk = {"id": "response-1", "model": analyzer.EXPECTED_MODEL, "provider": "Minimax",
                 "choices": [{"index": 0, "delta": {"content": answer_text},
                              "finish_reason": "stop"}], "usage": usage}
        events = [json.dumps(chunk, separators=(",", ":")), "[DONE]"]
        messages = [{"role": "user", "content": "question"}]
        request = {"model": analyzer.EXPECTED_MODEL, "messages": messages,
                   "temperature": 0.1, "top_p": 0.8, "seed": 10, "max_tokens": 128,
                   "reasoning": {"enabled": False}, "response_format": {"type": "json_object"},
                   "stream": True, "stream_options": {"include_usage": True},
                   "provider": {"only": ["minimax"], "allow_fallbacks": False}}
        digest = v3._request_hash(request)
        return {
            "raw_sse_events": events, "raw_response_body": "\n".join(events),
            "http_status": 200, "model": analyzer.EXPECTED_MODEL, "provider": "Minimax",
            "response_id": "response-1", "finish_reason": "stop", "usage": usage,
            "answer": answer_text[:500], "choice": choice,
            "normal": True,
            "valid_structured_choice": answer_validity,
            "answer_validity": "valid" if answer_validity else "invalid_or_incomplete",
            "expected": "A",
            "correct": answer_validity and choice == "A", "failure": None, "request": request,
            "request_sha256": digest, "request_payload_sha256": digest,
            "request_messages_sha256": v3._messages_hash(messages),
            "generation_seed": 10, "target_tokens": 32768, "arm": analyzer.EXPECTED_ARM,
            "local_rendered_prompt_tokens": 4, "provider_local_input_token_ratio": 1.0,
        }

    def test_raw_sse_is_the_answer_and_flags_are_derived(self):
        row = self._stage_row()
        parsed = analyzer._raw_stream(row, label="sample", json_answer=True)
        self.assertEqual(parsed["choice"], "A")
        self.assertTrue(parsed["correct"])
        row["choice"] = "B"
        with self.assertRaises(analyzer.AnalysisError):
            analyzer._raw_stream(row, label="tampered", json_answer=True)

    def test_completed_billable_invalid_answer_is_validly_scored_incorrect(self):
        row = self._stage_row('{"answer":"Z"}')
        parsed = analyzer._raw_stream(row, label="invalid-choice", json_answer=True)
        self.assertFalse(parsed["valid"])
        self.assertFalse(parsed["correct"])
        self.assertFalse(row["answer_validity"] == "valid")
        # The runner's strict sample flag is false for a malformed answer even
        # though the HTTP response and usage receipt remain operationally valid.
        row["strict_sample_valid"] = False
        analyzer._validate_strict_sample_valid(row, parsed, label="invalid-choice")
        row["strict_sample_valid"] = True
        with self.assertRaises(analyzer.AnalysisError):
            analyzer._validate_strict_sample_valid(row, parsed, label="tampered-invalid-choice")

    def test_saved_answer_is_a_500_character_prefix_but_score_uses_full_stream(self):
        raw = '{"answer":"A"}' + (" " * 600)
        row = self._stage_row(raw)
        parsed = analyzer._raw_stream(row, label="long-answer", json_answer=True)
        self.assertEqual(len(row["answer"]), 500)
        self.assertEqual(parsed["choice"], "A")
        self.assertTrue(parsed["correct"])

    def test_stage_request_protocol_is_checked(self):
        row = self._stage_row()
        analyzer._validate_stage_request(row, label="sample")
        row["request"]["top_p"] = 0.9
        with self.assertRaises(analyzer.AnalysisError):
            analyzer._validate_stage_request(row, label="tampered")

    def test_historical_receipt_does_not_reprice_cached_usage_at_stage2_rates(self):
        row = {"job_id": "historical", "usage": {
            "prompt_tokens": 100, "completion_tokens": 2, "is_byok": True,
            "cost_details": {"upstream_inference_cost": 0.01,
                             "upstream_inference_prompt_cost": 0.009,
                             "upstream_inference_completions_cost": 0.001},
            "prompt_tokens_details": {"cached_tokens": 90, "cache_write_tokens": 0},
        }}
        metrics = analyzer._metric_receipts([row], 0.3, 1.2, None,
                                            verify_price_reconstruction=False)
        self.assertEqual(metrics["upstream_reported_cache_inclusive_cost_usd"], 0.01)
        self.assertEqual(metrics["per_row_prompt_and_completion_cost_reconstruction_checks"], 0)

    def test_route_binding_checks_frozen_path_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            route_path = Path(directory) / "route.json"
            route_path.write_text('{"route":"pinned"}', encoding="utf-8")
            digest = analyzer.sha256(route_path)
            stage = {"route_metadata_path": str(route_path), "route_metadata_sha256": digest,
                     "source_hashes": {"route_metadata_sha256": digest}}
            analyzer._validate_route_binding(stage, route_path)
            stage["route_metadata_sha256"] = "0" * 64
            with self.assertRaises(analyzer.AnalysisError):
                analyzer._validate_route_binding(stage, route_path)

    def test_source_binding_covers_every_runner_declared_path(self):
        declared = {key: analyzer.sha256(path) for key, path in stage2_runner.SOURCE_PATHS.items()}
        stage = {"source_hashes": declared}
        result = {"source_hashes": dict(declared)}
        analyzer._validate_source_binding(result, stage)
        changed = next(iter(declared))
        result["source_hashes"][changed] = "0" * 64
        with self.assertRaises(analyzer.AnalysisError):
            analyzer._validate_source_binding(result, stage)


if __name__ == "__main__":
    unittest.main()
