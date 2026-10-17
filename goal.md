# LongBench v2 MiniMax M3 evaluation

## Status: paused for handoff

The user asked to stop this run gracefully. Do not resume or send additional provider requests until the user asks to continue and the unresolved attempt/accounting state is reviewed.

## Objective

Complete a reproducible Full-context versus default-Sift LongBench v2 comparison through OpenRouter MiniMax M3. The frozen schedule is one repeat over the public 503-question dataset. It is post-census development evidence, not a blind holdout, multi-turn agent benchmark, or proof of quality parity. Use the frozen prompt, route, scoring, retry, and stop rules; preserve receipts and report coverage, paired quality, token/cost, preprocessing, latency, and run time where measured.

## Current evidence

See [the wrap-up report](docs/results/longbench-v2-minimax-m3-fullsuite-progress-2026-10-17.md) and [handoff.md](handoff.md).

- 446 scoreable paired questions: Full 198/446 (44.4%); Sift 193/446 (43.3%), a -1.1 percentage-point observed difference.
- On those same pairs, Sift used 75.8% fewer provider prompt tokens and had 76.8% lower provider-reported upstream inference cost. BYOK receipts are not invoice verification; caching was enabled.
- Latest checkpoint: 923 completed scheduled jobs; 3 additional Full requests rejected by the provider limit; 1 job remains unresolved. The run is incomplete.
- LongBench does not measure end-to-end coding-agent task completion or Sift preprocessing-inclusive speed in this run.

## Remaining tasks

1. Keep the current checkpoint immutable and reconcile the unresolved Full job: the first attempt returned HTTP 200 with a cost receipt but no completed scoreable answer; its retry failed with SSL and has unknown usage. Do not retry until the user explicitly resumes the goal and the duplicate-charge risk is acknowledged.
2. Reduce resume preflight cost with a content-addressed prepared-input cache keyed by every frozen manifest, schedule, source, tokenizer, renderer, and Sift hash. Reconstruct and compare exact request-body hashes before trusting cached entries.
3. Independently review the cache and run offline equivalence checks. Do not make paid requests during this work.
4. On an explicitly authorized resume, refresh route/pricing and reconcile account/in-flight exposure. Continue only the frozen schedule with unchanged model, prompt, scoring, and stop rules. Preserve the 79 local-fit exclusions, three runtime rejections, and all attempts visibly.
5. Produce a final aggregate covering matched and unpaired outcomes, paired/task-level quality, provider usage/cost receipts, unknown usage, preprocessing, latency, total wall time, and exact coverage. Obtain an independent raw-receipt and analysis review before making broader public claims.

## Resource state

The `subroute-qwen-local-1` Qwen 27B container is stopped (Docker state `exited`, exit code 137); no Qwen/vLLM process or running Qwen container was found. At wrap-up, Windows reported about 8.1 GiB available system RAM. The GPU showed 8.7 GiB used of 16.3 GiB, with desktop applications visible and no Qwen process; do not attribute all current GPU use to this run.
