<p align="center">
  <img src="assets/sift-logo.png" alt="A hand holding a sieve, the Sift logo" width="240">
</p>

# Sift

**When tool history grows, keep relevant evidence in your coding agent’s next request.**

[![Tests](https://github.com/stancsz/sift/actions/workflows/test.yml/badge.svg)](https://github.com/stancsz/sift/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/stancsz/sift?label=release)](https://github.com/stancsz/sift/tags)

For coding-agent builders with long tool histories, Sift preserves the active request and tool work exactly when they fit, deterministically selects older task-related excerpts, and fails closed if current work cannot fit. It does this without a summary-model call.

**Measured trade-off:** on an exposed 344-question LongBench cohort, Sift used 59.66% fewer provider prompt tokens while its task-majority score was 5.25 percentage points lower than full context. This is not blind evidence or coding-agent success evidence.

**[Run the offline trace demo — no model required](https://stancsz.github.io/sift/#try)**

> **Preview release:** install `v0.11.0` from GitHub. It defaults to a 32,768-token target and fixes machine-readable overflow handling and native CLI continuations. Sift is not yet published to PyPI. This remains a preview; see the [release notes](docs/release-notes-0.11.0.md) and [roadmap](ROADMAP.md).

## Quick start

### Standalone CLI (no LiteLLM)

The standalone Chat Completions proxy is included in the `v0.11.0` preview. It uses only Python's standard library, binds to `127.0.0.1`, preserves tools and streamed responses, and forwards requests only after a client sends them. No LiteLLM install or manual repository checkout is needed to run the CLI. With Python 3.11+ and Git, install the preview into a virtual environment:

**Windows PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install "sift-context @ git+https://github.com/stancsz/sift.git@v0.11.0"
.\.venv\Scripts\python.exe -m sift.cli serve --base-url http://127.0.0.1:11434/v1 --target 4096 --tokenizer byte-estimate
```

**macOS/Linux:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install "sift-context @ git+https://github.com/stancsz/sift.git@v0.11.0"
.venv/bin/sift serve --base-url http://127.0.0.1:11434/v1 --target 4096 --tokenizer byte-estimate
```

Install [Ollama](https://ollama.com/), start `ollama serve` if its local service is not already running, and pull a model with `ollama pull qwen3.5:9b`. For another OpenAI-compatible backend, replace `--base-url`; use `--api-key-env ENV_VAR` to read a protected endpoint's key from an environment variable. Point your client at `http://127.0.0.1:4011/v1`.

To run the bundled demonstration, open a second terminal and clone the repository. The script sends an intentionally long deployment log, asks for a setting buried in the history, and prints the answer and Sift's estimated input/forwarded sizes:

```sh
git clone https://github.com/stancsz/sift.git
cd sift
python examples/ollama_compaction_demo.py --model qwen3.5:9b
```

The demo checks that `x-sift-compacted` is true and that the answer includes both `initialDelaySeconds` values, identifies the readiness probe, and says the old delay did not allow enough time. In one local run, `qwen3.5:9b` returned an answer that passed those checks; `qwen3.5:4b` omitted the previous value and gave the wrong reason. This synthetic check illustrates model-dependent behavior, not general answer quality. For your own client, use the OpenAI-compatible URL `http://127.0.0.1:4011/v1` and the model name your backend expects. For another compatible backend, replace `--base-url`; it must accept `POST /v1/chat/completions` and, when protected, standard Bearer authentication. Pass a protected endpoint's key through `--api-key-env ENV_VAR`, with the secret stored in that environment variable.

#### No-model local setup

To try the standalone proxy without installing or calling a model, use the local deterministic fixture. Run it from a source checkout with its own virtual environment. If you do not have a checkout yet:

```sh
git clone https://github.com/stancsz/sift.git
cd sift
```

**Terminal 1 — from that checkout, Windows PowerShell:**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m sift.cli serve --base-url http://127.0.0.1:4020/v1 --target 2048 --tokenizer byte-estimate
```

**Terminal 1 — from that checkout, macOS/Linux:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m sift.cli serve --base-url http://127.0.0.1:4020/v1 --target 2048 --tokenizer byte-estimate
```

**Terminal 2 — open the same checkout directory. Windows PowerShell:**

```powershell
.\.venv\Scripts\python.exe -m examples.no_inference_compaction_demo
```

**Terminal 2 — macOS/Linux:**

```sh
.venv/bin/python -m examples.no_inference_compaction_demo
```

Each command uses the checkout's `.venv` explicitly; activation is not required. The demo runs as a module from the repository root so its example imports resolve. It binds a stub backend to `127.0.0.1:4020`, checks whether Sift forwarded the buried rollout setting, and returns a fixed response. It makes no model call and requires no Ollama install. This verifies local request compaction only; it does not test an inference backend or answer quality.

#### 10-minute first-run task (no model)

1. Open the [Sift homepage](https://stancsz.github.io/sift/) and read the first screen for 20 seconds. Then explain in your own words what Sift keeps exact, what it may select from older history, when it refuses, and what the published result does not prove.
2. Follow the checkout, virtual-environment and two-terminal fixture commands above for your platform. Keep both terminals in the same checkout directory, using its explicit `.venv` interpreter.
3. Confirm the demo exits successfully and prints “Sift compacted the request” and “The loopback fixture found the buried setting.” No model is started or called.

After the demo, try this optional comprehension check privately: what stayed exact, what older content was selected, and what condition makes Sift refuse? What did the deterministic fixture not prove? Do not post your answers in the public issue.

This task uses synthetic history and a local deterministic stub only; it needs no Ollama install, API key, model request, or hosted inference. For the optional task feedback and up to three observed inference-free sessions, see [issue #13](https://github.com/stancsz/sift/issues/13). Issue comments are public under your GitHub account. If you share feedback there, report only `complete`, `blocked`, or `not started`, a broad workflow category, and the step that was unclear. Do not post prompts, logs, identifying details, or API keys.

`byte-estimate` is an explicit UTF-8 request-size estimate, **not the upstream model's tokenizer**. Sift enforces the target against this estimate, including message and tool-schema fields. Leave room for output and treat the target as estimate-relative; provider context fit is not guaranteed. Only OpenAI Chat Completions is supported by this standalone proxy. The existing LiteLLM callback remains the path for Anthropic Messages, Responses, and LiteLLM's provider-specific token counter.

To inspect a conversation without starting a proxy or making a network request, pass JSON to `sift compact` with the same explicit `--tokenizer` and `--target` options.

### LiteLLM Proxy

Install the tested GitHub release (Python 3.11+). Sift is not yet on PyPI:

```sh
python -m pip install "sift-context[litellm] @ git+https://github.com/stancsz/sift.git@v0.11.0"
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

The tagged preview above is the reproducible install path. Its default target is 32,768 estimated tokens; set route targets explicitly and reserve model output capacity. See the [full callback details](#litellm-callback-behavior-and-limits) and [direct library example](#use-the-library-directly).

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

A separate, broader 344-question run below tests three repeats per arm. It is more recent and has a larger repeated cohort, but it also shows a lower Sift task-majority score. Keep both findings visible rather than reading token reduction as a quality result.

[Protocol and complete-run status](docs/evals/longbench-v2-minimax-600-runner-2026-10-17.md) · [Aggregate result and hashes](docs/results/longbench-v2-minimax-600-2026-10-17.json) · [Earlier and ongoing evaluation work](docs/evaluation.md)

### Broader LongBench v2 cohort: 344 questions, three repeats per arm

The exposed-development MiniMax M3 study completed **2,063 of 2,064 requests with valid usage receipts**. One Full-context request returned HTTP 529 without a receipt and was not retried. For the 343 task clusters with three receipted responses in both arms:

| Measure | Full context | With Sift | Difference |
|---|---:|---:|---:|
| Exact answers | 434/1,029 · 42.18% | 414/1,029 · 40.23% | −1.94 pp |
| Task majorities | 145/343 · 42.27% | 127/343 · 37.03% | **−5.25 pp** |
| Provider-reported prompt tokens¹ | 66,007,295 | 26,628,470 | **59.7% fewer** |
| Provider-reported upstream cost¹ | $8.942262 | $3.690962 | **58.7% lower** |

The task-majority 95% question-cluster bootstrap interval for Sift minus Full is **−10.20 to −0.29 percentage points** (20,000 resamples, fixed seed). The paired task table is 100 both-correct, 45 Full-only, 27 Sift-only, and 171 neither. This is a descriptive result on public questions and labels previously exposed during development, not held-out evidence or an agent-task benchmark. Receipt costs are cache-sensitive OpenRouter BYOK fields, not an invoice. The one cluster with the unreceipted Full request is excluded from paired quality scoring. ¹Token and cost totals include every valid receipt, including the unpaired responses.

[Protocol, limits, and analysis method](docs/evaluation.md#broader-longbench-v2-cohort-344-questions-completed)

### Fresh repeat on the same public cohort

Fresh requests on the same exposed 344 questions completed all 2,064 scheduled
attempts, with 2,059 usage records and no retries of the five unconfirmed
attempts. On 339 complete paired questions, task-majority scores were **41.89%
Full vs 40.12% Sift** (−1.77 pp; 95% interval −6.49 to +2.95). Across known
usage, Sift used **59.56% fewer prompt tokens**. Our uncached input/output
calculation totals **$27.69 from unrounded costs** ($19.71 Full; $7.97 Sift). This repeat does not prove
parity, blind generalization or improvement over the earlier result.
[Coverage, money and provenance](docs/results/longbench-v2-minimax-fresh-344-2026-10-21.md).

### Synthetic retrieval probe: 950K-token archive

We compacted one synthetic archive estimated at **950,401 input tokens** to a Sift forwarding estimate of 32,698. The run record reports that both Sifted requests matched one planted fact. The public result omits raw replies, so readers cannot independently verify that answer.

**Observed Sifted requests**

| Model | Input tokens (Subroute receipt) | Output tokens | Fixture result |
|---|---:|---:|---|
| GPT-6 Astra | 32,502 | 6 | Recorded fixture match* |
| Gemini 4 Argon | 37,003 | 41 | Recorded fixture match* |

Sift's 32,698 forwarded-token count is an estimate; the provider tokenizers and request framing differ.
*The run record says both replies matched the planted fact, but the raw response text was not retained in the published result, so readers cannot independently verify the answer.

**Illustrative costs at public API rates (not billed amounts)**

| Model | Full 950K input, modeled¹ | Sifted receipt, priced² |
|---|---:|---:|
| GPT-6 Astra | $19.0085 | $0.3253 |
| Gemini 4 Argon | $1.9012 | $0.0744 |

¹The full-context subscription requests were rejected before inference, so no no-Sift usage receipt exists. These hypothetical amounts apply uncached public API rates to Sift's 950,401-token input estimate plus the output length observed in each Sifted reply. They are not measured full-context costs or bills.

²These costs apply uncached public API rates to the actual Sifted usage receipts. The subscription routes do not provide per-call dollar billing, so these are not subscription charges or invoices. Astra's long-context rate applies above 272K input tokens; Gemini 4 Argon's introductory rates run through November 30, 2026.

This one-fact probe does not establish task-quality parity, agent-task results, or measured savings. It compares observed usage for two Sifted requests with hypothetical API-rate arithmetic for a full-context input; it does not compare two successful model calls. See the [probe method, route limits, and pricing assumptions](docs/evals/subroute-950k-token-cost-probe-2026-10-20.md), [GPT-6 Astra pricing](https://developers.openai.com/api/docs/models/gpt-6-astra), and [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

LongBench v2 measures structured-choice QA, not agent-loop completion. Other Qwen and MiniMax screens used different samples and had different outcomes; see the [evaluation record](docs/evaluation.md) rather than combining their scores.


## The problem

An agent may need an old failure, a decision, or a policy ID hidden in thousands of routine lines. Sending everything spends context capacity and prompt-processing work. Keeping only the beginning and end can lose the evidence needed to finish.

Sift retains exact recent work, ranks older excerpts against the current task, carries neighboring diagnostic lines, and follows bounded identifier links to related facts. Completed groups of four tool cycles use fixed excerpts; each completed group can also contribute one query-independent, signal-bearing excerpt. The current group appends exactly while its reserved budget permits. This limits unnecessary prefix changes during a tool loop.

**Why it helps:** keep an agent's working set small as its history grows, without another model call or a generated summary. The `v0.11.0` preview's default selection target is **32,768 estimated input tokens** and can be changed per request or model route. The published `v0.10.0` release defaults to **24,576**; set a target explicitly when using that release. Sift can inspect up to **1,000,000 estimated input tokens** in CPU memory. The active task and current tool work must fit; if they do not, Sift fails closed with HTTP 413. Reserve output capacity and account for differences between estimated and provider token counts when choosing a target.

## LiteLLM callback behavior and limits

`local-chat` is the resolved public model name in your proxy configuration. Set a target for each model you want compacted. If a routing callback changes the model name, place it before Sift.

The callback supports **Chat Completions, Anthropic Messages, and stateless text Responses** on **LiteLLM Proxy 1.103.0**, pinned by the optional dependency. It uses the proxy's route counter, runs CPU work off the event loop with a configurable admission limit (two by default) per hook instance, and adds a server-owned `sift` audit to internal metadata. Excess work receives HTTP 429 with `Retry-After: 1`. Cancelled queued work is skipped; already running Python work retains its slot until it finishes. Configured routes return `x-sift-compacted` and estimated input/forwarded token headers. Requests below target keep their original messages or input and tools.

Starting with the 0.11.0 preview, core compaction errors converted to `HTTPException` expose their code in `exc.headers["x-sift-error-code"]`, while preserving detail text and chained cause. The status map covers current core/dynamic errors, including `late_instruction_limit` (422) and selection overflows (413). Active-work failures use `active_too_large`; `raw_limit` and `input_size_limit` remain distinct 413 errors.

Set `on_overflow="passthrough"` on `SiftLiteLLMHook` to forward only `active_too_large` requests unchanged. The default, `"error"`, preserves rejection. The full original request must fit the upstream's loaded context with output capacity reserved. This policy never bypasses raw/input-size guards, other selection overflows, unsupported content, or overload. Set `max_concurrency` to a positive integer to change the default two admitted compactions; it bounds CPU work, not provider requests.

The two protected-set overflow paths also expose `x-sift-required-tokens`, `x-sift-target-tokens`, and `x-sift-protected-region`. The count covers the complete protected set. Sift reserves 256 tokens of selection headroom, so rejection can occur before that count reaches the target. Diagnostics contain counts and a region label, not prompt text.

Existing callbacks matching `active turn` must be updated, or replaced with the built-in overflow policy. Upgrading Sift alone cannot change an old callback's string match. A custom callback can use:

```python
from fastapi import HTTPException
from sift.litellm_proxy import SiftLiteLLMHook

class PassThroughOn413Hook(SiftLiteLLMHook):
    async def async_pre_call_hook(self, *args, **kwargs):
        try:
            return await super().async_pre_call_hook(*args, **kwargs)
        except HTTPException as exc:
            if (exc.status_code == 413 and
                    (exc.headers or {}).get("x-sift-error-code") == "active_too_large"):
                return None  # Leave the original request unchanged.
            raise
```

Do not pass through every HTTP 413: input-size and raw-limit safeguards must remain fail-closed. Returning `None` leaves the request unchanged and does not make it fit; the deployer remains responsible for upstream context limits and sufficient output capacity.

Sift keeps the latest tool cycle exact; it does not silently truncate an oversized result. Raising the target helps only when the loaded model context has room. The pure [`compact_dynamic` API](docs/dynamic-local-inference.md) is available as `from sift import compact_dynamic`; it does not automatically change the callback's static model targets. Its defaults describe a reference local-inference profile, not universal model limits.

Plain assistant `reasoning_content` from OpenAI-compatible clients is preserved on retained messages and omitted from extracted historical evidence. Other roles and non-text values remain unsupported. The callback charges a text-token floor when the native counter ignores that field.

The [native CLI acceptance harness](docs/cli-acceptance.md) requires real tool continuations, independently checked edits, and a fact retained from compacted history. Its receipts establish those tested paths, not an absence of all bugs or broad task-quality parity.

Before tokenization, Sift bounds the parsed request to **16,777,216 aggregate string characters and 250,000 data nodes** by default. These safety limits are separate from the one-million-token `raw_limit`; both can be raised for trusted workloads through `max_input_characters` and `max_input_nodes`. The LiteLLM callback applies the guard to the complete parsed request, including tool schemas. Because callbacks run after HTTP JSON parsing, configure a request-body limit at the existing ingress or reverse proxy to bound initial memory use. LiteLLM 1.103.0's `max_request_size_mb` is Enterprise-only and is ignored by community installations; do not rely on it for this boundary. [Algorithm and guard behavior](docs/algorithm.md#intake-guards).

The integration uses private LiteLLM counting/conversion methods, so upgrading LiteLLM requires compatibility testing. Counting copies repair missing array `items` and account for tool schema text that this version's formatter skips. Original provider definitions stay exact. Sift leaves provider transport, streaming, retries, and public protocols to LiteLLM. [LiteLLM callback reference](https://docs.litellm.ai/docs/proxy/call_hooks).

The `v0.11.0` preview includes the source-slice work and defaults to 32,768 tokens. Its retention results remain development evidence, separate from the native CLI compatibility checks.

Responses input must include complete history. Text messages, function/custom tools, function namespaces, and plain reasoning summaries are supported. Codex `additional_tools` catalogs and encrypted reasoning items are retained verbatim; serialized copies are used only for counting, and reasoning never becomes historical evidence. Stateful references, media, built-in tools, malformed catalogs, and incomplete tool batches are rejected. For a Chat-only backend, enable LiteLLM's `use_chat_completions_api: true` on that deployment to let its native adapter serve Responses clients. [Adapter contract and audit logging](docs/algorithm.md#litellm-responses-selection-adapter).

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

In the `v0.11.0` preview, the default target is `DEFAULT_TARGET_TOKENS` (32,768). The published `v0.10.0` release defaults to 24,576. Pass `target` to select a budget explicitly. The hard bound is `forwarded_tokens <= target` according to your supplied counter. The audit includes raw and forwarded counts, omitted estimated tokens, retained prior turns, and selected excerpts. If the active task or latest tool cycle alone exceeds the target, compaction raises `CompactionError`; the LiteLLM callback returns HTTP 413. **Reserve output separately.** Estimated tokens may differ from provider counts, and Sift does not allocate or manage KV cache.

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
The full offline Python suite runs locally with the commands above. The standalone Node check exercises both GitHub Pages demo buttons and needs no npm packages. Pull requests run core, invariant, CLI, site, Ollama-demo, and no-inference-fixture smoke checks on Python 3.12; the full suite and offline comparison benchmark run across Python 3.11–3.14 weekly and on manual dispatch. The tests cover hard budgets, protocol preservation, active tool loops, append-only behavior inside fixed boundaries, diagnostic context, identifier joins, contradictory facts, unsupported inputs, and the LiteLLM callback.

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
