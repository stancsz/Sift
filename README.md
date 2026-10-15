<p align="center">
  <img src="assets/sift-logo.png" alt="A hand holding a sieve, the Sift logo" width="240">
</p>

# Sift

**Keep useful evidence. Send less context. Reuse the prefix.**

[![Tests](https://github.com/stancsz/Sift/actions/workflows/test.yml/badge.svg)](https://github.com/stancsz/Sift/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![MIT license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/stancsz/Sift?label=release)](https://github.com/stancsz/Sift/tags)

Sift is a CPU-only Python library and **LiteLLM Proxy callback for extractive context compaction**. It selects evidence from long chat histories and tool logs to fit a caller-owned input budget, preserving instructions and exact active work. It uses deterministic selection, with no extra model request or generated summary.

It is for people running agents through LiteLLM who face growing tool transcripts, slow prompt prefill, and limited context or KV-cache capacity. Sift reduces the text sent to inference and keeps a stable historical prefix between tool-cycle boundaries so supported backends can reuse cached work.

**Status: experimental, with live gateway validation.** Token reduction, cache reuse, and lower cold-prefill latency have been measured in selected workloads. General task-quality preservation, dollar savings, and whole-task performance remain open acceptance gates. [See the evidence](docs/evaluation.md) and [the maturity roadmap](ROADMAP.md).

## The problem

An agent may need an old failure, a decision, or a policy ID hidden in thousands of routine lines. Sending everything spends context capacity and prompt-processing work. Keeping only the beginning and end can lose the evidence needed to finish.

Sift retains exact recent work, ranks older excerpts against the current task, carries neighboring diagnostic lines, and follows bounded identifier links to related facts. Completed groups of four tool cycles use fixed excerpts; the current group appends exactly while its reserved budget permits. This limits unnecessary prefix changes during a tool loop.

For example, a gateway can accept a history of up to **1,000,000 estimated tokens** in CPU memory and select at most **24,576 estimated input tokens** for a **32,768-token model**. The model attends only to the selected context. The remaining capacity must cover output and any difference between estimated and provider token counts.

## Install and use with LiteLLM

Install the tagged release from GitHub. Sift is not currently published to PyPI.

```sh
python -m pip install "sift-context[litellm] @ git+https://github.com/stancsz/Sift.git@v0.10.0"
```

Put a callback instance beside your LiteLLM configuration:

```python
# litellm_callback.py
from sift.litellm_proxy import SiftLiteLLMHook

sift_callback = SiftLiteLLMHook(
    {"local-chat": 24_576},
    raw_limit=1_000_000,
)
```

Register it through LiteLLM's callback configuration:

```yaml
litellm_settings:
  callbacks:
    - litellm_callback.sift_callback
```

`local-chat` is the resolved public model name in your proxy configuration. Set a target for each model you want compacted. If a routing callback changes the model name, place it before Sift. The [complete example](examples/litellm_config.yaml) includes a local OpenAI-compatible route; [the callback file](examples/litellm_callback.py) can be copied alongside it.

The callback supports **Chat Completions, Anthropic Messages, and stateless text Responses** on **LiteLLM Proxy 1.103.0**, pinned by the optional dependency. It uses the proxy's route counter, runs CPU work off the event loop with at most two admitted compactions per hook instance, and adds a server-owned `sift` audit to internal metadata. Excess work receives HTTP 429 with `Retry-After: 1`. Cancelled queued work is skipped; already running Python work retains its slot until it finishes. Configured routes return `x-sift-compacted` and estimated input/forwarded token headers. Requests below target keep their original messages or input and tools.

The integration uses private LiteLLM counting/conversion methods, so upgrading LiteLLM requires compatibility testing. Counting copies repair missing array `items` and account for tool schema text that this version's formatter skips. Original provider definitions stay exact. Sift leaves provider transport, streaming, retries, and public protocols to LiteLLM. [LiteLLM callback reference](https://docs.litellm.ai/docs/proxy/call_hooks).

Responses input must include complete history. Text messages, function/custom tools, function namespaces, and plain reasoning summaries are supported; stateful references, encrypted reasoning, media, built-in tools, and incomplete tool batches are rejected. For a Chat-only backend, enable LiteLLM's `use_chat_completions_api: true` on that deployment to let its native adapter serve Responses clients. [Adapter contract and audit logging](docs/algorithm.md#litellm-responses-selection-adapter).

## Use the library directly

The core has no gateway or model dependency. Supply your route's token-counting function and supported messages:

```python
from sift import compact_messages

result = compact_messages(
    messages,
    count_tokens=count_request_tokens,
    target=24_576,
    raw_limit=1_000_000,
    protocol="anthropic",  # or "openai"
)

forwarded_messages = result.messages
audit = result.audit
```

The hard bound is `forwarded_tokens <= target` according to your supplied counter. The audit includes raw and forwarded counts, omitted estimated tokens, retained prior turns, and selected excerpts. **Reserve output separately.** A 24,576-token estimate is not a guarantee of 24,576 provider tokens, and Sift does not allocate or manage KV cache.

## What is measured

| Check | Observed result | What it establishes |
|---|---|---|
| Authored history with distant identifier links | 966,253 estimated tokens became 22,579 under a 24,576 target; both required facts survived; 1.86 seconds on one Windows desktop | Large input reduction and bounded CPU work in one synthetic case |
| Seeded middle-fact benchmark | Sift retained 100/100 facts; an 800-character head/tail reference retained 0/100 | Retrieval on this intentionally query-oriented corpus |
| Six private Claude Code trace replays, forced 5K target | Distinct failed-test retention rose from 24/28 on v0.7.0 to 28/28 on v0.8.0 | A specific diagnostic-retention improvement |
| Live 34/35/36-cycle Chat Completions sequence | 19,475 / 21,464 / 23,453 estimated forwarded tokens; 21,362 / 23,642 provider-cached tokens on appended turns | Cache reuse inside one fixed group boundary, with correct newest and earliest failure answers |
| Earlier controlled cold-prefill comparison | Mean input 13,215 to 7,433 tokens; mean TTFT 8.96 to 5.49 seconds; Sift and full context each correct 6/6 | Lower latency before the 0.10.0 extraction change, on three authored cases repeated twice; head/tail also scored 6/6 |
| Structured development cases, v0.10.0 | Required exact records 8/14 to 14/14 at the same 900-token estimate; research chain 1/6 to 6/6 at 1,500 | Repairs two observed extraction failures; not held-out task quality |
| Fresh private screening of frozen releases, targets 800 to 2,200 estimated tokens | Required spans 5/14 to 8/14; cases retaining every required span 2/6 to 3/6; all budgets and protected messages preserved | Improvement with substantial remaining misses; six AI-authored cases, private inputs |
| Four frozen native-client trials on one public build task | All four pass six visible tests and fail independent gold; both Codex runs stay below target; Claude/Sift trims only after code completion | No accepted-task speedup or paired coding-quality advantage established |
| Native Codex build-planner task | Six visible and five original holdouts passed; broader post-run contract probes and reporting checks failed | Existing test passes did not establish the full artifact contract |
| Native Claude Code incident investigation | All required records were cited exactly; elapsed-time calculation failed the gold check | Evidence availability did not ensure correct reasoning |

The [evaluation record](docs/evaluation.md) includes methods, earlier regressions, provider counts, timing observations, and failed tasks. Private trace labels were selected retrospectively; raw traces are not distributed. The older 800-character head/tail reference is not a protocol-preserving competing gateway; the new cold-prefill baseline preserves message structure. These results do not establish a general recall or task-success rate.

The fresh screening fixed its cases after the releases were frozen and kept the algorithm author blind to the inputs. Version 0.10.0 still lost six required spans across three cases, even though the required evidence could fit. This is a concrete reliability limit. The [aggregate screening report](docs/results/frozen-release-screening-2026-10-15.json) records hashes and methods; its private inputs are not publicly reproducible. Broader retention and accepted agent-task results remain required before calling Sift mature.

**Does this make AI cheaper and faster?** Fewer forwarded tokens can reduce uncached prefill and input charges; a reusable prefix can avoid repeated prompt processing. The selected cold comparison measured 43.8% fewer input tokens, 38.7% lower mean TTFT, and 19.8% lower preparation-plus-response time, including Sift's CPU work. Actual billed savings depend on cache pricing, output length, retries, and extra agent turns. Sift generated more output in this comparison, and the local model has no per-token bill. Whole-task dollar savings remain unproven. [Methods, full results, and the failed first attempt](docs/evaluation.md#controlled-cold-prefill-comparison-2026-10-15).

## Preservation and limits

- Leading system/developer messages and the latest real user request stay exact and retain their roles. Active tool work stays exact when it fits; oversized loops keep the newest cycle and extract older cycles. If essential active work cannot fit, Sift raises a capacity error.
- Older excerpts carry source message indices and role labels as quoted user-role historical data. Inputs are copied, and unsupported media or late instructions fail closed when compaction is required. Quoting does not eliminate prompt-injection risk.
- Extraction is lossy. Facts without recognizable lexical or identifier signals can disappear. The bounded failed-test index preserves identifiers, while error details depend on other excerpts or recent exact cycles. Old Anthropic thinking and Responses reasoning summaries are omitted from extracted evidence; retained current cycles remain exact.
- A changed query, group rollover, oversized tool result, or budget eviction can change the prefix. Cache reuse depends on the inference backend as well as the rendered prompt. Sift has no persistent session memory or multimodal compression.

Read [the algorithm and acceptance contract](docs/algorithm.md) for selection rules, limits, and complexity.

## Reproduce and contribute

```sh
git clone --branch v0.10.0 https://github.com/stancsz/Sift.git
cd Sift
python -m pip install -e .
python -m unittest discover -s tests -q
python benchmarks/compare.py
```

The tests cover hard budgets, protocol preservation, active tool loops, append-only behavior inside fixed boundaries, diagnostic context, identifier joins, contradictory facts, unsupported inputs, and the optional LiteLLM callback. Install `.[litellm]` to exercise the integration with its pinned dependency.

The [native-agent guide](docs/native-agents.md) includes opt-in Claude Code and Codex runs, public development fixtures with separate gold checks, and an isolated LiteLLM comparison gateway. These source-checkout benchmarks are separate from the installed callback and make real model calls.

Useful contributions include reproducible failure cases, consented agent traces with spans labeled before tuning, and controlled measurements of accepted task quality, total cost, and time to first token. [Open an issue](https://github.com/stancsz/Sift/issues) with the smallest redacted reproduction. See [ROADMAP.md](ROADMAP.md) for the gates toward a mature release.

### Controlled prefill benchmark

With `.[litellm]` installed and a local OpenAI-compatible gateway running, set `SIFT_BENCH_API_KEY` in your environment, then run:

```sh
python benchmarks/make_prefill_cases.py tmp/prefill-cases.jsonl
python benchmarks/prefill.py --cases tmp/prefill-cases.jsonl --base-url http://127.0.0.1:4005/v1 --model qwen3.8-27b --target 6000 --repeats 2 --max-output-tokens 768 --output tmp/prefill-results.json
```

This opt-in benchmark makes 18 sequential model calls across three authored cases. It compares full context, Sift, and protocol-preserving head/tail trimming, with deterministic shuffled order and no scripted retries. The gateway must preserve the prepared requests. Its local-backend `cache_prompt: false` request must be honored and cached-token usage reported for a verified cold comparison. Native finish/usage inspection is pinned to LiteLLM 1.103.0; unsupported versions fail before calls. Results retain failed samples, separate SDK-estimated usage, and only qualify complete, correct, normally terminated cold samples for comparison. Output budgets include reasoning. These cases do not estimate general task quality or dollar savings.

Sift is informed by [question-aware compression](https://arxiv.org/abs/2310.06839), [extractive prompt compression](https://arxiv.org/abs/2403.12968), and [middle-position retrieval failures](https://arxiv.org/abs/2307.03172). Its deterministic heuristic is a separate implementation. Released under the [MIT license](LICENSE).
