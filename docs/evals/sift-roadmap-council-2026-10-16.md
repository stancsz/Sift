# Sift roadmap council, 2026-10-16

## Verdict

Freeze core feature work briefly and prioritize independent held-out extraction evidence, then accepted multi-turn agent outcomes with cache-aware economics, then baseline-backed distribution and docs. Defer MCP, AST, conversation-history retrieval, and further core expansion until those gates are met.

## Prioritized suggestions

1. **Independent held-out extraction fixtures.** Freeze commit `e7e1f4f`. Have an independent author fix CSV, structured-game, and weak-overlap epoch cases with required source spans before selector outputs are inspected. Compare current Sift with the feature-disabled selector and exact full context. Track exact retained evidence, critical omissions, invariant failures, and budget compliance. Stop on a protected-context or budget violation, or a reproducible critical-evidence regression. Do not use the existing public development cases as holdout evidence.
2. **Accepted multi-turn agent tasks and economics.** Run paired tasks against cached full context and Sift at matched model, output cap, and workload. Require independent task acceptance. Measure provider input, output, cache-read/write tokens, selector CPU, TTFT, whole-task time, and reported cost. Show GPT-6 Astra cost arithmetic using verified current prices, clearly separated from local Qwen or other provider trials. Stop any savings claim when accepted-task rates worsen or cache-adjusted economics fail to improve.
3. **Reproducible public comparison and fresh-user check.** Publish fixture provenance, commands, versions, denominators, failures, price date/source, and machine-readable receipts. Ask a fresh user to reproduce one comparison; withhold broad claims if it cannot be reproduced.

Gemini also emphasized an end-to-end QA gate because retained text alone does not establish task value. Sol elevated accepted agent outcomes above standalone QA, while still requiring exact evidence retention and full-context quality controls. Together these suggest a staged scorecard: extraction correctness first, accepted task success second, economics third.

## Decision on retrieval tools

The previous council supported optional client-side MCP plain code search as a possible later experiment. This roadmap review moves it below held-out extraction and accepted task/economics evidence. Do not add AST parsers or history retrieval yet. A future MCP experiment should be compared on the same held-out tasks and count added tokens, round trips, citation quality, cache effects, and latency.

## Receipt

- Gemini 4 Argon: `chatcmpl-agy-7baa027f2d60`; 3,251 reported tokens; 15.014 seconds.
- GPT-6.1 Sol: `chatcmpl-codex-advisor-ceaadafd918b`; 1,013 reported tokens; 10.047 seconds.
- Packet: 1,944 characters; council mode.
- `decision_changed: true`: defer the previously suggested MCP prototype and prioritize held-out evidence plus cache-aware accepted-task economics.
- This is strategy advice, not implementation or acceptance evidence. The current tree already contains uncommitted benchmark work from other experiments; none is classified as independent holdout based on this review.

## Follow-up decision: external compressor or accepted-agent pilot, 2026-10-16

A second council compared repairing the invalid LLMLingua-2 arm with beginning the independent agent pilot. The public LongBench screens remain small and exposed (Sift 15/48 vs full 20/48 on one screen; 15/30 vs 16/30 on an extension). The LLMLingua-2 trial exceeded its encoder's 512-token input limit, so it is not a usable competitor result. One source-audited relation case showed a possible extraction loss, while one native task passed full context and failed Sift with higher reported cost. None of these alone generalizes.

Gemini 4 Argon favored first repairing LLMLingua-2 with sentence-aware 512-token chunks on the existing public benchmark, with a stop rule based on accuracy against Sift and full context. GPT-6.1 Sol favored the frozen eight-task independent agent pilot because chunking a public single-turn benchmark cannot answer whether Sift preserves accepted multi-turn work. Sol's advice is selected for the next action: commission and validate independent pilot cases before changing the selector or spending effort on another public diagnostic baseline. The LLMLingua-2 comparison remains required before any broad best-in-class claim; it is deferred, not rejected.

The next pilot still has a hard preflight gate: an author independent of the selector implementation must freeze unseen multi-turn fixtures, exact rendered-token budgets, source-to-gold traceability, failing baselines, allowed writes, and independent post-run checks before model inference. Stop if that independence or fixture validity cannot be established. Eight tasks can validate the harness and estimate variance; they cannot prove quality parity or a top-one-percent ranking. The Sift selector remains frozen, and all price examples must separate measured provider usage from Astra rate arithmetic.

Receipt: Gemini 4 Argon request `chatcmpl-agy-3eb29e56326b` (1,485 prompt / 176 completion tokens); GPT-6.1 Sol request `chatcmpl-codex-advisor-54f4eb99a0fc` (725 / 326 tokens). The council did not change the selector implementation; it resolved the next evaluation priority in favor of independent accepted-agent evidence.

## Follow-up decision: privacy-preserving evidence-retention audit, 2026-10-16

The next gap was measurement: the exposed rollup Sift arm compacted one request from 26,063 estimated input tokens to 14,094 forwarded, but prior artifacts contained no per-span retention states or event timestamp. The callback previously logged aggregate counts and selector time only.

Gemini 4 Argon and GPT-6.1 Sol recommended an eval-only source-span auditor alongside structured IDs/coordinates, with no prompt bodies in logs. Sol emphasized that emitted-span presence does not prove attention or task correctness, and that ordering must be verified against the agent edit event. The implementation adds versioned fixture-relative character spans with SHA-256 validation, opaque retention states, request sequence/UTC metadata, and a verifier for direct Claude file edits. The selector algorithm remains unchanged.

The public rollup annotation is calibration data only. The verifier returns unknown for shell-mediated edits, unsupported trace formats, missing logs, or incomplete annotations. This does not retroactively establish retention or pre-edit delivery for the prior run because its gateway log lacks timestamps. The next acceptance run must retain both gateway logs and native trace, and must use independently authored held-out spans before any broad retention claim.

Receipt: Gemini request `chatcmpl-agy-afd5d6b893f4` (1,322 prompt / 146 completion tokens); Sol request `chatcmpl-codex-advisor-532fdf9e55d8` (569 prompt / 235 completion tokens); packet 1,336 characters. `decision_changed: true`: add exact-span and event-order measurement before continuing the agent pilot; do not alter selector policy. Local verification passed six focused auditor tests and the complete 113-test suite (24 skipped). This proves the audit mechanism's tested boundaries, not live-run quality.

## Follow-up decision: lower-budget compaction reliability, 2026-10-16

At a 24,576-token target, a fresh exposed least-privilege rollup Sift run passed visible and independent gold tests, but the event auditor found no Sift compaction before the first direct edit. The accepted run therefore does not prove evidence retention under compaction. The same task's recency control compacted once late in its run and also passed. These are one-run development calibrations. A full-context control has been run separately; all arms use local Qwen and Claude Code telemetry, not billed Astra usage.

Gemini 4 Argon and GPT-6.1 Sol advise prioritizing compaction reliability at a lower budget before adding retrieval. Freeze the task, selector hash, model, checks, and 16,384-token target. A qualifying Sift result requires an actual reduction before the first evidence-dependent edit, all four exact spans retained in that compacted request, and accepted visible and gold tests. Compare with recency and full context; record cache-adjusted cost and latency and stop advancement on missing evidence, acceptance failure, or absent pre-edit compaction. Because the fixture is exposed and each arm runs once, any pass remains calibration only; require a newly fixed unseen task for a reliability claim.

Receipt: Gemini 4 Argon request `chatcmpl-agy-4e1fd88b9efe` (1,403 prompt / 128 completion tokens); GPT-6.1 Sol request `chatcmpl-codex-advisor-370179ea93a1` (637 prompt / 333 completion tokens); packet 1,713 characters; council mode; total 2,501 reported tokens. `decision_changed: true`: run the lower-budget reliability gate before investing in workspace retrieval. The exact arm order and acceptance conditions are preregistered in [the 16K protocol](native-evidence-audit-16k-protocol-2026-10-16.json).

## Preview readiness and savings claims review, 2026-10-16

The current tree remains an unreleased `0.11.0.dev0` candidate. The evidence supports experimental evaluation only: selected token reductions and latency observations exist, but task-quality parity, accepted-task cost savings, and faster whole-task completion are unproven. The 500K–1M matched multi-turn Astra/Opus protocol remains unrun. The README therefore labels price tables as single-request rate arithmetic, updates the default target to 32,768, and avoids presenting modeled percentages as measured savings. The core API default is configurable with a 32,768-token default.

Gemini 4 Argon and GPT-6.1 Sol agreed the preview is not ready for a broad recommendation. Their recommended next gate is a matched, accepted-task Astra/Opus pilot after the 500K checkpoint and provider-count gates are ready. Record every turn's provider usage, cache reads/writes, output, retries, Sift CPU, acceptance, and wall time; stop stronger claims if acceptance degrades or net cost/time exceeds full context. Gemini's characterization of 32,768 as the current default was corrected: the source default was 24,576 before this change.

Receipt: Gemini 4 Argon request `chatcmpl-agy-5d24ab4418db` (2,897 prompt / 179 completion tokens); GPT-6.1 Sol request `chatcmpl-codex-advisor-ce0453a6de07` (642 prompt / 194 completion tokens); packet 1,497 characters; council mode; total 3,912 reported tokens. `decision_changed: true`: set the core default to 32,768 and keep README cost percentages explicitly modeled. No provider benchmark was run by this consultation.

## Evaluation readiness and provider-cost gate

The proposed 500K–1M multi-turn price comparison has not run. Available evaluation routes have not been verified to support the required context sizes and invoice-level usage accounting. A future comparison needs documented compatible endpoints, sufficient context limits, provider usage receipts, and an explicit total spend cap before any inference. Until then, keep the long-context price table labeled as arithmetic rather than measured task savings. No inference calls were made for this readiness review.
