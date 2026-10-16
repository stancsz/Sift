"""Webhook intake API starter."""

import json
import sqlite3


def accept_event(
    connection: sqlite3.Connection,
    tenant_id: str,
    event_id: str,
    payload: dict,
    endpoint_key: str,
    received_at: int,
) -> dict:
    """Persist an event or return duplicate/conflict for its scoped identity."""
    # Starter uses event_id globally, stores no payload fingerprint, and has no
    # transaction around the lookup/insert race.
    row = connection.execute(
        "SELECT id FROM deliveries WHERE event_id = ?", (event_id,)
    ).fetchone()
    if row:
        return {"status": "duplicate", "delivery_id": row["id"]}
    cursor = connection.execute(
        "INSERT INTO deliveries(tenant_id,event_id,payload_json,state,attempts,"
        "next_attempt_at,endpoint_key,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (tenant_id, event_id, json.dumps(payload), "queued", 0,
         received_at, endpoint_key, received_at),
    )
    return {"status": "accepted", "delivery_id": cursor.lastrowid}
