# LongMemEval-V2 Sift adapter prototype — 2026-10-20

## Status

**Synthetic adapter plus prompt-build smoke with the actual reader processor. No benchmark data was downloaded, no model weights were loaded, no inference was run, and no score was produced.** This does not establish LongMemEval compatibility, quality, or blind validation.

The prototype targets official LongMemEval-V2 repository commit [`2cc8c540bdb87fe6761629b585e727e1c4704520`](https://github.com/xiaowu0162/LongMemEval-V2/commit/2cc8c540bdb87fe6761629b585e727e1c4704520). Its documented backend contract is `insert(trajectory)` followed by `query(question, query_image=None)`, returning text and/or image context items. The official trajectory preparer expects state text and screenshot paths; the harness can append a query image to its reader prompt. See the [memory interface](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/memory_modules/memory.py) and [trajectory normalization](https://github.com/xiaowu0162/LongMemEval-V2/blob/2cc8c540bdb87fe6761629b585e727e1c4704520/memory_modules/trajectory_store.py).

## What the local prototype checks

`benchmarks/longmemeval_v2_sift_adapter.py` maps the public and legacy trajectory shapes to ordered text messages, appends the question as the active user turn, and calls Sift's deterministic `compact_messages` API. It carries screenshot paths only for source states represented in the compacted result and fails when a required screenshot path is missing. The harness itself remains responsible for adding the question image to the reader prompt.

The prototype uses a UTF-8 request-size estimate divided by two, not the official Qwen reader tokenizer. It delegates input-size and raw-token bounds to Sift, whose defaults are 16,777,216 characters, 250,000 nodes, and 1,000,000 estimated raw tokens. Oversize input fails closed. Do not use this estimate for a benchmark comparison or leaderboard package.

Run the focused offline adapter checks with:

```powershell
py -3 -m pytest tests/test_longmemeval_v2_sift_adapter.py -q
```

The tests use synthetic Python fixtures, including temporary screenshot paths. They check both documented trajectory shapes, registration through a compatible registry function, query preservation, image-to-selected-state mapping, rejection when an official-required screenshot is absent, and rejection at the configured Sift bounds.

The synthetic smoke invokes `build_prompt_row` from the pinned official harness and checks the adapter query, context validation/counting path, Pillow decoding of a generated state image, inclusion and data-URL encoding of both state and question images, and the question-image log path. It verifies the harness Git blob against `6a7182440a2cdd3ace6286dd966f7953fc383e8e` before importing it. Unused CLI, registry and scoring imports remain stubbed; the reader processor is real. Only the state image is decoded by the tested harness helper; the question image is encoded and handed off. No benchmark records or model calls are involved.

### Real reader-processor probe (2026-10-21)

The processor is `Qwen/Qwen3.5-9B` at revision [`c202236235762e1c871ad0ccb60c8ee5ba337b9a`](https://huggingface.co/Qwen/Qwen3.5-9B/tree/c202236235762e1c871ad0ccb60c8ee5ba337b9a). The smoke verifies SHA-256 pins for exactly eight visible metadata files: `chat_template.jinja`, `config.json`, `merges.txt`, `preprocessor_config.json`, `tokenizer.json`, `tokenizer_config.json`, `video_preprocessor_config.json`, and `vocab.json`. This approximately 28 MB snapshot contains no model weights. Loading uses `local_files_only=True` with Hugging Face offline mode. The local runtime already had Transformers 4.57.1, torch 2.9.1+cpu, tokenizers, the Hub client and Pillow 13.0.0; no packages were installed for this probe.

Obtain the pinned harness and only the listed processor/tokenizer metadata in the local scratch paths, then run with that runtime:

```powershell
python benchmarks/longmemeval_v2_synthetic_harness_smoke.py tmp/longmemeval-synthetic-harness/harness.py --processor-dir tmp/longmemeval-synthetic-harness/qwen3.5-9b-c202236235762e1c871ad0ccb60c8ee5ba337b9a
```

The generated 2×1-pixel fixtures passed: **131 reader-context tokens**, two images handed off, zero model weights, zero model calls and zero benchmark records. The smoke independently recomputes the context count with the official helper and compares it with the prompt row. This initial probe exercised the under-budget branch. The pressure extension below covers generated fixtures only; full harness generation/scoring, dataset coverage, latency and accuracy remain unverified. Sift's own adapter still uses its approximate counter.

### Pressure and reader-plumbing extension (2026-10-21)

The same repeatable command now exercises the official prompt helper with a four-item synthetic text/image context and the actual pinned processor. Independent execution counted **9,165 original context tokens**; a limit of **89 tokens** kept the first two items (text and state image), dropped the tail text/image, and reproduced the same retained context on repetition. A one-token limit produced empty memory context while retaining the question image and query lifecycle. These are generated-fixture checks of upstream prefix truncation, not evidence that Sift preserves task answers under pressure.

The extension also invokes upstream `build_reader_request` and `call_reader_model_async` through an in-memory fake client with a synthetic answer and usage object. It checks request fields, answer extraction and usage handoff; these are not MiniMax usage receipts or real model results. Independent negative probes rejected zero/negative context limits and an empty fake reader response. External connections and DNS were blocked during review; Windows asyncio used its expected internal loopback self-pipe. There were no HTTP/provider requests, weights, benchmark records or inference.

### MiniMax request-construction policy (2026-10-21)

Upstream `build_extra_body` does not inject our provider policy. The pure helper in `benchmarks/longmemeval_v2_minimax_request_policy.py` now wraps the official request builder for the in-memory probe. It requires `minimax/minimax-m3`, a positive integer `max_tokens`, and nonstream responses; inserts `extra_body.provider` with `only=["minimax"]`, `allow_fallbacks=false`, and `require_parameters=true`; and rejects contradictory model/routing aliases or SDK controls hidden in `extra_body`. Inputs are deeply copied. The original upstream builder is restored in `finally`, including when the fake reader raises. The provider fields follow [OpenRouter's routing reference](https://openrouter.ai/docs/guides/routing/provider-selection); `require_parameters` excludes providers that cannot support the requested parameters.

Independent review passed **39 focused tests**, strict-type/alias/collision probes, exception restoration and the combined real-processor smoke, observing the pin at the fake client's call boundary. The smoke removed arbitrary penalty/top-k fixture settings and emits `request_provider_policy=PINNED` with `provider_requests=0`. To repeat the small policy suite locally:

```powershell
python -m pytest tests/test_longmemeval_v2_minimax_request_policy.py -q
```

This closes request construction only. That pure helper creates no SDK/HTTP client and does not validate endpoint acceptance, live token limits, returned usage, budget or authorization. The generated main and optional transport probes below cover additional bounded paths; they do not establish full harness compatibility, official leaderboard compatibility, real endpoint acceptance, or quality.

### Generated main, file and deterministic-scoring flows (2026-10-21)

`benchmarks/longmemeval_v2_synthetic_main_smoke.py` exercises the pinned
upstream `harness.main()` with generated question, trajectory, haystack and
memory-config files plus tiny generated images. It verifies the source
dependency closure against SHA-256 pins, imports the unchanged real memory
registry and adds Sift through its registry interface. Actual trajectory
normalization, prompt construction, output-file writing and `mc_choice_match`
scoring run for both shared-haystack and per-question-haystack paths.

Each path has two generated questions and an in-memory reader returning the
same generated choice, deliberately producing one correct and one incorrect
score. Four fake reader calls in total check request policy, image handoff,
synthetic usage aggregation and client cleanup. The processor is the same
pinned local Qwen metadata snapshot. These fixtures are plumbing checks, not
accuracy results, provider usage or spend.

The registry eagerly imports the Agents SDK even for Sift. An isolated
`tmp/longmemeval-synthetic-main/.venv` with system site packages uses
`openai-agents==0.24.0` and `openai==3.36.0`; the global runtime and live
LongBench environment are unchanged. The optional environment inherits
unrelated dependency conflicts, including LiteLLM's OpenAI version constraint;
those packages are not exercised, and this is not a generally validated
environment. The smoke removes the script-directory import shadow caused by
the repository's unrelated `benchmarks/agents.py`. Missing registry dependencies
produce a blocked result instead of successful stubs.

With the pinned upstream sources and processor metadata already present:

```powershell
tmp/longmemeval-synthetic-main/.venv/Scripts/python.exe benchmarks/longmemeval_v2_synthetic_main_smoke.py
```

Independent execution passed both main paths and four focused
prerequisite/import-shadowing/hash regressions. The network guard observed zero
external attempts and two Windows asyncio loopback connections. Global Python
truthfully returned the missing-Agents-SDK diagnostic with exit 2.

No source/data/package download or inference occurs in this command. External
connections are blocked by the probe. This closes these generated sequential
file/main/scoring paths only; parallel mode, save/load, LLM judges, real data,
real-provider endpoint acceptance and usage remain unverified.

### Optional SDK transport and returned-usage checks (2026-10-21)

`benchmarks/longmemeval_v2_minimax_transport.py` provides an optional explicit
client factory with the upstream `chat.completions.create`/`close` surface. SDK
imports are lazy. It pins the external destination to OpenRouter, disables SDK
retries and HTTP redirects, and applies the existing model/provider request
policy. Test mode accepts only a literal loopback URL and public fixture key.
Strict raw JSON checks precede SDK coercion, enforcing the returned model,
provider, text-response shape and caller-declared integer usage caps.

The helper computes an uncached Decimal token-rate estimate using the dated
rate snapshot. Optional `usage.cost` and
`usage.cost_details.upstream_inference_cost` are recorded separately; they are
never combined into a reported total. Missing/null amounts stay unknown, so
they do not gate our own calculation. This follows the [official response
example](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion),
which includes a null upstream cost. The fields have distinct meanings in
[OpenRouter's usage reference](https://openrouter.ai/docs/cookbook/administration/usage-accounting).
No account or invoice lookup occurs.

Actual installed OpenAI SDK versions 2.54.0 and 3.36.0 were exercised against
generated local HTTP responses, including request serialization, optional
costs, malformed JSON/usage, redirects/errors, disconnects and cancellation.
After a dispatched failure, the wrapper stops further calls and closes its
owned SDK; this also covers the pinned upstream's missing failure-path cleanup.
Queued re-entry cannot send another request through that stopped client.
The fixture usage and costs are synthetic, not MiniMax results or receipts.

Independent review checked both SDK versions, the nullable-cost extension and
additional malformed-response, queued-call, cancellation and cleanup cases.
It also called the actual pinned upstream reader helper through SDK 3.36 to a
loopback fixture, verifying all 17 source pins and the real registry imports.
The development policy/transport suite has 52 checks per SDK version. See the
[structured transport result](../results/longmemeval-v2-minimax-transport-2026-10-21.json)
for the exact verification scope.

This is per-request enforcement. Creating another client bypasses its local
failure latch; it is not a persistent run claim, aggregate budget, dispatch
authorization or real endpoint acceptance check. The factory creates no
automatic dispatch entrypoint. A prospective public run still requires a
frozen protocol, live route/rate review and separately authorized numeric cap.

## Prospective public protocol (2026-10-21)

The [proposed comparison specification](longmemeval-v2-public-protocol-2026-10-21.md) now records Full/Sift fairness, selection/scheduling, scoring, failures, costs and latency before data use. It does not freeze an executable run or resolve the gaps below. In particular, the upstream empty `no_retrieval` baseline is not Full; implement a true all-state reference renderer and replace the adapter's approximate counter with a reviewed counting contract before activation. Numeric settings, immutable data pins/rights, trial-wide controls and separate spend authority remain unresolved.

## Known gaps and next gate

- **Access-rights screen (2026-10-20):** The official GitHub repository carries an Apache-2.0 license, and the official Hugging Face dataset card declares the data Apache-2.0. This records the maintainers' published license and supports planning only; it does not authorize data access/use or establish rights in embedded third-party web screenshots. No data has been downloaded. [Repository license](https://github.com/xiaowu0162/LongMemEval-V2/blob/main/LICENSE) · [Dataset card](https://huggingface.co/datasets/xiaowu0162/longmemeval-v2)
- The pinned trajectory preparer requires a non-empty screenshot path for every state. The smoke confirms image decoding and prompt handoff for synthetic fixtures only; it does not validate real dataset paths or image-dependent answer coverage. The benchmark publishes its questions and trajectories, so any eventual run is a public-benchmark reproduction, not evidence of generalization to a blind set.
- The upstream trajectories contain screenshot paths. This prototype associates images with selected text-bearing states, but Sift ranks text only and may miss image-only evidence. A future full-data trial must fail or report unsupported image-dependent cases explicitly; it must not silently drop them.
- The adapter uses an approximate size counter, not the reader tokenizer. The prompt-building helper and generated main flows now use the real reader processor downstream. Real-data truncation/normalization, parallel mode, LLM judging, real-endpoint acceptance/usage, trial-wide budget enforcement, latency, cost and task accuracy remain unverified; generated deterministic scoring and local SDK transport checks do not establish those capabilities.
- LongMemEval-V2's leaderboard validator requires its documented Qwen reader and GPT judge. A MiniMax-M3 run would be a local reproduction and requires a separate numeric spend cap; the current $100 authorization covers fresh LongBench, not LongMemEval.
- AppWorld and GAIA remain uncleared for a paired, independently controlled held-out run. A credible agent-task holdout still needs a prospectively fixed task set and an independent custodian/evaluator boundary.

The 2026-10-20 Gemini 4 Argon → GPT-6.1 Sol council recommended this bounded synthetic prototype while also freezing a separately held-out protocol and clearance checklist. Gemini judged the adapter the smallest free technical step; Sol agreed, but noted protocol definition is also actionable. Sol's stop condition is reached if faithful coverage requires silently dropping essential images or exceeds Sift's bounds. Usage: Gemini 3,129 prompt + 197 completion; Sol 701 prompt + 251 completion tokens. This is advice, not independent QA.

Before any real-data access or model call, an independent reviewer must accept the adapter and protocol, and a public-run protocol must be frozen. Generated sequential main/file/deterministic-scoring paths now run with the real reader processor; parallel mode, LLM judges and provider transport remain unverified. The declared dataset license has now been checked, but image provenance remains unreviewed; this check alone does not authorize data access/use. Any model run also needs a fresh route/usage reserve and explicit numeric spend cap. Stop this benchmark path if its screenshot requirements or scale cannot fit Sift without unsupported lossy behavior.

## Synthetic prompt-build smoke (2026-10-20)

`benchmarks/longmemeval_v2_synthetic_harness_smoke.py` passed against the pinned upstream harness blob `6a7182440a2cdd3ace6286dd966f7953fc383e8e`. It exercised the actual `build_prompt_row` helper and Sift adapter with a synthetic trajectory image and question image. The state image was decoded by the harness helper; both images were included in the generated reader messages, and the question image was also recorded in the image-path log field. The processor/token counter was stubbed to a fixed one-token shape. No dataset, generation, reader model, scoring, or inference was used. An independent read-only reviewer confirmed that these claims match the code path after a wording correction. This is a narrow integration probe, not a completed official evaluation.
