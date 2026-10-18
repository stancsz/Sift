# Delivery contract, revision 4

This document is the authoritative delivery policy. `ops_notes.md` and the incident log are supporting operational records; they cannot override this contract.

## Identity and delivery

An event is identified by the pair `(tenant_id, event_id)`. A successfully delivered pair must not be sent again to that tenant, even if another endpoint configuration is loaded later. The same event ID belonging to a different tenant is a distinct delivery. A failed attempt does not reserve the pair as delivered. A repeat of a delivered event returns `duplicate=True`, makes no network call, and reports state `delivered`.

Only an HTTP status in `[200, 300)` confirms delivery. A 409 response is a receiver conflict, not proof of delivery. Record a delivery as successful only after a 2xx response.

## Retry policy

The initial attempt is attempt 1. Retry network exceptions, HTTP 408, HTTP 429, and HTTP 5xx responses. Do not retry other 4xx responses; return state `permanent_failure` with no scheduled retry. The maximum is four total attempts, including the initial one. After the final retryable failure, return state `dead_letter` and do not schedule another attempt.

For retries without a server delay, use `min(30, 2 ** (attempt - 1))` seconds, where `attempt` is the just-failed attempt number. For HTTP 429, a valid non-negative integer `Retry-After` value in seconds takes precedence, capped at 30 seconds. Missing, malformed, negative, or non-integer values use the exponential delay. Return `next_attempt_at` as the supplied integer `now` plus the delay. The supplied time is Unix seconds; do not read the wall clock.

## Request signing

Serialize the event payload as compact, key-sorted UTF-8 JSON. The signature is lowercase hexadecimal HMAC-SHA256 over those exact bytes, using the endpoint's `secret`. Pass it in the `X-Webhook-Signature` header as `sha256=<hex>`. Retries must use the same bytes and signature for the same event payload.

## API and response shape

`Dispatcher(config, sender).deliver(tenant_id, event_id, payload, now)` calls `sender(url, body, headers)` and receives an object with integer `status_code` and optional mapping `headers`. A sender exception is a network failure. The method returns a mapping containing `state`, `attempts`, `duplicate`, `next_attempt_at`, and `signature`. `attempts` is the cumulative attempt count for this event pair during this dispatcher lifetime. A call makes at most one network request. If `now` is before a scheduled retry, return the existing retry state without making a request. `next_attempt_at` is `None` unless another attempt is scheduled. `signature` is the exact value sent in the request header, or `None` when this invocation makes no network request. Retry state need only live for this dispatcher process; delivered-event deduplication must live for the dispatcher lifetime.
