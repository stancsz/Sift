from contextlib import redirect_stdout
from io import StringIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import socket
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch

import pytest

from examples import no_inference_compaction_demo as demo


def _free_local_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_fixture_does_not_claim_a_setting_missing_from_compacted_context():
    retained, answer = demo._fixture_answer([
        {"role": "user", "content": "Only routine kubelet polls were retained."},
    ])

    assert not retained
    assert answer == demo._MISSING_ANSWER


def test_demo_rejects_remote_url():
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", ["demo", "--url", "https://example.com/v1/chat/completions"]):
            demo.main()


def test_demo_refuses_redirects():
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "https://example.com/")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as error:
            demo._LOCAL_OPENER.open(Request(f"http://127.0.0.1:{server.server_port}/"), timeout=1)
        assert error.value.code == 302
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_documented_cli_path_confirms_compaction_with_proxy_environment_set():
    fixture_port = _free_local_port()
    sift_port = _free_local_port()
    child_env = os.environ.copy()
    child_env.update({
        "HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
        "NO_PROXY": "", "no_proxy": "",
    })
    process = subprocess.Popen(
        [sys.executable, "-m", "sift.cli", "serve", "--base-url", f"http://127.0.0.1:{fixture_port}/v1",
         "--port", str(sift_port), "--target", "2048", "--tokenizer", "byte-estimate"],
        cwd=os.getcwd(), env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    output = StringIO()
    try:
        assert process.stdout is not None
        ready = process.stdout.readline()
        assert "Sift proxy listening" in ready
        with patch.object(sys, "argv", [
            "no_inference_compaction_demo",
            "--url", f"http://127.0.0.1:{sift_port}/v1/chat/completions",
            "--stub-port", str(fixture_port),
        ]), patch.dict(os.environ, {
            "HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
            "NO_PROXY": "", "no_proxy": "",
        }), redirect_stdout(output):
            result = demo.main()
        assert result == 0, output.getvalue()
        assert "Sift compacted the request" in output.getvalue()
        assert "loopback fixture found the buried setting" in output.getvalue()
        assert "No model was started or called" in output.getvalue()
    finally:
        process.terminate()
        process.wait(timeout=5)
