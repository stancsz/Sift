# Sift readiness handoff — 2026-10-20

## Current state

The goal in [goal.md](goal.md) remains active. PR #14 is a draft; its current remote head is `d06b8fd178d5a171a45d6bef79775fc00fd14fd9`. The local working tree contains the reviewed safety repair and updated records, not yet pushed. The MiniMax 344-task × 3-repeat study stopped at 542/2,064 requests after one Full request returned HTTP 529 without a usage/cost receipt. Do not retry that request.

The partial run has 541 receipted responses and one unknown outcome. Receipt spend is $3.58631898; the unknown request's submitted reservation was $0.02571465. For future cap accounting, reserve each of the five unresolved requests at the entire dated route prompt limit plus the output cap, totaling **$0.786816** (four earlier unknown requests plus this 529). The user's existing $100 maximum covers the experiment, but any continuation must refresh current route pricing and charge every prior unknown reserve against the same cap.

Ninety fully matched task clusters provide preliminary exposed-development evidence: 110/270 correct Full versus 122/270 Sift; prompt tokens 17,275,101 versus 7,041,707; receipt cost $2.490294 versus $1.087784. The approximate task-cluster interval for the +4.44-point exact-choice difference is −3.26 to +12.15 points. Do not claim quality gain or parity. Nine outputs reached the length limit. This interim evidence is not held out and does not measure accepted coding-agent tasks.

## Work in progress

- PR #14 changes the paid runner so the exact older 503 report and the exact current 344 report are both required, pinned and separately reserved. A clean-state attestation cannot bypass them, and the operator must attest there are no additional unresolved requests. Focused tests pass (16 total); the final full local suite passed 380 tests in 105.86 seconds with 17 warnings.
- Independent release-readiness review identified the gap that led to this fix; the reviewer has been asked to recheck the updated working tree.
- Do not stage `.runs` or any raw prompt, answer, response, credentials, or private account data.
- Public recruitment issue [#13](https://github.com/stancsz/sift/issues/13) is authorized for up to three inference-free local-Ollama sessions; no respondents at last check. The independent first-screen 1280×800 review was READY for comprehension testing.
- The Astra and Gemini Subroute 950,401-token rate comparison is documented in the README. It reports measured Sifted path usage and modeled unsifted rate costs because both full-context routes rejected before inference.

## Next actions and gates

1. Complete the full local suite using `.venv-local-qa\Scripts\python.exe`; the global Python 3.14 failure was an environment import issue, not a valid suite result.
2. Obtain independent re-review of the focused guard/tests. Run full CI at release readiness; keep the normal PR workflow short.
3. Refresh provider route/pricing and operator usage/reserve before any further paid call. If continuing, skip the exact 529 job permanently, never retry it, preserve its unknown state, and stop at the same aggregate $100 ceiling. No new provider request has been made after the stopped run.
4. Publish the sanitized partial 344 result and limitations only after verifying aggregate calculations against the private raw report; keep raw data ignored.
5. Reconcile `docs/evaluation.md` and `ROADMAP.md` with the experiment and stable-release gates.
6. Stable release remains gated on independent quality/compatibility evidence, three opt-in usability sessions or a documented recruitment outcome, full release checks, and PyPI Trusted Publisher configuration.

## Key artifact identities

- Current branch: `codex/minimax-revalidation`
- Draft PR: [#14](https://github.com/stancsz/sift/pull/14)
- Current study manifest: `eaddd0d337111c6ab3c36d3f4a68dae4f002c94964de39beec620280f9c657c2`
- Private stopped report SHA-256: `20e1106b1f4c27c801f0411d433a06c7e1def9ed48be4b0b3df7431671e30356`
- 529 job identity: `66f53892821e116aacb33225:full:2`
- Main baseline: `63e4f4e8aa2ef39e8bec24c8910494d1607d86f1`
