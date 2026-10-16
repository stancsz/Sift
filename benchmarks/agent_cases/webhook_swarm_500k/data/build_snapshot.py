"""Rebuild the deterministic legacy snapshot and integrity ledger.

Every generated record participates in migration preservation and aggregate
checks. The fixed arithmetic and duplicate/conflict cohorts make the dataset
reproducible without random seeds or external packages.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "legacy_delivery_snapshot.jsonl"
LEDGER = ROOT / "snapshot_batches.jsonl"
BASE_ROWS = 2_000
DUPLICATES = 40
CONFLICTS = 20
BATCH_SIZE = 100


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def make_base(index: int) -> dict:
    shard_index = index // 500
    local_id = index % 500 + 1
    tenant_number = (index * 17 + index // 13) % 2_048
    event_number = index % 3_200
    kind = ("invoice.paid", "invoice.payment_failed", "shipment.updated",
            "subscription.changed", "account.closed", "payout.reconciled")[index % 6]
    currency = ("USD", "EUR", "GBP", "CAD")[index % 4]
    amount = (index * 7919 + 431) % 4_000_000
    happened = 1_735_689_600 + index * 37
    payload = {
        "data": {
            "account_id": f"acct-{(index * 29) % 91_337:06d}",
            "amount_minor": amount,
            "currency": currency,
            "event_id": f"evt-{event_number:05d}",
            "event_type": kind,
            "invoice_id": f"inv-{(index * 101 + 7) % 8_000_003:07d}",
            "lines": [
                {"code": f"sku-{(index * 3 + 11) % 8_191:04d}",
                 "quantity": index % 9 + 1, "unit_minor": (amount % 97_003)},
                {"code": f"tax-{(index * 5 + 19) % 4_093:04d}",
                 "quantity": 1, "unit_minor": amount % 1_001},
            ],
            "metadata": {
                "ledger_partition": f"p-{index % 32:02d}",
                "origin_ticket": f"OPS-{10_000 + (index * 7) % 73_921}",
                "schema_revision": 1 + index % 3,
            },
            "occurred_at": happened,
        },
        "id": f"evt-{event_number:05d}",
        "type": kind,
    }
    states = ("delivered", "queued", "retry", "sending", "failed")
    state = states[(index * 7 + index // 19) % len(states)]
    attempts = (index * 3 + index // 17) % 5
    if state == "delivered":
        attempts = max(1, attempts)
    if state == "sending":
        attempts = max(1, attempts)
    due = None if state in {"delivered", "failed"} else happened + (index % 3_601)
    statuses = (None, 200, 202, 408, 425, 429, 500, 502, 503, 504, 409, 422)
    status = statuses[(index * 11 + index // 31) % len(statuses)]
    errors = (None, "upstream_timeout", "rate_limited", "connection_reset",
              "invalid_signature", "receiver_conflict", "tls_handshake")
    error = errors[(index * 5 + index // 23) % len(errors)]
    endpoint_key = ("primary", "backup", "retired")[index % 3]
    generation = {"primary": 8, "backup": 3, "retired": 7}[endpoint_key]
    row = {
        "source_shard": ("region-a", "region-b", "region-c", "region-d")[shard_index],
        "legacy_id": local_id,
        "tenant_id": f"tenant-{tenant_number:04d}",
        "event_id": f"evt-{event_number:05d}",
        "payload": payload,
        "payload_sha256": hashlib.sha256(canonical(payload)).hexdigest(),
        "state": state,
        "attempts": attempts,
        "next_attempt_at": due,
        "endpoint_key": endpoint_key,
        "endpoint_generation": generation,
        "created_at": happened,
        "last_status": status,
        "last_error_code": error,
        "receiver_ack_id": (f"ack-{(index * 43) % 9_999_991:07d}"
                            if state == "delivered" else None),
        "legacy_retry_after": (str((index * 13) % 91)
                               if status == 429 else None),
        "source_ticket": f"OPS-{10_000 + (index * 7) % 73_921}",
    }
    return row


def build_rows() -> list[dict]:
    rows = [make_base(index) for index in range(BASE_ROWS)]
    # Identical replays came from regional resharding; the migration must retain
    # their source identity as aliases, not create duplicate sends.
    for offset in range(DUPLICATES):
        source = rows[offset]
        duplicate = dict(source)
        duplicate["source_shard"] = "replay-east" if offset % 2 == 0 else "replay-west"
        duplicate["legacy_id"] = offset + 1
        rows.append(duplicate)
    # These records reuse an identity but carry a changed payload and must be
    # quarantined with all original source fields instead of silently merged.
    for offset in range(CONFLICTS):
        source = rows[offset]
        conflict = json.loads(json.dumps(source))
        conflict["source_shard"] = "replay-conflict"
        conflict["legacy_id"] = offset + 1
        conflict["payload"]["data"]["amount_minor"] += 1
        conflict["payload_sha256"] = hashlib.sha256(canonical(conflict["payload"])).hexdigest()
        conflict["state"] = "queued"
        conflict["receiver_ack_id"] = None
        rows.append(conflict)
    return rows


def main() -> None:
    rows = build_rows()
    lines = [canonical(row) + b"\n" for row in rows]
    SNAPSHOT.write_bytes(b"".join(lines))
    ledger = []
    for start in range(0, len(lines), BATCH_SIZE):
        batch = lines[start:start + BATCH_SIZE]
        ledger.append({
            "batch": len(ledger),
            "first_row": start,
            "row_count": len(batch),
            "sha256": hashlib.sha256(b"".join(batch)).hexdigest(),
            "source_shards": sorted({rows[i]["source_shard"]
                                      for i in range(start, start + len(batch))}),
        })
    LEDGER.write_bytes(b"".join(canonical(row) + b"\n" for row in ledger))
    print(json.dumps({"rows": len(rows), "snapshot_bytes": SNAPSHOT.stat().st_size,
                      "ledger_batches": len(ledger)}, indent=2))


if __name__ == "__main__":
    main()
