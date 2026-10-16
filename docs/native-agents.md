# Native agent acceptance

Run public development tasks with native Claude Code or Codex through an isolated
LiteLLM gateway. The runner copies a case, asks the client to complete it, and
checks the delivered artifact. It does not implement provider transport.

Each run sends the case README as one initial user request; the native agent's
ordinary tool loop builds the conversation history. A long-context stress case
must accumulate useful evidence through necessary reads and test results, then
cross Sift's trigger before an evidence-dependent edit. A large README or
synthetic transcript prefix does not qualify. Keep the native trace and
per-request gateway audit for every compaction event. The benchmark callback
records selection counts and timing without logging prompt bodies. If the saved
client trace and gateway audit cannot establish whether a required fact
survived, report that retention result as unknown rather than infer it from
token counts.

These fixtures are authored and publicly inspectable, not a private held-out
benchmark. This setup is an evaluation tool, not evidence of a completed
Sift-versus-baseline pilot or guaranteed savings. See [evaluation.md](evaluation.md)
for recorded results and their limits.

## Prerequisites

Use a source checkout containing this document. The installed `sift-context`
package supplies the library and LiteLLM callback; its wheel does not include
`benchmarks/agents.py`, Compose files, or fixtures. From the checkout root:

```bash
python3 -m pip install -e '.[litellm]'
python3 benchmarks/agents.py --help
git rev-parse HEAD
```

Keep the commit, source hashes, native client version, and backend configuration
with each result. The Compose mounts read source files directly, so freeze the
checkout throughout a comparison. Install the native clients separately. The
runner itself uses only Python's standard library.

For Linux/WSL Codex, retain the complete official distribution and its relative
resource layout, including `bwrap`; a standalone copied binary can fail sandbox
startup. The client must support the flags used in `agents.py`. The tested
model-free Linux sandbox probe used Codex 0.154.0. That readiness check does not
establish a successful Codex model task on WSL.

## Start the dedicated gateway

The existing Qwen engine must already be reachable on an external Docker network.
These example defaults match a local Subroute engine; change both values for your
deployment. Port 4010 is a temporary loopback endpoint, separate from the regular
gateway. Generate a dedicated benchmark key rather than reusing production access.

```bash
export SIFT_NATIVE_GATEWAY_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SIFT_NATIVE_NETWORK=subroute_default
export SIFT_NATIVE_BACKEND_URL=http://qwen-local:8080/v1
export SIFT_BENCH_ARM=sift
# Optional: set the current case's evidence.json here before Compose startup.
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml config --quiet
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml up -d --force-recreate
curl --fail --silent --output /dev/null -H "Authorization: Bearer $SIFT_NATIVE_GATEWAY_KEY" http://127.0.0.1:4010/v1/models
```

Wait for that authenticated readiness check to succeed before starting a task.

`SIFT_BENCH_EVIDENCE_MANIFEST` is optional. When set, it validates exact
character offsets and SHA-256 hashes against the case files, then logs only
opaque evidence IDs with `retained`, `omitted`, `not_in_input`, or
`forwarded_only` states and a request sequence/UTC timestamp. It never logs
prompt bodies or evidence text. Capture the gateway log for each arm. This
can be checked against the Claude trace after the run:

```bash
python3 benchmarks/audit_native_evidence.py \
  --gateway-log sift-gateway.log \
  --native-trace "$RUN_DIR/native.stdout.jsonl" \
  --workspace "$RUN_DIR/workspace" \
  --manifest benchmarks/agent_gold/least_privilege_rollup/evidence.json \
  --editable audit_rollup.py
```

`verified_before_edit` means the latest logged Sift request that actually
reduced the input, before the first direct Claude `Edit`, `Write`, or
`MultiEdit` to an allowed file, contained every complete annotated span.
Unchanged pass-through requests do not qualify. Shell-mediated edits and other
client trace formats return `unknown` until a client-specific parser exists. This proves
literal span presence and event order, not that the model attended to or used
the span. The rollup annotations are exposed harness calibration data, not
held-out evidence.

For the rollup fixture, set
`SIFT_BENCH_EVIDENCE_MANIFEST=/bench/agent_gold/least_privilege_rollup/evidence.json`
before starting Compose. Pin the exact `evidence.json` bytes in that fixture's
`manifest.json` using `evidence_sha256` and pass that fixture manifest to
`agents.py`; preflight rejects changed annotations before the client runs.
Omit the variable for tasks that do not use that evidence manifest.

The pinned image runs LiteLLM 1.103.0. It mounts only this checkout's library and
benchmark files read-only, with no Subroute database, policy state, credentials,
or global client configuration. It shares the Qwen engine and its resource/cache
state. Avoid other inference during measurements. No database service is required.

The `sift` and `recency` arms use `qwen3.8-27b`, the same 24,576 estimated
input-token target including tools, a 1M estimated raw-input limit, and at most
4,096 output tokens. The `recency` arm retains complete recent protocol units
under the same ceiling and can leave unused space. The `sift` arm uses Sift's
selection. The uncompressed `full` arm calls the same backend through
`qwen3.8-27b-full`, an explicit alias that bypasses the callback; requests that
exceed the model's 28,672 input allowance are capacity failures. All aliases
use the same 32,768 context model and 4,096 output limit. Estimates are not exact
provider/template token counts. No arm silently raises an explicit output cap.

`native_callback.py` fixes the selector at process startup using a temporary
private integration binding. It also narrowly repairs LiteLLM 1.103.0's counter
formatter for valid arrays without `items`: native sync/async Router checks can
otherwise fail open. Provider tool objects stay unchanged. Retire that counter
repair when the pinned native formatter is fixed; retire the selector binding
when this experiment ends or a supported selection hook becomes available.
The same model profile explicitly places in-sequence Anthropic system/developer
messages before dialogue because this Qwen template rejects later instruction
entries and the pinned image adapter preserves their positions. Clean PyPI
1.103.0 has different adapter source and can demote unsupported late systems to
user messages. The profile must preserve the original leading instruction roles
and text on both builds; matching version labels alone do not prove matching
source. See [build provenance](results/litellm-build-provenance-2026-10-15.json). Original objects,
roles/content, within-group order, top-level system, tools and caps remain exact.
Instruction position changes deliberately; this is not general equivalence for
arbitrary late instructions. The profile applies before counting in both arms.
Chat/Responses and other models are unchanged. Retire it when the native adapter
or backend template supports the required placement. Sift's product callback
retains its separate instruction-position contract.
Never import this benchmark callback into a running production/staging gateway.

## Run a task

Run from the checkout root on the same host as the loopback endpoint. These are
two task examples; either client can run either case by changing `--client`.
Keep the case, gold, and editable-file arguments together:

```bash
python3 benchmarks/agents.py --client claude \
  --case benchmarks/agent_cases/research_evidence_audit \
  --gold benchmarks/agent_gold/research_evidence_audit \
  --editable findings.json --base-url http://127.0.0.1:4010/v1 \
  --model qwen3.8-27b --api-key-env SIFT_NATIVE_GATEWAY_KEY --timeout 1200

python3 benchmarks/agents.py --client codex \
  --case benchmarks/agent_cases/build_planner \
  --gold benchmarks/agent_gold/build_planner \
  --editable build_manifest.py --editable incremental.py \
  --base-url http://127.0.0.1:4010/v1 --model qwen3.8-27b \
  --api-key-env SIFT_NATIVE_GATEWAY_KEY --timeout 1200
```

For a frozen fixture, pass its manifest with `--manifest`. The runner verifies
the complete input file set and the exact hidden-test hashes before starting a
client, then records the verified hashes in `result.json`. For example:

```bash
python3 benchmarks/agents.py --client claude \
  --case benchmarks/agent_cases/payment_export_migration \
  --gold benchmarks/agent_gold/payment_export_migration \
  --manifest benchmarks/agent_gold/payment_export_migration/manifest.json \
  --editable reconcile.py --base-url http://127.0.0.1:4010/v1 \
  --model qwen3.8-27b --api-key-env SIFT_NATIVE_GATEWAY_KEY --timeout 1200

python3 benchmarks/agents.py --client claude \
  --case benchmarks/agent_cases/least_privilege_audit \
  --gold benchmarks/agent_gold/least_privilege_audit \
  --manifest benchmarks/agent_gold/least_privilege_audit/manifest.json \
  --editable audit_iam.py --allowed-output access_audit_report.json \
  --base-url http://127.0.0.1:4010/v1 \
  --model qwen3.8-27b --api-key-env SIFT_NATIVE_GATEWAY_KEY --timeout 1200
```

Use `--allowed-output` only for a declared deliverable the agent must create.
The path must be relative, inside the case, and absent before the run. The
runner executes the failing baseline in a separate copy so test-generated
files cannot leak into the agent's workspace or be mistaken for its output.

Use `--executable /path/to/native/client` when PATH discovery is unsuitable.
On Windows use `python`, PowerShell environment syntax, and an explicit native
Codex backend. For example, with the dedicated key already set in this shell:

```powershell
python benchmarks/agents.py --client codex --case benchmarks/agent_cases/build_planner --gold benchmarks/agent_gold/build_planner --editable build_manifest.py --editable incremental.py --base-url http://127.0.0.1:4010/v1 --model qwen3.8-27b --api-key-env SIFT_NATIVE_GATEWAY_KEY --windows-sandbox unelevated --executable 'C:\path\to\codex.exe'
```

The Windows backend option preserves the native sandbox. Fresh Windows sandbox
readiness has not been established here. Before any Codex model execution, the
runner performs a model-free native workspace-permission probe: an owned inside
write must succeed and be removed, while an owned sibling write must be denied.
A failure, timeout, or boundary violation produces a rejected report and skips
model execution. The runner does not provision, bypass, or copy sandbox state.

## What counts as accepted

Each run gets an owned directory under `~/.cache/sift-agent-runs/`, with a copied
workspace, isolated client home, redacted native traces, and `result.json`.
The source fixtures remain unchanged. Review artifacts before sharing; key
redaction is not a general private-data scrubber.

Acceptance requires an observed failing baseline, a normal native terminal
outcome, an actual client tool loop showing failing then passing unittest runs,
an allowed source change, every declared output, no undeclared or unauthorized
files, and passing visible and gold checks. The harness tests separate delivered snapshots. Gold `test_*.py`
modules enter only the post-client acceptance copy, never the client workspace.
Research has two visible and two gold checks. Build has six visible checks and
seven gold checks: five original checks plus two contract regressions added after
an earlier experiment. All seven were predeclared for this portable public case;
their chronology does not make them fresh held-out evidence.
The AcmePay migration case has one visible and four post-run acceptance checks;
its public manifest pins the exact input files and acceptance test.

Client configuration is per invocation with an isolated home, bounded tool access,
and no global config edits. The model phase defaults to a 1,200-second deadline;
the Codex readiness probe is bounded to 20 seconds. Owned process trees are
terminated using Unix process groups or a Windows kill-on-close job. Provider
requests have a 90-second timeout, no configured retries/fallbacks, and disconnect
cancellation. Native traces are checkpointed before parsing and final tests, so
a harness failure remains distinct from a model-quality failure.

## Compare arms and interpret results

Run the same task once with full context, once with Sift, and once with recency.
The full-context arm uses the explicit `qwen3.8-27b-full` alias and can fail when
the request exceeds the model's input capacity. Sift and recency share the same
compacted budget. The benchmark-only `SIFT_BENCH_TARGET` defaults to 24,576;
set the same value in every arm only for a predeclared target experiment. The
Qwen profile rejects targets above 28,672; the native MiniMax profile permits
targets up to the Sift raw-input limit. Recreate the gateway for every arm and
retain each result and log separately:

```bash
export SIFT_BENCH_ARM=full
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml up -d --force-recreate --wait --wait-timeout 90
# Run the uncompressed baseline with --model qwen3.8-27b-full.
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml logs --no-color native-benchmark > full-gateway.log
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml down

export SIFT_BENCH_ARM=sift
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml up -d --force-recreate --wait --wait-timeout 90
# Run with --model qwen3.8-27b.
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml logs --no-color native-benchmark > sift-gateway.log
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml down

export SIFT_BENCH_ARM=recency
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml up -d --force-recreate --wait --wait-timeout 90
# Run with --model qwen3.8-27b.
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml logs --no-color native-benchmark > recency-gateway.log
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml down
```

### MiniMax M3 through OpenRouter

The MiniMax profile uses the same OpenRouter model and output limit for all
arms. Its `minimax-m3-full` alias is deliberately unregistered with the Sift
hook; `minimax-m3-sift` is the only alias the Sift or recency selector can
compact. The profile supports 1M input budgets and therefore allows the 16K,
24K, 32K, 48K, and 64K target sweep. The actual provider context is 1,048,576
tokens; keep prompt plus reserved output within that limit. See the current
[OpenRouter MiniMax M3 model card](https://openrouter.ai/minimax/minimax-m3).

Set `OPENROUTER_API_KEY` and a dedicated `SIFT_NATIVE_GATEWAY_KEY` in the
shell, then use both Compose files for each fresh arm:

```bash
export SIFT_BENCH_TARGET=65536
export SIFT_BENCH_ARM=full
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml up -d --force-recreate --wait --wait-timeout 90
# Run the native task with --model minimax-m3-full.
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml logs --no-color native-benchmark > full-gateway.log
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml down

export SIFT_BENCH_ARM=sift
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml up -d --force-recreate --wait --wait-timeout 90
# Run with --model minimax-m3-sift.
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml logs --no-color native-benchmark > sift-gateway.log
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml down

export SIFT_BENCH_ARM=recency
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml up -d --force-recreate --wait --wait-timeout 90
# Run with --model minimax-m3-sift.
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml logs --no-color native-benchmark > recency-gateway.log
docker compose -p sift-native-m3 -f benchmarks/compose.native.yaml -f benchmarks/compose.native.minimax-m3.yaml down
```

Keep target size, fixture, output limit, and cache condition identical across
arms. The authored webhook fixture is only 2,333 static source tokens and has
not qualified as a natural compaction task; do not use it to claim a Sift
comparison unless actual native request logs show a qualifying pre-edit
compaction.

Recreation does not clear the shared engine's KV/prefix cache. Predeclare cold or
warm conditions, control/reset the backend cache through its supported mechanism,
and verify provider cached-token evidence; missing counts mean unknown. Alternate
arm order across repeats. Keep model, output budget, fixtures, and engine settings
fixed. The runner does not reset cache or force `cache_prompt=false`.

Report whole-task acceptance and elapsed time, request count, selector CPU/wall
time, and provider token/cache usage where available. Client-reported usage,
Claude TTFT, decode tokens/second, and cost keep their source labels. Decode
tokens/second uses the client stream's first-to-last generated-content interval
and response output-token count; it is not backend-only throughput. Missing
stream timing or cost stays null rather than being inferred from task duration.
Client cost is not an independently verified provider invoice. Task paths can
diverge, and auxiliary CLI requests can consume tokens. A faster failed task is
not an equivalent speedup. Neither one passing case nor a cold-to-warm timing
change establishes general savings; monetary claims also require explicit
provider pricing and cache discounts.

## Reproduce the LLMLingua-2 development answer probe

This optional text-only probe uses the already public synthetic coverage
cases. It is not an agent-task or held-out benchmark. It requires WSL/Ubuntu,
Python 3.12, `uv`, a local llama.cpp server at `127.0.0.1:8088` serving
`qwen3.8-27b`, and several gigabytes for the isolated PyTorch/LLMLingua
environment and XLM-R weights. It makes local inference calls only and does
not add LLMLingua to Sift's runtime dependencies.

From the repository root in WSL:

```bash
uv venv --python 3.12 /tmp/sift-llmlingua2-eval
uv pip sync --python /tmp/sift-llmlingua2-eval/bin/python benchmarks/llmlingua2-development.lock
export PYTHONPATH=src:benchmarks
export HF_HOME=/tmp/sift-llmlingua2-hf
/tmp/sift-llmlingua2-eval/bin/python benchmarks/llmlingua2_development.py docs/results/llmlingua2-development-2026-10-16.json
```

The lock pins the isolated Python packages; the runner pins the LLMLingua model
revision and exact local Qwen prompt-token check. The current run's method,
answers, token counts, and limitations are in the [development report](results/llmlingua2-development-2026-10-16.json).
