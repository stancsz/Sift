# Native Claude Code context-budget calibration, 2026-10-16

## Question and scope

Does Sift help a coding agent finish this task when its context is reduced to 24,576 or 16,384 tokens? This was one exposed synthetic least-privilege rollup task, one run per arm, with Claude Code 2.1.251 backed by local Qwen 3.8 27B. It is a development calibration, not a held-out benchmark or causal estimate. The selector source, fixture manifest, evidence, prompts, and run-level values are recorded in the [machine-readable results](../results/native-agent-least-privilege-rollup-context-calibration-2026-10-16.json).

Acceptance required normal agent termination, the visible tests, and independent gold checks. The evidence audit also checked whether compaction happened before the agent edited evidence-dependent behavior.

## Results

| Context target | Arm | Accepted | Task time | Mean client TTFT | Client input / cache-read / output tokens | Astra-equivalent arithmetic per attempt* | Qualification |
|---|---|---:|---:|---:|---:|---:|---|
| 24K | Full | Yes | 260 s | 2.44 s | 29,658 / 280,403 / 7,048 | $0.929 | Accepted baseline |
| 24K | Recency | Yes | 268 s | 3.99 s | 54,743 / 223,182 / 6,846 | $1.113 | Accepted baseline |
| 24K | Sift | Yes | 191 s | 1.98 s | 25,237 / 222,095 / 5,210 | $0.735 | **Unqualified:** no Sift compaction before edit |
| 16K | Full | Yes | 203 s | 2.37 s | 26,071 / 226,912 / 5,448 | $0.760 | Accepted baseline |
| 16K | Recency | Yes | 987 s | 3.62 s | 224,641 / 490,814 / 29,253 | $4.200 | Accepted baseline; many turns |
| 16K | Sift | **No** | 288 s | 2.66 s | 37,009 / 96,679 / 4,500 | $0.692 | **Failed:** two 413 errors; no edit or required artifact |

TTFT is the mean of client-reported per-request values; task time is whole-task elapsed time. This harness did not capture per-response generation duration, so tokens per second were not measured. The arm order was fixed in advance as recency, Sift, then full context, which leaves possible order and warm-cache effects.

## What this says

- Sift can reduce the context sent to the model, but reduction alone is not evidence of a cheaper or faster accepted task.
- The 24K Sift run passed, but did not compact before editing. Its timing and token counts cannot support a Sift benefit claim.
- At 16K, actual compaction exposed a hard boundary: the active task or latest tool cycle could not fit, so Sift rejected two requests with HTTP 413 and the agent did not finish. This is a concrete reliability failure for this configuration.
- Full context passed at both targets. The 16K Sift attempt was faster than the 16K recency run but slower than full context, and it failed. Those elapsed times do not show that Sift itself caused the difference.
- Each arm ran once on an already exposed fixture. The results are too small to estimate typical task quality, latency, or cost.

## Cost interpretation

Local Qwen reported no provider API charge; hardware, electricity, and host costs were not measured. The Astra column applies GPT-6 Astra Standard short-context list rates to the local model's client-reported usage counters. It is arithmetic for one attempt, not an Astra run, invoice, or cost-per-accepted-task comparison. Repeated attempts are not modeled, and the 16K Sift attempt is rejected. Current rates are listed on the [official OpenAI pricing page](https://developers.openai.com/api/docs/pricing).

## Decision

Sift is useful today as a bounded context-selection component and as a way to test whether a request can be reduced while retaining evidence. It is not yet demonstrated as a reliable general-purpose way to make agent tasks cheaper or faster. For this task, neither context target produced a qualified accepted Sift result: at 24K it did not compact before the edit, and at 16K it failed before editing.

Keep the core frozen. The next useful test is a newly fixed task whose natural active tool cycles fit below the target, with independent evidence and acceptance checks. Require a Sift reduction before the first evidence-dependent edit, accepted completion, and provider-reported cache/input/output usage. Repeat randomized matched arms before drawing speed or savings conclusions. Do not raise the turn cap or relax acceptance to turn this calibration into a pass.
