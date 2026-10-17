# LongBench v2 handoff

## Current state

The one-repeat MiniMax M3 Full-context/Sift run is paused at the user's request. It is a deterministic schedule over the public 503-question LongBench v2 dataset, but it is incomplete and post-census development evidence.

The strongest current comparison is 446 valid matched questions. Full scored 198/446 (44.4%); Sift scored 193/446 (43.3%), a -1.1-point observed difference. On those same pairs, Sift used 75.8% fewer provider prompt tokens and had 76.8% lower provider-reported upstream cost. Implicit caching was enabled; costs are OpenRouter BYOK receipt fields, not invoice-verified. This does not establish parity, general savings, or multi-turn coding-agent quality. See [the detailed report](docs/results/longbench-v2-minimax-m3-fullsuite-progress-2026-10-17.md).

The checkpoint reports 923 completed scheduled jobs, 956 attempts, three runtime Full context-limit rejections, and no in-flight call. One Full job remains unresolved after a first HTTP 200 response with cost but no scorable completion and a retry that failed with SSL/unknown usage. The four unknown-usage attempts include three earlier attempts whose retries later succeeded; retain all attempt-level accounting. Do not issue another retry without renewed user direction.

## Resume artifacts

- Frozen manifest: `.runs/longbench-v2-minimax-fullsuite-one-repeat-v1.json.gz`
- Latest checkpoint: `.runs/longbench-v2-minimax-fullsuite-run-all-retry9.json`
- Manifest SHA-256: `72f502946ce2b3269b52fed3c0bb9433f5c96a9d3e5ff143a7e80f9aca6fdc7e`
- Schedule SHA-256: `f8d21e02f8a96f8d0b690d7c16b5c299a0faae868987af8ce5a03b203eb24b4c`
- Checkpoint SHA-256: `d0b964b1a44e9f7b42edea7bc7f7761586dbd9e9b616f11fd13a3d9d624ed14a`
- Runner: `benchmarks/prepare_longbench_v2_minimax_fullsuite.py`, `benchmarks/dispatch_longbench_v2_minimax_fullsuite.py`

## Next work

1. First do offline engineering: implement a content-addressed preflight cache keyed by all frozen source and configuration hashes; verify reconstructed request-body hashes exactly.
2. Independently review that change and run offline equivalence checks. No provider requests in this phase.
3. If the user resumes the run, first reconcile the unresolved attempt and refresh route/pricing/account/in-flight checks. Preserve the frozen schedule, explicit exclusions, and existing retry/stop rules.
4. Complete or explicitly classify every eligible slot, then publish a final paired report with coverage, quality, tokens, receipts/costs, preprocessing, request latency, total wall time, and unresolved usage.
5. Obtain an independent receipt and analysis audit before broadening README claims. Keep this dataset labeled post-census development evidence.

## Qwen 27B resource cleanup

The `subroute-qwen-local-1` container is stopped and exited (code 137); no Qwen/vLLM process or running Qwen container was present at wrap-up. Windows reported approximately 8.1 GiB available RAM. GPU use was 8.7/16.3 GiB, with desktop applications active; the stopped Qwen model is no longer running.
