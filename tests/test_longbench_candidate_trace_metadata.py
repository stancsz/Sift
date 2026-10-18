from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import benchmarks.audit_longbench_v2_candidate_trace_metadata as audit_module
from benchmarks.audit_longbench_v2_candidate_trace_metadata import (
    StreamingWhitelistJSON,
    UnsafeJSON,
    _find_receipt_records,
    _receipt_fields,
    build_audit,
)


class CandidateTraceMetadataParserTests(unittest.TestCase):
    def test_forbidden_sentinels_are_skipped_and_safe_usage_is_retained(self) -> None:
        forbidden = "SENTINEL_MUST_NOT_SURFACE_5e0d7f"
        source = json.dumps(
            {
                "run": {"model": "minimax/minimax-m3", "status": "complete"},
                "results": [
                    {
                        "case_id": "candidate-1",
                        "repeat": 2,
                        "arm": "default",
                        "provider": "Minimax",
                        "usage": {
                            "prompt_tokens": 1234,
                            "cost": 0,
                            "prompt_tokens_details": {
                                "cached_tokens": 120,
                                "cache_write_tokens": 45,
                                "provider_extension": forbidden,
                            },
                            "cost_details": {
                                "upstream_inference_cost": 0.004,
                                "upstream_inference_prompt_cost": 0.003,
                                "upstream_inference_completions_cost": 0.001,
                                "unapproved_detail": forbidden,
                            },
                        },
                        "response": {
                            "usage": {"completion_tokens": 7, "cost_usd": 0.005},
                            "body": forbidden,
                            "choices": [{"choice": forbidden}],
                        },
                        "answer": forbidden,
                        "expected": forbidden,
                        "correct": forbidden,
                        "raw_sse": forbidden,
                        "raw_error": forbidden,
                        "unapproved_field": {"secret": forbidden},
                    }
                ],
            }
        )
        tree = StreamingWhitelistJSON(io.StringIO(source)).read()
        encoded = json.dumps(tree)
        self.assertNotIn(forbidden, encoded)
        for key in ("answer", "expected", "correct", "raw_sse", "raw_error", "body", "choices", "choice", "unapproved_field"):
            self.assertNotIn(f'"{key}"', encoded)
        rows: list[dict] = []
        _find_receipt_records(tree, rows)
        self.assertEqual(len(rows), 1)
        receipt = _receipt_fields(rows[0])
        self.assertEqual(receipt["case_id"], "candidate-1")
        self.assertEqual(receipt["arm"], "default_sift")
        self.assertEqual(receipt["usage_prompt_tokens"], 1234)
        self.assertEqual(receipt["usage_cost"], 0)
        self.assertEqual(receipt["prompt_tokens_details_cached_tokens"], 120)
        self.assertEqual(receipt["prompt_tokens_details_cache_write_tokens"], 45)
        self.assertEqual(receipt["cost_details_upstream_inference_cost"], 0.004)
        self.assertEqual(receipt["cost_details_upstream_inference_prompt_cost"], 0.003)
        self.assertEqual(receipt["cost_details_upstream_inference_completions_cost"], 0.001)
        self.assertNotIn("unapproved_detail", json.dumps(receipt))

    def test_skipped_large_nested_payload_is_not_retained(self) -> None:
        sentinel = "NO_RETAIN_" + ("x" * 20000)
        source = '{"samples":[{"case_id":"c","repeat":1,"arm":"full","response":{"body":' + json.dumps(sentinel) + '},"answer":' + json.dumps(sentinel) + '}]} '
        tree = StreamingWhitelistJSON(io.StringIO(source)).read()
        self.assertNotIn(sentinel, repr(tree))
        self.assertEqual(tree, {"samples": [{"case_id": "c", "repeat": 1, "arm": "full"}]})

    def test_malformed_json_fails_closed(self) -> None:
        with self.assertRaises(UnsafeJSON):
            StreamingWhitelistJSON(io.StringIO('{"results":[{"answer":"ignored", bad: 1}]}')).read()

    def test_cost_details_reject_nonnumeric_values(self) -> None:
        source = '{"results":[{"case_id":"c","repeat":1,"arm":"full","usage":{"cost_details":{"upstream_inference_cost":"not-numeric"}}}]}'
        with self.assertRaises(UnsafeJSON):
            StreamingWhitelistJSON(io.StringIO(source)).read()

    def test_cache_token_details_reject_nonnumeric_values(self) -> None:
        source = '{"results":[{"case_id":"c","repeat":1,"arm":"full","usage":{"prompt_tokens_details":{"cached_tokens":"not-numeric"}}}]}'
        with self.assertRaises(UnsafeJSON):
            StreamingWhitelistJSON(io.StringIO(source)).read()

    def test_build_audit_counts_paired_fixture_without_leaking_answers(self) -> None:
        # Keep the unit suite independent of large, answer-bearing local run
        # artifacts. The production audit remains available as an opt-in script.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            field_ids = [f"field-{index}" for index in range(9)]
            query_ids = [f"query-{index}" for index in range(9)]
            union_path = Path("candidate-union.json")
            historical_path = Path("results/historical.json")
            pilot_path = Path("results/pilot.json")
            manifest_path = Path("historical-manifest.json")
            preflight_path = Path("pilot-preflight.json")

            (root / union_path).write_text(json.dumps({
                "ids": {"field_pruning": field_ids, "query_directed": query_ids}
            }), encoding="utf-8")
            (root / historical_path).parent.mkdir(parents=True)
            historical = [
                {"case_id": case_id, "repeat": 1, "arm": arm, "answer": "SECRET_ANSWER"}
                for case_id in (field_ids + query_ids)[:14]
                for arm in ("full", "default_sift")
            ]
            pilot = [
                {"case_id": case_id, "repeat": 2, "arm": arm, "answer": "SECRET_ANSWER"}
                for case_id in field_ids[:4]
                for arm in ("full", "default_sift", "field_pruning")
            ]
            (root / historical_path).write_text(json.dumps({"results": historical}), encoding="utf-8")
            (root / pilot_path).write_text(json.dumps({"results": pilot}), encoding="utf-8")
            (root / manifest_path).write_text(json.dumps({
                "provider_endpoint": {
                    "provider_name": "MiniMax",
                    "provider_slug": "minimax",
                    "model_endpoint_id": "fixture-endpoint",
                    "request_provider_policy": {"allow_fallbacks": False, "only": ["minimax"]},
                }
            }), encoding="utf-8")
            (root / preflight_path).write_text(json.dumps({
                "model": "minimax/minimax-m3",
                "config": {
                    "provider_policy": {"only": ["minimax"], "allow_fallbacks": False},
                    "workers": 1,
                    "repeats": 1,
                    "arms": ["full", "default_sift", "field_pruning"],
                    "cli_seed": 7,
                    "randomization": "fixture",
                    "generation_seed_formula": "fixture-{case_id}-{repeat}-{arm}",
                },
            }), encoding="utf-8")

            with (
                patch.object(audit_module, "ROOT", root),
                patch.object(audit_module, "UNION_PATH", union_path),
                patch.object(audit_module, "SOURCES", (historical_path, pilot_path)),
                patch.object(audit_module, "HISTORICAL_MANIFEST", manifest_path),
                patch.object(audit_module, "PILOT_PREFLIGHT", preflight_path),
            ):
                audit = build_audit()

        self.assertEqual(audit["summary"]["candidate_ids"], 18)
        self.assertEqual(audit["summary"]["ids_with_historical_full_default"], 14)
        self.assertEqual(audit["summary"]["ids_with_concurrent_field_pruning_triplets"], 4)
        self.assertEqual(audit["summary"]["ids_with_query_directed_candidate_receipts"], 0)
        self.assertEqual(audit["summary"]["ids_with_no_receipts"], 4)
        encoded = json.dumps(audit)
        for key in ("answer", "expected", "correct", "choice", "response", "raw_sse", "raw_error"):
            self.assertNotIn(f'"{key}"', encoded)
        self.assertNotIn("SECRET_ANSWER", encoded)


if __name__ == "__main__":
    unittest.main()
