# LongBench next offline step: Advisor council

Date: 2026-10-18

## Decision

Pause candidate invention and build an answer-blind, provenance-aware paired-replay audit over existing LongBench traces before changing selector routing. No paid model request is authorized by this checkpoint.

## Evidence supplied

- All 503 public LongBench v2 rows were prompt/label-census-exposed; there are no untouched task IDs.
- The frozen 100-task development run recorded task-majority accuracy of Full 38/100 and default Sift 31/100 (−7 points; task-cluster 95% interval −15 to +1).
- A later six-task relation-matrix screen compared a candidate developed on those same six tasks with concurrent default Sift and showed 6/6 versus 4/6 task majorities. It is candidate-enriched development evidence, not representative selector validation.
- The completed 100-task hybrid run used the matrix on six selected tasks and default Sift on the remaining 94. Comparisons with historical runs are cross-run/cross-version; the hybrid’s observed pass-through cost was higher than historical Sift because cache share differed.
- Last recorded conservative task-scoped exposure was $18.69965639 of the earlier $20 authorization. Current route, prices, account usage and in-flight spend are not verified; the authorization is not renewed.

## Gemini 4 Argon — independent review

Gemini recommended pausing candidate invention and fixing measurement/selector design offline. It proposed an answer-blind prompt-only routing and cost-replay harness over existing traces, and cautioned that offline simulations cannot validate quality on unseen tasks without a fresh funded evaluation.

Usage: 3,069 prompt tokens, 161 completion tokens (3,230 total).

## GPT-6.1 Sol — own verdict and review of Gemini

Sol independently agreed on measurement first. Its verdict was to build a default-off, answer-blind paired-replay audit before changing routing. Replay only provenance-matched traces; report routing coverage, missing counterfactuals and cache-sensitive cost bounds. Stop if replay needs new calls, output-guided tuning, or incomparable traces. Sol emphasized that with every ID exposed, this can establish feasibility only, not unseen-task quality improvement.

Usage: 687 prompt tokens, 318 completion tokens (1,005 total).

## Independent trace-coverage review

A separate read-only Codex audit found:

- The current candidate union contains 18 IDs: 9 field-pruning and 9 query-directed, with no overlap.
- Fourteen IDs have Full/default-Sift receipts in the same historical 100-task run.
- Four IDs have concurrent Full/default/field-pruning triplets in the later four-task pilot.
- The remaining five field-pruning IDs have no field-pruning model arm; none of the nine query-directed IDs has a query-directed model arm.
- Four query-directed IDs have no receipts in the checked frozen artifacts.
- The 100-task hybrid is a separate run and does not supply missing Full/default candidate-arm counterfactuals.

These are receipt-availability findings, not quality results. Per-task cost replay needs provider usage/cost metadata from raw result samples, so the audit must stream a strict field allowlist and skip answer, choice, expected, correctness, response text, SSE, and error-body fields.

## Offline metadata replay completed

The strict-whitelist audit is implemented in [`benchmarks/audit_longbench_v2_candidate_trace_metadata.py`](../../benchmarks/audit_longbench_v2_candidate_trace_metadata.py), with its sanitized result at [`longbench-v2-candidate-trace-metadata-audit-2026-10-18.json`](longbench-v2-candidate-trace-metadata-audit-2026-10-18.json) and sentinel coverage in `tests/test_longbench_candidate_trace_metadata.py`. It hashes the two raw result sources and skips answer/choice/expected/correctness and response/SSE/error subtrees during parsing. It retains only receipt identity, provider/model/route, token/cache counts and three numeric upstream cost-detail fields.

The report confirms the coverage map: 14/18 IDs have historical Full/default-Sift matches, 4/18 have concurrent three-arm Full/default/field-pruning blocks (three repeats each), 10/18 have historical baseline pairs only, 4/18 have no receipts, and none has a query-directed candidate arm. The four concurrent pilot cases recorded 646,404 Full prompt tokens and $0.08973456 upstream pass-through; default Sift recorded 153,435 tokens and $0.02144034; field pruning recorded 22,224 tokens and $0.00281064. These are only 12 requests per arm over four candidate-enriched development tasks. Cached-prompt shares were 67.2%, 67.1%, and 73.8%, respectively. The observed cost reductions for field pruning were 96.9% versus Full and 86.9% versus default Sift in this pilot; they are not a general savings estimate. Quality in the same pilot was Full 8/12 exact and 3/4 task majorities, field pruning 6/12 and 2/4, default Sift 1/12 and 0/4. Do not market the cost percentages independently of this small-sample quality result and its selection limits.

All 120 retained receipts have `usage.is_byok=true`, OpenRouter `usage.cost=0`, and positive upstream inference cost details. The zero OpenRouter cost value is not zero upstream spend. `cache_write_tokens` summed to zero; cached prompt tokens were preserved explicitly.

Focused sentinel/type tests pass (6/6), the audit `--check` reproduces the saved JSON and source hashes, and an independent Codex reviewer accepted the parser, provenance, comparability labels, and interpretation. No network/API calls were made during this audit; its streaming parser did not decode or retain answer/output fields. A separate exploratory schema probe earlier in the parent task loaded a raw result object while checking top-level keys, but no answer or correctness values were inspected or used; this is disclosed below. The complete official dataset remains exposed; this report cannot validate quality on unseen tasks or fill missing candidate-arm responses. Another paid comparison still requires fresh route/pricing/usage/in-flight checks and explicit budget authorization covering its complete reserve.

## Next action and limits

Keep experimental selectors default-off and do not invent another selector based on these receipt counts. The existing field-pruning result has a small concurrent pilot; query-directed has no candidate-arm model receipts. The 503-row dataset itself has no separate official hidden holdout: the upstream repository instructs loading its one 503-row split as `train`, while the project page describes the 503 items as the benchmark test data. Therefore, no fresh confirmatory LongBench v2 tasks remain in this public release. Next work must either use a separately authorized external/fresh task set or be labeled as post-census development research; no unseen-task or broad quality claim follows from offline replay. Paid dispatch remains gated on fresh route and spend reconciliation plus explicit sufficient authorization.

## Consultation and process notes

Council packet: `.runs/longbench-next-offline-council-20261018.txt`. The Advisor caller returned both the Gemini and Sol reviews in one successful council invocation.

Official dataset references: [THUDM LongBench README](https://github.com/THUDM/LongBench#load-data) documents `load_dataset('THUDM/LongBench-v2', split='train')`; the [Hugging Face dataset card](https://huggingface.co/datasets/zai-org/LongBench-v2) lists one 503-row split and describes the benchmark as 503 multiple-choice questions.

Claude Code read-only review was attempted with a four-turn bound and returned `Error: Reached max turns (4)`; it yielded no usable review and was not retried. An exploratory schema probe in the parent task deserialized a raw result object while checking top-level keys; no answer or correctness values were inspected or used. Subsequent audit work is constrained to a streaming field allowlist.
