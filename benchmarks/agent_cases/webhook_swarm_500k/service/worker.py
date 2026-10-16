"""Durable delivery worker starter."""

import sqlite3


def deliver_one(connection: sqlite3.Connection, sender, now: int,
                secret_lookup, endpoints: dict) -> dict | None:
    """Claim and process at most one due delivery."""
    # Starter selects any row, ignores leases and retry policy, and treats all
    # HTTP responses as successful. Implement the documented state machine.
    row = connection.execute(
        "SELECT * FROM deliveries ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    endpoint = endpoints[row["endpoint_key"]]
    response = sender(endpoint["url"], row["payload_json"].encode(), {})
    connection.execute(
        "UPDATE deliveries SET state='delivered', attempts=attempts+1 WHERE id=?",
        (row["id"],),
    )
    return {"delivery_id": row["id"], "state": "delivered", "attempts": 1}
