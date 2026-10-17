# MiniMax LongBench relation screen v1 diagnostic

The frozen Stage 1 v1 run stopped with `safety_guard_stopped` after 33 of 36 planned responses. The 33rd receipt was correctly attributed to MiniMax and had valid usage/cost data, but it reached `finish_reason=length` at the 16-token cap before the model emitted an answer. The other three jobs were not dispatched. The runner did not retry.

This is an incomplete run, not a completed six-task comparison. It fails the 36-valid-receipt gate; its partial responses are excluded from quality comparisons and from the v2 run. The full immutable request/response artifact is `../results/longbench-v2-minimax-relation-stage1-2026-10-16.json`. Upstream-reported Stage 1 v1 cost was $0.09651672.

A separate format investigation found that an OpenRouter JSON Schema request was accepted but returned markdown, while a JSON-object mode canary and a second canary using the exact compacted prompt that truncated in v1 both returned valid one-field JSON objects. These probes are not scored benchmark responses. See `../results/longbench-v2-minimax-json-format-canaries-2026-10-17.json`. The full unsanitized prompt canary receipt remains in local `.runs/` scratch; the tracked summary records its request hash, response, usage, and cost.
