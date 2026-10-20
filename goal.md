# Goal: make Sift useful, credible, and ready to adopt

## Status: active

Continue the user's full Sift improvement and release-readiness objective. The local testing and short-CI design, first-screen value, public Pages site, expanded LongBench report, and LiteLLM-free CLI are substantially implemented. Do not claim broad adoption, general agent quality, or stable readiness from those artifacts alone. Completion requires credible held-out quality evidence, usable first-run evidence, compatible clients, verified publishing controls, and a successful stable release.

## Current constraint

The product now demonstrates a measurable token/quality trade-off, but the quality evidence uses development-exposed LongBench questions and the first-run flow has no external users yet. The 344-question, three-repeat study showed 59.66% fewer provider prompt tokens while Sift scored 5.25 percentage points lower on task-majority exact choice; the task-cluster 95% interval was −10.20 to −0.29 pp. User trust and successful agent-task outcomes remain unproven. Do not spend on another MiniMax run under the prior cap: that authorization covered the completed 344-task study, and its unreceipted-attempt reserve remains in the study accounting.

## Verified state at main `6fcec84` (2026-10-20)

- **Local tests and CI:** the PR #22 candidate (same source content as merge `6fcec84`) passed the full local suite: 393 tests on Python 3.13.11 in 113.25 seconds with 18 dependency warnings. Its Python 3.12 Core smoke passed in 46 seconds. The full CI matrix was skipped on this PR by design and remains weekly/manual.
- **First screen and Pages:** PR #19 updated the live homepage to “Long agent history. Less context to send.” It puts token savings and the negative quality result together with sample counts and limitations. Sol's image-backed review and independent mobile QA passed desktop 1280×800 and mobile 390×844. The live page at <https://stancsz.github.io/sift/> is deployed from `76f3baf`; mobile document width is 390 px with no horizontal overflow and the CTA/trust row inside the viewport.
- **LongBench:** the analyzer independently reproduces the completed 344-question × 3-repeat exposed public study: 2,063 valid usage receipts, one Full HTTP 529 without receipt that was not retried, and 343 complete paired clusters. Full/Sift exact-choice response scores were 42.18%/40.23%; task-majority scores were 42.27%/37.03% (−5.25 pp; task-cluster 95% CI −10.20 to −0.29). Sift used 59.66% fewer provider prompt tokens and had 58.72% lower cache-sensitive receipt cost. The independent local reproduction passed 10 analyzer tests and matched $12.63322398 in settled receipt cost. These are exposed development-cohort results, not blind validation, invoices, parity, or agent-loop success.
- **Standalone CLI:** `sift serve` is LiteLLM-free and accepts Ollama or another OpenAI Chat Completions-compatible base URL. The OpenAI Python SDK→Sift→Ollama tool round-trip and LiteLLM Python client→Sift→loopback fixture smoke cover two named clients; the latter makes no inference request. PR #22 merged as `6fcec84`, and its Python 3.12 core smoke passed. More endpoint/provider combinations remain unverified.
- **Adoption:** Public opt-in issue [#13](https://github.com/stancsz/sift/issues/13) is open with zero replies and no sessions. Its task now matches the README, discloses public comments, and remains limited to up to three inference-free opt-in sessions. No direct participant outreach or model inference is authorized by that session plan.
- **Release:** The latest GitHub release is still the v0.10.0 pre-release; PyPI's public `sift-context` endpoint returns 404. The `pypi` environment is restricted to `main`, but its sole reviewer can self-approve and administrators can bypass. The active `v*` tag ruleset also has an always-available owner bypass; `main` has no branch-protection rule. The PyPI pending publisher remains unverified. See the [release-control audit](docs/evals/release-control-audit-2026-10-20.md). Quality, adoption, compatibility, and full release gates remain open.

## Northstar decisions (2026-10-20)

For the 2026-10-20 next-priority decision, Gemini 4 Argon recommended deterministic compatibility coverage plus refreshing recruitment and release gates. GPT-6.1 Sol gave its own verdict: prioritize the first-run usability path first because no users have tried it; then verify multiple clients and release controls. Sol agreed with scoped compatibility and claims, but rejected compatibility-first sequencing because additional integrations do not reveal user friction. The README/protocol/issue path has now shipped in PR #20; remaining first-run evidence depends on opt-in replies. This is an accountable decision informed by two reviews, not a vote. See the [attributed council summary](docs/evals/sift-advisor-council-first-run-2026-10-20.md); raw answers were not retained. Council usage: Gemini 3,347 prompt + 211 completion; Sol 821 prompt + 294 completion tokens.

After the completed LongBench analysis, a second Gemini 4 Argon → GPT-6.1 Sol council recommended preserving the negative quality result and running a blind paired multi-turn agent-task evaluation with independent acceptance scoring before selector changes. Sol advised choosing any non-inferiority margin and sample size prospectively, not adopting Gemini's illustrative two-point threshold. Decision: keep the selector unchanged, prepare the held-out benchmark and its no-inference/quarantine rehearsal first, and do not spend beyond the completed $100-capped study. The prior handoff records 3,500 Gemini and 997 Sol tokens; raw answers were not retained. Council advice is not a QA verdict or authorization to spend.

## Acceptance and next actions

1. Continue the public opt-in recruitment issue #13. If volunteers respond, run no more than three reviewed inference-free sessions using the deterministic local fixture. Record comprehension, setup friction, trust in evidence, and voluntary follow-through separately. No responses means adoption remains unvalidated; do not contact people directly.
2. Prepare a blind paired multi-turn agent-task evaluation with independently authored tasks, hidden answers, a frozen selector/harness, and independent accepted-outcome scoring. The synthetic container output-boundary component passed an independent review, but does not establish an independent operator/reviewer boundary; no held-out task source is cleared yet. AppWorld stays parked until a test-free route and the complete quarantine boundary are independently verified. No new paid model requests are authorized by the prior cap.
3. Verify pending PyPI Trusted Publisher setup through the authenticated owner account. Resolve whether the self-review/admin-bypass and tag-owner-bypass controls are accepted or changed, and establish or explicitly accept the lack of `main` branch protection. Run the guarded non-publishing release rehearsal.
4. Keep the README, live Pages, evaluation, recruitment issue and Northstar records aligned with measured evidence. Publish a stable package and GitHub release only after held-out quality, adoption disposition, compatibility and full release checks are resolved.

## Durable evidence

- [Current handoff](handoff.md)
- [Adoption roadmap](ROADMAP.md)
- [Evaluation record](docs/evaluation.md)
- [Release instructions](docs/releasing.md)
- [First-run usability protocol](docs/evals/first-run-usability-protocol-2026-10-18.md)
- [First-run Advisor council summary](docs/evals/sift-advisor-council-first-run-2026-10-20.md)
- [Release-control audit](docs/evals/release-control-audit-2026-10-20.md)
- [Merged first-screen change](https://github.com/stancsz/sift/pull/19)
- [Merged LiteLLM client compatibility smoke](https://github.com/stancsz/sift/pull/22)
