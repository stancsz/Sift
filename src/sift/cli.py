"""LiteLLM-free command line tools for Sift.

The proxy uses an explicitly selected request-size estimate. It does not know
the upstream model's tokenizer or chat template and cannot guarantee provider
token counts or context-window fit.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .core import (
    DEFAULT_MAX_INPUT_CHARACTERS,
    DEFAULT_MAX_INPUT_NODES,
    DEFAULT_TARGET_TOKENS,
    CompactionError,
    _check_precount_size,
    compact_messages,
)


_CHAT_PATH = "/v1/chat/completions"
_MAX_BODY_BYTES = 16_777_216
_MAX_UPSTREAM_RESPONSE_BYTES = 67_108_864
_HOP_BY_HOP_HEADERS = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade",
})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, _request, _response, _code, _message, _headers, _new_url):
        return None


_UPSTREAM = build_opener(_NoRedirect())


def _request_size_estimate(value: Any) -> int:
    """Return a deliberately named UTF-8 size estimate, not model tokens."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except RecursionError as error:
        raise ValueError("request nesting exceeds the supported JSON depth") from error
    return (len(encoded) + 1) // 2


def _counting_function(fixed_fields: dict[str, Any]):
    def count(messages: list[dict[str, Any]]) -> int:
        request = dict(fixed_fields)
        request["messages"] = messages
        return _request_size_estimate(request)

    return count


def _compact_payload(payload: dict[str, Any], *, target: int, raw_limit: int) -> tuple[dict[str, Any], dict[str, Any]]:
    _check_precount_size(
        payload,
        max_characters=DEFAULT_MAX_INPUT_CHARACTERS,
        max_nodes=DEFAULT_MAX_INPUT_NODES,
    )
    messages = payload.get("messages")
    if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
        raise ValueError("request must contain a messages array of objects")
    fixed_fields = {key: value for key, value in payload.items() if key != "messages"}
    result = compact_messages(
        messages,
        _counting_function(fixed_fields),
        target=target,
        raw_limit=raw_limit,
        max_input_characters=DEFAULT_MAX_INPUT_CHARACTERS,
        max_input_nodes=DEFAULT_MAX_INPUT_NODES,
        protocol="openai",
    )
    forwarded = deepcopy(payload)
    forwarded["messages"] = result.messages
    audit = dict(result.audit)
    audit["counting_mode"] = "utf8-bytes/2 estimate"
    audit["upstream_token_count_guaranteed"] = False
    return forwarded, audit


def _upstream_url(base_url: str, request_target: str) -> str:
    base = urlsplit(base_url)
    if base.scheme not in {"http", "https"} or not base.netloc or base.username or base.password:
        raise ValueError("base URL must be an http(s) URL without embedded credentials")
    if base.query or base.fragment:
        raise ValueError("base URL must not include a query or fragment")
    request = urlsplit(request_target)
    if request.path != _CHAT_PATH:
        raise ValueError("only /v1/chat/completions is supported")
    path = base.path.rstrip("/")
    suffix = "/chat/completions" if path.endswith("/v1") else _CHAT_PATH
    return urlunsplit((base.scheme, base.netloc, path + suffix, request.query, ""))


class _SiftHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], *, base_url: str, target: int,
                 raw_limit: int, api_key_env: str | None, timeout: float) -> None:
        _upstream_url(base_url, _CHAT_PATH)
        self.base_url = base_url
        self.target_tokens = target
        self.raw_limit = raw_limit
        self.api_key_env = api_key_env
        self.upstream_timeout = timeout
        super().__init__(address, _SiftRequestHandler)


class _SiftRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _SiftHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        # Keep proxy logs free of request bodies, which may contain private history.
        sys.stderr.write("sift: " + (format % args) + "\n")

    def _send_json(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self._send_json(404, {"error": "not_found"})
            return
        self._send_json(200, {"ok": True, "service": "sift", "upstream_configured": True})

    def do_POST(self) -> None:
        try:
            upstream_url = _upstream_url(self.server.base_url, self.path)
            size = int(self.headers.get("Content-Length", "-1"))
            if size < 0 or size > _MAX_BODY_BYTES:
                self._send_json(413, {"error": "request_body_too_large"})
                return
            raw = self.rfile.read(size)
            if len(raw) != size:
                self._send_json(400, {"error": "incomplete_request_body"})
                return
            try:
                payload = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                self._send_json(400, {"error": "invalid_json"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "request_json_must_be_an_object"})
                return
            if type(payload.get("stream", False)) is not bool:
                self._send_json(400, {"error": "stream_must_be_boolean"})
                return
            forwarded, audit = _compact_payload(
                payload, target=self.server.target_tokens, raw_limit=self.server.raw_limit,
            )
        except CompactionError as error:
            self._send_json(413, {"error": error.code, "detail": str(error)})
            return
        except (ValueError, TypeError) as error:
            self._send_json(400, {"error": "invalid_request", "detail": str(error)})
            return

        body = json.dumps(forwarded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        streaming = forwarded.get("stream", False)
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if streaming else "application/json",
            "Accept-Encoding": "identity",
        }
        if self.server.api_key_env:
            api_key = os.environ.get(self.server.api_key_env)
            if not api_key:
                self._send_json(500, {
                    "error": "missing_upstream_api_key",
                    "environment_variable": self.server.api_key_env,
                })
                return
            headers["Authorization"] = f"Bearer {api_key}"
        request = Request(upstream_url, data=body, headers=headers, method="POST")
        try:
            with _UPSTREAM.open(request, timeout=self.server.upstream_timeout) as response:
                self._relay(response.status, response.headers, response, audit, stream=streaming)
        except HTTPError as response:
            with response:
                self._relay(response.code, response.headers, response, audit, stream=False)
        except (URLError, TimeoutError, OSError) as error:
            self._send_json(502, {"error": "upstream_unavailable", "detail": str(error)})

    def _relay(self, status: int, headers: Any, upstream: Any,
               audit: dict[str, Any], *, stream: bool) -> None:
        data = None
        if not stream:
            data = upstream.read(_MAX_UPSTREAM_RESPONSE_BYTES + 1)
            if len(data) > _MAX_UPSTREAM_RESPONSE_BYTES:
                self._send_json(502, {"error": "upstream_response_too_large"})
                return
        self.send_response(status)
        connection_tokens = {
            token.strip().lower()
            for token in (headers.get("Connection") or "").split(",")
            if token.strip()
        }
        excluded = (_HOP_BY_HOP_HEADERS | connection_tokens | {
            "content-length", "content-type", "content-encoding", "date", "server",
        })
        for name, value in headers.items():
            if name.lower() not in excluded:
                self.send_header(name, value)
        content_type = headers.get_content_type() if hasattr(headers, "get_content_type") else "application/json"
        self.send_header("Content-Type", content_type)
        if headers.get("Content-Encoding"):
            self.send_header("Content-Encoding", headers.get("Content-Encoding"))
        self.send_header("x-sift-compacted", str(bool(audit.get("compacted"))).lower())
        self.send_header("x-sift-estimated-input-tokens", str(audit["input_tokens"]))
        self.send_header("x-sift-estimated-forwarded-tokens", str(audit["forwarded_tokens"]))
        if stream:
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                # HTTPResponse.read(size) may wait for the full size or EOF.
                # read1 returns currently available bytes so short SSE events
                # reach the client without waiting for a large buffer.
                while chunk := upstream.read1(65_536):
                    self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        assert data is not None
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)


def _serve(args: argparse.Namespace) -> int:
    server = _SiftHTTPServer(
        ("127.0.0.1", args.port), base_url=args.base_url,
        target=args.target, raw_limit=args.raw_limit,
        api_key_env=args.api_key_env, timeout=args.timeout,
    )
    print(
        f"Sift proxy listening at http://127.0.0.1:{args.port}/v1 "
        f"(target={args.target}, "
        f"counting=utf8-bytes/2 estimate; provider counts are not guaranteed)",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _compact(args: argparse.Namespace) -> int:
    raw = Path(args.input).read_bytes() if args.input else sys.stdin.buffer.read(_MAX_BODY_BYTES + 1)
    if len(raw) > _MAX_BODY_BYTES:
        print("input exceeds the 16 MiB CLI limit", file=sys.stderr)
        return 2
    try:
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
            print(f"sift: invalid JSON: {error}", file=sys.stderr)
            return 2
        if isinstance(payload, list):
            payload = {"messages": payload}
        if not isinstance(payload, dict):
            raise ValueError("input must be a messages array or an object containing messages")
        forwarded, audit = _compact_payload(payload, target=args.target, raw_limit=args.raw_limit)
    except (ValueError, CompactionError) as error:
        print(f"sift: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"request": forwarded, "audit": audit}, ensure_ascii=False, indent=2))
    return 0


def _positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sift", description="Compact OpenAI-style chat history without LiteLLM.")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("compact", "serve"):
        child = commands.add_parser(command)
        child.add_argument("--target", type=_positive_int, default=DEFAULT_TARGET_TOKENS,
                           help=f"estimated input budget (default: {DEFAULT_TARGET_TOKENS})")
        child.add_argument("--raw-limit", type=_positive_int, default=1_000_000)
        child.add_argument("--tokenizer", choices=("byte-estimate",), required=True,
                           help="explicit estimate mode; not an upstream tokenizer guarantee")
    compact = commands.choices["compact"]
    compact.add_argument("--input", help="JSON file (otherwise read one JSON value from stdin)")
    compact.set_defaults(run=_compact)
    serve = commands.choices["serve"]
    serve.add_argument("--base-url", required=True, help="configured OpenAI-compatible upstream base URL")
    serve.add_argument("--port", type=int, default=4011)
    serve.add_argument("--api-key-env", help="environment variable containing the upstream API key")
    serve.add_argument("--timeout", type=float, default=120.0)
    serve.set_defaults(run=_serve)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "serve" and not 1 <= args.port <= 65_535:
        parser.error("--port must be between 1 and 65535")
    if args.command == "serve" and args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        return args.run(args)
    except OSError as error:
        print(f"sift: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
