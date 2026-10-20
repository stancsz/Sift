# LongMemEval-V2 Sift adapter prototype — 2026-10-20

## Status

**Synthetic contract prototype only. No benchmark data was downloaded, no inference was run, and no score was produced.** This does not establish LongMemEval compatibility, quality, or blind validation.

The prototype targets official LongMemEval-V2 repository commit [`2cc8c540bdb87fe6761629b585e727e1c4704520`](https://github.com/xiaowu0162/LongMemEval-V2/commit/2cc8c540bdb87fe6761629b585e727e1c4704520). Its documented backend contract is `insert(trajectory)` followed by `query(question, query_image=None)`, returning text and/or image context items. The official trajectory preparer expects state text and screenshot paths; the harness can append a query image to its reader prompt. See the [memory interface](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/memory_modules/memory.py) and [trajectory normalization](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/memory_modules/trajectory_store.py).

## What the local prototype checks

`benchmarks/longmemeval_v2_sift_adapter.py` maps the public and legacy trajectory shapes to ordered text messages, appends the question as the active user turn, and calls Sift's deterministic `compact_messages` API. It carries screenshot paths only for source states represented in the compacted result and fails when a required screenshot path is missing. The harness itself remains responsible for adding the question image to the reader prompt.

The prototype uses a UTF-8 request-size estimate divided by two, not the official Qwen reader tokenizer. It delegates input-size and raw-token bounds to Sift, whose defaults are 16,777,216 characters, 250,000 nodes, and 1,000,000 estimated raw tokens. Oversize input fails closed. Do not use this estimate for a benchmark comparison or leaderboard package.

Run the focused offline adapter checks with:

```powershell
py -3 -m pytest tests/test_longmemeval_v2_sift_adapter.py -q
```

The tests use synthetic Python fixtures, including temporary screenshot paths. They check both documented trajectory shapes, registration through a compatible registry function, query preservation, image-to-selected-state mapping, rejection when an official-required screenshot is absent, and rejection at the configured Sift bounds. They do not import or execute the LongMemEval harness.

## Known gaps and next gate

- The pinned trajectory preparer requires a non-empty screenshot path for every state. The synthetic fixtures enforce that requirement; actual image decoding and harness handoff remain untested. The benchmark publishes its questions and trajectories, so any eventual run is a public-benchmark reproduction, not evidence of generalization to a blind set.
- The upstream trajectories contain screenshot paths. This prototype associates images with selected text-bearing states, but Sift ranks text only and may miss image-only evidence. A future full-data trial must fail or report unsupported image-dependent cases explicitly; it must not silently drop them.
- The adapter uses an approximate size counter, not the reader tokenizer; it has not been run through the official harness; real dataset normalization, official scoring, latency, cost, and task accuracy are unverified.
- LongMemEval-V2's leaderboard validator requires its documented Qwen reader and GPT judge. A MiniMax-M3 run would be a local reproduction and requires a new numeric spend cap because the previous $100 authorization is exhausted.
- AppWorld and GAIA remain uncleared for a paired, independently controlled held-out run. A credible agent-task holdout still needs a prospectively fixed task set and an independent custodian/evaluator boundary.

The 2026-10-20 Gemini 4 Argon → GPT-6.1 Sol council recommended this bounded synthetic prototype while also freezing a separately held-out protocol and clearance checklist. Gemini judged the adapter the smallest free technical step; Sol agreed, but noted protocol definition is also actionable. Sol's stop condition is reached if faithful coverage requires silently dropping essential images or exceeds Sift's bounds. Usage: Gemini 3,129 prompt + 197 completion; Sol 701 prompt + 251 completion tokens. This is advice, not independent QA.

Before any real-data access or model call, an independent reviewer must accept the adapter and protocol; the actual harness, reader token counting and image path must be exercised using only synthetic fixtures; benchmark access terms must be reviewed; and a new route/usage reserve plus explicit numeric spend cap must be obtained. Stop this benchmark path if its screenshot requirements or scale cannot fit Sift without unsupported lossy behavior.
