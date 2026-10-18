import unittest

from dispatcher import Dispatcher


class Response:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class DispatcherVisibleTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.config = {
            "primary": {"url": "https://hooks.invalid/p", "secret": "secret"},
            "backup": {"url": "https://hooks.invalid/b", "secret": "other"},
        }

    def sender_with(self, *responses):
        queue = list(responses)

        def sender(url, body, headers):
            self.calls.append((url, body, headers))
            value = queue.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        return sender

    def test_only_2xx_marks_delivery_and_repeat_is_duplicate(self):
        dispatcher = Dispatcher(self.config, self.sender_with(Response(503), Response(204)))
        failed = dispatcher.deliver("acme", "evt-1", {"a": 1}, 100)
        self.assertNotEqual("delivered", failed["state"])
        delivered = dispatcher.deliver("acme", "evt-1", {"a": 1}, 101)
        self.assertEqual("delivered", delivered["state"])
        duplicate = dispatcher.deliver("acme", "evt-1", {"a": 1}, 102)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(2, len(self.calls))

    def test_429_honors_retry_after_and_retries_before_success(self):
        dispatcher = Dispatcher(self.config, self.sender_with(
            Response(429, {"Retry-After": "7"}), Response(200)
        ))
        first = dispatcher.deliver("acme", "evt-2", {"a": 1}, 50)
        self.assertEqual(57, first["next_attempt_at"])
        result = dispatcher.deliver("acme", "evt-2", {"a": 1}, 57)
        self.assertEqual("delivered", result["state"])
        self.assertEqual(2, result["attempts"])
        self.assertIsNone(result["next_attempt_at"])

    def test_request_has_canonical_signed_body(self):
        dispatcher = Dispatcher(self.config, self.sender_with(Response(201)))
        dispatcher.deliver("acme", "evt-3", {"z": 2, "a": 1}, 5)
        _, body, headers = self.calls[0]
        self.assertEqual(b'{"a":1,"z":2}', body)
        self.assertTrue(headers.get("X-Webhook-Signature", "").startswith("sha256="))


if __name__ == "__main__":
    unittest.main()
