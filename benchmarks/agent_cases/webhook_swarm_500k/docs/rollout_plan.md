# Staged rollout plan

1. Take a database backup and record the legacy row count.
2. Apply the additive schema migration in a transaction. Retain the old index
   until fingerprint backfill and row-count checks finish.
3. Verify all prior IDs and payloads match the backup, no row was deleted, and
   `(tenant_id,event_id)` is unique. Confirm the new event ID can exist for two
   different tenants.
4. Deploy API intake with durable idempotency before enabling the new workers.
   The worker must honor the persisted endpoint key and due time.
5. Enable metrics and alert on due backlog age, permanent failures, and dead
   letters. Keep both endpoint generations available during the drain window.
6. Roll back by disabling new worker claims and restoring the prior application
   version. Do not reverse the schema migration by deleting new columns or
   discarding rows. Reconcile the database before another rollout.

The change is not ready if the worker can send before committing its lease,
retry a request before `next_attempt_at`, or lose a row during migration.
