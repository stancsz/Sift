<p align="center">
  <img src="assets/sift-logo.png" alt="A hand holding a sieve, the Sift logo" width="240">
</p>

# Sift

**Keep your agent’s working memory lean. Keep the evidence it needs.**

[![Tests](https://github.com/stancsz/sift/actions/workflows/test.yml/badge.svg)](https://github.com/stancsz/sift/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/stancsz/sift?label=release)](https://github.com/stancsz/sift/tags)

Pull requests run a short Python 3.12 smoke over core behavior, invariants, the standalone CLI, and the local Ollama demo. The full test suite and offline comparison run weekly and on manual dispatch; run them locally before a release with `python -m pytest tests -q` and `python benchmarks/compare.py`. To also check the standalone proxy with the OpenAI Python client (loopback fixtures only, no model request), install `python -m pip install -e ".[test,client-smoke]"` and run `python -m pytest tests/test_openai_sdk_compat.py -q`.

Sift is a deterministic, CPU-only context compressor for coding and research agents. It trims older chat and tool history to a configurable token budget while preserving the current request and active tool work exactly when they fit. If they do not fit, Sift fails closed. It makes no summarization call and adds no model dependency.

Use Sift as a Python library, a **LiteLLM Proxy callback**, or the standalone `sift` CLI with Ollama or another OpenAI-compatible endpoint. On supported backends, stable history between tool-cycle boundaries can also help prefix-cache reuse.

[See an offline compaction example](https://stancsz.github.io/sift/#try) · [Project site](https://stancsz.github.io/sift/) · [Standalone CLI](#standalone-cli-no-litellm) · [LiteLLM quick start](#litellm-proxy) · [Measured LongBench results](#longbench-v2-658-fewer-prompt-tokens) · [How it works](docs/algorithm.md) · [Evaluation record](docs/evaluation.md) · [Release process](docs/releasing.md)

> **Preview release:** install the tested `v0.10.0` tag from GitHub today. It defaults to a 24,576-token target. The newer 32,768-token default is on unreleased `main` (`0.11.0.dev0`). Sift is not yet published to PyPI. See the [release roadmap](ROADMAP.md).

## Quick start

### Standalone CLI (no LiteLLM)

The standalone Chat Completions proxy is on unreleased `main` (`0.11.0.dev0`). It uses only Python's standard library, binds to `127.0.0.1`, preserves tools and streamed responses, and forwards requests only after a client sends them. No LiteLLM install or manual repository checkout is needed to run the CLI. With Python 3.11+ and Git, install the development candidate into a virtual environment:

**Windows PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install "sift-context @ git+https://github.com/stancsz/sift.git@main"
.\.venv\Scripts\python.exe -m sift.cli serve --base-url http://127.0.0.1:11434/v1 --target 4096 --tokenizer byte-estimate
```

**macOS/Linux:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install "sift-context @ git+https://github.com/stancsz/sift.git@main"
.venv/bin/sift serve --base-url http://127.0.0.1:11434/v1 --target 4096 --tokenizer byte-estimate
```

Install [Ollama](https://ollama.com/), start `ollama serve` if its local service is not already running, and pull a model with `ollama pull qwen3.5:4b`. For another OpenAI-compatible backend, replace `--base-url`; use `--api-key-env ENV_VAR` to read a protected endpoint's key from an environment variable. Point your client at `http://127.0.0.1:4011/v1`.

To run the bundled demonstration, open a second terminal and clone the repository. The script sends an intentionally long deployment log, asks for a setting buried in the history, and prints the answer and Sift's estimated input/forwarded sizes:

```sh
git clone https://github.com/stancsz/sift.git
cd sift
python examples/ollama_compaction_demo.py --model qwen3.5:4b
```

The demo checks that `x-sift-compacted` is true; its generated rollout log puts the approved `initialDelaySeconds` value among routine polls. The scenario is synthetic and demonstrates request behavior, not answer quality. For your own client, use the OpenAI-compatible URL `http://127.0.0.1:4011/v1` and the model name your backend expects. For another compatible backend, replace `--base-url`; it must accept `POST /v1/chat/completions` and, when protected, standard Bearer authentication. Pass a protected endpoint's key through `--api-key-env ENV_VAR`, with the secret stored in that environment variable.

`byte-estimate` is an explicit UTF-8 request-size estimate, **not the upstream model's tokenizer**. Sift enforces the target against this estimate, including message and tool-schema fields. Leave room for output and treat the target as estimate-relative; provider context fit is not guaranteed. Only OpenAI Chat Completions is supported by this standalone proxy. The existing LiteLLM callback remains the path for Anthropic Messages, Responses, and LiteLLM's provider-specific token counter.

To inspect a conversation without starting a proxy or making a network request, pass JSON to `sift compact` with the same explicit `--tokenizer` and `--target` options.

### LiteLLM Proxy

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

A separate, broader one-repeat run has 446 matched scoreable questions from the 503-question public dataset: Full scored 44.4%, Sift scored 43.3% (−1.1 percentage points), and Sift used 75.8% fewer provider-reported prompt tokens. That run is incomplete, and all questions were exposed during development; it does not demonstrate parity or generalization. See the [checkpoint and accounting](docs/results/longbench-v2-minimax-m3-fullsuite-progress-2026-10-17.md).

[Protocol and complete-run status](docs/evals/longbench-v2-minimax-600-runner-2026-10-17.md) · [Aggregate result and hashes](docs/results/longbench-v2-minimax-600-2026-10-17.json) · [Earlier and ongoing evaluation work](docs/evaluation.md)

### What a 950K-token context costs with Sift

We ran a synthetic 950,401-token archive through Sift, then sent the compacted request to GPT-6 Astra and Gemini 4 Argon through Subroute. Sift estimated 32,698 forwarded tokens. Both models returned the requested value, `37 seconds`.

| Model | Raw context (estimated tokens) | Sift forwarding estimate | Actual Sifted usage (input / output tokens) | No-Sift API-equivalent | With-Sift API-equivalent |
|---|---:|---:|---:|---:|---:|
| GPT-6 Astra | 950,401 | 32,698 | 32,502 / 6 | $19.0085 | $0.3253 |
| Gemini 4 Argon | 950,401 | 32,698 | 37,003 / 41 | $1.9012 | $0.0744 |

**Token counts:** Raw and forwarded counts are Sift's LiteLLM estimates. Subroute's usage receipt reports the input tokens each model actually received; tokenizers and request framing differ. The observed input reduction was 96.6% for Astra and 96.1% for Gemini.

**No-Sift estimates:** The full 950,401-token requests were rejected by the current subscription routes before inference: Astra's Codex route rejected the context, and Gemini's bridge rejected the request body at its 1,000,000-byte limit. These are API-rate equivalents, not measured full-context calls. They apply public uncached input rates to Sift's raw estimate and assume the same output length observed in each Sifted reply.

**With-Sift estimates:** The subscription routes do not provide per-call dollar billing. These figures apply public API rates to Subroute's actual Sifted token receipts; no cache discount is included. Astra's long-context rate applies above 272K input tokens. Gemini 4 Argon's introductory rates apply through November 30, 2026. See the [probe method and receipts](docs/evals/subroute-950k-token-cost-probe-2026-10-20.md), [GPT-6 Astra pricing](https://developers.openai.com/api/docs/models/gpt-6-astra), and [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

LongBench v2 measures structured-choice QA, not agent-loop completion. Other Qwen and MiniMax screens used different samples and had different outcomes; see the [evaluation record](docs/evaluation.md) rather than combining their scores.


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

## How Sift handles long histories

A few focused tests show the mechanisms behind Sift's smaller working set:

- **Find evidence far apart:** in one authored history, Sift reduced 966,253 estimated input tokens to 22,579 while preserving two linked facts; selection took 1.86 seconds on one Windows desktop.
- **Search beyond the edges:** Sift retained 100/100 deliberately middle-placed facts in a query-oriented benchmark; an 800-character head/tail slice retained 0/100.
- **Reuse stable prefixes:** a staging probe across 34, 35, and 36 tool cycles returned both the newest and earliest requested failures, with 21,362 and 23,642 cached prompt tokens on appended turns.

These are separate synthetic and staging diagnostics, not accepted-task or broad agent-quality measurements. The [full evaluation record](docs/evaluation.md) includes methods, failed trials, and limitations; the [native-agent guide](docs/native-agents.md) explains how to evaluate Sift with Claude Code or Codex.

## Preservation and limits

- Leading system/developer messages and the latest real user request stay exact and retain their roles. Active tool work stays exact when it fits; oversized loops keep the newest cycle and extract older cycles. If essential active work cannot fit, Sift raises a capacity error.
- Older excerpts carry source message indices and role labels as quoted user-role historical data. Inputs are copied, and unsupported media fail closed when compaction is required. Late system/developer messages stay exact and in order; Sift compacts eligible historical spans between them and preserves the latest active turn. It fails closed if pinned instructions, active work, or a fitting evidence excerpt cannot fit. Quoting does not eliminate prompt-injection risk.
- Extraction is lossy. Facts without recognizable lexical or identifier signals can disappear. The bounded failed-test index preserves identifiers, while error details depend on other excerpts or recent exact cycles. Old Anthropic thinking and Responses reasoning summaries are omitted from extracted evidence; retained current cycles remain exact.
- A changed query, group rollover, oversized tool result, or budget eviction can change the prefix. Cache reuse depends on the inference backend as well as the rendered prompt. Sift has no persistent session memory or multimodal compression.

Read [the algorithm and acceptance contract](docs/algorithm.md) for selection rules, limits, and complexity.

## Reproduce and contribute

Create a virtual environment before installing the test and LiteLLM extras to keep their dependencies isolated from other Python projects.

Clone the repository:
```sh
git clone https://github.com/stancsz/sift.git
cd sift
```

**Windows PowerShell**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[litellm,test]"
python -m pytest tests -q
node tests/test_site_demo.js
python benchmarks/compare.py
```

**macOS/Linux**
```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[litellm,test]"
python -m pytest tests -q
node tests/test_site_demo.js
python benchmarks/compare.py
```
The full offline Python suite runs locally with the commands above. The standalone Node check exercises both GitHub Pages demo buttons and needs no npm packages. Pull requests run core, invariant, CLI, site, and Ollama-demo smoke checks on Python 3.12; the full suite and offline comparison benchmark run across Python 3.11–3.14 weekly and on manual dispatch. The tests cover hard budgets, protocol preservation, active tool loops, append-only behavior inside fixed boundaries, diagnostic context, identifier joins, contradictory facts, unsupported inputs, and the LiteLLM callback.

The [native-agent guide](docs/native-agents.md) includes opt-in Claude Code and Codex runs, public development fixtures with separate gold checks, and an isolated LiteLLM comparison gateway. These source-checkout benchmarks are separate from the installed callback and make real model calls.

Useful contributions include reproducible failure cases, consented agent traces with spans labeled before tuning, and controlled measurements of accepted task quality, total cost, and time to first token. [Open an issue](https://github.com/stancsz/sift/issues) with the smallest redacted reproduction. See [ROADMAP.md](ROADMAP.md) for the gates toward a mature release.

<details>
<summary>Advanced: run the controlled prefill benchmark</summary>

With `.[litellm]` installed and a local OpenAI-compatible gateway running, set `SIFT_BENCH_API_KEY` in your environment, then run:

```sh
python benchmarks/make_prefill_cases.py tmp/prefill-cases.jsonl
python benchmarks/prefill.py --cases tmp/prefill-cases.jsonl --base-url http://127.0.0.1:4005/v1 --model qwen3.8-27b --target 6000 --repeats 2 --max-output-tokens 768 --output tmp/prefill-results.json
```

This opt-in benchmark makes 18 sequential model calls across three authored cases. It compares full context, Sift, and protocol-preserving head/tail trimming, with deterministic shuffled order and no scripted retries. The gateway must preserve the prepared requests. Its local-backend `cache_prompt: false` request must be honored and cached-token usage reported for a verified cold comparison. Native finish/usage inspection is pinned to LiteLLM 1.103.0; unsupported versions fail before calls. Results retain failed samples, separate SDK-estimated usage, and only qualify complete, correct, normally terminated cold samples for comparison. Output budgets include reasoning. These cases do not estimate general task quality or dollar savings.

</details>

Sift is informed by [question-aware compression](https://arxiv.org/abs/2310.06839), [extractive prompt compression](https://arxiv.org/abs/2403.12968), and [middle-position retrieval failures](https://arxiv.org/abs/2307.03172). Its deterministic heuristic is a separate implementation. Released under the [MIT license](LICENSE).
