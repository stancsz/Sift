# Agent-task holdout source review · 2026-10-18

## Decision

AppWorld `test_challenge` is the preferred candidate for a separate, agent-task validation track. It is not yet approved for execution. Its benchmark rules make this an aggregate-only evaluation: do not inspect test tasks, task-level outputs, task-specific reports, or errors, and do not tune against them. Therefore this source cannot support paired per-task analysis, failure diagnosis, or a non-inferiority claim under the current rules.

Keep this track separate from LongBench v2. LongBench is exposed development evidence; expanding it does not make it a holdout.

## Source assessment

The AppWorld paper and official repository describe 750 simulated multi-app tasks across nine apps and 457 APIs. The benchmark has `train`, `dev`, `test_normal`, and `test_challenge` splits, with `test_challenge` as the more difficult test subset. For test splits, evaluator-only initial-state setup/construction and written solutions are withheld, while task instructions are supplied to the agent during evaluation. Evaluation programs are available through the encrypted protected package. The benchmark rules permit test splits only for testing an agent and obtaining aggregate scores; they prohibit inspecting test tasks or task-wise reports, error analysis, and tuning.

The official README also makes the stock output boundary unsuitable without a wrapper: `AppWorld` creates task-specific output directories, and its documented evaluator writes a JSON report with an `individual` map keyed by task ID plus per-task Markdown reports containing pass/fail details and assertion traces. Task output directories can also contain checkpoints, database diffs, execution I/O, API-call logs, and version metadata. The stock runner therefore does not itself enforce aggregate-only access. This is a source-level finding, not a completed quarantine rehearsal; no AppWorld package, dataset, or test task has been loaded in this project.

The protected benchmark data is encrypted, and its license places conditions on public redistribution of plaintext protected material and derivatives.

This makes AppWorld a useful operational holdout candidate if the evaluation is run under its exact rules. It does not establish that model weights have never seen related tasks, nor does it create a privately authored benchmark.

Primary sources:

- [AppWorld paper (ACL 2024)](https://aclanthology.org/2024.acl-long.850/)
- [Official AppWorld repository, output layout, evaluator reports, and benchmark rules](https://github.com/StonyBrookNLP/appworld/blob/main/README.md)

## Frozen protocol before any test access or provider call

1. Record the Sift commit, AppWorld release, model route, agent/runtime versions, prompt, tool permissions, task timeout, retry rules, and all non-test configuration. Freeze the harness before loading `test_challenge`.
2. Compare Full context and Sift with the same model, task setup, tools, budgets, and execution settings. Randomize arm order where execution permits. Treat the benchmark's allowed aggregate score as the primary outcome.
3. Evaluate the complete permitted split under AppWorld's official runner, but only through an independently reviewed wrapper/quarantine. Do not choose tasks based on length, expected Sift-trigger coverage, or any other test-task-specific property. Count every official task in the denominator; if tasks fail or time out, follow the official scoring and report aggregate completion/score only.
4. Keep task IDs, trajectories, per-task grades, model outputs, and error reports sealed from analysis. Do not print, browse, or retain plaintext protected benchmark materials beyond the official runner's required handling. Do not redistribute them.
5. Report the aggregate Full and Sift scores, the benchmark-defined aggregate difference if available, resource totals, and run coverage. State that AppWorld rules prohibit task-level error analysis, so no paired task-level uncertainty or quality-parity conclusion is available from this run.
6. Do not tune Sift, prompts, selectors, budgets, or retries against `test_challenge`. Any change after test access invalidates this evaluation as a fresh holdout result.

## Provider and release gates

- Any model-backed run must use `openrouter/minimax-m3`, pin the intended MiniMax provider, disable fallbacks, refresh live route and prices, reconcile unresolved prior usage and account-wide committed spend, and obtain a fresh explicit numeric cap that covers the refreshed reserve. No provider call is authorized by this source review.
- Before any `test_challenge` access, run a non-test integration rehearsal using synthetic or permitted non-test tasks through the exact official-runner and harness path. Prove that task IDs and all task-level files, reports, and logs are inaccessible to the evaluation operator/reviewers and analysis workflow; suppress runner/agent stdout and stderr from public or analysis outputs, while allowing only the task instruction and live tool responses required for the run to reach the agent. Isolate persistent project artifacts, and allow only a documented aggregate allowlist to leave the quarantine. The rehearsal must not load AppWorld test data. The official README documents per-task outputs and task-keyed evaluator details, so the stock runner must not be treated as aggregate-only. Build and independently review an aggregate-only wrapper/quarantine first; if that boundary cannot be demonstrated without accessing test reports, stop and choose another benchmark.
- Have an independent reviewer inspect the protocol and output boundary before execution. Preserve raw protected outputs only as permitted by AppWorld's official runner and license; publish only allowed aggregates.
- Do not put AppWorld test details or a claim of held-out validation on the website until a compliant run succeeds and its aggregate artifact has been independently reviewed.

## Remaining limitations

The aggregate-only policy prevents diagnosis of why Sift helps or harms individual tasks. It also prevents a paired non-inferiority analysis. The benchmark is public and encrypted test data is operationally protected, but this cannot rule out pretraining exposure. A later, separately authored, privately held task set could complement AppWorld if its creators, scoring rules, and access controls are established before evaluation.
