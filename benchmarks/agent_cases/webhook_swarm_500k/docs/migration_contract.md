# Schema migration and rollout contract

The current deployment has `migrations/001_legacy.sql`. It incorrectly uses a
global unique index on `event_id`, has no payload fingerprint or lease state,
and stores retry scheduling without an enforced due-time claim. A prior
installation's two-row snapshot is in `legacy_snapshot.sql`.

Upgrade to the delivery contract without losing or renumbering existing rows.
Preserve the exact `id`, `tenant_id`, `event_id`, `payload_json`, state,
attempts, next-attempt time, endpoint key, and creation time. Keep any row that
cannot be safely backfilled visible to operators rather than dropping or
silently marking it delivered. New uniqueness is `(tenant_id, event_id)`.
Migration can be retried after process interruption and when the target schema
already exists. It must not recreate or clear the database.

The rollout is expand, backfill, verify, then contract. Add nullable columns and
the new scoped unique index before dropping the old event-only index. Existing
payload fingerprints are SHA-256 of canonical payload bytes. Backfill stable
idempotency keys and mark pre-existing rows with a completed or queued state
consistent with their old state; do not reset attempt history. Verify counts
and scoped uniqueness before disabling the old index. SQLite `BEGIN IMMEDIATE`
is available for the migration transaction. Multiple unique event IDs across
tenants must be allowed after upgrade.

No external database library or schema framework is part of this deployment.
The code and SQL must use the Python standard library and SQLite features.

## Partitioned snapshot reconciliation

The JSONL export `data/legacy_delivery_snapshot.jsonl` models independently
constrained legacy shards. Its `legacy_id` is unique only within
`source_shard`; the event-only unique index was local to each shard. The
combined export therefore legitimately reuses event IDs across tenants.
Validate every input line and the batch count/hash ledger before any target
write.

Import each `(source_shard, legacy_id)` exactly once. Rows with a unique
`(tenant_id,event_id)` become deliveries. If several legacy rows have the same
pair and identical canonical payload, select the lexicographically earliest
`(source_shard, legacy_id)` as canonical and add an alias for each other source
row. If payloads differ, keep the canonical row and store each noncanonical
source row with all original fields in `legacy_conflicts`; never silently
overwrite or send the conflicting payload. The canonical state is `delivered`
if any identical row is delivered; otherwise use greatest attempt count,
breaking ties by earliest next-attempt time and then source key. Keep every
source record recoverable through an alias or conflict row. Import is
transactional, deterministic, and safe to rerun.

Expose `import_snapshot(connection, path)` from `service.migrate`. It returns
counts for `read`, `inserted`, `aliased`, `conflicted`, and `already_imported`.
Running it twice over the same snapshot must not change row counts or state.
No partial import may remain after a malformed record or checksum mismatch.

The upgraded `deliveries` table retains source-compatible columns and adds
`payload_sha256`, `endpoint_generation`, `last_status`, `last_error_code`,
`receiver_ack_id`, `legacy_retry_after`, `source_ticket`, `idempotency_key`,
and `lease_until`. `legacy_aliases` maps each identical duplicate's source key
to its canonical delivery. `legacy_conflicts` stores the complete original
JSONL row plus the conflict reason for each changed-payload duplicate. A
snapshot source key may appear in exactly one canonical delivery, alias, or
conflict record. Use `data/snapshot_readme.md` for field meanings.
