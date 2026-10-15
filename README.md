# Sift

Sift is a small, CPU-only library for **query-aware extractive context compaction**. It accepts a long chat history and a caller-owned token counter, then returns a shorter history that fits an exact input budget. It does not call another model, invent a prose summary, or claim that a 32K model can attend to a million tokens.

The first use case is a local 32,768-token Qwen server behind Subroute. The gateway may accept up to 1,000,000 estimated input tokens, but forwards at most 24,576 after compaction, leaving room for generation and protocol overhead. Sift itself has no gateway or model dependency.

## What it keeps

1. Leading system and developer messages remain exact and in their original roles.
2. The latest real user request remains exact. When its tool loop fits, all following assistant/tool messages remain exact. When one long tool loop exceeds the target, Sift keeps the original request and newest tool cycle exact, retains up to three more recent cycles if they fit, and extracts older cycles as historical data. It reserves a small verbatim index of the first named test failures found in old tool output when space permits, and keeps bounded failure lines in completed groups. Completed groups of four tool cycles use fixed, task-anchored excerpts. When the current group fits its reserved share, its tool cycles append verbatim until the next group boundary.
3. Up to four recent complete prior turns remain exact when they fit a bounded share of the target.
4. Older text becomes quoted excerpts with original message index and role labels. Query term overlap, term rarity within the history, failure/decision signals, and recency rank candidates. A bounded second pass follows identifiers found in the best source lines to related lines, such as a delivery's policy ID and that policy's deadline. Each selected piece carries its immediate neighbors to retain local diagnostic context. Duplicate center pieces are suppressed in a bounded window. The selected excerpts stay in chronological order, and the caller's token budget determines how many fit.
5. A caller-supplied token counter checks the final serialized messages. If the active work cannot fit, Sift raises an explicit error rather than trimming it or claiming success.

```python
from sift import compact_messages

# Use the tokenizer/counting path that will actually enforce your model route.
result = compact_messages(
    messages,
    count_tokens=lambda candidate: router.count_tokens(candidate),
    target=24_576,
    raw_limit=1_000_000,
    protocol="anthropic",  # or "openai"
)
forwarded_messages = result.messages
audit = result.audit
```

`audit` reports input and forwarded token counts, omitted estimated tokens, retained prior turns, selected excerpts, and the method. The supplied counter owns token accounting. The defaults are not a guarantee of compatibility with every model or request schema.

## LiteLLM Proxy callback

Sift includes an optional native LiteLLM Proxy callback. Install from this checkout with `python -m pip install -e '.[litellm]'`. Copy [the callback instance](examples/litellm_callback.py) beside your LiteLLM config and list its dotted instance path under `litellm_settings.callbacks`:

```yaml
litellm_settings:
  callbacks:
    - litellm_callback.sift_callback
```

Set the callback's `model_targets` to the **resolved public model name** and its input budget. If another callback changes model aliases, list that routing callback before Sift. The hook runs for Chat Completions and Anthropic Messages, uses LiteLLM Proxy's route counter, and records a server-owned `sift` audit in internal request metadata. For configured models, responses report `x-sift-compacted` and estimated input/forwarded counts. Requests already under target retain their original messages and tools. On LiteLLM 1.103.0, the hook repairs missing array `items` only in a counting copy because that version's counter otherwise raises `KeyError('items')`. CPU work runs off the event loop with at most two concurrent compactions. The callback is explicitly scoped to LiteLLM Proxy 1.103.0 in the optional dependency; reevaluate its private route-counter call when upgrading LiteLLM. See [LiteLLM's Proxy callback guide](https://docs.litellm.ai/docs/proxy/call_hooks) and [the example config](examples/litellm_config.yaml).

## Safety and limits

Sift only compacts supported text and tool records. Unsupported media and late instruction messages fail closed when compaction is needed. It copies rather than mutating caller messages. Historical excerpts are wrapped as quoted **user-role data**, not elevated to system instructions. Quoting reduces accidental role confusion but does not make untrusted text harmless to a language model. Prior Anthropic thinking blocks are omitted from extracted evidence, while the current and retained tool cycles remain exact, including any thinking blocks. This is a deliberate lossy translation of older reasoning.

Extractive selection is lossy. A fact with no lexical overlap or recognizable signal can be omitted. Completed tool-cycle excerpts and the exact current group can preserve a provider cache prefix until the next group boundary. An oversized current group or budget pressure can trigger earlier eviction and invalidate that prefix. In a staging 34/35/36-cycle probe, llama.cpp reported 0/20,765/23,045 cached tokens and 17.22/4.15/3.86-second responses. These are one synthetic sequence, not a general speed guarantee. Sift has no persistent session memory, semantic model, multimodal compression, or guarantee that the downstream model answers correctly. The one-million-token value is an intake limit, not a model attention window.

## Verify

Install locally with `python -m pip install -e .`, then run `python -m unittest discover -s tests -q`. The 29 tests cover hard budgets, OpenAI and Anthropic single-request tool loops, fixed-boundary prompt reuse, the native LiteLLM callback, old thinking blocks, named test-failure retention, local diagnostic context, middle-of-history retrieval across five domains, contradictory facts, distant identifier joins, repetitive log noise, unsupported media, and 100 seeded placements of a needed fact. The reproducible `python benchmarks/compare.py` deliberately places facts in the middle: Sift retained 100/100 while a small head/tail baseline retained 0/100. A synthetic 966K estimated-token case with 76K distinct log lines retained two distant, joined policy facts in 1.86 seconds on a Windows desktop, forwarding 22,579 estimated tokens under a 24,576-token target. These are authored CPU-only examples, not natural-conversation quality or end-to-end latency guarantees. At a forced 5K budget, six private Claude Code traces retained a selected initial test-failure line in 74/74 compacted tool-result turns, up from 14/74 on 0.6.0; this is a retrospective span check, not an agent success rate. The raw traces are not distributed with this package. See [algorithm notes](docs/algorithm.md) and the [evaluation record](docs/evaluation.md).

Sift is informed by work on [question-aware long-context compression](https://arxiv.org/abs/2310.06839), [extractive prompt compression](https://arxiv.org/abs/2403.12968), and [middle-position retrieval failures](https://arxiv.org/abs/2307.03172). Its implementation is a deterministic heuristic, not a reproduction of those trained methods.
