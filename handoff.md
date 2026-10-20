# Sift readiness handoff — 2026-10-20

## Current state

The goal in [goal.md](goal.md) remains active. PR #14 is a draft; remote head `5b27c5ec7bcf6194dd6669a7f4f0cc97a08cb93f` contains the reserve fix, and the local working tree now also contains a single-use continuation path that has not been pushed yet. The MiniMax 344-task × 3-repeat study stopped at 542/2,064 requests after one Full request returned HTTP 529 without a usage/cost receipt. Do not retry that request.

The partial run has 541 receipted responses and one unknown outcome. Receipt spend is $3.58631898; the unknown request's submitted reservation was $0.02571465. For future cap accounting, reserve each of the five unresolved requests at the entire dated route prompt limit plus the output cap, totaling **$0.786816** (four earlier unknown requests plus this 529). The user's existing $100 maximum covers the experiment, but any continuation must refresh current route pricing and charge every prior unknown reserve against the same cap.

Ninety fully matched task clusters provide preliminary exposed-development evidence: 110/270 correct Full versus 122/270 Sift; prompt tokens 17,275,101 versus 7,041,707; receipt cost $2.490294 versus $1.087784. The approximate task-cluster interval for the +4.44-point exact-choice difference is −3.26 to +12.15 points. Do not claim quality gain or parity. Nine outputs reached the length limit. This interim evidence is not held out and does not measure accepted coding-agent tasks.

## Work in progress

- PR #14 changes the paid runner so the exact older 503 report and the exact current 344 report are both required, pinned and separately reserved. It reconstructs the 2,064-job schedule and all 541 valid prior receipts, then excludes the failed 529 at index 541 and returns only the 1,522-job suffix. A fixed output path and exclusive claim file make this continuation single-use; preserve both files, because deleting the local claim could permit replay. The operator must also attest that no additional unresolved requests exist. Independent review ACCEPTED the guard and single-use logic; focused tests pass (19 combined across the new tests and prior runner tests).
- Read-only OpenRouter preflight on 2026-10-20 confirmed MiniMax M3, the 524,288-token route limit, and unchanged $0.30/$1.20 per-million rates. MiniMax-side balance remains unverified. No inference requests were sent during this continuation work. Current minimum aggregate cap coverage is $35.217780: $30.844645 estimated remaining suffix + $3.586319 prior settled receipts + $0.786816 reserved for five unknown outcomes.
- The final full local suite passed 383 tests in 114.90 seconds with 17 dependency warnings.
- Do not stage `.runs` or any raw prompt, answer, response, credentials, or private account data.
- Public recruitment issue [#13](https://github.com/stancsz/sift/issues/13) is authorized for up to three inference-free local-Ollama sessions; no respondents at last check. The independent first-screen 1280×800 review was READY for comprehension testing.
- The Astra and Gemini Subroute 950,401-token rate comparison is documented in the README. It reports measured Sifted path usage and modeled unsifted rate costs because both full-context routes rejected before inference.

## Next actions and gates

1. Push the single-use continuation changes and updated records; run CI on that head and keep PR #14 draft until green.
2. The continuation remains authorized under the existing $100 cap. It must use the fixed output, claim file, exact private source reports, and latest route check. The MiniMax balance is unverified; preserve the $100 client-side aggregate limit and stop on any unreceipted response. Never retry the 529 or replay the suffix.
3. The sanitized matched-task counts and arithmetic were independently audited and verified against the private report; raw data stays ignored.
4. Stable release remains gated on independent quality/compatibility evidence, three opt-in usability sessions or a documented recruitment outcome, full release checks, and PyPI Trusted Publisher configuration.

## Key artifact identities

- Current branch: `codex/minimax-revalidation`
- Draft PR: [#14](https://github.com/stancsz/sift/pull/14)
- Current study manifest: `eaddd0d337111c6ab3c36d3f4a68dae4f002c94964de39beec620280f9c657c2`
- Private stopped report SHA-256: `20e1106b1f4c27c801f0411d433a06c7e1def9ed48be4b0b3df7431671e30356`
- 529 job identity: `66f53892821e116aacb33225:full:2`
- Main baseline: `63e4f4e8aa2ef39e8bec24c8910494d1607d86f1`
