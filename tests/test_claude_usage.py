import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.claude_usage import stream_request_usage


class ClaudeStreamUsageTests(unittest.TestCase):
    def test_records_body_free_per_response_usage_and_cache_fields(self):
        events = [
            {"type": "stream_event", "timestamp": "2026-10-16T12:00:00Z",
             "event": {"type": "message_start", "message": {
                 "id": "msg_1", "model": "minimax-m3-full",
                 "usage": {"input_tokens": 0, "output_tokens": 0,
                            "cache_creation_input_tokens": 500100,
                            "cache_read_input_tokens": 0},
                 "content": [{"type": "text", "text": "do not retain"}],
             }}},
            {"type": "stream_event", "event": {"type": "message_delta", "usage": {
                "input_tokens": 521, "output_tokens": 18,
                "cache_creation_input_tokens": 500100,
                "cache_read_input_tokens": 0,
            }}},
            {"type": "stream_event", "timestamp": "2026-10-16T12:00:01Z",
             "event": {"type": "message_stop"}},
        ]

        result = stream_request_usage(events)

        self.assertEqual(result, [{
            "stream_index": 1,
            "message_id": "msg_1",
            "model": "minimax-m3-full",
            "input_tokens": 521,
            "cache_creation_input_tokens": 500100,
            "cache_read_input_tokens": 0,
            "output_tokens": 18,
            "provider_reported_input_total": 500621,
            "input_total_method": "input+cache_creation+cache_read",
            "started_at": "2026-10-16T12:00:00Z",
            "finished_at": "2026-10-16T12:00:01Z",
        }])
        self.assertNotIn("do not retain", json.dumps(result))

    def test_keeps_input_total_unknown_if_provider_omits_a_cache_field(self):
        events = [
            {"type": "stream_event", "event": {"type": "message_start", "message": {
                "id": "msg_2", "model": "minimax-m3-sift", "usage": {"input_tokens": 0},
            }}},
            {"type": "stream_event", "event": {"type": "message_delta", "usage": {
                "input_tokens": 10, "output_tokens": 2,
            }}},
            {"type": "stream_event", "event": {"type": "message_stop"}},
        ]
        result = stream_request_usage(events)
        self.assertIsNone(result[0]["provider_reported_input_total"])


if __name__ == "__main__":
    unittest.main()
