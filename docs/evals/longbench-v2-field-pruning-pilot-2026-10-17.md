# LongBench v2 field-pruning pilot — 2026-10-17

## Result and scope

A frozen, concurrent development screen compared Full context, unchanged default Sift, and opt-in `field_pruning=True` on four preselected structured-data LongBench v2 tasks, with three matched repeats per task (36 MiniMax requests total). All 36 requests completed through OpenRouter `minimax/minimax-m3` with provider fallbacks disabled. The candidate remains off by default.

| Arm | Exact answers | Task majorities | Provider prompt tokens | Cached prompt share | Upstream-reported pass-through cost | Reconstructed uncached estimate | Mean preprocessing | Mean end-to-end request |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Full context | 8/12 (66.7%) | 3/4 | 646,404 | 67.2% | $0.08973456 | $0.19400400 | 241 ms | 2.010 s |
| Default Sift | 1/12 (8.3%; 11/12 strict-valid) | 0/4 | 153,435 | 67.1% | $0.02144034 | $0.04613250 | 557 ms | 1.825 s |
| Field pruning | 6/12 (50.0%) | 2/4 | 22,224 | 73.8% | $0.00281064 | $0.00674640 | 681 ms | 1.296 s |

In this four-task sample, field pruning had two more task-majority wins than default Sift, with no default-only majority. It used 96.56% fewer provider prompt tokens and 96.87% lower upstream-reported pass-through cost than Full context. It also had 85.52% fewer provider prompt tokens and 86.89% lower pass-through cost than default Sift.

Full context scored 8/12 exact answers and 3/4 task majorities; field pruning scored 6/12 and 2/4. The candidate therefore remains behind Full context on answer quality in this screen. Its result only passes the preregistered gate for preparing an offline 100-task validation protocol; it does not authorize paid dispatch, enabling the feature by default, or a README/marketing claim. Four tasks are too few to establish generalization.

Cache-inclusive costs are provider-reported estimates, not invoices. Cache shares differed by arm; the reconstructed uncached cost is a rate-based estimate, not a charge. Mean preprocessing was slower for field pruning than default Sift (681 ms vs 557 ms), while mean end-to-end request time was 1.296 s vs 1.825 s. This is request pipeline timing on these prompts, not multi-turn agent completion time.

## Parser correction and reproducibility

The first analysis pass reported zero valid answers because MiniMax repeated the same `finish_reason: "stop"` choice record in both its final content event and usage event. The runner had preserved the raw SSE and parsed answers, but the original strict analyzer expected exactly one finish marker. No request was retried. A separately versioned post-hoc analyzer now accepts only exactly identical repeated terminal choice records, rejects conflicting terminal metadata, post-stop content, empty-choice events, malformed events, missing stop, and any event after `[DONE]`. Ten focused parser tests pass. The frozen original analyzer, no-dispatch preflight, and raw responses were left unchanged. Independent Codex review reproduced the 36 scores and accepted the correction. The separate Claude Code review did not return within the bounded wait and was canceled.

- Frozen preflight SHA-256: `193f3a1afb8a2d625b0058938c090e1650863a5921e42a7513d92c2a54a81ba0`
- Raw run SHA-256: `0361fa6a60c67c2bae445162ba8aaf78ba83ee523d56269e0875e708b9b68f25`
- Corrected v2 analysis SHA-256: `103ceaaf023d7b392d87907e60d1cde2b1e165d78d7c93da639cb640b30c9cb6`
- Corrected analyzer source SHA-256: `9ee90bcfbac98dfd2ad849b89794ba0e60de89c7258b9399baa1f2fb49a7e2d3`

## Budget and next step

The 36-request run's provider receipts total $0.11398554. A conservative exposure ledger counts the prior documented $16.20458423, all unitemized aggregate BYOK counter growth since the last snapshot, the pilot's receipts, and the post-run counter growth beyond those receipts. This yields a conservative exposure estimate of $18.69965639 of the previously authorized $20 cap, leaving about $1.30. The OpenRouter key counters are unitemized and may include unrelated usage or duplicate previously recorded charges; this estimate is deliberately conservative and is not an invoice reconciliation. It leaves insufficient room for the planned 100-task paid comparison. Do not dispatch further requests unless fresh itemized accounting and new budget authorization make the complete run fit.

A pilot-based rough extrapolation for a 100-task × 3-repeat × 3-arm comparison (900 requests) is about $2.85 at the observed cached receipt rate, $6.17 at the reconstructed uncached rate, and $9.39 under the runner-style 1.5× input reserve. That reserve exceeds the current $4 run limit and is far above the roughly $1.30 conservative aggregate headroom; these linear estimates must be replaced by a full offline preflight. A 300-call candidate-only arm is estimated near $0.30 reserve, but reusing historical Full/default data would not provide a concurrent control.

Next: prepare and independently review the offline 100-task concurrent Full/default/field-pruning protocol, freeze the sample and scoring, estimate costs and runtime at cache-hit and uncached rates, and keep `field_pruning` default-off. Paid validation remains gated by adequate new authorization and a fresh route/usage/reserve review.
