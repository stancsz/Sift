# LongMemEval-V2 Sift adapter prototype — 2026-10-20

## Status

**Synthetic adapter plus prompt-build smoke only. No benchmark data was downloaded, no inference was run, and no score was produced.** This does not establish LongMemEval compatibility, quality, or blind validation.

The prototype targets official LongMemEval-V2 repository commit [`2cc8c540bdb87fe6761629b585e727e1c4704520`](https://github.com/xiaowu0162/LongMemEval-V2/commit/2cc8c540bdb87fe6761629b585e727e1c4704520). Its documented backend contract is `insert(trajectory)` followed by `query(question, query_image=None)`, returning text and/or image context items. The official trajectory preparer expects state text and screenshot paths; the harness can append a query image to its reader prompt. See the [memory interface](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/memory_modules/memory.py) and [trajectory normalization](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/memory_modules/trajectory_store.py).

## What the local prototype checks

`benchmarks/longmemeval_v2_sift_adapter.py` maps the public and legacy trajectory shapes to ordered text messages, appends the question as the active user turn, and calls Sift's deterministic `compact_messages` API. It carries screenshot paths only for source states represented in the compacted result and fails when a required screenshot path is missing. The harness itself remains responsible for adding the question image to the reader prompt.

The prototype uses a UTF-8 request-size estimate divided by two, not the official Qwen reader tokenizer. It delegates input-size and raw-token bounds to Sift, whose defaults are 16,777,216 characters, 250,000 nodes, and 1,000,000 estimated raw tokens. Oversize input fails closed. Do not use this estimate for a benchmark comparison or leaderboard package.

Run the focused offline adapter checks with:

```powershell
py -3 -m pytest tests/test_longmemeval_v2_sift_adapter.py -q
```

The tests use synthetic Python fixtures, including temporary screenshot paths. They check both documented trajectory shapes, registration through a compatible registry function, query preservation, image-to-selected-state mapping, rejection when an official-required screenshot is absent, and rejection at the configured Sift bounds.

An additional synthetic smoke invokes `build_prompt_row` from the pinned official harness source and checks the adapter query, context truncation path, Pillow decoding of one synthetic state image, inclusion and data-URL encoding of both state and question images, and the question-image log path. It verifies the harness Git blob against `6a7182440a2cdd3ace6286dd966f7953fc383e8e` before importing it. The check stubs upstream registry/scoring imports, unused OpenAI/tqdm CLI imports, and the processor/token counter. Only the state image is decoded by the tested harness helper; the question image is encoded and handed off. No benchmark records or model calls are involved. To repeat it, obtain `evaluation/harness.py` from upstream commit `2cc8c540bdb87fe6761629b585e727e1c4704520`, install Pillow in the active Python environment, then run:

```powershell
py -3 benchmarks/longmemeval_v2_synthetic_harness_smoke.py C:\path\to\LongMemEval-V2\evaluation\harness.py
```

## Known gaps and next gate

- **Access-rights screen (2026-10-20):** The official GitHub repository carries an Apache-2.0 license, and the official Hugging Face dataset card declares the data Apache-2.0. This records the maintainers' published license and supports planning only; it does not authorize data access/use or establish rights in embedded third-party web screenshots. No data has been downloaded. [Repository license](https://github.com/xiaowu0162/LongMemEval-V2/blob/main/LICENSE) · [Dataset card](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2)
- The pinned trajectory preparer requires a non-empty screenshot path for every state. The smoke confirms image decoding and prompt handoff for synthetic fixtures only; it does not validate real dataset paths or image-dependent answer coverage. The benchmark publishes its questions and trajectories, so any eventual run is a public-benchmark reproduction, not evidence of generalization to a blind set.
- The upstream trajectories contain screenshot paths. This prototype associates images with selected text-bearing states, but Sift ranks text only and may miss image-only evidence. A future full-data trial must fail or report unsupported image-dependent cases explicitly; it must not silently drop them.
- The adapter uses an approximate size counter, not the reader tokenizer. The prompt-building helper was exercised in isolation; the full official harness, real dataset normalization, official scoring, latency, cost, and task accuracy remain unverified.
- LongMemEval-V2's leaderboard validator requires its documented Qwen reader and GPT judge. A MiniMax-M3 run would be a local reproduction and requires a new numeric spend cap because the previous $100 authorization is exhausted.
- AppWorld and GAIA remain uncleared for a paired, independently controlled held-out run. A credible agent-task holdout still needs a prospectively fixed task set and an independent custodian/evaluator boundary.

The 2026-10-20 Gemini 4 Argon → GPT-6.1 Sol council recommended this bounded synthetic prototype while also freezing a separately held-out protocol and clearance checklist. Gemini judged the adapter the smallest free technical step; Sol agreed, but noted protocol definition is also actionable. Sol's stop condition is reached if faithful coverage requires silently dropping essential images or exceeds Sift's bounds. Usage: Gemini 3,129 prompt + 197 completion; Sol 701 prompt + 251 completion tokens. This is advice, not independent QA.

Before any real-data access or model call, an independent reviewer must accept the adapter and protocol; reader token counting and the full harness flow must be exercised using only synthetic fixtures; and a public-run protocol must be frozen. The declared dataset license has now been checked, but image provenance remains unreviewed; this check alone does not authorize data access/use. Any model run also needs a fresh route/usage reserve and explicit numeric spend cap. Stop this benchmark path if its screenshot requirements or scale cannot fit Sift without unsupported lossy behavior.

## Synthetic prompt-build smoke (2026-10-20)

`benchmarks/longmemeval_v2_synthetic_harness_smoke.py` passed against the pinned upstream harness blob `6a7182440a2cdd3ace6286dd966f7953fc383e8e`. It exercised the actual `build_prompt_row` helper and Sift adapter with a synthetic trajectory image and question image. The state image was decoded by the harness helper; both images were included in the generated reader messages, and the question image was also recorded in the image-path log field. The processor/token counter was stubbed to a fixed one-token shape. No dataset, generation, reader model, scoring, or inference was used. An independent read-only reviewer confirmed that these claims match the code path after a wording correction. This is a narrow integration probe, not a completed official evaluation.
