# Native agent acceptance

Run public development tasks with native Claude Code or Codex through an isolated
LiteLLM gateway. The runner copies a case, asks the client to complete it, and
checks the delivered artifact. It does not implement provider transport.

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
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml config --quiet
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml up -d --force-recreate
curl --fail --silent --output /dev/null -H "Authorization: Bearer $SIFT_NATIVE_GATEWAY_KEY" http://127.0.0.1:4010/v1/models
```

Wait for that authenticated readiness check to succeed before starting a task.

The pinned image runs LiteLLM 1.103.0. It mounts only this checkout's library and
benchmark files read-only, with no Subroute database, policy state, credentials,
or global client configuration. It shares the Qwen engine and its resource/cache
state. Avoid other inference during measurements. No database service is required.

Both arms use `qwen3.8-27b`, a 24,576 estimated input-token target including tools,
a 1M estimated raw-input limit, and at most 4,096 output tokens. The configured
model context is 32,768. Estimates are not exact provider/template token counts.
The `recency` arm retains complete recent protocol units under the same ceiling;
it can leave unused space. The `sift` arm uses Sift's selection. Neither arm
silently raises an explicit output cap.

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
an allowed source change, no extra/unauthorized files, and passing visible and
gold checks. The harness tests separate delivered snapshots. Gold `test_*.py`
modules enter only the post-client acceptance copy, never the client workspace.
Research has two visible and two gold checks. Build has six visible checks and
seven gold checks: five original checks plus two contract regressions added after
an earlier experiment. All seven were predeclared for this portable public case;
their chronology does not make them fresh held-out evidence.

Client configuration is per invocation with an isolated home, bounded tool access,
and no global config edits. The model phase defaults to a 1,200-second deadline;
the Codex readiness probe is bounded to 20 seconds. Owned process trees are
terminated using Unix process groups or a Windows kill-on-close job. Provider
requests have a 90-second timeout, no configured retries/fallbacks, and disconnect
cancellation. Native traces are checkpointed before parsing and final tests, so
a harness failure remains distinct from a model-quality failure.

## Compare arms and interpret results

Save the first arm's reports and gateway logs, then recreate for the other arm:

```bash
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml logs --no-color native-benchmark > sift-gateway.log
export SIFT_BENCH_ARM=recency
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml up -d --force-recreate
# Repeat the same client/case commands, retaining each new evidence directory.
docker compose -p sift-native-eval -f benchmarks/compose.native.yaml down
```

Recreation does not clear the shared engine's KV/prefix cache. Predeclare cold or
warm conditions, control/reset the backend cache through its supported mechanism,
and verify provider cached-token evidence; missing counts mean unknown. Alternate
arm order across repeats. Keep model, output budget, fixtures, and engine settings
fixed. The runner does not reset cache or force `cache_prompt=false`.

Report whole-task acceptance and elapsed time, request count, selector CPU/wall
time, and provider token/cache usage where available. Client-reported usage and
Claude TTFT are labelled as such; unavailable TTFT is null, and decode TPS is not
fabricated from task duration. Task paths can diverge, and auxiliary CLI requests
can consume tokens. A faster failed task is not an equivalent speedup. Neither
one passing case nor a cold-to-warm timing change establishes general savings;
monetary claims also require explicit provider pricing and cache discounts.
