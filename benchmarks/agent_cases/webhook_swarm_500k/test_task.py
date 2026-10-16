"""Visible contract checks for the webhook reliability migration."""

import concurrent.futures
import hashlib
import hashlib
import hmac
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from service.api import accept_event
from service.db import connect, initialize, metrics_snapshot
from service.worker import deliver_one


ROOT = Path(__file__).resolve().parent
ENDPOINTS = json.loads((ROOT / "config/endpoints.json").read_text())


class Response:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


class WebhookVisibleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "db.sqlite"
        self.db = connect(self.db_path)
        initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_scoped_idempotency_and_payload_conflict(self):
        a = accept_event(self.db, "north", "same", {"x": 1}, "primary", 100)
        again = accept_event(self.db, "north", "same", {"x": 1}, "backup", 101)
        other_tenant = accept_event(self.db, "south", "same", {"x": 1}, "primary", 101)
        conflict = accept_event(self.db, "north", "same", {"x": 2}, "primary", 102)
        self.assertEqual("accepted", a["status"])
        self.assertEqual(("duplicate", a["delivery_id"]),
                         (again["status"], again["delivery_id"]))
        self.assertEqual("accepted", other_tenant["status"])
        self.assertNotEqual(a["delivery_id"], other_tenant["delivery_id"])
        self.assertEqual("conflict", conflict["status"])

    def test_intake_race_creates_one_row(self):
        def submit(_):
            connection = connect(self.db_path)
            try:
                return accept_event(connection, "north", "race", {"n": 4}, "primary", 200)
            finally:
                connection.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(16)))
        self.assertEqual(1, self.db.execute(
            "SELECT COUNT(*) FROM deliveries WHERE tenant_id='north' AND event_id='race'"
        ).fetchone()[0])
        self.assertEqual(1, sum(item["status"] == "accepted" for item in results))
        self.assertEqual(15, sum(item["status"] == "duplicate" for item in results))

    def test_signature_and_only_2xx_is_success(self):
        accepted = accept_event(self.db, "north", "sign", {"z": 2, "a": 1}, "primary", 300)
        calls = []
        def sender(url, body, headers):
            calls.append((url, body, headers))
            return Response(503 if len(calls) == 1 else 204)
        keys = {"webhook/primary/current": b"unit-test-key"}
        first = deliver_one(self.db, sender, 300, keys.get, ENDPOINTS)
        self.assertEqual("retry", first["state"])
        self.assertEqual(301, first["next_attempt_at"])
        second = deliver_one(self.db, sender, 300, keys.get, ENDPOINTS)
        self.assertIsNone(second)
        second = deliver_one(self.db, sender, 301, keys.get, ENDPOINTS)
        self.assertEqual("delivered", second["state"])
        body = b'{"a":1,"z":2}'
        expected = "sha256=" + hmac.new(b"unit-test-key", body, hashlib.sha256).hexdigest()
        self.assertEqual(accepted["delivery_id"], second["delivery_id"])
        self.assertEqual((body, expected),
                         (calls[0][1], calls[0][2].get("X-Webhook-Signature")))
        self.assertEqual(calls[0][2].get("Idempotency-Key"),
                         calls[1][2].get("Idempotency-Key"))

    def test_429_is_capped_and_retry_is_not_claimed_early(self):
        accept_event(self.db, "north", "throttle", {}, "primary", 400)
        calls = []
        def sender(*args):
            calls.append(args)
            return Response(429, {"Retry-After": "300"})
        result = deliver_one(self.db, sender, 400, lambda _: b"key", ENDPOINTS)
        self.assertEqual(430, result["next_attempt_at"])
        self.assertIsNone(deliver_one(self.db, sender, 429, lambda _: b"key", ENDPOINTS))
        self.assertEqual(1, len(calls))

    def test_metrics_derive_from_persisted_states(self):
        accept_event(self.db, "north", "metric", {}, "primary", 100)
        snapshot = metrics_snapshot(self.db, 115)
        self.assertEqual(1, snapshot["total"])
        self.assertEqual(1, snapshot["queued"])
        self.assertEqual(1, snapshot["due_now"])
        self.assertEqual(15, snapshot["oldest_due_age_seconds"])

    def test_snapshot_batch_ledger_matches_source_bytes(self):
        source = (ROOT / "data/legacy_delivery_snapshot.jsonl").read_bytes()
        lines = source.splitlines(keepends=True)
        ledger = [json.loads(line) for line in
                  (ROOT / "data/snapshot_batches.jsonl").read_text().splitlines()]
        self.assertEqual(2060, len(lines))
        self.assertEqual(21, len(ledger))
        for batch in ledger:
            chunk = lines[batch["first_row"]:
                          batch["first_row"] + batch["row_count"]]
            self.assertEqual(batch["row_count"], len(chunk))
            self.assertEqual(batch["sha256"], hashlib.sha256(b"".join(chunk)).hexdigest())


if __name__ == "__main__":
    unittest.main()
