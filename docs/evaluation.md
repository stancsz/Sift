# Evaluation record

Sift is still a preview. These checks show what it currently does on selected tests and public development tasks; they do not establish broad agent quality, user adoption, or a general cost or speed improvement.

## Local verification

The latest local full-suite runs passed all 366 tests in isolated Python 3.14.0 (98.27 seconds) and Python 3.11.14 (107.65 seconds; 17 dependency warnings in each run). Root-level `python -m pytest -q` works because discovery is scoped to `tests/`; this avoids duplicate-module collection from benchmark fixtures. The latest `python benchmarks/compare.py` run passed 100/100 authored middle-fact placements in 0.335 CPU seconds. These are offline software checks. Pull request #2 run [#39174267512](https://github.com/stancsz/sift/actions/runs/39174267512) passed the 48-test Python 3.12 smoke in 22 seconds at head `a1dea16`; its full compatibility matrix was skipped because the workflow runs that matrix on schedule or manual dispatch, not on every PR.

## LongBench v2

Both studies use public questions that were exposed during development. Neither is a blind holdout or an agent-loop completion benchmark.

### Matched 600-response study

The completed MiniMax M3 study used 100 questions with three repeats per arm. Sift used 65.8% fewer provider-reported prompt tokens than full context, with an exact-choice accuracy gap of −4.36 percentage points. The score and denominator differ by arm because five responses reached the output limit and were unscorable. The run does not establish quality parity.

- [Protocol, full results, and limitations](evals/longbench-v2-minimax-600-runner-2026-10-17.md)
- [Aggregate-only machine-readable result](results/longbench-v2-minimax-600-2026-10-17.json)

### Broader one-repeat checkpoint

A separate comparison on the public 503-question set has 446 matched scoreable answers: Full scored 198/446 (44.4%) and Sift 193/446 (43.3%), a −1.1-point observed difference. Sift used 75.8% fewer prompt tokens in those pairs. The run is incomplete, and one Full slot remains unresolved. The paired-row artifact includes only correctness, token counts, receipt cost, and request wall time; it excludes prompts, answer text, raw responses, timestamps, and provider IDs.

- [Checkpoint report and limitations](results/longbench-v2-minimax-m3-fullsuite-progress-2026-10-17.md)
- [Sanitized paired-row aggregate](results/longbench-v2-minimax-m3-fullsuite-paired-aggregate-2026-10-17.json)

Receipt costs are provider-reported OpenRouter BYOK data, not invoice totals. Implicit caching was enabled. Request wall time excludes Sift preprocessing; it is not end-to-end agent speed. Treat both comparisons as descriptive development evidence only.

### Prepared broader paired cohort (not run)

A larger Full/Sift schedule is prepared for 344 questions selected by the historical modeled paired-fit screen from the same public 503-question set, with three repeats per arm (2,064 planned generations). These IDs and labels were exposed during development; a future run would broaden the exposed comparison, not create a holdout. The prepared schedule's historical-rate planning reserve is approximately $41.87, not a live quote or spending authorization. No inference for this schedule has been made. Before dispatch, reconcile the unresolved prior attempt and account exposure, refresh the exact MiniMax route and pricing, verify available credits, and obtain an explicit user-set cap sufficient for the refreshed reserve. Report exclusions and all failures alongside scoreable pairs.

For new generalization evidence, use separately sourced held-out tasks with blinded answers and a frozen harness; LongBench v2's public set cannot serve as that holdout. AppWorld `test_challenge` is under consideration as an aggregate-only agent-task validation source. It has not been run; its [source review and protocol](evals/agent-holdout-source-review-2026-10-18.md) requires an aggregate-only output rehearsal before any test access and rules out task-level error analysis.

## Native-agent checks

A single accepted research-audit task and several failed or inconclusive coding-agent tasks show why span retention alone is not enough. In the accepted task, compaction preserved the checked result, but the one warm/mixed-cache run had higher TTFT and whole-task time than Full. Other development runs found selector misses, context-limit errors, and increased request counts. These are task-specific observations, not an adoption study or a general Sift-caused outcome.

See the [native-agent pilot record](evals/natural-agent-pilot-2026-10-16.md) and the [acceptance roadmap](../ROADMAP.md) for the current gates. Before claiming production readiness, Sift still needs independently authored held-out tasks, matched accepted outcomes, real-client compatibility coverage, and repeated total-cost and latency measurements.
