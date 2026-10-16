"""Build a deterministic, cross-domain incident corpus and gold answer.

This is a local fixture generator only. Token totals use the pinned LiteLLM
1.103.0 tokenizer as a sizing estimate, not a prepared-route qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "benchmarks" / "agent_cases" / "multi_domain_incident_swarm_500k"
GOLD = ROOT / "benchmarks" / "agent_gold" / "multi_domain_incident_swarm_500k"
SEED = 381904
ROWS = 3500
MODEL = "openrouter/minimax/minimax-m3"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def make_record(rng: random.Random, i: int) -> dict:
    domain = ("deploy", "iam", "network", "payments", "tickets")[i % 5]
    stamp = f"2026-09-{(i % 27) + 1:02d}T{(i * 7) % 24:02d}:{(i * 13) % 60:02d}:{(i * 17) % 60:02d}Z"
    common = {
        "source_id": f"{domain[:3].upper()}-{i:06d}",
        "source_system": {
            "deploy": "ArgoCD audit export", "iam": "CloudTrail immutable archive",
            "network": "VPC flow aggregator", "payments": "settlement ledger mirror",
            "tickets": "SupportDesk export",
        }[domain],
        "observed_at": stamp,
        "record_type": domain,
        "provenance": {"partition": f"p-{i % 17:02d}",
                       "export_batch": f"batch-{i // 250:03d}",
                       "collector_version": f"{1 + i % 4}.{i % 9}"},
    }
    if domain == "deploy":
        common["data"] = {
            "change_id": f"CHG-{100000 + i}", "service": rng.choice(("ledger-export", "invoice-api", "reporting")),
            "region": rng.choice(("us-east-1", "us-west-2", "eu-central-1")),
            "image_digest": f"sha256:{rng.getrandbits(128):032x}",
            "actor": f"svc-release-{i % 31:02d}", "result": rng.choice(("healthy", "rolled_out", "no-op", "rollback")),
            "approval_ref": f"APR-{rng.randrange(100000, 999999)}",
            "note": rng.choice(("canary completed", "no customer alert", "replica reconciled", "config sync observed")),
        }
    elif domain == "iam":
        common["data"] = {
            "principal": f"role/{rng.choice(('exporter', 'reconciler', 'support-read', 'batch-worker'))}-{i % 43:02d}",
            "action": rng.choice(("AssumeRole", "GetObject", "PutObject", "ListBucket", "Decrypt", "UpdatePolicy")),
            "resource": f"arn:cloud:storage:::acct-{i % 89:03d}/exports/{rng.randrange(1000, 99999)}",
            "source_ip": f"10.{i % 250}.{(i * 7) % 250}.{1 + i % 253}",
            "decision": rng.choice(("allowed", "denied", "allowed", "mfa_required")),
            "session": f"sess-{rng.getrandbits(48):012x}", "request_id": f"req-{rng.getrandbits(64):016x}",
        }
    elif domain == "network":
        common["data"] = {
            "src": f"10.{i % 250}.{(i * 11) % 250}.{1 + i % 253}:{10000 + i % 50000}",
            "dst": f"172.{i % 30}.{(i * 3) % 250}.{1 + (i * 5) % 253}:443",
            "bytes": rng.randrange(64, 2_000_000), "packets": rng.randrange(1, 4000),
            "action": rng.choice(("ACCEPT", "REJECT", "ACCEPT", "ACCEPT")),
            "interface": f"eni-{rng.getrandbits(40):010x}", "flow_id": f"fl-{rng.getrandbits(56):014x}",
            "zone": rng.choice(("private-a", "private-b", "egress", "shared")),
        }
    elif domain == "payments":
        common["data"] = {
            "export_id": f"EXP-{i % 2400:06d}", "batch_ref": f"SET-{i % 900:05d}",
            "account": f"merchant-{i % 771:04d}", "currency": rng.choice(("USD", "EUR", "GBP", "CAD")),
            "amount_minor": rng.randrange(100, 80_000_000), "entry_type": rng.choice(("capture", "refund", "fee", "payout")),
            "status": rng.choice(("posted", "pending", "reversed", "matched")),
            "checksum": f"{rng.getrandbits(128):032x}",
        }
    else:
        common["data"] = {
            "ticket": f"CS-{200000 + i}", "customer": f"org-{i % 1900:05d}",
            "severity": rng.choice(("P3", "P2", "P4", "P2", "P1")),
            "status": rng.choice(("open", "triaged", "resolved", "waiting")),
            "product_area": rng.choice(("exports", "billing", "reports", "identity")),
            "summary": rng.choice(("scheduled report delayed", "export status unclear", "reconciliation question", "access review request")),
            "runbook_ref": f"RB-{rng.randrange(10, 99)}.{1 + i % 5}",
        }
    record = common
    record["row_sha256"] = hashlib.sha256(canonical(common)).hexdigest()
    return record


def critical_records() -> list[dict]:
    # Three rare, deliberately separated source facts. Preserve source IDs in
    # the task acceptance so an answer must join domains rather than guess.
    facts = [
        ("DEP-000000", "deploy", "2026-10-02T09:00:00Z", {
            "change_id": "CHG-88421", "service": "ledger-export", "result": "rolled_out",
            "actor": "svc-release-07", "region": "us-east-1", "image_digest": "sha256:9a71c4e0",
            "approval_ref": "APR-4410", "note": "egress policy bundle net-export-17 attached"}),
        ("IAM-INC-003001", "iam", "2026-10-02T09:07:13Z", {
            "principal": "role/exporter-prod", "action": "AssumeRole", "resource": "role/finance-export-writer",
            "source_ip": "10.44.8.19", "decision": "allowed", "session": "sess-incident-88421",
            "request_id": "req-iam-88421", "change_id": "CHG-88421",
            "detail": "session tag owner=ledger-export absent; ticket approval APR-4410 is read-only"}),
        ("NET-005999", "network", "2026-10-02T09:09:44Z", {
            "src": "10.44.8.19:443", "dst": "198.51.100.77:443", "bytes": 8840217,
            "packets": 9201, "action": "ACCEPT", "interface": "eni-incident-88421",
            "flow_id": "fl-incident-88421", "zone": "egress", "change_id": "CHG-88421",
            "detail": "destination is unapproved external sink; policy exception absent"}),
        ("PAY-008997", "payments", "2026-10-02T09:18:00Z", {
            "export_id": "EXP-771204", "batch_ref": "SET-99201", "account": "merchant-0042",
            "currency": "USD", "amount_minor": 4819920, "entry_type": "payout", "status": "posted",
            "checksum": "ledger:7f11", "change_id": "CHG-88421", "detail": "bank settlement total matches; duplicate external copy is not a second posting"}),
        ("TIC-011999", "tickets", "2026-10-02T09:32:00Z", {
            "ticket": "CS-88421", "customer": "org-0042", "severity": "P1", "status": "open",
            "product_area": "exports", "summary": "customer reports confidential payout export appeared at third-party endpoint",
            "runbook_ref": "RB-41.3", "change_id": "CHG-88421", "detail": "runbook requires revoke session, preserve evidence, notify security; do not replay payout"}),
        ("RUN-012000", "tickets", "2026-10-02T09:41:00Z", {
            "ticket": "SEC-88421", "customer": "internal-security", "severity": "P1", "status": "triaged",
            "product_area": "identity", "summary": "RB-41.3 directs containment before rollback",
            "runbook_ref": "RB-41.3", "change_id": "CHG-88421",
            "detail": "revoke sess-incident-88421, rotate finance-export-writer credentials, block 198.51.100.77, preserve logs, notify affected customer; only then rollback CHG-88421"}),
        ("DEP-017999", "deploy", "2026-10-02T10:04:00Z", {
            "change_id": "CHG-88421", "service": "ledger-export", "result": "rollback_complete",
            "actor": "svc-release-07", "region": "us-east-1", "image_digest": "sha256:rollback-42",
            "approval_ref": "APR-4410", "note": "rollback occurred after containment; not proof the exposure was prevented"}),
    ]
    out = []
    for source_id, domain, stamp, data in facts:
        base = {"source_id": source_id, "source_system": f"authoritative {domain} incident record",
                "observed_at": stamp, "record_type": domain,
                "provenance": {"partition": "incident", "export_batch": "sealed-88421",
                               "collector_version": "3.2"}, "data": data}
        base["row_sha256"] = hashlib.sha256(canonical(base)).hexdigest()
        out.append(base)
    return out


def records() -> list[dict]:
    rng = random.Random(SEED)
    rows = [make_record(rng, i) for i in range(ROWS)]
    # Position three high-value facts early, middle, and late in the raw stream.
    rare = critical_records()
    for position, record in zip((0, len(rows) // 2 + 1, len(rows) - 1), (rare[0], rare[1], rare[2])):
        rows[position] = record
    # Keep remaining correlated records together but separated from the three
    # anchor facts, including an explicit false reassurance after the event.
    rows[100] = rare[3]
    rows[ROWS - 120] = rare[4]
    rows[ROWS - 2] = rare[5]
    rows[ROWS - 3] = rare[6]
    stale_dashboard = {
        "source_id": "DASH-88421", "source_system": "derived incident status dashboard",
        "observed_at": "2026-10-02T10:00:00Z", "record_type": "dashboard",
        "provenance": {"partition": "incident", "export_batch": "derived-88421",
                       "collector_version": "1.4"},
        "data": {"change_id": "CHG-88421", "summary": "no unauthorized egress; no customer impact",
                 "source_watermark": "2026-10-02T09:05:00Z",
                 "detail": "derived from cached policy simulation; not connected to IAM or flow archive"}}
    stale_dashboard["row_sha256"] = hashlib.sha256(canonical(stale_dashboard)).hexdigest()
    rows[ROWS // 2 + 70] = stale_dashboard
    return rows


def write_fixture() -> dict:
    CASE.mkdir(parents=True, exist_ok=True)
    GOLD.mkdir(parents=True, exist_ok=True)
    rows = records()
    lines = [canonical(row) + b"\n" for row in rows]
    (CASE / "data").mkdir(exist_ok=True)
    source_path = CASE / "data" / "source_records.jsonl"
    source_path.write_bytes(b"".join(lines))
    manifest = {"schema": 1, "fixture": CASE.name, "seed": SEED,
                "record_count": len(rows), "source_file": "data/source_records.jsonl",
                "source_bytes": source_path.stat().st_size,
                "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                "row_accounting": [{"row": i, "source_id": row["source_id"],
                                    "bytes_including_newline": len(lines[i]),
                                    "sha256": hashlib.sha256(lines[i]).hexdigest()}
                                   for i, row in enumerate(rows)],
                "critical_positions": {"early": 0, "middle": len(rows)//2 + 1, "late": len(rows)-1},
                "token_estimate": {"method": "Pinned LiteLLM 1.103.0 litellm.token_counter; model=openrouter/minimax/minimax-m3; one system message and one user message containing the exact task packet and source records once. Estimate only; excludes prepared route/tool schemas/provider usage.",
                                   "count": None, "route_qualified": False}}
    (GOLD / "input_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (GOLD / "expected_dispositions.json").write_text(json.dumps({
        "incident_id": "CHG-88421",
        "root_cause": "CHG-88421 attached egress policy net-export-17 and permitted exporter-prod to assume finance-export-writer; the session lacked owner tag and sent data to unapproved sink 198.51.100.77.",
        "confirmed_exposure": True,
        "payment_posting_duplicate": False,
        "containment_order": ["revoke sess-incident-88421", "rotate finance-export-writer credentials", "block 198.51.100.77", "preserve evidence", "notify affected customer", "rollback CHG-88421"],
        "authority": ["immutable IAM and flow archives for observed actions", "signed change record for deployed state", "settlement ledger for posting state", "runbook for required response", "tickets for customer-reported impact", "chat or dashboard summaries are leads only"],
        "required_evidence_ids": ["DEP-000000", "IAM-INC-003001", "NET-005999", "PAY-008997", "TIC-011999", "RUN-012000", "DEP-017999"]
    }, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_packet() -> tuple[str, int]:
    sources = [CASE / "README.md", CASE / "task.md", CASE / "authority.md", CASE / "data" / "source_records.jsonl"]
    text = "\n\n".join(f"===== {p.relative_to(CASE).as_posix()} =====\n{p.read_text(encoding='utf-8')}" for p in sources)
    try:
        from importlib.metadata import version
        import litellm
        installed = version("litellm")
        if installed != "1.103.0":
            raise RuntimeError(f"Expected LiteLLM 1.103.0, found {installed}")
        count = litellm.token_counter(model=MODEL, messages=[
            {"role": "system", "content": "You are a coding agent investigating a production incident. Use source evidence and preserve uncertainty."},
            {"role": "user", "content": text},
        ])
    except ImportError as exc:
        raise RuntimeError("Install the repo's pinned LiteLLM 1.103.0 extra to count the estimate") from exc
    return text, count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-packet", action="store_true")
    args = parser.parse_args()
    manifest = write_fixture()
    if args.write_packet:
        packet, count = build_packet()
        (CASE / "swarm_context.md").write_text(packet, encoding="utf-8")
        manifest["token_estimate"]["count"] = count
        manifest["token_estimate"]["packet_bytes"] = len(packet.encode())
        manifest["token_estimate"]["packet_sha256"] = hashlib.sha256(packet.encode()).hexdigest()
        (GOLD / "input_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case": str(CASE), "gold": str(GOLD), "rows": manifest["record_count"],
                      "source_bytes": manifest["source_bytes"],
                      "token_estimate": manifest["token_estimate"]["count"]}, indent=2))


if __name__ == "__main__":
    main()
