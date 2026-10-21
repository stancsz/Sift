# Compare provider cost with and without Sift

Sift makes no model calls. It selects a smaller request on CPU. To compare what
you pay, run the same accepted work with and without Sift through the same
provider, model, settings, output limit, and cache conditions. Use provider
usage or LiteLLM's per-request spend logs for the billable totals. Sift's
estimated token counts are useful for its input limit, but are not a provider
invoice.

## Recorded LongBench cost

The completed 344-question study used three repeats per arm. Its published
aggregate records the following successful-request usage and cost:

| | Without Sift | With Sift | Total |
|---|---:|---:|---:|
| Provider prompt tokens | 66,007,295 | 26,628,470 | 92,635,765 |
| Recorded usage-receipt cost | $8.94 | $3.69 | **$12.63** |
| Our uncached input-only calculation | $19.80 | $7.99 | **$27.79** |

Our calculation is `prompt tokens × $0.30 / 1,000,000`, using the dated
MiniMax route price. It excludes output tokens because the published aggregate
does not contain their total. The lower receipt costs reflect the provider's
cache-sensitive accounting. See the [published aggregate](results/longbench-v2-minimax-344-aggregate-2026-10-20.json)
and [rate snapshot](evals/longbench-v2-openrouter-minimax-m3-endpoints-2026-10-20T1651Z.json).

The six selected tracked experiments below report **$35.96** in usage-receipt
costs altogether. This subtotal covers these experiments, rather than every
project call or an account invoice; shared benchmark questions are separate
requests in separately scheduled runs.

| Experiment | Recorded cost |
|---|---:|
| [344 questions, three repeats per arm](results/longbench-v2-minimax-344-aggregate-2026-10-20.json) | $12.63 |
| [100 questions, 600 receipt-backed requests](results/longbench-v2-minimax-600-2026-10-17.json) | $4.52 |
| [503-question incomplete run, all valid receipts](results/longbench-v2-minimax-m3-fullsuite-progress-2026-10-17.md) | $18.08 |
| [Field-pruning pilot, 36 requests](evals/longbench-v2-field-pruning-pilot-2026-10-17.md) | $0.11 |
| [Initial screen, 48 requests](evals/longbench-v2-minimax-m3-results-2026-10-16.md) | $0.51 |
| [Relation-binding study, 36 fresh requests](evals/longbench-v2-minimax-relation-stage1-v3-analysis-corrected-2026-10-17.md) | $0.11 |
| **Selected study subtotal** | **$35.96** |

The 503-run matched-pair subset and reused historical baselines are already
inside their parent records and are not added again. Subscription probes priced
at illustrative API rates are excluded from this spend subtotal.

Separately, $2.05 is reserved for 13 historical requests without usage receipts;
that reserve is not counted as money spent. The newly authorized 344 × 3 × 2
run has a $41.87 conservative schedule estimate and a $100 client cap. Account
balances and invoice reconciliation are not needed for these calculations.

## Synthetic retrieval probe: 950K-token archive

We compacted one synthetic archive with Sift and sent the resulting request
through isolated Subroute staging to GPT-6 Astra and Gemini 4 Argon. The raw
archive was estimated at 950,401 input tokens; Sift's forwarded estimate was
32,698. Subroute recorded 32,502 input / 6 output tokens for Astra and 37,003
input / 41 output tokens for Gemini.

**Observed Sifted requests**

| Model | Input tokens (Subroute receipt) | Output tokens | Fixture result |
|---|---:|---:|---|
| GPT-6 Astra | 32,502 | 6 | Recorded fixture match* |
| Gemini 4 Argon | 37,003 | 41 | Recorded fixture match* |

Sift's 32,698 forwarded-token count is an estimate; the provider tokenizers and
request framing differ.
*The run record says both replies matched the planted fact, but the raw response text was not retained in the published result, so readers cannot independently verify the answer.

**Illustrative costs at public API rates (not billed amounts)**

| Model | Full-context API-rate scenario¹ | Sifted receipt, priced² |
|---|---:|---:|
| GPT-6 Astra | $19.0085 | $0.3253 |
| Gemini 4 Argon | $1.9012 | $0.0744 |

¹The full-context subscription requests were rejected before inference: Astra's
route rejected the context window and Gemini's bridge rejected the serialized
body size. These hypothetical costs apply uncached API rates to the 950,401-token
Sift estimate plus the output length observed with Sift; they are not successful
full-context cost measurements or bills. ²Subscription billing was unavailable;
these amounts apply public uncached API rates to Subroute's actual Sifted usage
receipts and are not subscription charges or invoices. Tokenizers and request
framing differ, so Sift's estimate and provider usage do not match exactly.

This one-fact, one-request-per-model probe does not establish task-quality
parity, agent-task results, measured savings, or a general cost reduction. The
Astra estimate uses the long-context rate above 272K input tokens for the raw
request and the standard rate for its Sifted request. Gemini's introductory
rates are listed through November 30, 2026. See the [full method, route limits, and rate
assumptions](evals/subroute-950k-token-cost-probe-2026-10-20.md), [GPT-6 Astra
pricing](https://developers.openai.com/api/docs/models/gpt-6-astra), and
[Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

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
and billed usage must be measured on Astra. The Subroute probe below measures
usage for the Sifted path and uses rate-card arithmetic for rejected full-context
requests; it does not show equal-quality or end-to-end savings. See the
[evaluation record](evaluation.md).

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
