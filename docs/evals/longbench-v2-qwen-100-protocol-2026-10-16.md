# LongBench v2 100-task Qwen evaluation protocol

**Frozen before generation on 2026-10-16.** This is a public diagnostic, not a
blind holdout or a native coding-agent evaluation.

## Sample and input limits

- Dataset: `zai-org/LongBench-v2`, revision
  `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`; pinned `data.json` SHA-256
  `15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2`.
- Frozen sample manifest:
  [`longbench-v2-qwen-100-manifest-2026-10-16.json`](longbench-v2-qwen-100-manifest-2026-10-16.json),
  SHA-256 `84426affa8168637a5a93afbcec3db35ab252e0dcd68d48d9e54b56c7d75de5d`.
- The preparation scan found 186 full-context-fit candidates among the 301
  rows under a 500,000-character prefilter. Contexts above that character
  prefilter were not tokenized. Of the fit candidates, 118 exceeded the
  24,576-token Sift target. A seeded round-robin sample of 100 was selected
  across domain and difficulty strata; all selected prompts exceed the target.
- Local model: Qwen3.8-27B IQ3_S via llama.cpp. The serving context is 73,728
  tokens, with a 4,096-token output reserve; exact full prompts must fit within
  69,632 tokens. The sample's selected prompts range from 24,645 to 68,817
  tokens. Sift target is 24,576 estimated tokens, matching the prior published
  LongBench screens; it is below the current `main` default of 32,768.
- Frozen Sift core SHA-256:
  `80a87f088448f2f6ee658e8e101a6ac8d85b0f3d3a45bc264f1d96ca38444371`.

## Arms and scoring

Compare only full context and Sift. Use three randomized repeats for each of
the 100 tasks and each arm, for 600 total calls. Both arms use the same
system/user/assistant/user prompt structure, the same pinned answer key, and a
strict JSON schema requiring one choice in A/B/C/D. Temperature is 0.1,
top-p 0.8, top-k 20, reasoning disabled, 16 output tokens maximum, and prompt
cache disabled. Retries are disabled. The run seed is 20261022; the runner uses
one shared generation seed per repeat and randomizes arm order within each task
and repeat.

A call is correct only if it terminates normally and returns a valid structured
choice matching the official answer key. Invalid or truncated outputs remain
incorrect in the denominator. Report both raw correct calls and task-level
strict majority over the three repeats; a task counts correct only when at
least two of its three calls are correct. The task, not each repeat, is the
independent unit for paired outcomes.

No answer-driven Sift changes, prompt edits, manual rescoring, or retries are
allowed after generation begins. Local model calls have no provider API charge;
hardware and electricity costs are not measured. These results do not
establish Astra or Opus quality or billing outcomes.

## Reproduction

Freeze the sample without model generations:

```powershell
python benchmarks/prepare_longbench_v2.py `
  --model-context 73728 --output-reserve 4096 --target 24576 `
  --sample-size 100 --seed 20261021 `
  --output docs/evals/longbench-v2-qwen-100-manifest-2026-10-16.json
```

Run after the protocol and manifest are frozen:

```powershell
python benchmarks/run_longbench_v2.py `
  --manifest docs/evals/longbench-v2-qwen-100-manifest-2026-10-16.json `
  --output docs/results/longbench-v2-qwen-100-2026-10-16.json `
  --repeats 3 --seed 20261022 --target 24576 --model-context 73728 `
  --arm full --arm sift
```
