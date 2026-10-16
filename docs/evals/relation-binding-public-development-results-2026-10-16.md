# Relation binding public development result

**Result: public development evidence, one task only.** The frozen run met its
predeclared diagnostic rule for an extraction-related Sift miss. This is not a
blind holdout, a general quality estimate, or proof of production savings.

## Outcome

All 12 calls returned HTTP 200 with a normal terminal outcome. Each used local
Qwen, and each reported zero cached prompt tokens.

| Arm | Exact Qwen prompt tokens | Qwen reported input / output | Correct | Mean TTFT | Mean response time | Astra-repriced cost per call* |
|---|---:|---:|---:|---:|---:|---:|
| Full context | 26,077 | 26,053 / 12 | 3/3 | 17.607 s | 18.016 s | $0.26113 |
| Sift | 5,760 | 5,736 / 14 | 0/3 | 4.459 s | 4.833 s | $0.05806 |
| Whole-record research candidate | 23,484 | 23,460 / 12 | 3/3 | 15.376 s | 15.770 s | $0.23520 |
| Oracle evidence control | 456 | 432 / 9 | 3/3 | 1.267 s | 1.500 s | $0.00477 |

The official key is D. Full context, the whole-record arm, and oracle evidence
answered D on every repeat. Sift answered C on every repeat. The source audit
found the gold `player_7` record incomplete in Sift's excerpts and intact in
the whole-record arm. Under the frozen interpretation rule, this is an
extraction-related failure for this case. It does not establish that the model
would fail on other prompts or that record-preserving selection is generally
better.

Sift reduced input by 78.0% and mean local TTFT by 74.7% relative to full
context, while losing the answer on all three repeats. The whole-record
candidate preserved this answer with 9.9% fewer reported input tokens and
12.7% lower mean local TTFT than full context, but still forwarded about four
times as many exact prompt tokens as Sift. All latency observations were cold
local Qwen timings with caching disabled. Neither speed result predicts Astra
latency or cache behavior.

## Illustrative Astra arithmetic

For requests below Astra's long-context threshold, the official standard API
rates are $10 per million uncached input tokens and $50 per million output
tokens. The table reprices the *local Qwen-reported* input/output counts using
those rates:

`(input_tokens × $10 + output_tokens × $50) / 1,000,000`

This is an example calculation, not an Astra run or invoice. Astra's tokenizer,
reasoning-token output, prompt formatting, and cache behavior may change the
actual bill. The Qwen trial itself incurred $0 in provider API spend. See the
[official GPT-6 Astra pricing page](https://developers.openai.com/api/docs/models/gpt-6-astra)
for current rates and thresholds.

For this one task, the Sift row's lower hypothetical price is not a valid
quality-adjusted saving because it returned the wrong answer. The whole-record
row illustrates a much smaller token and latency reduction while preserving
the answer. Repeat calls are not independent tasks, and this example should
not be generalized into a per-task success rate.

## Artifacts and reproduction

- [Frozen protocol](relation-binding-public-development-2026-10-16.md)
- [Raw machine-readable calls](../results/relation-binding-public-development-2026-10-16.json)
- Pre-inference protocol snapshot: commit `61176ca`, SHA-256
  `f9075e06672559d38d4e7e962f245714fa3e05cffdc9d1d174a707e7a0395e17`.
- Frozen selector commit: `59494ba60474404d9330b36304a39d46ad0cfcfe`.
- The candidate source was tracked after inference in `bbdb1eb`; its bytes match
  the SHA-256 recorded in the frozen protocol.
- Runner SHA-256: `89afc734a86676e8d6619a6343a1b0e81083db00b3427e07f21893bc19a34921`.
- Raw result SHA-256: `b9f1670edd820bb26fea84e958f296d47f0a87385cc24727776f1f2df8525f7d`.

The result replays model calls stochastically; exact token preparation is
deterministic against the pinned dataset, tokenizer endpoint, and frozen core.
The fixture is public and permanently retired from unseen validation.
