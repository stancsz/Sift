# Stable history anchor development check

Date: 2026-10-16. Status: unreleased selector candidate. No provider calls were made.

## Question

Does a query-independent history anchor preserve a reusable serialized prefix when the latest user question changes, while leaving query-specific evidence available?

The existing query-aware selector can reorder the full historical summary for a topic change. In a deterministic source-history probe, a payment query selected records `0, 28, 26, ...`, while an incident query selected `29, 27, 25, ...`. This establishes prompt-content divergence in the fixture, not provider cache invalidation or billed cost.

## Candidate

The candidate keeps one query-independent anchor in its own quoted user message before the query-ranked excerpts. It chooses the first historical failed-test index when available, otherwise one bounded excerpt from the first old message. Structured excerpts that carry a shared table prefix are excluded to avoid duplicating headers. The anchor uses at most one eighth of the caller's target and is dropped if it would crowd out active work. Query-aware excerpts remain separate and continue to follow the latest question.

No request fields, roles, provider adapters, external storage, model calls, or dependencies were added. LiteLLM and the caller continue to own transport and cache behavior.

## Development evidence

Two deterministic tests change the query against the same history:

- Ordinary multi-turn history at a 2,000-token test target.
- A 48-cycle tool history at a 6,000-token test target.

In both cases, the anchor message is byte-identical across the topic shift. The next query-ranked summary changes and retains the matching payment or incident marker. Both requests remain within the hard test-counter budget, and the current user request/tool tail stays intact. The focused core, acceptance-corpus, invariant, and structured-evidence tests passed: 42 passed. Ruff and `git diff --check` passed on the changed source and tests.

The full repository suite is not green in this working tree. Its run had 58 failures and 29 setup errors, including absent files in pending agent fixtures and failures in unrelated Responses/provenance tests. Those results are not attributed to this candidate; rerun the full suite after the incomplete fixtures and environment-specific failures are resolved.

## Limits and next gate

The tests use a deterministic character-based token counter and synthetic histories. They establish a stable serialized message prefix, not provider cache hits, lower cost, natural-history recall, or accepted-task parity. The anchor can spend budget that query-ranked excerpts would otherwise use.

Keep this candidate unreleased until a frozen natural-trace replay compares baseline and candidate for exact retained evidence, shared-prefix token count, and hard-budget behavior. If that holds, run matched provider requests with actual cached-input usage, task acceptance, total latency, and cost. Stop on a required-evidence or accepted-task regression. The Codex Advisor council agreed this is a reasonable fixed-budget pilot and specifically cautioned that synthetic prefix stability does not prove provider savings.
