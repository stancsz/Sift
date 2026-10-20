"""Optional named-client compatibility smoke; all requests stay on loopback."""

from __future__ import annotations

import json
import ipaddress
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from time import time

import pytest


def test_openai_python_client_streamed_tool_turn_through_standalone_proxy():
    openai = pytest.importorskip("openai", reason="install the client-smoke extra")
    from sift.cli import _SiftHTTPServer

    observed = []

    class BackendHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(payload)
            self.send_response(200)
            if payload.get("stream"):
                self.send_header("Content-Type", "text/event-stream")
                events = [
                    {"role": "assistant"},
                    {"tool_calls": [{"index": 0, "id": "call_smoke", "type": "function",
                                      "function": {"name": "lookup", "arguments": '{"q":'}}]},
                    {"tool_calls": [{"index": 0,
                                      "function": {"arguments": '"ok"}'}}]},
                    {},
                ]
                chunks = []
                for index, delta in enumerate(events):
                    chunk = {
                        "id": "chatcmpl-sift-smoke", "object": "chat.completion.chunk",
                        "created": int(time()), "model": "local-fixture",
                        "choices": [{"index": 0, "delta": delta,
                                     "finish_reason": "tool_calls" if index == 3 else None}],
                    }
                    chunks.append(f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n".encode())
                body = b"".join(chunks) + b"data: [DONE]\n\n"
            else:
                self.send_header("Content-Type", "application/json")
                body = json.dumps({
                    "id": "chatcmpl-sift-smoke", "object": "chat.completion",
                    "created": int(time()), "model": "local-fixture",
                    "choices": [{"index": 0,
                                 "message": {"role": "assistant", "content": "Tool result received."},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
                }).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
    backend_thread = Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    proxy = _SiftHTTPServer(
        ("127.0.0.1", 0), base_url=f"http://127.0.0.1:{backend.server_port}/v1",
        target=2_000, raw_limit=100_000, api_key_env=None, timeout=3,
    )
    proxy_thread = Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    try:
        client = openai.OpenAI(base_url=f"http://127.0.0.1:{proxy.server_port}/v1",
                               api_key="loopback-smoke")
        tools = [{"type": "function", "function": {
            "name": "lookup", "description": "Lookup",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}},
                           "required": ["q"]},
        }}]

        chunks = list(client.chat.completions.create(
            model="local-fixture", messages=[{"role": "user", "content": "look this up"}],
            tools=tools, stream=True,
        ))
        tool_deltas = [tool_call for chunk in chunks
                       for tool_call in chunk.choices[0].delta.tool_calls or []]
        assert tool_deltas[0].id == "call_smoke"
        assert tool_deltas[0].function.name == "lookup"
        assert "".join(delta.function.arguments or "" for delta in tool_deltas) == '{"q":"ok"}'

        result = client.chat.completions.create(
            model="local-fixture",
            messages=[
                {"role": "user", "content": "look this up"},
                {"role": "assistant", "tool_calls": [{
                    "id": "call_smoke", "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"ok"}'},
                }]},
                {"role": "tool", "tool_call_id": "call_smoke", "content": "found: ok"},
            ],
            tools=tools,
        )
        assert result.choices[0].message.content == "Tool result received."
        assert observed[0]["tools"] == tools
        assert observed[1]["messages"][-2]["tool_calls"][0]["id"] == "call_smoke"
        assert observed[1]["messages"][-1]["tool_call_id"] == "call_smoke"
    finally:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join(timeout=2)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=2)


def test_litellm_python_client_compaction_through_standalone_proxy(monkeypatch):
    litellm = pytest.importorskip("litellm", reason="install the litellm extra")
    from sift.cli import _SiftHTTPServer

    # Keep this compatibility smoke strictly local, including any SDK telemetry.
    monkeypatch.setattr(litellm, "telemetry", False)
    blocked_hosts = []
    real_connect = socket.socket.connect

    def loopback_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host == "localhost"
        if not is_loopback:
            blocked_hosts.append(host)
            raise OSError(f"non-loopback network is disabled in this smoke: {host}")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", loopback_connect)
    observed = []

    class BackendHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(payload)
            body = json.dumps({
                "id": "chatcmpl-litellm-smoke",
                "object": "chat.completion",
                "created": int(time()),
                "model": "local-fixture",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "Buried setting preserved."},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
    backend_thread = Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    proxy = _SiftHTTPServer(
        ("127.0.0.1", 0), base_url=f"http://127.0.0.1:{backend.server_port}/v1",
        target=2_000, raw_limit=100_000, api_key_env=None, timeout=3,
    )
    proxy_thread = Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    messages = []
    for index in range(8):
        messages.append({"role": "user", "content": f"Old status {index}: " + ("routine deployment poll. " * 30)})
        messages.append({"role": "assistant", "content": f"Poll {index} completed without a change."})
    messages.append({"role": "user", "content": "What was the approved readiness delay?"})
    try:
        response = litellm.completion(
            model="openai/local-fixture",
            api_base=f"http://127.0.0.1:{proxy.server_port}/v1",
            api_key="loopback-smoke",
            messages=messages,
            timeout=3,
            num_retries=0,
        )

        assert response.choices[0].message.content == "Buried setting preserved."
        assert len(observed) == 1
        assert len(observed[0]["messages"]) < len(messages)
        assert observed[0]["messages"][-1]["content"] == "What was the approved readiness delay?"
        assert blocked_hosts == []
    finally:
        proxy.shutdown()
        proxy.server_close()
        proxy_thread.join(timeout=2)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=2)
