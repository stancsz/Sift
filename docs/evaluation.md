# Evaluation record

Sift is still a preview. These checks show what it currently does on selected tests and public development tasks; they do not establish broad agent quality, user adoption, or a general cost or speed improvement.

## Local verification

The latest local full suite passed **375 tests on Python 3.14** in 103.42 seconds, with 17 dependency warnings, from a clean virtual environment after installing `.[litellm,test]`. Run it with `python -m pytest tests -q`; the scheduled/manual CI job uses the same command across Python 3.11–3.14. This includes the optional OpenAI Python SDK loopback test and regressions for Ollama reasoning fields on active tool turns. An isolated Ubuntu/Python 3.12 container at code-bearing PR head `6b317c8` previously passed all 370 tests in 83.59 seconds, with 17 warnings; its offline authored comparison returned 100/100 Sift hits and 0/100 head/tail hits. The prior 369-test suite also passed on Python 3.11.14, 3.12, 3.13, and 3.14. The current CI design runs a short Python 3.12 core smoke on every push and pull request; its [exact-head run for PR #7](https://github.com/stancsz/sift/actions/runs/39272382994) passed in 29 seconds. The full multiversion suite and offline comparison remain weekly/manual to limit routine CI time. These are software checks, not model-quality evidence. The earlier [failure #39077270041](https://github.com/stancsz/sift/actions/runs/39077270041) came from a workflow that omitted the pytest extra and a test that opened an untracked LongBench result file; the current workflow installs both `litellm` and `test` extras.

## LongBench v2

Both studies use public questions that were exposed during development. Neither is a blind holdout or an agent-loop completion benchmark.

### Matched 600-response study

The completed MiniMax M3 study used 100 previously exposed questions with three repeats per arm. Sift used 65.8% fewer provider-reported prompt tokens than full context, with an exact-choice accuracy gap of −4.36 percentage points. The score and denominator differ by arm because five responses reached the output limit and were unscorable. Collapsing the three repeats to one paired majority per question gives Full 40/100 and Sift 34/100 (−6 pp); the aggregate-only 20,000-resample question bootstrap interval is −17 to +5 pp, with exact two-sided McNemar *p* = 0.361595. The interval describes task sampling within this exposed cohort; neither it nor the response-level result establishes parity, non-inferiority, or generalization.

- [Protocol, full results, and limitations](evals/longbench-v2-minimax-600-runner-2026-10-17.md)
- [Aggregate-only machine-readable result](results/longbench-v2-minimax-600-2026-10-17.json)

### Broader one-repeat run (incomplete)

A separate frozen schedule covered the public 503-question set once per arm. Of its 927 locally eligible Full/Sift slots, 923 completed; three Full requests were rejected at runtime by the provider context limit, and one Full slot remains unresolved. Four attempts had unknown usage: three later succeeded after retry, and the fourth is the unresolved Full slot. The strongest paired comparison has 446 questions with a scoreable answer from both arms: Full scored 198/446 (44.4%) and Sift 193/446 (43.3%), a −1.1 percentage-point observed gap. Sift used 75.8% fewer provider-reported prompt tokens. A paired question bootstrap gives conditional 95% intervals of −6.1 to +3.6 pp for accuracy and 73.7% to 77.6% for prompt-token reduction. These intervals apply only to the matched exposed development rows; they do not establish parity, non-inferiority, or generalization. Receipt costs were $13.9004 for Full and $3.2311 for Sift, but are cache-sensitive OpenRouter BYOK estimates rather than invoice totals. Request time excludes Sift preprocessing.

- [Checkpoint report, full accounting, and limitations](results/longbench-v2-minimax-m3-fullsuite-progress-2026-10-17.md)
- [Sanitized paired-row aggregate](results/longbench-v2-minimax-m3-fullsuite-paired-aggregate-2026-10-17.json)

### Field-pruning pilot (four tasks)

An opt-in structured-data field-pruning screen used four preselected exposed tasks, three matched repeats, and 36 MiniMax M3 requests. Full context scored 8/12 exact answers (3/4 task majorities), default Sift scored 1/12 (0/4), and field pruning scored 6/12 (2/4). Field pruning used 96.56% fewer provider prompt tokens than Full in this small sample, but remained behind Full on exact answers. This only supports preparing a broader offline validation; four tasks do not show generalization, and field pruning remains off by default. Reported receipt costs are cache-sensitive and not invoice totals.

- [Pilot protocol, results, parser correction, and budget limits](evals/longbench-v2-field-pruning-pilot-2026-10-17.md)
- [Corrected analysis and scored rows](evals/longbench-v2-minimax-field-pruning-pilot-analysis-v2-2026-10-17.json)

### Prepared broader paired cohort (not run)

A separate prepared schedule covers 344 questions selected by a historical modeled paired-fit screen from the same public 503-question set, with three repeats per arm (2,064 planned generations). These IDs and labels were exposed during development; the schedule would broaden the exposed comparison, not create a holdout. Its prepared manifest estimates a $41.865635 reserve using a 64-token output cap and dated route rates. The linked offline cost audit models the same cohort with a legacy 16-token output cap and estimates $41.707235; that is a different cap assumption, not a replacement manifest estimate. Neither estimate is a live quote or spending authorization. No inference has been run for this schedule. Before dispatch, reconcile the unresolved prior attempt and all committed/unsettled account usage, refresh the exact MiniMax route and pricing, verify available credits, and obtain an explicit user-set cap sufficient for the refreshed full reserve. Report exclusions and all failures alongside scoreable pairs.

- [Prepared 344-question manifest](evals/longbench-v2-minimax-344-prepared-2026-10-18.json)
- [Offline cost and route planning audit](evals/longbench-v2-minimax-fullsuite-offline-cost-audit-2026-10-18.json)

For new generalization evidence, use separately sourced held-out tasks with blinded answers and a frozen harness; LongBench v2's public set cannot serve as that holdout. AppWorld `test_challenge` is under consideration as an aggregate-only agent-task validation source. It has not been run; its [source review and protocol](evals/agent-holdout-source-review-2026-10-18.md) requires an aggregate-only output rehearsal before any test access and rules out task-level error analysis.

## Native-agent checks

A single accepted research-audit task and several failed or inconclusive coding-agent tasks show why span retention alone is not enough. In the accepted task, compaction preserved the checked result, but the one warm/mixed-cache run had higher TTFT and whole-task time than Full. Other development runs found selector misses, context-limit errors, and increased request counts. These are task-specific observations, not an adoption study or a general Sift-caused outcome.

See the [native-agent pilot record](evals/natural-agent-pilot-2026-10-16.md) and the [acceptance roadmap](../ROADMAP.md) for the current gates. Before claiming production readiness, Sift still needs independently authored held-out tasks, matched accepted outcomes, real-client compatibility coverage, and repeated total-cost and latency measurements.
