# Fresh MiniMax LongBench repeat — completed 2026-10-21

Fresh API requests on the **same exposed public 344-question cohort**, three
repeats per arm. This is a repeat measurement, not a new held-out cohort or an
agent-task benchmark. The original negative study remains published separately.

## Money: our token-rate calculation

| Known usage | Without Sift | With Sift | Total |
|---|---:|---:|---:|
| Prompt tokens | 65,696,425 | 26,565,388 | 92,261,813 |
| Completion tokens | 3,078 | 2,661 | 5,739 |
| Our uncached calculation | **$19.7126211** | **$7.9728096** | **$27.6854307** |
| Optional provider-reported amount | $8.6517051 | $3.6974460 | $12.3491511 |
| Attempts with recorded usage | 1,029 | 1,030 | 2,059 |

Own calculation: `prompt_tokens × $0.30/M + completion_tokens × $1.20/M`,
using the frozen MiniMax route rates. Rounded total: **$27.69**. These are
uncached rate calculations from recorded tokens, not account or invoice totals.
Provider-reported amounts are separate, cache-sensitive fields.

Across recorded usage, Sift used **59.56% fewer prompt tokens** and had **59.55%
lower own calculated cost**. Arm coverage differs by one usage record; these
ratios do not quantify missing usage or establish equal quality. Five attempts
have unconfirmed outcomes/usage and were not retried. Their **$0.19543245**
reserve is separate from money spent. Including that reserve and the historical
**$2.0457216** reserve gives **$29.92658475** conservative coverage, within the
separately authorized **$100** cap. No balance or invoice reconciliation is used.

## Quality and coverage

All **2,064 scheduled attempts** were attempted: 23 in the stopped prefix and
2,041 in its continuation. There are 2,059 confirmed responses with usage,
five unconfirmed attempts and **339 complete paired questions** with all six
responses observed. Five questions are excluded from this complete-pair view.

| Task-majority exact choice | Full | Sift | Sift − Full |
|---|---:|---:|---:|
| Complete paired questions | 142/339 (41.89%) | 136/339 (40.12%) | **−1.77 pp** |
| Scheduled questions; unknowns counted incorrect | 144/344 (41.86%) | 137/344 (39.83%) | −2.03 pp |

For complete pairs, the task-cluster bootstrap 95% interval is **−6.49 to
+2.95 pp**. The scheduled-denominator interval is −6.69 to +2.62 pp. Both use
20,000 percentile resamples of question clusters with seed 20261018. Including
zero does not establish parity or noninferiority; no accepted margin exists.

On complete pairs, response-level exact choices were Full 431/1,017 (42.38%)
and Sift 410/1,017 (40.31%). Across all confirmed responses, valid stopped choices
were Full 969/1,029 and Sift 987/1,030. The remaining 103 confirmed responses
were not valid stopped choices under the analyzer contract and count incorrect;
they are distinct from the five unconfirmed attempts.

The [earlier study](longbench-v2-minimax-344-aggregate-2026-10-20.json) reported
−5.25 pp on 343 complete questions (95% interval −10.20 to −0.29). Different
missing-response coverage and fresh responses prevent treating the smaller
point gap here as a demonstrated improvement. Both studies use exposed data;
neither proves blind generalization, agent-loop benefits or quality parity.

## Method, provenance and acceptance scope

- [Aggregate-only result](longbench-v2-minimax-fresh-344-aggregate-2026-10-21.json): counts, quality, own costs, reserves, input hashes and integrity limits.
- [Frozen fresh manifest](../evals/longbench-v2-minimax-fresh-344-manifest-2026-10-20.json) and [base schedule](../evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json).
- [Accounting/run record](../evals/longbench-v2-minimax-budget-preflight-2026-10-20.md) and [strict final analyzer](../../benchmarks/analyze_longbench_v2_minimax_fresh_344.py).

Root confirmed the detached process absent and terminal status
`completed_with_failures`, with no in-flight request, before running the strict
analyzer once. It accepted all scheduled attempts and emitted the aggregate.
Terminal state was observed at 2026-10-22T00:19:08Z (October 21 locally). No
failed request was retried, no claim was reset and no interim quality tuning
occurred.

The original 38 analyzer tests include the actual producer's final report
transition. It verifies the fixed prefix, manifest/order/request hashes,
coverage, route/model and token/rate/reserve arithmetic. Prefix streams are
reparsed internally. Continuation choices, transport flags and usage are
runner-recorded; raw continuation streams/usage receipts were not retained and
cannot be independently revalidated. Its final SHA-256 identifies the analyzed
snapshot, not a provider signature or precommitted response. The report does
not contain an execution-source hash. The public aggregate alone cannot
regenerate the task-level bootstrap. Review of aggregate arithmetic and
accepted analyzer evidence must retain these provenance limits.

Independent public-aggregate review recomputed own costs with Decimal arithmetic,
coverage, reported-cost/reserve sums, quality ratios/deltas and fixed source
references. It did not access private inputs, authenticate continuation raw
outputs or regenerate the bootstrap. Its retained receipt is
`tmp/qa-fresh344-final/aggregate-review.json`; no full-suite rerun is claimed.

### Frozen manifest checkout serialization

The base manifest's frozen input hash is for CRLF bytes (`eaddd0d3…c657c2`).
Its unchanged Git blob uses LF (`1277778a…59acb`). The exact-path rule in
[.gitattributes](../../.gitattributes) materializes the original CRLF form on Git
checkout; this preserves the input pin rather than changing the study.
A negative-control checkout without the rule reproduced the LF/hash mismatch.

The focused analyzer suite now has **40 passing checks**: the original 38 plus
two isolated real-Git checkout cases for `core.autocrlf=false` and `true`.
Independent targeted review passed the actual manifest-pin check and both
checkout cases (three checks, 37 deselected), reusing prior analyzer evidence.
These executions were on Windows; they do not claim actual Linux execution or
that LF archive exports are ready for the strict analyzer. The short Ubuntu CI
selects those same three cheap checks, while the broad suite stays local and
weekly/manual. No frozen manifest, private report or aggregate bytes changed.
