# Subroute 950K-token cost probe

Date: 2026-10-20

## What this measures

This is a one-request-per-model token-usage probe, not an agent task benchmark or a claim of quality parity. It checks whether Sift can reduce a long context while preserving one directly queried fact, then records the usage reported by Subroute when the compacted request reaches each model.

## Fixture and compaction

- Synthetic archive: 864 chat messages, 5,258,375 content characters, SHA-256 `4b0e88032f1a9c2a5913bac60165fbb2eb101eba137222cb60715873ecc62c38`.
- LiteLLM estimated 950,401 input tokens for both configured model aliases.
- The one fact queried was `ORCHID-73C9: escalation_window = 37 seconds`.
- Sift used the default extractive compactor with a 32,768-token target and 1,000,000-token raw limit. It estimated 32,698 forwarded tokens and retained the queried fact.

## Subroute requests

The calls used fixed model aliases `codex-astra` and `gemini-subscription-argon` through a temporary, isolated Subroute staging instance. The production gateway and its saved forced route were left unchanged. The temporary instance used the two models' advertised context limits, disabled the Advisor for these target requests, and used low reasoning effort with a 96-token output limit. No OpenRouter or MiniMax request was made.

| Route | Result | Subroute usage receipt | Answer |
|---|---|---:|---|
| `codex-astra` | Complete | 32,502 input / 6 output / 32,508 total | `37 seconds` |
| `gemini-subscription-argon` | Complete | 37,003 input / 41 output / 37,044 total | `37 seconds` |

The Astra Chat Completions response omitted its `usage` object; Subroute's staging usage ledger recorded the complete receipt. Gemini returned usage in the response, which the Subroute ledger also recorded. The provider-side count can exceed Sift's forwarding estimate because each model has its own tokenizer and request framing.

## Why the no-Sift rows are rate equivalents

The 950,401-token raw request could not be delivered through the current subscription adapters. Astra's Codex subscription route returned a context-window rejection. Gemini's Antigravity bridge rejected the serialized request because its body exceeded 1,000,000 bytes. Neither produced a successful full-context usage receipt.

The README's no-Sift amounts therefore apply public uncached API rates to the 950,401-token Sift estimate and hold output at the observed Sifted reply length for that model. They are rate-card arithmetic, not measured full-context usage or subscription charges. The Sifted amounts use the actual Subroute usage receipts but are also API-rate equivalents, since the subscription routes do not issue per-call dollar billing. No cache discount is included.

- GPT-6 Astra: $10/M input and $50/M output up to 272K input tokens; long-context requests use $20/M input and $75/M output. The no-Sift row uses the long-context rates; the Sifted row uses standard rates. [Official model pricing](https://developers.openai.com/api/docs/models/gpt-6-astra).
- Gemini 4 Argon: $2/M input and $10/M output at the introductory paid rate through November 30, 2026. [Official Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

The full-context requests failed at route/provider limits, so this probe demonstrates the usage of the Sifted path and an API-rate comparison. It does not establish a successful 950K no-Sift model call, task-quality parity, or end-to-end agent savings.
