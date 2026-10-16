# Goal: LongBench v2 evaluation with OpenRouter MiniMax M3

## Objective

Run a reproducible, provider-attributed comparison of Sift against full-context prompting on a frozen 100-task LongBench v2 development sample. Measure answer quality, input tokens, upstream-reported cost, cache use, and latency. Use the evidence to decide what Sift can claim and what to improve next.

## OpenRouter MiniMax plan

Use OpenRouter's MiniMax M3 route for a paired comparison: send each selected LongBench v2 task once with its full prompt and once with the same task compressed by Sift to a 32,768-token target. Pin both arms to the MiniMax provider with fallbacks disabled, run three matched repeats across 100 frozen tasks, and retain per-request provider, token, cache, cost, latency, and scoring receipts. Start the 600-generation main run only after the active Qwen evaluation is terminal and the live endpoint, source hashes, request-size preflight, smoke receipts, and spend gates pass. Analyze quality and efficiency together; distinguish observed cache-inclusive cost from reconstructed uncached estimates, and publish only results supported by the task-level evidence.

## Execution plan

1. Use OpenRouter's `minimax/minimax-m3` route for both arms, pin requests to the MiniMax provider, and disable provider fallbacks. Recheck the selected endpoint, prompt limit, pricing, credentials, and frozen source hashes before spending on the main run.
2. On the frozen 100-task public training-split sample, compare full-context prompts with Sift-compressed prompts at a 32,768-token target. Run three paired repeats per task with matched settings and seeds, for 600 generations total. Keep the task wording, question, and message roles consistent between arms.
3. Start only after the Qwen job is terminal and the one-task smoke, request-size checks, receipt validation, and spend gates pass. Use two workers and a $19 primary-run ceiling, keeping total smoke-plus-main spend within the $20 working budget. This client-side ceiling is best-effort because already dispatched calls may still bill.
4. Preserve every response and receipt. Compare answer accuracy and paired task outcomes alongside provider prompt-token reduction, cache-inclusive upstream cost, reconstructed uncached cost, latency, preprocessing, and wall-clock time. Report cache effects and sample limits next to any savings claim.
5. Review the task-level failures, make only evidence-backed Sift changes, then rerun the same frozen sample and settings for a paired before/after readout. Publish only claims supported by those results; this sample is not a full-suite score or a blind holdout.

## Route and limits

- Send both arms through OpenRouter using `minimax/minimax-m3`, pinned to provider `minimax` with provider fallbacks disabled. Do not use an automatic model alias or let requests switch providers. Verify and save the returned provider and model for every response; exclude route deviations from the counted result and report them.
- The frozen manifest records the provider-specific endpoint observed on 2026-10-16: `minimax/minimax-m3-20260531`, 524,288 maximum prompt tokens, 512,000 maximum completion tokens, and $0.30/M uncached input and $1.20/M output. OpenRouter's broader model page advertises a 1M context, but that is not the selected endpoint's prompt limit. Recheck live metadata and rates immediately before dispatch; stop if they changed.
- Keep API credentials in environment configuration. Do not write secrets into source, manifests, logs, or result artifacts.

## Frozen experiment

- Dataset: pinned public LongBench v2 training data; 100 distinct task IDs in `docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json`.
- Sample: deterministic, length-conditioned development sample. Every full-context prompt is above the configurable 32,768-token Sift target and at most 150,000 local M3-rendered tokens. The frozen sample has 44 short, 56 medium, and zero `long` dataset labels; difficulty is balanced 50/50 and the candidate scan found 225 eligible cases. Say clearly that this is not a full-suite score or blind holdout.
- Arms: original full context versus Sift-compressed context, preserving task wording, final question, and message roles. Use the pinned MiniMax tokenizer and chat template for local counts. Manifest hashes freeze source data, prompts, answer keys, tokenizer/template, Sift core, runner, preparer, and sample settings.
- Repeats: three paired repeats per task (600 generations total), randomized arm order within each pair, with matching generation settings and repeat seeds. Keep all attempts and failures; do not silently retry, substitute tasks, or drop invalid outputs.
- Scoring: parse the benchmark's structured A–D choice and exact-match the published answer key. Report per-repeat accuracy, per-task majority outcomes, paired wins/losses/ties, invalid responses, and discordant cases. Do not select the best repeat.

## Readiness checks and spend control

1. Recheck endpoint/provider metadata, pricing, credentials, manifest hashes, target, and task count.
2. Project request size using the runner's conservative 3.25× local-token estimate plus the 16-token output cap; every request must remain below the live 524,288 prompt limit.
3. Run a one-task, one-repeat paired smoke with one worker. Confirm route attribution, HTTP/finish status, valid choices, provider/local token reconciliation, cache and cost receipts, latency capture, and spend-guard behavior. Preserve the smoke receipts.
4. Before the main run, verify the runner's estimated-cost guard and its actual-spend gate. The full 600-call run has a 1.5× estimated input reserve, about $15.35 at the frozen rates; the former 4× reserve was about $40.90. Use two workers and a $19.00 primary-run ceiling. Combined with the two completed smoke receipts ($0.06408108 upstream-reported), this leaves about $0.94 under the $20 evaluation budget. The guard is best-effort: already dispatched calls may still bill, so halt new dispatch on route, usage, price, or cost-receipt anomalies.
5. Launch the frozen run only when all gates pass, using CLI seed `20261022`. Save the exact command, run timestamp, worker count, paired generation seeds, route metadata, source hashes, settings, and every request/response/error/usage receipt. Preserve partial results if interrupted.

## Cache and cost reporting

OpenRouter's MiniMax endpoint supports implicit prompt caching, and no verified cache-disable control is available. Do not claim a cache-cold run. Preserve `cached_tokens`, provider-reported `cost_details`, and upstream inference cost for every arm and repeat. Report actual cache-inclusive upstream cost by arm/repeat and overall, with cached-token counts and cache fractions beside it. First-repeat cost is not necessarily cold.

Also calculate a clearly labeled *reconstructed uncached estimate* from raw input/output token usage and the verified uncached rates. Validate its aggregation against the raw receipts and output-price components. Treat this as a counterfactual estimate, not observed billing. Because cache hits and shared prefixes can affect the two arms differently, show both the observed cache-inclusive savings and the reconstructed uncached estimate; do not collapse them into one marketing percentage. OpenRouter responses may show `cost: 0` and `is_byok: true`; call the upstream value provider-reported pass-through cost, not an invoice or independently verified charge.

Keep these measures separate:

- input-token reduction from provider-reported prompt usage;
- actual cache-inclusive upstream cost reduction;
- reconstructed uncached cost reduction;
- model latency and total wall-clock runtime, including preprocessing where measured.

For each savings percentage, state the formula, denominator, sample, repeat aggregation, date, and route. Include per-task and distribution data so a mean is not mistaken for a universal saving. Report full-context and Sift quality beside all efficiency numbers.

## Improvement loop and publication

Audit quality regressions by task and failure type. Have independent reviewers inspect the scoring and a bounded set of representative failures. Make a targeted Sift change only when supported by the evidence, preserve the original run, and rerun the same frozen manifest/settings for a paired before/after comparison. Do not change the sample or scoring to improve the headline.

After acceptance, publish the protocol and raw aggregateable results in `docs/evals/` and `docs/results/`; update the README with clear, measured claims and sample/route/cache caveats adjacent to them. Keep this LongBench QA evidence distinct from native Codex or Claude Code agent-workflow evidence. Commit and push each reviewed milestone.

## Current status (2026-10-16)

- The 100-task MiniMax manifest and protocol are frozen. Independent manifest acceptance passed. The selected maximum is 145,686 local M3 tokens; its request-size projection is 473,496, leaving 50,792 tokens against the observed endpoint prompt limit.
- Two paired longest-task smoke artifacts exist: `docs/results/longbench-v2-minimax-m3-smoke-longest-2026-10-16.json` and `docs/results/longbench-v2-minimax-m3-smoke-guard-2026-10-16.json`. Both confirmed MiniMax attribution, HTTP 200, valid choices, and provider/local input counts in agreement. They are one task only and establish no quality claim. The second smoke exercised the 1.5× spend guard.
- The smokes show implicit caching can materially change observed costs: the later smoke had near-total prompt cache hits. The cost-reporting plan above therefore separates actual cache-inclusive cost from a reconstructed uncached estimate.
- The main 100 × 3 paired evaluation has **not** started. The runner now requires BYOK mode with a positive upstream cost receipt and records run/per-request seeds, outbound message hashes, request timestamps, and Sift preprocessing time. The manifest freezes and verifies the runner, protocol, sample preparer, dataset helper, renderer, and core hashes; targeted local preflight and receipt assertions passed. Codex Advisor council recommends proceeding only after the Qwen run completes and the live route/pricing and budget gates are rechecked. The primary-run ceiling is $19.00.
- The separate Qwen run remains active. Keep it undisturbed until terminal; its existing prompt-cache behavior makes it exploratory evidence only.
- A separate exploratory Qwen run is not evidence for this MiniMax comparison. Preserve it without restarting its service until its current run ends; disclose its cache conditions if it is later used as context.
