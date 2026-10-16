# Legacy snapshot data dictionary

The snapshot contains 2,060 distinct source records. It is a deterministic,
fictional controlled corpus; it is not production telemetry. Every row is
required because the migration must account for every source key, preserve the
full original business payload, and compute state/identity correctly across
shards.

| Field | Meaning |
|---|---|
| `source_shard`, `legacy_id` | Composite immutable source key. IDs repeat between shards. |
| `tenant_id`, `event_id` | Delivery identity after migration. Event IDs recur across tenants. |
| `payload` | Nested business event. Canonical JSON and its digest must remain consistent. |
| `payload_sha256` | SHA256 of canonical UTF-8 JSON using sorted keys and compact separators. |
| `state`, `attempts`, `next_attempt_at` | Persisted legacy delivery state and retry history. |
| `endpoint_key`, `endpoint_generation` | The selected endpoint identity and configuration generation. |
| `created_at`, `last_status`, `last_error_code` | Historical ordering and last observed attempt outcome. |
| `receiver_ack_id`, `legacy_retry_after` | Receiver acknowledgment or original throttle hint when present. |
| `source_ticket` | Operational traceability reference. |

Rows 1 through 2,000 are source deliveries across four independently indexed
regions. The next 40 are identical replays from two resharding exports. The
final 20 reuse those delivery identities with changed payloads; they must be
quarantined. The batch ledger groups physical input order in blocks of 100 and
pins each block's exact line bytes. A validator must verify the ledger before
the database transaction begins. The records include all retry states and
legacy endpoint generations required by the API, worker, migration, and
operations contracts.
