# Relation-binding diagnostic pilot

**Status: preregistration, not a completed evaluation.** This pilot tests one
mechanism suggested by the LongBench source audit. It is not a powered quality
comparison, a release gate, or evidence of Astra savings.

## Question

When a task depends on joining a key to a value across structured history, does
Sift drop or separate the relation, and can preserving the source record as a
unit recover the answer at the same input budget?

The current LongBench screen supplies one supported example: `player_7` and
its round-four bid of 40 appear in separate Sift excerpts. Its public answer
must not be used to tune the selector or define the new cases.

## Case construction and freeze

An independent case author must create 8 record-template families and 4
hidden instances per family (32 task instances). The Sift selector author must
not see the templates, generated records, answer keys, or required source spans
until the full case set and scoring code have been hashed. Keep the cases
private until the pilot report is complete, then publish the generated cases,
gold mappings, and hashes so others can replay the diagnostic.

Each task must require joining at least two fields from a source record or
several records. Vary JSON nesting, field names, order, unrelated records,
repeated query words in distractors, and query phrasing. Include positive and
negative cases, including conflicting revisions. Inputs should be ordinary
text-only chat histories with a historical tool result and an exact current
question. Every required answer must be reproducible from quoted source spans.
The author must independently validate the gold mapping against those spans
before freezing the files.

Use the evaluated local model's tokenizer to keep full requests at or below
28,672 input tokens, reserving 4,096 of the 32,768 context for generation. Each
case must exceed Sift's 24,576 estimated-token trigger. Cases outside these
bounds are reported as exclusions before any inference call. Use the frozen
LongBench candidate source hash recorded in the main quality-comparison
protocol; no selector edits are allowed during this pilot.

The selector freeze is Git commit
`ea99aaa377662c93024d010a3a7376bf61cf4d65`; its `src/sift/core.py` blob
SHA-256 is `88521ac93678bbc241149248e0b7162dfe3a79595b400559f98811be3b6fc9d5`.
The earlier preregistration hash (`c37f8482...`) does not resolve to any core
version in this repository's Git history, so it is not a reproducible freeze.
Run the pilot from the committed source snapshot, not the dirty development
worktree. The research-only whole-record candidate in
[`relation_binding_candidate.py`](../../benchmarks/relation_binding_candidate.py)
was implemented before the case author run and hashes to
`adb0668cf30fb07d7af9a0be6920e4f217b47ca94e893e80532f7957b4a630e4`. Its two
initial boundary tests pass. Any change to either source file invalidates this
pilot freeze; do not edit either against the authored cases. The candidate must
import the frozen core snapshot identified above, not the working-tree module.

## Arms and procedure

Run each of the 32 tasks through the same model, question, generation settings,
and output reserve:

1. Full context.
2. Frozen Sift at the 24,576 estimated-input target.
3. A separately frozen structure-preserving candidate, which selects complete
   source records without access to gold answers or spans, at the same exact
   downstream token ceiling. To isolate record boundaries, this research-only
   candidate must reuse Sift's query terms, rarity weights, signal and recency
   weights, tie-breaking order, caller tokenizer, and chronological output
   ordering. Apply those same scoring inputs to each complete parsed JSON
   record as one indivisible candidate, then emit the original source slice
   verbatim. This is its only selection change. It must pass the existing hard
   budget and protected-context checks before the pilot. Freeze its source hash
   separately; do not ship it as a Sift runtime path.
4. An oracle-evidence diagnostic containing the independently verified source
   spans plus the same task and protected instructions. This diagnostic is not
   a deployable compressor or a competing product; it tests whether the model
   can answer when the necessary relations are visibly intact.

Randomize arm order per task and disable prompt caching for this diagnostic so
cache state does not change the evidence comparison. Make three generations
per task/arm with a fixed seed where supported. A task is the analysis unit;
repeats are aggregated by strict majority, with ties scored incorrect and also
reported. Keep every invalid answer and abnormal termination as a failure.

## Primary diagnostic

The primary paired outcome is exact task answer accuracy at the task level.
For each task, also record whether its required source spans appear intact in
each forwarded request. Classify each full-correct/Sift-wrong task as:

- **Extraction-related:** the full request contains the gold relation, Sift
  omits or separates it, and the oracle-evidence arm answers correctly.
- **Reasoning or prompt-related:** the full request contains the gold relation,
  but the oracle-evidence arm still fails.
- **Unresolved:** source presence or the answer cause cannot be verified.

Publish the paired 2x2 full/Sift task table and the same table for the
structure-preserving candidate. Report extraction accuracy, exact token counts,
selector CPU and wall time, TTFT, end-to-end latency, output tokens, and
terminal outcomes. Do not count repeats as independent tasks or use this pilot
for a noninferiority confidence claim.

## Decision rule

First stop any arm that changes protected instructions, alters active work,
exceeds its budget, or fails a protocol invariant. Do not modify the frozen
selector from these cases.

Advance the structure-preserving approach to a new, independently authored
holdout only if it repeatedly rescues source-verified full-correct/Sift-wrong
tasks across at least three instances and two template families, the oracle
arm answers those tasks correctly, and no corresponding full-correct task is
lost. If the oracle arm fails, classify the evidence as reasoning/prompt risk,
not a selector defect. A pilot pass only justifies the next blinded evaluation;
it does not establish parity, sharper answers, lower whole-task cost, or
generalization to natural agent histories.

## Advisor review

On 2026-10-16, the GPT-6.1 Sol / Gemini 3.8 Flash council recommended this
frozen-selector relation-binding pilot with independently authored templates,
hidden instances, source-to-answer gold checked before evaluation, and
task-level paired answer accuracy. The advice distinguishes extraction loss
from reasoning error using an oracle-evidence diagnostic. It cautions that
synthetic results may not transfer to noisy natural histories. The advice
changed the next evaluation from a broad structured-data comparison to this
specific relation-binding pilot; no selector change was authorized. Reported
usage: Gemini 3,037 prompt + 115 completion tokens; Sol 648 prompt + 341
completion tokens.

## Authoring preflight, 2026-10-16

The frozen selector snapshot passes 21 core tests and the whole-record
candidate passes its 2 boundary tests. The case set is not ready. A Claude Code
authoring response was rejected: its JSON was malformed, and a syntax-only
diagnostic found multiple cases below the preregistered 8-record minimum. The
response is quarantined under ignored `.runs/` data and was not scored. The
reported CLI cost for that request was $0.2672536; token usage fields were not
available. A second attempt with constrained JSON output was stopped after 15
minutes without a payload or usage receipt. Neither response is a holdout, and
no inference calls were made. The next evaluation requires a valid independent
author response, a predeclared scoring harness, and hashes recorded before
examining the case content.
