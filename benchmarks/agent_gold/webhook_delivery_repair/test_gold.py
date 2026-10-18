"""Independent acceptance checks for the public development fixture."""

import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path

CASE = Path(__file__).resolve().parents[2] / "agent_cases" / "webhook_delivery_repair"
sys.path.insert(0, str(CASE))
from dispatcher import Dispatcher  # noqa: E402


class Response:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class GoldDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.config = {
            "primary": {"url": "https://hooks.invalid/p", "secret": "s3cr3t"},
            "backup": {"url": "https://hooks.invalid/b", "secret": "rotated"},
        }

    def dispatcher(self, *outcomes):
        queue = list(outcomes)

        def sender(url, body, headers):
            self.calls.append((url, body, headers))
            value = queue.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        return Dispatcher(self.config, sender)

    def test_signature_uses_compact_sorted_json_and_hmac_sha256(self):
        dispatcher = self.dispatcher(Response(503), Response(200))
        result = dispatcher.deliver("acme", "e1", {"z": 2, "a": 1}, 100)
        body = b'{"a":1,"z":2}'
        expected = "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
        dispatcher.deliver("acme", "e1", {"z": 2, "a": 1}, 101)
        self.assertEqual(body, self.calls[0][1])
        self.assertEqual(expected, self.calls[0][2]["X-Webhook-Signature"])
        self.assertEqual((body, expected),
                         (self.calls[1][1], self.calls[1][2]["X-Webhook-Signature"]))
        self.assertEqual(expected, result["signature"])

    def test_same_event_id_is_scoped_by_tenant(self):
        dispatcher = self.dispatcher(Response(200), Response(200))
        dispatcher.deliver("acme", "shared", {"x": 1}, 0)
        other_tenant = dispatcher.deliver("beta", "shared", {"x": 1}, 1)
        self.assertFalse(other_tenant["duplicate"])
        self.assertEqual(2, len(self.calls))

    def test_delivered_pair_stays_deduplicated_after_endpoint_config_rotation(self):
        dispatcher = self.dispatcher(Response(204), Response(200))
        dispatcher.deliver("acme", "rotate", {"x": 1}, 0)
        self.config["primary"] = self.config["backup"]
        again = dispatcher.deliver("acme", "rotate", {"x": 1}, 1)
        self.assertTrue(again["duplicate"])
        self.assertEqual("delivered", again["state"])
        self.assertEqual(1, len(self.calls))

    def test_503_uses_exponential_schedule_and_does_not_run_early(self):
        dispatcher = self.dispatcher(Response(503), Response(200))
        retry = dispatcher.deliver("acme", "backoff", {}, 40)
        self.assertEqual(("retry", 1, 41),
                         (retry["state"], retry["attempts"], retry["next_attempt_at"]))
        early = dispatcher.deliver("acme", "backoff", {}, 40)
        self.assertEqual(1, early["attempts"])
        self.assertEqual(1, len(self.calls))
        done = dispatcher.deliver("acme", "backoff", {}, 41)
        self.assertEqual(("delivered", 2, None),
                         (done["state"], done["attempts"], done["next_attempt_at"]))

    def test_network_exception_is_retryable(self):
        dispatcher = self.dispatcher(OSError("temporary"), Response(202))
        first = dispatcher.deliver("acme", "network", {}, 10)
        self.assertEqual(("retry", 11), (first["state"], first["next_attempt_at"]))
        second = dispatcher.deliver("acme", "network", {}, 11)
        self.assertEqual("delivered", second["state"])
        self.assertEqual(2, second["attempts"])

    def test_429_retry_after_is_capped_at_thirty_seconds(self):
        dispatcher = self.dispatcher(Response(429, {"Retry-After": "90"}))
        result = dispatcher.deliver("acme", "throttle", {}, 500)
        self.assertEqual(("retry", 530), (result["state"], result["next_attempt_at"]))

    def test_408_is_retryable(self):
        dispatcher = self.dispatcher(Response(408))
        result = dispatcher.deliver("acme", "timeout", {}, 200)
        self.assertEqual(("retry", 201), (result["state"], result["next_attempt_at"]))

    def test_permanent_4xx_is_not_retried_and_409_is_not_success(self):
        dispatcher = self.dispatcher(Response(409), Response(400))
        conflict = dispatcher.deliver("acme", "conflict", {}, 0)
        self.assertNotEqual("delivered", conflict["state"])
        self.assertEqual("permanent_failure", conflict["state"])
        bad_request = dispatcher.deliver("acme", "bad", {}, 0)
        self.assertEqual("permanent_failure", bad_request["state"])
        self.assertEqual(2, len(self.calls))

    def test_four_total_retryable_attempts_end_in_dead_letter(self):
        dispatcher = self.dispatcher(*(Response(500) for _ in range(4)))
        expected_due = [1, 3, 7]
        now = 0
        for due in expected_due:
            result = dispatcher.deliver("acme", "exhaust", {}, now)
            self.assertEqual("retry", result["state"])
            self.assertEqual(due, result["next_attempt_at"])
            now = due
        final = dispatcher.deliver("acme", "exhaust", {}, now)
        self.assertEqual(("dead_letter", 4, None),
                         (final["state"], final["attempts"], final["next_attempt_at"]))
        self.assertEqual(4, len(self.calls))


if __name__ == "__main__":
    unittest.main()
