"""Verify the packaged-wheel campaign from repository-local native receipts."""
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from benchmarks.cli_acceptance import native_evidence
from benchmarks.cli_campaign import recovered_disconnect_count, session_id
from benchmarks.cli_matrix import schedule


def main():
    directory = Path(__file__).resolve().parent / "matrix"
    matrix = json.loads((directory / "matrix.json").read_text(encoding="utf8"))
    expected = {f"{client}-{task}-{repeat+1}" for client, task, repeat in schedule()}
    assert matrix["complete"] and matrix["accepted_sessions"] == 27
    assert matrix["terminal_sessions"] == 27 and not matrix["active_sessions"]
    assert {record["name"] for record in matrix["records"]} == expected
    assert all(attempt["key_revoked"] for attempt in matrix["attempts"])
    paths = {"sift": "src/sift/__init__.py", **{
        "sift." + name: "src/sift/" + name + ".py"
        for name in ("core", "dynamic", "litellm_proxy", "litellm_responses")}, **{
        "benchmarks." + name: "benchmarks/" + name + ".py"
        for name in ("acceptance_tasks", "cli_acceptance", "cli_campaign", "cli_matrix")}}
    frozen_sources = json.loads(gzip.decompress((directory.parent / "matrix-sources.json.gz").read_bytes()))
    assert set(frozen_sources) == set(matrix["source_sha256"])
    for name, digest in matrix["source_sha256"].items():
        recorded = frozen_sources[name].encode("utf8")
        assert hashlib.sha256(recorded).hexdigest() == digest, name
        # The archived bytes retain mixed Windows line endings. A Git
        # checkout may normalize them, but no other source change is allowed.
        current = (ROOT / paths[name]).read_bytes()
        assert current.replace(b"\r\n", b"\n") == recorded.replace(b"\r\n", b"\n"), name
    summaries = []
    identifiers = set()
    for record in matrix["records"]:
        name = record["name"]
        assert record["accepted"] and record["key_revoked"] and record["exit_code"] == 0
        receipt = json.loads(gzip.decompress((directory / f"{name}.json.gz").read_bytes()))
        rows = [json.loads(line) for line in gzip.decompress(
            (directory / f"{name}.trace.jsonl.gz").read_bytes()).decode("utf8").splitlines()]
        assert receipt["accepted"] and receipt["sift_version"] == "0.11.1"
        assert receipt["source_sha256"] == matrix["source_sha256"]
        assert receipt["client"] == record["client"] and receipt["task"] == record["task"]
        assert receipt["model"] == "default" and receipt["upstream"] == "http://127.0.0.1:4000/v1"
        assert receipt["active_client_seconds"] > 185 and len(receipt["turns"]) >= 6
        assert record["turns"] == len(receipt["turns"])
        assert record["active_seconds"] == receipt["active_client_seconds"]
        assert receipt["session_id"] not in identifiers
        identifiers.add(receipt["session_id"])
        assert math.isclose(receipt["active_client_seconds"], sum(t["duration_seconds"]
                            for t in receipt["turns"]), abs_tol=.04)
        if receipt["client"] == "codex":
            assert receipt["sandbox_readiness"]["passed"]
        for turn in receipt["turns"]:
            events = [row["event"] for row in rows if row["turn"] == turn["number"]]
            assert session_id(receipt["client"], events) == receipt["session_id"]
            identity_key = {"codex": "thread_id", "claude": "session_id", "opencode": "sessionID"}[receipt["client"]]
            assert {event[identity_key] for event in events if event.get(identity_key)} == {receipt["session_id"]}
            observed = native_evidence(receipt["client"], events)
            assert observed == turn["native"], (name, turn["number"])
            assert observed["terminal_success"] and observed["final_passed"]
            assert observed["completed"] == observed["calls"] and not observed["unmatched_results"]
            if turn["number"] == 1:
                assert observed["workflow_ordered"]
            assert turn["accepted"] and turn["client_exit"] == 0 and not turn["timed_out"]
            assert turn["historical_gold_passed"] and turn["hidden_tests_exit"] == 0
            assert turn["daily_report_passed"] and not turn["unexpected_files"]
        assert receipt["audits"] and any(a["tool_results"] for a in receipt["audits"])
        clean = all(a["upstream_status"] == 200 for a in receipt["audits"])
        disconnects = sum(a["upstream_status"] == 500 for a in receipt["audits"])
        assert receipt["transport_clean"] == clean
        assert receipt["recovered_provider_disconnects"] == disconnects
        assert recovered_disconnect_count(receipt["audits"]) == disconnects
        for audit in receipt["audits"]:
            assert (audit["upstream_status"] == 200 or (audit["upstream_status"] == 500
                    and audit.get("upstream_transport_error") == "provider_connection_closed"))
            assert audit["compacted"] and audit["gold_retained"]
            assert audit["forwarded_tokens"] <= receipt["target"]
            assert audit["sealed_items_unchanged"] and audit["latest_active_sealed_retained"] and audit["catalogs_unchanged"]
        summaries.append({"name": name, "turns": len(receipt["turns"]),
                          "active_seconds": receipt["active_client_seconds"], "requests": len(receipt["audits"]),
                          "transport_clean": clean, "recovered_provider_disconnects": disconnects})
    print(json.dumps({"verified": True, "sessions": summaries}, indent=2))


if __name__ == "__main__":
    main()
