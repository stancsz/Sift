# Evaluation record

Sift is still a preview. These checks show what it currently does on selected tests and public development tasks; they do not establish broad agent quality, user adoption, or a general cost or speed improvement.

## Local verification

The full local suite passed **387 tests on Python 3.14 in 113.62 seconds**, with 17 dependency warnings, using the worktree's `.venv-local-qa` environment. Run it with `python -m pytest tests -q`; install `.[litellm,test]` first in a clean environment. This run includes focused regression tests for the MiniMax per-attempt unknown-outcome guard, single-use continuation, and split-report LongBench analyzer. An isolated Ubuntu/Python 3.12 container at code-bearing PR head `6b317c8` previously passed all 370 tests in 83.59 seconds; its offline authored comparison returned 100/100 Sift hits and 0/100 head/tail hits. Earlier full suites passed on Python 3.11.14, 3.12, 3.13, and 3.14. The current CI design runs a short Python 3.12 core smoke on every push and pull request; PR #16's [core smoke](https://github.com/stancsz/sift/actions/runs/39414387805) passed in 46 seconds, while its full-suite job was skipped by design. The full multiversion suite and offline comparison remain weekly/manual to limit routine PR CI time. These are software checks, not model-quality evidence. The earlier [failure #39077270041](https://github.com/stancsz/sift/actions/runs/39077270041) came from a workflow that omitted the pytest extra and a test that opened an untracked LongBench result file; the current workflow installs both `litellm` and `test` extras.

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

### Broader LongBench v2 cohort (344 questions; completed)

The frozen schedule sampled 344 questions selected by a historical modeled paired-fit screen from the same public 503-question set, with three repeats per arm (2,064 planned requests). The questions and labels were exposed during development; this is not a blind holdout. The run produced 2,063 valid provider usage receipts. One Full-context request returned HTTP 529 without a receipt; it was never retried. Settled receipt cost was $12.633224 across both arms, not an invoice-verified amount.

Quality comparisons use the 343 task clusters with three receipted responses in each arm (1,029 responses per arm). Exact answers were Full 434/1,029 (42.18%) and Sift 414/1,029 (40.23%), a −1.94-point response-level difference. By task majority, Full was correct on 145/343 questions (42.27%) and Sift on 127/343 (37.03%), a −5.25-point difference. The paired table was 100 both-correct, 45 Full-only, 27 Sift-only, and 171 neither. A deterministic 20,000-resample task-cluster bootstrap gives a 95% interval of −10.20 to −0.29 points for Sift minus Full. The interval is specific to this exposed cohort; it does not establish a general effect or performance on agent tasks. The 344th cluster is excluded from paired quality because its Full arm lacks a usage receipt.

Across all receipted requests, provider-reported prompt usage was 66,007,295 tokens for Full and 26,628,470 for Sift (59.66% fewer); receipt cost was $8.942262 and $3.690962 respectively (58.72% lower). These BYOK cost fields are cache-sensitive usage receipts, not an invoice. Thirty-five outputs ended at the length limit; invalid and incomplete choices count as incorrect. The 13 historical unreceipted attempts across the three audited report families were reserved separately for the user's cap; the reserve does not change this study's settled receipt total. Do not combine these rows with other LongBench samples.

The raw report and model responses remain private under `.runs`. The paid continuation skipped the HTTP 529, used a fixed single-use output and claim, and completed the remaining 1,522 requests. The dated $100 cap covered prior settled spend and all 13 unknown-attempt reserves; the MiniMax account balance itself was not observable in the BYOK preflight.

The checked-in strict analyzer validates the refreshed manifest, stopped prefix, and continuation directly. It reconciles all 2,063 successful receipts and total settled cost, excludes the unreceipted 529 from quality, and pairs the remaining 343 complete task clusters. The result file records the manifest and private input hashes.

To reproduce locally, retain the two private reports under `.runs` and run:

```sh
python benchmarks/analyze_longbench_v2_minimax_paired_344.py \
  --prefix .runs/longbench-v2-minimax-344-stage-run-prepared-20261020.json \
  --continuation .runs/longbench-v2-minimax-344-continuation-2026-10-20.json \
  --manifest docs/evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json \
  --output .runs/longbench-v2-minimax-344-analysis.json
```

This analysis is offline and makes no model requests. It emits aggregate statistics only; keep the source reports and generated output under `.runs` rather than publishing them.

- [Frozen 344-question manifest](evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json)
- [Current route snapshot](evals/longbench-v2-openrouter-minimax-m3-endpoints-2026-10-20T0750Z.json)
- [Sanitized aggregate result and private source-report hashes](results/longbench-v2-minimax-344-aggregate-2026-10-20.json)

### 950K-token Subroute cost probe (one request per model)

A synthetic archive of 950,401 locally estimated input tokens was compacted to 32,698 estimated tokens. Sifted requests were then sent through an isolated Subroute staging instance to GPT-6 Astra and Gemini 4 Argon. Both returned the queried fact. Astra's Subroute usage ledger recorded 32,502 input and 6 output tokens; Gemini reported 37,003 input and 41 output tokens. The different input counts reflect each model's tokenizer and request framing.

The full-context requests were rejected by the current subscription adapters before inference. Therefore, the “without Sift” amounts below are uncached public API rate equivalents for 950,401 input tokens plus the observed output length; they are not measured full-context calls. “With Sift” applies the same public rates to actual Subroute usage receipts. Neither amount is a subscription charge or provider invoice.

| Model | No-Sift API-rate equivalent | Sifted usage receipt | With-Sift API-rate equivalent | Modeled reduction |
|---|---:|---:|---:|---:|
| GPT-6 Astra | $19.008470 | 32,502 input / 6 output | $0.325320 | 98.3% |
| Gemini 4 Argon | $1.901212 | 37,003 input / 41 output | $0.074416 | 96.1% |

- [Probe method, route limits, and rate assumptions](evals/subroute-950k-token-cost-probe-2026-10-20.md)
- [Sanitized aggregate results](results/subroute-950k-token-cost-probe-2026-10-20.json)

For new generalization evidence, use separately sourced held-out tasks with blinded answers and a frozen harness; LongBench v2's public set cannot serve as that holdout. AppWorld `test_challenge` is parked, not run: its official runner writes a task-ID keyed evaluator JSON map and per-task reports with assertion details, and the public data download is bundle-wide rather than split-scoped. The [source review and frozen protocol](evals/agent-holdout-source-review-2026-10-18.md) require an independently reviewed output quarantine rehearsal before any test access and rule out task-level error analysis. No bundle was downloaded; resume only if a verified test-free rehearsal path becomes available.

## Native-agent checks

A single accepted research-audit task and several failed or inconclusive coding-agent tasks show why span retention alone is not enough. In the accepted task, compaction preserved the checked result, but the one warm/mixed-cache run had higher TTFT and whole-task time than Full. Other development runs found selector misses, context-limit errors, and increased request counts. These are task-specific observations, not an adoption study or a general Sift-caused outcome.

See the [native-agent pilot record](evals/natural-agent-pilot-2026-10-16.md) and the [acceptance roadmap](../ROADMAP.md) for the current gates. Before claiming production readiness, Sift still needs independently authored held-out tasks, matched accepted outcomes, real-client compatibility coverage, and repeated total-cost and latency measurements.
