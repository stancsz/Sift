# Goal: make Sift useful, credible, and ready to adopt

## Status: active

Continue the user's full Sift improvement and release-readiness objective. The local testing and short-CI design, first-screen value, public Pages site, expanded LongBench report, and LiteLLM-free CLI are substantially implemented. Do not claim broad adoption, general agent quality, or stable readiness from those artifacts alone. Completion requires credible held-out quality evidence, usable first-run evidence, compatible clients, verified publishing controls, and a successful stable release.

## Current constraint

The product now demonstrates a measurable token/quality trade-off, but the quality evidence uses development-exposed LongBench questions and the first-run flow has no external users yet. The 344-question, three-repeat study showed 59.66% fewer provider prompt tokens while Sift scored 5.25 percentage points lower on task-majority exact choice; the task-cluster 95% interval was −10.20 to −0.29 pp. User trust and successful agent-task outcomes remain unproven. Do not spend on another MiniMax run under the prior cap: that authorization covered the completed 344-task study, and its unreceipted-attempt reserve remains in the study accounting.

## Verified state at main `033f9eb` (2026-10-20)

- **Local tests and CI:** the PR #22 candidate passed 393 tests on Python 3.13.11 in 113.25 seconds. The Python source at `29457b9` passed 397 tests locally on Python 3.14.0 in 233.02 seconds with 18 dependency warnings; offline comparison passed 100/100 Sift hits vs 0/100 head-tail hits. Docs-only PRs #28 and #29 leave that test result unchanged. PR #28's Core smoke passed in 43 seconds and its post-merge main smoke passed in 51 seconds; PR #29's Core smoke passed in 44 seconds and its post-merge main smoke passed in 51 seconds. The full multiversion CI matrix remains weekly/manual.
- **First screen and Pages:** PR #19 updated the live homepage to “Long agent history. Less context to send.” It puts token savings and the negative quality result together with sample counts and limitations. Sol's image-backed review and independent mobile QA passed desktop 1280×800 and mobile 390×844. The live page at <https://stancsz.github.io/sift/> is deployed from `76f3baf`; mobile document width is 390 px with no horizontal overflow and the CTA/trust row inside the viewport.
- **LongBench:** the analyzer independently reproduces the completed 344-question × 3-repeat exposed public study: 2,063 valid usage receipts, one Full HTTP 529 without receipt that was not retried, and 343 complete paired clusters. Full/Sift exact-choice response scores were 42.18%/40.23%; task-majority scores were 42.27%/37.03% (−5.25 pp; task-cluster 95% CI −10.20 to −0.29). Sift used 59.66% fewer provider prompt tokens and had 58.72% lower cache-sensitive receipt cost. The independent local reproduction passed 10 analyzer tests and matched $12.63322398 in settled receipt cost. These are exposed development-cohort results, not blind validation, invoices, parity, or agent-loop success.
- **Standalone CLI:** `sift serve` is LiteLLM-free and accepts Ollama or another OpenAI Chat Completions-compatible base URL. The OpenAI Python SDK→Sift→Ollama tool round-trip and LiteLLM Python client→Sift→loopback fixture smoke cover two named clients; the latter makes no inference request. PR #22 merged as `6fcec84`, and its Python 3.12 core smoke passed. More endpoint/provider combinations remain unverified.
- **Quarantine tooling:** four strict aggregate-schema checks are part of the short Python 3.12 PR smoke. The manual synthetic Docker rehearsal passed on local Windows and on ephemeral GitHub-hosted Ubuntu run [39433528577](https://github.com/stancsz/sift/actions/runs/39433528577), exporting one aggregate-safe result with zero private sentinels. This uses generated fixtures only; it is not a benchmark or held-out quality result and does not prove separate human reviewer permissions for real task data.
- **Adoption:** Public opt-in issue [#13](https://github.com/stancsz/sift/issues/13) is open with zero replies and no sessions. Its task now matches the README, discloses public comments, and remains limited to up to three inference-free opt-in sessions. No direct participant outreach or model inference is authorized by that session plan.
- **Release:** The latest GitHub release is still the v0.10.0 pre-release; PyPI's public `sift-context` endpoint returns 404. `main` now requires PRs and the `Core smoke (Python 3.12)` check, enforces the rule for admins, and requires linear history; it asks for zero approvals because `stancsz` is the sole collaborator, so this is a process gate rather than independent review. The `pypi` environment still allows admin bypass and sole-reviewer self-approval, and the active `v*` tag ruleset has an always-available owner bypass. The PyPI pending publisher remains unverified. See the [release-control audit](docs/evals/release-control-audit-2026-10-20.md). Quality, adoption, compatibility, and full release gates remain open.

PR #29 merged as `033f9eb90e01387d9afda7c711c5ab9921a08296` on 2026-10-20 and changed project-state documentation only. Its required Core smoke passed in 44 seconds; the post-merge `main` smoke passed in 51 seconds. This updates the current documentation/source pointer without extending the code-test evidence beyond `29457b9`.

## Northstar decisions (2026-10-20)

For the 2026-10-20 next-priority decision, Gemini 4 Argon recommended deterministic compatibility coverage plus refreshing recruitment and release gates. GPT-6.1 Sol gave its own verdict: prioritize the first-run usability path first because no users have tried it; then verify multiple clients and release controls. Sol agreed with scoped compatibility and claims, but rejected compatibility-first sequencing because additional integrations do not reveal user friction. The README/protocol/issue path has now shipped in PR #20; remaining first-run evidence depends on opt-in replies. This is an accountable decision informed by two reviews, not a vote. See the [attributed council summary](docs/evals/sift-advisor-council-first-run-2026-10-20.md); raw answers were not retained. Council usage: Gemini 3,347 prompt + 211 completion; Sol 821 prompt + 294 completion tokens.

After the completed LongBench analysis, a second Gemini 4 Argon → GPT-6.1 Sol council recommended preserving the negative quality result and running a blind paired multi-turn agent-task evaluation with independent acceptance scoring before selector changes. Sol advised choosing any non-inferiority margin and sample size prospectively, not adopting Gemini's illustrative two-point threshold. Decision: keep the selector unchanged, prepare the held-out benchmark and its no-inference/quarantine rehearsal first, and do not spend beyond the completed $100-capped study. The prior handoff records 3,500 Gemini and 997 Sol tokens; raw answers were not retained. Council advice is not a QA verdict or authorization to spend.

For release controls, a read-only review confirmed `stancsz` is the only GitHub collaborator. Decision: enforce a PR plus the short Core smoke on `main`, including for admins, while requiring zero approvals so the only maintainer is not blocked from merging. GitHub's up-to-date/strict check is disabled to avoid rebuilding merely because the base branch moved; this can let a PR tested against older `main` merge and reveal incompatibilities after merge. Squash and rebase remain allowed to preserve linear history. Independent review agreed this is a reversible tested-PR gate, not independent human review. The PyPI self-review/admin bypass and `v*` owner bypass remain unresolved; do not call release approval independent.

## Acceptance and next actions

1. Continue the public opt-in recruitment issue #13. If volunteers respond, run no more than three reviewed inference-free sessions using the deterministic local fixture. Record comprehension, setup friction, trust in evidence, and voluntary follow-through separately. No responses means adoption remains unvalidated; do not contact people directly.
2. Prepare a blind paired multi-turn agent-task evaluation with independently authored tasks, hidden answers, a frozen selector/harness, and independent accepted-outcome scoring. The synthetic container output-boundary component passed an independent review, but does not establish an independent operator/reviewer boundary; no held-out task source is cleared yet. A 2026-10-20 independent read-only check of AppWorld's current README and downloader found no documented split-scoped download or test-free rehearsal route; AppWorld remains parked. First establish a suitable source and the complete independent quarantine boundary. No new paid model requests are authorized by the prior cap.
3. Verify pending PyPI Trusted Publisher setup through the authenticated owner account. Resolve whether the `pypi` self-review/admin-bypass and `v*` tag-owner-bypass controls are accepted or changed; identify an independent reviewer before claiming independent release approval. Run the guarded non-publishing release rehearsal.
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
- [Merged synthetic quarantine rehearsal](https://github.com/stancsz/sift/pull/24)
- [Merged hosted rehearsal workflow](https://github.com/stancsz/sift/pull/25)
- [Merged hosted-run evidence and correction](https://github.com/stancsz/sift/pull/27)
- [Merged release-control hardening](https://github.com/stancsz/sift/pull/28)
- [Current-state documentation sync](https://github.com/stancsz/sift/pull/29)
