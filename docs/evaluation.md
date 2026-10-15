# Evaluation record

This page separates span retention, runtime compatibility, and model answers. The source Claude Code logs are locally generated task traces and are not distributed in this repository.

## Reproducible package tests

`python -m unittest discover -s tests -q` runs 17 tests for budget enforcement, message preservation, Anthropic and OpenAI tool loops, old thinking blocks, neighboring diagnostics, unsupported inputs, and seeded middle-fact placement. `python benchmarks/compare.py` uses 100 authored placements of a unique fact in the middle of a noisy history. Sift retained 100/100; an 800-character head/tail slice retained 0/100. This benchmark is designed around Sift's query-aware selection and does not estimate general recall.

The 0.3.0 regression places `FAILED test_invoice_total` beside a `rounding_mode=HALF_EVEN` clue in a 1,000-line log. Under the same 700-token budget, 0.2.0 retained the failure name but lost the adjacent clue; 0.3.0 retains both. This is a concrete causal-context failure of isolated excerpt selection, not proof that all agent failures came from Sift. A separate 90,000-distinct-line, 784,764-estimated-token case retained the same pair and forwarded 16,420 estimated tokens under a 24,576-token target in 0.68 seconds on one Windows desktop.

## Private agent-trace replay

Five native Claude Code task traces were generated locally while solving streaming, billing, scheduling, context-planning, and policy-persistence fixtures. They contained 23 to 66 replayable messages and had deterministic four-character estimates of 7,906 to 15,869 tokens. The replay forced a 5,000-token target to exercise compaction because the actual 24,576-token gateway target would not have been crossed by those traces.

Sift preserved the original task and latest tool message within the forced budget in 5/5 traces. Five retrospective questions about a named initial test failure each retained the matching failure line. A naive 20,000-character head/tail string slice retained the same line in 2/5. That slice is a span-retention reference, not a protocol-valid competing gateway. The questions were selected after inspecting the logs, so this is not a blinded or representative corpus.

## Live gateway checks

The Subroute staging gateway ran Sift with the local Unsloth Qwen3.8-27B `UD-IQ3_S` model. A 36-cycle Anthropic Messages request returned the exact newest failing test name with HTTP 200, `end_turn`, and 18,434 provider-reported input tokens. A corresponding Chat Completions request returned the newest failure name with HTTP 200, `stop`, and 18,334 input tokens. These probes test one long-loop shape on both public protocol surfaces.

For the paired-diagnostic regression, a 6,000-line log was sent through the staging Chat Completions route on 0.2.0. The model said the cause was absent because it received only the failure line. On 0.3.0, the same history and question returned an answer containing the adjacent `rounding_mode=HALF_EVEN` clue. A clearer follow-up question asked for the setting immediately after the failure and received exactly `rounding_mode=HALF_EVEN` through both Chat Completions and Anthropic Messages, with normal `stop` and `end_turn` outcomes and 22,570 provider-reported input tokens. The higher forwarded count compared with 0.2.0's 2,004 tokens increases cold-prefill work: the matching first responses took 11.56 and 20.2 seconds respectively. Later cached 0.3.0 queries took 2.58 and 4.05 seconds. These timings are not a controlled latency benchmark, but they show the tradeoff of retaining more evidence.

Six actual failed-test outputs from the local task logs were each buried between 4,500 routine lines on both sides and sent through staging Chat Completions. Five queries asked whether a named test was listed as `ERROR`; one asked about a named `FAIL` in a later run. The model answered 6/6 correctly with normal `stop` outcomes. Each raw history was about 415,000 to 417,000 characters; forwarded input was 2,199 to 2,351 provider-reported tokens. These are selected binary questions with artificial padding. They show that this route can answer these queries after compaction, not that it reliably solves arbitrary questions over a million-token history.

## Next quality gate

Collect a larger consented corpus of genuine long agent sessions and annotate must-retain spans before tuning. Include queries requiring facts without direct lexical overlap, conflicting revisions, and facts whose exact source matters. Compare answer correctness and latency against protocol-preserving head/tail and model-based baselines at the same forwarded-token budget. Current measurements do not establish a general recall rate or a mature optimum.
