# Fresh LongBench v2 Table QA sample, MiniMax M3

This is a small public benchmark diagnostic for Sift's current selector. It is
not a blind holdout, an independently authored task set, or a model comparison.
The six rows were selected by a seeded sample from the remaining eligible
LongBench v2 Table QA rows after excluding case IDs used by the earlier
published screens. The questions and answers remain public and may have been
seen during model training.

## Protocol and provenance

- Dataset revision: `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`.
- Dataset SHA-256: `15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2`.
- Seed: `20261017`; six eligible rows were selected before looking at prompts
  or outputs. The source contains one easy/short, three hard/medium, one
  easy/medium, and one hard/short case.
- Model: `minimax/minimax-m3` via OpenRouter throughput-sorted routing with
  fallbacks enabled. Temperature 0.1, top-p 0.8, reasoning disabled, output
  cap 16, one repeat, four concurrent workers, no retries.
- Arms: exact full prompt and Sift targets of 16K, 24K, 32K, 48K, and 64K.
  The 48K and 64K arms have five cases because one full-context request failed.
- Sift source SHA-256: `efd224e19f96d86e0c4836fc1ff654ed9743db95b190365b88e9d06b2c035179`.
- [Machine-readable sample manifest](longbench-v2-minimax-m3-table-fresh-2026-10-16.json)
  SHA-256: `156a44eefb95e02a3a941cd2e40bcfc087afb163912bc4616f3ffdf161b6959b`.
- [Raw request results](../results/longbench-v2-minimax-m3-table-fresh-2026-10-16.json).

The manifest's expected context window was 1,048,576 tokens, but the selected
provider endpoint rejected one full prompt: its stated endpoint limit was
524,288 and its request estimate was about 558,513 tokens. The local published
MiniMax tokenizer had estimated 187,640 tokens for that prompt. Keep this as a
provider capacity/tokenization mismatch and failed full-context observation;
do not retry it or treat it as an answer. The Sift requests for that case fit.

## Results

| Arm | Valid answers | Correct | Provider prompt tokens | Upstream-reported cost* |
|---|---:|---:|---:|---:|
| Full context | 5/5 | 1/5 | 1,227,471 | $0.368090 |
| Sift 16K | 6/6 | 2/6 | 96,971 | $0.028921 |
| Sift 24K | 6/6 | 1/6 | 143,664 | $0.037702 |
| Sift 32K | 6/6 | 1/6 | 184,539 | $0.050007 |
| Sift 48K | 5/5 | 1/5 | 217,435 | $0.065089 |
| Sift 64K | 5/5 | 1/5 | 260,220 | $0.077922 |

\* OpenRouter marked these calls `is_byok=true` and its top-level cost as
$0. The amounts shown are sums of the pass-through
`cost_details.upstream_inference_cost`; they are not invoice-verified and are
not billed-cost claims.

On matched successful pairs, Sift used 93.4%, 90.3%, 87.6%, 85.7%, and 82.9%
fewer provider-reported prompt tokens at 16K, 24K, 32K, 48K, and 64K,
respectively. The corresponding pass-through cost reductions were 93.5%,
91.7%, 89.1%, 85.8%, and 82.9%. Paired mean TTFT was 6.276 seconds for full
context versus 2.114, 2.414, 1.885, 4.765, and 2.588 seconds for those Sift
targets. These are single observations on at most five matched cases, with
four-worker concurrency and routed provider fallbacks. They are diagnostic,
not reliable latency estimates. The current runner's response time does not
include Sift preprocessing, so these are not end-to-end speedups.

Sift scored 6/28 across all five targets, versus 1/5 among successful full
requests. At 16K it scored 2/6. Because samples are tiny, public, and noisy,
this supports neither a quality advantage nor a quality-preservation claim.
Most Sift answers were valid structured choices, which only establishes that
the API returned parseable answers.

## Interpretation and next evidence

The run confirms that selecting much shorter prompts can materially reduce
provider-reported input and pass-through cost on this sample. It does not show
that those savings preserve task quality or reduce cost per accepted task.
The aggregate Sift score is poor, and the full-context denominator is small.
This makes independent extraction fixtures and accepted multi-turn agent
tasks more decision-relevant than expanding the selector or claiming an
optimal context target.

Next, independently author and freeze evidence-retention fixtures before
running arms; then evaluate accepted agent tasks with matched provider/model,
cache conditions, tool budgets, and output caps. Include preprocessing time,
cache read/write tokens, task completion and acceptance, and invoice-verified
cost. Keep this public sample labeled as development evidence.
