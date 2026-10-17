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

## Current execution status

The frozen offline bundle contains all 600 scheduled requests. The first paid
attempt stopped incomplete on 2026-10-17 after **90 requests were attempted and
89 completed**. Provider receipts reported **5,330,954 prompt tokens + 135
completion tokens = 5,331,089 total tokens**. The 90th request, Sift job
`6725db46bb02136c067d84b4:sift:2`, failed with an SSL exception before returning
an HTTP status, response ID, or usage receipt. Its token outcome is unknown and
is not counted as zero. The original report is
`.runs/longbench-v2-minimax-600-run.json`.

The first continuation resumed the same frozen schedule, successfully retried
job 89, then stopped at job 198 (`672494e5bb02136c067d7697:full:2`) after a
`ConnectionError` with no HTTP response or provider usage receipt. The next
continuation retried job 198 successfully and proceeded through job 223, which
then stopped on an SSL exception with no HTTP response, generation ID, or usage
receipt. Its report is `.runs/longbench-v2-minimax-600-continuation-2.json`.
Combined status is **226 attempts, 223 unique scheduled jobs completed**. The
three unknown-token attempts are the original job 89 attempt, the original job
198 attempt, and job 223. Across 223 provider usage receipts, MiniMax reported
**13,317,186 prompt + 396 completion = 13,317,582 tokens**. Unknown-token
attempts remain unknown and are not counted as zero.

Continuation 3 retried job 223 successfully and proceeded through job 318,
which stopped on an SSL exception with no HTTP status, response ID, or usage
receipt. Its report is `.runs/longbench-v2-minimax-600-continuation-3.json`.
Combined status is **322 attempts, 318 unique scheduled jobs completed**.
Provider receipts report **19,399,752 prompt + 600 completion = 19,400,352
tokens**. Four attempts have unknown usage (indices 89, 198, 223, and 318); that
usage is not counted as zero. The independent checkpoint audit verified the
attempt sequence, frozen request hashes, 318 receipt rows, and token ledger.

Continuation 4 retried job 318 successfully and completed through job 549. It
stopped before sending job 550 because Windows denied the atomic report rename
(`WinError 5`). The committed JSON and `.tmp` checkpoints contain identical
554 attempts through successful job 549; the `.tmp` file adds only the
pre-request marker for job 550. Source order and the independent audit confirm
that the provider call occurs after that checkpoint write, so job 550 was not
sent and is not counted as an attempt or unknown-token request.

The recovered checkpoint is
`.runs/longbench-v2-minimax-600-continuation-4-recovery.json`. It records 554
attempts and 550 unique completed jobs. Provider receipts report **30,882,116
prompt + 1,142 completion = 30,883,258 tokens**. Four earlier attempts remain
unknown (indices 89, 198, 223, and 318). The next request is job 550 as its
first attempt, followed by jobs 551–599. The runner validates this exact
recovery state before dispatch. Its report writer now uses unique temporary
files and bounded retries for short Windows sharing locks.

Among completed responses so far, Full scored 104/262 scorable responses
(39.7% response accuracy; 38.8% equal-task-weighted across 92 tasks). Sift
scored 94/266 (35.3%; 35.5% equal-task-weighted across 92 tasks). These are
partial, exposed-sample diagnostics, not final LongBench comparison results.

Continuation validates the exact saved prefix against schedule hashes, row
identities, request body hashes, provider token totals, and receipts. A user
authorized one retry per ambiguous attempt, followed by schedule-order work;
unknown outcomes remain separately recorded. A pre-request checkpoint failure
resumes at the unsent index as attempt 1. Each continuation report is saved
separately and carries an up-to-date provider token total.

The user authorized up to $2,000 for the evaluation and confirmed billing
headroom/no unsettled requests earlier in the run. Progress reporting focuses
on provider-reported tokens; unknown-token attempts remain separate. The $2,000
value is a client-side guard.

## Commands

Build the deterministic offline bundle (no API key read and no network call):

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --bundle .runs\longbench-v2-minimax-600-v4-bundle.json.gz
```

Continue from the verified pre-request checkpoint. Job 550 was not sent, so this
resumes it as its first attempt:

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --continue-from-report .runs\longbench-v2-minimax-600-continuation-4-recovery.json `
  --retry-unknown-once --spend-cap-usd 2000 `
  --accept-unknown-prior-outcome `
  --user-authorized-spend-cap-with-unverified-provider-balance `
  --bundle .runs\longbench-v2-minimax-600-v4-bundle.json.gz `
  --output .runs\longbench-v2-minimax-600-continuation-5.json
```

Only `status: complete` with `full_schedule_complete: true`, all 600 completed
jobs, and no in-flight request represents a completed study. A partial report
must be called partial and reported with unique scheduled completions, total
attempts, provider-reported prompt and completion tokens, unknown-token attempts,
and scorable responses. Never infer usage for an attempt without a provider receipt.
