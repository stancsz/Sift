# LongBench v2 next-step council — 2026-10-18

## Decision reviewed

Whether to continue with the planned fresh 100-task MiniMax Full-context/default-Sift pilot or pivot directly to a 503-task model study, given incomplete exposure coverage and the historical spend ledger.

## Evidence supplied

- `goal.md` specifies the 100-task pilot before a separately budgeted 503-task suite.
- The prior conservative ledger records `$18.69965639` against the historical `$20` cap; only about `$1.30` remains, versus `$9.39` for the historical 900-request proposal.
- The restricted offline preparation completed for an already exposed 100-task manifest, preparing 600 metadata/hash records with `actual_dispatch_started: false`.
- At least 190 of 503 task IDs are already known to have outcome, candidate, or mechanism exposure. That inventory is incomplete; the 100-ID manifest builder therefore marks its selection provisional.

## Council recommendation

Gemini 4 Argon recommended an exhaustive answer-blind ID audit across all local sources, then a fresh 100-task pilot if at least 100 unexposed IDs remain. GPT-6.1 Sol independently agreed: retain the 100-task pilot followed by the separately budgeted 503-task suite; do not pivot to the full study without revising the plan. Both recommend stopping any freshness claim if coverage remains incomplete or fewer than 100 unseen IDs remain, and stopping all paid dispatch until sufficient fresh funding is explicitly authorized.

## Use and limits

This advice determines the next offline step; it is not independent protocol acceptance or spending authorization. The exposure audit and any future budget/route preflight still require independent verification. No OpenRouter benchmark requests were made for this consultation.

Council receipt: Gemini 4 Argon — 3,259 total tokens; GPT-6.1 Sol — 865 total tokens. Packet: `.runs/advisor-longbench-next-decision-20261018.txt`.
