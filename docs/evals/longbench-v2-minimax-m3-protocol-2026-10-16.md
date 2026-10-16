# MiniMax M3 Sift context budget screen

Frozen before the benchmark requests on 2026-10-16. This is a public
development screen. It is not a blind holdout, acceptance test, or direct
comparison with the separately reported Qwen runs.

## Frozen inputs and sample

- Dataset: `zai-org/LongBench-v2`, revision
  `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`;
  `data.json` SHA-256 `15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2`.
- Model route: OpenRouter `minimax/minimax-m3`, provider sort `throughput`,
  fallbacks enabled. The returned provider name and usage receipt are retained
  per request. Do not combine these measurements with Qwen measurements.
- Frozen 10-case manifest:
  `longbench-v2-minimax-m3-sift-screen-2026-10-16.json`, SHA-256
  `c947b4c2a61ffe05964318afb79457aa0355e7e589206a1cf4320339d369cd38`.
- MiniMax tokenizer: `MiniMaxAI/MiniMax-M3`, tokenizer file SHA-256 is in the
  manifest. The published chat template is also pinned by hash there. The
  local budget counter renders this template with reasoning disabled; each
  request also records OpenRouter's provider-reported prompt count, which is
  authoritative for observed token usage.
- Cases were sampled deterministically, two each from rendered prompt-length
  bands 16-32K, 32-64K, 64-128K, 128-256K, and 256-900K. All ten are from the
  public LongBench v2 training split. This small sample supports diagnosis,
  not a broad quality claim.
- Sift core SHA-256: `c37f84829cf75a38f410e4eebb219ebf99c27c89a5c0b62a0ca9b70c36265de7`.
- Runner SHA-256 at freeze: `a880a0328d684ca58413297703d95f404204c606ded26f12fa3cc8605ef60f24`.
- Preparation script SHA-256 at freeze:
  `2eb34e08fbdb3d1acb69339505e1e228030b930e2d967b174e67490006adee77`.

## Comparison

Each case gets one full-context baseline. Sift gets one request at each
applicable budget in 65,536, 49,152, 32,768, 24,576, and 16,384 tokens. A Sift
request is omitted when its input already fits that budget. The local target
counter reserves 128 tokens below the named budget for template/provider
accounting differences. Record both local rendered counts and provider-reported
prompt counts; flag any Sift request whose provider count exceeds its named
target.

Requests are shuffled with seed `20261019` and run with at most four concurrent
requests. There is one repeat, one shared generation seed (`20261020`), no
retries, and no request-level fallback outside OpenRouter. Temperature is 0.1,
top-p is 0.8, reasoning is disabled, and output is capped at 16 tokens. The
question prompt requests exactly one letter. Only a response whose trimmed
content is exactly `A`, `B`, `C`, or `D` is scorable; all other terminal
responses remain incorrect in the denominator.

The target set consists of 48 requests: 10 full-context baselines, 10 at 16K,
8 at 24K, 8 at 32K, 6 at 48K, and 6 at 64K. The preflight local-tokenizer
estimate is 2,335,825 total input tokens. It is not a charge estimate.

## Reporting

Report, by arm and target, valid-answer rate, accuracy, provider prompt and
completion tokens, average time to first visible token, average completion
tokens per second, local preprocessing time, and provider usage cost fields.
Include paired full-context comparisons on the same cases that have a Sift
request at each target. Because request concurrency is four, timing is a
throughput-oriented experiment and does not estimate single-request latency.

OpenRouter's public listing at freeze showed $0.23/M input and $0.96/M output
tokens. The smoke request reported `is_byok: true`, zero OpenRouter `cost`, and
nonzero `cost_details.upstream_inference_cost`. Preserve those raw fields;
describe upstream cost as provider-reported pass-through usage, not as a
verified invoice or OpenRouter charge. No cost conclusion should be based on
the public list price when the receipt supplies a different amount.

The preflight smoke used a separate short arithmetic prompt, not a frozen
benchmark case. It returned `B`, ended normally, and reported zero reasoning
tokens. It is excluded from benchmark results.
