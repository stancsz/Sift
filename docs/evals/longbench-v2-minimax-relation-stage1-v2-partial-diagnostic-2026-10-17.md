# LongBench v2 MiniMax Stage 1 v2 partial diagnostic

## Status

The frozen six-task screen stopped after 23 of 36 planned requests. The runner marked `stage1_quality_gate_stopped` because only one candidate-only correct task majority remained possible, below the required two. The run has no in-flight request; the other 13 requests were not sent. This is an incomplete gate diagnostic, not a six-task score, LongBench aggregate, or estimate of the 100-task result. Do not combine it with the earlier v1 run or resume it.

All 23 received answers were attributed to MiniMax, returned HTTP 200 with `finish_reason=stop`, and parsed as valid one-key A–D JSON. There were no format failures, unknown cost receipts, or route anomalies. Upstream-reported run cost was `$0.08548464`. The account-level OpenRouter BYOK endpoint is unitemized, but its daily and weekly deltas over the captured run window were each `$0.08548464`, exactly matching the task receipts. The task-scoped exposure calculation after settlement is `$14.78240705` against the `$20` evaluation authorization. This is not an account-wide invoice or spend guarantee.

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

Keep the original JSON at `docs/results/longbench-v2-minimax-relation-stage1-v2-2026-10-17.json` as the source of truth. All 23 dispatched v2 requests returned structured answers that parsed successfully; v2 changed both response mode and the output cap, so this run cannot isolate which change mattered. The gate safely stopped further spend when its success condition became unreachable. The partial paired rows show a large prompt-token reduction with one fewer correct response among 11 observed pairs; they do not show that the selector improves answer quality or establish a quality-cost trade-off for the full task set.

## Next diagnostic direction

Before another API run, inspect whether each choice's question-specific evidence fields survived compaction; the candidate's group-closure audit confirms IDs, but does not prove semantic coverage. An independent spot check found the relevant option records and comparison relations present in all six observed candidate contexts, including the dual-club memberships in the shared miss, so an omitted answer record is not yet established as the cause. Test a normalized table or proof-snippet rendering as a hypothesis with offline fixtures against the six frozen cases and 100-task manifest, including all-choice evidence coverage, fallback behavior, and exact output stability. Any new live comparison must use a separately versioned manifest, protocol, source hashes, and spend projection; it must be independently reviewed and remain within the original `$20` task-scoped authorization.
