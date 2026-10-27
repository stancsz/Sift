# Native CLI acceptance

These opt-in tests send real native client requests through an owned loopback
Sift proxy to `http://127.0.0.1:4000/v1`, using Subroute's dynamic `default`
alias. They never change a shared gateway or select a fixed upstream backend.
Use a source checkout with the `test` and `litellm` extras and installed native
OpenCode, Claude Code, and Codex CLIs.

## One-task smoke

With an authorized inference key already in `SIFT_ACCEPTANCE_API_KEY`:

```powershell
python -m benchmarks.cli_acceptance --client opencode --output-dir .cache/sift-opencode-smoke
python -m benchmarks.cli_acceptance --client claude --output-dir .cache/sift-claude-smoke
python -m benchmarks.cli_acceptance --client codex --output-dir .cache/sift-codex-smoke
```

Output directories must be new. Each run creates synthetic task files, injects
an oversized old archive with a planted setting, and requires native reads,
a failing baseline, real edits, a successful native final test, and independent
gold checks. The historical fact must occur in the injected source's retained
excerpt; a later agent echo cannot satisfy this check. The test file must stay
unchanged. A zero exit code, HTTP 200, or a final claim alone cannot pass.

## Long-session campaign

```powershell
python -m benchmarks.cli_matrix --create-scoped-keys --output-dir .cache/sift-27-session-matrix
```

This explicit opt-in uses the existing local `GATEWAY_MASTER_KEY` only in the
orchestrator to create one model-restricted inference key per session. Each key
has a 20-minute lifetime, a $0.50 budget ceiling, and at most two parallel
requests. Keys are revoked and their exact aliases checked absent in `finally`.
The master key is removed from session-runner environments; native clients
receive only a dummy credential for their owned loopback proxy. No credential
is written to a report, configuration file, prompt, or command argument.

The matrix is three clients × three task types × three repetitions: 27 sessions,
with at most two active sessions. Tasks cover a numeric-library repair,
a configuration migration, and expense processing. The expense task also reads
a changing synthetic CSV and produces an independently checked daily JSON report.

Every accepted session must exceed **185 seconds of active native client wall
time**, use at least six user turns with the same native session ID, and finish
all observed turns successfully. Turns introduce cumulative requirements and
seed-specific regression probes. There is no sleep padding. API wait counts
as native wall time; this is not a throughput benchmark. Hidden tests use a
different seed, and input/test files and unexpected outputs are checked.

`matrix.json` and per-session `result.json` are checkpointed after progress.
They include source hashes, native tool evidence, compaction audits, historical
fact checks, duration, session continuity, and failures. Raw traces use synthetic
fixtures only. Client homes/workspaces remain local; do not add them wholesale
to Git. The matrix stops on failed criteria and revokes scoped keys. Fix the
cause before rerunning; preserve failures rather than overwriting them. Source
changes during a session invalidate it.

After inspecting a failure and resolving its cause, explicitly rerun the same
command with `--resume`. Resume requires identical source hashes, no unresolved
active sessions and revoked prior keys. It keeps qualifying completed sessions,
starts fresh workspaces for failed/pending cases, and preserves every attempt
in `matrix.json`. It does not automatically retry failures or erase their
receipts. A provider failure is reported separately from Sift behavior.

## Client isolation and protocol checks

Claude and OpenCode use fresh configuration/data homes. Claude's available
`Edit` tool populates pre-created empty JSON stubs; no unavailable `Write` tool
is required. Windows Codex uses its already-provisioned native sandbox runtime,
ignores user config/rules, and gets process-local provider/catalog settings.
Every Codex session first proves inside-workspace write and sibling-write denial
without model calls. No sandbox state is copied and no bypass flag is used.
Each session has its own workspace and explicit native ID.

The proxy uses Sift's real adapter and deployed LiteLLM counter. Provider SSE
bytes are relayed, catalog and retained sealed-reasoning items are compared
against their originals, and counting substitutions never reach the provider.
Raw/input-size guards and overflow behavior have separate deterministic tests.

Functional acceptance and transport cleanliness are separate. A completed
native session may qualify after its client recovers an HTTP 500 whose JSON
`error` string or `error.message` starts with `APIConnectionError:` (optionally
prefixed `litellm.`) and contains `OpenrouterException - Connection closed.`.
Only the first 8192 error bytes are inspected; malformed/truncated JSON or
markers in unrelated fields do not qualify. The proxy records only that classification, relays the
error bytes/status unchanged and adds no retry. Its receipt then exposes
`transport_clean=false` and `recovered_provider_disconnects`; this does not
resolve production transport reliability. Unknown errors, fatal native turns,
and any failed functional/Sift check still reject the session. Earlier
campaigns used a stricter all-HTTP-200 gate; their original failures remain
preserved rather than retrospectively relabeled.

Each allowed disconnect must match a later HTTP 200 with the same hash of the
native endpoint and request payload, received after the error response finished.
An earlier or concurrent success, unrelated payload, or missing completion
timestamp cannot establish recovery. Only hashes and monotonic times are saved.

These are bounded synthetic compatibility and persistence checks. They do not
establish universal bug freedom, broad answer-quality parity, every provider's
context fit, or production load capacity. Consult the issue #59 receipts for
completed coverage and outstanding cases.
