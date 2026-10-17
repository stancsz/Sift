# Deterministic LongBench v2 MiniMax pilot runner

## Design

The frozen design selects 100 LongBench v2 task IDs and schedules three matched
repeats for each of two arms: Full context and Sift. That is **600 model
requests over 100 distinct questions**, not 600 distinct questions. The IDs are
the previously exposed development sample, so the cohort is not a blind
holdout.

The runner rebuilds the exact request bodies from the pinned dataset, tokenizer,
chat template, current Sift implementation, and a current-source manifest. It
checks the 100 IDs and case metadata against both the current live-route parent
manifest and the historical sample before building prompts. The historical
manifest remains unchanged; its old source hash is not treated as current
provenance.

Each task/arm block contains three repeats. A fixed study seed randomizes the
six requests within each block. The request schedule, prompt messages, and
canonical JSON bodies are committed with SHA-256 hashes in a gzip bundle whose
metadata is stable across rebuilds. This makes schedule and request
reconstruction deterministic. It does **not** guarantee deterministic model
outputs; the seed is a matched request parameter, not a provider determinism
claim.

Scoring keys are stored separately from the request bodies. A response is
scorable only when its trimmed output is exactly one uppercase choice letter.
The current 10-request dispatch report preserves response text and joins each
sample back to its case ID so a local post-run scorer can use the frozen keys.

## First-10 pilot

Dispatch is a single sequential prefix and the runner hard-limits it to schedule
indices 0 through 9. It does not retry or resume. This prefix contains all six
repeats for the first question and four requests for the second question: four
Full and six Sift responses in total. It is an operational pilot only; it is
too small and unbalanced for a comparative accuracy claim.

The offline bundle has 600 requests and a deterministic gzip SHA-256 of
`0c30b2deb4854a239486f927ea71354a6a3b7556cf0becb682b17dded9542b64`. Its
schedule SHA-256 is
`0e2a121037e01ff82e447f710b9019546722603fa0545f4643b5f111fcb117bf`. These
hashes identify the prepared artifact; rebuilding after a runner or provenance
change produces a different artifact and requires a new review.

The first ten requests reserve approximately `$0.511` at the currently pinned
planning prices (`$0.30/M` input and `$1.20/M` output). Those are dated planning
assumptions, not a live quote. Before dispatch, refresh the route and account
limits, compare the live prices to the manifest, and obtain the user's explicit
aggregate cap for this prefix. The client-side cap and per-request reservation
checks are protective guards; BYOK provider billing remains the settlement
source.

## Commands

Prepare or verify the offline bundle (no API key read and no network call):

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --bundle .runs\longbench-v2-minimax-600-bundle.json.gz
```

After live route/account preflight and user approval of a cap, dispatch only the
first ten jobs by replacing `<approved-cap>` with that approved dollar amount:

```powershell
\.venv\Scripts\python.exe benchmarks\run_longbench_v2_minimax_600.py `
  --dispatch --prefix 10 --spend-cap-usd <approved-cap> `
  --confirm-no-unsettled-requests --confirm-minimax-billing-headroom `
  --bundle .runs\longbench-v2-minimax-600-bundle.json.gz `
  --output .runs\longbench-v2-minimax-600-pilot.json
```

Any mismatch in provenance, route, price, usage, receipt, or response termination
stops the pilot. Reconcile the saved report and provider billing before
considering another run.
