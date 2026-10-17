# LongBench v2 next-step council

Date: 2026-10-18

## Question

After the zero-network 503-row fit/cost audit, should the next step first address rows outside the historical Full/default-Sift route screen, or freeze a narrower, explicitly scoped comparison? No paid requests are authorized.

## Evidence provided

- All 503 pinned task rows were processed locally. The answer field was skipped; there were no API/network calls or model responses.
- The historical screen contains 344 modeled Full/default-Sift paired-fit rows. The other 159 comprise 128 Full-screen-only failures and 31 rows failing both Full screening and Sift compaction (`raw_limit`). This is not live provider acceptance.
- On the 344 modeled rows, Full prompt input is 22,019,445 local tokens and default Sift is 8,874,718, 59.7% fewer. No answer quality or provider-billed cost was measured.
- Corrected reserve arithmetic under the dated $0.30/M input and $1.20/M output assumptions is $13.92 for one paired repeat and $41.75 for three. Current route, account usage, and spending authority are unverified.
- All task IDs are prompt/label-census-exposed; no untouched holdout exists.

## Gemini 4 Argon — independent review

Gemini recommends freezing an explicitly scoped comparison on the 344 modeled-fit IDs rather than first remediating all 159 exclusions. Its proposed smallest offline step is to lock the ID-only manifest and fix generator issues, then stop before any network call. It warns that the 344 tasks are not a blind sample and that dated route/pricing assumptions may change actual fit and reserve.

Usage: 3,129 prompt tokens, 185 completion tokens (3,314 total).

## GPT-6.1 Sol — own verdict and review of Gemini

Sol independently agrees to freeze a descriptive comparison scoped to the 344 historically modeled paired-fit IDs and not to repair the exclusions first. Sol says generator fixes are not necessary for that smallest step if the immutable report and interpretation addendum explicitly preserve the limitations. Sol rejects calling it a clean baseline because every ID is census-exposed and fit is only modeled. Next, freeze the IDs and exclusion counts, record token totals and dated reserve assumptions, then stop. Before paid requests, verify the current route/provider, prices, usage, full reserve, and obtain sufficient explicit spend authorization. If any frozen ID fails a refreshed route check, rescope and recompute the full reserve.

Usage: 730 prompt tokens, 162 completion tokens (892 total).

## Decision recorded

Freeze the 344 IDs in `longbench-v2-minimax-modeled-pair-manifest-2026-10-18.json` as a historical modeled-fit planning cohort. It is not a current route-eligibility result, fresh sample, quality result, or spend authorization. Preserve the generator caveats in the audit review addendum; do not dispatch until fresh operational gates and user spending authorization pass.

Advisor packet: `.runs/longbench-fullsuite-cost-council-20261018.txt`.
