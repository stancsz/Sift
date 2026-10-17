# MiniMax relation-matrix v3 follow-up: six-task paired exploratory gate

This result covers six relation-closure-supported tasks, three repeats, and two Sift arms (36 calls). The matrix was developed on these same public training prompts, so this candidate-enriched diagnostic is not a LongBench v2 aggregate, holdout, or generalization result. Unchanged default Sift and the option-aligned complete-entity matrix treatment are paired in the same interleaved run. Historical Full/Sift are non-concurrent references and may be affected by provider/model drift.

- Analysis integrity: **VALIDATED**. Stage-1 expansion gate: **PASS**.
- Gate checks: PASS — all 36 rows receipt usage route target valid; PASS — no relation matrix candidate fallback occurred; PASS — no route usage cost target anomalies; PASS — no invalid answers; PASS — at least one candidate only majority vs concurrent default; PASS — strictly more exact choice correct than default.
- Exact-choice correct: matrix candidate **16/18**, default Sift **13/18**; invalids: matrix candidate **0**, default **0**.
- Task majorities: matrix candidate **6/6**, default Sift **4/6**.
- Concurrent task-majority comparison: **2 candidate-only wins**, **0 default-only wins**, 4 ties.
- Candidate selector: 18 complete-entity matrix selections; 0 default-Sift fallbacks across 18 candidate attempts and 36 total calls.
- Local prompt tokens: relation 65,652; concurrent default Sift 583,752; historical Sift 583,470; historical Full 2,410,833.
- Upstream reported cost: relation $0.009165; default Sift $0.097145.
- Median end-to-end: relation 1180.4 ms; default Sift 2071.2 ms.

## Provider usage and cache accounting

The uncached estimate is a counterfactual at the saved MiniMax route rates; it is not observed billing. Observed cache-inclusive cost comes from the upstream receipt.

| Arm | Provider prompt tokens | Cached tokens | Cached fraction | Observed upstream cost | Reconstructed uncached cost (counterfactual) |
|---|---:|---:|---:|---:|---:|
| Option-aligned complete-entity matrix | 65,652 | 44,374 | 67.6% | $0.009165 | $0.019814 |
| Concurrent default Sift | 583,752 | 325,516 | 55.8% | $0.097145 | $0.175268 |
| Historical Full | 2,410,833 | 2,200,891 | 91.3% | $0.195058 | $0.723271 |
| Historical Sift | 583,470 | 519,064 | 89.0% | $0.050508 | $0.175083 |

Counterfactual rate basis per million tokens: uncached input $0.300000, output $1.200000, cache read $0.060000; cache write rate unavailable.

## Per-task outcomes

| Case ID | Relation | Default Sift | Historical Full | Historical Sift | Relation vs default |
|---|---:|---:|---:|---:|---|
| `672494e5bb02136c067d7697` | 2/3 (majority) | 3/3 (majority) | 3/3 (majority) | 2/3 (majority) | tie |
| `67249705bb02136c067d76d1` | 3/3 (majority) | 1/3 (no majority) | 0/3 (no majority) | 0/3 (no majority) | candidate-only win |
| `6724c1d4bb02136c067d77ec` | 2/3 (majority) | 3/3 (majority) | 2/3 (majority) | 0/3 (no majority) | tie |
| `67285e1dbb02136c067d901b` | 3/3 (majority) | 1/3 (no majority) | 3/3 (majority) | 3/3 (majority) | candidate-only win |
| `67286036bb02136c067d9092` | 3/3 (majority) | 3/3 (majority) | 0/3 (no majority) | 1/3 (no majority) | tie |
| `6724c4aabb02136c067d78a6` | 3/3 (majority) | 2/3 (majority) | 0/3 (no majority) | 0/3 (no majority) | tie |

## Historical reference comparison

| Paired arm vs historical reference | Wins | Losses | Ties |
|---|---:|---:|---:|
| Relation Vs Historical Full | 3 | 0 | 3 |
| Relation Vs Historical Sift | 4 | 0 | 2 |
| Default Vs Historical Full | 2 | 1 | 3 |
| Default Vs Historical Sift | 3 | 1 | 2 |

The cases were selected because the offline relation-closure parser supported them. This is a targeted debugging/evidence-retention screen, not a representative benchmark sample. The concurrent arm comparison is paired by task/repeat with the same seed; historical references remain non-concurrent and provider-drift-limited.
