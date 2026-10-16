# Least-privilege rollup repeat, 2026-10-16

## Result

This is a randomized repeat on one exposed public synthetic task, not an
independent task or a quality estimate. The frozen input manifest verified
before all three runs. Claude Code 2.1.251 used local Qwen 3.8 27B, a 3,072-token
output cap, and the 24,576 estimated-token Sift target. Seed `20261017` produced
the order recency, full, Sift. The baseline failed as expected. The isolated
gateway was removed after the run.

| Arm | Accepted | Wall time | Mean client TTFT (n) | Uncached input | Cache reads | Output | Astra short-context estimate* |
|---|---:|---:|---:|---:|---:|---:|---:|
| Recency | No | 226.67 s | 6.505 s (11) | 25,195 | 146,691 | 4,964 | $0.6468 |
| Full | Yes | 264.51 s | 3.398 s (17) | 28,863 | 305,186 | 6,494 | $0.9185 |
| Sift | Yes | 238.90 s | 2.829 s (17) | 40,238 | 271,028 | 6,242 | $0.9855 |

Acceptance requires a normal client terminal result, the visible suite, and the
independent gold suite. Full and Sift each passed all four visible tests and
nine gold tests. Recency exited with an error: the report contained three of
six permissions, omitting `dynamodb:Query`, `s3:GetObject`, and
`rds:DescribeDBInstances`; both visible and gold checks failed. Its lower
estimated price is therefore not an accepted-task saving.

Sift compacted two requests: 25,032 to 13,418 estimated tokens and 25,510 to
13,896. Across 18 Sift requests, gateway estimates summed to 284,113 raw and
260,885 forwarded tokens. Recency had 13 requests, none over target, and no
compactions. The full arm bypassed selection. Selector CPU was 247 ms summed
across Sift requests. These are request-stream totals, not unique conversation
tokens.

\*The estimate substitutes local Qwen client usage into GPT-6 Astra's published
short-context rates: $10/M uncached input, $1/M cache reads, and $50/M output.
It assumes zero cache writes. No Astra request was made; provider tokenizer
differences, real cache behavior, and invoices are not represented. On this
single accepted task, estimated Sift cost was 7.3% above full context despite
6.8% fewer combined uncached-plus-cached input tokens. Sift's uncached input was
higher and its cache reads lower. The observed Sift wall time and mean TTFT were
lower in this block, but the small fixed workload and shared warm backend do
not establish a causal latency improvement.

The run does not establish parity, general task success, or savings. It does
show that a repeat can change the recency outcome on the same task, while both
full and Sift passed in this block. Qwen engine generation-rate records were
not joined to these client requests by request ID, so no tokens-per-second
claim is made here. The prior single-block diagnostic is documented in the
[natural-agent pilot](natural-agent-pilot-2026-10-16.md#least-privilege-rollup-three-arm-diagnostic-2026-10-16).

## Reproduction record

- Fixture: `least_privilege_rollup`, frozen manifest SHA256
  `2c82403fba61c4ef6c5c89b04d036cc6e691aacee64a26fa9a41b55b7b71fb96`.
- Run result summaries and gateway measurements:
  [`least-privilege-rollup-repeat-2026-10-16.json`](../results/least-privilege-rollup-repeat-2026-10-16.json).
- Raw Claude/Qwen run records were retained locally under
  `%USERPROFILE%\.cache\sift-agent-runs`.
- The fixture is public development data and is retired from unseen validation.
