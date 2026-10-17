# Evaluation record

This page separates span retention, runtime compatibility, and model answers. The source Claude Code logs are locally generated task traces and are not distributed in this repository.

## Reproducible package tests

`python -m unittest discover -s tests -q` covers budget enforcement, message preservation, Anthropic and OpenAI tool loops, the optional LiteLLM callback, old thinking blocks, neighboring diagnostics, distant identifier joins, repetitive log noise, unsupported inputs, and seeded middle-fact placement. The 0.9.0 suite has 42 passing tests with LiteLLM 1.103.0, including five actual SDK loopback tests for native terminal/usage provenance. The packaged wheel's Sift code passed the suite inside the staging runtime; a clean Python 3.14 core install passed 23 tests and explicitly skipped 19 optional integration tests. Subroute's focused integration/configuration suite passed 35 tests. `python benchmarks/compare.py` uses 100 authored placements of a unique fact in the middle of a noisy history. Sift retained 100/100; an 800-character head/tail slice retained 0/100. This benchmark is designed around Sift's query-aware selection and does not estimate general recall.

The current `0.11.0.dev0` source checkout was also wheel-built and installed
into a clean Python 3.14 environment with the pinned LiteLLM 1.103.0 proxy
extra. `python -m unittest discover -s tests -q` passed all 98 tests with no
skips, and `pip check` reported no broken requirements. This verifies the
candidate's declared install and callback test path, not a public release or
provider task quality. The optional dependency now requests LiteLLM's `proxy`
extra only; the additional `extra-proxy` integration set was not needed by
Sift's callback and introduced unrelated key-management, vector-search, and
A2A dependencies.

The 0.3.0 regression places `FAILED test_invoice_total` beside a `rounding_mode=HALF_EVEN` clue in a 1,000-line log. Under the same 700-token budget, 0.2.0 retained the failure name but lost the adjacent clue; 0.3.0 retains both. This is a concrete causal-context failure of isolated excerpt selection, not proof that all agent failures came from Sift. A separate 90,000-distinct-line, 784,764-estimated-token case retained the same pair and forwarded 16,420 estimated tokens under a 24,576-token target in 0.68 seconds on one Windows desktop.

## Private agent-trace replay

Five native Claude Code task traces were generated locally while solving streaming, billing, scheduling, context-planning, and policy-persistence fixtures. They contained 23 to 66 replayable messages and had deterministic four-character estimates of 7,906 to 15,869 tokens. The replay forced a 5,000-token target to exercise compaction because the actual 24,576-token gateway target would not have been crossed by those traces.

Sift preserved the original task and latest tool message within the forced budget in 5/5 traces. Five retrospective questions about a named initial test failure each retained the matching failure line. A naive 20,000-character head/tail string slice retained the same line in 2/5. That slice is a span-retention reference, not a protocol-valid competing gateway. The questions were selected after inspecting the logs, so this is not a blinded or representative corpus.

## Live gateway checks

The Subroute staging gateway ran Sift with the local Unsloth Qwen3.8-27B `UD-IQ3_S` model. A 36-cycle Anthropic Messages request returned the exact newest failing test name with HTTP 200, `end_turn`, and 18,434 provider-reported input tokens. A corresponding Chat Completions request returned the newest failure name with HTTP 200, `stop`, and 18,334 input tokens. These probes test one long-loop shape on both public protocol surfaces.

## 0.4.0 cache-aware replay and native callback

The optional native LiteLLM Proxy callback was exercised in Subroute staging with deployed LiteLLM 1.103.0. A paired-diagnostic history returned `rounding_mode=HALF_EVEN` through both Anthropic Messages and Chat Completions with HTTP 200, `x-sift-compacted: true`, and a 24,576-token Sift target. With four-cycle grouping, 36-cycle live probes again returned the newest failing test through both protocols; provider-reported input was 26,400 and 26,450 tokens respectively, within the model's 32,768-token context with a 4,096-token output cap. LiteLLM's estimate and the provider's count differ, so the Sift target is not a provider-token guarantee.

For five private Claude Code traces at a forced 5K target, median serialized prompt-prefix fractions between **tool-result turns** rose from 0.085, 0.085, 0.033, 0.060, and 0.069 on 0.3.0 to 0.241, 0.209, 0.363, 0.195, and 0.075 on 0.4.0. The labeled baseline failure remained in 5/5 later-query trials. A harder billing stress trace with 65,368 estimated raw tokens retained four named incident codes within 20,515 estimated forwarded tokens; 0.3.0 also retained all four but used 24,411. Its median serialized prefix fraction rose from 0.007 to 0.749 across 18 tool-result transitions. This trace's native Claude Code run failed to edit code and failed its holdout tests, so code-task acceptance did not improve in that run.

These are prompt-serialization metrics, not KV-cache measurements. In two adjacent 34- and 35-cycle live requests, llama.cpp reported just 57 cached tokens each and processed roughly 24,000 prompt tokens per call, even though the rendered messages shared a long prefix. A direct simple 26K-token request to the same server did reuse over 25K tokens when only its final line changed. This establishes a remaining cache-reuse problem for this compacted tool-loop shape; the release should not be described as a proven first-token latency improvement.

## 0.5.0 fixed-boundary cache check

The current unfinished four-cycle group now stays exact while it fits a reserved third of the target. Its messages append after a fixed historical excerpt until the next boundary. A regression checks that 18-, 19-, and 20-cycle compacted message lists are append-only within one group and remain under target. At a forced 5K target, five private Claude Code trace replays retained the original task, latest tool message, and labeled initial failure in 5/5 later-query trials. Median serialized prefix overlap between tool-result turns was 1.0, 1.0, 1.0, 0.653, and 0.542. The 65,368-estimated-token billing stress replay still retained all four named incident codes within 20,515 estimated forwarded tokens.

In a staging sequence of 34, 35, and 36 tool cycles, llama.cpp reported 0, 20,765, and 23,045 cached prompt tokens. End-to-end buffered response times were 17.22, 4.15, and 3.86 seconds, and each answer named the newest failing test. The gateway estimated 18,959, 20,948, and 22,937 forwarded input tokens, all under its 24,576 target; provider-reported prompt tokens were 20,769, 23,049, and 25,329. Fresh single-request 36-cycle Anthropic and Chat Completions probes returned the newest failure name with normal terminal outcomes and 26,400 and 26,450 provider-reported input tokens. The paired-diagnostic middle-history question still returned `rounding_mode=HALF_EVEN` through both protocols. These are selected live examples; a boundary rollover or oversized tool result can still reset the cache, and native agent task completion was not remeasured on 0.5.0.

For the paired-diagnostic regression, a 6,000-line log was sent through the staging Chat Completions route on 0.2.0. The model said the cause was absent because it received only the failure line. On 0.3.0, the same history and question returned an answer containing the adjacent `rounding_mode=HALF_EVEN` clue. A clearer follow-up question asked for the setting immediately after the failure and received exactly `rounding_mode=HALF_EVEN` through both Chat Completions and Anthropic Messages, with normal `stop` and `end_turn` outcomes and 22,570 provider-reported input tokens. The higher forwarded count compared with 0.2.0's 2,004 tokens increases cold-prefill work: the matching first responses took 11.56 and 20.2 seconds respectively. Later cached 0.3.0 queries took 2.58 and 4.05 seconds. These timings are not a controlled latency benchmark, but they show the tradeoff of retaining more evidence.

Six actual failed-test outputs from the local task logs were each buried between 4,500 routine lines on both sides and sent through staging Chat Completions. Five queries asked whether a named test was listed as `ERROR`; one asked about a named `FAIL` in a later run. The model answered 6/6 correctly with normal `stop` outcomes. Each raw history was about 415,000 to 417,000 characters; forwarded input was 2,199 to 2,351 provider-reported tokens. These are selected binary questions with artificial padding. They show that this route can answer these queries after compaction, not that it reliably solves arbitrary questions over a million-token history.

## 0.6.0 identifier joins and rarity

The 0.6.0 candidate adds two bounded retrieval steps. Query terms occurring rarely in old history rank above ubiquitous log words, and identifiers from high-ranked source lines lead to related lines. A 966,253-estimated-token synthetic history with 76,000 distinct heartbeat lines hid a delivery-to-policy mapping and the policy's retry timestamp 25,000 lines apart. Version 0.5.0 retained neither; 0.6.0 retained both within 22,579 forwarded estimated tokens in 1.86 seconds of CPU time on one Windows desktop. Three smaller domain cases and one changed-policy case also retain both sides of distant joins. This is authored span-retention evidence, not answer quality on real conversations.

The same 6,000-line changed-policy history was sent through Subroute staging. Both Anthropic Messages and Chat Completions returned the current policy's timestamp `2026-10-16T18:00Z` with HTTP 200 and normal terminal outcomes. Each reported 27,225 provider input tokens versus a 22,149-token gateway estimate; the route stayed inside its 32,768-token model context with a 4,096-token output cap. A 34/35/36-cycle cache probe after the retrieval change reported 20,759 and 23,039 cached tokens on the two appended turns. Its first 128-output-token run had an empty answer on the last request; rerunning with 768 output tokens yielded the expected newest test name on all three, with 20,759/20,759/23,039 cached tokens and normal `stop` outcomes. The cache measurement supports prefix reuse inside that fixed boundary; it does not guarantee answer correctness or reuse across rollover.

One native Claude Code webhook task finished in 478.14 seconds, edited source, and passed five visible tests, but failed an independent concurrency holdout because simultaneous SQLite connections could raise `database is locked` during WAL setup. Its 24 logged model responses averaged 2.60 seconds to first token and 42.95 generated tokens/s. The holdout identifies a code-solution defect; the run does not establish a Sift retrieval failure or a passed acceptance task.

## 0.7.0 named-failure retention

A private replay of six real Claude Code task traces found a loss in 0.6.0: one selected initial `ERROR: test_*` line survived only 14 of 74 compacted tool-result turns at a forced 5K target, even though the task had not necessarily passed its tests. The 0.7.0 candidate reserves a bounded verbatim index of the first named failed tests from historical tool output and keeps bounded failure lines in frozen four-cycle epochs. The selected line survived 74/74 turns on the same traces. Median serialized prompt-prefix overlap stayed at 1.0 in four traces and rose from 0.652 to 0.676 and from 0.551 to 0.611 in two others. These failure labels were selected after inspecting the traces, and neither retention nor prompt overlap proves that an agent completes the task. The first diagnostic can become stale after tests pass; source message labels and the exact latest tool cycle remain available to disambiguate it.

A public Anthropic regression checks three named failure formats through 18, 19, and 20 tool cycles under a 3K hard target, with append-only compacted messages inside the group. A 981,587-estimated-token authored OpenAI tool-loop case forwarded 23,369 estimated tokens under the 24,576 target in 0.135 CPU seconds while retaining the first named failure and exact latest tool result. That repetitive synthetic timing is not a general million-token latency estimate. The standalone suite has 29 passing tests and the seeded 100-case middle-fact benchmark remains 100/100.

In staging, a 34/35/36-cycle Chat Completions sequence returned the newest failure on all three requests with 21,362 and 23,642 cached tokens on appended turns. A separate sequence asked for the earliest failure and returned `test_cache_probe_0` on all three with the same cache counts. Gateway estimated 19,475/21,464/23,453 forwarded tokens; llama.cpp reported 21,366/23,646/25,926 prompt tokens. All stopped normally. A separate 36-cycle Anthropic Messages probe returned the newest failure with HTTP 200, `end_turn`, and 26,058 provider input tokens. This demonstrates both old-evidence recall and prefix reuse inside this one fixed boundary; rollover and larger outputs remain separate limits.

A native Claude Code build-planner task on 0.6.0 ran for 480.5 seconds and passed six visible tests, but failed its independent holdout because a directly supplied unknown dependency raised `KeyError` instead of `BuildError`. A later, explicitly post-run holdout found a fingerprint collision from delimiter-based encoding, and the agent left an extra scratch file outside its allowed edit scope. Its 26 logged model responses averaged 2.19 seconds to first token and 43.04 generated tokens/s. The run does not count as accepted and does not establish a Sift-caused failure.

## 0.8.0 compact failure identifiers

The 0.7.0 index retained the first selected failure on every compacted tool turn, but its full-line, 640-character allowance covered only 24 of 28 distinct failed-test names across six private Claude Code traces at a forced 5K target. The 0.8.0 candidate quotes the exact failure prefix and test identifier from each matched tool line instead of its surrounding error text. With the same character bound and up to 12 distinct identifiers per tool result, coverage rose to 28/28. This is extractive but lossy: detailed errors still depend on selected neighboring excerpts or exact recent cycles. Average forwarded tokens fell in all six trace replays. Median serialized prefix overlap remained 1.0 in four traces and moved from 0.676 to 0.675 and 0.611 to 0.590 in two; the latter changes do not support a universal cache improvement claim.

The staging 34/35/36-cycle Chat Completions probes still answered newest and earliest failed-test questions correctly. The appended turns reported 21,362 and 23,642 cached prompt tokens, with 19,475/21,464/23,453 gateway-estimated and 21,366/23,646/25,926 provider-reported input tokens. A separate 36-cycle Anthropic Messages probe returned the newest failure with HTTP 200 and `end_turn`. The public regression now checks 12 distinct failure names, hard budget compliance, and append-only compacted messages inside one group. The standalone suite passed 29 tests and the seeded middle-fact benchmark remained 100/100. These selected results establish the fixed-boundary behavior observed here, not cache reuse across a group rollover or changed query.

## 0.9.0 Responses integration

The stateless text Responses adapter preserves retained original items while using LiteLLM's converter only for selection. Independent tests cover reasoning-separated parallel calls, interleaved results, exact active work, append-only behavior inside one boundary, unchanged instructions/tools/output limits, and explicit rejection of unsupported histories. A live 34/35/36-cycle sequence returned each newest failure with normal `response.completed` outcomes. Forwarded estimates were 19,669/21,658/23,647, provider input was 21,558/23,838/26,118, and cached input was 0/21,554/23,834. Client first-token times including reasoning were 14.22/2.06/2.15 seconds. This selected cold/warm sequence is not a controlled Sift-versus-full speedup.

A native Codex request exposed a concrete counting defect: the proxy estimated 14,736 tokens while the backend saw roughly 272K after connected tool schemas were serialized. Inspection showed that LiteLLM's counter omitted namespace/custom descriptions and JSON Schema branches such as `$defs`. Version 0.9.0 uses native tool translation for counting plus a conservative serialized-schema floor. Independent 1.103.0 regressions confirm that long definitions now consume the target or raw limit, while original provider tools remain unchanged. The fix improves admission estimates; exact model-template counting remains an open gate.

Native Codex text and shell smoke checks passed after disabling unrelated connected apps for this isolated test. The first build-planner attempt failed because the harness had omitted this Windows host's native sandbox backend, so every tool command was rejected. That attempt is retained as a harness failure, not a Sift quality result.

The fresh Codex build-planner run completed in 537.13 seconds, passed six visible tests and the original five independent holdouts, and had a clean final edit scope. Its 30 backend completions averaged 42.94 generated tokens/s, calculated as total generated tokens divided by total decode time. Native Codex JSONL does not expose per-response TTFT. Gateway audits recorded 16 compacted requests out of 30; every forwarded estimate was at most 24,555 tokens. Client usage reported 484,723 cumulative input tokens, of which 392,781 were cached. There was no matched no-Sift task run, so these counts do not establish cost savings.

Broader independent review then found two contract defects outside those original five assertions: source inputs and dependency fingerprints could collide, and malformed directly supplied targets were accepted. Two explicitly post-run holdout tests preserve those failures for future trials. The final narrative also incorrectly described the initial test result and claimed one edited file was unchanged. Thus the original eleven tests passed, but the artifact and reporting do not satisfy the full task contract. These are solution/reporting defects; this run does not establish that Sift caused them. Whole-task cost/latency benefits and additional held-out domains remain pending.

### Predeclared operations investigation

A separate authored incident task required sequential full-file intake of four 160-line JSONL files, followed by a JSON investigation artifact with exact citations. Gold conclusions were fixed before the run and hidden from the client. Native Claude Code received every line of all four files before its first edit, without client context snapshots. The 308.24-second run had 16 backend responses, 10 gateway-confirmed compactions, a 24,545-token maximum forwarded estimate, 7.6206-second mean client TTFT, and 43.11 aggregate generated tokens/s. The final write scope was clean and both visible schema/citation tests passed.

The task was **not accepted**: one of two independent gold tests failed. Nine conclusion fields were right, but the artifact reported 16,200 rather than 6,200 elapsed milliseconds. Its eight exact citations included the correct request-start and upstream-completion timestamps, so missing source evidence was not demonstrated. This is an observed calculation error; attribution to compaction requires a matched comparison. It is one authored stress-intake case, not a natural incident corpus or a general task-success estimate.

Native Codex attempted the same fixed case in 243.15 seconds. Its artifact passed both visible and both independent gold tests, including the correct 6,200 ms elapsed time. Its final edit scope was clean. However, it switched to targeted searches instead of the required sequential intake of all four complete files. The client reported display truncation, but its raw first-file execution aggregate retained all 160 lines; model-visible limits and the requested output cap are not exposed by those JSONL events. Files three and four were only searched. The full-intake stress gate failed, so the run is **not accepted as that stress test**. It completed 12 backend requests at 41.93 aggregate generated tokens/s, with one gateway-confirmed compaction and a maximum forwarded estimate of 24,401 tokens. Per-response TTFT was unavailable from Codex JSONL. A correct artifact after targeted retrieval does not prove that Sift handled the intended full raw history.

| Native client / task | Wall time, seconds | Mean client TTFT, seconds | Aggregate server tokens/s | Acceptance |
|---|---:|---:|---:|---|
| Codex / build planner | 537.13 | Unavailable | 42.94 | Original 11 tests passed; broader contract/reporting failures |
| Claude Code / incident | 308.24 | 7.621 | 43.11 | Gold calculation failed |
| Codex / incident | 243.15 | Unavailable | 41.93 | Artifact passed; required full intake failed |

These runs used Claude Code 2.1.251 and Codex CLI 0.154.0 against local `qwen3.8-27b`. Client context was set to 1,000,000; Claude's client auto-compaction threshold was 95% and Codex's was 950,000. These native task timings are observations with different work and output lengths, not a controlled client or compactor speed ranking. Staging routing/advisor settings were restored after every run.

## Controlled cold-prefill comparison, 2026-10-15

This comparison preceded the 0.10.0 structured-record change. It is historical latency evidence, rather than a fresh timing comparison of the current release.

Three public authored cases cover a changed retry policy, an appointment's UTC offset, and an invoice rounding rule. Their expected labels were fixed before inference. Each case ran twice with full context, Sift, and protocol-preserving head/tail trimming, for 18 sequential calls. Variant order was deterministically shuffled with seed 773. Full prompts fit the backend context; the two compactors had the same 6,000-estimated-token ceiling. This is a small label-answer benchmark, not natural agent-task acceptance.

The local stack used Unsloth `Qwen3.8-27B-UD-IQ3_S.gguf`, model revision `4ca720788d1e01f1bff70c033e0d0028fd02e502`, on an NVIDIA RTX 5070 Ti with 16 GB VRAM. The llama.cpp CUDA image was pinned to `sha256:b0baccbe2e00b5d74e63f85f9f023c93d61d0f329475269e1e7002e87eb875ea`. Context was 32,768, parallelism one, K/V caches `q8_0`, flash attention enabled, and reasoning budget 512. LiteLLM 1.103.0 served the gateway and benchmark SDK. All variants used temperature zero, seed 773, and a 768-token output cap including reasoning.

| Variant | Correct / calls | Mean endpoint input tokens | Mean TTFT, seconds | Mean preparation + response, seconds | Mean compaction CPU, ms | Aggregate server tokens/s |
|---|---:|---:|---:|---:|---:|---:|
| Full context | 6 / 6 | 13,214.7 | 8.963 | 13.356 | 0.004 | 44.04 |
| Sift | 6 / 6 | 7,433.0 | 5.491 | 10.708 | 38.49 | 45.45 |
| Head/tail | 6 / 6 | 7,561.3 | 5.570 | 14.365 | 35.20 | 45.33 |

All 18 requests terminated with native `stop`, and endpoint usage reported zero cached tokens for every sample after `cache_prompt: false`. Gateway audits confirm that all 18 prepared requests were forwarded without further compaction; the saved routing/advisor policy was restored. Eighteen server decode records match the sample count and output-token order. The published report's server fields were joined from historical engine logs after the run and independently checked. Server throughput is total generated tokens divided by total decode time, not tokens divided by client wall time; the standalone runner does not infer it.

On this corpus, Sift used **43.8% fewer input tokens**, had **38.7% lower mean TTFT**, and **19.8% lower mean preparation-plus-response time** than full context. TTFT includes reasoning when exposed. Its observed ranges were 5.26 to 5.89 seconds, versus 8.31 to 9.59 for full context. Preparation measures the transformation and its required internal counters; report-only raw/prepared counting is excluded. The Sift step ran in the benchmark process, so this is not a measurement of the proxy's full concurrent compaction path.

Head/tail also answered all six labels correctly and had similar TTFT. These cases therefore do not establish a general Sift quality advantage over head/tail. Two repeats of three cases are not six independent tasks. Sift also generated more output: a mean 233.3 tokens versus 191.7 for full context. No dollar saving is inferred from this local unpriced model; billed cost needs input, cache, output, retry, and auxiliary-call accounting under dated provider prices. Warm prefixes, group rollover, concurrency, and whole-task cost remain separate gates.

The [complete 768-token report](results/prefill-2026-10-15-cap768.json) retains every sample, SDK usage separately from native endpoint usage, comparison gates, timing spread, and gateway/server observations. The [initial 256-token attempt](results/prefill-2026-10-15-cap256.json) is also retained: full/Sift each completed correctly in 4/6 calls and head/tail in 2/6 because the cap truncated reasoning. Its comparisons are invalid. The explicit 768-token rerun changed only the output cap; it was not an automatic retry. Reproduction commands are in the [README](../README.md#controlled-prefill-benchmark).

### Skill learning

For this release, Northstar's independent review found both an orphaned parallel-call boundary and a skipped-schema counter path that development checks missed. Preserve the complete pending call batch and test counting with real deployed LiteLLM, including schema branches. An HTTP 200 or a client-reported completed turn does not establish an accepted artifact. The same rule applies to benchmarks: LiteLLM may synthesize terminal markers and estimated usage for an incomplete provider stream, so those fields need provenance before supporting performance claims. The next checks use fixed answers and independent artifact assertions, with failure samples retained.

Carry the model's reasoning reserve into benchmark output limits. The first 256-token run repeated a known empty-answer failure mechanism because its cap was below the backend's 512-token reasoning budget. Preserve that failure, use one explicit 768-token comparison, and keep cap changes visible in the report. Do not tune case questions or extraction against failed evaluation answers.

The final hand-and-sieve PNG was inspected at 160 and 48 pixels on light and dark backgrounds, with a separate source-detail review. Independent visual review accepted the current asset; no remaining material defect was found at those display sizes.

## Runtime admission checkpoint after 0.9.0

Independent review reproduced a runtime defect in 0.9.0: the two-worker semaphore was acquired inside the executor, so additional requests could queue with large histories. A cancelled queued caller could still enter the token counter later. The candidate now admits work before executor submission, rejects overload with HTTP 429 and `Retry-After: 1`, skips a cancelled caller's queued work, and keeps already running work admitted until its thread actually finishes. Detached worker errors are consumed, submission failures release capacity, and request context variables propagate into counting. No provider call or automatic retry was added.

The complete candidate suite passed 45 checks against LiteLLM 1.103.0. An independent public-callback probe verified immediate overload rejection with two blocked counters, event-loop responsiveness, running and queued cancellation, late errors, submission failures, and recovery. Already running Python threads cannot be forcibly stopped; concurrency stays bounded at two per hook instance. Subroute's automatic recovery adapter reuses this execution owner while retaining its budget and error translation; 35 focused checks passed. These are CPU/runtime checks, not new provider compatibility or task-quality results. No running gateway was restarted for this checkpoint.

At this historical checkpoint, the portable native-client runner and its two public development fixtures remained under review. Independent review caught a gold-file collision, an invalid test-loop success condition, ambiguous native executable discovery, and a Windows descendant-cleanup gap before any new inference calls. Those findings were subsequently fixed and independently rechecked before the later controls below; the third public build fixture was added afterward. Public authored fixtures are development controls, not a held-out corpus.

The host's Python 3.14 check then exposed a second cancellation detail: `asyncio.shield` logs a detached worker exception explicitly, even when our callback has retrieved it. Waiting with `asyncio.wait` preserves the worker on caller cancellation and allows the existing drain callback to own detached errors without duplicate logging. The same three runtime regressions pass on Python 3.14, and all 45 checks pass on Python 3.13 with LiteLLM 1.103.0. An initial host-wide suite used a preexisting unsupported LiteLLM 1.100.1 and failed its version/counting checks; it is not a clean compatibility result. A separate dependency-free Python 3.14 environment passed 23 core checks with 22 optional skips. CI now includes Python 3.14 for both core and the pinned optional integration.

Checkpoint lesson: reserve capacity before retaining work in an executor queue, and preserve the reservation until the real worker finishes. Verify asynchronous cancellation behavior on every supported runtime and separate clean installs from host-wide dependency state. Benchmark acceptance also needs native command exit status and owned descendant cleanup; parsing an `OK` line alone can certify a failed command incorrectly.

## Next quality gate

Collect a larger consented corpus of genuine long agent sessions and annotate must-retain spans before tuning. Include queries requiring facts without direct lexical overlap, conflicting revisions, and facts whose exact source matters. Compare answer correctness and latency against protocol-preserving head/tail and model-based baselines at the same forwarded-token budget. Current measurements do not establish a general recall rate or a mature optimum.

## 0.10.0 structured records and portable agent controls

A pre-release review found that splitting long JSON lines and ranking routine field-name overlaps above rare identifiers could omit linked evidence. The candidate keeps valid JSON lines up to 2,048 characters atomic and gives each query term an inverse-frequency weight. No dependency, model request, persistent state, or configuration option was added. Malformed and longer lines retain bounded text fallback; exact active work and the four-cycle cache boundaries are unchanged.

Three authored development cases were fixed by an independent author before the algorithm change: warehouse disposition, build compatibility, and museum climate audit. At the same 900-token estimate, required exact-record retention rose from 8/14 on 0.9.1 to 14/14. On the public research correction chain at a 1,500-token estimate, retention rose from 1/6 to 6/6. JSON-only achieved 4/6 and rarity-only 1/6 on that chain. These are now public development inputs, not held-out generalization evidence. Creation-time metadata is retained in [the fixture](../benchmarks/structured_evidence_cases.json); its initial private status describes creation, not current accessibility.

| Variant | Three-case exact records, target 900 | Research exact records, target 1,500 |
|---|---:|---:|
| 0.9.1 | 8/14 | 1/6 |
| Atomic JSON only | 14/14 | 4/6 |
| Inverse-frequency weight only | 8/14 | 1/6 |
| Both changes | 14/14 | 6/6 |

The estimate is `ceil(len(json.dumps(messages)) / 4)`, not a provider tokenizer. Source hashes, per-case budgets, and ablations are in [the replay report](results/structured-evidence-2026-10-15.json). Run `python -m unittest discover -s tests -p test_structured_evidence.py -v` against the installed candidate to reproduce the three-case retention, immutability, neighboring diagnostic and malformed-input checks. A single 720,653-estimated-token structured screening input used 0.94 process CPU seconds versus 0.69 previously. Both retained the needle under budget; this change has a measured CPU cost. Structured 18/19/20-cycle replay retained the earlier prefix byte-for-byte within one boundary. A subsequent isolated LiteLLM 1.103.0 live 34/35/36-cycle sequence returned the correct newest failure each time with normal stop outcomes. Forwarded estimates were 19,475/21,464/23,453, provider input 21,366/23,646/25,926, and cached input 0/21,362/23,642. Independent gateway and engine logs match all three requests, decode counts and cache arithmetic, without truncation. Buffered response times were 18.63/4.07/3.98 seconds; these are not first-token times or a matched performance comparison. [Selected cache check](results/structured-cache-2026-10-15.json).

The portable research control with Claude Code 2.1.251 completed in 118.97 seconds, with a real two-test failure-to-pass loop, exact seven-record citations, unchanged noneditable files, normal native terminal, and all four post-run visible/gold assertions passing independently. Mean client-reported TTFT was 1.480 seconds over eight samples. Engine-window weighted decode throughput was 44.95 tokens/s across nine completions and may include auxiliary client calls. Its nine local-route audits were below target (maximum 10,753 estimated tokens), with no compaction. This is harness/control evidence, not a Sift savings comparison. The preceding attempt lost native output on a parser error and remains rejected; its passing artifact cannot replace missing terminal/test-loop evidence.

Fresh Windows Codex homes could not provision their sandbox. The missing-directory and missing-setup-marker attempts remain rejected. The portable runner now performs a model-free native workspace permission probe before inference and records readiness failures without a model call. The model-free Linux Codex 0.154.0 readiness probe, using its official bundled resources, passed through WSL. No global sandbox settings or setup markers were changed. The model-free gate accepts EACCES/EPERM/EROFS for the owned outside-write denial and rejects unrelated I/O errors. Longer native acceptance and paired whole-task measurements remain open.

The subsequent native Linux Codex research control completed normally in 128.14 seconds and produced a correct artifact with six exact citations and clean edit scope. All four combined visible/gold tests passed independently. It remains **rejected** because the client combined both unittest commands with other shell work and masked the failing baseline exit status. The strict standalone-loop gate recognized zero test calls. Ten gateway audits and ten engine completions showed zero compactions, at most 19,202 forwarded estimated tokens, and 42.98 weighted decode tokens/s. Codex JSONL exposes no verified TTFT, so it remains unavailable. The prompt was clarified for later, different tasks; this rejected research run was not retroactively accepted or retried. [Control summaries and preserved failures](results/native-research-controls-2026-10-15.json).

A four-run authored build pilot is [predeclared](results/native-build-pilot-plan-2026-10-15.json) with fixed fixture/source hashes, two native clients, Sift/whole-unit-recency arms, cold engine starts followed by natural within-task cache reuse, identical budgets and all seven predeclared gold checks. Its initial plan is not a completed comparison or a result. LiteLLM's framework first-chunk timestamp can include empty/header events and even fall back to the end timestamp; it is not substituted for verified first-token latency. Missing native Codex TTFT is kept unavailable.

The first planned Claude/Sift build attempt failed before generation: two short, uncompacted Anthropic requests reached the Qwen template, which rejected a later system-message position. No source file changed and the native terminal is an error. Inspection of LiteLLM 1.103.0 confirmed that its adapter preserves in-sequence instruction positions, with no placement flag; demoting system roles would change the request and was rejected as a fix. The isolated benchmark now uses the same explicit Qwen/Anthropic instruction placement profile as the existing local gateway, before either selector. It preserves objects, roles/content and within-group order while deliberately moving instructions before dialogue. This profile is separate from Sift's product behavior and is not general equivalence for arbitrary late instructions. Actual native-adapter regression checks placement, tools/caps and immutability on both arms. The [revised plan and retained initial failure](results/native-build-pilot-revision-2026-10-15.json) preserve the original declaration and unchanged fixture/acceptance conditions. No completed paired result is claimed yet.

Release CI 38813211144 caught an environment assumption: the pinned image and official PyPI wheels both report LiteLLM 1.103.0 but contain different Anthropic adapter source. The image preserves late system roles; PyPI adds a mid-conversation-system capability check and can demote unsupported late systems to user. The original regression incorrectly assumed the image's unprofiled output in both environments. Its requirement is now expressed directly against the original input: after the explicit profile, BASE/LATER instructions must both retain system role and exact text, followed by TASK user content, with unchanged tools/caps/temperature and caller data. Runtime profile and product source did not change. [Verified source and wheel hashes](results/litellm-build-provenance-2026-10-15.json) preserve this failed release gate; fresh clean-package CI is required before release.

That release gate subsequently passed: main CI 38813888559 and tag CI 38814264306 both succeeded, including installed LiteLLM 1.103.0 integration on Python 3.13/3.14 with all 67 checks and no optional skips. Core-only CI also passed on Python 3.11 through 3.14. Version 0.10.0 remains an experimental prerelease. The clean Python 3.14 wheel install discovered 67 checks, passed 39 core checks and skipped 28 optional integration checks; the pinned image ran all 67 against the explicitly unpacked wheel because that image has no pip. The 22,286-byte wheel has SHA256 `bb7b784b92a1159e51f77fdeb960ab6f0dd2af4f53e32c0dd6d1443e523bca79`. All four vendored Subroute modules match the peeled release commit and wheel; 35 focused Subroute checks pass. Running Subroute gateways were not reloaded from the shared dirty checkout.

## Fresh screening of frozen releases, 2026-10-15

An independent author fixed six small private cases after 0.10.0 was frozen. The algorithm author stayed blind to the case text and answers during the original comparison, and neither release was tuned during scoring. The input hash was declared before comparison. The cases cover revision dependencies, CSV, low lexical overlap, source indentation, protected parallel work, and structured tool-cycle append stability. They are AI-authored screening data, not consented real agent traces or a representative quality benchmark. The cases have since been opened for development and are permanently retired from unseen validation.

| Frozen release | Exact required spans | Cases retaining every required span | Budget / immutable / protected passes | Append-prefix checks |
|---|---:|---:|---:|---:|
| 0.9.1 | 5/14 | 2/6 | 6/6 each | 2/2 |
| 0.10.0 | 8/14 | 3/6 | 6/6 each | 2/2 |

All six inputs required compaction, every required span set could fit alongside protected context, and neither version raised an exception. Targets ranged from 800 to 2,200 estimated tokens to exercise extraction on small inputs; these are not retention measurements at the deployed 24,576 target. The counter used a serialized-character estimate, not a provider tokenizer. Version 0.10.0 still omitted six required spans and failed full retention on half the cases. The favorable 14/14 development result above therefore does not establish generalization or mature reliability. No model calls, answer accuracy, task cost or latency were measured here.

The [aggregate report](results/frozen-release-screening-2026-10-15.json) records declaration time, input/result hashes, exact release sources, budgets, feasible packing costs and denominators. The [exact frozen input](../benchmarks/retired_frozen_release_screening_2026-10-15.json) and [initial per-case results](results/frozen-release-screening-details-2026-10-15.json) now match those declared hashes and allow public replay against the tagged versions. Their metadata saying "private holdout" describes their original status only. Because they were opened for algorithm development, future validation needs newly fixed, unseen cases.

An unreleased source-slice correction preserves original spacing in selected CSV and Python excerpts and bounds neighboring context across blank gaps. On the now-retired cases it raises exact span retention from 8/14 to 11/14 and complete cases from 3/6 to 5/6, with six budget, immutability and protected-context passes and two append-prefix passes. All three low-overlap handover spans still fail. In a paired synthetic 979,060-estimated-token CPU screen, both versions took about 1.8 process seconds per call; this is not a live prefill result. The candidate passed 70/70 offline tests in a separate LiteLLM 1.103.0 container. See the [candidate report](results/source-slice-candidate-2026-10-15.json). It requires new unseen cases and accepted agent tasks before a wider effectiveness claim.

A new six-case synthetic screening was fixed privately after the candidate core hash was recorded. Required evidence fit every target. The candidate and frozen v0.10.0 each retained 8/15 exact spans and completed 2/6 cases; each passed all six budget, immutable-input and protected-context checks and both append-prefix checks. The candidate therefore showed no gain on this unseen set. The [aggregate blind-screening report](results/source-slice-blind-screening-2026-10-15.json) records declared hashes, targets, denominators and limits. Raw cases remain private, so public readers cannot reproduce the per-case result. These cases are not being used to tune this candidate.

## Completed frozen native build pilot, 2026-10-15

The revised four-run pilot above is complete. Every run used the same public authored build-planner fixture, six visible and seven predeclared gold methods, frozen runtime hashes, a 24,576-estimated-token input ceiling, a 4,096-token output cap and a fresh idle-engine restart. Claude Code 2.1.251 and native Linux Codex 0.154.0 are the clients; all inference used the same local Qwen model. No delivered artifacts were repaired and no acceptance checks changed between arms. The initial pre-generation compatibility failure remains in the revised plan, separate from these four generated-artifact trials.

| Client / selector | Native time, seconds | Mean client TTFT, seconds (samples) | Engine weighted decode tokens/s | Requests / compacted | Final acceptance |
|---|---:|---:|---:|---:|---|
| Claude / Sift | 392.48 | 2.650 (16) | 43.57 | 17 / 1 | Rejected: three malformed-input subcases |
| Codex / recency | 246.19 | Unavailable | 43.27 | 17 / 0 | Rejected: two malformed-input subcases |
| Claude / recency | 847.01 | 5.974 (39) | 42.18 | 40 / 22 | Rejected: two malformed-input subcases |
| Codex / Sift | 183.53 | Unavailable | 43.98 | 14 / 0 | Rejected: three malformed-input subcases |

All four have normal native completion, a real standalone failing-to-passing test loop, clean scope and six passing visible tests. Independent acceptance still rejects every artifact for malformed directly supplied targets. These are four trials of one development task, not four independent tasks or a general success-rate estimate.

Chronology limits causal conclusions. Claude/Sift's only compaction followed its last source edit and final visible-test request; no source edit followed it. Both Codex runs stayed below target, so their time difference occurs without any selection. Claude/recency did make six successful edits after its first compaction, but replaying the edit trace shows that its defective validator already existed before compaction and remained unchanged. It also encountered four denied diagnostic/version commands under the same per-client permission profile. Different generated paths, requests and output lengths therefore prevent attribution of the elapsed-time difference to Sift. This pilot does not establish successful artifact construction under Sift compression.

Posthoc engine accounting matched complete prompt/decode/release records by slot/task ID. For these untruncated logs, full prompt is inferred as `release_n_tokens - generated_tokens + 1`, and cached prompt as full minus newly evaluated prompt tokens. These inferred quantities reconcile exactly with client aggregates, including Claude's model-wide totals. Main-turn Claude usage excludes an initial auxiliary call with 1,470 prompt tokens and 126/179 generated tokens respectively; that arithmetic is consistent with the auxiliary call but lacks a client/server request-ID join.

| Client / selector | Inferred full prompt | Newly evaluated prompt | Inferred cached prompt | Engine generated, including auxiliary calls | Total selector thread CPU, ms |
|---|---:|---:|---:|---:|---:|
| Claude / Sift | 213,541 | 34,313 | 179,228 | 15,016 | 168.63 |
| Codex / recency | 271,417 | 23,243 | 248,174 | 9,402 | 141.00 |
| Claude / recency | 804,633 | 293,419 | 511,214 | 25,290 | 1,632.30 |
| Codex / Sift | 187,738 | 17,617 | 170,121 | 6,979 | 91.62 |

These are totals over different task paths, not equal-workload token savings, provider wire-usage receipts or bills. All artifacts failed acceptance, so no cheaper successful-task claim is supported. The [complete aggregate report](results/native-build-pilot-2026-10-15.json) preserves sources, fixture/artifact/evidence hashes, estimated counts, client usage, chronology and limitations. Raw native traces remain private; fixture/source reproduction does not reproduce the original stochastic outputs exactly. After saving all logs, the dedicated benchmark gateway was removed and the existing Qwen engine left running idle with unchanged configuration. Running Subroute production and staging gateways were not reloaded.

## Native research-evidence selector stress pilot, 2026-10-15

A separate public research-audit development task passed visible and independent gold checks in one full-context, one Sift and one recency Claude Code run. Sift and recency used the same predeclared 8,192-token stress target; the Sift default at experiment time was 24,576. The current source candidate changes that default to 32,768. All inference used local Qwen3.8-27B, and the engine cache was shared and not reset.

| Arm | Accepted | Task seconds | Mean client TTFT (samples) | Engine weighted decode tok/s | Requests compacted |
|---|---:|---:|---:|---:|---:|
| Full | Yes | 97.10 | 2.656 (6) | 45.32 | 0/7 |
| Sift, 8K target | Yes | 108.29 | 4.891 (5) | 45.40 | 2/6 |
| Recency, 8K target | Yes | 133.02 | 2.840 (8) | 45.63 | 4/9 |

Sift compacted before the evidence artifact edit and preserved the accepted result. In this one fixed-order run its task time and mean TTFT were higher than full context, even though its client-reported total input-plus-cache tokens were lower. The engine processed more prompt tokens under Sift, while reported cache reads were lower. This flags prefix reuse for investigation, but task paths and cache state differed, so it is not a causal speed estimate. API spend was $0 for all arms; hardware costs and any Astra bill were not measured. See the [full pilot](evals/native-research-pilot-2026-10-15.md), [predeclared plan](evals/native-research-pilot-plan-2026-10-15.json), and [machine-readable data](results/native-research-pilot-2026-10-15.json).

## Query-independent epoch coverage development screen, 2026-10-15

The frozen-release screen showed that a source-fidelity repair did not improve
weak-overlap narrative retrieval. Following an Advisor recommendation, the
unreleased `0.11.0.dev0` candidate now reserves one optional excerpt per
completed four-cycle epoch. It chooses the best signal-bearing source excerpt
without query terms during the existing ranking pass, replacing the lowest
ranked query-selected excerpt. Diagnostic evidence, the protected task, and
the active tool cycle retain priority. The rule adds no dependency, service,
model call, configuration, or extra candidate scan.

The public synthetic fixture was fixed and hashed before either selector was
scored. Each of six cases contains nine tool cycles, query-word distractors,
and one exact weak-overlap span in the first four-cycle epoch. The target is
4,000 estimated tokens using `ceil(len(json.dumps(messages))/4)`, which is a
character estimate rather than a provider tokenizer. The baseline is core
SHA256 `010b7dda0336362d0334fc7054c2957ce40bbee86a07647f83ff8e01b2165f18`;
the candidate is `6c856b8bebc61c9ade96c1f6bc51438dffa1c9b9cc86f9ec0d12872619ea3003`.

| Selector | Exact spans | Complete cases | Budget | Task/latest cycle/input invariants |
|---|---:|---:|---:|---:|
| Baseline at `3bc15e3` | 0/6 | 0/6 | 6/6 | 6/6 each |
| Coverage-reserve candidate | 5/6 | 5/6 | 6/6 | 6/6 each |

The candidate misses the refund-retention span. These cases are now public
development data and must not be called held-out validation or tuned until
they appear better. They measure exact span retention, not model answers or
agent task success. The [baseline report](results/coverage-reserve-baseline-2026-10-15.json),
[candidate report](results/coverage-reserve-candidate-2026-10-15.json), and
[fixture](../benchmarks/coverage_reserve_cases.json) preserve the denominators
and hashes.

A separate CPU screen used 991,386 estimated input tokens, 72 tool cycles,
and a 24,576 target. Three alternating runs measured median selector process
CPU of 1.047 seconds at baseline and 1.000 second for the candidate. The
4.5% difference is within this small local run's timing noise; it is not an
inference latency or cache result. The [performance report](results/coverage-reserve-perf-2026-10-15.json)
and [replay script](../benchmarks/coverage_reserve_perf.py) define the setup.
All 75 repository tests passed with 24 optional skips. This supports keeping
the change as a development candidate, not claiming general reliability or a
performance win. An independent read-only review found no must-fix invariant
violation and reproduced the 5/6 versus 0/6 retention result. Its separate CPU
rerun measured equal 1.031-second medians for baseline and candidate, rather
than the original 1.047-second and 1.000-second medians. The runs therefore
show timing noise, not a reliable CPU comparison. The reviewer also identified
the need to state the reserve policy and its limitation in the algorithm
contract; that documentation is now included there.

A GPT-6.1 Sol and Gemini 3.8 Flash council review recommended keeping this
candidate unreleased and testing it on a small independently authored, blinded
paired set before further tuning. The proposed set should include weak-overlap
required facts competing with query-relevant evidence, and measure exact-span
retention, critical-context eviction, accepted task success, invariants, and
selector CPU. Stop promotion for a protected-context or budget invariant
failure, critical-context eviction, or reproducible task-success regression.
The consultation used 3,190 prompt, 106 completion, and 3,296 total tokens for
Gemini, and 682 prompt, 176 completion, and 858 total tokens for Sol. The
review reinforced the existing decision to freeze this implementation and
change only from verified failures. Fresh independently authored cases and
accepted agent tasks remain necessary.

### Reproduced query-echo miss and development fix, 2026-10-16

Inspection of the failed `refund_retention` case found a concrete false
positive: the task query's word `must` appeared in distractor excerpts, so a
query-independent reserve selected one of those distractors instead of the
required retention instruction. The candidate now requires a matched signal
that does not occur in the task query; `retain`, `retention`, and `shred` are
eligible signals for this reserve. This repairs the known miss on the same
public cases that exposed it. It may miss useful evidence when every available
signal overlaps the query.

The fixed candidate retains 6/6 exact spans and completes 6/6 cases. Budget,
protected task, latest tool cycle, and input immutability checks pass 6/6.
These are tuned public development cases, not a blind test, generalization
result, or model-answer/agent-task quality measure. The report records core
SHA256 `c37f84829cf75a38f410e4eebb219ebf99c27c89a5c0b62a0ca9b70c36265de7`.

As a supplemental tokenizer check, the six compacted requests were counted
without inference by the local Qwen 3.8 27B llama.cpp server's exact rendered
prompt-token endpoint. Counts ranged from 1,995 to 2,085, below the 4,096
comparison cap. This is not the selector's own counter, a latency measurement,
or evidence that the selected context improves answers. The machine-readable
[fixed development report](results/coverage-reserve-query-echo-fix-2026-10-16.json)
contains selector estimates and invariants; the exact tokenizer counts were
collected separately and must not be confused with its 4,000 estimated-token
target.

The next gate remains a newly authored, blinded paired set with weak-overlap
targets competing against query-relevant evidence, critical-context eviction
checks, and accepted agent-task outcomes. A shorter prompt alone does not
establish sharper answers, less drift, or lower end-to-end cost.

## Direct answer probe with LLMLingua-2, 2026-10-16

To check whether retention translated into answers, I sent the six already
public coverage-reserve cases through one local Qwen 3.8 27B IQ3_S completion
per arm. Arms used the same answer wrapper, temperature 0.7, top-p 0.8, top-k
20, seed, 256-token output cap, and disabled thinking mode. Arm order was
randomized per case. Sift and recency had a hard 4,096 **exact Qwen prompt-token**
cap; full context had the 28,672 input limit. LLMLingua-2 compressed historical
tool text with its 2,800-token target and ran as a text-only baseline. Its
requests were also checked with the exact Qwen tokenizer before inference.

| Arm | Required-answer marker checks | Required spans retained | Mean exact prompt tokens |
|---|---:|---:|---:|
| Full context | 5/6 | 6/6 | 13,034 |
| Sift | 3/6 | 6/6 | 1,990 |
| Complete-unit recency | 0/6 | 0/6 | 2,775 |
| LLMLingua-2, text-only | 1/6 | 0/6 | 3,742 |

This is direct evidence that exact retention did not guarantee a usable answer
in this sample: Sift kept every required string, yet Qwen missed three answers
that full context answered correctly. Full context also missed the timezone
case, where query-echo distractors competed with the answer. LLMLingua-2
answered the refund question correctly without retaining its exact source
sentence. Those examples argue for scoring downstream answers and tasks, not
just retained spans.

Inspection of Sift's three false-negative prompts found one repeated pattern:
each quoted the same later query-echo distractor from source message 8 in three
overlapping excerpts. That text repeats the task wording and says “reference
only, no value or instruction recorded,” while the required fact appears once
in an earlier excerpt. This is a plausible attention/conflict mechanism and
repeated text waste, not a proven cause. The cases are exposed, so the current
candidate stays frozen; a future blinded evaluation should measure overlapping
excerpt duplication and answer quality before any repair is promoted.

The six cases were already visible and used to fix the selector; they are
synthetic development data, not a blind sample. Each cell is one stochastic
completion, marker checks are not human-reviewed task acceptance, and no
latency or Astra bill was measured. The run also emitted a Transformers
warning about a 1,440-token sequence exceeding the compressor tokenizer's
512-token setting, although compression completed and no arm request failed.
Treat the LLMLingua result as a preliminary text-only screen until that warning
and a newly authored held-out evaluation are addressed. The [machine-readable
report](results/llmlingua2-development-2026-10-16.json), [invalid first
attempt](results/llmlingua2-development-invalid-output-cap-2026-10-16.json),
[runner](../benchmarks/llmlingua2_development.py), and [isolated dependency
lock](../benchmarks/llmlingua2-development.lock) preserve the result and setup.

The Qwen API spend was $0; the temporary CPU compressor used about 46.85
seconds of wall time per case on average (42.76 to 48.08 seconds). That is not a monetary cost comparison. The
next action is the held-out, paired task protocol, not tuning against these six
answers.

### Native operations incident task screen, 2026-10-16

I ran the public fictional incident-reconstruction task through Claude Code
2.1.251 with local Qwen3.8-27B IQ3_S, the current Sift source, and a
24,576-token estimated target. Inputs and the independent gold test were
hash-frozen before the randomized recency, Sift, full order. This is a public
development fixture, not a blind quality result.

| Arm | Accepted | Native time | Client-reported mean TTFT | Terminal outcome |
|---|---:|---:|---:|---|
| Recency | No | 398 s | 7,168 ms (21 samples) | Claude Code reported a 32 MB conversation limit; one request also received Sift's 413 for an oversized active tool cycle. |
| Sift | No | 69 s | 5,698 ms (6 samples) | Claude Code reported the 32 MB conversation limit; no artifact was written. |
| Full context | No | 48 s | 2,859 ms (6 samples) | 34,555 prompt tokens exceeded Qwen's 32,768-token context. |

All three outcomes failed acceptance, so these timing and usage observations do
not establish quality, speed, or savings. The Sift selector did compact an
observed 26,461-token request to 24,518 estimated tokens, but that did not
prevent Claude Code's later size error. Local provider API spend was $0;
electricity and hardware cost were not measured, and cost per accepted task is
unavailable. See the [machine-readable screen](results/native-incident-reconstruction-development-2026-10-16.json)
and [frozen fixture manifest](evals/incident-reconstruction-development-manifest-2026-10-16.json).
This surfaced a client-size boundary in this test setup, not evidence that
Sift caused the failure. The public task must be replaced with independently
fixed blind cases for a promotion comparison.

### LongBench v2 MiniMax 600-request sample, 2026-10-17

The frozen 100-question development sample ran to completion as 300 matched
requests per arm, with three repeats per question. Across 600 successful
provider usage receipts, MiniMax reported 32,527,062 prompt and 1,239
completion tokens. Full context used 24,245,610 prompt tokens; Sift used
8,281,452 (65.84% fewer). Full answered 117/286 scorable responses correctly
(40.91%) and Sift 106/290 (36.55%). Equal-task-weighted accuracy was 39.83%
and 36.67%; task majorities were 40/100 and 34/100. There were 18 Full-only,
12 Sift-only, 22 both-correct, and 48 neither-correct tasks.

Across the same 600 receipts, OpenRouter reported cache-inclusive upstream
inference costs of $3.23171004 for Full and $1.28419728 for Sift (60.26% lower
for Sift). These BYOK `cost_details` are upstream estimates, not invoice-
verified charges; OpenRouter's top-level `usage.cost` was zero. Cached prompt
shares differed (69.47% Full and 60.44% Sift), and five ambiguous original
attempts have unknown costs that are excluded. Treat this as an observed
receipt-cost difference for this cache state, not a general dollar-savings rate.

Five original requests had ambiguous network failures and no provider usage
receipt. Each was retried once and succeeded; unknown usage from the original
attempts is not counted as zero. Five successful responses ended at the output
limit and were unscorable. All 100 task IDs were previously exposed during
development, so this is not a blind holdout. Three repeats per task are
clustered observations. This is a completed 100-question sample, not all 503
LongBench v2 questions and not 600 unique questions. It does not establish
quality parity, general cost savings, or accepted Claude Code/Codex task
quality. See the [complete protocol and audit](evals/longbench-v2-minimax-600-runner-2026-10-19.md)
and [aggregate result artifact](results/longbench-v2-minimax-600-2026-10-19.json).

### LongBench v2 sample preparation, 2026-10-16

To test long-context answer accuracy on an external public benchmark, I pinned
the Apache-2.0 `zai-org/LongBench-v2` dataset at revision
`2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`. The 465,490,535-byte `data.json`
matched SHA-256
`15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2`. Using
the local Qwen tokenizer endpoint, a deterministic rule froze 23 cases across
all six categories before generation: 16 have exact full prompts above the
24,576 Sift target and below the 28,672 full-input cap; seven are below target
as no-op controls. The model and selector have not seen generations for this
sample.

This is a focused diagnostic set, not enough to establish general parity or a
top-percentile claim. The preparation scan tokenized only rows with context up
to 500,000 characters; 202 longer rows were excluded by this prefilter, and
all 23 selected rows are in the dataset's `short` length category. The
[selection manifest](evals/longbench-v2-qwen-screen-2026-10-16.json) records
IDs, answer keys, prompt hashes, exact counts, categories, and the frozen Sift
source hash. The [preparation script](../benchmarks/prepare_longbench_v2.py)
verifies the pinned data hash and refuses to overwrite the selection. No model
calls or cost were incurred during preparation.

### LongBench v2 structured-choice rerun, 2026-10-16

The first 128-token scoring pass is retained only as a harness diagnostic: seven
outputs hit the cap, mostly with full context, and the report kept only the
first 500 answer characters. Those counts are not a valid quality comparison.
Before rerunning, a local smoke test and a 12-call pilot verified strict JSON
Schema choice output. The frozen protocol then ran all 23 cases, four arms,
three randomized repeats, with no retries, no prompt cache, and a 16-token
structured output cap. All 276 outputs parsed as one A-D choice and ended
normally. The [protocol](evals/longbench-v2-qwen-structured-protocol-2026-10-16.md),
[pilot](results/longbench-v2-qwen-schema-pilot-2026-10-16.json),
[runner](../benchmarks/run_longbench_v2.py), and
[full report](results/longbench-v2-qwen-schema-2026-10-16.json) retain settings,
hashes, per-call outputs, token counts, timing, and preprocessing cost.

For the 16 above-target cases (48 repeated completions per arm), the result was:

| Arm | Exact answers | Mean Qwen input tokens | Mean TTFT | Mean decode speed | Preprocess wall time per case |
|---|---:|---:|---:|---:|---:|
| Full context | 20/48 (41.7%) | 26,822 | 18.69 s | 36.73 tok/s | — |
| Sift | 15/48 (31.3%) | 19,347 | 13.42 s | 38.55 tok/s | 0.44 s |
| Naive recency | 13/48 (27.1%) | 221 | 1.23 s | 42.17 tok/s | 0.10 s |
| LLMLingua-2 text-only | 21/48 (43.8%) | 17,875 | 11.94 s | 38.48 tok/s | 52.42 s |

Sift reduced the mean local Qwen input by 27.9% and reduced mean model TTFT by
28.2% in this cold-prefix-cache screen. Under the official answer keys, full
context scored 20/48 and Sift 15/48 on the 16 above-target cases. The five
paired official-key losses and no wins occurred on two public long-dialogue
aggregation questions, so the 48 repeated outputs are not 48 independent
tasks. In the seven below-target controls, Sift, full, and recency had identical
prompt-token counts and the same answer on all 21 paired outputs. The score
gap is an investigation signal, not a broad quality estimate.

A source audit of the first affected case supports its official key: the
per-player history says `player_7` bid 40 in round four, the highest of the ten
player logs, and the key is `player_7`. In the reconstructed Sift prompt, the
player ID and bid appear in separate excerpts; none of the 20 `round_records`
objects is preserved as a whole excerpt. That is concrete evidence that this
compaction can separate an entity from its value, while the three repeated
answers remain one task-level observation.

The second case's key is unresolved. Summing the per-player history's logged
receipts gives `player_2` 158, who is not an offered choice. Among the offered
players, `player_4` has 156 and `player_7` has 153, while the official key is
`player_7`. The aggregate `round_records` contain response vectors without
player IDs, so they cannot independently settle the mapping. Keep the frozen
official score unchanged and show sensitivity: excluding only this uncertain
case gives full 18/45 versus Sift 15/45; excluding both audited cases gives
15/42 for each. This is not a re-score and does not establish parity.

The [reproducible row audit](../benchmarks/audit_longbench_v2_rows.py) checks
the pinned data and reconstructs Sift's excerpts; its [machine-readable
output](results/longbench-v2-gold-audit-2026-10-16.json) retains the source
facts and score sensitivities. Keep the core frozen. The current next quality
gate is the independently checked [natural-agent pilot](evals/natural-agent-pilot-2026-10-16.md).
The earlier [relation-binding pilot](evals/relation-binding-pilot-2026-10-16.md)
remains unrun after its case-authoring attempt failed its length and gold-pointer
checks.

For a post-hoc task-level diagnostic, strict majority over each case's three
existing repeats yields 5 tasks correct in both arms, 2 full-only, 0 Sift-only,
and 9 neither. Excluding the label-uncertain second audited row leaves 5 both,
1 full-only, 0 Sift-only, and 9 neither. Excluding both audited rows leaves 5
both-correct and 9 neither, with no discordant tasks. This aggregation was not
predeclared and is descriptive only; the three repeats do not increase the
independent task count. One full-only task is the source-supported relation
loss described above. These data do not establish a general task-quality gap,
but they do show a concrete case where extraction changed a correct answer.
The preregistered relation-binding diagnostic has not run: its authored prompts
were below the Sift trigger and all gold pointers failed independent validation.
The next effort is the [natural-agent pilot](evals/natural-agent-pilot-2026-10-16.md),
which must first represent long context across prior turns and tool results.

The recency baseline is not a meaningful competitor on this data shape: the
single historical context is one large user message, and the baseline drops
most of it entirely when over budget. LLMLingua-2 emitted a Transformers warning
that the 31,053-token source exceeded its 512-token encoder limit. Its result is
therefore only a diagnostic comparator, not a validated quality or runtime
baseline. All model calls used local Qwen and cost $0 in provider API spend;
the times above are not Astra measurements. See the separate
[Astra cost comparison](cost-comparison.md).

### LongBench v2 Qwen extension, 2026-10-16

The [frozen extension protocol](evals/longbench-v2-qwen-extension-protocol-2026-10-16.md)
selected all ten remaining above-target rows that fit the full-input cap,
without manual exclusions. The completed randomized run made three calls per
case and arm, for 90 calls total. All 90 terminated normally and returned a
valid structured answer. The [machine-readable report](results/longbench-v2-qwen-extension-2026-10-16.json)
preserves every response, exact input count, timing, and selector cost.

| Arm | Exact answers | Mean prompt tokens | Preprocess / case | Mean TTFT | Mean decode speed | Mean endpoint + preprocess |
|---|---:|---:|---:|---:|---:|---:|
| Full context | 16/30 (53.3%) | 26,216 | <0.01 s | 18.15 s | 36.49 tok/s | 18.47 s |
| Sift | 15/30 (50.0%) | 24,544 | 0.55 s | 16.80 s | 34.75 tok/s | 17.69 s |
| Complete-unit recency | 15/30 (50.0%) | 260 | 0.11 s | 1.17 s | 42.37 tok/s | 1.55 s |

Strict task majority over the three repeats gives five cases correct for both
full context and Sift, no discordant cases, and five wrong for both. This is
descriptive evidence of neither a quality loss nor a quality gain on these ten
tasks; it is too small and public to establish parity or generalization. Sift
reduced mean prompt tokens 6.4% and mean TTFT 7.4%, with 4.8% lower mean decode
speed. Including Sift's measured preprocessing, mean endpoint-plus-preprocess
time was 4.2% lower. The small speed difference is not evidence that answers
got sharper. Recency drops almost all of the single historical user message on
these examples, so its 260-token average is a degenerate control rather than a
useful comparison. All calls used local Qwen, with $0 provider API spend;
electricity and hardware cost were not measured. These numbers do not establish
GPT-6 Astra savings.

### Context-budget Qwen development screen, 2026-10-16

The [development report](evals/context-budget-qwen-development-2026-10-16.md)
compares Sift targets of 8,192 and 16,384 on the same ten public LongBench v2
extension questions, then reuses the 24,576 result above. Each arm has three
generations per task. The public inputs have already been seen, so the screen
is useful for target sizing and latency exploration only.

At 8,192, mean exact input was 8,153 tokens and mean TTFT was 5.82 seconds;
full context used 26,216 tokens and had 17.71-second mean TTFT. The 16,384
target used 16,357 tokens and had 10.80-second mean TTFT. Task-majority scores
were five of ten for both Sift and full context at all three targets. The
16,384 paired table had one full-only and one Sift-only task; the 8,192 and
24,576 tables had five both-correct and five neither-correct tasks. These
small, public results do not establish noninferiority or justify changing the
default.

Applying Astra's current standard short-context $10/M input rate to the local
mean token counts gives an illustrative input-only charge per request of
$0.2622 full, $0.0815 at 8,192, $0.1636 at 16,384, and $0.2454 at 24,576. These
are not provider bills. The experiment used local Qwen, disabled prompt
caching, and did not measure Astra usage. See the [official rates](https://developers.openai.com/api/docs/pricing)
and the [raw 8,192](results/context-budget-qwen-8192-2026-10-16.json) and
[16,384 results](results/context-budget-qwen-16384-2026-10-16.json).

### Native network-audit MiniMax development comparison, 2026-10-16

On one exposed synthetic operations task, the no-Sift arm completed and passed 7 visible plus 20 independent gold tests in 88.8 seconds. The Sift arm at 16,384 estimated tokens compacted 81 requests, reducing selector estimates by 88.2% in aggregate, but reached the 80-turn client limit without editing the implementation or creating its required report. Its native task time was 394.3 seconds and its client-reported MiniMax cost was $3.225 versus $0.588 for full context. This rejected run is a useful negative development result; it does not establish that compaction alone caused the behavior or that Sift is generally slower or more expensive.

Repricing those particular MiniMax usage totals at GPT-6 Astra's standard short-context rates gives an illustrative $1.140 full-context and $6.424 Sift. It is arithmetic from another model's usage, not an Astra run or a cost-per-accepted-task result. The task is retired from unseen evaluation, and the next quality comparison needs a newly authored frozen case. The [report](evals/native-network-audit-development-2026-10-16.md) and [machine-readable result](results/native-network-audit-minimax-m3-2026-10-16.json) include the full qualifications and usage breakdown.

### Stable history anchor development check, 2026-10-16

A query-shift review found that a new user question can reorder the entire older-history summary. The unreleased candidate puts one query-independent historical anchor in its own message before the query-ranked excerpts. The anchor uses at most one eighth of the target and is dropped when it would crowd the active work. Structured records that share a prefix are excluded to avoid duplicating table headers. Query-aware excerpts remain separate and continue to change with the question.

Two deterministic regressions cover ordinary history and a 48-cycle tool transcript. For both payment-to-incident topic shifts, the first summary message is byte-identical, while the following query-ranked message changes and retains the matching fact marker. Both runs stay within their 2,000- and 6,000-token test budgets. These are synthetic selector tests using the test counter; they do not establish provider cache hits, lower billed cost, or no quality regression on natural histories. A GPT-6 Advisor council endorsed this as a fixed-budget pilot and required provider-route cache and accepted-task evidence before adoption claims. Keep it unreleased pending replay on frozen natural traces and paired provider measurements.

### Native Claude Code least-privilege context calibration, 2026-10-16

A single exposed development task was tested once per arm at 24,576 and 16,384 tokens. At 24K, Sift completed and passed independent checks but did not compact before the edit, so the run does not demonstrate a Sift effect. At 16K, Sift compacted, then returned two HTTP 413 errors because the active task or latest tool cycle exceeded the target; it produced no edit or required artifact. Full context passed at both targets. The [calibration report](evals/native-agent-context-calibration-2026-10-16.md) and [machine-readable results](results/native-agent-least-privilege-rollup-context-calibration-2026-10-16.json) preserve per-arm acceptance, task time, client-reported TTFT and usage, and the limitations. Tokens per second were not captured. Local Qwen incurred no provider API charge; the Astra figures are usage arithmetic only and not measured Astra costs. This is a concrete 16K boundary failure and an unqualified 24K Sift pass, not evidence that Sift generally helps or hurts.

### Native MiniMax M3 least-privilege diagnostic, 2026-10-16

The corrected OpenRouter M3 profile completed a fixed-order diagnostic on the
same exposed least-privilege rollup fixture. Full context and Sift at a 16,384
target both passed the same visible and independent gold checks. An independent
trace audit verified that Sift compacted request 29 before the first direct
edit, from 88,037 to 16,352 estimated tokens, with all four required source
spans present. Across 31 Sift requests, summed estimates fell 74.1%, but the
accepted task took 131.2 seconds and Claude Code reported $1.492, versus 63.3
seconds and $0.421 for full context. The Sift 24,576 arm did not compact; the
16,384 recency arm failed closed before editing. TTFT sample counts differed,
decode throughput was unavailable, and runs were not randomized or repeated.
This is one exposed development diagnostic, not a quality, speed, or savings
claim. See the [full report](evals/native-m3-least-privilege-rollup-2026-10-16.md)
and [machine-readable result](results/native-m3-least-privilege-rollup-2026-10-16.json).


## MiniMax LongBench v2 hybrid Stage 2, 2026-10-17

This completed evaluation covers 100 public LongBench v2 training-split tasks,
three repeats each, and 300 Sift responses through OpenRouter's
`minimax/minimax-m3` model with the MiniMax provider pinned. The option-aligned
relation matrix was enabled only for six previously audited in-sample task IDs;
unchanged default Sift was used for the other 94. All requests used a 32,768
token target, 128-token answer cap, no fallback, and no retry. Eight malformed
or incomplete billable answers were retained as incorrect; 292 were valid.

| Arm/reference | Exact answers | Task majorities | Provider prompt tokens | Cache-hit share | Upstream-reported cost |
|---|---:|---:|---:|---:|---:|
| Sift hybrid | 132/300 (44.0%) | 43/100 | 7,801,125 | 54.8% | $1.315868 |
| Historical Full | 117/300 (39.0%) | 38/100 | 24,245,610 | 92.3% | $1.901571 |
| Historical Sift | 104/300 (34.7%) | 31/100 | 8,281,452 | 94.3% | $0.611442 |

On this sample, the hybrid recorded 5.0 percentage points more exact answers,
67.8% fewer provider prompt tokens, and 30.8% lower observed pass-through cost
than the saved Full-context run. Against saved Sift it recorded 9.3 percentage
points more exact answers and 5.8% fewer prompt tokens, but its observed
pass-through cost was 115.2% higher ($1.315868 versus $0.611442). Historical
Sift had a 94.3% cache-hit share versus 54.8% for this hybrid run. Do not claim
a measured cost reduction versus Sift from this experiment; the comparison is
strongly cache-sensitive.

The first request through completion took 26m 32.1s, including the safe
checkpoint and later continuation. The resumed 207 requests took 10m 46.8s.
Per-request end-to-end median was 1.80s and p95 was 3.30s. The complete Stage 2
receipt total was $1.31586798. The remaining 207-request cost ($0.59055102)
matched the aggregate OpenRouter BYOK usage delta after the checkpoint. The
final task-scoped ledger is $16.20458423 of the user's $20 cap; the run stayed
below its $4 guard. OpenRouter BYOK counters are aggregate and unitemized, so
they are not an account invoice.

The historical Full and Sift runs are non-concurrent and use an earlier Sift
core; provider behavior and cache state may differ. These public training tasks
are development data, not a blind holdout or the full LongBench v2 suite. The
matrix was developed on its six evaluation IDs; only the hybrid policy receives
100-task coverage. Results do not establish a causal Sift effect, generalized
matrix quality, or native Claude Code/Codex task performance.

The [validated scorecard](evals/longbench-v2-minimax-hybrid-stage2-analysis-2026-10-17.md)
links the [analysis JSON](evals/longbench-v2-minimax-hybrid-stage2-analysis-2026-10-17.json)
and [gzip-compressed 300-response report](results/longbench-v2-minimax-hybrid-stage2-continued-2026-10-17.json.gz).
The raw report SHA-256 (compressed artifact) is recorded in the analysis JSON;
the gzip stream contains the exact 79,680,922-byte JSON used for analysis.
The [run protocol](evals/longbench-v2-minimax-hybrid-stage2-protocol-2026-10-17.md)
and [Stage 2 manifest](evals/longbench-v2-minimax-hybrid-stage2-manifest-2026-10-17-v3.json)
pin the prompt, route, source, and request-generation settings.
