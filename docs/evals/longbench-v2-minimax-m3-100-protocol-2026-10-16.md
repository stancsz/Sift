# LongBench v2 MiniMax M3 100-case protocol

## Purpose

Measure answer quality, provider input-token reduction, provider-reported upstream cost, cache use, and latency for Sift versus full-context prompting on a frozen 100-task LongBench v2 development sample. This is a length-conditioned subset of the public training split, not a full-suite score or blind holdout.

## Frozen sample and route

- Manifest: [`longbench-v2-minimax-m3-100-manifest-2026-10-16.json`](longbench-v2-minimax-m3-100-manifest-2026-10-16.json).
- Dataset: `zai-org/LongBench-v2`, revision `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`, public `train` split, 503 rows, SHA-256 recorded in the manifest.
- Request `minimax/minimax-m3` through OpenRouter with `provider.only=["minimax"]` and `allow_fallbacks=false`. Save the provider/model for every call and stop the run on any mismatch.
- Live endpoint metadata rechecked 2026-10-16: provider `Minimax`, endpoint `minimax/minimax-m3-20260531`, maximum prompt 524,288, maximum completion 512,000, input $0.30/M, output $1.20/M, cache read $0.06/M. Implicit caching is supported. OpenRouter's model-level 1M context headline does not override this selected provider endpoint's 524,288 prompt cap. Recheck endpoint metadata, rates, and availability immediately before dispatch.
- Pinned M3 tokenizer/template, target, Sift core, runner, sample-selection script, dataset-preparation helper, and M3-rendering helper hashes are recorded in the manifest and checked before dispatch. Primary Sift target is 32,768 tokens, with a 128-token implementation safety margin.
- Selection seed is `20261021`. The preparer scanned all 503 rows and froze 100 distinct cases from the 225 whose full M3-rendered prompt counts are greater than 32,768 and no more than 150,000. The sample has 50 easy/50 hard, 44 short/56 medium/0 long dataset labels, and 38/30/32 cases in the 32–64K/64–96K/96–150K local-token strata. No eligible candidate carries the `long` label; this restricts generalization to that subset.
- Largest full prompt: 145,686 local tokens. The 3.25× request projection plus 16 output tokens is 473,496, leaving 50,792 under the current endpoint prompt limit. Largest projected Sift prompt is 106,096.

## Paired run

- Arms: original full context and Sift-compressed context at 32,768 target. Preserve task wording, final question, and message roles.
- Run 100 cases × 3 repeats × 2 arms = 600 generations. Use CLI seed `20261022`; the generation seed is `CLI seed + repeat + 1`, shared by paired arms. Randomize arm order within each repeat. Persist the CLI and per-request generation seed, outbound message SHA-256, Sift preprocessing duration, request start/end timestamps, and response data.
- The longest-task paired smoke is complete in two artifacts. It confirmed the requested model/provider, HTTP 200, normal finish, valid A–D answers, and exact local/provider prompt counts in the guard smoke. These one-task smokes establish no quality result.
- Preserve every attempt, failure, malformed answer, and route deviation. Do not silently retry or replace tasks. Score valid answers by exact match to the frozen key. Report response-level accuracy and invalids; primary paired quality uses each task's majority over three repeats and a 2×2 task-level paired outcome table. Do not treat the 300 responses per arm as independent tasks or select the best repeat.

## Spend and cache gates

- Before launch, verify manifest/source hashes, exact task count, target, endpoint/provider, rates, tokenizer/template availability, request-size projection, and cost math. The 1.5× local-input reserve plus maximum outputs estimates **$15.3457245** for the primary 600 calls at the recorded prices. Use two workers and a **$19.00 primary-run spend ceiling**. The two existing paired smoke artifacts report $0.06408108 combined upstream cost; adding the primary ceiling gives $19.06408108, leaving $0.93591892 beneath the $20 evaluation working budget.
- The runner requires the observed BYOK billing mode and a positive finite upstream receipt, charges per-call reported cost to the guard, and keeps 1.5× input plus output-cap reservations for in-flight calls. It closes new dispatch on a missing/invalid/zero upstream receipt, unexpected billing mode, wrong model/provider/status, missing prompt usage, or provider/local prompt ratio above 1.05. No new request may be dispatched after a gate closes. This is a best-effort client guard, not a provider-enforced hard billing cap; already dispatched requests may bill. Stop before launch if rates, endpoint metadata, or projection differ from the frozen assumptions.
- OpenRouter's MiniMax route supports implicit prompt caching and there is no verified cache-disable control. Do not describe any run as cache-cold. Preserve each call's `cached_tokens`, upstream cost and cost components, OpenRouter cost, and `is_byok`. Report observed cache-inclusive upstream cost by arm/repeat and overall, with cache-token counts/fractions beside it. First repeat is not necessarily cold.
- Separately calculate a reconstructed uncached counterfactual using reported prompt tokens × $0.30/M plus completion tokens × $1.20/M, and validate against raw cost components. It is not observed billing. OpenRouter may report `cost=0` with `is_byok=true`; call nonzero upstream inference cost provider-reported pass-through cost, not an invoice. Keep token reduction, cache-inclusive cost savings, reconstructed uncached savings, and latency separate.
- Report input reduction as `(sum full provider prompt tokens - sum Sift provider prompt tokens) / sum full provider prompt tokens`, with per-pair distributions as context. Report observed cost savings with the same formula over upstream costs; use the uncached reconstruction only as a labeled counterfactual. Pair latency by task/repeat and provide median/spread. Include preprocessing and wall-clock runtime separately from API latency.

## Analysis and publication

Report 300 outputs per arm, invalid counts and denominators, per-task majority accuracy, paired correctness cells (both correct/full only/Sift only/neither), exact paired uncertainty on task outcomes, input-token totals and distributions, cached-token fractions, actual cache-inclusive and reconstructed uncached costs, TTFT/end-to-end latency, Sift preprocessing time, model/provider/endpoint, dataset revision, run date, and hashes. Limit inference to this length-conditioned sample of the training split. LongBench does not establish full-suite results or end-to-end Codex/Claude Code agent quality.

After reviewing failures, use independent reviewers to diagnose a bounded set and make only evidence-backed Sift improvements. Preserve this original run, freeze the revised code, and rerun the same cases/settings for paired before/after evidence. Update README marketing claims only from measured results; keep agent-workflow evidence separate.

## Current readiness status

- The manifest and task sample are frozen; runner, protocol, core, and all preparation/rendering module hashes are checked before work. The runner now rejects zero BYOK upstream cost receipts and records run/per-request seeds, outbound message hashes, request timestamps, and Sift preprocessing time. Targeted local preflight and receipt assertions passed.
- Both smoke artifacts prove route and token-count behavior. Cache state changed observed paired cost from $0.05338494 to $0.01069614 across identical prompts; cost reporting must include cached-token counts and distinguish observed from reconstructed uncached amounts.
- The separate Qwen 100-task job is live at 87/100 tasks. Do not restart its service until the process exits and its result is preserved; it is not evidence for this MiniMax result.
- Codex Advisor council (Gemini first, then Sol) recommends launch only after the Qwen run completes and the current route/pricing plus budget reservations are rechecked. The read-only Claude Code review also flagged source/provenance drift; seed, request-hash, and preprocessing telemetry are now recorded. Keep the user's custom Claude gateway route unchanged.
- Remaining launch gates: let the Qwen run finish; recheck endpoint metadata/prices and the primary-run cost projection; confirm `OPENROUTER_API_KEY` is available without printing it; then run with seed 20261022, two workers, target 32768, and the $19.00 primary-run ceiling.
