# LongBench v2 MiniMax M3 — wrap-up evidence

**Status: incomplete one-repeat run; no further requests dispatched.** This report summarizes the last saved checkpoint of a deterministic Full-context versus default-Sift comparison on the public 503-question LongBench v2 dataset. All questions were exposed during development, so this is development evidence, not a blind holdout or a multi-turn agent benchmark.

## Strongest matched evidence

The paired comparison includes **446 questions with a valid, scoreable answer from both arms**:

| Measure | Full context | Sift | Sift change |
|---|---:|---:|---:|
| Exact-choice correct | 198/446 (44.4%) | 193/446 (43.3%) | −1.1 percentage points |
| Provider prompt tokens | 48,995,078 | 11,873,192 | **75.8% fewer** |
| Provider-reported upstream inference cost | $13.9004 | $3.2311 | **76.8% lower** |
| Mean request wall time per paired answer | 3.23 s | 1.95 s | 39.7% lower request time |

Paired correctness outcomes were **136 both correct, 191 both incorrect, 62 Full-only correct, and 57 Sift-only correct**. A deterministic 20,000-resample question-level bootstrap over the 446 matched question rows gives a 95% percentile interval of **−6.1 to +3.6 percentage points** for Sift minus Full accuracy. The same paired bootstrap estimates prompt-token reduction at **75.8%**, with a 95% interval of **73.7% to 77.6%**. Both intervals are conditional on the 446/503 questions with scoreable answers in both arms and describe resampling variability within this exposed sample. They do not cover unscoreable or unresolved slots, and do not establish holdout performance, parity, non-inferiority, or generalization. Request time excludes Sift preprocessing, so it is not an end-to-end speed claim.

These figures use only the matched paired answers. Provider-reported upstream cost is an OpenRouter BYOK receipt field, not a verified MiniMax invoice. Implicit caching was enabled. The comparison therefore describes this route, cache behavior, sample, and one-repeat setup; it does not establish uncached or general dollar savings.

## Latest run status and accounting

- The frozen schedule contains 503 questions and 1,006 Full/Sift slots at one repeat. Local preflight marked 927 slots eligible (455 Full and 472 Sift); 79 slots were excluded by the local-fit screen.
- The latest checkpoint records **923 completed scheduled jobs**, 956 attempt records, 3 Full requests rejected at runtime by the provider context limit, and no in-flight request. The run is not complete.
- Four attempts have unknown usage. Three were followed by successful receipt-backed retries. One Full job remains unresolved: its first attempt returned HTTP 200 and a cost receipt but no completed scorable answer; its retry failed with SSL and has unknown usage. Preserve both attempts and do not retry again without a new explicit decision.
- Valid usage receipts cover 949 attempts: 64,110,516 prompt tokens, 2,079 completion tokens, and **$18.0783** reported upstream cost. This excludes the four attempts with unknown usage and is not an invoice total.
- The latest all-response score summary has 447 scorable Full answers (199 correct, 44.5%) and 471 scorable Sift answers (203 correct, 43.1%). Those are unpaired totals; the matched table above is the fair comparison.
- The successful paired responses' request wall times exclude preprocessing. End-to-end run time was not measured.

## Reproducibility and retained evidence

- Frozen manifest SHA-256: `72f502946ce2b3269b52fed3c0bb9433f5c96a9d3e5ff143a7e80f9aca6fdc7e`
- Frozen schedule SHA-256: `f8d21e02f8a96f8d0b690d7c16b5c299a0faae868987af8ce5a03b203eb24b4c`
- Latest raw checkpoint is retained outside this repository. Its SHA-256 is `d0b964b1a44e9f7b42edea7bc7f7761586dbd9e9b616f11fd13a3d9d624ed14a` (3,852,073 bytes). A [sanitized paired-row aggregate](longbench-v2-minimax-m3-fullsuite-paired-aggregate-2026-10-17.json) is published beside this report.
- Runner sources: `benchmarks/prepare_longbench_v2_minimax_fullsuite.py` and `benchmarks/dispatch_longbench_v2_minimax_fullsuite.py`
- The aggregate-only bootstrap is reproducible without model calls: `python benchmarks/bootstrap_longbench_v2_pairs.py`. It checks that the paired rows reconcile to the correctness cells, scores, and prompt-token totals before resampling. Default settings are 20,000 paired question-level percentile resamples with seed `20261018`; the script emits aggregate metrics only.

The raw checkpoint retains individual provider receipts and responses locally; this report publishes aggregate evidence only. Keep README claims scoped to the paired result above and its limitations.
