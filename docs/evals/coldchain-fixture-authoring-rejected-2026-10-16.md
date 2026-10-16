# Cold-chain fixture authoring attempt, 2026-10-16

## Decision

Reject this partial candidate for long-context evaluation. No agent-task
comparison was run, and the fixture was not copied into the repository.

Claude Code 2.1.251 ran in a temporary isolated configuration against the local
Qwen 3.8 27B backend. It reached the local benchmark gateway with a dummy
gateway key; no provider API was used. The call stopped at the configured
18-turn limit (`error_max_turns`, 19 turns reported, 633,848 ms). The CLI's
`total_cost_usd` model-map estimate was $0.8058255; it is not a provider bill.
Hardware and electricity costs were not measured.

The generated `coldchain-excursion-audit` candidate has eleven task input files
and 16,580 characters. The new preflight utility counted the task files once
with the local Qwen tokenizer and returned **6,391 tokens**, before
native-client tool schemas and other conversation overhead. This is far below
Sift's 24,576-token trigger and cannot exercise compaction. The candidate
author explicitly described the evidence corpus as compact and under the
32,768-token context window. This canonical preflight supersedes the earlier
ad hoc count, which omitted `data/manifest.json`.

The generated manifest is unusable for the native runner. It records SHA values
as `unverified`, uses a `files` map instead of the runner's required
`input_sha256` and `acceptance_sha256` maps, and includes the gold test among the
case files. Its manifest SHA256 is
`45c9c3d5f7b3048c13f8e1d4cfb83f602afd256f079dc552e707c4fe9eca769d`.

I ran the visible and gold suites against the intentional TODO starter. Each
discovered nine tests and failed all nine because `audit.py` raises
`NotImplementedError: TODO: load evidence` during shared setup. That confirms a
failing starter, but it does not validate that the gold suite distinguishes a
correct solution from plausible wrong implementations. No solved task or
acceptance result exists.

## Changed authoring requirement

The next authoring assignment needs a numeric context range and an exact local
tokenizer preflight, not a qualitative request for a “long” corpus. The new
[fixture preflight command](../../benchmarks/freeze_agent_fixture.py) computes
the flattened source count and writes the native runner's `input_sha256` and
`acceptance_sha256` schema only when an explicit range passes. For example:

```powershell
python benchmarks/freeze_agent_fixture.py `
  --case benchmarks/agent_cases/<case> `
  --gold benchmarks/agent_gold/<case> `
  --manifest benchmarks/agent_gold/<case>/manifest.json `
  --min-source-tokens 18000 --max-source-tokens 22000
```

The flattened count is a corpus-sizing gate, not a rendered native request
count. Require an actual multi-turn run to show the full context crossing the
target while staying below the matched full-context ceiling. Reject the
candidate before task inference if the corpus range or standard manifest
verification fails. Preserve this candidate only in the local temporary
directory `sift-independent-author-20261016`; it is not part of the benchmark
corpus.
