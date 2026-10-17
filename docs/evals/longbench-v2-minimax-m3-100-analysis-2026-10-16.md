# LongBench v2 MiniMax M3 results

Run: `2026-10-16T23:52:59.566956+00:00` · Model: `minimax/minimax-m3` · 100 tasks × 3 repeats

## Quality

| Measure | Full context | Sift |
|---|---:|---:|
| Correct responses | 117/300 (39.0%) | 104/300 (34.7%) |
| Correct task majorities | 38/100 (38.0%) | 31/100 (31.0%) |
| Invalid choices | 10 | 3 |

Task-majority pairs: **26 both correct**, **12 full only**, **5 Sift only**, **57 neither**. Sift–full difference: -7.0%; 95% task-cluster bootstrap CI [-15.0%, 1.0%]; exact McNemar p=0.1435.

## Efficiency

| Measure | Full context | Sift | Reduction with Sift |
|---|---:|---:|---:|
| Provider prompt tokens | 24,245,610 | 8,281,452 | 65.8% |
| Cache-inclusive upstream cost | $1.9016 | $0.6114 | 67.8% |
| Reconstructed uncached cost | $7.2741 | $2.4852 | 65.8% |
| Reconstructed cache-adjusted cost | $1.9016 | $0.6114 | 67.8% |

Cached prompt-token fractions: full 92.3%; Sift 94.3%.

## Latency and scope

Median TTFT: full 1491 ms, Sift 1363 ms. Median request wall time: full 1540 ms, Sift 1455 ms. Median paired request wall-time difference (Sift − full): -96 ms; paired TTFT difference: -115 ms. Median Sift preprocessing: 1180 ms per request.

The task-cluster bootstrap interval is exploratory and conditional on this quota-balanced sample.

This is a length-conditioned sample from the public LongBench v2 training split, not a full-suite score or blind holdout. MiniMax implicit caching was enabled; the observed cost is cache-inclusive upstream-reported pass-through cost, not an invoice. The uncached and cache-adjusted cost rows are reconstructions, not observed charges.
