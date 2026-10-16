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
- Sample: freeze 100 deterministic LongBench v2 cases using MiniMax's published tokenizer/template, with full prompts above the 32,768-token default and no more than 150,000 locally rendered tokens. A prior OpenRouter request showed a 524,288-token endpoint cap and a large gap between local counts and the provider's estimate; the 150K ceiling leaves headroom for that observed mismatch. Balance selection across available length, domain, and difficulty strata. Freeze IDs, prompt hashes, answer keys, and seed before the 100-task run; never select cases based on MiniMax outcomes. This M3-specific sample is distinct from the earlier Qwen sample and the 10-case/6-case MiniMax development screens.
- Arms: (1) full original context; (2) Sift-compressed context. Keep the final question and message roles identical.
- Repeats: three paired repeats per case and arm (600 generations total), with randomized arm order within each pair. Preserve raw generation records and per-task outcomes.
- Task score: valid structured-choice answer and exact match to the published answer key. Report per-repeat results, per-case majority results, and paired disagreements; do not use only the best repeat.
- Record request/response timestamps, provider-reported prompt and completion usage, returned provider/model IDs, HTTP status, finish reason, schema validity, answer, correctness, and estimated/model-reported cost for each call.

## Token-budget and cost accounting

The earlier Qwen sample used Qwen tokenization and a 24,576-token target. For the primary MiniMax evaluation, use the configurable 32,768-token default and count rendered prompts with the pinned MiniMax tokenizer and chat template. Record tokenizer/template hashes, target, 150K maximum, and safety margin in the frozen manifest. Verify all 100 selected full prompts exceed the target and fit the conservative route limit; use identity/passthrough outcomes as explicit failures of that invariant rather than silently omitting them.

Use OpenRouter's returned prompt usage and `cost_details` as the source for provider-reported cost and input-token savings. The existing OpenRouter screens used BYOK and reported `cost: 0`, `is_byok: true`, and nonzero upstream inference costs; label those values as upstream-reported pass-through costs, not verified invoices. Calculate cost savings as `(full-context upstream cost - Sift upstream cost) / full-context upstream cost`; calculate input-token reduction separately using actual provider-reported prompt tokens. Include output and any billed reasoning usage in total cost.

Recalculate expected spend from the frozen M3-tokenized prompts and current OpenRouter price immediately before the run. Use a 4x local-token reserve for the $20 working ceiling, based on a prior observed provider/local count discrepancy of about 2.98x. Separately project request size at 3.25x local tokens against the previously observed 524,288-token OpenRouter request limit. These are best-effort client-side guards, not provider-enforced billing or context limits. The runner tracks provider-reported costs and stops dispatching when receipts plus in-flight estimates reach the budget, but already dispatched requests may still bill. If preflight exceeds the ceiling, preserve the 100-case scope and stop before dispatching the full run pending a budget decision.

## Execution stages and gates

1. **Finish and preserve the current Qwen run.** Do not restart or modify its service mid-run. Label its existing cache behavior accurately and do not present it as a cache-clean confirmation.
2. **Harden the existing MiniMax runner.** Reuse `benchmarks/run_longbench_v2_minimax.py`; do not create a duplicate or point the Qwen runner at OpenRouter unchanged. Lock the OpenRouter model/provider route with provider fallbacks disabled, verify the returned model and provider per call, retain complete response/error and usage evidence, support three randomized paired repeats at the single 32K target, and implement a local conservative spend ceiling.
3. **Freeze a new 100-case M3-tokenizer manifest.** Use only local pinned LongBench data, tokenizer, and chat template; require every selected full prompt to exceed 32,768 tokens and fit the full-context window. Balance length, domain, and difficulty where candidate counts allow; publish the selection policy and actual composition.
4. **Run a paired smoke test** on one frozen case, one repeat, both arms. Verify OpenRouter model/provider attribution, no provider/model fallback, structured choice, equal task prompt semantics, usage and cost fields, latency capture, and budget accounting. Reconcile OpenRouter-reported prompt tokens against the tokenizer/template estimate.
5. **Run the frozen 100-case evaluation** only after the smoke-test and spend gates pass. Use the pinned sample and fixed settings, preserve every attempt and failure in raw results, and never silently replace invalid calls.
6. **Audit, report, and update the README.** Summarize sample selection, provider route, model/version, dataset revision, Sift version and exact tokenizer/target definition, repeat aggregation, task accuracy, paired changes, provider-reported input reduction and upstream cost savings, preprocessing time, model latency, and confidence limits. Separate LongBench QA evidence from native Codex/Claude Code agent-workflow evidence. Do not imply LongBench alone proves end-to-end coding-agent quality or generalizes to the full suite.

## Completion criteria

- The frozen sample and paired prompts are unchanged and checksummed.
- Every counted response is attributable to OpenRouter MiniMax M3, with no unreported fallback.
- Raw inputs, outputs, usage, timing, per-task scores, and price assumptions are saved in a reproducible result artifact with secrets excluded.
- The README presents results and savings only as measured, with sample size, run date, protocol, and known limitations adjacent to the claims.
- The benchmark scripts and documentation are committed and pushed after the result is reviewed.

## Current status

- Frozen 100-case Qwen sample and runner are committed. Its 600-generation run is still in progress (last checked at 414/600 on 2026-10-16) and remains exploratory because server-side prompt caches were active; preserve it for forensic comparison, not cache-disabled claims. Advisor council recommends continuing in the background with a hard stop at completion, local-resource contention, or 60 additional minutes.
- MiniMax M3 through OpenRouter has completed a 10-case development screen and a separate 6-case Table QA screen. These used different samples, one repeat, and provider fallbacks; they are diagnostic only. At the 32K target the 10-case screen scored 2/8 for Sift versus 4/8 for full context, despite lower provider-reported input/cost usage. Treat this as an improvement signal, not a quality-preservation claim.
- The OpenRouter MiniMax runner is hardened and committed/pushed as `afc0d76`. It enforces exact 100-case, three-repeat, 32,768-target settings; verifies provider/model attribution; retains partial failures; writes atomically; and applies the 4x cost reserve plus separate 3.25x request-size projection. Independent Codex review accepts these as best-effort estimates, not guarantees.
- A new local-only MiniMax manifest preparer is scanning eligible rows under 120K, 130K, and 150K local prompt caps. No final 100-case M3 manifest or matching protocol has been frozen yet. The existing 10-case screen manifest is incompatible with the hardened runner and must not be used for the smoke or primary run.
- A provider-attributed, three-repeat, 100-case M3-tokenizer evaluation at the 32,768 default is still the next primary LongBench result. It has not run yet; no 100-case MiniMax score or savings percentage is established. The sample will be described as a length-conditioned development subset of LongBench v2's public training split, not a full-suite score or holdout.
