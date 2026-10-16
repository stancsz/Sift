# MiniMax LongBench v2 evidence-retention audit

This is a blinded, offline follow-up to the [MiniMax M3 screen](longbench-v2-minimax-m3-results-2026-10-16.md). The source evidence was frozen from the pinned dataset before reading the model outputs. The audit makes no provider requests and does not change the Sift selector.

## Method

The audit checks complete source evidence rather than asking a model to explain an answer. For the Yelp CSV question, it parses the original CSV and identifies every row whose comment contains “mexican,” then counts unique exact comment strings. For the game question, it derives every round's complete player-contribution vector from the original JSON. Full prompts and compacted prompts are compared against these exact values. The script verifies the dataset, prompt, tokenizer, template, manifest, and Sift core hashes before measuring retention.

This is a narrow diagnostic with two questions. It is not a gold-span annotation for LongBench v2, and it does not establish the cause of the full benchmark's accuracy differences.

## Results

| Case | Source evidence | Full prompt | Sift 16K | 24K | 32K | 48K | 64K |
|---|---|---:|---:|---:|---:|---:|---:|
| Yelp distinct-comment count | 41 unique exact matching CSV records | 41/41 | 0/41 | 0/41 | 0/41 | 0/41 | 0/41 |
| Game contribution aggregation | 20 complete round vectors | 20/20 | 16/20 | 16/20 | 16/20 | Original prompt fits | Original prompt fits |

The CSV case's full-context request failed during the benchmark. Its Sift answers were wrong at 16K, 24K, 32K, and 64K, and correct at 48K. Since no full answer exists, this case cannot support a paired correctness comparison. In the game case, full context answered incorrectly; Sift answered correctly at 24K and incorrectly at 16K and 32K. Thus a correct Sift answer can occur despite incomplete retained evidence, and a wrong full answer does not make omitted evidence harmless.

## Interpretation

These two cases establish a concrete weakness for exhaustive structured-data questions: generic excerpts did not preserve the complete source records needed to verify the distinct count, and the game excerpts omitted four whole contribution vectors at the smaller targets. They do not show that every lost item was individually essential, nor that this omission explains the overall MiniMax score. The question may be answerable through another sufficient representation, which this exact-containment audit intentionally does not credit.

The next selector work should be driven by a small, task-neutral regression fixture that preserves query-relevant structured records as complete units under the token budget. Any candidate needs to retain record boundaries and prove that selection does not silently imply complete coverage when it is partial. Keep this benchmark finding separate from implementation claims until such a change is evaluated against the same frozen cases and broader regression tests.

## Artifacts

- [Frozen protocol and aggregate results](longbench-v2-minimax-m3-results-2026-10-16.md)
- [Machine-readable audit output](../results/longbench-v2-minimax-m3-evidence-retention-2026-10-16.json)
- [Offline audit script](../../benchmarks/audit_longbench_v2_minimax_evidence.py)
- [Advisor council receipt](sift-advisor-council-research-validity-2026-10-16.md)
