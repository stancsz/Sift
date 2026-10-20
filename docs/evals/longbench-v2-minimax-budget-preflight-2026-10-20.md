# MiniMax LongBench budget preflight — 2026-10-20

## Authorization and requested scope

The user separately authorized up to **$100 USD** for a fresh LongBench-v2 cohort of 344 questions, three repeats in each of two arms (2,064 requests). This cap applies to the new run; historical spend and unknown-attempt reserves from the completed study remain separately recorded. The user also authorized up to three inference-free opt-in first-run sessions. No participant contact has occurred.

## Refreshed route

OpenRouter's public endpoint metadata was fetched at `2026-10-20T16:51:40Z`; the saved snapshot is [longbench-v2-openrouter-minimax-m3-endpoints-2026-10-20T1651Z.json](longbench-v2-openrouter-minimax-m3-endpoints-2026-10-20T1651Z.json), SHA-256 `CD5993F3D533AAAB1065DC6539A8A1A6DBB7BA43B3D62EF6FC7BD5599874BC26`. It identifies `minimax/minimax-m3`, provider `Minimax`, exact provider tag `minimax/fp8`, status `0`, context/prompt limit 524,288, completion limit 512,000, prompt price $0.30/M, completion price $1.20/M, and no fallback route. This is a public metadata snapshot, not a guarantee of future availability or provider balance.

Read-only OpenRouter diagnostics reported about $2.829 key usage and $10 total credits with $5.532 usage. These are OpenRouter diagnostics and do not establish the MiniMax-side BYOK balance. No credential or key label is recorded here.

## Modelled reserve

The prepared 344-case schedule contains 2,064 requests and 92,682,489 local prompt-token estimates across the three repeats. Applying 1.5× input reserve and a 64-token maximum completion for each request at the refreshed endpoint prices yields **$41.86563525**. This is a modelled reserve derived from the prepared prompts and the public listed rates. It is not an invoice quote, a hard provider-side $100 ceiling, or proof of exact upstream tokenization. The client can stop before later requests when its reserve estimate reaches the cap, but cannot retract an already accepted request.

## Dispatch gate and disposition

The current-main manifest [longbench-v2-minimax-344-manifest-current-main-2026-10-20.json](longbench-v2-minimax-344-manifest-current-main-2026-10-20.json) remains `prepared_only_no_dispatch` with `dispatch_authorized=false` and references the older 07:50 route snapshot. The legacy stage runner `benchmarks/run_longbench_v2_minimax_stage1_100.py` still blocks fresh 344-task dispatch and only permits a tightly pinned continuation of a prior stopped run. The 503-question full-suite dispatcher uses a different schedule (one repeat), so it is not a substitute.

Added a separate fresh entry point at [run_longbench_v2_minimax_fresh_344.py](../../benchmarks/run_longbench_v2_minimax_fresh_344.py), its focused tests, and a code-pinned manifest [longbench-v2-minimax-fresh-344-manifest-2026-10-20.json](longbench-v2-minimax-fresh-344-manifest-2026-10-20.json). It binds the 344-case schedule and current route snapshot; fixes one run ID, one dispatch output and a single-use cohort claim; caps the CLI spend at $100; requires all three pinned prior unknown-outcome reports and explicit settlement/billing attestations; runs live account/route preflight; and then reuses the existing per-job budget/in-flight safeguards. It is isolated from the old continuation path.

The first independent review found a P1 alternate-run-ID and caller-supplied-manifest-hash bypass. Those were repaired, and the independent re-review marked the path READY for a single paid attempt within this checkout. The reviewer also noted that the claim is local to the checkout and that the cap is client-side rather than provider-enforced. Eight focused tests, compilation, and whitespace validation passed. This acceptance does not cover full prompt reconstruction or live dispatch.

**Disposition: public data prepared; no inference request.** The dataset, tokenizer, and template were saved under the safe worktree's ignored `tmp/longbench-v2-fresh/` folder and matched pinned SHA-256 values (`15d61c…7fe2`, `bb1f16…5ad6e`, `114212…9fe64`). The fresh entry point reconstructed 344/344 tasks and 2,064 jobs with the exact `$41.86563525` reserve. No private `.runs` artifact was accessed or copied. Dispatch still requires the three exact prior unknown-outcome reports used for reserve accounting. The route, usage, and reserve must be refreshed immediately before a call. No request should be sent if the refreshed schedule reserve plus prior unknown reserve exceeds the $100 cap, if the route changes, or if the live account preflight fails. The fixed claim coordinates this checkout only; do not run another copy concurrently. A request already accepted by the provider may exceed its client-side reservation before the response can be settled.

The Codex Advisor council invocation for this cap decision produced no captured receipt. Its verdict is unavailable and was not retried. The dispatch audit's initial finding and repaired re-review are summarized above. Learning: keep a fresh study's spend authority separately pinned from continuation state, and make the authorization itself single-use rather than relying on a caller-provided run ID or digest.
