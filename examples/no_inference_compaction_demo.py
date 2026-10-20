"""Exercise Sift's local proxy with a deterministic backend and no model."""

from __future__ import annotations

import argparse
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from examples.ollama_compaction_demo import answers_buried_setting, build_messages


_EXPECTED_ANSWER = (
    "The readiness probe changed from initialDelaySeconds=5 to the "
    "operator-approved initialDelaySeconds=25 because the old delay did not allow sufficient time."
)
_MISSING_ANSWER = "The compacted request did not include the buried readiness-probe setting."


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, _request, _response, _code, _message, _headers, _new_url):
        return None


_LOCAL_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def _validate_local_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise argparse.ArgumentTypeError("URL must be a valid loopback HTTP URL") from error
    if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or port == 0):
        raise argparse.ArgumentTypeError("URL must be a loopback HTTP URL without credentials, query, or fragment")
    host = parsed.hostname
    try:
        is_loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host == "localhost"
    if not is_loopback:
        raise argparse.ArgumentTypeError("URL host must be localhost or a loopback IP address")
    return value


def _fixture_answer(messages: object) -> tuple[bool, str]:
    if not isinstance(messages, list):
        messages = []
    content = "\n".join(
        message.get("content", "")
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("content", ""), str)
    )
    retained_setting = answers_buried_setting(content)
    return retained_setting, _EXPECTED_ANSWER if retained_setting else _MISSING_ANSWER


class _FixtureHandler(BaseHTTPRequestHandler):
    server: "_FixtureServer"

    def log_message(self, _format: str, *_args: object) -> None:
        # Keep request contents local and out of terminal logs.
        pass

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= size <= 16_777_216:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(size))
            messages = payload.get("messages", []) if isinstance(payload, dict) else []
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return

        self.server.retained_setting, answer = _fixture_answer(messages)
        body = json.dumps({
            "id": "chatcmpl-no-inference-fixture",
            "object": "chat.completion",
            "model": "no-inference-fixture",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                         "finish_reason": "stop"}],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    retained_setting = False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", type=_validate_local_url, default="http://127.0.0.1:4011/v1/chat/completions",
                        help="local Sift Chat Completions URL")
    parser.add_argument("--stub-port", type=int, default=4020,
                        help="loopback port for the deterministic backend fixture")
    parser.add_argument("--timeout", type=float, default=10,
                        help="seconds to wait for Sift's response")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    try:
        fixture = _FixtureServer(("127.0.0.1", args.stub_port), _FixtureHandler)
    except OSError as error:
        print(f"Could not start the local no-inference fixture: {error}")
        return 1
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({
            "model": "no-inference-fixture",
            "messages": build_messages(),
        }).encode("utf-8")
        request = Request(args.url, data=body, headers={"Content-Type": "application/json"})
        try:
            with _LOCAL_OPENER.open(request, timeout=args.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                compacted = response.headers.get("x-sift-compacted", "false")
                estimated = response.headers.get("x-sift-estimated-input-tokens", "unknown")
                forwarded = response.headers.get("x-sift-estimated-forwarded-tokens", "unknown")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            print(f"Sift returned HTTP {error.code}: {detail}")
            return 1
        except (URLError, TimeoutError) as error:
            print(f"Could not reach Sift at {args.url}: {error}")
            return 1

        choices = result.get("choices", [])
        answer = choices[0].get("message", {}).get("content") if choices else None
        if compacted.lower() != "true":
            print(f"Sift reported x-sift-compacted={compacted!r}; expected 'true'.")
            print(f"estimated input: {estimated}; forwarded: {forwarded}")
            return 1
        if not fixture.retained_setting or not answer or not answers_buried_setting(answer):
            print("The local fixture did not confirm the buried setting survived compaction.")
            return 1

        print(f"Sift compacted the request: {estimated} estimated input units -> {forwarded} forwarded.")
        print("The loopback fixture found the buried setting and returned a fixed response.")
        print("No model was started or called. This checks request handling, not answer quality.")
        return 0
    finally:
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
