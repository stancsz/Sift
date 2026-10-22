# LongMemEval-V2 public local reproduction — prospective protocol

**2026-10-21 · Proposed specification; not activated or permission to access data or dispatch.**

No executable run manifest is frozen. The missing numeric inputs, rights
decisions and implementation work below remain activation dependencies.

Question: with the same public histories, question, reader and scoring rules,
what changes when Sift selects the history supplied to the reader? Report
quality alongside input reduction, our token-rate cost and elapsed time. This
is exposed public development evidence. It provides neither a held-out result
nor an official leaderboard-compatible submission: the existing source screen
records a Qwen3.5-9B reader/GPT-5.2 judge requirement for that route, whereas
this proposal targets MiniMax M3. No data or model result accompanies this file.

## 1. Freeze the run record before use

Create one versioned, hash-addressed manifest, independently reviewed before
activation. A field marked unresolved below is a blocker for its phase, not a
default to infer from another experiment.

| Freeze | Required contents |
| --- | --- |
| Implementation | Sift Git commit; adapter, Full renderer, driver, analysis and scoring source hashes; upstream commit `2cc8c540bdb87fe6761629b585e727e1c4704520`; complete runtime/dependency versions. |
| Data before access | Official dataset repository, immutable dataset revision, exact file/archive allowlist and published checksums where available; intended public cohort; rights disposition for access, processing and any external model transmission of embedded screenshots. Revision, files and screenshot rights are unresolved. |
| Selection before prompts/tuning | A sealed ordered question-ID list and its hash, question-to-haystack mapping, trajectory insertion order, normalized-record/image hashes, exclusions with fixed reasons, and all selection seeds. Verify downloaded bytes against the pinned revision and inventory before preparing prompts. Do not publish screenshot bytes or raw prompts without the corresponding rights. |
| Experiment | Numeric Sift target and counting basis; input/context/output limits and timeouts; repeat count; reader and judge configuration; request schedule; scoring and analysis settings; independently approved numeric spend ceiling and reservation rules. These numeric choices are not supplied by this document. |

Proposed cohort is every question supplied by the chosen public question and
haystack files. Preserve the published haystack and within-trajectory order;
do not select histories by relevance or answers. If resources require a subset,
freeze its numeric size and an ID-only seeded ordering rule **before** reading
question contents for selection or tuning, amend the cohort claim, and retain
the complete candidate-ID inventory. No result-driven replacement of cases.
Dataset/import validation may establish unsupported cases, but cannot erase
them from the selected population or its coverage report.

## 2. Define the two arms and the common reader

**Full:** normalize the pinned trajectories, then render every state using the
same goal/ID/state/URL/action/notes/accessibility-text representation used as
Sift's input. Join all state text into one context text item and append every
corresponding screenshot in source order. Apply no selection or summarization.
The [reference renderer](../../benchmarks/longmemeval_v2_full_context.py) now has
independently accepted generated fixtures: all-state retention/order, atomic
validation and the pinned upstream `build_messages` helper. That helper check
stubs unused registry/CLI/scoring imports; it does not establish full harness
integration or token fit. See the [scoped result](../results/longmemeval-v2-full-context-2026-10-21.json).
Upstream `no_retrieval` returns empty context and is not Full.

**Sift:** use the same normalized state stream and insertion order, append the
active query for compaction, then render selected/summarized text and the
images mapped to its selected source states using the adapter contract. The
question and its image are added once by the common harness in both arms.
No gold answer, scorer output or other arm's response enters retrieval.
Sift ranks text rather than image pixels; image-only evidence loss is part of
the intervention, not grounds to silently remove difficult questions.

Use the pinned upstream prompt template, normalization, image handling and
answer extraction for both arms. Same image bytes, preprocessing, question,
system prompt, reader model (`minimax/minimax-m3`), exact MiniMax-only routing,
sampling/reasoning configuration, maximum output, timeout and cache policy.
Freeze supported settings after route review; no arm-specific fallback, answer
repair or output allowance. Use sequential execution and one reader request
at a time; parallel and memory save/load modes are outside this proposal.
Build separate memory instances; reuse shared-haystack indexing only as the
pinned harness permits, with equal lifecycle boundaries and recorded build cost.

Preflight both rendered arms without inference. Full must fit the chosen
reader's complete input allowance, including instructions, question and images,
with output headroom. Record the pinned Qwen processor's original/final context
counts, image counts and exact request hash; require no downstream prefix
truncation in either arm. A Full input that cannot fit is `full_not_fit`, not a
truncated Full baseline. Sift may reduce history as specified, but missing
required images, malformed input or unsupported bounds are explicit failures.
The current adapter's byte estimate is unsuitable as a measured token budget:
replace it with a frozen, independently reviewed counting contract before use.
If budgeting uses the pinned Qwen processor, label it a reference count, not
MiniMax billing tokens. Returned provider usage supplies actual token reporting.

## 3. Pair, repeat and score without post-selection

Freeze the same positive integer repeat count for each question and arm before
dispatch. Each repeat is a planned fresh measurement, never a retry of a failed
attempt. Use a recorded seed to shuffle question order per repeat and a seeded
balanced Full-first/Sift-first assignment across pairs; publish the resulting
schedule rather than relying on implicit harness order. Keep each pair adjacent
in time. Interleaving limits timing/order effects; it does not eliminate caching.
Log cache metadata when returned and disclose warm/cold order rather than
claiming cache-independent billed savings.

Use each selected question's original `eval_function` and gold answer with the
pinned answer extractor and scorer. Do not replace required LLM judging with
exact match or call deterministic-only coverage the whole benchmark. Freeze
judge model/version, route, prompt, sampling, output limits and parser before
responses; blind arm labels and randomize scoring order. A different judge is
an explicitly named local variant, not official score comparability. Real LLM
judge behavior and its transport/cost limits remain unverified: the reader
wrapper does not guard the scorer's separate SDK client or its default retries.

For every scheduled reader/judge operation, retain its unique claim, status,
timings, response identity/hash, token usage, parsing/scoring outcome and reason
for failure, without exposing unauthorized content. Never retry transport,
HTTP, malformed response, usage, cap or judge failures automatically. On a
dispatched failure, stop new trial dispatches; retain completed evidence and
unstarted schedule rows. A later approved continuation may run only proven
unstarted claims under the same manifest, without replacing failed/unknown ones.

Report selected, preflight-supported, attempted, valid-response, scored and
complete-pair counts by question category and repeat; show every exclusion and
failure separately. Paired accuracy differences use the intersection of scored
arms, averaged within question across matched repeats, with question-cluster
95% uncertainty intervals and frozen resampling settings. Label this estimate
conditional on completed pairs. Also report verified-correct/planned counts as
operational yield, not accuracy on missing outputs, plus worst/best-case quality
bounds for unresolved scores. Missing scores are not silently dropped or treated
as evidence of a wrong answer. No parity/noninferiority claim without a margin
accepted before results; no accepted margin or quality result exists here.

## 4. Report quality, tokens, money and time together

Publish raw counts and paired deltas on the same coverage set, with category
breakdowns and repeat variability. Include answer accuracy/abstention outcomes,
original/retained text and image counts, truncation/failure counts, and provider
prompt/completion tokens. Keep reference processor counts and Sift's internal
counting basis separate from returned usage; report reasoning/cache details
when supplied rather than inventing missing fields.

Our primary money estimate is:

`prompt_tokens × frozen_input_USD_per_million / 1,000,000 + completion_tokens × frozen_output_USD_per_million / 1,000,000`.

Use Decimal arithmetic and a dated, reviewed rate snapshot for each reader or
judge route. The helper's existing defaults are a dated snapshot, not a current
rate promise. Sum own estimates only for operations with valid usage; disclose
unknown usage and outstanding exposure separately. Report reader, judge and
any authorized acceptance-probe costs separately, including failures with known
usage. Preserve optional OpenRouter `usage.cost` and
`usage.cost_details.upstream_inference_cost` as distinct reported amounts with
their own coverage. Missing/null means unknown; zero is not missing. Never add
those two reported fields together or substitute either for our calculation.
No account, balance, invoice or receipt reconciliation is required.

Use monotonic elapsed time for normalization/indexing, Sift query/compaction,
processor/prompt building, reader request, judge/scoring and end-to-end pair
duration. Show medians/tails, failure/timeout elapsed times, sample counts and
shared-index amortization explicitly; reader HTTP duration is not server-only
inference latency. Record machine/runtime and caching conditions. Report Sift
CPU time separately; hardware/electricity costs remain unknown unless measured.

## 5. Activation and trial-wide controls still required

The [optional transport evidence](../results/longmemeval-v2-minimax-transport-2026-10-21.json)
establishes generated loopback behavior only. Per-request caps and a stopped
client do not prevent another process or new client from dispatching. Before a
run, implement and independently verify one persistent trial claim store and
single-dispatcher lock across readers, judges, probes, restarts and clients.
Claim `(trial, question, repeat, arm, operation)` durably before wire activity;
persist started/valid/failed/unknown states and reject duplicate started claims.
Exercise crash/restart, duplicate entry and stop behavior without inference.

Reserve an operation's conservative own-rate upper bound before dispatch using
validated prompt/image bounds plus output/reasoning caps. All completed own
estimates, outstanding/unknown reservations and the next reservation must fit
the separately authorized numeric ceiling. Stop if no trustworthy bound exists,
if limits/rates change or if the ceiling would be exceeded. Unknown outcomes
retain exposure; reservations are not invented spent money. Do not release one
solely because a new client starts or a receipt is absent. This accounting uses
our calculation and needs no account-balance verification.

Activation therefore needs: a rights decision and immutable dataset inventory;
reviewed Full renderer/counting contract and no-truncation preflight; a complete
numeric manifest/schedule; independently verified trial-wide claims/reservations
including the separate judge path; and separate LongMemEval spend authority.
Then any minimal real endpoint acceptance probe must itself be explicitly
authorized, capped and included in that schedule/budget before a broader run.
Fresh route capabilities, rates and returned-usage handling need confirmation
there; loopback success is not endpoint acceptance. The existing up-to-$100
authorization belongs to the fresh LongBench run and does not cover this trial.
Independent protocol/implementation acceptance precedes activation. This file
does not grant data access, screenshot rights, spend or submission permission.

## Source and local evidence pins

- [Upstream harness](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/evaluation/harness.py): SHA-256 `93fe5855a74ad46d7e8b489cebac24de38a9b30ba7ec1de2dd8708bd4aeebdb6`; Git blob `6a7182440a2cdd3ace6286dd966f7953fc383e8e`.
- Same-commit [normalizer](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/memory_modules/trajectory_store.py), [empty no-retrieval backend](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/memory_modules/no_retrieval.py), and [scorers](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/evaluation/qa_eval_metrics.py). The generated main probe pins the 17-file source closure; freeze all hashes in the run manifest.
- [Qwen processor metadata](https://huggingface.co/Qwen/Qwen3.5-9B/tree/c202236235762e1c871ad0ccb60c8ee5ba337b9a), revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`; eight metadata files pinned by the existing smoke. This is not a MiniMax tokenizer or model-weight snapshot.
- [Official dataset landing page](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2): discovery link only, not the missing immutable data pin or screenshot-rights disposition. The [adapter/evidence record](longmemeval-v2-sift-adapter-2026-10-20.md) records the published license screen, generated rehearsal and remaining gaps.

No data, screenshots, private reports, credentials, provider calls or new
dependencies were accessed to write this prospective protocol.
