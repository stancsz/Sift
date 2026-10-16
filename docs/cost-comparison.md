# Compare provider cost with and without Sift

Sift makes no model calls. It selects a smaller request on CPU. To compare what
you pay, run the same accepted work with and without Sift through the same
provider, model, settings, output limit, and cache conditions. Use provider
usage or LiteLLM's per-request spend logs for the billable totals. Sift's
estimated token counts are useful for its input limit, but are not a provider
invoice.

## A simple price example

For scale, suppose a single request would otherwise send **1,000,000 uncached
input tokens** to GPT-6 Astra. At the standard API rates checked on 2026-10-16,
uncached short-context input is $10.00 per million tokens. Because this
baseline exceeds 272,000 input tokens, Astra applies long-context prices to
the full request: $20.00 per million input tokens and $75.00 per million
output tokens. If Sift instead causes the provider to receive **24,576
billable input tokens**, its input charge is $0.2458. Assume both runs
generate the same 10,000 output tokens.

| One request, no prompt cache | Input charge | Output charge | Total |
|---|---:|---:|---:|
| Without Sift | $20.0000 | $0.7500 | $20.7500 |
| With Sift | $0.2458 | $0.5000 | $0.7458 |
| Difference | $19.7542 less | $0.2500 less | $20.0042 less (96.4%) |

### Warm-prefix sensitivity

The cold-cache table is not the only useful comparison. For one follow-up
request, assume the 1,000,000-token full prompt is already cached for 95% of
its input, while the 24,576-token Sift prompt has either the same 95% cache
share or no cache hit. This excludes the earlier cache-write bill and keeps
the same 10,000 output tokens.

| One warm follow-up request | Input charge | Output charge | Total |
|---|---:|---:|---:|
| Without Sift, 95% cached | $2.9000 | $0.7500 | $3.6500 |
| With Sift, 95% cached | $0.0356 | $0.5000 | $0.5356 |
| With Sift, no cache hit | $0.2458 | $0.5000 | $0.7458 |

Under these assumptions Sift is $3.11 (85.3%) cheaper with a matching 95%
cache share, or $2.90 (79.6%) cheaper if its shortened prompt gets no cache
hit. These are price sensitivities, not measured cache rates or task savings.
Sift's effect on prefix reuse must be measured from provider usage; include the
initial cache-write cost when calculating a whole conversation or task.

The cold-cache table is arithmetic for stated token counts, not a measured Sift
task result. It assumes provider-counted input equals the example counts, no
cache hits or writes, equal task success, and equal output token counts; retries
and tool charges are excluded. The 24,576 Sift target is an estimate; the
actual request can count differently. The 1M input example is not a claim that
every request, including its tools and output reserve, fits a 1.05M context
window. Use provider invoices and usage for actual totals.

GPT-6 Astra's short-context rates are $10.00 per million uncached input tokens,
$1.00 per million cached input tokens, $12.50 per million cache-write tokens,
and $50.00 per million output tokens. Above 272,000 input tokens, its
long-context rates double input and cache prices and multiply output by 1.5
for the full request. Its documented context window is 1,050,000 tokens. See
the [GPT-6 Astra pricing and threshold](https://developers.openai.com/api/docs/models/gpt-6-astra)
and [OpenAI API pricing](https://developers.openai.com/api/docs/pricing).
Rates vary by model, provider, service tier, and date. LiteLLM tracks request spend from its pricing map and
exposes it in response headers and spend logs; see its
[spend-tracking guide](https://docs.litellm.ai/docs/proxy/cost_tracking).
The provider invoice is the final billing record.

## Run a fair comparison

For every arm, retain the same accepted task, provider, model, sampling and
reasoning settings, tool definitions, output cap, and retry policy. Alternate
run order and predeclare whether the provider cache is cold or warm. Record each
request's provider cost and usage, including uncached input, cache reads, cache
writes, output, retries, and any auxiliary calls. Also record task acceptance,
wall time, Sift CPU time, and cache reuse. Report raw totals and cost per
accepted task. If no task is accepted, cost per accepted task is unavailable;
a cheaper failed run is not a saving.

Calculate provider cost per arm by summing its request spend. Report Sift CPU or
hosting expense separately unless it is measured and allocated to the same
accepted workload. For a local model, report provider API spend as $0 and keep
electricity, hardware, and operating cost separate unless measured. Do not
convert estimated tokens or local GPU time into dollars without an explicit
price and method.

## What current Sift trials establish

The native Claude Code and Codex pilot ran local Qwen through a shared GPU. Its
provider API charge was $0 in both selector arms; electricity and hardware
costs were not measured. All four delivered artifacts failed independent
acceptance, so the pilot establishes neither savings nor cost per accepted
task. Earlier cold-prefill measurements also used local Qwen and older Sift
code. They are latency and token-count observations, not monetary evidence.
See the [evaluation record](evaluation.md) for denominators and limitations.

A separate one-run Claude Code research-task pilot passed independent acceptance
with full context, Sift, and recency. It used an 8,192-token stress target, a
fixed arm order, and a shared warm/mixed local Qwen cache. Provider API spend
was $0 in all three arms; the task did not measure Astra costs. Sift had fewer
client-reported input-plus-cache tokens than full context, but its mean TTFT
and task time were higher in this single run. Treat this as a cache-reuse
diagnostic, not a measured saving. See the [pilot report](evals/native-research-pilot-2026-10-15.md)
and [machine-readable results](results/native-research-pilot-2026-10-15.json).

A later single-arm least-privilege IAM stress run sent 53 local Qwen requests;
Sift compacted 45 and reduced summed estimated request input by 73.4%. The run
timed out at 1,200 seconds and failed independent acceptance, so it has no
cost-per-accepted-task result and cannot support a savings claim. Full context
could not fit the same 134,913-token request on the 32K backend. API spend was
$0, and hardware cost was not measured. See the [stress-run record](results/least-privilege-audit-sift-stress-2026-10-16.json).

A second public operations-log development screen failed on all three arms:
recency and Sift ended at Claude Code's reported 32 MB conversation limit,
while full context exceeded local Qwen's 32,768-token window. Local API spend
was $0, but no arm produced an accepted task, so cost per accepted task and
any saving are unavailable. Electricity and hardware cost were not measured.
See the [incident screen](results/native-incident-reconstruction-development-2026-10-16.json).

The frozen LongBench v2 diagnostic used local Qwen, so its API spend was also
$0 and it does not provide an Astra invoice. On the 16 above-target cases,
Sift reduced mean local Qwen input from 26,822 to 19,347 tokens (27.9%), but
scored 15/48 repeated answers versus 20/48 for full context. This does not
support claiming equal-quality savings. Applying Astra's price to Qwen token
counts would be a rough illustration only; provider tokenization, caching,
and billed usage must be measured on Astra. The large 1M-to-24,576 example
above remains price arithmetic under an equal-success assumption, not a result
we have demonstrated for current Sift. See the [evaluation record](evaluation.md).

A fresh six-case public LongBench v2 Table QA screen used MiniMax M3 through
OpenRouter. Sift reduced provider-reported input by 82.9% to 93.4% and the
provider's pass-through cost field by 82.9% to 93.5% on matched successful
requests. OpenRouter marked the requests as BYOK and top-level cost was $0, so
the pass-through amounts are not invoice-verified. Full context got 1/5
correct answers; Sift got 6/28 across targets, with tiny per-target samples.
One full request failed because the provider's endpoint limit was lower than
the local tokenizer estimate. The result shows input reduction, not
equal-quality savings or production latency benefit; Sift preprocessing was
not included in the response timings. See the [fresh sample report](evals/longbench-v2-minimax-m3-table-fresh-2026-10-16.md)
and [raw result](results/longbench-v2-minimax-m3-table-fresh-2026-10-16.json).

The 2026-10-16 least-privilege rollup diagnostic later completed one public
synthetic task in all three arms. Substituting each arm's client-reported local
Qwen usage into Astra's short-context rates gives illustrative totals of
$1.7738 for recency, $1.0593 for Sift, and $0.9991 for full context. These are
not measured Astra costs: the full-context arm is lowest, and no Astra request
was made. Since only one exposed task was tested, this comparison does not
establish savings or equal-quality cost reduction. See the
[three-arm diagnostic](evals/natural-agent-pilot-2026-10-16.md#least-privilege-rollup-three-arm-diagnostic-2026-10-16).

A randomized repeat of the same public fixture accepted both full and Sift,
while recency missed three requested permissions. Substituting local Qwen usage
into the same Astra short-context rates gives $0.9185 for full and $0.9855 for
Sift; the failed recency arm estimates $0.6468 and is not an accepted-task
saving. This is one repeated task, not general cost evidence. See the
[repeat report](evals/least-privilege-rollup-repeat-2026-10-16.md).
