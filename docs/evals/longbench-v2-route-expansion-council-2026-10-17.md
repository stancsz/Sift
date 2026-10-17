# LongBench route expansion council

Date: 2026-10-17

## Decision question

Should a historical provider-token calibration replace the frozen 344-task/3.25× planning baseline, given current public OpenRouter MiniMax metadata and a candidate 454-task/1.05× planning screen?

## Gemini 4 Argon — independent review

Gemini recommends retaining the frozen 344 cohort and 3.25× guard as active, while staging the 454-row/1.05× cohort only as a contingency. It recommends an answer-blind diff manifest for the 110 additional IDs and a hard stop before paid requests until pinned-route smoke testing and sufficient budget authorization are in place. The historical receipt set does not establish pinned-route capacity above 150,000 local tokens.

Usage: 3,485 prompt tokens, 202 completion tokens (3,687 total).

## GPT-6.1 Sol — own verdict and review of Gemini

Sol independently agrees to keep 344/3.25× as the active planning baseline and retain 454/1.05× only as a planning alternative. It advises producing an answer-blind 110-ID diff with token counts, exclusions, and preserved baseline provenance. Sol notes that $84.13 is a three-repeat planning estimate, not necessarily a sufficient authorization because any smoke request and changed route assumptions also need reserve. Stop before any paid call until the pinned route, token accounting, capacity, and complete spend authorization are verified.

Usage: 879 prompt tokens, 213 completion tokens (1,092 total).

## Recorded action

The 344-task cohort remains active. A separate answer-blind planning diff, `longbench-v2-minimax-route-expansion-planning-diff-2026-10-17.json`, records 110 possible additions under a 1.05× projection and the current public 524,288-token MiniMax provider limit. The resulting 454-task cohort is not current route eligibility or quality evidence. Do not replace the primary cohort unless a future authorized pinned-route check confirms the changed operating envelope and the complete reserve is recalculated.

The OpenRouter endpoint lookup was metadata-only. It did not probe the route or make an inference request. No paid request was made.

## Historical receipt-count correction

A later metadata-only audit found 608 HTTP 200 Full-arm usage receipt rows with exact local/provider prompt-token equality across seven result files. The rows overlap: they correspond to 312 distinct non-null job IDs and 109 task IDs. Routing policy was explicitly pinned with fallback disabled for 593 rows, fallback-enabled for 14, and unverified for one. All five receipts above 150,000 tokens came from fallback-enabled files; there are no pinned no-fallback receipts above 150,000. These receipts therefore do not validate the 1.05× expansion on the pinned MiniMax route. The original council packet is retained as sent; its receipt count was not independently deduplicated before the council call. See [`longbench-v2-token-accounting-receipt-audit-2026-10-17.json`](longbench-v2-token-accounting-receipt-audit-2026-10-17.json).

Advisor packet: `.runs/longbench-route-expansion-council-20261018.txt`.
