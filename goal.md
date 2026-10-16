# Goal: LongBench v2 with OpenRouter MiniMax M3

## Objective

Produce a reproducible, provider-attributed comparison of Sift and full-context prompting on a frozen 100-task LongBench v2 sample, using OpenRouter's MiniMax M3 route. Report answer quality, actual input-token reduction, latency, and cost from the same paired requests. Use the results to decide what performance and savings claims are supported.

## Chosen model route

- Model: `minimax/minimax-m3` through OpenRouter (`openrouter/minimax/minimax-m3` in the Subroute LiteLLM configuration).
- Do not use the `auto` alias or a route that can switch to direct MiniMax, Xiaomi, or Codex. Isolate this evaluation route from LiteLLM and OpenRouter model fallbacks, and record the provider and model returned for every generation. If OpenRouter changes the provider, mark the sample as a routing deviation and do not silently count it as MiniMax.
- Keep credentials in the existing environment configuration. Never put API keys in this repository or benchmark output.
- OpenRouter currently lists a 1M-token context window and prices the model at $0.23 per million input tokens and $0.96 per million output tokens. Recheck the live route price immediately before the pilot and record the retrieved price and date in the result metadata.

## Frozen comparison design

- Dataset: LongBench v2, pinned dataset revision and data hash in `docs/evals/longbench-v2-qwen-100-manifest-2026-10-16.json`.
- Sample: the same frozen 100 cases, prompt hashes, answer keys, and seed for both arms. Do not select cases based on MiniMax outcomes.
- Arms: (1) full original context; (2) Sift-compressed context. Keep the final question and message roles identical.
- Repeats: three paired repeats per case and arm (600 generations total), with randomized arm order within each pair. Preserve raw generation records and per-task outcomes.
- Task score: valid structured-choice answer and exact match to the published answer key. Report per-repeat results, per-case majority results, and paired disagreements; do not use only the best repeat.
- Record request/response timestamps, provider-reported prompt and completion usage, returned provider/model IDs, HTTP status, finish reason, schema validity, answer, correctness, and estimated/model-reported cost for each call.

## Token-budget and cost accounting

The frozen sample was prepared with the Qwen tokenizer and a 24,576-token Sift target. The product default is configurable and should be 32,768 tokens; use that default for the MiniMax follow-up unless the frozen runner or a recorded protocol requires an explicit override. Treat either target as **Qwen-token-estimated** in the MiniMax experiment. Do not claim equal token budgets or exact context-fit parity unless a MiniMax-compatible tokenizer is available and the prompts are rechecked with it. Record the effective target and any override in the result metadata.

Use OpenRouter's returned usage and billed generation records as the source of truth for actual cost and input-token savings. Calculate cost savings as `(full-context cost - Sift cost) / full-context cost`; calculate input-token reduction separately using actual provider-reported prompt tokens. Include output and any billed reasoning usage in total cost. Label the estimate from the Qwen token counts as an estimate, not a guarantee or a spend cap.

At the listed OpenRouter prices, the frozen Qwen counts and 32,768 target imply at most roughly 21.95 million estimated input tokens across all 600 calls (about $5.05 input cost before MiniMax tokenization differences, output, or billed reasoning). This is a planning estimate, not an invoice or cap. Recalculate from observed pilot usage before scaling. Configure an enforceable OpenRouter account/credit limit for the pilot; do not treat a client-side token estimate as a hard cap. If an enforceable limit cannot be set, stop after the smoke test and get a budget decision before the 100-task run.

## Execution stages and gates

1. **Finish and preserve the current Qwen run.** Do not restart or modify its service mid-run. Label its existing cache behavior accurately and do not present it as a cache-clean confirmation.
2. **Build a separate MiniMax runner/adapter.** Do not point the Qwen runner at OpenRouter unchanged. Separate provider transport and model request options; remove Qwen/llama.cpp-only fields; keep Sift preparation, prompt hashes, structured-choice parsing, and raw evidence. Use a provider-appropriate tokenizer or explicitly preserve the Qwen-estimated target caveat.
3. **Run a paired smoke test** on one frozen case, one repeat, both arms. Verify OpenRouter model/provider attribution, no fallback, structured output, equal task prompt semantics, usage fields, latency capture, and actual generation billing. Confirm the enforceable budget control before proceeding.
4. **Run the frozen 100-case evaluation** only after the smoke-test gate passes. Use the pinned sample and fixed settings, preserve failures and retries in the raw results, and do not silently replace invalid calls.
5. **Audit, report, and update the README.** Summarize sample selection, provider route, model/version, dataset revision, Sift version and target definition, repeat aggregation, task accuracy, paired changes, provider-reported input reduction, cost savings, preprocessing time, model latency, and confidence limits. Separate LongBench QA evidence from native Codex/Claude Code agent-workflow evidence. Do not imply LongBench alone proves end-to-end coding-agent quality or generalizes to the full suite.

## Completion criteria

- The frozen sample and paired prompts are unchanged and checksummed.
- Every counted response is attributable to OpenRouter MiniMax M3, with no unreported fallback.
- Raw inputs, outputs, usage, timing, per-task scores, and price assumptions are saved in a reproducible result artifact with secrets excluded.
- The README presents results and savings only as measured, with sample size, run date, protocol, and known limitations adjacent to the claims.
- The benchmark scripts and documentation are committed and pushed after the result is reviewed.

## Current status

- Frozen sample and Qwen runner are committed; a 600-generation Qwen run is in progress. That run is exploratory because server-side prompt-cache settings were found active.
- MiniMax M3 through OpenRouter is the planned follow-up. The Qwen runner is not yet safe to reuse for that route; first complete the adapter and paired smoke test.
- No MiniMax LongBench outcome or cost-saving percentage has been measured yet.
