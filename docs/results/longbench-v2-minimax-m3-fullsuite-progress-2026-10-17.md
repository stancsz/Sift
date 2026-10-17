# LongBench v2 MiniMax M3 full-suite progress report

**Status: substantial interim evidence; the full suite is not complete.** This report summarizes the latest saved one-repeat checkpoint from the deterministic 503-question LongBench v2 schedule. It is not a blind holdout or a multi-turn agent benchmark.

## Matched comparison

Among **446 questions with a valid, scoreable response from both arms** (one scheduled repeat per question):

| Measure | Full context | Sift | Sift change |
|---|---:|---:|---:|
| Exact-choice correct | 198/446 (44.4%) | 193/446 (43.3%) | −1.1 percentage points |
| Provider prompt tokens | 48,995,078 | 11,873,192 | **75.8% fewer** |
| Provider-reported upstream inference cost | $13.9004 | $3.2311 | **76.8% lower** |
| Mean request wall time for these paired answers | 3.23 s | 1.95 s | 39.7% lower request time |

Paired correctness outcomes were **136 both correct, 191 both incorrect, 62 Full-only correct, and 57 Sift-only correct**. The observed accuracy difference is small relative to the discordant outcomes: a simple paired normal interval is approximately −5.9 to +3.7 percentage points. Treat this as a descriptive interim comparison, not proof of quality parity or non-inferiority. It does show that Sift substantially reduced prompt exposure and reported provider cost on the same scoreable questions while retaining similar observed accuracy in this checkpoint.

The cost figures are provider-reported OpenRouter upstream inference-cost details for BYOK requests, not an independently verified invoice. The percentages use the matched 446-question subset and formula `1 − (Sift aggregate / Full aggregate)`. Implicit provider caching was enabled; no cache-cold claim is made. Completion-token usage was small for this exact-choice task, and the comparison concerns prompt reduction and these provider-reported costs, not arbitrary workloads.

## Coverage and run accounting

- Dataset: 503 questions; frozen schedule: 1,006 Full/Sift request slots, one repeat per question.
- Local preflight marked 927 slots eligible and 79 ineligible (455 Full, 472 Sift eligible). Three additional Full requests were rejected at runtime for exceeding the provider prompt limit and are recorded as runtime-ineligible.
- Checkpoint records 923 completed jobs, four unresolved-usage attempts, and 446 paired scoreable answers. It contains 956 attempt records because some requests were retried. Do not treat attempt count as completed unique jobs.
- Provider receipts include 64,110,516 prompt tokens and 2,079 completion tokens across 949 attempts with valid usage. Four connection failures have unknown usage; their tokens are not included in those totals. The receipt-reported upstream cost is $18.0783, excluding any unknown unreceipted usage.
- The continuation was stopped during local prompt preflight before any further provider requests. The checkpoint has no in-flight request. The full schedule is incomplete; there is no multi-repeat estimate.
- The matched-response request-time values exclude Sift preprocessing. End-to-end task time was not measured for this run, so the request-time comparison is not an end-to-end speed claim.

## Reproducibility and artifacts

The frozen manifest SHA-256 is `72f502946ce2b3269b52fed3c0bb9433f5c96a9d3e5ff143a7e80f9aca6fdc7e`; the frozen schedule SHA-256 is `f8d21e02f8a96f8d0b690d7c16b5c299a0faae868987af8ce5a03b203eb24b4c`. The local raw checkpoint is `.runs/longbench-v2-minimax-fullsuite-run-all-retry9.json` (3,852,073 bytes), SHA-256 `d0b964b1a44e9f7b42edea7bc7f7761586dbd9e9b616f11fd13a3d9d624ed14a`. It preserves individual receipts and responses and is intentionally kept out of this compact report. The source suite builder and dispatcher are `benchmarks/prepare_longbench_v2_minimax_fullsuite.py` and `benchmarks/dispatch_longbench_v2_minimax_fullsuite.py`.

The next step is to fix the resume preflight cost or add a verified reusable prepared-input cache, validate it against the frozen hashes, then resume the same schedule from the saved checkpoint. Do not change questions, scoring, prompts, target, or model settings. See [`handoff.md`](../../handoff.md) and the LongBench remaining-work section in [`goal.md`](../../goal.md).
