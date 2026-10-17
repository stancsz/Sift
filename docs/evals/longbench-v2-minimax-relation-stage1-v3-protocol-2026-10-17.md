# LongBench v2 MiniMax relation-matrix Stage 1 v3 protocol

## Purpose and status

This protocol specifies a new six-task paired diagnostic for the MiniMax route. It does not resume, overwrite, pool, or score either stopped v1/v2 attempt. The treatment combines the default-off relation-closure selector with an option-aligned matrix that serializes each complete selected entity once and records all answer-option letters that refer to it. The control is unchanged default Sift. Neither arm is full context.

The six cases are inherited from the prior relation-closure success subset, and the matrix layout was developed using those same public training prompts. Results are therefore candidate-enriched exploratory evidence only. They cannot establish generalization, a full-suite LongBench score, native Codex/Claude Code agent performance, or a marketing claim. A passing gate permits a separate budget and protocol review; it does not authorize a larger run automatically.

## Frozen design

- Dataset: public LongBench v2 training split, revision `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`, using the six IDs listed in the v3 stage manifest.
- Arms: `sift_default` and `sift_relation_matrix_v3`. The treatment first runs relation closure, requires complete supported comparison groups, then transforms the selected context to the matrix. It preserves every selected entity field, every supporting entity, exact source paths, the final question/options, and every non-context message. The pure transform must round-trip to the original selected context exactly. Any parse, coverage, reconstruction, target, or request-limit failure selects default Sift for that candidate slot and fails the zero-fallback gate.
- Sample: six preselected tasks × three paired repeat parameters × two arms = 36 requests. The case IDs and order are fixed in the stage manifest. No v1/v2 responses are combined with v3.
- Sift target: 32,768 tokens with a 128-token local safety margin. Use the pinned MiniMax M3 tokenizer and chat template for local counts; provider usage is authoritative during execution.
- Repeats: CLI seed `20261022`, paired generation seed parameters `20261024`, `20261025`, and `20261026`. The selected endpoint does not advertise seed support; these are matched request parameters only, not a deterministic-repeat guarantee.
- Generation: temperature 0.1, top-p 0.8, reasoning disabled, maximum 128 output tokens, JSON-object response mode, one worker, zero retries. Both arms receive the same output instruction and matched seed parameter.
- Answer contract: accept only a completed `finish_reason=stop` response containing an entire strict JSON object with exactly one string field `answer` whose value is uppercase A/B/C/D. Reject truncated, malformed, extra-key, prose-wrapped, missing, or invalid answers. Do not recover an answer from prose and do not retry.
- Route: OpenRouter `minimax/minimax-m3`, provider pinned to `minimax`, with provider fallbacks disabled. Verify returned model/provider and token/cost receipts for every request. A route mismatch is an anomaly and invalidates expansion.
- Dispatch: randomize case-pair order and order within each adjacent pair using the frozen shuffle seed; save the exact prepared payload/hash and in-flight receipt before each request. Preserve all sent and unsent rows.

## Acceptance and stop rules

Expansion consideration requires all criteria below:

1. All 36 paired responses have valid, reconciled request, route, usage, cost, target, and answer receipts.
2. There are zero candidate fallbacks and zero route, usage, cost, target, or answer anomalies.
3. The matrix candidate has at least one candidate-only correct task majority versus the concurrent default-Sift control.
4. The matrix candidate has strictly more exact-choice-correct responses than the concurrent default-Sift control.

The same gate is implemented by `benchmarks/longbench_v3_gate.py` and consumed by both runner and analyzer. Separate operational aborts from quality-gate failures. Stop dispatch immediately on route/provider mismatch, missing or inconsistent usage/cost/cache receipts (including cost components that do not reconcile), provider/local token-ratio or context-limit violation, transport/stream failure, or budget issue. Count a billable HTTP 200 response with valid route/usage/cost/cache receipts but malformed, truncated, or non-A–D output as an invalid answer and continue the frozen schedule; it fails the zero-invalid expansion criterion, but completing the remaining calls yields a complete six-task diagnostic rather than another gate-triggered partial run. Record candidate fallbacks and continue only if the default-Sift fallback request remains valid and within all hard limits; any fallback fails expansion. Do not stop early because a quality criterion has become impossible. Include any in-flight request in budget exposure.

## Cost and timing accounting

OpenRouter's selected MiniMax route supports implicit prompt caching. Do not claim cache-cold behavior or equate upstream-reported pass-through cost to an invoice. Preserve per-call prompt/completion/cached token counts, cost details, route, preprocessing time, request latency, response latency, and run wall time. Report the observed cache-inclusive upstream-reported cost separately from a reconstructed uncached-price estimate. Any savings percentage must include its denominator, aggregation, sample, date, and route. Show quality beside efficiency.

At the previous v2 checkpoint, the task-scoped artifact ledger was `$14.78240705` of the user's `$20` authorization: `$14.32900946` prior actual plus `$0.36791295` unsettled/reserved plus `$0.08548464` v2 actual. The initial v3 in-memory projection at the frozen route rates is not a fresh authorization. Before dry run and again immediately before dispatch, refresh the MiniMax route/prices, prepared-job projection, recorded/unsettled ledger, and account/key usage snapshot. The current account/key BYOK usage endpoint is aggregate and unitemized; it cannot be attributed to this run or reconciled as a task invoice. Label the $20 arithmetic as a task-scoped conservative artifact ledger, not a guarantee of total account spend.

Do not dispatch unless prior actual + unsettled reservations + the full-run reserve, including one-request in-flight headroom, remains within `$20`. Use a run-specific `$4` best-effort client guard only if the exact full-run reserve fits; the guard is not provider-enforced. Stop if any amount or receipt is unknown. Recheck prices and the total reserve if endpoint rates, max prompt/completion limits, source hashes, or prepared prompts change.

## Required artifacts and validation

Before any live request, create and verify the frozen v3 stage manifest, protocol hash, fresh route snapshot, candidate/helper/core/runner/analyzer hashes, dataset/tokenizer/template hashes, 36 prepared requests, dispatch ordering, zero candidate fallbacks, exact request projections, and the entire task-scoped reserve. Run the CLI `--dry-run`; it must not access the API key or dispatch. Independently verify that it prepares exactly 36 unique requests (18 per arm), all paired seeds match, all matrices preserve complete records and untouched questions/options, the request-size maximum is below the verified endpoint limit, and total exposure stays inside the cap.

Preserve the raw request, response, score, provider attribution, usage/cost/cache receipt, timing, and selector/matrix audit for every attempted request. Analyze only a complete valid v3 run. Keep the partial v1/v2 diagnostics separate. Stage 2 (a 100-task × three-repeat Sift run with candidate-to-default fallback) requires a fresh review after v3, a new protocol/manifest, live pricing, exact request reserve, and independent acceptance. Do not change the Sift default or README performance claims based on a six-task pass alone.
