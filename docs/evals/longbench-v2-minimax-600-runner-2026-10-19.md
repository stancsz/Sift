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

The frozen offline bundle contains all 600 scheduled requests. The paid run has
**not started**; no request from this 600-request schedule has been sent. The
default prepare command is offline. Dispatch requires an explicit `--dispatch`,
an explicit cap, successful live OpenRouter route/account preflight, and the
operator's billing and unsettled-request attestations. Failures stop the run;
there is no automatic retry or resume because replay could double-charge.

The live OpenRouter route check at **2026-10-17 14:55 UTC** found the pinned
`minimax/minimax-m3` / `minimax/fp8` endpoint, a 524,288-token prompt limit,
512,000-token completion limit, and prices of $0.30/M input and $1.20/M output.
At those live prices, the frozen 600-request schedule reserves **$14.6832579**.
This is a dated reserve estimate, not actual settlement or a guarantee against
single-request overage. Refresh route prices immediately before dispatch. If
either rate differs from the pinned assumptions, stop and review a new reserve
before sending requests. The key reports BYOK; OpenRouter credits and usage
limits do not enforce the MiniMax-side cap. The client checks per-request
reservations and settled receipts, but cannot prevent a single upstream request
from exceeding its projected reserve before the receipt arrives.

## Commands

Build the deterministic offline bundle (no API key read and no network call):

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --bundle .runs\longbench-v2-minimax-600-bundle.json.gz
```

The user authorized up to $2,000, and confirmed at least $14.69 of available
MiniMax billing headroom with no unsettled requests. The run uses a tighter
**$14.69 client cap**, just above the current full-schedule reserve. Refresh live
route pricing immediately before dispatch; do not run if the reserve rises
above the cap. Then dispatch the frozen schedule:

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --dispatch --prefix 600 --spend-cap-usd 14.69 `
  --confirm-no-unsettled-requests --confirm-minimax-billing-headroom `
  --bundle .runs\longbench-v2-minimax-600-bundle.json.gz `
  --output .runs\longbench-v2-minimax-600-run.json
```

Only `status: complete` with `full_schedule_complete: true`, all 600 completed
jobs, and no in-flight request represents a completed study. A partial report
must be called partial and reported with its arm counts, cost, failures, and
scorable responses. Reconcile the saved report against MiniMax billing before
interpreting cost results.
