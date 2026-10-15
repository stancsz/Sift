# Sift

Sift is a small, CPU-only library for **query-aware extractive context compaction**. It accepts a long chat history and a caller-owned token counter, then returns a shorter history that fits an exact input budget. It does not call another model, invent a prose summary, or claim that a 32K model can attend to a million tokens.

The first use case is a local 32,768-token Qwen server behind Subroute. The gateway may accept up to 1,000,000 estimated input tokens, but forwards at most 24,576 after compaction, leaving room for generation and protocol overhead. Sift itself has no gateway or model dependency.

## What it keeps

1. Leading system and developer messages remain exact and in their original roles.
2. The latest real user turn and all following assistant/tool messages remain exact.
3. Up to four recent complete prior turns remain exact when they fit a bounded share of the target.
4. Older text becomes quoted excerpts with original message index and role labels. Query term overlap, failure/decision signals, and recency rank candidates. Duplicate lines are suppressed in a bounded window. The selected excerpts stay in chronological order.
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

## Safety and limits

Sift only compacts supported text and tool records. Unsupported media and late instruction messages fail closed when compaction is needed. It copies rather than mutating caller messages. Historical excerpts are wrapped as quoted **user-role data**, not elevated to system instructions. Quoting reduces accidental role confusion but does not make untrusted text harmless to a language model.

Extractive selection is lossy. A fact with no lexical overlap or recognizable signal can be omitted. Query-aware selection can change when the latest question changes, so provider prefix-cache reuse may vary. Sift has no persistent session memory, semantic model, multimodal compression, or guarantee that the downstream model answers correctly. The one-million-token value is an intake limit, not a model attention window.

## Verify

Install locally with `python -m pip install -e .`, then run `python -m unittest discover -s tests -q`. The suite covers hard budgets, active tool chains, Anthropic tool results, middle-of-history retrieval across five domains, contradictory facts, unsupported media, and 100 seeded placements of a needed fact. The reproducible `python benchmarks/compare.py` deliberately places facts in the middle: Sift retained 100/100 while a small head/tail baseline retained 0/100. A synthetic 935K estimated-token repeated-text case retained a middle fact in about 0.06 seconds on a Windows desktop; a separate 830K case with 90K distinct lines took about 0.73 seconds. These are authored CPU-only examples, not natural-conversation quality or end-to-end latency guarantees. See [algorithm notes](docs/algorithm.md) for the selection and evaluation contract.

Sift is informed by work on [question-aware long-context compression](https://arxiv.org/abs/2310.06839), [extractive prompt compression](https://arxiv.org/abs/2403.12968), and [middle-position retrieval failures](https://arxiv.org/abs/2307.03172). Its implementation is a deterministic heuristic, not a reproduction of those trained methods.
