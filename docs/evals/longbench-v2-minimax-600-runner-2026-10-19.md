# LongBench v2 MiniMax 600-request evaluation

## Frozen design

This schedule contains 100 distinct LongBench v2 questions and three matched
repeats for each of two arms: Full context and Sift. It therefore schedules
**600 model requests**: 300 Full and 300 Sift. It is not 600 unique questions.
The questions come from the previously exposed development sample, not a blind
holdout.

The runner reconstructs the exact request bodies from the pinned dataset,
tokenizer, chat template, current Sift implementation, and pinned source
manifest. It verifies the 100 IDs and case metadata against the live-route
parent and historical sample. Request order, messages, canonical bodies, and
the gzip bundle are hash-bound. The fixed seed is a matched request parameter;
it does not guarantee deterministic model outputs.
Sift preprocessing durations are runtime measurements, so they are recorded on
dispatch samples and excluded from the deterministic schedule hash.

Scoring keys remain outside provider request bodies. A response is scorable
only if its trimmed text is exactly one uppercase choice letter, the expected
MiniMax route/model was returned, the SSE stream ended with `[DONE]`, the request
had no failure, and the finish reason was `stop` or `length`. The report
preserves every attempted response and per-request cost receipt. Accuracy is
reported by arm both per response and with equal weight per task among tasks
with at least one scorable response; the denominator is reported explicitly.
The three repeats are clustered within each of 100 exposed questions; 300
responses per arm are not 300 independent questions. Treat scores as
descriptive and do not make blind-holdout or statistical-independence claims.
Incomplete runs must not be described as a completed comparison.

## Completed execution and results

The frozen schedule is complete: **100 exposed questions × 3 repeats × 2 arms
= 600 successful model responses**. There were **605 attempts** because five
requests with unknown original outcomes were each retried once and then
succeeded. An independent audit matched the full schedule, all request body
hashes, and all provider usage receipts to the frozen bundle. The five failed
attempts had no provider usage receipt; their token counts remain unknown and
are excluded rather than treated as zero.

Across the 600 successful provider receipts, MiniMax reported **32,527,062
prompt + 1,239 completion = 32,528,301 tokens**. Full context used 24,245,610
prompt tokens; Sift used 8,281,452, a **65.84% reduction** on this run. These
are provider-reported token counts, not a dollar or end-to-end time measurement.

| Arm | Correct / scorable | Response accuracy | Equal-task-weighted accuracy | Task majorities correct |
|---|---:|---:|---:|---:|
| Full context | 117/286 | 40.91% | 39.83% | 40/100 |
| Sift | 106/290 | 36.55% | 36.67% | 34/100 |

There were 18 Full-only task majorities, 12 Sift-only, 22 both-correct, and 48
neither-correct. Five successful responses ended with `finish_reason=length`
and were unscorable. Results are descriptive: repeats are clustered within
questions, all 100 question IDs were previously exposed during development,
and answer differences do not reveal which evidence omission caused them.
This run is not a blind holdout and does not establish quality parity, cost
savings, or accepted-task quality in Claude Code or Codex.

The final report is `.runs/longbench-v2-minimax-600-continuation-6.json`; the
frozen bundle is `.runs/longbench-v2-minimax-600-v4-bundle.json.gz`. An
aggregate-only copy intended for publication is
[`../results/longbench-v2-minimax-600-2026-10-19.json`](../results/longbench-v2-minimax-600-2026-10-19.json).
The report records the attempt history, including exactly one retry each for
jobs 89, 198, 223, 318, and 555.

The user authorized up to $2,000 for the original evaluation and asked that
progress focus on provider-reported tokens rather than billing reconciliation.
No spend claim is made here. Any new model comparison after changing Sift needs
a separately frozen protocol and appropriate authorization.

## Commands

Build the deterministic offline bundle (no API key read and no network call):

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --bundle .runs\longbench-v2-minimax-600-v4-bundle.json.gz
```

The completed run can be audited offline from the saved report and bundle. Do
not rerun the paid continuation command unless starting a new, explicitly
frozen study. For the original completion, the command was:

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --continue-from-report .runs\longbench-v2-minimax-600-continuation-5.json `
  --retry-unknown-once --spend-cap-usd 2000 `
  --accept-unknown-prior-outcome `
  --user-authorized-spend-cap-with-unverified-provider-balance `
  --bundle .runs\longbench-v2-minimax-600-v4-bundle.json.gz `
  --output .runs\longbench-v2-minimax-600-continuation-6.json
```

Only `status: complete` with `full_schedule_complete: true`, all 600 completed
jobs, and no in-flight request represents a completed study. A partial report
must be called partial and reported with unique scheduled completions, total
attempts, provider-reported prompt and completion tokens, unknown-token attempts,
and scorable responses. Never infer usage for an attempt without a provider receipt.
