# MiniMax M3 Sift context budget screen results

This is the public development run described in
[the frozen protocol](longbench-v2-minimax-m3-protocol-2026-10-16.md). The
[raw request report](../results/longbench-v2-minimax-m3-sift-screen-2026-10-16.json)
contains every request, including failed and unscorable outcomes.

## Results by context target

| Sift target | Sift requests | Sift correct | Full correct on same cases | Paired avg TTFT, Sift / full | Paired input-token reduction | Paired upstream-cost reduction | Mean measured decode tok/s† |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 64K | 6 | 2/6 | 3/6 | 1.70 / 5.59 s (n=5) | 83.2% (n=5) | 93.1% (n=5) | 316 |
| 48K | 6 | 2/6 | 3/6 | 2.45 / 5.59 s (n=5) | 83.2% (n=5) | 94.2% (n=5) | 43 |
| 32K | 8 | 2/8 | 4/8 | 1.86 / 4.85 s (n=7) | 82.2% (n=7) | 82.3% (n=7) | 65 |
| 24K | 8 | 3/8 | 4/8 | 1.90 / 4.85 s (n=7) | 84.3% (n=7) | 86.8% (n=7) | 109 |
| 16K | 10 | 3/10 | 4/10 | 1.93 / 4.17 s (n=9) | 86.2% (n=9) | 86.9% (n=9) | 59 |

The full-context baseline scored 4/10. One 407K-token full request failed with a
connection error. The Sift version of that case completed. Across all 48
requests, 45 produced a valid one-letter answer, two completed with an
unscorable output, and one full-context request failed. Failures count as
incorrect. No request was retried. Provider-reported token counts matched the
local rendered-template counts for completed calls, and no Sift request crossed
its target.

## What this suggests

On this sample, Sift cut the input tokens by about 82-86% for the matched cases
and reduced TTFT by roughly 2.2-3.9 seconds while the four-request pool was
active. The MiniMax/OpenRouter path completed 48 requests in 30.7 seconds
after prompt preparation. Re-preparing the 38 Sift prompts took 60.7 seconds
of local wall time, averaging about 1.1 seconds per 16K prompt and 1.5-2.0
seconds per larger target. Per-target and per-case timings are in the
[selection timing report](../results/longbench-v2-minimax-m3-sift-preprocess-timing-2026-10-16.json).
Sift's local selection and token recount therefore remain material to
end-to-end latency on this machine.

The quality result is mixed and too small to establish safety: each Sift target
scored one or two fewer answers than the corresponding full-context cases.
The public sample has only two cases in each length band, every case belongs to
the public training split, and there was one generation per arm. Treat these
accuracy differences as a warning signal for follow-up, not a reliable estimate
of Sift's average quality effect.

† The model was asked to return one letter, so responses contained only about
1-2 completion tokens each. The displayed token-per-second means are
dominated by stream timing granularity and are not useful estimates of sustained
generation speed. TTFT is the meaningful latency measurement in this run.

## Usage and cost fields

The 48 request receipts report zero OpenRouter `cost` and `is_byok: true`.
Their `cost_details.upstream_inference_cost` values sum to $0.5142. That is the
provider-reported pass-through estimate, not a verified billing invoice. For
matched cases, this field was 82.3-94.2% lower for Sift, depending on target.
OpenRouter's public M3 listing at run time showed $0.23 per million input and
$0.96 per million output tokens; actual provider routing and BYOK billing can
differ ([current OpenRouter MiniMax M3 pricing](https://openrouter.ai/minimax/minimax-m3/pricing)).

The runner used throughput-sorted OpenRouter routing with fallbacks and four
concurrent requests. TTFT therefore reflects a parallel throughput test, not
single-request latency. These measurements are separate from the Qwen-local
results and are not a cross-model comparison.
