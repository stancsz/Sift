# Delivery contract

## Intake identity and payload

The durable identity is the exact pair `(tenant_id, event_id)`. Event IDs are
only unique within a tenant. A retry of the same pair with the same canonical
JSON payload returns the existing delivery ID and does not create another
outbox row. Reusing the pair with a different canonical payload returns a
conflict and leaves the original row untouched. Canonical JSON is UTF-8 JSON
with sorted object keys, compact separators, and no ASCII escaping. Arrays keep
their order. Reject values that the standard JSON encoder cannot represent.

Intake and persistence are one atomic operation. Concurrent identical requests
must produce one durable delivery and one accepted response; other identical
requests return duplicate. Concurrent different payloads for the same pair
must produce one winner and a conflict for the other request. The API must not
claim acceptance until the durable row exists.

## Delivery, signatures, and retries

Delivery is at least once. A process crash after the remote endpoint accepted a
request but before local acknowledgement can cause a retry. Every attempt sends
the same stable `Idempotency-Key` derived from the tenant/event pair so a
receiver can deduplicate that crash window. Never claim exactly-once network
delivery.

The request body is the stored canonical payload. Sign
`HMAC-SHA256(secret, body)` and send `X-Webhook-Signature: sha256=<hex>`. Send
the endpoint generation and a stable `X-Webhook-Event` event ID. Resolve the
signing key reference at send time. Persist the endpoint key selected at intake;
configuration rotation may change its URL and secret reference without
changing the delivery identity.

Only status codes 200 through 299 are success. 408, 425, 429, and 500 through
599 are retryable. Other 4xx responses, including 409, are permanent failures.
Network exceptions are retryable. There are at most four total attempts. The
base retry delay is exponential: after attempts 1, 2, and 3 schedule 1, 2, and
4 seconds. A valid integer `Retry-After` on 429 replaces that delay, capped at
30 seconds. Invalid or negative values use the exponential delay. A retry is
not sent before its persisted due time. After attempt four, a retryable result
becomes `dead_letter`, with no next attempt.

At most one worker owns a row lease at a time. Use a 30-second lease. An
unexpired lease is not claimable; an expired lease can be reclaimed. Persist
attempt count before the network call so a crash consumes that attempt. Clear
the lease on every terminal or retry transition. A failed claim or an empty
queue is a no-op.

## Result shape

`accept_event` returns `status` (`accepted`, `duplicate`, or `conflict`) and
`delivery_id` for accepted and duplicate results. `deliver_one` returns `None`
when nothing is claimable, otherwise a dict containing `delivery_id`, `state`,
`attempts`, and `next_attempt_at`. Never return `delivered` for a non-2xx
response.
