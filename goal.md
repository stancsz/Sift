# Goal: make Sift useful and credible to adopt

## Status: active

The owner asked to continue the Sift adoption and release-readiness work through completion. Keep the current product evidence honest, reduce routine CI cost, improve the first-use story, broaden evaluation, and make the no-LiteLLM CLI straightforward to try. Do not call the preview stable until the gates in [the roadmap](ROADMAP.md) are satisfied.

## Current constraint

The latest wider LongBench v2 experiment stopped safely at request 542/2,064 when a MiniMax request returned HTTP 529 without a provider usage/cost receipt. The runner now validates both exact unresolved reports, validates the complete stopped schedule against reconstructed prompts, and offers one single-use continuation of only the unattempted suffix. It reserves full possible route exposure, includes the 541 prior receipts, skips the failed request, and requires a no-additional-unknowns attestation under the user's $100 aggregate study cap.

## Current evidence

- The current run has 541 receipted responses and one unresolved 529 attempt. Provider-receipted spend is $3.58631898. These figures are private run accounting, not an invoice.
- Ninety complete task clusters (270 responses per arm) have both three-repeat arms. Full exact choice: 110/270 (40.74%); Sift: 122/270 (45.19%), a +4.44 percentage-point observed difference. The approximate task-cluster 95% interval is −3.26 to +12.15 points.
- On those 90 matched tasks, provider prompt tokens were 17,275,101 Full versus 7,041,707 Sift (−59.24%); receipt costs were $2.490294 versus $1.087784 (−56.32%). These are partial, cache-sensitive OpenRouter BYOK receipts, not invoice totals. Nine outputs ended at the length limit and strict-choice scoring counts invalid/truncated outputs as wrong.
- The selected public LongBench questions were exposed during development. This is not a holdout or an agent-loop accepted-task benchmark. The partial observed accuracy difference does not establish improvement, parity, or non-inferiority.
- The actual screenshot of the homepage at 1280×800 received an independent READY review for a 20-second comprehension session. Up to three inference-free local-Ollama first-run sessions are authorized; issue #13 is public and had no respondents at the last check.
- The stopped checkpoint now reconstructs exactly against the frozen manifest: 541 receipted jobs sum to $3.58631898; the one failed 529 request is excluded from the 1,522-job suffix. A read-only OpenRouter refresh on 2026-10-20 confirmed the MiniMax route and the pinned $0.30/$1.20 per-million rates. MiniMax-side balance remains unverified by the API; user authorization allows that uncertainty under the client-side $100 cap.
- GPT-6 Astra and Gemini 4 Argon Subroute examples use a synthetic 950,401-token archive and report observed Sifted-path usage plus explicit rate-card estimates. Both unsifted requests were rejected before model inference, so their costs are modeled, not measured.

## Acceptance and next actions

1. Land and independently review the pinned unknown-outcome reserve fix and focused regression tests.
2. Run the complete local test suite on this exact worktree revision; retain short PR CI and run the full matrix at release readiness.
3. Continue only the validated suffix using the fixed output and single-use claim; the current minimum projected exposure is about $35.22 (remaining estimate + prior receipts + five unknown reserves), below the approved $100 cap. Never retry the 529 job; keep each new unknown outcome explicit and stop at the aggregate cap.
4. Complete the three local usability sessions if volunteers opt in; report observed comprehension and setup friction without treating completion as adoption.
5. Keep the GitHub Pages site, README, and evaluation record consistent with verified evidence and a clear OpenAI-compatible/Ollama quick start.
6. Complete independent quality and compatibility gates, full release CI, and PyPI Trusted Publisher setup before making a stable release.

## Durable evidence

- [Evaluation record](docs/evaluation.md)
- [Current handoff](handoff.md)
- [Roadmap](ROADMAP.md)
- [LongBench v2 primary manifest](docs/evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json)
- The full run artifact and answer text remain private under `.runs`; never commit them.
