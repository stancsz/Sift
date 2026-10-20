# Evaluation record

Sift is still a preview. These checks show what it currently does on selected tests and public development tasks; they do not establish broad agent quality, user adoption, or a general cost or speed improvement.

## Local verification

The full local suite passed **383 tests on Python 3.14 in 114.90 seconds**, with 17 dependency warnings, using the worktree's `.venv-local-qa` environment. Run it with `python -m pytest tests -q`; install `.[litellm,test]` first in a clean environment. This run includes focused regression tests for the MiniMax unknown-outcome guard and single-use continuation. An isolated Ubuntu/Python 3.12 container at code-bearing PR head `6b317c8` previously passed all 370 tests in 83.59 seconds; its offline authored comparison returned 100/100 Sift hits and 0/100 head/tail hits. Earlier full suites passed on Python 3.11.14, 3.12, 3.13, and 3.14. The current CI design runs a short Python 3.12 core smoke on every push and pull request; its [exact-head run for PR #7](https://github.com/stancsz/sift/actions/runs/39272382994) passed in 29 seconds. The full multiversion suite and offline comparison remain weekly/manual to limit routine PR CI time. These are software checks, not model-quality evidence. The earlier [failure #39077270041](https://github.com/stancsz/sift/actions/runs/39077270041) came from a workflow that omitted the pytest extra and a test that opened an untracked LongBench result file; the current workflow installs both `litellm` and `test` extras.

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

### Broader 344-question cohort (partial; stopped safely)

The frozen schedule covers 344 questions selected by a historical modeled paired-fit screen from the same public 503-question set, with three repeats per arm (2,064 planned generations). Questions and labels were already exposed during development; this is not a holdout. The run stopped after 542 requests when a Full-context request returned HTTP 529 without a valid usage/cost receipt. No retry was sent. It contains 541 receipted responses and one unresolved provider outcome; receipt spend is $3.58631898, not invoice-verified.

At this checkpoint, 90 task clusters have all three responses in both arms (270 responses per arm). Full scored 110/270 (40.74%) and Sift 122/270 (45.19%), an observed +4.44 percentage-point difference. An approximate task-cluster 95% interval is −3.26 to +12.15 points; this does not demonstrate a reliable quality improvement or parity. Nine outputs ended at the length limit and strict-choice scoring counts invalid/truncated choices as incorrect. Within these 90 matched clusters, provider prompt usage was 17,275,101 tokens for Full and 7,041,707 for Sift (−59.24%); OpenRouter BYOK receipt costs were $2.490294 and $1.087784 (−56.32%). Receipt cost is cache-sensitive and is not an invoice amount. These partial-prefix results are exploratory and must not be combined with other LongBench samples.

The run report and answer text remain private under `.runs`. Five requests have unresolved provider usage across this and the earlier run. The runner now requires both exact private reports, reconstructs the complete schedule and receipted prefix, and reserves each unknown request at the maximum dated provider prompt limit plus the 64-token output cap: current worst-case unknown exposure is $0.786816 at the pinned rates. Its only continuation is a single-use, fixed-output suffix of 1,522 jobs; it permanently skips the HTTP 529 request and includes the prior $3.586319 receipts in per-request cap accounting. The local claim file must be preserved to prevent replay. A read-only OpenRouter refresh on 2026-10-20 confirmed the same MiniMax M3 route and pinned $0.30/$1.20 per-million rates; MiniMax account balance is not observable in this BYOK preflight. The user's $100 aggregate study cap includes prior spend and unknown reserves.

- [Frozen 344-question manifest](evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json)
- [Current route snapshot](evals/longbench-v2-openrouter-minimax-m3-endpoints-2026-10-20T0750Z.json)

The prepared manifest's older $41.865635 reserve used dated rates and is not a current quote, completed-run cost, or authorization. Before any further dispatch, refresh the exact MiniMax route/pricing and account state; include all historical unresolved exposure in the user-authorized $100 cap. Report exclusions, missing jobs, and all failures alongside scoreable pairs.

- [Prepared 344-question manifest](evals/longbench-v2-minimax-344-prepared-2026-10-18.json)
- [Offline cost and route planning audit](evals/longbench-v2-minimax-fullsuite-offline-cost-audit-2026-10-18.json)

For new generalization evidence, use separately sourced held-out tasks with blinded answers and a frozen harness; LongBench v2's public set cannot serve as that holdout. AppWorld `test_challenge` is parked, not run: its official runner writes a task-ID keyed evaluator JSON map and per-task reports with assertion details, and the public data download is bundle-wide rather than split-scoped. The [source review and frozen protocol](evals/agent-holdout-source-review-2026-10-18.md) require an independently reviewed output quarantine rehearsal before any test access and rule out task-level error analysis. No bundle was downloaded; resume only if a verified test-free rehearsal path becomes available.

## Native-agent checks

A single accepted research-audit task and several failed or inconclusive coding-agent tasks show why span retention alone is not enough. In the accepted task, compaction preserved the checked result, but the one warm/mixed-cache run had higher TTFT and whole-task time than Full. Other development runs found selector misses, context-limit errors, and increased request counts. These are task-specific observations, not an adoption study or a general Sift-caused outcome.

See the [native-agent pilot record](evals/natural-agent-pilot-2026-10-16.md) and the [acceptance roadmap](../ROADMAP.md) for the current gates. Before claiming production readiness, Sift still needs independently authored held-out tasks, matched accepted outcomes, real-client compatibility coverage, and repeated total-cost and latency measurements.
