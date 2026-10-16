# Massive-context swarm comparison protocol

## Purpose

The current native-agent fixtures do not test Sift at the raw context scale
where it is expected to help. The largest recent native comparison started
from a 19,496-token flattened source estimate, and the native runner disabled
Claude Code's `Agent` tool. Its failed run is a useful loop/overhead diagnostic,
not evidence about large-context swarm behavior.

This protocol's first qualification pilot targets about 550K raw input tokens
in one prepared task request, followed by a multi-workstream
software-operations task. The larger experiment must cover additional raw
context bands above 500K after the pilot, with each band measured per request.
Scale must come from task-relevant data, not unrelated filler. The large packet
is a deterministic synthetic legacy delivery snapshot whose replay duplicates,
payload conflicts, and migration ledger are part of the required idempotent
import behavior.

## Frozen scenario

Use the new fixture with connected work across webhook API idempotency, worker
retry semantics, schema migration, and the operator runbook. The frozen
`swarm_context.md` packet is a checkpoint artifact, not the final user request.
Prepare one persisted Claude Code session with the packet in historical
tool/file-result context, verify it was not truncated, then fork that exact
checkpoint for each arm and send the same short final task request. The latest
user turn must stay short: Sift protects that turn, so putting the packet there
would test oversized-active-turn rejection rather than historical compaction.
Require four named read-only subagents for the API, worker, migration, and
operations investigations. The parent is the only writer.

The exact current packet is **1,849,622 bytes** and has a **559,763-token
packet-only local estimate** with pinned LiteLLM 1.103.0 and a fixed system
message. That clears the fixture-design scale estimate, not the trial gate.
The actual prepared historical request in each arm must be measured at 500,000
or more input tokens by the deployed route counter before selection. The full
arm must also confirm provider-reported input usage. Use a 500K–900K measured
raw-input band for the first comparison so the full-context control leaves
room inside the provider's 1M window for system/tool overhead and output. Add
higher bands only after the same end-to-end qualification passes at the lower
band.

Use Claude Code 2.1.251 through the same MiniMax M3 OpenRouter route for every
arm. Freeze the task prompt, input/gold manifest, exact context packet, model
aliases, client settings, and workspace before the first run. Verify the
gateway uses the pinned MiniMax profile with a 1,044,480-token input limit; the
currently running older profile is capped at about 200K and is ineligible.

Prepare the checkpoint with `benchmarks/seed_claude_checkpoint.py`, using the
full-context alias and an isolated new `CLAUDE_CONFIG_DIR`. A single oversized
MCP result is truncated by Claude Code and replaced with a file-read notice, so
the helper exposes the packet as numbered, bounded MCP results. It verifies the
complete concatenated SHA-256 in both Claude's stream and the saved JSONL
transcript. Claude Code's `--max-budget-usd` is recorded as a client limit, not
a hard provider spend cap. Fork that session for each
arm with `benchmarks/agents.py --resume-session-id <uuid>
--claude-config-dir <same-directory> --checkpoint-packet
<case>/swarm_context.md`; do not pass `--context-file` for this experiment.
The runner records the checkpoint packet hash and calls Claude with
`--fork-session`, leaving the prepared parent unchanged. The seed report alone
does not prove 500K input: require a callback count on the subsequent prepared
request and full-arm provider usage before qualifying the pair.

## Scale gate

Measure the actual prepared checkpoint request with the deployed LiteLLM/
MiniMax route counter before selection, including tool schemas and the short
active user request. A qualifying trial must show all of the following on the
first task request after checkpoint preparation:

1. At least **500,000 raw input tokens** reach the route counter on the first
   task request in every arm. Record a body-free per-request event for the full
   and Sift arms with sequence, raw count, forwarded count, target, and count
   status. A packet-only estimate or sum across requests does not qualify.
2. Sift forwards no more than the assigned target (64,000 or 32,000 tokens),
   with the task instructions and active tool cycle preserved.
3. The matched full-context arm receives the same complete historical context,
   without truncation, is measured in the same 500K–900K raw-input band, and
   remains below the model's 1M context limit with output reserve. Reconcile
   route counts with provider-reported input usage and report cache-read tokens
   separately.
4. The trace shows all four named read-only subagent calls, ordinary task
   tool use, and the same workspace and source inputs. Repeated file reads
   without delegated work do not qualify as a swarm.

### Provider-free preflight

Run `python -m benchmarks.preflight_massive_context_sift` for the reproducible
selector stress check. It builds an Anthropic Messages tool-cycle request from
the exact 38 bounded chunks of `webhook_swarm_500k/swarm_context.md`, appends
the frozen webhook-migration request, then calls Sift's actual LiteLLM Proxy
adapter with a LiteLLM 1.103.0 Router counter. It compares full context with
Sift at 64K, 48K, 32K, 24K, and 16K without contacting a provider. The packet
is **1,849,622 bytes** (SHA-256
`b29a4fd63a906764e026ba6ffc1e698e4fc41d9e62519e591597f0c0ca07400e`).

The latest provider-free preflight counted **560,436 raw input tokens**. The
full arm forwarded all 560,436 unchanged. Sift forwarded **63,904 / 47,756 /
31,989 / 23,918 / 15,899** at the five targets, taking **0.97–1.12 seconds**
of local selector time per target. All five were under their requested token
ceilings. The mechanical evidence audit retained **4 / 4 / 3 / 3 / 3 of 16**
required spans at those targets. At 64K and 48K, retained evidence was one
source row, one crash-window record, one migration-recovery record, and one
early-retry record; the two smaller targets also lost the source row. The
selector omitted the tenant identity and payload contract, retry and lease
policy, migration reconciliation/schema, snapshot cohorts and duplicate/
conflict exemplars, metrics, rollout, rotation, and tenant-collision evidence.
The target reached the intended scale, but this preflight fails the
evidence-retention check. It is not a qualified agent comparison or a quality
pass. Do not spend on the paid swarm run until a query-specific retrieval plan
or selector change can recover the facts needed by each workstream within the
budget.

This is a constructed Anthropic Messages history, not Claude Code's exact
serialized request. It omits Claude Code's system prompt and active tool
schemas, and the task/file evidence are fictional controlled development data.
It therefore does not establish exact client request size, provider
ingestion, task acceptance, or task quality. The host's LiteLLM 1.100.1 is not
eligible for this check; the script fails closed unless the installed counter
is exactly 1.103.0. The run used the dedicated benchmark container. The older
`.runs/multi_domain_swarm_500k_offline_preflight.json` measured a different
incident-reconstruction packet and is not evidence for this webhook task.

The Oct 16 Gemini 4 Argon and GPT-6.1 Sol advisor council agreed that this is
a credible candidate but not a qualified comparison. Their advice changed the
next check to require offline validation of the exact forked requests, plus a
spend ceiling and effective stop condition before paid inference. Reported
advisor usage was 1,655 Gemini tokens and 957 Sol tokens.

Before paid inference, capture each fork's first serialized task request
offline and check the same 500K raw floor, equal full/Sift history, and Sift
forwarded ceiling. Then require an explicit total spend ceiling and an
effective preflight/stop mechanism. A Claude client budget is not a hard
provider spend cap.

If any scale condition is missed, report a harness qualification failure and
do not call the run a 500K-context comparison. A sum of tokens across many
small requests does not satisfy the raw-request gate. Record checkpoint
preparation time and cost separately, and include shared preparation in total
cost per accepted task so the Sift arm does not get an accounting advantage.

## Arms and outcomes

For the first pilot, compare full context, Sift at 64K, and Sift at 32K at the
same measured raw-input size. After it qualifies, repeat at larger measured
bands (for example 750K and 900K) with a newly frozen, task-relevant packet for
each band. Compare full context, Sift at 64K, and Sift at 32K. Add complete-message
recency only if the current protocol adapter can represent the same request
without dropping tool links or changing roles. Keep model, client version,
output cap, spend cap, permissions, fixture, initial prompt, and completion
limits fixed. Randomize arm order within paired blocks and repeat from the
same frozen task/workspace state. Preserve failed runs and their spend.

The independent gold suite checks API behavior, tenant-scoped idempotency,
payload conflict handling, retry ordering/backoff, migration compatibility,
runbook claims, and cross-workstream consistency. A visible test pass alone is
not acceptance. Require only allowed files to change, a normal terminal
result, a real failing-to-passing test loop, all four subagent roles, and all
independent tests.

Record per request raw/forwarded tokens, target, compaction count and CPU time,
TTFT, decode throughput when the stream can measure it, cached/uncached/output
usage, provider-reported cost or invoice, total task time, turns, agent count,
and acceptance. Report total cost per accepted task. Label estimates and
client-reported cost distinctly from provider invoices.

For each runner report, save the isolated gateway log and run
`benchmarks/qualify_massive_context.py` with the arm, gateway log, client
`result.json`, first task request sequence, and Sift target. The callback emits
the full-arm raw/forwarded count through the same pinned LiteLLM route counter
used by Sift; the full prompt itself remains unchanged. It also logs body-free
provider response usage against the same request sequence. OpenAI-compatible
`prompt_tokens` is treated as the input total and cached tokens are reported
separately, without adding them twice. The runner also retains body-free
per-response usage fields from Claude's stream. The qualification tool prefers
the exact callback sequence and falls back to the nearest later response-stream
start only when that event is absent. Preserve the emitted JSON with the run.
It separates `scale_qualified` from `task_accepted`; both are required for a
qualified successful trial. Stream usage is not an invoice.

The first paired run is a harness pilot only. Do not infer noninferiority,
general savings, or a quality gain from one fixture. Broader claims require
multiple independently authored held-out tasks and repeated paired runs.

## Current status

The dedicated 1M-configured MiniMax gateway accepted one **615,784-token**
full-arm request and returned HTTP 200 while seeding the multi-domain packet.
That run is not qualified: Claude Code exited nonzero, its transcript and
stream did verify the full packet, but its client-reported per-response usage
was only 3,877 tokens and could not be matched to the large route event. Its
reported **$3.09 is an aggregate seed-session cost**, not the price of that
single request, and exceeded the configured $1.50 client budget after the work
had already completed. Do not treat the client budget as a hard spend guard.

The isolated gateway now records body-free provider response usage with the
same benchmark request sequence; a small real Claude/MiniMax smoke matched
route and provider events. The cross-domain fixture and output-only acceptance
harness are prepared, and targeted offline tests pass. The older 612,519-token
offline preflight used a different incident-reconstruction packet and does
not qualify this webhook workload. The latest webhook-specific constructed
history exceeds 560K tokens, but its current selector misses most required
contract spans as detailed above. The paired 500K+ agent task has not run.
Continue only after selecting a total spend ceiling
and qualifying the exact forked requests for the paired experiment. The
fixture's connected workstreams are a first pilot, not
enough to generalize across domains. The earlier embedded initial-user-message
path is ineligible for measuring Sift compaction and must not be used to claim a
500K result.
