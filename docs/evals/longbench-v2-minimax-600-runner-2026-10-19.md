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

The user directed continuation through all 600 requests and instructed that
progress reporting focus on token use. The next continuation retries job 223
once as attempt 2, then proceeds through jobs 224–599. It validates and retains
all 226 prior attempts, frozen job identities, request hashes, provider token
totals, and receipts. Any further ambiguous network failure stops the run.

Among completed responses so far, Full scored 48/109 scorable responses (44.0%
response accuracy; 43.7% equal-task-weighted across 37 tasks). Sift scored
31/109 (28.4%; 27.9% equal-task-weighted across 37 tasks). This remains a
partial, exposed-sample diagnostic, not a LongBench comparison result.

Continuation explicitly retries only the latest saved, eligible unknown
network attempt. It checks the exact saved prefix against schedule hashes, row
identities, request body hashes, provider token totals, and cost receipts;
preserves every earlier attempt; records a retry as attempt 2; then continues in
schedule order. It never retries other failures. A new ambiguous failure stops
the run. Each continuation report is saved separately and sums provider-reported
tokens only, with unknown-token attempts counted separately.

Refresh the live OpenRouter route before sending. The user authorized up to
$2,000. Provider balance after the initial attempt is unverified, so the command
records that limitation rather than claiming a fresh balance attestation. The
$2,000 value is a client-side guard; OpenRouter BYOK does not impose a
MiniMax-side hard cap.

## Commands

Build the deterministic offline bundle (no API key read and no network call):

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --bundle .runs\longbench-v2-minimax-600-v4-bundle.json.gz
```

The user authorized up to **$2,000**, and earlier confirmed no unsettled
requests and at least $14.69 of MiniMax headroom. Continue with a fresh live
route check and record provider balance as unverified:

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --continue-from-report .runs\longbench-v2-minimax-600-continuation-2.json `
  --retry-unknown-once --spend-cap-usd 2000 `
  --accept-unknown-prior-outcome `
  --user-authorized-spend-cap-with-unverified-provider-balance `
  --bundle .runs\longbench-v2-minimax-600-v4-bundle.json.gz `
  --output .runs\longbench-v2-minimax-600-continuation-3.json
```

Only `status: complete` with `full_schedule_complete: true`, all 600 completed
jobs, and no in-flight request represents a completed study. A partial report
must be called partial and reported with unique scheduled completions, total
attempts, provider-reported prompt and completion tokens, unknown-token attempts,
and scorable responses. Never infer usage for an attempt without a provider receipt.
