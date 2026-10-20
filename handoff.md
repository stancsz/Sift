# Sift Northstar handoff — 2026-10-20

## Owner and current checkout

The top-level goal remains active in [goal.md](goal.md). Current integration checkout: branch `codex/northstar-goals`, based on `origin/main` at `76f3baf8ad71a7259fd97c34ba0059ac2ce31a27`. This turn is reconciling stale operating records and advancing the first-run adoption path. Do not stage private `.runs`, credentials, responses, or participant data.

## Verified delivery since the previous handoff

- PR #19, merged at `76f3baf`, revised the homepage first screen with a concrete coding/research context-crowding use case and an adjacent, qualified token/quality evidence card. Pages deployment run `39425862451` succeeded. The live page is <https://stancsz.github.io/sift/>.
- Final Sol image review passed actual 1280×800 desktop and 390×844 mobile renders. It requested larger evidence labels/caveat text; those were enlarged and returned to the same Sol reviewer, who passed the revised views. Independent mobile reviewer marked READY. Live mobile DOM: `scrollWidth=390`, evidence card ends at y=601, CTA at y=616–664, trust row ends y=702.
- Current full local suite: 392 passed on Python 3.13.11 in 137.89 seconds, 17 dependency warnings. PR #19's Python 3.12 smoke passed in 46 seconds; post-merge main smoke passed in 48 seconds. The CI full matrix is weekly/manual and was skipped for PR #19 by design.
- PRs #17–19 are merged: strict LongBench analyzer, deterministic no-inference standalone CLI demo, and homepage value/evidence revision. `sift serve` does not require LiteLLM; Ollama and compatible base URLs are supported. Existing exact-client evidence remains limited to one OpenAI SDK→Sift→Ollama loop plus fixture tests.

## Evaluation and limits

The 344-question LongBench v2 study completed 2,063/2,064 requests with usage receipts; one Full request returned HTTP 529 without a receipt and was not retried. The frozen public questions were exposed during development. Of 343 complete paired task clusters, Full scored task-majority exact choice on 145/343 and Sift on 127/343: −5.25 pp, cluster-bootstrap 95% CI −10.20 to −0.29 pp. All 2,063 receipts show 59.66% fewer prompt tokens and 58.72% lower cache-sensitive BYOK receipt cost with Sift. Settled receipt cost was $12.633224; it is not an invoice. There are 13 conservatively reserved historical unreceipted attempts ($2.0457216 aggregate reserve) across the reviewed report family. The original $100 authorization applied to this completed study; do not send more MiniMax or other paid inference requests without a new user cap.

Other documented checks include the earlier 600-response and incomplete 503-question studies, a four-task field-pruning pilot, one 950K-token Astra/Gemini Subroute probe, and native-agent pilots. They are separate exposed or task-specific samples and must not be pooled into generalized quality claims. AppWorld remains parked pending a test-free output-quarantine rehearsal.

## Adoption and release state

- Issue [#13](https://github.com/stancsz/sift/issues/13) is open; it has zero comments/respondents and no sessions have occurred. Up to three inference-free first-run sessions are authorized. The issue already cites homepage revision `76f3baf` and the fixture task; after this docs PR merges, sync its exact commands and disclose that comments are public. Participants must use only the deterministic loopback fixture, never Ollama/model inference. Do not contact people directly.
- The first-run usability protocol is in [docs/evals/first-run-usability-protocol-2026-10-18.md](docs/evals/first-run-usability-protocol-2026-10-18.md). Its frozen homepage revision matches deployed `76f3baf`; the README and protocol now make the checkout prerequisite, commands, and privacy handling explicit.
- GitHub's latest release is the v0.10.0 pre-release. PyPI project `sift-context` does not exist yet; the release workflow is prepared, but PyPI pending publisher and live environment/tag protections are not verified. Stable release remains gated on held-out task quality, compatibility coverage, adoption disposition, and full release checks.

## Northstar council and decision

On 2026-10-20, Gemini 4 Argon recommended deterministic multi-client compatibility plus refreshing issue #13 and checking release gates. GPT-6.1 Sol independently assessed Gemini and prioritized usability first: there are no user observations, so more passing integrations alone will not expose onboarding friction. The current decision is to refresh the issue and publish the first-run task, then run the named-client compatibility work and non-publishing release-gate rehearsal. This preserves both reviews without turning them into a vote. Council usage: Gemini 3,347 prompt/211 completion; Sol 821 prompt/294 completion tokens.

## Next actions

1. Finish the corrected first-run README/protocol and durable, explicitly paraphrased council record; verify the docs diff and links.
2. Refresh issue #13 after the docs PR merges, with the exact successful demo output, checkout prerequisite, privacy-safe feedback format, and notice that issue comments are public. Keep recruitment opt-in and capped at three.
3. Merge the docs update after its short CI smoke passes; record the resulting commit. Pages is not expected to redeploy for docs-only changes.
4. Then progress a second named client path, held-out agent-task protocol/harness, and release-control verification. Preserve aggregate-only outputs; no AppWorld test access and no paid requests without new authorization.

## Learning

The last website change showed that visual measurement should be repeated on the actual deployed stylesheet after a hard reload; a transient mobile emulation state initially lacked loaded CSS and produced misleading dimensions. Once stylesheets were confirmed loaded, the live page matched the accepted local layout and showed no overflow. Keep rendered evidence, loaded-resource checks, and DOM measurements distinct in future site acceptance.
