# LongBench v2 MiniMax Stage 1: 100-task development run

**Prepared:** 2026-10-18
**Status:** offline plan only; no provider requests sent; dispatch is not authorized.

## Purpose

Move quickly to a useful paired measurement while the larger 344-task study remains prepared. This stage runs the same 100 public LongBench v2 task IDs used by the earlier exposed development sample, selected from the newly reviewed 344-task cohort. Because these IDs and their answers were previously exposed in development work, this is a continuity/development sample, not a blind holdout and not an independent confirmation set.

## Paired protocol

- Dataset: pinned LongBench v2 train snapshot recorded in the manifest.
- Model: `minimax/minimax-m3` through OpenRouter, with provider restriction `minimax` and fallbacks disabled.
- Arms: full prompt and Sift compacted prompt at the configured 32,768-token target.
- Repeats: three paired requests per task per arm; 600 requests total.
- Generation: temperature 0.1, top-p 0.8, max output 64 tokens, reasoning disabled, streaming usage receipts. Matched seed per task/repeat is a request parameter; deterministic model output is not claimed.
- Results must retain per-request provider, model, usage, cost, latency, response ID, exact request hashes, score, and failures. Any provider/model mismatch, fallback, missing usage/cost receipt, or provider/local input-token ratio above 1.05 must stop further dispatch and be reported. On stop, reserve and reconcile all submitted/in-flight requests before considering any continuation; no unsent request is silently dropped from the spend ledger.

## Modeled reserve

Using the pinned local MiniMax tokenizer counts in the manifest, total local input is 32,527,062 tokens across both arms and three repeats. Applying a 1.5× input reserve factor at the dated planning assumption of $0.30 per million input tokens gives **$14.6371779**. The 600 requests have a worst-case output budget of 38,400 tokens; at the dated $1.20 per million output assumption that is **$0.04608**. Total modeled reserve: **$14.6832579**.

These are historical planning rates, not a live quote, account check, authorization, or provider-enforced spending cap. Refresh route, price, and account state before any dispatch. A person must separately approve an explicit aggregate spend ceiling. The runner must reject the default path and only dispatch under a deliberate `--dispatch` flag and a user-approved ceiling at least as high as a refreshed preflight estimate.

## Fast-path implementation status

The manifest is derived from the already-generated 344-task artifact and historical 100 task IDs; it avoids rerunning the 503-row eligibility/compaction scan. It binds the parent manifest hash and retains its source hashes. A shared offline preparation/dispatch adapter now exists at [`benchmarks/run_longbench_v2_minimax_stage1_100.py`](../../benchmarks/run_longbench_v2_minimax_stage1_100.py). It accepts only the pinned Stage 1 and 344 manifest paths and hashes, reconstructs the 100-task schedule, and verifies every frozen 344 request identity, seed, body hash, projected prompt count, and schedule hash. Do not point the older 16-token runner at this manifest or relax its hash checks.

The first no-network preparation completed successfully: [`longbench-v2-minimax-stage1-100-prepared-2026-10-18.json`](longbench-v2-minimax-stage1-100-prepared-2026-10-18.json) records 600 unique requests (300 per arm), a 64-token output cap, a per-request body hash, and a `$14.6832579` dated reserve. It records `prepared_only_no_dispatch` and `actual_dispatch_started=false`; answer and prompt text are excluded. Independent Codex review accepts this offline preparation path. Claude Code's focused read-only review confirmed the no-network default and explicit dispatch gates, and cautioned that the client-side spend ceiling cannot guarantee the final BYOK invoice. Each canonical request body includes `max_tokens=64`; provider enforcement and invoice behavior still need live runtime verification. The per-run ceiling is a best-effort client guard, not a provider-enforced cap.

Dispatch remains gated on independent runtime/schema verification, fresh exact endpoint, prompt/completion limits, rates, account credit and unsettled usage checks, plus a new explicit user-approved cap covering a refreshed complete reserve. OpenRouter's [endpoint metadata API](https://openrouter.ai/docs/api/api-reference/endpoints/list-all-endpoints-for-a-model) exposes `model_id`, route limits, and per-token prices; its [credits API](https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits) requires a management key and reports aggregate credits/usage. Use `OPENROUTER_MANAGEMENT_KEY` for those read-only checks and `OPENROUTER_API_KEY` for inference; do not include either credential in reports. OpenRouter account credits do not establish that a BYOK provider invoice or unsettled upstream request is covered, so reconcile that separately.

## Interpretation

This 100-task stage provides paired directional evidence and can identify failure modes quickly. It covers 100 distinct tasks, a subset of the public 503-row suite. It cannot support a blind generalization claim or replace the planned 344-task study. Report outcomes and confidence intervals alongside exact task coverage, correctness, input reduction, cost, and time-to-finish; do not characterize Sift as a universal accuracy-preserving or cost-saving result without those measurements.
