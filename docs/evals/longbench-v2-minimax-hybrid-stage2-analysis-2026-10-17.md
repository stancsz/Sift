# MiniMax LongBench v2 Stage 2 hybrid development evaluation

**Integrity:** VALIDATED · **Scope:** 100 tasks × 3 repeats · 300 Sift responses

This hybrid applies the research matrix to six in-sample relation-closure task IDs and unchanged default Sift to the other 94.

## Results

| Arm/reference | Exact answers | Task majorities | Provider prompt tokens | Cached prompt share | Observed pass-through cost |
|---|---:|---:|---:|---:|---:|
| Hybrid Sift (Stage 2) | 132/300 (44.0%) | 43/100 | 7,801,125 | 54.8% | $1.315868 |
| Historical Full | 117/300 (39.0%) | 38/100 | 24,245,610 | 92.3% | $1.901571 |
| Historical Sift | 104/300 (34.7%) | 31/100 | 8,281,452 | 94.3% | $0.611442 |

Against the saved Full-context reference, this sample recorded **+5.0 percentage points** in exact answers, **67.8% fewer provider prompt tokens**, and **30.8% lower observed pass-through cost**.

Against historical Sift, the hybrid recorded **+9.3 percentage points** in exact answers and **5.8% fewer prompt tokens**; observed pass-through cost was **115.2% higher**. Cache hit share was 54.8% for the hybrid and 94.3% for historical Sift, so cross-run cost is cache-sensitive.

## Runtime

The full request schedule took **26.5 minutes** from first dispatch through completion, including the safe checkpoint and resume. The resumed 207-request continuation took **10.8 minutes**. Per-request end-to-end median was **1801 ms** (p95 **3299 ms**).

## Limits

- Historical Full and Sift are non-concurrent cross-run references; provider behavior, cache state, and timing can differ.
- Historical observed costs are the saved upstream receipts from the frozen baseline run. Historical counterfactual estimates use that run's pinned input/output rates; its manifest has no cache-tier prices, so cached receipt costs are not reconstructed from rates.
- The relation-matrix candidate was developed on the same six LongBench training prompts it uses here; the 94 unchanged tasks add coverage for the hybrid policy, not candidate generalization.
- This is a 100-task development sample, not the full LongBench v2 suite or a blind holdout.
- Upstream-reported cost is cache-inclusive provider pass-through data, not an independently verified invoice. The uncached estimate is counterfactual.
