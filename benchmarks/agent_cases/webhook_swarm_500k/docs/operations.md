# Operations and observability contract

Expose `metrics_snapshot(connection, now)` with integer counters for `total`,
`queued`, `leased`, `delivered`, `permanent_failure`, and `dead_letter`;
`due_now` counts queued rows whose next-attempt time is at or before `now`.
`oldest_due_age_seconds` is zero or greater when a due row exists, otherwise
null. Counts must come from persisted state, not process-local counters.

Do not put tenant IDs, event IDs, payloads, endpoint URLs, or secret references
in metric labels or structured logs. Operators need to distinguish a retry
backlog from permanent failures and dead letters without exposing customer
data.

## Rotation and incident handling

`endpoint_key` is persisted on each delivery. A key rotation updates the
configuration's URL and secret reference for that key; it must not reset the
row, change its idempotency identity, or cause a second outbox entry. The
retired key remains in configuration during the 24-hour drain window but is
not selected for newly accepted events.

On a growing retry backlog, inspect due counts and the oldest due age, then
verify endpoint health and 429 `Retry-After` behavior. Do not reset attempt
counts or mark rows delivered to clear an alert. Dead letters require a
documented replay after fixing the cause, preserving the original identity and
payload. A replay must not bypass receiver idempotency.
