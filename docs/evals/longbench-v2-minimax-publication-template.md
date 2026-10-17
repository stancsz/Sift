# LongBench v2 result publication template

Use this template only after the frozen 344-task MiniMax M3 run finishes and the aggregate analyzer output has been independently checked. It is linked to manifest SHA-256 `a13822840ceeb3648be58496d9814703a02dca0f70227226a9883a34f0ed4665`. Keep all placeholders until verified results exist. This file is a reporting contract, not benchmark evidence.

## Evidence and release gate

Required inputs:

- A `complete` run with exactly 2,064 scheduled response receipts (344 tasks × two arms × three repeats).
- The exact reviewed manifest, prepare-only schedule, and runner hashes.
- OpenRouter receipts from the pinned MiniMax M3 endpoint, MiniMax provider, `minimax/fp8` route, no fallbacks, with `usage.is_byok=true` and reconciled per-request / top-level upstream costs.
- The aggregate-only analyzer output, reproduced from the saved run and manifest; no output text, prompt, answer key, account balance, or credential enters public artifacts.
- Independent review of scoring, route, usage, cost, uncertainty and timing calculations.

If a request lacks a settled cost receipt, fails route validation, loses its terminal SSE marker, exceeds a safety cap, or leaves the run incomplete, do not publish a complete comparison. Preserve the raw receipt privately and report the stop condition in the evaluation record.

## Result table contract

Populate every value from the analyzer output. Do not substitute projected values for receipts.

| Measure | Full context | Default Sift | Paired result / interpretation |
|---|---:|---:|---|
| Exact-choice correct responses | `[n/1,032]` | `[n/1,032]` | `[strict exact-choice accuracy]` |
| Valid A–D outputs | `[n/1,032]` | `[n/1,032]` | `[invalid/incomplete output counts]` |
| Task-majority accuracy (≥2 of 3) | `[n/344]` | `[n/344]` | `[Sift − Full: pp; task-cluster bootstrap 95% interval]` |
| Paired task outcomes | — | — | `[both correct / Full only / Sift only / neither]` |
| Provider prompt tokens | `[receipt total]` | `[receipt total]` | `[reduction %]` |
| Cached prompt tokens | `[receipt total and share]` | `[receipt total and share]` | `[same pinned route; describe cache treatment]` |
| MiniMax BYOK upstream cost | `[$ receipt total]` | `[$ receipt total]` | `[observed reduction %]` |
| Uncached rate reconstruction | `[$ labeled estimate]` | `[$ labeled estimate]` | `[sensitivity check only]` |
| Median / p95 TTFT | `[ms; n of 1,032]` | `[ms; n of 1,032]` | `[per-request distribution]` |
| Median / p95 request time | `[ms; n of 1,032]` | `[ms; n of 1,032]` | `[per-request distribution]` |
| Sift compaction | — | `[ms/task; n of 344; count each task once]` | `[distribution over tasks]` |
| Whole-run wall time | `[not arm-specific]` | `[not arm-specific]` | `[process start through last response]` |

The run interleaves both arms, so process wall time is a whole-run measure, not a direct Full-versus-Sift speed comparison. This QA benchmark does not measure multi-turn Codex or Claude Code task completion time.

## README copy block

Replace the brackets only after result review; retain the scope sentence beside the headline.

> **Make long-context API calls go further.** In a paired evaluation of 344 LongBench v2 tasks × 3 repeats on MiniMax M3, default Sift used **[X%] fewer provider prompt tokens** and recorded **[Y%] lower MiniMax BYOK cost** than full context. Task-majority accuracy was **[Sift]% vs [Full]%** (paired difference **[Δ] pp**, task-cluster 95% interval **[L, U] pp**). This is a post-census development result on the stated cohort, not a blind holdout or a multi-turn coding-agent speed test.

Choose only a sentence that matches the measured outcome:

- **Favorable estimate:** “Sift scored `[Δ]` percentage points higher on task-majority accuracy in this cohort.” Keep the interval and post-census limitation beside it; do not generalize beyond this run.
- **Uncertain estimate:** “The paired estimate was `[Δ]` points (95% interval `[L, U]`); this run does not establish that quality is unchanged.”
- **Lower estimate:** “Sift scored `[Δ]` points lower on task-majority accuracy in this cohort.” Show the interval and inspect the predeclared loss categories before proposing a default change.

Do not call results “quality-preserving,” “non-inferior,” “state of the art,” or a general savings guarantee. The protocol has no preregistered non-inferiority margin or power calculation; a confidence interval crossing zero is not evidence of equivalence. If a future product claim needs such a threshold, preregister a new design before collecting that evidence.

## Failure and regression review

Keep the planned cohort and denominator fixed. As a separate manual review of private receipts, triage every incorrect or unscoreable response into the mutually exclusive categories below. Apply the stated precedence and publish aggregate counts only; the analyzer does not produce this manual breakdown. Never copy answer text into the public report:

1. Incomplete generation: missing terminal marker, empty output, length-limited output, or other incomplete transport/generation. Check this category first.
2. Format miss: complete terminal response that is not exactly one trimmed uppercase letter A–D.
3. Exact-choice miss: valid terminal A–D response, but the selected option is wrong.
4. Run safety stop: route, provider, BYOK receipt, usage, cost, context, SSE termination, or spend guard failed. A safety stop invalidates a complete-run publication; it is not an incorrect answer to be hidden in the denominator.
5. Cohort exclusion: a task failed the frozen answer-blind eligibility rules before dispatch. Report counts and reasons separately; never replace an excluded task after seeing outcomes.

For any later Sift change, describe the observed failure pattern, create a separately versioned default-off candidate, obtain independent evidence-retention review, and rerun the full frozen comparison under a new manifest. Do not edit this baseline's result or combine runs with different source hashes.

## Publication checklist

- [ ] Denominators, task IDs, route, protocol and hashes match the frozen study.
- [ ] Both arms have 1,032 settled response records; all 344 task pairs have three repeats per arm.
- [ ] Strict A–D scoring and paired task-majority/bootstrap results independently reproduce.
- [ ] BYOK cost, token, cache and latency totals reconcile with receipts; reconstructions are labeled.
- [ ] README headline states the measured cohort, model, repeats, result and uncertainty together.
- [ ] The post-census/non-holdout limitation is adjacent to the result; no agent speed claim is made.
- [ ] Result and review artifacts are committed before updating the GitHub README, Awesome README, release or production materials.
