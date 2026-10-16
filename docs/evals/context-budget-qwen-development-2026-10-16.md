# Qwen context-budget development screen, 2026-10-16

**Status: public development diagnostic, not a blind holdout or a selected
default.** It compares smaller Sift targets on the same ten LongBench v2
questions already used in the public Qwen extension. These cases are exposed
and reused here to inspect a budget curve; they cannot support a release or
generalization claim.

## Setup

The Qwen3.8-27B Unsloth IQ3_S model ran locally through llama.cpp. The runtime
reported a 32,768-token context, with 4,096 reserved for output; full prompts
were 24,636 to 28,213 exact input tokens. Sift used the same local Qwen input
token counter at targets 8,192 and 16,384. For the 24,576 point, this report
reuses the completed [10-case extension](../results/longbench-v2-qwen-extension-2026-10-16.json)
at the same model, tokenizer, prompt wrapper and generation settings. Every
arm had three generations per case, temperature 0.1, a 16-token output cap,
thinking disabled, prompt caching disabled, and no retries. The two new runs
are retained in [the 8,192 report](../results/context-budget-qwen-8192-2026-10-16.json)
and [the 16,384 report](../results/context-budget-qwen-16384-2026-10-16.json).

The exact input tokenizer was used for selection and measurement. Production
LiteLLM estimates can differ. Each arm made 30 calls and all calls terminated
normally. Mean effective latency adds Sift's measured preprocessing wall time
to model end-to-end time. The existing 24,576 extension used a separate run
seed; only the task-level descriptive outcomes and averages are compared.

## Results

| Sift target | Task-majority correct, Sift / full | Paired outcomes (both / full-only / Sift-only / neither) | Mean input tokens, Sift / full | Mean TTFT, Sift / full | Mean effective latency, Sift / full | Illustrative Astra input charge, Sift / full |
|---:|---:|---|---:|---:|---:|---:|
| 8,192 | 5/10 / 5/10 | 5 / 0 / 0 / 5 | 8,153 / 26,216 | 5.82 / 17.71 s | 6.48 / 18.03 s | $0.0815 / $0.2622 |
| 16,384 | 5/10 / 5/10 | 4 / 1 / 1 / 4 | 16,357 / 26,216 | 10.80 / 17.82 s | 11.58 / 18.14 s | $0.1636 / $0.2622 |
| 24,576 | 5/10 / 5/10 | 5 / 0 / 0 / 5 | 24,544 / 26,216 | 16.80 / 18.15 s | 17.69 / 18.48 s | $0.2454 / $0.2622 |

The task score aggregates three generations by strict majority; ties are
incorrect. The 16,384 point has one task where full context wins and another
where Sift wins. At the other two targets, five tasks are correct in both arms
and five fail in both. Identical aggregate scores do not establish quality
parity: this is only ten public questions, including eight single-document
questions and two multi-document questions.

For these tasks, reducing the target shortened mean TTFT and reduced prompt
tokens. Mean Sift preprocessing was 0.36, 0.46 and 0.55 seconds at 8,192,
16,384 and 24,576 respectively. Including that work, mean Sift effective time
was 64%, 36% and 4% below full context. These results are single-request,
local llama.cpp timings with GPU utilization near 100%; decode throughput is
not a reliable differentiator from these short 12-token average answers.

The Astra figures are **input-only arithmetic, not API measurements**. They
apply the standard short-context $10 per million input-token rate to each
arm's mean local token count. They exclude cached-input pricing, output,
retries, Sift host cost, and any difference between local and provider token
counts. The [official pricing page](https://developers.openai.com/api/docs/pricing)
lists Astra at $10/M standard short-context input and $1/M cached input. This
screen made no Astra calls and spent $0 in provider API charges.

## What this says about targets

On this small public sample, 8,192 used 69% fewer input tokens than full
context and had the same task-majority outcomes as 24,576, with much lower
local TTFT. The 16,384 target was between them in token use and latency, with
one paired miss and one paired win. This is a useful signal that 24,576 should
not be assumed to be the cheapest effective target for every task. It is not
enough evidence to lower Sift's default: more domains, independent cases, and
accepted agent tasks are needed, especially for retrievals requiring distant
cross-document relations.

The current local server cannot test 32,768-to-65,536 input targets: its
configured context is 32,768, with the generation reserve and safety margin
still to account for. While loaded, the RTX 5070 Ti had about 1.7 GiB free and
the host reported about 7.2 GiB free RAM. A 65,536 input test requires a
separate runtime verified for at least 73,728 total context tokens and enough
measured KV capacity. Do not infer that capacity from the model's advertised
training length.

No selector behavior or default changed. The next quality gate remains a
fresh independently authored task set, with cache-cold and cache-warm arms
reported separately. The wider [context-budget sweep protocol](context-budget-sweep-protocol-2026-10-16.md)
defines the long-window test and measurements.
