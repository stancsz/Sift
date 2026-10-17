# LongBench v2 readiness and evidence report

**Date:** 2026-10-17

**Purpose:** Consolidate the current MiniMax LongBench v2 evidence and set the next gate. This is a readiness report, not a new benchmark run.

## Decision

Keep experimental Sift selectors default-off and pause candidate experiments and paid dispatch. The existing 100-task model comparison is valid as a development result, but the available candidate coverage is too small, too exposed, and not backed by an evaluated dispatcher to justify a 100-task active-candidate study. No result here establishes quality parity, noninferiority, or a universal cost or speed saving.

The next review should begin only when there is a candidate with answer-blind evidence-preservation checks and a credible, fresh evaluation population, plus explicit budget authorization for the entire preregistered MiniMax run. Do not expand the quality claim by changing the original scoring rule after seeing results.

## MiniMax model result and scoring audit

The completed evaluation used OpenRouter `minimax/minimax-m3` on 100 public LongBench v2 training tasks with three repeats per task (600 responses). The frozen primary parser accepts only a complete `A`, `B`, `C`, or `D` response. It gives Full context **38/100 task majorities** and default Sift **31/100** (−7 percentage points; task-cluster 95% interval −15 to +1; McNemar p=.1435). This result does not establish a statistically significant quality loss, and it does not establish parity. It remains development evidence on a public training sample, not a held-out or full-suite evaluation.

An independent scoring audit found no arithmetic, pairing, or aggregation defect. A post hoc strict-format sensitivity that additionally accepts only a full-string parenthesized choice such as `(A)` changes the result to **38/100 vs 32/100** task majorities (119/300 vs 106/300 correct responses). Keep this as a secondary sensitivity; do not replace the frozen 38/31 primary score. Four Full-context outputs ended at the 16-token completion limit without a final choice, compared with zero for Sift. Those remain failures under the preregistered scoring protocol.

The audit also supports a future prospective format/parser check: freeze one answer format and parser before dispatch, then apply it identically to all arms. Do not repair or re-score this completed run under a new primary rule.

**Evidence:** [`longbench-v2-minimax-m3-100-analysis-2026-10-16.md`](longbench-v2-minimax-m3-100-analysis-2026-10-16.md), its machine-readable companion JSON, the [format-sensitivity audit JSON](longbench-v2-minimax-m3-100-format-sensitivity-2026-10-16.json), and [compressed raw result](../results/longbench-v2-minimax-m3-100-2026-10-16.json.gz). Its decompressed SHA-256 is `09d80674f03cb432e7cd8c9917f327f9dfd9675446d912cbd3d5f9e1dadb3d62`. Reproduce the narrow secondary analysis with `python benchmarks/audit_longbench_v2_format_sensitivity.py`. The audit found nine single-parenthesized answers (six Full, three Sift); accepting only this strict form yields the sensitivity above. Four Full outputs have `finish_reason=length` at the frozen output cap.

## Candidate coverage and exposure

The answer-blind census comparison covers the same pinned 503-task LongBench v2 dataset, MiniMax tokenizer/template, 32,640-token target, and current core hash `5a1d64474eea5d5ca6d599ab893411d40922dd7d12cc47e0ae33b9a097c86f1a`.

| Selector census | Eligible rows | Domain coverage | Exposure and interpretation |
|---|---:|---|---|
| Field pruning | 9/503 | 1 Long Structured Data Understanding; 8 Long-dialogue History Understanding | All nine were in the original 100-task sample; four also appeared in the field-pruning model pilot. |
| Query-directed labels | 9/503 | 9 Long Structured Data Understanding | Five were in the original 100-task sample. All nine were in the frozen 20-row mechanism screen (7 development, 2 mechanically screened as held-out); those two are not untouched quality-confirmation cases. |
| Mechanical union | 18/503 upper bound | 10 Long Structured Data Understanding; 8 Long-dialogue History Understanding | Zero overlap between selector sets; 14/18 were in the original 100. The remaining four were still processed in the frozen mechanism screen. The selectors are mutually exclusive; no combined dispatcher or quality result exists. |

These are target-fit and structural-coverage counts only. They do not measure answer quality, noninferiority, or savings. The exact task IDs, per-census dispositions, pinned source hashes, and exposure memberships are recorded in [`longbench-v2-candidate-census-union-2026-10-18.json`](longbench-v2-candidate-census-union-2026-10-18.json) and its two input census reports.

## Other candidate evidence

- The complete-record-ranking screen evaluated 10 development rows only: 7 met the mechanical method, token-target, and growth gates; 3 failed closed. No held-out row was evaluated and no accuracy was measured. The screen is pinned to core hash `7e388eb135113e4b1e6ed54b63af4149a596267e9849020743a916c9feaf3316`, which differs from the current census/core hash above. Treat its result as historical development evidence; do not claim it validates the current core.
- A separate synthetic query-facet selector prototype improved hand-labeled evidence recall in two constructed cases, tied one, and lost the only required evidence in a facet-mislabeling counterexample. The facet labels were supplied as oracle inputs. Its timing was a synthetic selection-loop microbenchmark. It is not LongBench evidence and does not justify production integration.
- The synthetic 500K/1M-context preflights are a separate workstream; they do not establish LongBench model quality, OpenRouter ingestion, or 1M-token provider support.

## Budget gate and next acceptance criteria

The last conservative spend ledger recorded approximately **$18.70 of a $20 authorization**, about **$1.30 remaining**, a **$4 per-run guard**, and an estimated **$9.39 reserve** for a proposed 900-request run. These figures are historical, not current approval. Do not send paid requests until usage, route, price, and in-flight exposure are reconciled and the user authorizes enough budget for the complete conservative reserve under all applicable limits.

Before reconsidering candidate evaluation:

1. Freeze one implementation and code hash; keep the candidate opt-in.
2. Demonstrate answer-blind evidence retention on a development set with independently reviewable source links and fail-closed behavior for ambiguous or unsupported inputs.
3. Freeze and pass a genuinely untouched acceptance split before applying the selector to the full 503-task census. Report candidate-active, fallback, under-target, route-ineligible, and failed-closed counts separately.
4. Require enough fresh, eligible tasks for the intended claim. A 100-task policy evaluation is not a 100-task active-candidate evaluation unless the candidate is actually applied to all 100.
5. Preregister a concurrent matched Full/default/candidate comparison, strict scoring, task/repeat schedule, cost accounting, timing, and stop rules. Obtain new spend authorization before dispatch.
6. Update README or production claims only from completed, independently reviewed results; keep sample size, selector coverage, cache accounting, and timing scope adjacent to each claim.
