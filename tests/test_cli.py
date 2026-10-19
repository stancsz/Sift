import json
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from threading import Event, Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from sift.cli import _SiftHTTPServer, _compact_payload, _request_size_estimate, _upstream_url, build_parser, main


class _BackendHandler(BaseHTTPRequestHandler):
    requests = []
    stream_body = b'data: {"choices":[]}\n\ndata: [DONE]\n\n'
    response_body = b'{"choices":[]}'
    stream_gate = None
    response_status = 200

    def do_POST(self):
        self.__class__.requests.append({
            "path": self.path,
            "headers": dict(self.headers.items()),
            "payload": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
        })
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        streaming = self.__class__.requests[-1]["payload"].get("stream")
        body = self.stream_body if streaming else self.response_body
        self.send_response(self.__class__.response_status)
        self.send_header("Content-Type", "text/event-stream" if b"data:" in body else "application/json")
        self.send_header("x-request-id", "fixture-request-123")
        self.send_header("x-ratelimit-remaining-requests", "7")
        self.send_header("Connection", "close, x-internal-hop")
        self.send_header("x-internal-hop", "must-not-cross-proxy")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if streaming and self.__class__.stream_gate is not None:
            split = body.index(b"\n\n") + 2
            self.wfile.write(body[:split])
            self.wfile.flush()
            self.__class__.stream_gate.wait(timeout=2)
            self.wfile.write(body[split:])
            return
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class CliTests(unittest.TestCase):
    def setUp(self):
        _BackendHandler.requests = []
        _BackendHandler.response_body = b'{"choices":[]}'
        _BackendHandler.stream_gate = None
        _BackendHandler.response_status = 200
        self.backend = ThreadingHTTPServer(("127.0.0.1", 0), _BackendHandler)
        self.backend_thread = Thread(target=self.backend.serve_forever, daemon=True)
        self.backend_thread.start()
        self.proxy = _SiftHTTPServer(
            ("127.0.0.1", 0),
            base_url=f"http://127.0.0.1:{self.backend.server_port}/v1",
            target=2_000,
            raw_limit=100_000,
            api_key_env=None,
            timeout=2,
        )
        self.proxy_thread = Thread(target=self.proxy.serve_forever, daemon=True)
        self.proxy_thread.start()

    def tearDown(self):
        self.proxy.shutdown()
        self.proxy.server_close()
        self.proxy_thread.join(timeout=2)
        self.backend.shutdown()
        self.backend.server_close()
        self.backend_thread.join(timeout=2)

    def _send(self, payload, path="/v1/chat/completions"):
        request = Request(
            f"http://127.0.0.1:{self.proxy.server_port}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urlopen(request, timeout=3)

    def test_explicit_estimator_counts_tools_and_preserves_them(self):
        tools = [{"type": "function", "function": {"name": "ReadLog", "parameters": {"type": "object"}}}]
        payload = {
            "model": "local-chat",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": tools,
        }
        forwarded, audit = _compact_payload(payload, target=2000, raw_limit=100_000)
        self.assertEqual(forwarded["tools"], tools)
        self.assertEqual(audit["counting_mode"], "utf8-bytes/2 estimate")
        self.assertFalse(audit["upstream_token_count_guaranteed"])
        self.assertEqual(audit["input_tokens"], _request_size_estimate(payload))

    def test_size_guard_covers_tool_schemas_before_counting(self):
        payload = {
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [{"name": "lookup", "parameters": {"type": "object"}}],
        }
        with patch("sift.cli.DEFAULT_MAX_INPUT_NODES", 8):
            with self.assertRaisesRegex(ValueError, "structural limit"):
                _compact_payload(payload, target=2_000, raw_limit=100_000)

    def test_proxy_compacts_messages_and_preserves_request_fields(self):
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
        payload = {
            "model": "llama3.2",
            "messages": [
                {"role": "user", "content": "old deployment log " * 8_000},
                {"role": "assistant", "content": "log received"},
                {"role": "user", "content": "What happened?"},
            ],
            "tools": tools,
            "temperature": 0,
        }
        with self._send(payload) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["x-sift-compacted"], "true")
            self.assertEqual(response.headers["x-request-id"], "fixture-request-123")
            self.assertEqual(response.headers["x-ratelimit-remaining-requests"], "7")
            self.assertNotIn("x-internal-hop", response.headers)
            self.assertLess(
                int(response.headers["x-sift-estimated-forwarded-tokens"]),
                int(response.headers["x-sift-estimated-input-tokens"]),
            )
            self.assertEqual(json.loads(response.read()), {"choices": []})
        observed = _BackendHandler.requests[-1]
        self.assertEqual(observed["path"], "/v1/chat/completions")
        self.assertEqual(observed["payload"]["tools"], tools)
        self.assertEqual(observed["payload"]["temperature"], 0)
        self.assertEqual(observed["payload"]["messages"][-1], payload["messages"][-1])
        self.assertLess(len(json.dumps(observed["payload"])), len(json.dumps(payload)))

    def test_tool_turn_auth_and_upstream_error_are_forwarded(self):
        _BackendHandler.response_status = 401
        _BackendHandler.response_body = b'{"error":{"message":"unauthorized"}}'
        self.proxy.api_key_env = "SIFT_TEST_API_KEY"
        tool_call = {
            "role": "assistant",
            "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
        }
        tool_result = {"role": "tool", "tool_call_id": "call-1", "content": "found it"}
        payload = {
            "model": "local",
            "messages": [
                {"role": "user", "content": "old log " * 2_000},
                {"role": "user", "content": "Look up the result, then summarize it."},
                tool_call,
                tool_result,
            ],
        }
        with patch.dict("os.environ", {"SIFT_TEST_API_KEY": "test-secret"}):
            with self.assertRaises(HTTPError) as error:
                self._send(payload)
        self.assertEqual(error.exception.code, 401)
        self.assertEqual(json.loads(error.exception.read()), {"error": {"message": "unauthorized"}})
        self.assertEqual(error.exception.headers["x-sift-compacted"], "true")
        error.exception.close()
        observed = _BackendHandler.requests[-1]
        self.assertEqual(observed["headers"]["Authorization"], "Bearer test-secret")
        self.assertEqual(observed["payload"]["messages"][-3:], payload["messages"][-3:])

    def test_streaming_response_is_forwarded(self):
        payload = {"model": "local", "messages": [{"role": "user", "content": "hello"}], "stream": True}
        with self._send(payload) as response:
            self.assertEqual(response.headers["Content-Type"], "text/event-stream")
            self.assertIn(b"data: [DONE]", response.read())

    def test_streaming_forwards_available_events_before_upstream_finishes(self):
        gate = Event()
        _BackendHandler.stream_gate = gate
        payload = {"model": "local", "messages": [{"role": "user", "content": "hello"}], "stream": True}
        with self._send(payload) as response:
            first_event = response.read1(128)
            self.assertIn(b'data: {"choices":[]}', first_event)
            gate.set()
            self.assertIn(b"data: [DONE]", response.read())

    def test_oversized_nonstream_upstream_response_is_rejected(self):
        from unittest.mock import patch

        _BackendHandler.response_body = b"123456789"
        with patch("sift.cli._MAX_UPSTREAM_RESPONSE_BYTES", 8):
            with self.assertRaises(HTTPError) as error:
                self._send({"model": "local", "messages": [{"role": "user", "content": "hello"}]})
        self.assertEqual(error.exception.code, 502)
        self.assertEqual(json.loads(error.exception.read()), {"error": "upstream_response_too_large"})
        error.exception.close()

    def test_unsupported_route_does_not_reach_backend(self):
        with self.assertRaises(HTTPError) as error:
            self._send({"messages": []}, path="/v1/responses")
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        self.assertEqual(_BackendHandler.requests, [])

    def test_estimator_must_be_chosen_explicitly(self):
        parser = build_parser()
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            parser.parse_args(["serve", "--base-url", "http://localhost:11434/v1"])
        self.assertEqual(error.exception.code, 2)

    def test_compatible_base_url_shapes(self):
        request_target = "/v1/chat/completions?client=demo"
        self.assertEqual(
            _upstream_url("http://localhost:11434", request_target),
            "http://localhost:11434/v1/chat/completions?client=demo",
        )
        self.assertEqual(
            _upstream_url("https://gateway.example/api/v1/", request_target),
            "https://gateway.example/api/v1/chat/completions?client=demo",
        )
        self.assertEqual(
            _upstream_url("http://gateway.example/custom", request_target),
            "http://gateway.example/custom/v1/chat/completions?client=demo",
        )

    def test_unsafe_or_ambiguous_base_urls_are_rejected(self):
        for base_url in (
            "http://user:password@localhost:11434/v1",
            "http://localhost:11434/v1?key=secret",
            "http://localhost:11434/v1#fragment",
            "http://localhost:0/v1",
            "http://localhost:65536/v1",
            "http://localhost:not-a-port/v1",
            "http://[::1/v1",
            "file:///tmp/model",
        ):
            with self.subTest(base_url=base_url), self.assertRaises(ValueError):
                _upstream_url(base_url, "/v1/chat/completions")

    def test_invalid_upstream_url_fails_cleanly_at_startup(self):
        stderr = StringIO()
        with patch("sys.argv", [
            "sift", "serve", "--tokenizer", "byte-estimate",
            "--base-url", "http://localhost:65536/v1",
        ]):
            with redirect_stderr(stderr):
                self.assertEqual(main(), 1)
        self.assertIn("base URL must be a valid http(s) URL with a valid port", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
