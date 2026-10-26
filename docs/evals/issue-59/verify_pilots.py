"""Recompute pilot acceptance from repository-local receipts and native traces."""
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmarks.cli_acceptance import native_evidence


def main():
    directory = Path(__file__).resolve().parent
    paths = {"sift": "src/sift/__init__.py", **{
        "sift." + name: "src/sift/" + name + ".py"
        for name in ("core", "dynamic", "litellm_proxy", "litellm_responses")}, **{
        "benchmarks." + name: "benchmarks/" + name + ".py"
        for name in ("acceptance_tasks", "cli_acceptance", "cli_campaign", "cli_matrix")}}
    summaries = []
    for client in ("codex", "claude"):
        receipt = json.loads(gzip.decompress((directory / f"pilot-{client}.json.gz").read_bytes()))
        records = [json.loads(line) for line in gzip.decompress(
            (directory / f"pilot-{client}.trace.jsonl.gz").read_bytes()).decode("utf-8").splitlines()]
        assert receipt["accepted"] is True
        assert receipt["active_client_seconds"] > 185 and len(receipt["turns"]) >= 6
        assert math.isclose(receipt["active_client_seconds"], sum(t["duration_seconds"] for t in receipt["turns"]), abs_tol=.02)
        for name, digest in receipt["source_sha256"].items():
            raw = (ROOT / paths[name]).read_bytes()
            # Git may change line endings on checkout; no other differences
            # are accepted by this cross-platform artifact verifier.
            variants = (raw, raw.replace(b"\r\n", b"\n"), raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            assert digest in {hashlib.sha256(value).hexdigest() for value in variants}, name
        for turn in receipt["turns"]:
            events = [row["event"] for row in records if row["turn"] == turn["number"]]
            identifiers = {e.get("thread_id") for e in events if e.get("type") == "thread.started"} if client == "codex" else {
                e["session_id"] for e in events if isinstance(e.get("session_id"), str)}
            assert identifiers == {receipt["session_id"]}, (client, turn["number"], identifiers)
            observed = native_evidence(client, events)
            assert observed == turn["native"], (client, turn["number"], "native evidence differs")
            assert observed["terminal_success"] and observed["final_passed"]
            assert observed["unmatched_results"] == 0 and observed["completed"] == observed["calls"]
            if turn["number"] == 1:
                assert observed["workflow_ordered"]
            assert turn["accepted"] and turn["historical_gold_passed"] and turn["hidden_tests_exit"] == 0
            assert not turn["unexpected_files"]
        for audit in receipt["audits"]:
            assert audit["upstream_status"] == 200 and audit["compacted"] and audit["gold_retained"]
            assert audit["forwarded_tokens"] <= receipt["target"]
            assert audit["sealed_items_unchanged"] and audit["latest_active_sealed_retained"] and audit["catalogs_unchanged"]
        summaries.append({"client": client, "verified": True, "turns": len(receipt["turns"]),
                          "active_seconds": receipt["active_client_seconds"], "requests": len(receipt["audits"]),
                          "source_and_native_traces_verified": True})
    print(json.dumps({"verified": True, "scope": "Two pre-release pilots only; full 27-session matrix pending", "pilots": summaries}, indent=2))


if __name__ == "__main__":
    main()
