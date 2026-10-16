# LongBench v2 MiniMax M3 100-case protocol

## Purpose

Measure answer quality, actual provider input-token reduction, upstream-reported inference cost, and latency for Sift versus full context on a frozen 100-task LongBench v2 development sample. This is a length-conditioned sample of the public training split, not a full-suite score or a blind holdout.

## Frozen sample and implementation

- Manifest: [`longbench-v2-minimax-m3-100-manifest-2026-10-16.json`](longbench-v2-minimax-m3-100-manifest-2026-10-16.json)
- Dataset: `zai-org/LongBench-v2`, revision `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`, public `train` split, 503 rows, SHA-256 `15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2`.
- Model request: `minimax/minimax-m3` through OpenRouter, with `provider.only=["minimax"]` and `allow_fallbacks=false`. Verify returned model and provider for every response; preserve any mismatch as a failed route check.
- Endpoint metadata checked 2026-10-16: MiniMax endpoint `minimax/minimax-m3-20260531`, maximum prompt 524,288 tokens, maximum completion 512,000, $0.30/M input and $1.20/M output. The published model page lists a larger model-level context; this protocol uses the selected provider endpoint's smaller limit. Recheck the endpoint metadata before the primary run.
- Tokenizer and template are pinned by SHA-256 in the manifest. Reasoning is disabled. Count full prompts after rendering through the frozen M3 chat template.
- Sift core and runner source hashes are pinned in the manifest. Primary target is 32,768 tokens with a 128-token implementation safety margin.
- Selection seed is `20261021`. The preparer scanned all 503 rows and selected 100 distinct eligible cases from the 225 with more than 32,768 and at most 150,000 local M3-rendered prompt tokens. It balances domain, difficulty, dataset length label, and M3 token-size strata. The selected sample has 50 easy and 50 hard cases; 44 short and 56 medium; token strata 38 / 30 / 32 across 32–64K, 64–96K, and 96–150K. It contains zero `length=long` cases because there are none in the eligible range; this limits generalization to the dataset's longest label.
- The largest selected full prompt is 145,686 local tokens. At the 3.25× conservative provider-size projection plus 16 output tokens, it projects to 473,496 request tokens, leaving 50,792 below the endpoint prompt limit. The largest Sift prompt projection is 106,096 tokens.

## Paired run

- Compare two arms for each frozen task: (1) full original context and (2) Sift-compressed context at target 32,768.
- Run three repeats per arm, 600 generations total. Randomize arm order within each pair and use matched seeds/settings for both arms.
- Use one case, one repeat, both arms as the route smoke before the primary run. The smoke must use the longest selected full prompt. Confirm route attribution, status/finish reason, valid A–D output, usage/cost receipts, prompt-token reconciliation, latency, and spend-guard accounting.
- Preserve all attempts, including errors and malformed outputs. Do not silently retry or replace a task. Exclude an answer from accuracy only under a predeclared invalid-response rule; report the invalid count explicitly.
- Score a valid answer by exact match to the frozen answer key. Report each repeat, per-case majority across three repeats, paired correctness outcomes, and invalid-output counts. Do not select the best repeat.

## Cost and safety gates

- Use provider-reported prompt and completion usage as authoritative after each request. Record OpenRouter cost, upstream inference cost, cached-token usage, and `is_byok` fields separately. BYOK upstream values are provider-reported costs, not invoice-verified amounts.
- At exact endpoint prices, local prompt counts project to about $10.23 for the three-repeat paired run before any safety multiplier, plus at most $0.01152 output at the 16-token cap. The runner currently reserves 4× input tokens, projecting $40.902732 total and exceeding its $20 working ceiling.
- The one-case paired smoke is permitted under the $20 ceiling. Only reduce the input reserve to 1.5× if both arms' provider prompt-token counts are within 1.1× of their frozen local counts. If this condition fails, keep 4× and do not dispatch the full run under the current ceiling.
- Before and during the primary run, stop dispatching if provider-reported spend plus the remaining in-flight and queued reservations reaches $20. This is a best-effort client-side spend guard; requests already dispatched may still incur charges. Do not describe it as a hard billing cap.
- Recompute estimated run cost using the frozen manifest, actual selected endpoint metadata, and exact runner reserve before the first primary request. If the estimate exceeds $20, do not start the 600-generation run until an evidence-based reserve or explicit budget decision changes the gate.

## Reporting

Report model/provider route, endpoint metadata date, dataset revision, manifest and source hashes, Sift target, run date, per-arm accuracy, majority accuracy, paired outcomes, invalids, provider prompt-token reduction, upstream-reported cost reduction, TTFT and end-to-end latency, preprocessing time, and limitations together. Keep token reduction and dollar savings as separate metrics. The result does not establish full-suite performance, blind-holdout quality, or end-to-end Codex/Claude Code agent quality.

The first 10-case M3 screen and separate 6-case Table screen are development diagnostics and must not be pooled with this frozen 100-case result.
