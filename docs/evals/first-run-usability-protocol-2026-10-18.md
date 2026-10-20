# First-run usability protocol

**Status: cleared for up to three sessions; no sessions have run.** The owner authorized recruitment on 2026-10-20. The homepage first screen was reviewed at the required viewport and is frozen to the deployed revision recorded below. The public opt-in invitation is issue #13.

This small, qualitative pilot checks whether developers with existing long-context work can understand Sift's benefit and complete its standalone Ollama quick start without coaching. It does not measure product-market fit, agent quality, production readiness, or adoption.

## Decision this study informs

Where do first-time developers get stuck or misunderstand what Sift does, and which repeated problem should be fixed before broader distribution?

## Participants and authority

- Start with up to three developers who already work with long agent histories or another long-context workflow. Three sessions are a usability screen, not a representative sample or statistical estimate.
- The project owner authorized recruitment for up to three sessions on 2026-10-20. Do not exceed that limit without renewed authorization.
- Ask participants to use synthetic or non-sensitive history. Do not record API keys, account details, proprietary prompts, or personal data. Collect anonymized task observations only.
- Use Ollama only at a loopback address (normally `http://127.0.0.1:11434/v1`). Do not configure a hosted `--base-url`, external proxy, or API key. The requested `openrouter/minimax-m3` evaluation model is not used in this usability pilot; make no paid or remote provider calls.

## Materials and setup

- Freeze the tested source commit used for the standalone CLI (use an immutable Git SHA, not a moving `main` reference) and the exact README/site instructions shown to participants. Record the commit SHA, operating system, Python version, install time, Ollama version, model and whether that model was already downloaded.
- **Reviewed homepage screen:** `https://stancsz.github.io/sift/`, deployed Pages source commit `557702a0643b6370cf1098d20a75ff2fd80abd16`, rendered at 1280×800 CSS pixels on 2026-10-20. The site files are unchanged through current `main` commit `63e4f4e8aa2ef39e8bec24c8910494d1607d86f1`. An independent reviewer judged the first screen clear enough for a 20-second comprehension task: it explains deterministic selection, exact recent turns, relevant older excerpts and the no-summary-model-call property; the illustration is marked fictional and the quality caveat is visible. This screen is frozen for the comprehension task. If any page file changes before a session, review the new rendered revision before showing it.
- Use the documented LiteLLM-free command and `examples/ollama_compaction_demo.py`. The demo is synthetic and checks whether a buried deployment setting survives compaction; it is a behavior demonstration, not evidence of general answer quality.
- Reset to a clean local environment for each session where practical. Record setup failures separately from Sift behavior and do not silently help one participant through a blocker that others must solve alone.
- Obtain consent to take notes. Do not audio/video record unless separately agreed.

## Session script

1. Before showing the page, ask: “When an agent's conversation gets long, what do you currently do?” Then show the frozen homepage first screen for 20 seconds and ask the participant to explain in their own words what Sift does, what changes in the request, and who answers the task.
2. Ask the participant to follow the Ollama quick start from the repository without coaching. Start timing when they begin. Give them up to 10 minutes to get one successful request with `x-sift-compacted=true`; this single request satisfies both completion outcomes. If blocked, record the step and their attempted recovery; then offer help so the session remains useful.
3. Ask them to describe what history they expect Sift to keep and remove, what they believe the demo proves, what it does not prove, and when they would consider trying it on their own work.
4. If they have an appropriate synthetic or non-sensitive example, ask how the demo maps to their workflow. Do not send their content to an external model or store it in the report.
5. Close by asking what felt valuable, unclear, risky, or burdensome. Do not ask for a recommendation, star, testimonial, or commitment to adopt.

## Observation record

For each session, record only:

- anonymous participant number and broad workflow description, kept only in internal notes and never cross-tabulated or published for an individual;
- environment needed to reproduce setup friction (OS, Python, Ollama/model readiness);
- elapsed time to first successful request and to confirmed compaction, or `not reached`;
- exact instruction or step where a blocker occurred, the participant's own explanation, and any help provided;
- whether they correctly describe (a) Sift selects context for a downstream agent, (b) recent turns are preserved when they fit, (c) matching older excerpts may be included, (d) some history is filtered, and (e) the synthetic demo is not quality validation;
- stated workflow relevance and unresolved concerns, clearly marked as self-report rather than observed adoption.

Do not retain raw session prompts or any identifying notes. Summarize internal results by repeated theme and participant count; report all three denominators, including incomplete sessions. Do not record verbatim explanations or publish individual rows. With only three participants, publish group-level results only when the summary cannot reasonably identify anyone; otherwise keep it internal unless each participant separately opts in to publication of an anonymized aggregate.

## Decision rules

- A blocker or misunderstanding repeated by at least two of the first three participants is a must-fix candidate. Reproduce it locally, repair it, and rerun the affected step with an independent reviewer before broadening distribution.
- A single failure within ten minutes is a signal to inspect setup conditions and instructions, not an automatic product failure; the small sample and local model downloads can dominate elapsed time.
- If two or more participants independently explain the core benefit correctly and complete the demo, treat that as evidence that the tested onboarding works for this small recruited sample only. It is not adoption, quality, cost savings, or general usability proof.
- If results split or setup conditions differ materially, run up to two additional sessions only after reviewing the discrepancy; preserve the initial three-session results and explain the selection.
- Do not change product positioning based on praise or hypothetical intent alone. Look for a specific workflow where the retained context changes what the participant would ask the downstream agent to do next.

## Report and next action

Prepare an anonymized summary with the commit, aggregate sample description, task instructions, environments, completion times, recurring blockers, comprehension outcomes, deviations, and limitations. Obtain separate opt-in consent before publishing any participant-derived summary; without it, keep the report internal. Separate observed behavior from participant opinion. The project owner decides which repeated blocker to address; the next acceptance check is a fresh unassisted session or a reproduced workflow check for that defect.

## Northstar learning

- **Method:** Observe a small number of target developers completing the real first-run path; separate observed task behavior from stated intent and adoption.
- **Trigger:** Use before broader distribution when the code path works locally but value comprehension and onboarding friction remain unverified.
- **Limits:** Local friends or volunteers can be biased; three sessions cannot establish broad demand or quality. Account for setup variability and keep session notes non-sensitive.
- **Current disposition:** Up to three sessions are authorized and the reviewed first-screen revision is recorded above. Issue #13 is open for volunteers; as of this protocol update, no participants have replied and no sessions have occurred.
