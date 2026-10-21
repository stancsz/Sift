"""Actual optional OpenAI SDK over local HTTP; no credentials or inference."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import unittest

try:
    import openai
    import httpx
except ImportError:
    openai = httpx = None

from benchmarks.longmemeval_v2_minimax_transport import (
    FIXTURE_API_KEY, MiniMaxTransportError, ReaderCaps, TokenRates,
    create_minimax_reader_client,
)


CAPS = ReaderCaps(100, 8, 108)


def response_body():
    return {
        "id": "synthetic-loopback-response", "object": "chat.completion", "created": 1,
        "model": "minimax/minimax-m3", "provider": "MiniMax",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": r"\boxed{A}"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 3, "total_tokens": 103},
    }


def request_body():
    return {"model": "minimax/minimax-m3", "messages": [{"role": "user", "content": "synthetic fixture"}],
            "max_tokens": 8, "timeout": 2, "temperature": 0, "top_p": 1, "stream": False}


@contextmanager
def fixture(*, body=None, status=200, disconnect=False, pause=False, content_type="application/json"):
    calls = []
    received = threading.Event()
    release = threading.Event()
    payload = body if isinstance(body, bytes) else json.dumps(response_body() if body is None else body).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            content = self.rfile.read(int(self.headers.get("content-length", "0")))
            calls.append({"path": self.path, "body": json.loads(content),
                          "headers": {key.lower(): value for key, value in self.headers.items()}})
            received.set()
            if pause:
                release.wait(3)
            if disconnect:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            if status == 302:
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/redirected")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls, received, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive(), "fixture server did not stop"


def make_client(url, **kwargs):
    return create_minimax_reader_client(base_url=url, api_key=FIXTURE_API_KEY,
                                        caps=CAPS, loopback_fixture=True, timeout_seconds=2, **kwargs)


@unittest.skipIf(openai is None or httpx is None, "optional installed OpenAI SDK/httpx required")
class MiniMaxTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_sdk_serialization_usage_cost_and_cleanup(self):
        body = response_body()
        body["usage"]["cost"] = 0.00001
        original_connect, original_dns = socket.socket.connect, socket.getaddrinfo
        original_request = request_body()
        untouched = deepcopy(original_request)
        with fixture(body=body) as (url, calls, *_):
            client = make_client(url)
            self.assertEqual(client._sdk.max_retries, 0)
            self.assertFalse(client._sdk._client.follow_redirects)
            self.assertFalse(client._sdk._client._trust_env)
            async with client:
                result = await client.chat.completions.create(**original_request)
                self.assertEqual(result.choices[0].message.content, r"\boxed{A}")
                self.assertEqual(result.usage.total_tokens, 103)
                usage = client.last_usage
                self.assertEqual(usage.own_input_cost_usd, Decimal("0.000030"))
                self.assertEqual(usage.own_output_cost_usd, Decimal("0.0000036"))
                self.assertEqual(usage.own_cost_usd, Decimal("0.0000336"))
                self.assertEqual(usage.openrouter_reported_cost_usd, Decimal("0.00001"))
                self.assertIsNone(usage.upstream_inference_cost_usd)
                self.assertFalse(client.poisoned)
            self.assertTrue(client._sdk._client.is_closed)
            await client.close()  # idempotent
            with self.assertRaises(MiniMaxTransportError):
                await client.chat.completions.create(**original_request)
            self.assertEqual(len(calls), 1)
            sent = calls[0]
            self.assertEqual(sent["path"], "/v1/chat/completions")
            self.assertEqual(sent["headers"]["authorization"], f"Bearer {FIXTURE_API_KEY}")
            expected = {key: value for key, value in untouched.items() if key != "timeout"}
            expected["provider"] = {"only": ["minimax"], "allow_fallbacks": False, "require_parameters": True}
            self.assertEqual(sent["body"], expected)
            self.assertEqual(original_request, untouched)
        self.assertIs(socket.socket.connect, original_connect)
        self.assertIs(socket.getaddrinfo, original_dns)

    async def test_missing_provider_cost_is_allowed_and_custom_rates_are_exact(self):
        rates = TokenRates(Decimal("2.5"), Decimal("10"))
        with fixture() as (url, calls, *_):
            async with make_client(url, rates=rates) as client:
                await client.chat.completions.create(**request_body())
                self.assertIsNone(client.last_usage.openrouter_reported_cost_usd)
                self.assertIsNone(client.last_usage.upstream_inference_cost_usd)
                self.assertEqual(client.last_usage.own_cost_usd, Decimal("0.00028"))
                await client.chat.completions.create(**request_body())
                self.assertEqual(len(calls), 2, "valid calls may continue; this is not a run ledger")

    async def test_byok_reported_costs_remain_separate_from_own_calculation(self):
        body = json.dumps(response_body()).encode()
        body = body.replace(b'"total_tokens": 103',
            b'"total_tokens": 103, "cost": 0, "cost_details": {"upstream_inference_cost": 0.00001234567890123456789}')
        with fixture(body=body) as (url, calls, *_):
            async with make_client(url) as client:
                await client.chat.completions.create(**request_body())
                usage = client.last_usage
                self.assertEqual(usage.openrouter_reported_cost_usd, Decimal(0))
                self.assertEqual(usage.upstream_inference_cost_usd, Decimal("0.00001234567890123456789"))
                self.assertEqual(usage.own_cost_usd, Decimal("0.0000336"))
                self.assertEqual(len(calls), 1)

    async def test_upstream_cost_can_be_present_without_openrouter_cost(self):
        body = response_body()
        body["usage"]["cost_details"] = {"upstream_inference_cost": 0}
        with fixture(body=body) as (url, calls, *_):
            async with make_client(url) as client:
                await client.chat.completions.create(**request_body())
                self.assertIsNone(client.last_usage.openrouter_reported_cost_usd)
                self.assertEqual(client.last_usage.upstream_inference_cost_usd, Decimal(0))
                self.assertEqual(len(calls), 1)

    async def test_nullable_reported_costs_are_unknown_and_own_cost_is_available(self):
        # Official OpenRouter reference uses upstream_inference_cost:null.
        for reported, expected_openrouter in (
            ({"cost": 0, "cost_details": {"upstream_inference_cost": None}}, Decimal(0)),
            ({"cost": None, "cost_details": {"upstream_inference_cost": None}}, None),
            ({"cost": None, "cost_details": None}, None),
            ({"cost_details": None}, None),
        ):
            with self.subTest(reported=reported):
                body = response_body()
                body["usage"].update(reported)
                with fixture(body=body) as (url, calls, *_):
                    async with make_client(url) as client:
                        await client.chat.completions.create(**request_body())
                        self.assertEqual(client.last_usage.openrouter_reported_cost_usd, expected_openrouter)
                        self.assertIsNone(client.last_usage.upstream_inference_cost_usd)
                        self.assertEqual(client.last_usage.own_cost_usd, Decimal("0.0000336"))
                        self.assertFalse(client.poisoned)
                        self.assertEqual(len(calls), 1)

    async def test_returned_response_failures_stop_all_further_wire_requests(self):
        cases = {}
        for key, value in (("model", "other/model"), ("provider", "another-provider"),
                           ("id", ""), ("object", "chat.completion.chunk"), ("created", True),
                           ("usage", None), ("choices", [])):
            changed = response_body()
            changed[key] = value
            cases[key] = changed
        for key, value in (("prompt_tokens", True), ("completion_tokens", "3"),
                           ("completion_tokens", -1), ("prompt_tokens", 0),
                           ("prompt_tokens", 101), ("completion_tokens", 9),
                           ("total_tokens", 104), ("cost", -1), ("cost", "0.1"),
                           ("cost", False)):
            changed = response_body()
            changed["usage"][key] = value
            if key in {"prompt_tokens", "completion_tokens"} and type(value) is int and value >= 0:
                changed["usage"]["total_tokens"] = changed["usage"]["prompt_tokens"] + changed["usage"]["completion_tokens"]
            cases[f"{key}:{value!r}"] = changed
        for value in ([], "invalid", False):
            changed = response_body()
            changed["usage"]["cost_details"] = value
            cases[f"malformed cost_details:{value!r}"] = changed
        for value in (False, "0.1", -1, [], {}):
            changed = response_body()
            changed["usage"]["cost"] = 0
            changed["usage"]["cost_details"] = {"upstream_inference_cost": value}
            cases[f"malformed upstream cost:{value!r}"] = changed
        changed = response_body()
        changed["choices"][0]["message"]["content"] = ""
        cases["empty text"] = changed
        cases["malformed JSON"] = b"{"
        valid = json.dumps(response_body()).encode()
        cases["duplicate model"] = valid[:-1] + b', "model": "minimax/minimax-m3"}'
        cases["duplicate usage counter"] = valid.replace(b'"total_tokens": 103', b'"total_tokens": 103, "total_tokens": 103')
        cases["nonfinite JSON"] = valid.replace(b'"total_tokens": 103', b'"total_tokens": 103, "cost": NaN')
        cases["nonfinite upstream cost"] = valid.replace(b'"total_tokens": 103',
            b'"total_tokens": 103, "cost_details": {"upstream_inference_cost": Infinity}')
        for label, body in cases.items():
            with self.subTest(label=label), fixture(body=body) as (url, calls, *_):
                async with make_client(url) as client:
                    for _ in range(2):
                        with self.assertRaises(MiniMaxTransportError) as error:
                            await client.chat.completions.create(**request_body())
                        self.assertNotIn("synthetic fixture", str(error.exception))
                        self.assertNotIn(FIXTURE_API_KEY, str(error.exception))
                    self.assertTrue(client.poisoned)
                    self.assertIsNone(client.last_usage)
                    self.assertEqual(len(calls), 1)
                    self.assertTrue(client._sdk._client.is_closed, "failure must close even before upstream cleanup")
                self.assertTrue(client._sdk._client.is_closed)

    async def test_total_cap_is_enforced_even_when_components_fit(self):
        with fixture() as (url, calls, *_):
            client = create_minimax_reader_client(base_url=url, api_key=FIXTURE_API_KEY,
                caps=ReaderCaps(100, 8, 102), loopback_fixture=True, timeout_seconds=2)
            async with client:
                with self.assertRaises(MiniMaxTransportError):
                    await client.chat.completions.create(**request_body())
                self.assertEqual(len(calls), 1)
                self.assertTrue(client.poisoned)

    async def test_http_and_disconnect_failures_never_retry_or_redirect(self):
        for status, disconnect, content_type in ((302, False, "application/json"),
                (400, False, "application/json"), (429, False, "application/json"),
                (500, False, "application/json"), (200, True, "application/json"),
                (200, False, "text/plain")):
            with self.subTest(status=status, disconnect=disconnect, content_type=content_type):
                with fixture(status=status, disconnect=disconnect, content_type=content_type) as (url, calls, *_):
                    async with make_client(url) as client:
                        for _ in range(2):
                            with self.assertRaises(MiniMaxTransportError):
                                await client.chat.completions.create(**request_body())
                        self.assertEqual(len(calls), 1)
                        self.assertTrue(client.poisoned)

    async def test_queued_call_cannot_pass_a_failed_dispatch(self):
        with fixture(status=500) as (url, calls, *_):
            async with make_client(url) as client:
                results = await asyncio.gather(*(client.chat.completions.create(**request_body()) for _ in range(2)),
                                               return_exceptions=True)
                self.assertTrue(all(isinstance(result, MiniMaxTransportError) for result in results))
                self.assertEqual(len(calls), 1)

    async def test_cancellation_after_wire_stops_following_call(self):
        with fixture(pause=True) as (url, calls, received, release):
            async with make_client(url) as client:
                task = asyncio.create_task(client.chat.completions.create(**request_body()))
                for _ in range(100):
                    if received.is_set():
                        break
                    await asyncio.sleep(0.01)
                self.assertTrue(received.is_set())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(client.poisoned)
                self.assertTrue(client._sdk._client.is_closed)
                with self.assertRaises(MiniMaxTransportError):
                    await client.chat.completions.create(**request_body())
                self.assertEqual(len(calls), 1)
                release.set()

    async def test_invalid_request_settings_are_rejected_before_wire(self):
        with fixture() as (url, calls, *_):
            async with make_client(url) as client:
                invalid = ({"max_tokens": 7}, {"max_tokens": 9}, {"max_tokens": True},
                           {"stream": True}, {"timeout": 3}, {"timeout": False},
                           {"model": "other/model"}, {"extra_body": {"provider": {"allow_fallbacks": True}}},
                           {"extra_body": {"messages": []}}, {"extra_headers": {"Authorization": "other"}})
                for changes in invalid:
                    with self.subTest(changes=changes), self.assertRaises(ValueError):
                        await client.chat.completions.create(**{**request_body(), **changes})
                    self.assertFalse(client.poisoned)
                self.assertEqual(calls, [])
                await client.chat.completions.create(**request_body())
                self.assertEqual(len(calls), 1)


class TransportConstructionTests(unittest.TestCase):
    def test_external_destination_and_fixture_credentials_are_explicit(self):
        invalid = (
            {"base_url": "http://127.0.0.1:80/v1", "api_key": FIXTURE_API_KEY},
            {"base_url": "https://other.invalid/v1", "api_key": "explicit-test-value"},
            {"base_url": "https://openrouter.ai/api/v1/", "api_key": "explicit-test-value"},
            {"base_url": "https://openrouter.ai/api/v1", "api_key": FIXTURE_API_KEY},
            {"base_url": "http://localhost:80/v1", "api_key": FIXTURE_API_KEY, "loopback_fixture": True},
            {"base_url": "http://192.0.2.1:80/v1", "api_key": FIXTURE_API_KEY, "loopback_fixture": True},
            {"base_url": "http://127.0.0.1:80/v1", "api_key": "not-the-fixture-key", "loopback_fixture": True},
            {"base_url": "http://127.0.0.1:80/v1?x=y", "api_key": FIXTURE_API_KEY, "loopback_fixture": True},
            {"base_url": "http://user@127.0.0.1:80/v1", "api_key": FIXTURE_API_KEY, "loopback_fixture": True},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                create_minimax_reader_client(caps=CAPS, **kwargs)

    def test_caps_and_rates_are_type_strict(self):
        for values in ((True, 8, 108), (100, 0, 108), (100, 8, 99), (100, 8, "108")):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ReaderCaps(*values)
        for value in (0.3, True, Decimal("NaN"), Decimal("Infinity"), Decimal("-1")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                TokenRates(value, Decimal(1))


if __name__ == "__main__":
    unittest.main()
