# Advisor council receipt: MiniMax quality signal

Date: 2026-10-16. Risk tags: `research-validity` and `complex-code`.

## Packet

The packet described the frozen 10-case public LongBench v2 sample, one
generation per arm, the per-target full/Sift accuracy counts, one full-context
connection failure, two unscorable responses, exact MiniMax token-count
agreement, and the limitations of a small one-shot sample. It asked which
single experiment could distinguish evidence loss from model/sample variance,
and what result should trigger a selector change. Packet length was 1,500
characters. No credentials or answer outputs were included.

## Advice

- Gemini 4 Argon approved a zero-spend, blinded offline evidence-retention
  audit. It cautioned that LongBench v2 has no gold spans, so ambiguous or
  multi-hop labels can be wrong. It proposed comparing retained evidence for
  cases where full context succeeds.
- GPT-6.1 Sol agreed on freezing selector settings and labeling
  question-essential evidence in original contexts before seeing arm outputs.
  It rejected conditioning the audit on a full-context success: one success
  can be luck, and evidence loss matters even when the full arm fails. It
  recommends requiring an adjudicated, reproducible omission that leaves no
  sufficient evidence before changing the selector. Equivalent retained
  evidence should count as retained; unresolved labels should not trigger
  tuning.

The blinded source-derived retention audit is complete. It found two concrete
omission patterns, documented with limits and answer outcomes in the
[audit report](longbench-v2-minimax-m3-evidence-retention-2026-10-16.md). This
changes the earlier possible action of tuning the selector based on aggregate
accuracy alone, so `decision_changed: true`. The audit uses local processing
only and makes no provider requests.

## Provider receipts

- Gemini route `gemini-4-argon-advisor`, request
  `chatcmpl-agy-4db71d9fe546`: 1,443 prompt + 137 completion tokens; 16.148 s.
- GPT route `codex-gpt-6.1-sol-advisor`, request
  `chatcmpl-codex-advisor-355b5112f003`: 668 prompt + 233 completion tokens;
  9.925 s.
- Combined: 2,111 prompt + 370 completion tokens; 26.7 s end to end.

## Recovered prior failure

An earlier council call failed because the port-4040 experts container served
`gemini-3.8-flash-advisor`, while the skill requires
`gemini-4-argon-advisor`. The mounted `config/litellm.experts.yaml` already
defined the required alias, but the running container was stale. After checking
the live `/v1/models` list and the mounted Compose configuration, only the
local `experts` service was recreated. The new live model list exposed the
required Gemini 4 route and this single council call succeeded. No model
fallback was used.
