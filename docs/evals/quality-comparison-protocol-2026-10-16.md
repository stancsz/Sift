# Held-out quality and cost comparison protocol

**Status: preregistration for the next evaluation, not a completed benchmark.**
Do not use results from this plan to promote the current candidate until its
case set and scoring are independently fixed.

## Decision this evaluation answers

Does Sift preserve successful work while reducing provider cost or latency,
and does it improve answer quality enough to justify saying it makes answers
sharper? Token reduction by itself answers neither question.

## Freeze and case provenance

Freeze the tested Sift source, LiteLLM version, model, prompts, tools, output
limits, and arm implementations before scoring. The reproducible source freeze
for the next evaluation is Git commit
`ea99aaa377662c93024d010a3a7376bf61cf4d65`; its `src/sift/core.py` blob
SHA-256 is `88521ac93678bbc241149248e0b7162dfe3a79595b400559f98811be3b6fc9d5`.
An earlier preregistration hash (`c37f8482...`) does not resolve to any core
version in this repository's Git history. Run from the committed source
snapshot and exclude dirty working-tree changes. Any later code change starts
a new comparison.

An author who does not implement the selector must choose and freeze the test
cases, required evidence, task-specific acceptance checks, allowed writes, and
run limits. Use consented agent tasks or a public benchmark whose data license
permits the intended use. Save hashes before exposing cases or gold to the
selector author. Existing public synthetic fixtures, including the six
coverage-reserve cases, are development data and cannot fill this holdout.
Report domains and exclusions; do not imply that synthetic QA represents
real-world agent work.

## Arms and controls

Run each frozen case through these arms using the same downstream model,
generation settings, tools, client, output cap, retry policy, and input-token
ceiling:

1. Full original context when it fits. An overflow is a capacity failure.
2. Sift at the predeclared input target.
3. Complete-unit recency at the same target.
4. LLMLingua-2 at the same exact downstream model-token target.

For LLMLingua-2, preserve instructions, the original task, and exact active
tool work outside compression where possible. If the method cannot preserve
message roles, tool-call batches, and request semantics, label it a text-only
compression baseline, not an equivalent LiteLLM adapter. Measure its
preprocessing time, CPU, peak memory, dependencies, and any model/API charge.
It stays evaluation-only and must not become a Sift runtime dependency.

Use the downstream model's exact rendered-prompt tokenizer to check each
forwarded request. Record both that count and any selector-estimated count.
Measure cold and warm/cache-reuse conditions separately. Randomize arm order
within each repeat, keep cache conditions fixed within a block, and record
cache reads and writes when the provider exposes them. Include at least three
repeats per case/arm for the initial screen; do not treat repeats of one case
as independent tasks. Expand the case set or repeats if intervals remain too
wide to decide.

## Outcomes and scoring

The task is the unit of analysis. A run is accepted only when it ends normally,
respects write scope, passes visible checks, and passes independent gold
acceptance. Retain every failure, timeout, retry, and rejected artifact in the
denominator. Report per-domain and aggregate accepted-task rates.

For answer-quality scoring, hide the arm and model metadata from two independent
reviewers. Score relevance, required-fact coverage, factual support, unsupported
claims, and unnecessary detail against a fixed rubric. Resolve disagreements
under a documented rule and retain both initial ratings. Exact evidence
retention is a diagnostic outcome; it is not a substitute for answer or task
quality.

Before making a quality-parity claim, require the one-sided 95% confidence
bound for the paired acceptance-rate difference (compaction minus full) to be
greater than -2 percentage points. Estimate uncertainty by resampling whole
tasks, not individual turns or repeated runs. Also report the paired 2x2
acceptance table and a preselected exact unconditional paired-binary interval
as the primary small-sample check; a task bootstrap alone can be uninformative
when few tasks disagree. Before generation, freeze the task population, exact
interval method, one-sided confidence level, planned task count, and power
assumptions from an independent pilot or a prespecified range of paired
discordance rates. Paired binary noninferiority methods and power depend on
joint outcomes, and small-sample asymptotic methods may not control error rates
([Liu et al., 2002](https://doi.org/10.1002/sim.1012),
[Suissa and Shuster, 1991](https://pubmed.ncbi.nlm.nih.gov/11414572/)).

As a conservative planning floor, if Sift has zero task outcomes accepted by
full context but rejected by Sift, at least 149 independent tasks are needed
for the one-sided 95% exact upper bound on that harmful-discordance rate to
fall below 2%: `1 - 0.05^(1/n) < 0.02`. Any harmful discordance requires a
larger powered design. This bound ignores Sift-only wins, so it is conservative
for the paired acceptance-rate difference. It assumes independent tasks drawn
from the frozen target population; stratified evaluation must preserve and
report its planned domain weights. 149 is not a general sufficient sample
size. The first screen is inconclusive if it cannot meet the paired bound; do
not widen the margin after seeing results.

The [harm-only exact planner](../../benchmarks/paired_harm_power.py) gives a
planning sensitivity for nonzero failure rates. It tests the conservative
harmful-discordance probability (full accepts, Sift fails) against the 2%
margin and ignores Sift-only wins. At one-sided alpha 5% and 80% target power,
the reproducible results are:

| Assumed harmful-discordance rate | Independent tasks | Maximum harms in rejection region | Achieved power |
|---:|---:|---:|---:|
| 0.0% | 149 | 0 | 100.0% |
| 0.5% | 386 | 3 | 87.0% |
| 1.0% | 969 | 12 | 82.1% |
| 1.5% | 4,318 | 71 | 80.2% |

These are sensitivity scenarios, not an estimate of Sift's true failure rate
or a finalized sample size. The calculator treats each independent task as one
binary paired outcome; repeated runs need a frozen task-level aggregation rule
or a cluster-aware analysis and do not increase the number of independent
tasks.

Claim sharper answers only if blinded quality scores show a statistically
supported improvement over full context, with no increase in unsupported
claims or accepted-task failures.

Report time to first token, end-to-end task time, generated tokens per second,
selector/compressor CPU and wall time, peak memory, input/cache/output tokens,
request count, retries, and normal terminal outcomes. Present cold and warm
results separately. Do not claim a speed win from decode tokens per second
alone or from fewer estimated input tokens.

## External long-context answer-quality track

The six coverage-reserve cases are development data and cannot establish
general answer quality. Before making another selector change, run a separate
public long-context QA track on [LongBench v2](https://huggingface.co/datasets/zai-org/LongBench-v2).
Its dataset card identifies 503 multiple-choice tasks across six long-context
categories and reports an Apache-2.0 dataset license. This track measures
single-turn answer accuracy; it does not replace native agent acceptance.

Pin the dataset revision and data-file hashes, then freeze a deterministic,
category- and length-stratified sample before generation. Keep the question,
choices, and answer key in the evaluation harness, not the model prompt. Use
the same prompt wrapper and generation settings for full context, Sift,
complete-unit recency, and text-only LLMLingua-2. Count the actual rendered
prompt with the evaluated model's tokenizer. For the local Qwen screen, reserve
4,096 output tokens from its 32,768-token context, cap full input at 28,672
exact tokens, and set Sift's estimated target to 24,576. Compare accuracy only
on tasks where full context fits; report longer-task capacity separately.
Score the exact A/B/C/D answer, retain invalid or missing
answers as failures, randomize arm order, and publish per-category results
alongside paired task-level uncertainty. Do not claim statistical parity or
general quality improvement if the sample cannot resolve the preregistered
two-point margin. The dataset is public, so describe this as external
benchmark evidence, not a blind private holdout.

For a local Qwen screen, this provides no Astra bill. Keep the dated GPT-6
Astra example as price arithmetic until a separately authorized and measured
Astra run records model-token usage and actual accepted tasks.

### Initial public screen completed, 2026-10-16

The first frozen LongBench v2 Qwen screen is complete and recorded in the
[evaluation report](../evaluation.md#longbench-v2-structured-choice-rerun-2026-10-16)
and [machine-readable result](../results/longbench-v2-qwen-schema-2026-10-16.json).
It used 23 public cases, three repeats, and structured-choice scoring. This
initial sample was stratified by category and budget, not dataset length: all
selected rows are labeled `short`, and 202 longer rows were excluded by the
preparation prefilter. It is diagnostic, not blind, powered, or sufficient for
the two-point noninferiority gate. On the 16 above-target cases, Sift scored
15/48 repeated answers versus 20/48 for full context under official keys. The
seven below-target controls preserved the same Sift/full prompt-token counts
and answers. Do not interpret repeated answers as independent tasks.

A follow-up source audit supports the official key for case
`6713066fbb02136c067d3214`: its per-player logs identify `player_7` as the
highest round-four bidder. Reconstructed Sift excerpts place the `player_7`
identifier and bid value in separate excerpts, and preserve none of the 20
`round_records` objects whole. This is a relation-loss signal, but the three
repeats are still one task.

Case `6719bce5bb02136c067d4447` remains label-uncertain: per-player logged
receipts total 158 for `player_2`, who is not an option; among offered players,
`player_4` totals 156 and `player_7` totals 153, while the official key is
`player_7`. `round_records` provide response vectors without player IDs. Keep
the official score unchanged and report sensitivity separately: excluding
that row gives full 18/45 and Sift 15/45; excluding both audited rows gives
15/42 for each. See the [source audit](../results/longbench-v2-gold-audit-2026-10-16.json)
and its [reproduction script](../../benchmarks/audit_longbench_v2_rows.py).

An exploratory strict-majority aggregation over each case's three existing
repeats yields 5 tasks correct in both arms, 2 full-only, 0 Sift-only, and 9
neither. Excluding the uncertain row leaves 5 both and 1 full-only; excluding
both audited rows leaves 5 both and 9 neither. This post-hoc view is descriptive,
not an inferential test, and repeats do not increase the independent task count.

Keep the current core frozen. The next gate is the independently checked
[natural-agent pilot](natural-agent-pilot-2026-10-16.md), after the harness can
represent long history across separate prior turns and tool results. The
relation-binding case authoring attempt failed before inference because its
prompts missed the compaction trigger and its gold pointers did not validate;
that pilot remains unrun. Do not implement a format-specific fallback unless
independent evidence shows a general failure mechanism and the candidate passes
the blinded noninferiority and preservation gates.

## Cost accounting

Sum actual provider usage and charges across every request in each task,
including retries and auxiliary calls. Report spend per run and total spend per
accepted task; a failed task is not a saving. Keep selector CPU/hosting cost
separate unless measured and allocated to the same workload.

For a GPT-6 Astra illustration, use the dated standard API rate sheet and each
request's actual cache and context tier. At the rates checked 2026-10-16,
uncached input is $10/M and output is $50/M through 272K input tokens; prompts
above 272K use long-context rates for the full request ($20/M input, $75/M
output). Cached reads and cache writes have separate rates. The README's 1M vs
24,576-token table is price arithmetic only. Until actual Astra usage is
measured on accepted matched tasks, describe Astra savings as an example, not
a Sift result.

## Go/no-go and claims

- Stop on changed instruction roles, corrupted active work, an input-budget
  violation, unauthorized files, or a reproducible task-quality regression.
- Promote only when the acceptance noninferiority bound passes and the claimed
  cost or latency outcome is lower under paired conditions. Report all arms,
  failures, uncertainty, and preprocessing overhead.
- Say “sharper” only after the blinded quality-superiority test passes. Say
  “cheaper” only for measured cost per accepted task. Otherwise publish the
  result as inconclusive or as a bounded token-retention result.
- A successful comparison is one evidence unit; it cannot establish “top 1%”
  by itself. A percentile claim also needs a defined peer set, comparable
  benchmark results, and evidence of qualified use/adoption.

## Advisor review

On 2026-10-15, the Codex Advisor council (Gemini 3.8 Flash, then GPT-6.1 Sol)
recommended freezing further tuning and using a preregistered, independently
fixed task set with randomized repeated arms. Gemini highlighted the absence
of evidence for quality parity. Sol recommended matched LLMLingua-2, full,
recency, and Sift arms; independent task and answer-quality checks; actual
Astra cost per accepted task; and a 95% confidence bound excluding an
acceptance loss greater than two percentage points. The council advised that
“sharper” requires superior blinded scores. Total reported usage was 3,154
prompt + 219 completion tokens for Gemini and 767 prompt + 283 completion
tokens for Sol. `decision_changed: true`: this plan freezes the candidate and
makes task acceptance, not token retention, the promotion gate.

After the direct answer probe, a second council review considered whether the
repeated query-echo excerpts justified a selector change. Gemini 3.8 Flash and
GPT-6.1 Sol agreed to keep the source frozen: the six cases were public and
tuned, with one stochastic completion per arm, so the observed misses do not
establish that excerpt overlap caused them. Add overlap scoring to the blinded
set. If the pattern persists there, preregister an isolated deduplication
ablation against new unseen cases. Stop if it drops required evidence or
without blinded task-acceptance evidence. Usage: Gemini 3,115 prompt + 179
completion tokens; Sol 716 prompt + 154 completion tokens.

After the structured LongBench screen, the 2026-10-16 council advised keeping
the core frozen, auditing lost evidence and row integrity, then preregistering
an independent aggregation holdout with task-level power and a fixed
noninferiority margin. It cautioned that fragmentary excerpts were observed,
but not established as the cause. Report paired Astra usage and prices only in
an authorized measured run; do not claim cost per accepted task yet. Usage:
Gemini 3,461 prompt + 216 completion tokens; Sol 876 prompt + 231 completion
tokens. `decision_changed: true`: the observed quality gap makes the next step
failure-mechanism audit and blind confirmation, not a selector repair against
the public benchmark.

After the source/gold audit, a second Gemini 3.8 Flash + GPT-6.1 Sol council
review advised treating the two rows as potentially invalid or ambiguous,
preserving official keys and scores, and reporting row-exclusion sensitivity
without rekeying or tuning. The audit confirmed `player_7`'s key from its
per-player round-four bids, while the second row's logged receipt totals do not
support its offered keyed answer. Keep relation-loss evidence distinct from
answer-key validity; stop attributing all five official-key losses to Sift
until the second row is adjudicated. Usage: Gemini 3,316 prompt + 218
completion tokens; Sol 796 prompt + 200 completion tokens. `decision_changed:
true`: the report now distinguishes one source-supported miss from one
unresolved label and includes score sensitivities.

LLMLingua-2 references: [paper](https://arxiv.org/abs/2403.12968) and
[Microsoft implementation](https://github.com/microsoft/LLMLingua).
GPT-6 Astra prices: [official model pricing](https://developers.openai.com/api/docs/models/gpt-6-astra)
and [API pricing table](https://developers.openai.com/api/docs/pricing).
