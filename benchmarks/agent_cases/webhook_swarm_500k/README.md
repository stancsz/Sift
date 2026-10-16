# Webhook delivery reliability migration

This is a fictional but internally consistent software operations case. It is
new development data, not production evidence or a held-out benchmark. The
starter is intentionally incomplete. The repository contains a legacy SQLite
delivery table, API and worker code, endpoint configuration, migration notes,
operational requirements, and distinct incident evidence.

## Task

Implement a safe, backwards-compatible webhook reliability change across the
intake API, delivery worker, SQLite migration, and operator telemetry/runbook.
The system must use `(tenant_id, event_id)` as the delivery identity, reject a
reused identity with a different canonical payload, preserve existing delivery
rows through migration, and provide durable at-least-once delivery with bounded
retries. Read the contract, migration and operations docs, endpoint config, and
the incident evidence before changing behavior. The append order of incident
records is not policy precedence.

`data/legacy_delivery_snapshot.jsonl` is a partitioned synthetic legacy export
with 2,060 distinct source rows, cross-tenant event-ID reuse, 40 identical
duplicate rows, and 20 conflicting payload rows. Its records vary in tenant,
event, nested invoice payload, state, attempt history, endpoint generation,
retry metadata, and source ticket. Every row is required migration input, not
benchmark padding. Reconcile every source row into the new delivery table,
alias table, or explicit conflict quarantine. Validate the per-batch
SHA256/count ledger in `data/snapshot_batches.jsonl` before importing.

`python build_checkpoint_packet.py --output <path>` writes a deterministic
context packet. The packet is a fixture artifact, not the final user prompt.
Seed it into a persisted Claude Code session as historical tool/file-result
context, then fork that exact checkpoint for each comparison arm and submit a
short final task request. Do not put the packet in the latest user message:
Sift intentionally protects the active user turn, so doing that would test
oversized-turn rejection rather than historical-context compaction. Verify
Claude Code preserves the complete packet in the checkpoint; any truncation
disqualifies the run.

An earlier version of this packet was estimated at 559,364 tokens with one
fixed system message and one user message using repo venv LiteLLM 1.103.0 and
model `openrouter/minimax/minimax-m3`. That is only a scale estimate for the
older, ineligible initial-user-message design. The actual
prepared checkpoint request includes the real client system prompt, tool
schemas, and historical tool results, so recount it through the deployed full
LiteLLM route before any paid task run. Record the callback count and compare
it with provider-reported input usage. Do not sum tokens across requests to
claim a 500K raw-context trial. Record checkpoint preparation cost and time
separately and include shared preparation in end-to-end cost per accepted task.

This task has separable API, worker, migration, and operations workstreams, but
their contracts meet at the durable delivery record. You may delegate those
investigations in parallel. Integrate and test the complete path before
finishing.

## Constraints

- Use only the Python standard library.
- Preserve the public function signatures in `service/api.py`,
  `service/worker.py`, and `service/db.py` unless a compatibility wrapper is
  retained.
- Do not edit the supplied tests or evidence.
- The migration must preserve all legacy rows and be safe to invoke more than
  once.
- Do not log payload bodies, endpoint secrets, or signing keys.
- Run `python -m unittest -q` before and after implementation.
- The visible suite is not the complete acceptance contract. Report any
  unresolved migration, crash-window, or deployment assumptions.

## Repository map

- `service/`: API intake, worker, persistence, and metrics starter.
- `migrations/`: legacy schema and upgrade contract.
- `config/`: endpoint routing and key references.
- `docs/`: delivery, migration, rollout, and operational contracts.
- `evidence/`: separate incident chains and deployment observations.
- `data/`: task-essential delivery snapshot and deterministic batch ledger.

The acceptance suite checks the integrated behavior, including adversarial
tenant collisions, concurrent intake, migration preservation, retry timing,
lease recovery, endpoint-key rotation, and operational counters.
