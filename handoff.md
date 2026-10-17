# LongBench v2 handoff

## Current state

The MiniMax M3 LongBench v2 run has a deterministic frozen 503-question, one-repeat Full/Sift schedule. A saved checkpoint contains 923 completed jobs, 4 attempts with unknown provider usage, 3 runtime context-limit rejections, and 446 questions with valid scoreable responses from both arms. It is an incomplete run; no full-suite or multi-repeat claim is supported.

Interim matched results and accounting are in [`docs/results/longbench-v2-minimax-m3-fullsuite-progress-2026-10-17.md`](docs/results/longbench-v2-minimax-m3-fullsuite-progress-2026-10-17.md). On 446 matched answers, Sift used 75.8% fewer prompt tokens and had 76.8% lower provider-reported upstream inference cost; exact accuracy was 43.3% for Sift and 44.4% for Full. This is promising efficiency evidence with unresolved quality uncertainty, not a parity guarantee or general marketing claim.

## Resume artifacts and safety

- Frozen manifest: `.runs/longbench-v2-minimax-fullsuite-one-repeat-v1.json.gz`
- Latest checkpoint: `.runs/longbench-v2-minimax-fullsuite-run-all-retry9.json`
- Builder and dispatcher: `benchmarks/prepare_longbench_v2_minimax_fullsuite.py`, `benchmarks/dispatch_longbench_v2_minimax_fullsuite.py`
- Manifest hash: `72f502946ce2b3269b52fed3c0bb9433f5c96a9d3e5ff143a7e80f9aca6fdc7e`
- Schedule hash: `f8d21e02f8a96f8d0b690d7c16b5c299a0faae868987af8ce5a03b203eb24b4c`
- Checkpoint hash: `d0b964b1a44e9f7b42edea7bc7f7761586dbd9e9b616f11fd13a3d9d624ed14a`

The full suite dispatcher was stopped during local input reconstruction before sending new provider requests. The checkpoint recorded no in-flight request. Four earlier connection failures have unknown usage; preserve them as unknown even if a retry later returned a receipt. Resume only after resolving why each job remains unresolved and checking the aggregate budget ledger. The user's authorization up to $2,000 remains recorded, but the latest receipt totals do not establish a complete account balance or include unknown usage.

## Next work

1. Make resume practical: cache the exact preflighted request inputs keyed by manifest, schedule, source hashes, renderer, tokenizer, and Sift implementation hashes. The cache must be content-addressed, verified before use, and safely rebuilt when any pinned input changes. Avoid re-tokenizing every prompt on every resume.
2. Add and independently review a regression check proving cached and freshly reconstructed request bodies and hashes match exactly for the frozen manifest. Do not dispatch during this work.
3. Resume from the saved checkpoint with the same pinned model/provider, prompt construction, scoring, request settings, retries, and stop rules. Preserve every attempt, receipt, and unresolved usage record. Recheck the budget and provider route before dispatch.
4. Complete all locally eligible scheduled requests or classify each remaining one explicitly. Do not silently count the 79 preflight-ineligible slots or 3 runtime-rejected requests as completed.
5. Produce a final aggregate with paired accuracy and task-level outcomes, prompt/cache/completion token totals, observed and reconstructed cost where inputs permit, preprocessing time, request latency, end-to-end wall time, unknown attempts, and coverage. Use multiple repeats only in a separately frozen follow-up; this schedule contains one repeat.
6. Have an independent reviewer audit the report against raw receipts and the pinned schedule. Update README claims only after that review, placing sample, eligibility, cache, timing, and quality caveats adjacent to all claims.

## Local resource cleanup

The `subroute-qwen-local-1` Docker container (llama.cpp Qwen 27B server on port 8088) was stopped at the user's request. Its container was using about 7.9 GiB system memory; GPU memory fell from about 12.5 GiB used to 2.8 GiB after it stopped. To restart later, use the existing Compose configuration in its checkout and inspect that checkout's status first; do not discard its unrelated local changes.
