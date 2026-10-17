# LongBench v2 MiniMax relation-selector Stage 1 protocol

## Purpose and scope

This is a narrow, contemporaneous screen of a research-only relation-closure selector against unchanged default Sift. It uses six LongBench v2 public training-split tasks selected by the frozen offline relation-closure sweep. It is not a LongBench aggregate, full-suite result, blind holdout, or native Codex/Claude Code workflow evaluation. The prior 100-task full-context results are historical references and are not concurrent controls.

## Frozen design

- Stage manifest: `longbench-v2-minimax-relation-stage1-manifest-2026-10-16.json`.
- Baseline sample: `longbench-v2-minimax-m3-100-manifest-2026-10-16.json`; baseline run: `../results/longbench-v2-minimax-m3-100-2026-10-16.json`.
- Cases, in frozen manifest order: `672494e5bb02136c067d7697`, `67249705bb02136c067d76d1`, `6724c1d4bb02136c067d77ec`, `67285e1dbb02136c067d901b`, `67286036bb02136c067d9092`, and `6724c4aabb02136c067d78a6`.
- Three matched repeats use CLI seed `20261022`; generation seed is `CLI seed + repeat + 1`, yielding `20261024`, `20261025`, and `20261026` for both arms of a task/repeat pair.
- Two arms: `sift_default` (unchanged default selector) and `sift_relation_followup` (research-only relation closure, explicitly enabled). Both use target 32,768 and the same source messages, question, expected answer, generation settings, and paired seed.
- Total: six cases × three repeats × two arms = 36 requests. Randomize task-pair order per repeat and randomize arm order inside each adjacent pair with Python `random.Random(cli_seed + repeat)`. Use one worker; do not retry, replace tasks, or select a best repeat.
- If the research candidate raises a supported compaction error or fails to retain complete comparison groups, the runner records the reason and uses exact default Sift output for that request. Any candidate fallback disqualifies the screen from expansion. Preflight should stop before API dispatch if such a fallback is found while preparing the screen.

## Route and preflight

- Request `minimax/minimax-m3` through OpenRouter, with `provider.only=["minimax"]` and `allow_fallbacks=false`. The individual generation receipts identify the requested model and provider family; they do not prove a physical endpoint ID per request.
- Immediately before dispatch, re-fetch the official endpoint catalog at `https://openrouter.ai/api/v1/models/minimax/minimax-m3/endpoints`. Save the raw response and a normalized route snapshot. Confirm provider, model, prompt and context limits, current input/output/cache rates, availability, and route pin. The prior snapshot observed a 524,288-token prompt limit and rates of $0.30/M input, $1.20/M output, and $0.06/M cache read; those are not assumed to remain current.
- Validate the frozen sample, dataset revision, tokenizer/template, baseline manifest/result, relation-follow-up runner, analyzer, Sift core, protocol, and route-metadata hashes. Run CLI help, syntax checks, analyzer synthetic cases, local 36-job preparation, exact dispatch-order replay, and receipt-shape fixtures without API dispatch.
- Require `OPENROUTER_API_KEY` in the environment without printing or persisting it. Check cumulative reported and unsettled exposure plus the conservative Stage 1 reserve against the authorized $20 total budget. The $4 Stage 1 client-side guard must include the next request's reservation and any in-flight exposure; it is a best-effort guard, not a hard provider billing limit. Stop if any exposure is unknown or the total could exceed $20.
- Prepared requests must remain under the current endpoint prompt limit using the frozen 3.25× local-token projection plus output allowance. Stop before dispatch on any source/hash, route, price, request-size, spend, or candidate-fallback discrepancy.

## Dispatch and immediate stop rules

Persist a run record before the first request and atomically update it after every response. Store every request and response, unique task/repeat/arm key, seed, HTTP/finish status, requested model/provider, response usage and cost details, cache tokens, correctness, local/provider prompt ratio, selector audit/fallback reason, preprocessing time, latency, route snapshot hash, and stop reason. Omit API secrets.

Stop dispatch immediately after any confirmed route, usage, cost-receipt, target, malformed-answer, invalid-response, or budget anomaly. Also stop as soon as the expansion gate is mathematically impossible: either fewer than two candidate-only task-majority wins can still be achieved, or a default-only correct task majority is guaranteed because default already has at least two correct repeats while candidate can no longer reach two. Do not stop merely because a default-only outcome is still possible; remaining repeats may change that task's classification. No retry or gate relaxation is allowed. Preserve partial records and count every in-flight reservation in exposure.

## Analysis and expansion gate

The frozen analyzer must validate all 36 unique rows, matching paired seeds, randomized dispatch-order replay, route attribution, valid usage/cost receipts, target compliance, answer structure, and selector audits. Report exact-choice accuracy and correct-task majorities per arm, paired task outcomes, prompt tokens, observed cache-inclusive provider-reported cost, a separate reconstructed uncached estimate, preprocessing, model latency, and total run time. Treat reported costs as provider-reported upstream values, not verified invoices. Do not make universal savings or quality claims from six cases.

Stage 1 passes only with 36 valid paired receipts, zero candidate fallbacks, no route/usage/cost/target anomaly, at least two candidate-only correct task majorities, and zero default-only correct task majorities. A pass permits consideration of Stage 2; it does not prove an aggregate quality improvement or authorize a marketing claim. If any criterion fails, preserve results and stop to diagnose.

Only after independent result review and a passing Stage 1 gate may Stage 2 be considered: the same frozen 100-task development sample, three repeats, 300 Sift-only requests. Use relation closure only for complete, supported groups and otherwise preserve an explicit reason for falling back to unchanged default Sift. Revalidate route, exact source hashes, prices, request-size and aggregate budget immediately before Stage 2; keep its $4 best-effort guard and the same $20 aggregate authorization. Compare with historical full-context data only as a non-concurrent reference subject to provider drift.

