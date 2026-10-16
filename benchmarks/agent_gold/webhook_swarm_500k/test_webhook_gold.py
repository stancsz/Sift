"""Independent acceptance checks for the webhook swarm case."""

import concurrent.futures
import hashlib
import hmac
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

CASE = Path(__file__).resolve().parents[2] / "agent_cases" / "webhook_swarm_500k"
sys.path.insert(0, str(CASE))
from service.api import accept_event  # noqa: E402
from service.db import connect, initialize, metrics_snapshot  # noqa: E402
import service.migrate as migration  # noqa: E402
from service.worker import deliver_one  # noqa: E402

migrate = migration.migrate

ENDPOINTS = json.loads((CASE / "config/endpoints.json").read_text())


class Response:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


class GoldWebhookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "gold.sqlite"
        self.db = connect(self.path)
        initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_api_worker_round_trip_preserves_identity_through_rotation(self):
        accepted = accept_event(self.db, "north", "evt-rotate",
                                {"amount": 7, "currency": "USD"}, "primary", 10)
        self.assertEqual("accepted", accepted["status"])
        calls = []
        def sender(url, body, headers):
            calls.append((url, body, headers))
            return Response(204)
        # Rotation changes endpoint URL and key reference, not the durable pair.
        rotated = dict(ENDPOINTS)
        rotated["primary"] = {**ENDPOINTS["primary"],
                              "url": "https://hooks-new.example.invalid/v1/events",
                              "signing_key_ref": "webhook/primary/next",
                              "generation": 9}
        outcome = deliver_one(self.db, sender, 10,
                              {"webhook/primary/next": b"rotated-key"}.get,
                              rotated)
        duplicate = accept_event(self.db, "north", "evt-rotate",
                                 {"currency": "USD", "amount": 7}, "primary", 11)
        self.assertEqual("delivered", outcome["state"])
        self.assertEqual("duplicate", duplicate["status"])
        self.assertEqual(accepted["delivery_id"], duplicate["delivery_id"])
        self.assertEqual("https://hooks-new.example.invalid/v1/events", calls[0][0])
        self.assertEqual("9", calls[0][2]["X-Webhook-Endpoint-Generation"])
        expected = "sha256=" + hmac.new(b"rotated-key", calls[0][1], hashlib.sha256).hexdigest()
        self.assertEqual(expected, calls[0][2]["X-Webhook-Signature"])

    def test_payload_mismatch_is_conflict_without_mutating_original(self):
        original = accept_event(self.db, "east", "evt-8", {"v": [1, 2]}, "primary", 1)
        conflict = accept_event(self.db, "east", "evt-8", {"v": [2, 1]}, "backup", 2)
        row = self.db.execute("SELECT * FROM deliveries WHERE id=?",
                              (original["delivery_id"],)).fetchone()
        self.assertEqual("conflict", conflict["status"])
        self.assertEqual('{"v":[1,2]}', row["payload_json"])
        self.assertEqual("primary", row["endpoint_key"])
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0])

    def test_parallel_identical_and_conflicting_intake_has_one_winner(self):
        barrier = __import__("threading").Barrier(12)
        def submit(index):
            barrier.wait()
            payload = {"amount": index % 2}
            connection = connect(self.path)
            try:
                return accept_event(connection, "west", "race", payload, "primary", 9)
            finally:
                connection.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(submit, range(12)))
        self.assertEqual(1, sum(x["status"] == "accepted" for x in outcomes))
        self.assertEqual(11, sum(x["status"] in {"duplicate", "conflict"} for x in outcomes))
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0])

    def test_migration_preserves_legacy_rows_and_can_resume(self):
        legacy = sqlite3.connect(":memory:")
        legacy.row_factory = sqlite3.Row
        try:
            legacy.executescript((CASE / "migrations/001_legacy.sql").read_text())
            legacy.executescript((CASE / "migrations/legacy_snapshot.sql").read_text())
            before = [tuple(row) for row in legacy.execute(
                "SELECT id,tenant_id,event_id,payload_json,state,attempts,next_attempt_at,"
                "endpoint_key,created_at FROM deliveries ORDER BY id")]
            migrate(legacy)
            migrate(legacy)
            after = [tuple(row) for row in legacy.execute(
                "SELECT id,tenant_id,event_id,payload_json,state,attempts,next_attempt_at,"
                "endpoint_key,created_at FROM deliveries ORDER BY id")]
            self.assertEqual(before, after)
            self.assertIsNotNone(legacy.execute(
                "SELECT payload_sha256,idempotency_key FROM deliveries WHERE id=41").fetchone())
            legacy.execute("INSERT INTO deliveries(tenant_id,event_id,payload_json,state,"
                           "attempts,next_attempt_at,endpoint_key,created_at) "
                           "VALUES('south','evt-rotate','{}','queued',0,0,'primary',0)")
            with self.assertRaises(sqlite3.IntegrityError):
                legacy.execute("INSERT INTO deliveries(tenant_id,event_id,payload_json,state,"
                               "attempts,next_attempt_at,endpoint_key,created_at) "
                               "VALUES('north','evt-rotate','{}','queued',0,0,'primary',0)")
        finally:
            legacy.close()

    def test_worker_respects_lease_recovery_and_attempt_accounting(self):
        result = accept_event(self.db, "central", "lease", {}, "primary", 0)
        calls = []
        def sender(*args):
            calls.append(args)
            return Response(500)
        first = deliver_one(self.db, sender, 0, lambda _: b"key", ENDPOINTS)
        self.assertEqual(("retry", 1, 1),
                         (first["state"], first["attempts"], first["next_attempt_at"]))
        row = self.db.execute("SELECT lease_until FROM deliveries WHERE id=?",
                              (result["delivery_id"],)).fetchone()
        self.assertIsNone(row["lease_until"])
        self.assertIsNone(deliver_one(self.db, sender, 0, lambda _: b"key", ENDPOINTS))
        self.assertEqual(1, len(calls))
        self.assertEqual("retry", deliver_one(self.db, sender, 1, lambda _: b"key", ENDPOINTS)["state"])

    def test_expired_lease_reclaims_but_live_lease_does_not(self):
        queued = accept_event(self.db, "central", "claim", {}, "primary", 0)
        self.db.execute("UPDATE deliveries SET state='leased', lease_until=30 WHERE id=?",
                        (queued["delivery_id"],))
        calls = []
        def sender(*args):
            calls.append(args)
            return Response(200)
        self.assertIsNone(deliver_one(self.db, sender, 29, lambda _: b"k", ENDPOINTS))
        result = deliver_one(self.db, sender, 30, lambda _: b"k", ENDPOINTS)
        self.assertEqual("delivered", result["state"])
        self.assertEqual(1, len(calls))

    def test_retry_matrix_permanent_status_network_and_dead_letter(self):
        cases = [(408, "retry"), (425, "retry"), (409, "permanent_failure"),
                 (400, "permanent_failure"), (503, "retry")]
        for index, (status, expected) in enumerate(cases):
            accept_event(self.db, "matrix", f"event-{index}", {}, "primary", 0)
            outcome = deliver_one(self.db, lambda *args, s=status: Response(s), 0,
                                  lambda _: b"k", ENDPOINTS)
            self.assertEqual(expected, outcome["state"])
        accept_event(self.db, "matrix", "network", {}, "primary", 0)
        def raises(*_):
            raise OSError("temporary network issue")
        self.assertEqual("retry", deliver_one(self.db, raises, 0,
                          lambda _: b"k", ENDPOINTS)["state"])
        exhaust_db = connect(Path(self.temp.name) / "exhaust.sqlite")
        initialize(exhaust_db)
        accept_event(exhaust_db, "matrix", "exhaust", {}, "primary", 0)
        for now in (0, 1, 3, 7):
            result = deliver_one(exhaust_db, lambda *args: Response(500), now,
                                 lambda _: b"k", ENDPOINTS)
        self.assertEqual(("dead_letter", 4), (result["state"], result["attempts"]))
        exhaust_db.close()

    def test_metrics_count_due_age_and_exclude_sensitive_dimensions(self):
        accept_event(self.db, "tenant-secret", "event-secret", {}, "primary", 100)
        snapshot = metrics_snapshot(self.db, 130)
        self.assertEqual({"total", "queued", "leased", "delivered",
                          "permanent_failure", "dead_letter", "due_now",
                          "oldest_due_age_seconds"}, set(snapshot))
        self.assertEqual((1, 1, 30), (snapshot["total"], snapshot["due_now"],
                                     snapshot["oldest_due_age_seconds"]))
        self.assertNotIn("tenant-secret", json.dumps(snapshot))
        self.assertNotIn("event-secret", json.dumps(snapshot))

    def test_snapshot_is_fully_accounted_for_and_rerunnable(self):
        path = CASE / "data/legacy_delivery_snapshot.jsonl"
        ledger_path = CASE / "data/snapshot_batches.jsonl"
        raw_lines = path.read_bytes().splitlines(keepends=True)
        source_rows = [json.loads(line) for line in raw_lines]
        ledger = [json.loads(line) for line in ledger_path.read_text().splitlines()]
        self.assertEqual(2060, len(source_rows))
        self.assertEqual(21, len(ledger))
        for batch in ledger:
            start = batch["first_row"]
            chunk = raw_lines[start:start + batch["row_count"]]
            self.assertEqual(batch["row_count"], len(chunk))
            self.assertEqual(batch["sha256"], hashlib.sha256(b"".join(chunk)).hexdigest())
        importer = getattr(migration, "import_snapshot", None)
        self.assertTrue(callable(importer), "service.migrate.import_snapshot is required")
        if not callable(importer):
            return
        first = importer(self.db, path)
        self.assertEqual({"read": 2060, "inserted": 2000, "aliased": 40,
                          "conflicted": 20, "already_imported": 0}, first)
        counts = tuple(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                       for table in ("deliveries", "legacy_aliases", "legacy_conflicts"))
        self.assertEqual((2000, 40, 20), counts)
        source_keys = {(row["source_shard"], row["legacy_id"]) for row in source_rows}
        delivery_keys = {(row[0], row[1]) for row in self.db.execute(
            "SELECT source_shard,legacy_id FROM deliveries")}
        alias_keys = {(row[0], row[1]) for row in self.db.execute(
            "SELECT source_shard,legacy_id FROM legacy_aliases")}
        conflict_keys = {(row[0], row[1]) for row in self.db.execute(
            "SELECT source_shard,legacy_id FROM legacy_conflicts")}
        self.assertEqual(source_keys, delivery_keys | alias_keys | conflict_keys)
        self.assertFalse(delivery_keys & alias_keys)
        self.assertFalse(delivery_keys & conflict_keys)
        self.assertEqual(len(source_keys), len(delivery_keys | alias_keys | conflict_keys))
        second = importer(self.db, path)
        self.assertEqual({"read": 2060, "inserted": 0, "aliased": 0,
                          "conflicted": 0, "already_imported": 2060}, second)
        counts_after = tuple(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                             for table in ("deliveries", "legacy_aliases", "legacy_conflicts"))
        self.assertEqual(counts, counts_after)

    def test_snapshot_checksum_failure_is_atomic(self):
        import tempfile
        import shutil
        lines = (CASE / "data/legacy_delivery_snapshot.jsonl").read_text().splitlines()
        lines[0] = lines[0].replace('"attempts":', '"attempts_changed":', 1)
        bad_dir = Path(self.temp.name) / "bad"
        bad_dir.mkdir()
        bad = bad_dir / "legacy_delivery_snapshot.jsonl"
        bad.write_text("\n".join(lines) + "\n")
        shutil.copy(CASE / "data/snapshot_batches.jsonl", bad_dir / "snapshot_batches.jsonl")
        importer = getattr(migration, "import_snapshot", None)
        self.assertTrue(callable(importer), "service.migrate.import_snapshot is required")
        if not callable(importer):
            return
        before = self.db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
        with self.assertRaises((ValueError, sqlite3.IntegrityError)):
            importer(self.db, bad)
        after = self.db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
