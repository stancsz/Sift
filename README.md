<p align="center">
  <img src="assets/sift-logo.png" alt="A hand holding a sieve, the Sift logo" width="240">
</p>

# Sift

**Keep your agent’s working memory lean. Keep the evidence it needs.**

[![Tests](https://github.com/stancsz/sift/actions/workflows/test.yml/badge.svg)](https://github.com/stancsz/sift/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/stancsz/sift?label=release)](https://github.com/stancsz/sift/tags)

Sift is a deterministic, CPU-only context compressor for coding and research agents. It trims older chat and tool history to a configurable token budget while preserving the current request and active tool work exactly when they fit. If they do not fit, Sift fails closed. It makes no summarization call and adds no model dependency.

Use Sift as a Python library or a **LiteLLM Proxy callback**. On supported backends, stable history between tool-cycle boundaries can also help prefix-cache reuse.

[Try Sift in a LiteLLM proxy](#quick-start) · [Measured LongBench results](#longbench-v2-658-fewer-prompt-tokens) · [How it works](docs/algorithm.md) · [Evaluation record](docs/evaluation.md)

> **Preview release:** install the tested `v0.10.0` tag from GitHub today. It defaults to a 24,576-token target. The newer 32,768-token default is on unreleased `main` (`0.11.0.dev0`). Sift is not yet published to PyPI. See the [release roadmap](ROADMAP.md).

Sift is a deterministic, CPU-only context compressor for coding and research agents. It trims older conversation and tool history to a configurable token budget while preserving the latest request and active tool work exactly when they fit. No second model call, generated summary, or additional model dependency.

Use Sift as a Python library or a **LiteLLM Proxy callback**. It can inspect histories up to **1,000,000 estimated input tokens** and forward a smaller, query-focused working set. On supported backends, stable history between tool-cycle boundaries can also help prefix-cache reuse.

### LongBench v2: 65.8% fewer prompt tokens

Across 100 previously exposed LongBench v2 questions, three repeats per arm, Sift used **65.8% fewer provider-reported prompt tokens** and had **60.3% lower provider-reported upstream cost** than full context. This was a completed, matched MiniMax M3 study: 600 valid response receipts across Full and Sift.

| Measure | Full context | With Sift | Difference |
|---|---:|---:|---:|
| Provider-reported prompt tokens | 24,245,610 | 8,281,452 | **65.8% fewer with Sift** |
| Provider-reported upstream cost¹ | $3.2317 | $1.2842 | **60.3% lower with Sift** |
| Exact-choice accuracy | 117/286 · 40.91% | 106/290 · 36.55% | −4.36 percentage points |
| Equal-task-weighted accuracy | 39.83% | 36.67% | −3.16 percentage points |
| Task majorities correct | 40/100 | 34/100 | 18 Full-only · 12 Sift-only |

**The measured quality gap belongs with the token result.** This run does not establish quality parity, accepted-task quality, or performance on Claude Code or Codex agent workflows.

**Scope:** 100 public development questions previously exposed during selector work, with three repeats clustered within each question—not a blind holdout or the full 503-question dataset. Five ambiguous original attempts were retried once; their token usage and costs are unknown and excluded, so both savings figures cover only the 600 responses with usage receipts. Five responses ended at the output limit and were unscorable. ¹The cost row sums OpenRouter's cache-inclusive `upstream_inference_cost` receipt field for BYOK requests; it is not a MiniMax invoice. Full context had 69.5% cached prompt tokens versus 60.4% for Sift, so the observed cost ratio depends on this run's cache behavior. No end-to-end speed claim is made.

[Protocol and complete-run status](docs/evals/longbench-v2-minimax-600-runner-2026-10-19.md) · [Aggregate result and hashes](docs/results/longbench-v2-minimax-600-2026-10-19.json) · [Earlier and ongoing evaluation work](docs/evaluation.md)

### 32,768-token budget: premium-model rate examples

This is a separate **rate-card illustration**, not the measured LongBench cost and not an Astra or Claude API run. It models one uncached request with the same 10,000 output tokens in both arms and a 32,768-token Sift forwarding target.

| Model card | Full input | Full cost | With Sift | Modeled reduction |
|---|---:|---:|---:|---:|
| [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) | 500K | $10.75 | $0.83 | **92.3% · $9.92** |
| [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) | 1M | $20.75 | $0.83 | **96.0% · $19.92** |
| [Claude Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview) | 500K | $2.20 | $0.33 | **85.0% · $1.87** |
| [Claude Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview) | 950K¹ | $4.00 | $0.33 | **91.7% · $3.67** |

*Standard API rate arithmetic, equal task success and equal output, excluding cache, tools, retries, and hosting. GPT-6 Astra's long-context price applies to prompts above 272K; 950K leaves output room in Claude Opus 5.5's 1M context window. Rate cards checked 2026-10-19. These are modeled amounts, not measured savings or API bills; see [assumptions and calculations](docs/cost-comparison.md).*

LongBench v2 measures structured-choice QA, not agent-loop completion. Other Qwen and MiniMax screens used different samples and had different outcomes; see the [evaluation record](docs/evaluation.md) rather than combining their scores.

## Quick start

Install the tested GitHub release (Python 3.11+). Sift is not yet on PyPI:

```sh
python -m pip install "sift-context[litellm] @ git+https://github.com/stancsz/sift.git@v0.10.0"
```

Create `litellm_callback.py` beside your LiteLLM config. The published release uses a 24,576-token default; set the target for your model route and reserve space for model output.

```python
from sift.litellm_proxy import SiftLiteLLMHook

sift_callback = SiftLiteLLMHook(
    {"local-chat": 24_576},
    raw_limit=1_000_000,
)
```

Assumes an OpenAI-compatible model endpoint is already running at `http://127.0.0.1:8080/v1` and does not require authentication. Replace `your-model` and the URL with your backend's values. For a protected endpoint, load the API key from your environment rather than putting it in the config file.

```yaml
model_list:
  - model_name: local-chat
    litellm_params:
      model: openai/your-model
      api_base: http://127.0.0.1:8080/v1
      api_key: none

litellm_settings:
  callbacks:
    - litellm_callback.sift_callback
```

Start the proxy from the directory containing both files:

```sh
litellm --host 127.0.0.1 --config config.yaml --port 4000
```

On Windows PowerShell, if LiteLLM's Unicode startup banner does not fit your console encoding, run `$env:PYTHONUTF8 = "1"` before starting the proxy.

Send a first request through Sift:

```sh
curl http://127.0.0.1:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"local-chat","messages":[{"role":"user","content":"Reply with READY."}]}'
```

The response should contain the backend's answer. This short request is below the Sift target and passes through unchanged. To confirm compaction, send a conversation whose estimated input exceeds the configured target and inspect `x-sift-compacted`, `x-sift-estimated-input-tokens`, and `x-sift-estimated-forwarded-tokens`. On Windows PowerShell, use `curl.exe`. Start with the target below your backend's input limit so there is room for output.

The release install above is the fastest supported path. The unreleased `main` branch currently defaults to 32,768 estimated tokens (`0.11.0.dev0`); use it only if you intentionally want the development candidate. See the [full callback details](#litellm-callback-behavior-and-limits) and [direct library example](#use-the-library-directly).

## The problem

An agent may need an old failure, a decision, or a policy ID hidden in thousands of routine lines. Sending everything spends context capacity and prompt-processing work. Keeping only the beginning and end can lose the evidence needed to finish.

Sift retains exact recent work, ranks older excerpts against the current task, carries neighboring diagnostic lines, and follows bounded identifier links to related facts. Completed groups of four tool cycles use fixed excerpts; each completed group can also contribute one query-independent, signal-bearing excerpt. The current group appends exactly while its reserved budget permits. This limits unnecessary prefix changes during a tool loop.

**Why it helps:** keep an agent's working set small as its history grows, without another model call or a generated summary. The current `main` candidate's default selection target is **32,768 estimated input tokens** and can be changed per request or model route. The published `v0.10.0` release defaults to **24,576**; set a target explicitly when using that release. Sift can inspect up to **1,000,000 estimated input tokens** in CPU memory. The active task and current tool work must fit; if they do not, Sift fails closed with HTTP 413. Reserve output capacity and account for differences between estimated and provider token counts when choosing a target.

## LiteLLM callback behavior and limits

`local-chat` is the resolved public model name in your proxy configuration. Set a target for each model you want compacted. If a routing callback changes the model name, place it before Sift.

The callback supports **Chat Completions, Anthropic Messages, and stateless text Responses** on **LiteLLM Proxy 1.103.0**, pinned by the optional dependency. It uses the proxy's route counter, runs CPU work off the event loop with at most two admitted compactions per hook instance, and adds a server-owned `sift` audit to internal metadata. Excess work receives HTTP 429 with `Retry-After: 1`. Cancelled queued work is skipped; already running Python work retains its slot until it finishes. Configured routes return `x-sift-compacted` and estimated input/forwarded token headers. Requests below target keep their original messages or input and tools.

Before tokenization, Sift bounds the parsed request to **16,777,216 aggregate string characters and 250,000 data nodes** by default. These safety limits are separate from the one-million-token `raw_limit`; both can be raised for trusted workloads through `max_input_characters` and `max_input_nodes`. The LiteLLM callback applies the guard to the complete parsed request, including tool schemas. Because callbacks run after HTTP JSON parsing, configure a request-body limit at the existing ingress or reverse proxy to bound initial memory use. LiteLLM 1.103.0's `max_request_size_mb` is Enterprise-only and is ignored by community installations; do not rely on it for this boundary. [Algorithm and guard behavior](docs/algorithm.md#intake-guards).

The integration uses private LiteLLM counting/conversion methods, so upgrading LiteLLM requires compatibility testing. Counting copies repair missing array `items` and account for tool schema text that this version's formatter skips. Original provider definitions stay exact. Sift leaves provider transport, streaming, retries, and public protocols to LiteLLM. [LiteLLM callback reference](https://docs.litellm.ai/docs/proxy/call_hooks).

The source-slice work on `main` is an unreleased `0.11.0.dev0` candidate. The tagged `v0.10.0` install above remains the tested release; its default target is 24,576, while this candidate defaults to 32,768. The candidate's new retention result is development evidence until fresh validation is complete.

Responses input must include complete history. Text messages, function/custom tools, function namespaces, and plain reasoning summaries are supported; stateful references, encrypted reasoning, media, built-in tools, and incomplete tool batches are rejected. For a Chat-only backend, enable LiteLLM's `use_chat_completions_api: true` on that deployment to let its native adapter serve Responses clients. [Adapter contract and audit logging](docs/algorithm.md#litellm-responses-selection-adapter).

## Use the library directly

The core has no gateway or model dependency. Supply your route's token-counting function and supported messages:

```python
from sift import compact_messages

result = compact_messages(
    messages,
    count_tokens=count_request_tokens,
    target=32_768,
    raw_limit=1_000_000,
    protocol="anthropic",  # or "openai"
)

forwarded_messages = result.messages
audit = result.audit
```

On current `main`, the default target is `DEFAULT_TARGET_TOKENS` (32,768). The published `v0.10.0` release defaults to 24,576. Pass `target` to select a budget explicitly. The hard bound is `forwarded_tokens <= target` according to your supplied counter. The audit includes raw and forwarded counts, omitted estimated tokens, retained prior turns, and selected excerpts. If the active task or latest tool cycle alone exceeds the target, compaction raises `CompactionError`; the LiteLLM callback returns HTTP 413. **Reserve output separately.** Estimated tokens may differ from provider counts, and Sift does not allocate or manage KV cache.

## What is measured

| Check | Observed result | What it establishes |
|---|---|---|
| Authored history with distant identifier links | 966,253 estimated tokens became 22,579 under a 24,576 target; both required facts survived; 1.86 seconds on one Windows desktop | Large input reduction and bounded CPU work in one synthetic case |
| Seeded middle-fact benchmark | Sift retained 100/100 facts; an 800-character head/tail reference retained 0/100 | Retrieval on this intentionally query-oriented corpus |
| Six private Claude Code trace replays, forced 5K target | Distinct failed-test retention rose from 24/28 on v0.7.0 to 28/28 on v0.8.0 | A specific diagnostic-retention improvement |
| Live 34/35/36-cycle Chat Completions sequence | 19,475 / 21,464 / 23,453 estimated forwarded tokens; 21,362 / 23,642 provider-cached tokens on appended turns | Cache reuse inside one fixed group boundary, with correct newest and earliest failure answers |
| Earlier controlled cold-prefill comparison | Mean input 13,215 to 7,433 tokens; mean TTFT 8.96 to 5.49 seconds; Sift and full context each correct 6/6 | Lower latency before the 0.10.0 extraction change, on three authored cases repeated twice; head/tail also scored 6/6 |
| Structured development cases, v0.10.0 | Required exact records 8/14 to 14/14 at the same 900-token estimate; research chain 1/6 to 6/6 at 1,500 | Repairs two observed extraction failures; not held-out task quality |
| Frozen-release screening, targets 800 to 2,200 estimated tokens | Required spans 5/14 to 8/14; cases retaining every required span 2/6 to 3/6; all budgets and protected messages preserved | Improvement with substantial remaining misses; six AI-authored cases, now public development data |
| Unreleased source-slice candidate on the retired cases | Exact spans 8/14 to 11/14; complete cases 3/6 to 5/6; six budgets and protected contexts pass | Repairs CSV/Python text fidelity; three low-overlap facts still missing; not unseen validation |
| New unseen synthetic screening of that candidate | v0.10.0 and candidate both retain 8/15 exact spans and complete 2/6 cases | No observed generalization gain; six budgets and two append-prefix checks pass |
| Four frozen native-client trials on one public build task | All four pass six visible tests and fail independent gold; both Codex runs stay below target; Claude/Sift trims only after code completion | No accepted-task speedup or paired coding-quality advantage established |
| Native Codex build-planner task | Six visible and five original holdouts passed; broader post-run contract probes and reporting checks failed | Existing test passes did not establish the full artifact contract |
| Native Claude Code incident investigation | All required records were cited exactly; elapsed-time calculation failed the gold check | Evidence availability did not ensure correct reasoning |
| Payment-export full-context preflight | One template setup failure and four full-context attempts exposed a UTC as-of miss, an event-ID ordering gap, then two remaining gold failures; latest run passed visible tests and ended normally | No Sift comparison yet; full-context task acceptance remains unproven |
| [Least-privilege IAM Sift stress run](docs/results/least-privilege-audit-sift-stress-2026-10-16.json) | 53 local requests, 45 compacted; summed estimated input fell 73.4%; mean client-reported TTFT 6.14 s | 1,200-second timeout; 8/9 visible and 14/21 combined checks passed; no full-context control, no accepted task, no quality or cost claim |
| [Public research-audit three-arm stress pilot](docs/evals/native-research-pilot-2026-10-15.md) | All three passed independent acceptance; mean TTFT 2.66 / 4.89 / 2.84 s, engine decode 45.32 / 45.40 / 45.63 tok/s | Sift compacted before the edit but was slower in this single warm/mixed-cache run; no Astra bill or general speed claim |
| [Query-independent epoch coverage development screen](docs/evaluation.md#query-independent-epoch-coverage-development-screen-2026-10-15) | On six public weak-overlap synthetic cases, source baseline retained 0/6 required spans; candidate retained 5/6; all budgets, task text, latest cycles, and input immutability passed | One controlled synthetic development comparison; not task-quality validation or generalization evidence |
| [Query-echo regression fix](docs/evaluation.md#reproduced-query-echo-miss-and-development-fix-2026-10-16) | The tuned candidate retains 6/6 required spans on the same six public development cases; invariants pass | Regression repair on exposed cases only; not blind validation or evidence of better model answers |
| [Post-hoc public Qwen answer probe](docs/evaluation.md#direct-answer-probe-with-llmlingua-2-2026-10-16) | Full 5/6, Sift 3/6, recency 0/6, LLMLingua-2 text 1/6; Sift retained all six required strings | One answer per arm/case on exposed synthetic data; three Sift answers still missed despite exact retention; no quality or cost claim |
| [LongBench v2 Qwen structured-choice screen](docs/evaluation.md#longbench-v2-structured-choice-rerun-2026-10-16) | On 16 above-target cases: full 20/48, Sift 15/48; Sift used 27.9% fewer local Qwen input tokens and had lower mean TTFT | Public short-category diagnostic; post-hoc task majority: 5 both, 2 full-only, 0 Sift-only; one supported relation-loss case and one label-uncertain row; excluding both gives no discordant tasks; no parity or Astra-billing claim |
| [Fresh LongBench v2 Qwen extension](docs/evaluation.md#longbench-v2-qwen-extension-2026-10-16) | On 10 additional above-target cases: full 16/30, Sift 15/30; Sift used 6.4% fewer prompt tokens and had 7.4% lower mean TTFT | Task-majority outcomes: 5 both correct, 0 discordant, 5 neither; endpoint plus Sift preprocessing was 4.2% faster, decode speed 4.8% lower; public, small diagnostic, no sharper-answer, parity, or Astra-billing claim |
| [Qwen context-budget screen](docs/evaluation.md#context-budget-qwen-development-screen-2026-10-16) | On the same ten public tasks: 8K Sift used 8,153 versus 26,216 input tokens; mean TTFT 5.82 versus 17.71 s; 5/10 task majorities correct in both arms | 16K had one full-only and one Sift-only task; all three targets are exposed development results, not a default-selection or parity claim; 32K–64K input remains untested |
| [Native network-audit MiniMax development comparison](docs/evals/native-network-audit-development-2026-10-16.md) | Full context passed 7 visible and 20 gold tests in 88.8 s; Sift at 16K did not finish the task | Sift compacted 81 requests, but hit the 80-turn cap after 394.3 s and reported $3.225 versus $0.588 for full context; one exposed development case, no savings claim |
| [Native MiniMax M3 least-privilege diagnostic](docs/evals/native-m3-least-privilege-rollup-2026-10-16.md) | Full and Sift at 16K both passed; pre-edit audit verified all four required spans in the Sift request; selector estimates fell 74.1% in aggregate | Sift took 131 s and reported $1.49 versus 63 s and $0.42 for full context; 24K Sift was a no-op; one fixed-order exposed task, no general savings or speed claim |

The [evaluation record](docs/evaluation.md) includes methods, earlier regressions, provider counts, timing observations, and failed tasks. Private trace labels were selected retrospectively; raw traces are not distributed. The older 800-character head/tail reference is not a protocol-preserving competing gateway; the new cold-prefill baseline preserves message structure. These results do not establish a general recall or task-success rate.

The fresh screening fixed its cases after the releases were frozen and kept the algorithm author blind during the original comparison. Version 0.10.0 lost six required spans across three cases, even though the required evidence could fit. The [aggregate screening report](docs/results/frozen-release-screening-2026-10-15.json) and [exact frozen cases](benchmarks/retired_frozen_release_screening_2026-10-15.json) are public. The cases were subsequently opened for development and permanently retired as unseen validation. An [unreleased source-slice candidate](docs/results/source-slice-candidate-2026-10-15.json) repairs three formatting misses, but a [new unseen screening](docs/results/source-slice-blind-screening-2026-10-15.json) found no retention gain over v0.10. Broader retention and repeated accepted-agent-task results remain required before calling Sift mature.

The premium-model price illustration near the top is single-request arithmetic, not a measured 500K–1M-token multi-turn agent result. Astra's long-context rates apply above 272K input tokens; Opus rates and cache terms vary by API plan and platform. The current native-agent trials do not establish equal task quality, whole-conversation spend, or faster completion. Actual cost per accepted task must include every turn, output, cache read/write, retries, and preprocessing; faster time to finish is also unproven. See the [cost method and assumptions](docs/cost-comparison.md) and [evaluation record](docs/evaluation.md).

The [network-audit development comparison](docs/evals/native-network-audit-development-2026-10-16.md) also records a real MiniMax full-context run at $0.588 and a rejected Sift run at $3.225. Repricing those usage totals at Astra's standard short-context rates gives illustrative amounts of $1.140 and $6.424. These are not Astra measurements; model token use, cache behavior, and task success can differ.

The gated [natural-agent pilot](docs/evals/natural-agent-pilot-2026-10-16.md) now has a corrected isolated baseline/output harness and one public Sift stress diagnostic. It still needs eight valid tasks, matched full/Sift/recency arms, and independently checked outcomes. The [relation-binding pilot](docs/evals/relation-binding-pilot-2026-10-16.md) remains unrun because its case-author attempt failed validation. The broader [held-out quality comparison protocol](docs/evals/quality-comparison-protocol-2026-10-16.md) still requires matched LLMLingua-2, blinded answer scoring, and measured cost per accepted task. No quality-parity or “sharper answers” claim is supported yet.

## Preservation and limits

- Leading system/developer messages and the latest real user request stay exact and retain their roles. Active tool work stays exact when it fits; oversized loops keep the newest cycle and extract older cycles. If essential active work cannot fit, Sift raises a capacity error.
- Older excerpts carry source message indices and role labels as quoted user-role historical data. Inputs are copied, and unsupported media fail closed when compaction is required. Late system/developer messages stay exact and in order; Sift compacts eligible historical spans between them and preserves the latest active turn. It fails closed if pinned instructions, active work, or a fitting evidence excerpt cannot fit. Quoting does not eliminate prompt-injection risk.
- Extraction is lossy. Facts without recognizable lexical or identifier signals can disappear. The bounded failed-test index preserves identifiers, while error details depend on other excerpts or recent exact cycles. Old Anthropic thinking and Responses reasoning summaries are omitted from extracted evidence; retained current cycles remain exact.
- A changed query, group rollover, oversized tool result, or budget eviction can change the prefix. Cache reuse depends on the inference backend as well as the rendered prompt. Sift has no persistent session memory or multimodal compression.

Read [the algorithm and acceptance contract](docs/algorithm.md) for selection rules, limits, and complexity.

## Reproduce and contribute

```sh
git clone --branch v0.10.0 https://github.com/stancsz/sift.git
cd sift
python -m pip install -e ".[litellm]"
python -m unittest discover -s tests -q
python benchmarks/compare.py
```

GitHub Actions runs the same full unit suite and offline comparison benchmark on Python 3.11 through 3.14. The tests cover hard budgets, protocol preservation, active tool loops, append-only behavior inside fixed boundaries, diagnostic context, identifier joins, contradictory facts, unsupported inputs, and the LiteLLM callback.

The [native-agent guide](docs/native-agents.md) includes opt-in Claude Code and Codex runs, public development fixtures with separate gold checks, and an isolated LiteLLM comparison gateway. These source-checkout benchmarks are separate from the installed callback and make real model calls.

Useful contributions include reproducible failure cases, consented agent traces with spans labeled before tuning, and controlled measurements of accepted task quality, total cost, and time to first token. [Open an issue](https://github.com/stancsz/sift/issues) with the smallest redacted reproduction. See [ROADMAP.md](ROADMAP.md) for the gates toward a mature release.

### Controlled prefill benchmark

With `.[litellm]` installed and a local OpenAI-compatible gateway running, set `SIFT_BENCH_API_KEY` in your environment, then run:

```sh
python benchmarks/make_prefill_cases.py tmp/prefill-cases.jsonl
python benchmarks/prefill.py --cases tmp/prefill-cases.jsonl --base-url http://127.0.0.1:4005/v1 --model qwen3.8-27b --target 6000 --repeats 2 --max-output-tokens 768 --output tmp/prefill-results.json
```

This opt-in benchmark makes 18 sequential model calls across three authored cases. It compares full context, Sift, and protocol-preserving head/tail trimming, with deterministic shuffled order and no scripted retries. The gateway must preserve the prepared requests. Its local-backend `cache_prompt: false` request must be honored and cached-token usage reported for a verified cold comparison. Native finish/usage inspection is pinned to LiteLLM 1.103.0; unsupported versions fail before calls. Results retain failed samples, separate SDK-estimated usage, and only qualify complete, correct, normally terminated cold samples for comparison. Output budgets include reasoning. These cases do not estimate general task quality or dollar savings.

Sift is informed by [question-aware compression](https://arxiv.org/abs/2310.06839), [extractive prompt compression](https://arxiv.org/abs/2403.12968), and [middle-position retrieval failures](https://arxiv.org/abs/2307.03172). Its deterministic heuristic is a separate implementation. Released under the [MIT license](LICENSE).
