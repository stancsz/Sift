# Sift Northstar handoff — 2026-10-21

## Goal and current constraint

The [full goal](goal.md) remains active: make Sift useful and credible to adopt, then publish the stable release after its quality, adoption, compatibility and publishing criteria are resolved. Do not narrow this to packaging success. Prior turn was progress: PR #53 merged and issue #13 was repaired. The paid fresh LongBench run is live; observe it rather than restarting. Account/balance/invoice reconciliation is retired by the user's explicit instruction; report our token/rate calculation.

Use only `C:/Users/stanc/.codex/worktrees/inference-free-demo/Sift`. Never inspect dirty `D:/github/Sift` or broadly search/read `.runs`. Earlier accidental delegated searches touched private snippets; they were not relied on. Reviewers must not access current or old private reports. Root alone may use the exact numeric sanitizer below, and after terminal completion the accepted aggregate analyzer on the exact current prefix/continuation. Never expose questions, answers, choices, task IDs or raw streams.

## Current integration

- Branch `codex/public-memory-protocol` starts at main `7dfd1e479a6fa6d4f885dfe0791ae866919b66ac` (PR #53). It changes no runtime source or version. Pending work: [prospective public-memory protocol](docs/evals/longmemeval-v2-public-protocol-2026-10-21.md), aligned goal/roadmap/adapter links and this consolidated handoff. The specification is proposed, not an executable frozen run or dispatch authority. Historical handoffs remain in Git; use linked evidence rather than reviving superseded startup/billing instructions.
- [PR #53](https://github.com/stancsz/sift/pull/53) shipped the accepted clean first-run repair, optional MiniMax SDK transport and local release evidence. PR Core smoke passed in 52 seconds; post-merge [39696035794](https://github.com/stancsz/sift/actions/runs/39696035794) passed in 49 seconds. Watch `80491` is terminal. Standing user merge approval applies to independently reviewed, green PRs.
- Issue [#13](https://github.com/stancsz/sift/issues/13) was updated and re-read successfully at `2026-10-21T23:51:43Z`, after verifying its original-body hash and the merged README anchor. It links to canonical no-model setup. Receipt: `tmp/readme-first-run-issue/change.json`. Consent/privacy and **three total sessions** remain unchanged. No direct outreach, volunteer replies or sessions are claimed.
- Do not create status-only PRs or repeat full suites for recordkeeping. Batch new evidence with substantive work. Commit only named paths; never stage private/ignored run data.

## Live fresh LongBench run

**Do not relaunch.** Durable hidden Python **PID 25244**, created **2026-10-21T22:54:05Z** (`2026-10-21T16:54:05.916644-06:00` locally), executable `C:/Program Files/Python314/python.exe`, command contains `run_longbench_v2_minimax_fresh_continuation.py --dispatch`. Reviewed runner contents match accepted `dd4fc3a`. The detached process survived shell exit; missing old PTY handles are not evidence it stopped.

Authoritative numeric observation at this checkpoint: matching PID live, CPU 908.21875 seconds; **1,359 continuation attempts**, 1,356 usage records, three continuation unknown outcomes, next request in flight. Including the 23-attempt prefix: **1,382/2,064 attempts**. Fresh known calculated cost **$18.5648046 (~$18.56)**: Full **$13.2166449**, Sift **$5.3481597**. Not final quality or final cost.

Pair a real process command-line/creation-time check with:

```powershell
py -3 tmp/longbench-v2-fresh/persistent-20261021T225405Z/observe_numeric.py
```

This root-only helper reads exactly the current continuation report and emits numeric/status fields only. `progress.log`, `errors.log` and `process.json` are in the same ignored directory. Logs/claims alone do not prove liveness. Observation timeout is not terminal; recheck the process. Never reset claims, retry unknown requests or tune on interim quality.

Frozen run:

- Fresh manifest: `docs/evals/longbench-v2-minimax-fresh-344-manifest-2026-10-20.json`; canonical SHA256 `881e896141de69ec4d2c9b8134f724faf0e7bb2736ea640e33e08181f35a8d5a`.
- Base manifest: `docs/evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json`; SHA256 `eaddd0d337111c6ab3c36d3f4a68dae4f002c94964de39beec620280f9c657c2`.
- Schedule SHA256 `52814e20912f272da4d0fd3b1b8668d25b120f4e3800f29cff500bb491239f1f`.
- Exact stopped prefix: `.runs/longbench-v2-minimax-fresh-344/fresh344-dispatch.json`; SHA256 `c3669172ba0a29062fc3d217ebbd49946e82f19ff4d9ba353a9151364244fdc7`. Its claim is consumed. 23 attempts, 22 usage records, one connection error without usage. Known input 1,164,672 / output 107; own cost $0.34953, recorded cost $0.17086824. Sanitized tracked prefix: `docs/results/longbench-v2-minimax-fresh-344-prefix-2026-10-21.json`.
- Fixed suffix: `.runs/longbench-v2-minimax-fresh-344/fresh344-continuation-1.json`, with sibling `fresh344-continuation-1.claim.json`. It schedules only the 2,041 previously unattempted jobs. Do not read these directly during dispatch.
- MiniMax M3 `minimax/minimax-m3`, provider `minimax/fp8`, no fallback, prompt cap 524288. Own rates $0.30/M input + $1.20/M output. Client budget uses max(own calculation, positive recorded amount); authorization **up to $100** for this study only.
- Unknown reserves are not spend: historical $2.0457216, prefix $0.06167235, current continuation $0.09215595. Initial conservative coverage $43.7351241 was within the cap. Unknown jobs are never replayed; transient failures advance, ten consecutive transient failures stop; auth/billing/route/usage/cap violations stop.
- Original session `22523` stopped after the prefix. Later `18111` failed before claim/inference on a cap metadata key; independently accepted one-key repair plus seven tests fixed it. Former `22574` observation disappeared; authoritative checks found no process/claim/output before the single detached launch. An orphaned prepare-only process was stopped. None of these handles should be mistaken for the current process.

### Terminal action

After actual terminal completion, root may run `benchmarks/analyze_longbench_v2_minimax_fresh_344.py` with the two tracked manifest paths and exact private prefix/suffix above, plus a **new** aggregate `--output` under `docs/results/`. It rejects partial/in-flight/replayed schedules. Never overwrite an existing aggregate or inspect raw reports manually. Independent reviewer checks the aggregate arithmetic/provenance and accepted analyzer/synthetic evidence, without private-report access.

The analyzer passed **38 synthetic tests**, including actual dispatch over 2,041 generated responses. It validates frozen coverage/order/request hashes/model/route/token/cost/reserves and emits scheduled-attempt and complete-six-request paired quality with task-cluster bootstrap. Continuation provenance is runner-recorded, without retained raw streams/provider signatures or execution-source hash. Final content hashes identify snapshots only. The immutable top-level initial suffix reserve differs from the final nested zero remainder; real-producer regression covers this and float-scale zero tolerance.

Publish truthful aggregate counts, failures, token/rate cost and paired quality, preserving the earlier negative result. No interim quality analysis or selection changes. Full quality/publication acceptance is still pending.

## Accepted evidence to reuse

- **Local tests/package:** [structured candidate result](docs/results/release-candidate-0.11.0-local-2026-10-21.json). Baseline `e19828a` passed 505 tests, Python 3.14, 152.35 seconds, 18 third-party warnings. Builder tool receipt retained as labelled excerpt; no complete raw stdout or independent full rerun. QA independently passed nine guards and verified 65 exact Git-blob build inputs, archive hashes/metadata and clean no-extras wheel/sdist installs. Stable-version snapshot exists only in ignored `tmp/release-candidate-011/`; checkout remains `0.11.0.dev0`. The later transport checks are separate, not part of that 505 count.
- **Clean first run:** [result](docs/results/no-inference-first-run-2026-10-21.json). Independent fresh Windows clone/venv execution reproduced old missing-global-Sift and direct-script example-import failures, then passed explicit local-venv/module commands: 4,613→1,982 estimated units, buried setting retained, no model. POSIX text review only. Engineering verification is not a volunteer result.
- **Optional SDK transport:** [result](docs/results/longmemeval-v2-minimax-transport-2026-10-21.json). 52 combined checks on SDK 2.54 and 3.36; QA independently checked final nullable handling/adversarial cases, actual pinned upstream reader→SDK3.36→loopback, real registry and 17 source pins, zero external attempts. Per-request caps/raw validation/no retries/redirects plus client-local failure latch and cleanup are accepted. Missing/null optional reported costs stay unknown; own Decimal calculation remains available. Reported OpenRouter and upstream amounts stay separate. This is not a run-wide budget, persistent claim, endpoint attestation or dispatch permission.
- **LongMemEval foundation:** [adapter record](docs/evals/longmemeval-v2-sift-adapter-2026-10-20.md). Pinned upstream `2cc8c540bdb87fe6761629b585e727e1c4704520`; generated adapter, real pinned Qwen processor/pressure, sequential main/file/scoring and reader transport checks accepted. Public data, weights, real provider, parallel mode and LLM judges were not exercised. SDK3.36 dependencies are isolated in ignored `tmp/longmemeval-synthetic-main/.venv`; global SDK2.54 remains unchanged. Do not install into the live-run environment. Direct script path can shadow Agents SDK via `benchmarks/agents.py`; accepted probes remove that path explicitly.
- **Previous public LongBench:** [aggregate](docs/results/longbench-v2-minimax-344-aggregate-2026-10-20.json). 2,063 receipts, 343 complete paired tasks; Full145 vs Sift127 task majorities, −5.25pp (95% CI −10.20 to −0.29), 59.66% fewer prompt tokens, recorded cost $12.63322398. Public/exposed development cohort, not blind/parity/agent-loop success. Six selected prior studies total $35.96192684 recorded cost, not lifetime/account total. Do not double-count reused baselines or combine different accounting bases as one bill.
- **Standalone/Pages:** core Chat Completions CLI works without LiteLLM. One synthetic local Ollama qwen3.5:9b run passed; 4b failed the rationale check. Two named client pathways have bounded compatibility checks. Pages and README retain measured token/negative-quality trade-offs; no broad provider or adoption claim. The original 950K Astra/Gemini full subscription requests were rejected before inference, so their full-context amounts are hypothetical API-rate equivalents, not measured savings.

## Next dependencies and authority

1. Finish the actual fresh run and aggregate acceptance as above. No additional paid study is covered by its cap.
2. Freeze the next public LongMemEval protocol with trial-wide controls and rights disposition before data access or a separately authorized call. It is a **public local reproduction**, not a blind test or official MiniMax leaderboard entry (official reader/judge contract differs). AppWorld/GAIA paired holdout routes remain uncleared. Do not manufacture held-out evidence or waive quality criteria.
3. Continue only existing public opt-in recruitment. At most three total inference-free sessions; no direct messages. No replies means adoption remains unverified. [Protocol](docs/evals/first-run-usability-protocol-2026-10-18.md).
4. [Release instructions](docs/releasing.md) and [draft notes](docs/release-notes-0.11.0.md): stable tag/version/main ancestry, full checks and authenticated PyPI publisher remain required. Solo-maintainer self-review/admin/tag-owner bypasses have an accepted, independently reviewed disposition; no settings changed or independent human approval is claimed. PyPI pending publisher remains unverified; last read-only check redirected to login. Do not repeat login checks without a state change or publish before the remaining gates pass.

Advisor councils already informed decisions and remain attributable in goal/eval records. Latest bounded council call failed HTTP401, produced no advice/usage receipt and was not retried; no fallback/retry is authorized by this handoff. Use primary evidence and independent review within existing authority.

## Ownership and checkpoint learning

Root integrates shared docs and accepts independently reviewed work. Reuse `reader_route_policy` for its assigned protocol file, `synthetic_flow_qa` for independent acceptance, and `fresh_run_analyzer` for aggregate/analyzer repairs if needed. No agent may read private reports. No new delegation layer is needed.

Applied lessons: run actual first-run commands in a clean environment; preserve explicit interpreter/module invocation; handle documented nullable SDK fields without adding account gates; validate producer transitions when accepting an analyzer; retain detached process identity and numeric observation across shell loss; distinguish selected recorded costs, own calculations and reserves. Current simplification consolidates contradictory historical checkpoints into this current handoff and links durable evidence, rather than repeating status-only CI or broad test runs.
