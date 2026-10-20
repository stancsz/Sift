# Goal: make Sift useful, credible, and ready to adopt

## Status: active

Continue the user's full Sift improvement and release-readiness objective. The local testing and short-CI design, first-screen value, public Pages site, expanded LongBench report, and LiteLLM-free CLI are substantially implemented. Do not claim broad adoption, general agent quality, or stable readiness from those artifacts alone. Completion requires credible held-out quality evidence, usable first-run evidence, compatible clients, verified publishing controls, and a successful stable release.

## Current constraint

The product now demonstrates a measurable token/quality trade-off, but the quality evidence uses development-exposed LongBench questions and the first-run flow has no external users yet. The 344-question, three-repeat study showed 59.66% fewer provider prompt tokens while Sift scored 5.25 percentage points lower on task-majority exact choice; the task-cluster 95% interval was −10.20 to −0.29 pp. User trust and successful agent-task outcomes remain unproven. Do not spend on another MiniMax run under the prior cap: that authorization covered the completed 344-task study, and its unreceipted-attempt reserve remains in the study accounting.

## Verified state at main `70012d4` (2026-10-20)

- **Local tests and CI:** main's prior full suite passed 392 tests on Python 3.13.11 in 137.89 seconds. Candidate `600ef9a` passed 393 tests in 137.80 seconds with 18 dependency warnings after adding the loopback-only LiteLLM client check. PR #19's Python 3.12 smoke passed in 46 seconds; the post-merge main smoke passed in 48 seconds. PR runs intentionally skip the four-version full matrix, which runs weekly or manually.
- **First screen and Pages:** PR #19 updated the live homepage to “Long agent history. Less context to send.” It puts token savings and the negative quality result together with sample counts and limitations. Sol's image-backed review and independent mobile QA passed desktop 1280×800 and mobile 390×844. The live page at <https://stancsz.github.io/sift/> is deployed from `76f3baf`; mobile document width is 390 px with no horizontal overflow and the CTA/trust row inside the viewport.
- **LongBench:** 344 exposed public questions, three repeats per arm, 2,063 valid usage receipts, one Full HTTP 529 without receipt that was not retried. There are 343 complete paired task clusters. Full/Sift exact-choice response scores were 42.18%/40.23%; task-majority scores were 42.27%/37.03%. Sift used 59.66% fewer provider prompt tokens and had 58.72% lower cache-sensitive receipt cost. These are scoped development-cohort results, not blind validation, invoices, parity, or agent-loop success.
- **Standalone CLI:** `sift serve` is LiteLLM-free and accepts Ollama or another OpenAI Chat Completions-compatible base URL. The recorded OpenAI Python SDK→Sift→Ollama tool round-trip is joined by a LiteLLM Python client→Sift→loopback fixture smoke; the latter makes no inference call. More endpoint/provider combinations remain unverified.
- **Adoption:** Public opt-in issue [#13](https://github.com/stancsz/sift/issues/13) is open with zero replies and no sessions. Its task now matches the README, discloses public comments, and remains limited to up to three inference-free opt-in sessions. No direct participant outreach or model inference is authorized by that session plan.
- **Release:** The latest GitHub release is still the v0.10.0 pre-release; PyPI's public `sift-context` endpoint returns 404. The `pypi` environment is restricted to `main`, but its sole reviewer can self-approve and administrators can bypass. The active `v*` tag ruleset also has an always-available owner bypass; `main` has no branch-protection rule. The PyPI pending publisher remains unverified. See the [release-control audit](docs/evals/release-control-audit-2026-10-20.md). Quality, adoption, compatibility, and full release gates remain open.

## Northstar council decision (2026-10-20)

For the 2026-10-20 next-priority decision, Gemini 4 Argon recommended deterministic compatibility coverage plus refreshing recruitment and release gates. GPT-6.1 Sol gave its own verdict: prioritize the first-run usability path first because no users have tried it; then verify multiple clients and release controls. Sol agreed with scoped compatibility and claims, but rejected compatibility-first sequencing because additional integrations do not reveal user friction. The README/protocol/issue path has now shipped in PR #20; remaining first-run evidence depends on opt-in replies. This is an accountable decision informed by two reviews, not a vote. See the [attributed council summary](docs/evals/sift-advisor-council-first-run-2026-10-20.md); raw answers were not retained. Council usage: Gemini 3,347 prompt + 211 completion; Sol 821 prompt + 294 completion tokens.

## Acceptance and next actions

1. README and protocol now describe the checkout prerequisite, separate terminal commands, actual successful demo output, and public issue privacy boundary. Refresh issue #13 after merge to match these instructions and deployed `76f3baf`; do not imply the fixture tests answer quality.
2. Run up to three sessions only if volunteers opt in. Record completion, comprehension, friction, and voluntary follow-through separately; no respondents means the adoption gate remains unresolved.
3. Prepare independent held-out agent-task evidence with blinded answers and accepted-outcome scoring. Reuse AppWorld only after a test-free aggregate-output quarantine rehearsal is independently accepted; otherwise author synthetic, nonproprietary tasks. Do no paid inference until the user authorizes a new bounded study.
4. Add deterministic compatibility evidence for at least two named supported clients, including OpenAI Python SDK and one independent client path, without broadening the advertised API contract silently.
5. Verify pending Trusted Publisher setup in the authenticated PyPI account. Decide whether to eliminate self-approval/owner bypass and add `main` branch protection or explicitly accept those controls. Run a non-publishing release rehearsal; publish a stable package/release only after the quality, compatibility, adoption disposition, and full release checks pass.
6. Keep the goal, roadmap, evaluation record, README, Pages content, and recruitment issue consistent with current deployed evidence. Continue until the stable Sift release and required evidence are verified.

## Durable evidence

- [Current handoff](handoff.md)
- [Adoption roadmap](ROADMAP.md)
- [Evaluation record](docs/evaluation.md)
- [Release instructions](docs/releasing.md)
- [First-run usability protocol](docs/evals/first-run-usability-protocol-2026-10-18.md)
- [First-run Advisor council summary](docs/evals/sift-advisor-council-first-run-2026-10-20.md)
- [Release-control audit](docs/evals/release-control-audit-2026-10-20.md)
- [Merged first-screen change](https://github.com/stancsz/sift/pull/19)
