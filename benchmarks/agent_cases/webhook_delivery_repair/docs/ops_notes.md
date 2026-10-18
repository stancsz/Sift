# Relay operations notes

The 2026-09-14 incident review recorded two symptoms: a partner retried one timed-out event and received it twice, and a throttled endpoint was retried in a tight loop. Do not infer policy from the old implementation or these notes; use `delivery_policy.md` for the current retry limits and duplicate semantics.

An endpoint's signing secret is endpoint-specific. Configuration reloads are common during secret rotation, so deduplication identity must not include the secret, URL, or configuration revision.
