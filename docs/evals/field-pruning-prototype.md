# Field-pruning prototype audit

`field_pruning=True` is an experimental, shape-based prototype and remains
disabled by default. The selector only considers a root JSON object with one
unambiguous object-array whose rows map one-to-one to all explicit choices,
plus a separate scalar-bearing summary array. It removes only conversation-
shaped nested arrays from the selected rows and preserves other root values,
including shared round summaries. For CSV, every option must occur in one
unique non-group column before complete sibling rows can be retained.

This is a four-case offline retention and token-budget audit. It does not call a
model, establish answer quality after compaction, or show that the pruning rule
generalizes to other prompt and data shapes. Keep the feature opt-in until
broader held-out evidence supports a default change.

Run it with local copies of the pinned LongBench v2 dataset and MiniMax M3
tokenizer:

```powershell
python benchmarks/audit_longbench_v2_field_pruning.py `
  --dataset path\to\data.json `
  --tokenizer path\to\tokenizer.json `
  --output path\to\field-pruning-audit.json
```

The script validates the pinned dataset hash, recomputes each gold answer from
the source data, checks all four option-linked rows and required sibling or
round-summary evidence, verifies source immutability, and enforces the 32,640
token target and a per-case ceiling of 110% of default Sift's forwarded tokens.
The JSON result records the dataset, tokenizer, core, template-source, and
audit-script hashes; `audit_body_sha256` hashes the canonical report body
before that checksum field is added. The audit performs no network requests.

## MiniMax answer-quality pilot

The offline retention audit does not establish whether a model still answers
correctly after compaction. The next stage is a separate, frozen 36-request
screen using four pinned LongBench v2 development tasks, three repeats, and
three concurrent arms: full context, default Sift, and opt-in `field_pruning`.
Each task/repeat block shares a seed and randomizes arm order. Requests are
pinned to OpenRouter `minimax/minimax-m3`, provider `minimax`, with fallbacks
disabled. There are no retries or substitutions.

Prepare the exact request artifact offline:

```powershell
python benchmarks/run_longbench_v2_minimax_field_pruning_pilot.py prepare `
  --dataset path\to\pinned\data.json `
  --tokenizer path\to\minimax-m3-tokenizer.json `
  --template path\to\minimax-m3-chat-template.jinja `
  --offline-gate docs\evals\longbench-v2-field-pruning-offline-audit-2026-10-17.json `
  --preflight-output docs\evals\longbench-v2-minimax-field-pruning-pilot-preflight-2026-10-17.json `
  --seed 20261023
```

Preparation performs no model/API calls. Review and commit the generated
artifact, then calculate its exact SHA-256. The explicit `dispatch` mode
requires that expected SHA, refreshes the live MiniMax route and a spend ledger
checked within 30 minutes, and refuses to send unless the whole conservative
reserve fits the `$4` run guard and `$20` aggregate authorization. The runner
checks the expected artifact hash before looking up credentials or contacting
the route. It then records every request/response and stops on route, transport,
receipt, or budget anomalies. A complete billable response with an invalid
answer remains in the dataset and scores incorrect.

The analyzer requires both the complete run report and its verified preflight.
It scores only a complete raw SSE stream containing one JSON `answer` key with
an A–D choice, validates answer/request metadata against the frozen manifest,
reconciles observed cost to provider receipts, reconstructs uncached cost from
the verified endpoint rates, and reports preprocessing, request, and combined
pipeline timing. The four-task result is a screening signal; do not present it
as a LongBench-wide quality or savings claim.
