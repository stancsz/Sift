"""Native LiteLLM SDK provenance checks against a loopback fake SSE server."""

from contextlib import contextmanager
import importlib.util
from importlib.metadata import version
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import unittest

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
try:
    import litellm
except ImportError:
    litellm = None

SPEC = importlib.util.spec_from_file_location(
    "sift_benchmark_prefill", Path(__file__).resolve().parents[1] / "benchmarks" / "prefill.py")
prefill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prefill)


@contextmanager
def fake_provider(*, finish=None, usage=None):
    chunks = [{"choices": [{"index": 0, "delta": {"content": "label_1"}, "finish_reason": None}]}]
    if finish is not None:
        chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
    if usage is not None:
        chunks.append({"choices": [], "usage": usage})
    common = {"id": "chatcmpl-local-fake", "created": 0,
              "object": "chat.completion.chunk", "model": "gpt-4o-mini"}
    body = "".join("data: " + json.dumps({**common, **chunk}) + "\n\n" for chunk in chunks)
    body = (body + "data: [DONE]\n\n").encode()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if thread.is_alive():
            raise RuntimeError("Fake provider thread did not stop")


@unittest.skipIf(litellm is None, "install sift-context[litellm] for native SDK benchmark checks")
class PrefillProvenanceTests(unittest.TestCase):
    def sample(self, **scenario):
        self.assertEqual(version("litellm"), "1.103.0")
        with fake_provider(**scenario) as (base_url, requests):
            result = prefill._stream_sample(
                litellm.completion, [{"role": "user", "content": "Reply label_1"}],
                model="gpt-4o-mini", base_url=base_url, api_key="local-test-key")
            self.assertEqual(len(requests), 1)
            self.assertFalse(requests[0]["cache_prompt"])
            self.assertEqual(requests[0]["max_tokens"], 768)
        self.assertTrue(result["native_provenance_supported"])
        return result

    def test_done_without_native_terminal_or_usage_is_not_normal(self):
        result = self.sample()
        self.assertEqual(result["answer"], "label_1")
        self.assertEqual(result["finish_reason"], "stop")  # Synthesized by the real SDK.
        self.assertIsNone(result["native_finish_reason"])
        self.assertFalse(result["normal"])
        self.assertEqual(result["usage_source"], "unknown")
        self.assertTrue(all(value is None for value in result["usage"].values()))
        self.assertIsNotNone(result["sdk_usage"]["input_tokens"])
        self.assertEqual(result["cold_status"], "unknown")

    def test_native_stop_and_usage_can_verify_cold(self):
        result = self.sample(finish="stop", usage={
            "prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 3}})
        self.assertTrue(result["normal"])
        self.assertEqual(result["native_finish_reason"], "stop")
        self.assertEqual(result["usage_source"], "provider_chunk")
        self.assertEqual(result["usage"], {"input_tokens": 120, "output_tokens": 8,
                                           "reasoning_tokens": 3, "cached_tokens": 0})
        self.assertEqual(result["cold_status"], "verified")

    def test_native_usage_without_cached_detail_does_not_verify_cold(self):
        result = self.sample(finish="stop", usage={
            "prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128})
        self.assertTrue(result["normal"])
        self.assertEqual(result["usage"]["input_tokens"], 120)
        self.assertIsNone(result["usage"]["cached_tokens"])
        self.assertEqual(result["cold_status"], "unknown")

    def test_native_stop_without_usage_keeps_usage_unknown(self):
        result = self.sample(finish="stop")
        self.assertTrue(result["normal"])
        self.assertEqual(result["usage_source"], "unknown")
        self.assertEqual(result["cold_status"], "unknown")

    def test_sparse_native_usage_does_not_turn_missing_counts_into_zero(self):
        result = self.sample(finish="stop", usage={"prompt_tokens_details": {"cached_tokens": 0}})
        self.assertTrue(result["normal"])
        self.assertIsNone(result["usage"]["input_tokens"])
        self.assertIsNone(result["usage"]["output_tokens"])
        self.assertEqual(result["usage"]["cached_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
