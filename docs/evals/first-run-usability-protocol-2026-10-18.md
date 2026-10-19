# First-run usability protocol

**Status: prepared, but not yet cleared for sessions; no participants recruited and no sessions run.** First-screen testing requires an independently reviewed preview of the exact page revision, and participant contact still requires owner authorization.

This small, qualitative pilot checks whether developers with existing long-context work can understand Sift's benefit and complete its standalone Ollama quick start without coaching. It does not measure product-market fit, agent quality, production readiness, or adoption.

## Decision this study informs

Where do first-time developers get stuck or misunderstand what Sift does, and which repeated problem should be fixed before broader distribution?

## Participants and authority

- Start with three developers who already work with long agent histories or another long-context workflow. Three sessions are a usability screen, not a representative sample or statistical estimate.
- Recruit only after the project owner authorizes participant contact. Do not send invitations or collect participant information before then.
- Ask participants to use synthetic or non-sensitive history. Do not record API keys, account details, proprietary prompts, or personal data. Collect anonymized task observations only.
- Use Ollama only at a loopback address (normally `http://127.0.0.1:11434/v1`). Do not configure a hosted `--base-url`, external proxy, or API key. The requested `openrouter/minimax-m3` evaluation model is not used in this usability pilot; make no paid or remote provider calls.

## Materials and setup

- Freeze the tested PR commit and the exact README/site instructions shown to participants. Record the commit SHA, operating system, Python version, install time, Ollama version, model and whether that model was already downloaded.
- For the comprehension prompt, show the opening viewport of the homepage rendered from a reviewable preview at the frozen commit, at 1280×800 CSS pixels; record its URL, commit and viewport. Do not run first-screen comprehension testing against the unrendered draft. If no reviewed preview is available, defer this measure rather than substitute the older production page.
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
- **Current disposition:** Prepared only. No outreach or sessions have occurred. Participant-contact authority and a reviewed rendered preview are still needed before sessions.
