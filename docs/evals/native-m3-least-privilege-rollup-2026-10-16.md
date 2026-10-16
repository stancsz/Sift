# Native MiniMax M3 least-privilege rollup diagnostic, 2026-10-16

This is a single, fixed-order diagnostic on an exposed public synthetic task.
It validates the corrected MiniMax gateway route, the native Claude Code
runner, acceptance checks, and body-free evidence telemetry. It is not a
held-out quality study or a general performance comparison.

The frozen task asks Claude Code to implement a least-privilege rollup from
four audit exports and policy notes. The full-context and Sift 16K arms passed
the same visible and independent gold tests. The recency 16K arm failed closed
before editing. All runs used Claude Code 2.1.251, the same OpenRouter
`minimax/minimax-m3` route, 3,072 output tokens, the frozen fixture manifest,
and no configured retries. The arm order was full, Sift 24K, recency 16K, then
Sift 16K. Runs were not randomized or repeated.

| Arm | Accepted | Task time | Mean TTFT (samples) | Client-reported usage: input / cache read / output | Client-reported cost |
|---|---:|---:|---:|---:|---:|
| Full context | Yes | 63.3 s | 2.92 s (18) | 20,919 / 209,612 / 7,847 | $0.421 |
| Sift, 24,576 target | Yes; no compaction | 128.3 s | 10.49 s (10) | 20,395 / 123,248 / 9,384 | $0.417 |
| Recency, 16,384 target | No; HTTP 422 `late instruction cannot be compacted` before edit | 16.9 s | 1.15 s (11) | 11,311 / 37,109 / 634 | $0.104 |
| Sift, 16,384 target | Yes | 131.2 s | 2.06 s (30) | 235,570 / 112,018 / 10,138 | $1.492 |

The provider cost column is Claude Code's client-reported `total_cost_usd`,
not a verified OpenRouter invoice. Decode tokens per second were unavailable.
TTFT sample counts and cache state differ, so the averages do not rank latency.
The 24K Sift run's largest selector input was 20,032 tokens; it never
compacted, so it is a no-op control rather than evidence for Sift.

At 16K, Sift compacted 27 of 31 requests. Summed selector estimates fell from
1,289,644 to 333,928 tokens (74.1%); these counts include repeated history
and are not billable provider usage. The independent pre-edit audit verified
that request 29 was compacted from 88,037 to 16,352 estimated tokens before
the first direct file edit, with all four required policy/event spans present
in that forwarded request. The final artifact passed the visible and gold
checks.

That accepted Sift run still took 2.07 times as long and reported 3.55 times
the full-context cost. Its cumulative client-reported input, cache-read, and
output tokens were also higher. The recency run's lower spend is not a saving:
it did not produce an accepted artifact. This single exposed pair cannot
establish that Sift caused the cost or time increase, but it shows that a
smaller per-request prompt does not guarantee a cheaper or faster completed
task.

## GPT-6 Astra price sensitivity

For a rough cross-provider illustration, repricing the reported token totals
at GPT-6 Astra's standard short-context rates ($10/M uncached input, $1/M
cached input, $50/M output, and no reported cache writes) gives $0.811 for
full context, $0.796 for the 24K no-op, $0.182 for the failed recency arm, and
$2.975 for Sift at 16K. These amounts are arithmetic from MiniMax-reported
usage, not Astra requests, invoices, or cost-per-accepted-task measurements.
The Sift 16K value cannot be presented as an expected Astra cost. See the
[official Astra pricing](https://developers.openai.com/api/docs/models/gpt-6-astra)
and the [cost comparison method](../cost-comparison.md).

## Evidence and limits

The checked-in [machine-readable result](../results/native-m3-least-privilege-rollup-2026-10-16.json)
records source and fixture hashes, request-level selector summaries, usage,
acceptance, timing, and qualifications. Detailed native transcripts and
gateway logs remain in the local `.runs/native-m3-rollup-c25fcfe` directory;
the published record omits conversation bodies. Retire this fixture from
unseen evaluation. Continue with independently authored tasks and repeated,
randomized arms before making a broader quality, speed, or savings claim.
