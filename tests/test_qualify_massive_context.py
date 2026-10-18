import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.qualify_massive_context import _provider_events, _route_events, qualify


class MassiveContextQualificationTests(unittest.TestCase):
    def setUp(self):
        self.started = "2026-10-16T12:00:01Z"
        self.client = {"accepted": True, "client_reported_request_usage": [{
            "stream_index": 1, "message_id": "msg_1", "model": "minimax-m3-full",
            "input_tokens": 10_000, "cache_creation_input_tokens": 540_000,
            "cache_read_input_tokens": 0, "output_tokens": 30,
            "provider_reported_input_total": 550_000,
            "started_at": self.started,
        }]}

    def test_full_requires_per_request_provider_usage_matching_raw_band(self):
        logs = "INFO sift_benchmark_selection selector=full model=minimax-m3-full " \
               "request_seq=1 observed_utc_ns=1792152000000000000 target=none " \
               "status=ok input_tokens=559763 forwarded_tokens=559763 " \
               "count_method=litellm_router_1_103_0"
        events = _route_events(logs)
        result = qualify(arm="full", route_events=events, client_report=self.client,
                         request_seq=1, min_raw_tokens=500_000, max_raw_tokens=900_000,
                         target_tokens=None, max_usage_delta_percent=25)
        self.assertTrue(result["qualified"], result)
        self.assertTrue(result["task_accepted"])
        self.assertEqual(result["route_event"]["input_tokens"], 559763)
        self.assertEqual(result["client_reported_request_usage"]["provider_reported_input_total"], 550000)

    def test_sift_provider_input_is_checked_against_forwarded_target_not_raw_floor(self):
        logs = "INFO sift_benchmark_selection selector=sift model=minimax-m3-sift " \
               "request_seq=4 observed_utc_ns=1792152000000000000 target=32768 " \
               "status=ok input_tokens=559763 forwarded_tokens=32100 " \
               "count_method=litellm_router_1_103_0"
        client = {"accepted": True, "client_reported_request_usage": [{
            "stream_index": 1, "model": "minimax-m3-sift", "input_tokens": 30_000,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "provider_reported_input_total": 30_000, "started_at": self.started,
        }]}
        result = qualify(arm="sift", route_events=_route_events(logs), client_report=client,
                         request_seq=4, min_raw_tokens=500_000, max_raw_tokens=900_000,
                         target_tokens=32_768, max_usage_delta_percent=25)
        self.assertTrue(result["qualified"], result)

    def test_missing_usage_and_small_raw_input_fail_qualification(self):
        logs = "INFO sift_benchmark_selection selector=full model=minimax-m3-full " \
               "request_seq=1 observed_utc_ns=1792152000000000000 target=none " \
               "status=ok input_tokens=19496 forwarded_tokens=19496"
        result = qualify(arm="full", route_events=_route_events(logs), client_report={},
                         request_seq=1, min_raw_tokens=500_000, max_raw_tokens=900_000,
                         target_tokens=None, max_usage_delta_percent=25)
        self.assertFalse(result["qualified"])
        self.assertIn("raw_input_outside_qualification_band", result["failures"])
        self.assertIn("missing_per_request_provider_usage", result["failures"])

    def test_body_free_gateway_usage_matches_exact_request_sequence(self):
        route = "INFO sift_benchmark_selection selector=full model=minimax-m3-full " \
                "request_seq=11 observed_utc_ns=1792152000000000000 target=none " \
                "status=ok input_tokens=615784 forwarded_tokens=615784"
        usage = "INFO sift_benchmark_provider_usage arm=full model=minimax-m3-full " \
                "request_seq=11 observed_utc_ns=1792152001000000000 status=ok " \
                "input_tokens=612000 provider_reported_input_total=612000 " \
                "input_total_method=prompt_tokens_includes_cached cache_read_input_tokens=800 " \
                "output_tokens=60"
        result = qualify(arm="full", route_events=_route_events(route),
                         provider_events=_provider_events(usage), client_report={},
                         request_seq=11, min_raw_tokens=500_000, max_raw_tokens=900_000,
                         target_tokens=None, max_usage_delta_percent=25)
        self.assertTrue(result["scale_qualified"], result)
        self.assertFalse(result["qualified"])
        self.assertEqual(612000, result["provider_usage_event"]["provider_reported_input_total"])


if __name__ == "__main__":
    unittest.main()
