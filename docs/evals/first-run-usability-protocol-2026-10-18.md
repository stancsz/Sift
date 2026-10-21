# First-run usability protocol

**Status: recruitment authorized for up to three sessions; no sessions have run.** The owner authorized recruitment on 2026-10-20. The homepage first screen was independently reviewed at the required viewports and is frozen to the deployed revision recorded below. The public opt-in invitation is issue #13. The deterministic fixture and proxy/redirect guards passed independent security review before PR #18 merged; the current main revision is `76f3baf8ad71a7259fd97c34ba0059ac2ce31a27`.

This small, qualitative pilot checks whether developers with existing long-context work can understand Sift's benefit and complete a standalone CLI compaction request without coaching. The request goes through a deterministic loopback stub: no model is started or called, including Ollama. This pilot does not measure Ollama setup success, model answer quality, product-market fit, production readiness, or adoption.

## Decision this study informs

Where do first-time developers get stuck or misunderstand what Sift does, and which repeated problem should be fixed before broader distribution?

## Participants and authority

- Start with up to three developers who already work with long agent histories or another long-context workflow. Three sessions are a usability screen, not a representative sample or statistical estimate.
- The project owner authorized recruitment for up to three sessions on 2026-10-20. Do not exceed that limit without renewed authorization.
- Ask participants to use only the bundled synthetic history. Do not record API keys, account details, proprietary prompts, or personal data. Collect anonymized task observations only.
- Feedback on public issue #13 is optional; anyone posting there should know GitHub comments are public under their account. Ask participants to share only a completion status and broad workflow/step category, never logs, prompts, names, or private account information.
- The CLI's only upstream for this pilot is the deterministic fixture at `http://127.0.0.1:4020/v1`. Do not configure a hosted `--base-url`, external proxy, API key, Ollama model, or other model. The requested `openrouter/minimax-m3` evaluation model is not used; make no inference, paid, or remote provider calls.

## Materials and setup

- Use a merged source revision containing the checkout-local virtual-environment and module-invocation instructions below (runtime/package baseline `e19828a40a3dbbeb652bcdc7bd2fedade5fefd16`). Before any session, freeze the exact source commit and README/site revisions shown to that participant. Record the commit SHA, operating system, Python version, and install time. Do not collect Ollama/model details because no model is used.
- **Reviewed homepage screen:** `https://stancsz.github.io/sift/`, deployed Pages source commit `76f3baf8ad71a7259fd97c34ba0059ac2ce31a27`, rendered at 1280×800 and 390×844 CSS pixels on 2026-10-20. Sol's image-backed final review and an independent mobile review cleared the screen: the headline names long agent histories, the mechanism and caveat are visible, and the first-screen evidence pairs 59.66% fewer provider prompt tokens with a −5.25 pp task-majority score vs Full, sample counts, and exposed-question limitations. The “Try it locally” action and trust row fit on mobile. Live mobile layout has no horizontal overflow. This is the screen frozen for the 20-second comprehension task. If any page file changes before a session, review the new rendered revision before showing it.
- Use the [README's platform-specific no-inference setup](../../README.md#no-model-local-setup): clone if needed, create/install the checkout-local `.venv`, and use that explicit interpreter in both terminals without activation. Start `sift.cli serve` in terminal 1 and run `-m examples.no_inference_compaction_demo` from the same repository root in terminal 2. This avoids relying on a globally installed Sift or incidental import paths. The fixture binds to loopback, checks whether the buried deployment setting survived compaction, and returns fixed text. A successful run prints that Sift compacted the request and that the fixture found the buried setting. This checks the actual Sift request path without model inference; it is not evidence of general answer quality or Ollama compatibility. Participants may read the Ollama instructions, but must not run an Ollama request.
- Reset to a clean local environment for each session where practical. Record setup failures separately from Sift behavior and do not silently help one participant through a blocker that others must solve alone.
- Obtain consent to take notes. Do not audio/video record unless separately agreed.

## Session script

1. Before showing the page, ask: “When an agent's conversation gets long, what do you currently do?” Then show the frozen homepage first screen for 20 seconds and ask the participant to explain in their own words what Sift does, what changes in the request, and who answers the task.
2. Ask the participant to follow the no-inference README setup without coaching. Start timing when they begin. Give them up to 10 minutes to get one request with `x-sift-compacted=true` and the fixture's buried-setting confirmation. This checks Sift's own compaction and routing path, not a model answer. If blocked, record the step and their attempted recovery; then offer help so the session remains useful. Do not start or call Ollama.
3. Ask the participant: “What stayed exact, what older content was selected, and what condition makes Sift refuse? What did the deterministic fixture not prove?” Then ask when they would consider trying Sift with an inference backend on their own work.
4. If they have an appropriate synthetic or non-sensitive example, ask how the demo maps to their workflow. Do not send their content to an external model or store it in the report.
5. Close by asking what felt valuable, unclear, risky, or burdensome. Do not ask for a recommendation, star, testimonial, or commitment to adopt.

## Observation record

For each session, record only:

- anonymous participant number and broad workflow description, kept only in internal notes and never cross-tabulated or published for an individual;
- environment needed to reproduce setup friction (OS and Python; no model or Ollama readiness is required);
- elapsed time to first successful request and to confirmed compaction, or `not reached`;
- the step where a blocker occurred, a brief paraphrase of the participant's explanation, and any help provided; do not capture exact wording;
- structured yes/no/partial comprehension marks for whether they understand (a) Sift selects context for a downstream agent, (b) recent turns are preserved when they fit, (c) matching older excerpts may be included, (d) some history is filtered, and (e) the deterministic stub confirms forwarding only, not model answer quality;
- stated workflow relevance and unresolved concerns, clearly marked as self-report rather than observed adoption.

Do not retain raw session prompts or any identifying notes. Summarize internal results using structured marks and paraphrased themes with participant counts; report all three denominators, including incomplete sessions. Never record verbatim explanations or publish individual rows. With only three participants, publish group-level results only when the summary cannot reasonably identify anyone; otherwise keep it internal unless each participant separately opts in to publication of an anonymized aggregate.

## Engineering verification

**Engineering check (2026-10-21):** An independent fresh Windows environment
verified the revised README sequence without activation, global Sift or
inherited Python paths. The previous direct-script invocation failed on its
example import; the documented module invocation passed the real proxy and
deterministic fixture, reducing 4,613 estimated units to 1,982 while retaining
the buried setting. POSIX instructions received text review only. This is
engineering verification, not a volunteer session or adoption result. See the
[scoped result](../results/no-inference-first-run-2026-10-21.json).

## Decision rules

- A blocker or misunderstanding repeated by at least two of the first three participants is a must-fix candidate. Reproduce it locally, repair it, and rerun the affected step with an independent reviewer before broadening distribution.
- A single failure within ten minutes is a signal to inspect setup conditions and instructions, not an automatic product failure; the small sample and Python, virtual-environment, or package setup can dominate elapsed time.
- If two or more participants independently explain the core benefit correctly and complete the no-inference demo, treat that as evidence that the tested onboarding and compaction path work for this small recruited sample only. It is not adoption, model quality, cost savings, Ollama compatibility, or general usability proof.
- If results split or setup conditions differ materially, preserve the results and review the discrepancy. The current authorization is at most three sessions total; any additional sessions require separate authorization before recruitment or execution.
- Do not change product positioning based on praise or hypothetical intent alone. Look for a specific workflow where the retained context changes what the participant would ask the downstream agent to do next.

## Report and next action

Prepare an anonymized summary with the commit, aggregate sample description, task instructions, environments, completion times, recurring blockers, comprehension outcomes, deviations, and limitations. Obtain separate opt-in consent before publishing any participant-derived summary; without it, keep the report internal. Separate observed behavior from participant opinion. The project owner decides which repeated blocker to address; the next acceptance check is a fresh unassisted session or a reproduced workflow check for that defect.

## Northstar learning

- **Method:** Observe a small number of target developers completing the real first-run path; separate observed task behavior from stated intent and adoption.
- **Trigger:** Use before broader distribution when the code path works locally but value comprehension and onboarding friction remain unverified.
- **Limits:** Local friends or volunteers can be biased; three sessions cannot establish broad demand or quality. Account for setup variability and keep session notes non-sensitive.
- **Current disposition:** Up to three sessions are authorized and the reviewed first-screen revision is recorded above. Issue #13 is open for volunteers; as of 2026-10-20, no participants have replied and no sessions have occurred. Keep its task steps in sync with this protocol and disclose that issue comments are public under the poster's account. No logs, prompts, or identifying details should be posted.
