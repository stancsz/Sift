# Subroute 950K-token cost probe

Date: 2026-10-20

## What was measured

One synthetic archive was compacted by Sift and sent once each to GPT-6 Astra and Gemini 4 Argon through an isolated Subroute staging instance. This measures the Sifted requests' usage receipts; it is not a quality benchmark, repeated workload, or proof of equal task success with and without Sift.

- 864 synthetic chat messages; 5,258,375 content characters.
- LiteLLM estimated 950,401 input tokens for the configured routes.
- Sift used the default extractive compactor with a 32,768-token target and 1,000,000-token raw limit; its forwarded estimate was 32,698 tokens.
- Astra usage: 32,502 input and 6 output tokens. Gemini usage: 37,003 input and 41 output tokens. Subroute recorded Astra's usage because its response omitted the usage object; Gemini returned usage that Subroute also recorded.
- The two isolated subscription routes were queried once each. The production Subroute gateway and saved forced route were not changed. No OpenRouter or MiniMax calls were made.

## Cost comparison

The full-context subscription requests were rejected before inference: Astra's route rejected the context window, and Gemini's bridge rejected the serialized request body above its 1,000,000-byte limit. There is no successful no-Sift usage receipt.

The no-Sift amounts are public, uncached API rate arithmetic over Sift's 950,401-token input estimate plus the output length observed in the corresponding Sifted request. The Sift amounts apply the same public API rates to actual Subroute usage receipts. These are API-rate equivalents, not subscription charges, provider bills, or measured full-context costs.

| Model | No-Sift rate equivalent | Sifted usage | With-Sift rate equivalent | Modeled reduction |
|---|---:|---:|---:|---:|
| GPT-6 Astra | $19.008470 | 32,502 input / 6 output | $0.325320 | 98.3% |
| Gemini 4 Argon | $1.901212 | 37,003 input / 41 output | $0.074416 | 96.1% |

Rates used:

- GPT-6 Astra: $10/M input and $50/M output up to 272K input; long-context requests use $20/M input and $75/M output. The full-context estimate uses the long-context rate; the Sifted request uses the standard rate. [Official model pricing](https://developers.openai.com/api/docs/models/gpt-6-astra).
- Gemini 4 Argon: $2/M input and $10/M output at the introductory paid rate through November 30, 2026. [Official Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

Input counts differ between LiteLLM estimates and Subroute receipts because model tokenizers and request framing differ. The calculation omits caching, retries, tools, hardware, and hosting. It does not show a successful 950K no-Sift call, task-quality parity, or end-to-end agent savings.
