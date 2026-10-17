# LongBench v2 MiniMax relation-selector Stage 1 v2 protocol

## Purpose and separation from the failed run

This is a new, complete 36-request paired screen of the research-only relation-closure selector against unchanged default Sift on the same six frozen LongBench v2 public training-split tasks. It replaces the failed Stage 1 attempt as the only candidate for expansion; it does not overwrite, continue, retry, or combine with the prior 33/36 report. The prior run is diagnostic evidence only.

Stage 1 v1 stopped safely after 33 receipts because a MiniMax response ended with `finish_reason=length` at the 16-token cap before emitting a choice. Its exact request and response remain preserved at `docs/results/longbench-v2-minimax-relation-stage1-2026-10-16.json`. Three jobs were not sent. No score or quality comparison may combine that partial run with v2.

## Frozen design

- Stage manifest: `longbench-v2-minimax-relation-stage1-v2-manifest-2026-10-17.json`.
- Baseline sample: `longbench-v2-minimax-m3-100-manifest-2026-10-16.json`; baseline run: `../results/longbench-v2-minimax-m3-100-2026-10-16.json`.
- Cases, in frozen manifest order: `672494e5bb02136c067d7697`, `67249705bb02136c067d76d1`, `6724c1d4bb02136c067d77ec`, `67285e1dbb02136c067d901b`, `67286036bb02136c067d9092`, and `6724c4aabb02136c067d78a6`.
- Three matched repeats use CLI seed `20261022`; the generation seed parameter is CLI seed + repeat + 1: `20261024`, `20261025`, `20261026`. Endpoint metadata does not advertise seed support; seeds are matched request parameters only, with no deterministic RNG claim.
- Arms: `sift_default` (unchanged default selector) and `sift_relation_followup` (default-off research selector, with exact baseline fallback if compaction does not retain complete comparison groups). Both use a 32,768-token target, identical source question and context protocol, generation settings, output-format instruction, and paired seed.
- Total: six tasks × three repeats × two arms = 36 requests. Randomize pair order and arm order within each adjacent pair, use one worker, and never retry or replace a request/task. The previous v1 attempt is not resumed.

## Answer format, based on canaries

The v1 failure showed that a 16-token output cap can cut off an explanatory preamble even when the prompt requests a single letter. Raise `max_tokens` to 128 for this version. Send `response_format: {"type":"json_object"}` and append the same instruction to the final user message in both arms: return one JSON object with exactly one key, `answer`, whose value is a single uppercase A/B/C/D letter; no explanation.

Canary evidence: the freshly queried OpenRouter MiniMax endpoint advertises `response_format`. A non-scored strict JSON Schema canary returned HTTP 200 but markdown (`**B) 4**`), so this protocol does not rely on JSON Schema enforcement. A separate synthetic `json_object` canary returned HTTP 200, `finish_reason=stop`, and `{"answer":"B"}` (7 completion tokens; upstream-reported cost $0.00004218). The actual compacted prompt for the prior truncated case was then sent as a non-scored canary under the frozen v2 request format. It returned HTTP 200, MiniMax attribution, `finish_reason=stop`, exact content `{"answer":"A"}`, 7,031 prompt tokens, 6 completion tokens, and upstream-reported cost $0.00044298; the summarized, hashed receipt is `../results/longbench-v2-minimax-json-format-canaries-2026-10-17.json`; full local request/response JSON is retained in ignored `.runs/` scratch. This verifies output-format compatibility on one representative prompt, not answer quality or guaranteed formatting for all requests.

Scoring stays strict: parse the whole completion as exactly one JSON object with the sole key `answer`, no duplicate keys, no surrounding prose, and a string value in A/B/C/D. Do not extract letters heuristically. A completed `finish_reason=stop` and valid JSON answer are both required. JSON-object mode is a formatting aid, not a correctness guarantee.

## Route, provenance, and spend preflight

- Use OpenRouter `minimax/minimax-m3`, pinned with `provider.only=["minimax"]` and `allow_fallbacks=false`. The fresh route snapshot is `longbench-v2-minimax-stage1-v2-route-2026-10-17.json`; the endpoint is `Minimax | minimax/minimax-m3-20260531`, prompt/context limit 524,288, and rates at check time are $0.30/M uncached input and $1.20/M output. Metadata is time-sensitive; re-fetch before dispatch and stop on changed route/rates/limits or stale data.
- Validate the frozen sample/dataset, tokenizer/template, historical manifest/result, current Sift core, versioned v2 runner/analyzer/protocol, route snapshot hashes, 36 exact prepared requests, JSON output contract in both arms, dispatch-order replay, zero candidate fallbacks, request projection, and CLI dry-run. The dry-run must not access the API key or dispatch.
- Reconciled exposure ledger entering the run: prior provider-reported costs `$8.04465726` = prior manifest actual `$6.90272880` plus the 47 successful `sift-screen` receipts `$0.51419670` and 33 successful `table-fresh` receipts `$0.62773176`. Prior unsettled exposure is `$0.30682335`: existing `$0.01705665` plus conservative maximum-charge reserves of `$0.12219840` for the no-usage `ConnectionError` at 407,264 prompt tokens + 16 output tokens and `$0.16756830` for the no-usage HTTP 400 rejected request at 558,497 prompt tokens + 16 output tokens. Both error calls are reserved at full stated prompt length despite having no usage receipts. Recompute the Stage 1 v2 conservative 1.5× input reserve plus all 128-token output caps from fresh prices and all 36 prepared requests. Include the next in-flight reservation in that reserve. Stop before dispatch unless cumulative actual + unsettled + planned full-run reserve is below the authorized `$20` aggregate limit, and record the arithmetic. The $4 run guard is best-effort client accounting, not a provider billing cap.
- Keep `OPENROUTER_API_KEY` only in the environment. Never persist or print it.

## Dispatch and stop rules

Before each API call, persist the exact complete request payload, canonical payload hash, job ID, and dispatch timestamp as the in-flight record. After the response settles, append its full request/response, route, usage/cost/cache receipt, score, timing, Sift selector audit, and failure state; clear the in-flight record atomically. Count all unresolved exposure.

Stop dispatch at the first confirmed route, attribution, usage, cost, target, fallback, malformed JSON, invalid answer, or budget anomaly. Also stop when the expansion gate is mathematically impossible: fewer than two candidate-only task-majority wins remain possible, or a default-only majority is guaranteed. Do not stop merely because one remains possible. Never retry inside this frozen run. Preserve all dispatched and undispatched rows.

## Analysis and expansion gate

Independently verify all 36 unique paired rows, request hashes and response-format contract, matching seed parameters, randomized dispatch order, provider attribution, finish reason, usage/cost receipts, prompt target, exact strict JSON choice parse, and selector audit. Report per-arm exact-choice and task-majority outcomes, paired task outcomes, invalids, provider prompt tokens and cache tokens, observed cache-inclusive provider-reported cost, a separate reconstructed uncached estimate, preprocessing, model latency, and elapsed wall time. Provider-reported cost is not a verified invoice. Six cases are a narrow screen, not a LongBench aggregate, full-suite result, blind holdout, or agent-workflow evaluation.

Expansion is permitted only when all 36 responses are valid, there are zero candidate fallbacks and route/usage/cost/target/answer anomalies, there are at least two candidate-only correct task majorities, and there are zero default-only correct task majorities. A pass permits consideration—not automatic launch—of the 100-task follow-up. Any failure keeps the old and new attempts separate and stops expansion for diagnosis.

If this gate passes, consider a separately reviewed, frozen 100-task × three-repeat Sift-only run (300 requests) using relation closure only when complete and otherwise unchanged default Sift. Reconcile actual spend and live prices before launch; preserve fallback reasons and compare only against the historical full-context arm with an explicit non-concurrent/provider-drift caveat. The historical sample is public training data and length-conditioned, not a full-suite or blind-holdout score. Do not publish performance claims from the six-case screen.
