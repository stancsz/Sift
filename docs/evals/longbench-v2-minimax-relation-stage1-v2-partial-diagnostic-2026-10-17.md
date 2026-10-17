# LongBench v2 MiniMax Stage 1 v2 partial diagnostic

## Status

The frozen six-task screen stopped after 23 of 36 planned requests. The runner marked `stage1_quality_gate_stopped` because only one candidate-only correct task majority remained possible, below the required two. The run has no in-flight request; the other 13 requests were not sent. This is an incomplete gate diagnostic, not a six-task score, LongBench aggregate, or estimate of the 100-task result. Do not combine it with the earlier v1 run or resume it.

All 23 received answers were attributed to MiniMax, returned HTTP 200 with `finish_reason=stop`, and parsed as valid one-key A–D JSON. There were no format failures, unknown cost receipts, or route anomalies. Upstream-reported run cost was `$0.08548464`. The account-level OpenRouter BYOK endpoint is unitemized, but its daily and weekly deltas over the captured run window were each `$0.08548464`, exactly matching the task receipts. The task-scoped exposure calculation after settlement is `$14.78240705` against the `$20` evaluation authorization. This is not an account-wide invoice or spend guarantee.

The 23 calls ran from the first request start to the last response in 40.45 seconds (mean request end-to-end latency 1.72 seconds). This is partial-screen timing, not the completion time of a full 36-request run or a 100-task evaluation.

## Partial task observations

“Correct” counts are exact matches to the frozen answer key among responses received before the gate stopped. A majority is not assigned to an arm unless its planned three repeats are complete.

| Task ID | Gold | Research candidate | Default Sift | Readout so far |
|---|---:|---:|---:|---|
| `672494e5bb02136c067d7697` | C | 1/2 correct (B, C) | 2/2 correct (C, C) | Candidate currently trails; one repeat per arm was pending. |
| `67285e1dbb02136c067d901b` | A | 2/2 correct (A, A) | 2/2 correct (A, A) | Both arms currently correct; one repeat per arm was pending. |
| `67286036bb02136c067d9092` | D | 1/1 correct (D) | 2/2 correct (D, D) | Candidate had one fewer dispatched repeat; two remained in the planned candidate arm. |
| `67249705bb02136c067d76d1` | D | 2/2 correct (D, D) | 1/2 correct (A, D) | Candidate success was observed; default's last repeat could still reach a majority, so this was the only possible candidate-only majority. |
| `6724c4aabb02136c067d78a6` | B | 0/2 correct (C, A) | 0/2 correct (C, C) | Both arms currently miss; one repeat per arm was pending. |
| `6724c1d4bb02136c067d77ec` | A | 1/2 correct (A, D) | 2/2 correct (A, A) | Default currently leads; one repeat per arm was pending. |

The stop rule was not a discretionary early look at a favorable or unfavorable score: with only one candidate-only majority still attainable, the predeclared expansion requirement of at least two could no longer be met. The gate did not establish a default-only majority as guaranteed at stop.

## Cost and operational observations

The request receipts account for `$0.00783336` in candidate-arm inference cost and `$0.07765128` in default-arm inference cost. The partial, unbalanced counts mean these amounts are not a per-answer cost comparison. In particular, the default arm received more responses before sequential dispatch stopped. Do not infer a billing-savings percentage from these totals.

An independent row audit found 11 completed same-task/same-repeat pairs. In those pairs, the candidate was correct alone once, default was correct alone twice, both were correct six times, and both were wrong twice (7/11 candidate responses correct versus 8/11 default responses correct). Candidate requests used 50,420 prompt tokens across those 11 pairs versus 356,860 for the matching default requests, 85.9% fewer. These are descriptive partial-run observations only: the benchmark stopped before all planned repeats, the paired outcomes are not task majorities, and they do not estimate full-suite accuracy, billing savings, or end-to-end time.

Two offline renderings were evaluated with the pinned MiniMax tokenizer. The first lossless JSONL rendering reconstructed all six candidate contexts exactly, but raised the six-prompt total from 27,300 to 37,897 tokens (+38.8%); it was rejected as a token-efficiency fix. A second option-aligned matrix places complete choice entity records first and comparator/support records afterward. All six contexts round-tripped exactly, with the same frozen questions/options, and the matrix lowered the six-prompt total to 21,932 tokens (−5,368; −19.7%). In the Scunthorpe/Barrow example it displays Q8870414's edges to both clubs, Q319810's edge to Scunthorpe only, and Q443019's edge to Barrow only; compound option C remains mapped to both entities. The untouched source context is retained as an offline fallback artifact. This is representation-size and evidence-layout evidence only: no model has answered using the matrix. Prototype sources/results are `.runs/relation_table_prototype*` and `.runs/question_evidence_matrix_prototype*`.

Keep the original JSON at `docs/results/longbench-v2-minimax-relation-stage1-v2-2026-10-17.json` as the source of truth. All 23 dispatched v2 requests returned structured answers that parsed successfully; v2 changed both response mode and the output cap, so this run cannot isolate which change mattered. The gate safely stopped further spend when its success condition became unreachable. The partial paired rows show a large prompt-token reduction with one fewer correct response among 11 observed pairs; they do not show that the selector improves answer quality or establish a quality-cost trade-off for the full task set.

## Next diagnostic direction

Before another API run, use the matrix only as a separately versioned research arm; it preserves complete records, so it does not introduce predicate-extraction loss. A fresh Advisor council (Gemini then GPT-6.1 Sol) recommended a new 36-call paired v3 screen and cautioned that model quality remains unmeasured. Freeze questions/options, matrix hashes, scoring, and missing-pair rules; refresh route, prices, exact requests, and the exposure ledger. Consider the 100-task follow-up only if the new complete paired screen has at least one candidate-only task majority and strictly positive paired accuracy, and the full current reserve keeps total task-scoped exposure at or below `$20`. This recommendation does not authorize automatic expansion. Never resume or combine the v2 run.
