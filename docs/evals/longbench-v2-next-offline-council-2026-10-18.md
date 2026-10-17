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

## Next action and limits

Build a metadata-only, strict-whitelist streaming audit for the 18 candidate-union IDs. It should hash each source and report per-task arm receipt counts, route/model, request identity, token/cache/cost metadata, whether each comparison is concurrent and paired, and missing counterfactuals. Use synthetic sentinel tests to prove excluded fields are not surfaced or retained. Do not read correctness or answer text. A successful artifact may support coverage and cache-sensitive cost bounds only; it cannot support an accuracy claim, savings forecast, or generalization claim. A future paid comparison still requires fresh route/pricing/usage/in-flight checks and explicit budget authorization covering the complete run reserve.

## Consultation and process notes

Council packet: `.runs/longbench-next-offline-council-20261018.txt`. The Advisor caller returned both the Gemini and Sol reviews in one successful council invocation.

Claude Code read-only review was attempted with a four-turn bound and returned `Error: Reached max turns (4)`; it yielded no usable review and was not retried. An exploratory schema probe in the parent task deserialized a raw result object while checking top-level keys; no answer or correctness values were inspected or used. Subsequent audit work is constrained to a streaming field allowlist.
