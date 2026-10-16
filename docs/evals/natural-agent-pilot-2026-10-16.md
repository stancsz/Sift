# Natural agent pilot

**Status: design in progress. One exposed synthetic task has an accepted
three-arm diagnostic; this is not the planned multi-task pilot.**

## Decision

Test whether frozen Sift preserves successful work in realistic long-context
agent tasks while reducing forwarded input. This pilot validates the task
harness and estimates task-level variance. Eight tasks cannot establish quality
parity, general superiority, or a top-one-percent claim.

## Evidence and freeze

The selector remains frozen at SHA256
`c37f84829cf75a38f410e4eebb219ebf99c27c89a5c0b62a0ca9b70c36265de7`.
The public LongBench diagnostics have not shown a quality advantage: the 23-task
structured screen scored Sift 15/48 and full context 20/48 above target; the
10-task extension scored 15/30 and 16/30. These are small, public, diagnostic
samples and do not prove equivalence or inferiority. The synthetic
relation-binding authoring attempt is rejected: every prompt was below Sift's
trigger and all gold pointers failed independent validation; no inference ran.

The next set must be authored independently from the selector implementation
and from exposed cases. Hash every case, gold test, protocol, and scorer before
the first model call. Validate exact model-token counts, expected failing
baselines, task-to-gold traceability, and post-run checks independently. Reject
the set before inference if any case fails those checks. Once exposed, retire
these cases from future unseen validation. Keep the core frozen throughout.

## Authoring and harness diagnostics

An isolated Claude Code case-author attempt on 2026-10-16 reached its 30-turn
limit without creating any fixture files. It reported $1.823873 cost, 759,988
input tokens, and 25,446 output tokens. This is a failed authoring attempt, not
evaluation evidence. Do not retry the same large assignment unchanged.

A temporary development probe prepended synthetic project-history text to the
public research-audit task. The single resulting README user message measured
22,602 exact Qwen tokens. The first Sift request received HTTP 413 with “active
task or latest tool cycle exceeds target.” The native task later exited
normally in 241.53 seconds and passed its visible and gold tests, but the
accepted artifact does not rescue the failed provider request or show that
Sift compacted. Claude Code reported mean TTFT of 6.783 seconds across seven
samples and 35,411 input, 67,185 cached-input, and 4,242 output tokens. The
gateway logs were not fully retained, so no decode-rate or compaction claim is
made from this attempt. API spend was $0; hardware cost was not measured.

This exposed-history probe was invalid for the multi-turn question: putting a
history larger than the active-work budget inside one user message triggers the
fail-closed path, by design. The next harness must let context grow across
separate task and tool-result turns, keeping each active turn below the target.
See the [README's request-size limit](../../README.md#the-problem).

## Pilot population and procedure

Use eight distinct, executable agent tasks spanning at least four domains.
Each task must begin with a realistic multi-turn history above the 24,576-token
Sift trigger and fit under the full-context input ceiling with the output
reserve. The current actionable request must require at least one older fact or
constraint. Acceptance must verify the delivered artifact, not just the
agent's explanation. Include a failing baseline, allowed-file list, normal
terminal evidence, and independently maintained post-run tests.

Compare full context, Sift at 24,576, and complete-unit recency at the same
budget. Randomize arm order and predeclare cache handling. Keep model, native
client, tools, output cap, retry policy, fixture, and run limits equal. Record
every failure and abnormal end. For each run capture exact rendered input and
output tokens, cache usage, client TTFT samples, backend decode tokens/second,
selector preprocessing time, wall time, accepted outcome, and provider usage.
Do not substitute task duration for decode speed or missing TTFT.

## Harness preflight, 2026-10-15

The current repository contains five public authored development fixtures,
not eight unseen pilot tasks: build planning, incident reconstruction,
payment reconciliation, research evidence auditing, and least-privilege IAM
auditing. Their baseline visible test suites fail as expected before the requested implementation: build
planning has 13 errors, incident reconstruction has two failures, payment
reconciliation has one error, and the research audit has two failures. These
fixtures may validate runner mechanics, but must not count as held-out pilot
tasks.

Using the running local Qwen tokenizer endpoint, the non-test source files in
each case were tokenized together with filename separators (no chat-template or
tool-call overhead):

| Public development case | Source tokens | Pilot implication |
|---|---:|---|
| Build planning | 756 | Below the Sift trigger |
| Incident reconstruction | 57,638 | Full concatenated source set exceeds the 32,768-token window; its four incident logs are 14,219–14,292 tokens each |
| Payment reconciliation | 2,200 | Below the Sift trigger |
| Research evidence audit | 5,251 | Below the Sift trigger |
| Least-privilege IAM audit | 21,281 | Below the trigger as a source corpus; tool and transcript overhead may cross it, but a rendered run must prove that |

These are source-corpus counts, not rendered request counts. They establish
that the existing cases cannot simply be used as the requested matched pilot:
three source corpora are below the Sift trigger, while the incident corpus
requires a controlled read sequence to keep full context within the model
window. A valid new case should produce more than 24,576 total prompt tokens across
multiple completed turns, keep every active task/tool cycle below the
compaction guard, and fit the full arm below 28,672 prompt tokens when the
output reserve is 4,096 tokens. Count the final rendered request with the same
Qwen tokenizer and record the actual prompt token count for each arm.

The native runner's standard frozen-manifest verifier initially rejected the
build-planner nested manifest and found no incident-reconstruction manifest.
Added `benchmarks/agent_gold/build_planner/native-manifest.json` and
`benchmarks/agent_gold/incident_reconstruction/manifest.json`; the standard
verifier now passes for all four public fixtures. This repairs runner
integrity checks, not the fixtures' held-out status or their eligibility for
the planned quality pilot. No inference was started during this preflight.

LLMLingua-2 may be included only as a separately labeled text-only arm unless
it can preserve the native tool interaction and request semantics. Its
preprocessing and memory costs must be measured; it remains evaluation-only.
Use local Qwen for the pilot. No Astra calls are authorized or needed for the
acceptance run; calculate Astra price examples separately from observed token
counts and label them as estimates until real Astra usage is measured.

## Analysis and claim limits

The task is the unit of analysis. Report paired acceptance outcomes, all
failures, per-task exact input tokens, and matched timing/cache conditions.
Eight tasks are a harness and variance pilot only. Do not report quality parity
or sharper answers from this sample. Use its paired discordance and task
variance to set a separate powered, independently frozen noninferiority study.
Claim “sharper” only after a preregistered blinded quality-superiority test;
claim cheaper only from measured cost per accepted task.

## Advisor council, 2026-10-16

Gemini 3.8 Flash and GPT-6.1 Sol recommended switching from another synthetic
relation-set repair to a gated natural-agent harness. Sol recommended eight
unseen tasks with valid histories above 24,576 tokens and executable acceptance
checks, followed by independent validation before any inference. The council
classified the pilot as harness validation, not noninferiority, and advised
stopping before inference on any validation failure. It also cautioned that
the existing LongBench results show no demonstrated advantage but cannot
establish equivalence or inferiority. Reported usage: Gemini 4,294 prompt +
1,321 completion tokens; Sol 680 prompt + 271 completion tokens. The advice
changed the next experiment from repairing synthetic relation data to
independent natural-task authoring and acceptance checks.

## Follow-up council: usable context, not compression ratio

After the native research-task pilot and LongBench extension, a second council
review recommended testing whether selected historical evidence remains usable
as a coherent context. Gemini and GPT-6.1 Sol agreed that retaining literal
answer strings is not enough. Sol cautioned that the 5/6 full versus 3/6 Sift
probe does **not** identify fragmentation as the cause. The current selector
already quotes exact source slices, keeps nearby pieces, and emits selected
excerpts chronologically; a proposed change therefore needs to test a specific
coherence mechanism instead of assuming that span order is wrong.

The next algorithm experiment should compare frozen full context, current Sift,
and one bounded extractive candidate that preserves the tested dependency
context around a selected fact. Keep query, case, and gold checks blinded from
the candidate author. Do not tune against the exposed LongBench rows or the
existing six-case probe. Preserve active-task and latest-cycle protection,
cache-boundary behavior, and the same hard token target. First run the existing
eight-task pilot to validate the harness and estimate paired outcome variance;
then freeze new cases and a powered quality study before claiming improvement.

The paired-harm planning script shows why the eight-task pilot cannot establish
noninferiority. With a 2 percentage-point margin and 80% target power, its exact
binomial sensitivity calculation needs 386 tasks if the assumed full-only harm
rate is 0.5%, 969 if it is 1%, and 4,318 if it is 1.5%. These are planning
scenarios, not universal sample-size requirements; the actual design should
use observed paired discordances and a predeclared paired risk-difference
interval.

For promotion, require the candidate to improve accepted-task quality over
current Sift on held-out cases, exclude more than 2 percentage points of harm
versus full context with the predeclared interval, preserve all protected
context invariants, and reduce **measured cost per accepted task** by at least
10% versus full context. A failed or unaccepted run contributes cost but not an
accepted task. Astra price tables remain arithmetic examples until equivalent
provider usage and acceptance are measured; no paid Astra inference was part
of this review.

The council advice changed the follow-up from optimizing a token-retention
score to testing usability of retained evidence. Its diagnosis remains a
hypothesis, not a confirmed defect. Reported usage: Gemini 4,307 prompt +
1,418 completion tokens; Sol 635 prompt + 319 completion tokens.

## Least-privilege audit fixture preflight, 2026-10-16

This fifth case is public synthetic development data, not a held-out task. Its
21,281 exact Qwen-token source count covers the README, starter, request, policy
notes, and four audit logs; it excludes tests, generated reports, tool-call
overhead, and the chat template. The source count alone does not meet Sift's
24,576-token trigger. A real native run must show that the multi-turn tool
transcript crosses the trigger while each active task/tool cycle remains
within the guard and the full-context arm stays within its reserved budget.

The visible suite discovers nine tests and fails on the starter (four failures
and four errors). An isolated case copy with the independent acceptance module
discovers 21 tests and fails as expected (12 failures and six errors). The
frozen input and acceptance manifest verifies. The acceptance module locates
source files relative to the isolated test workspace, matching the native
runner's post-run layout. These are fixture and runner checks only; no
performance inference ran.

Claude Code's separate fixture-authoring attempt cost $1.8376416 across an
initial partial result and a permission-blocked follow-up. The returned draft
needed local fixture, test-discovery, and corpus-size repairs before passing
these preflight checks. This is authoring overhead, not Sift performance or
provider inference cost.

## Single-arm Sift stress run, 2026-10-16

Ran the public IAM case through Claude Code CLI 2.1.251 backed by local
`qwen3.8-27b` IQ3_S (32,768 context), with Sift targeted at 24,576 estimated
input tokens and a 4,096 output limit. Across 53 model requests, the hook
compacted 45. Summed estimated request input was 3,209,246 tokens and selected
input was 855,074 (73.4% fewer); this sum includes repeated conversation
prefixes. The largest request measured 134,913 tokens and was reduced to no
more than 24,576. Mean selector thread CPU time was 154 ms per request.

This did **not** produce an accepted task. The native run reached its 1,200
second deadline and ended with exit 124. The visible suite passed 8/9 tests;
the combined independent check passed 14/21. The report omitted all three
expected overgrants, including the unused PII bucket, and failed six
gold-specific checks including citation support. Claude Code reported 52 TTFT
samples with a 6.14 second mean and 3.20 second median. The retained Qwen
engine log has rotation gaps, so its partial 42.43 token/second decode average
is not used as a paired performance result. Local provider API spend was $0;
hardware cost was not measured. Cost per accepted task is unavailable.

This was a stress diagnostic, not a matched comparison. The uncapped history
grew past the 32K model's capacity, so no full-context arm could process the
same requests. The run also cannot show that Sift caused the task failure:
there is no control arm, and the client timed out after an incomplete test loop.
It does show that the gateway repeatedly served long histories through the
32K backend, while answer quality still requires independent acceptance.

The run exposed a harness defect: baseline tests generated the required report
inside the client workspace, and the result checker treated every new file as
unauthorized. The runner now executes baseline tests in a separate copy and
accepts only predeclared `--allowed-output` paths that were absent before the
run. The gold test also resolves fixture data relative to the isolated
acceptance workspace. A new regression test covers these boundaries. Reruns
must use the corrected harness; this timed-out result remains unchanged as
historical evidence.

## Follow-up advisor council, 2026-10-16

Gemini 3.8 Flash and GPT-6.1 Sol advised authoring a bounded multi-turn task
before replaying the over-capacity stress run. The next task must naturally
cross Sift's 24,576-token trigger while every full-context request stays at or
below 28,672 tokens, including tool overhead. Then randomize matched full,
Sift, and recency runs with the core frozen and the same settings. Check
omissions, overgrants, citations, and retained evidence against hidden
expectations. Stop attribution if Sift never compacts or if full context cannot
fit; diagnose the task/client setup before expanding or blaming Sift.

Decision changed: author the bounded matched case next, not a replay of the
134K stress history. Reported usage: Gemini 3,258 prompt + 108 completion
tokens; Sol 702 prompt + 259 completion tokens. This is advice for experiment
design, not validation evidence.

## Least-privilege rollup three-arm diagnostic, 2026-10-16

After fixing the output cap and full-arm input reserve, the same public
synthetic least-privilege task completed successfully in all three randomized
arms. The frozen manifest SHA256 is
`2c82403fba61c4ef6c5c89b04d036cc6e691aacee64a26fa9a41b55b7b71fb96`;
order was recency, Sift, full. Each arm used Claude Code CLI 2.1.251, local
`qwen3.8-27b` IQ3_S, a 3,072-token output cap, and the same visible and hidden
acceptance tests. Sift and recency targeted 24,576 estimated tokens. The full
profile reserved 3,072 output tokens inside the 32,768-token backend window.

| Arm | Accepted | Task wall time | Mean client TTFT (n) | Median TTFT | Mean Qwen decode rate (requests) | Client-reported input + cached input | Astra price sensitivity* |
|---|---:|---:|---:|---:|---:|---:|---:|
| Recency | yes | 331.3 s | 4,893 ms (18) | 740 ms | 43.99 tok/s (19) | 347,368 | $1.7738 |
| Sift | yes | 214.1 s | 2,340 ms (18) | 775 ms | 44.02 tok/s (19) | 338,562 | $1.0593 |
| Full | yes | 236.8 s | 2,007 ms (17) | 454 ms | 43.68 tok/s (18) | 349,614 | $0.9991 |

Decode rate is the arithmetic mean of Qwen's completed-request `eval time`
rates in the engine log. The Sift arm's weighted aggregate was 43.13 tok/s;
the full arm's was 42.65 tok/s; recency was 42.95 tok/s. These are local GPU
measurements. TTFT is client-reported and includes runtime/cache variation.
Different request counts and pronounced mean/median TTFT gaps make this
single sequential replay unsuitable for a latency ranking. Task wall time is
not model decode speed.

All arms passed the same acceptance checks, so this run only shows that the
fixture's required outcome remained achievable with Sift. It does not show a
sharper answer, lower drift, quality parity, or a general success-rate benefit.
The case is public synthetic development data, was exposed by this run, and
counts as one task and one sample per arm. It is not held-out evidence. The
full run remains the cheapest in the price sensitivity, so this task does not
demonstrate Sift savings.

*Price sensitivity substitutes local client-reported token counts into
GPT-6 Astra's short-context rates ($10/M uncached input, $1/M cached input,
$50/M output), with no cache writes. Each individual request fit under the
272K long-context price threshold. The resulting amounts are illustrative
only: no Astra request or invoice was used, and provider tokenization, cache
behavior, and billable usage may differ. All three local runs had $0 provider
API spend; GPU and electricity costs were not measured. See the machine-readable
per-arm records in `docs/results/least-privilege-rollup-*.json`.

This comparison illustrates the answer-sharpness hypothesis but cannot test
it. To test “less drift,” future blinded cases should score required facts,
instruction adherence, unsupported claims, and task completion, while holding
cache conditions and output budget stable. Report omission and regression
rates alongside concision. A lower token count alone is not a quality metric.
