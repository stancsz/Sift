# LongBench v2 MiniMax hybrid Stage 2 protocol

## Objective and scope

Run the frozen 100-task public LongBench v2 development sample for three repeats using one Sift request per task/repeat (300 requests). The purpose is to measure answer quality for a frozen hybrid policy after the six-task Stage 1 diagnostic passed its review gate. It does not repeat Full context and is not a blind holdout or a full-suite evaluation.

The policy applies the option-aligned complete-entity matrix only to the six task IDs that passed the frozen offline relation-closure audit. Unchanged default Sift handles the other 94 IDs. Any candidate preparation fallback on the six IDs blocks dispatch; unsupported IDs are intentional default-Sift selections, not candidate failures. Candidate work remains opt-in and default-off in the product.

## Frozen inputs and request construction

- Dataset and tasks: the exact 100 cases in `docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json`, public LongBench v2 training split at the pinned revision. No task substitution or reweighting.
- Candidate allowlist: `672494e5bb02136c067d7697`, `67249705bb02136c067d76d1`, `6724c1d4bb02136c067d77ec`, `67285e1dbb02136c067d901b`, `67286036bb02136c067d9092`, and `6724c4aabb02136c067d78a6`. All other frozen IDs use default Sift.
- Sift target: 32,768 M3 tokens with a 128-token local safety margin. Use the pinned MiniMax M3 tokenizer and chat template. Verify the prepared request projection remains below the live provider prompt limit.
- Candidate preparation: relation closure must report complete comparison groups and zero unfit groups; matrix serialization must preserve every selected entity field, exact source paths, final question/options, and all non-context messages. The selected matrix must remain within the effective target. Any failure on an allowlisted task blocks the preflight; it is not silently converted into a successful Stage 2 result.
- Generation: OpenRouter `minimax/minimax-m3`; pin provider `minimax`, disable provider fallbacks, temperature 0.1, top-p 0.8, reasoning disabled, strict JSON object response with one A–D answer, 128 output tokens, one worker, and zero retries. Use CLI seed `20261022` and generation seed parameters `20261024`, `20261025`, `20261026` to align task/repeat keys with the historical run. The endpoint does not advertise seed support; no deterministic-repeat claim is made.
- Randomize task order with the frozen seed for each repeat. Before any API call, materialize all 300 canonical request bodies and hashes in the no-dispatch artifact. An independent reviewer must be able to inspect/recompute every hash from the saved body. Dispatch the exact frozen object from that artifact; do not reconstruct its fields at send time. Preserve every response, including invalid or incomplete billable responses.

## Budget and operational gates

Before provider requests, verify the live route and model, account access, current prices, context limits, unsettled usage, and available billing headroom. Set a fresh numeric cap for each paid batch and enforce a per-run ceiling with an in-flight reservation before sending each request. Stop dispatch on route drift, missing or inconsistent usage receipts, context rejection, transport failure, or a cap breach. Keep credentials, account snapshots, and authorization amounts out of published artifacts.

For each request, reserve sufficient uncached input and full output allowance at current rates. Persist the in-flight request and reservation before sending. Preserve incomplete or billable-invalid responses in accounting; do not retry an uncertain request without reconciling its provider outcome and receiving fresh authorization. Report receipt costs as provider-reported pass-through amounts, not invoice totals.

## Analysis and claims

Score exact A–D choices against the frozen answer key for all 300 responses. Independently parse the retained raw SSE stream, validate the response/usage receipt, and recompute the saved answer, validity, and correctness flags. A billable HTTP 200 with a valid receipt but malformed, truncated, or non-A–D answer remains in the denominator as incorrect; do not reject a complete run merely because some model answers are invalid. Validate historical result/manifest integrity and unique complete `(task, repeat, arm)` keys before comparing. Report per-repeat accuracy, task-majority accuracy, paired task/repeat outcomes against historical Full and historical Sift, invalid answers, route/receipt integrity, and per-task outcomes. Historical arms are non-concurrent and use a different Sift core revision; describe comparisons as cross-run and cross-version context subject to provider/cache/time drift, not as an isolated causal effect of the matrix selector. Do not infer causal quality change from matched IDs or requested seeds.

Report local and provider prompt tokens, observed upstream-reported cache-inclusive cost, cached tokens, clearly labeled uncached cost counterfactual, preprocessing time, request latency, end-to-end time, and full-run wall time separately. Do not claim invoice-level dollar savings. This hybrid run can assess a 100-task policy using the candidate on six in-sample IDs; it cannot establish matrix generalization beyond those six IDs, a LongBench full-suite result, or native Codex/Claude Code workflow performance.

## Required artifacts and release boundary

Freeze the protocol, stage manifest, route snapshot, source/import hashes, 100-task preparation output, all 300 request bodies and hashes, dispatch order, and spend projection before any API request. Use a separate Stage 2 runner and analyzer; do not alter v1/v2/v3 results or reuse the six-task gate as Stage 2 acceptance. Independently review the exact final dry run, credentials-presence check, key-usage snapshot, and ledger before dispatch. Publish the new results only after raw-receipt analysis and independent review. Keep README performance language unchanged until that review is complete.
