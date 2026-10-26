# Issue #59 acceptance record

Ask: preserve machine-readable compaction failures, address the source-backed
follow-up findings, release a new preview, and exercise native coding clients
through Sift with real long-session work.

Acceptance for the upstream preview:

- Both real active-work failure paths expose `active_too_large`; raw/input-size
  guards remain distinguishable and rejected. The code/status map covers current
  core and dynamic literals. Overflow passthrough is opt-in and narrowly scoped.
- Native OpenCode plain reasoning, Codex declarative catalogs, and retained
  sealed reasoning have preservation/counting regressions. Counting copies are
  isolated from forwarded provider objects. Protected oversized work still fails.
- The local Python 3.14 suite passed **581 tests, one skipped**, with 18 dependency
  warnings: [full output](full-suite.txt). Package checks built and clean-installed
  both archives without optional dependencies, passed strict metadata checks,
  and verified source correspondence: [package receipt](package-acceptance.json).
- Two pre-release persisted pilots passed: Codex 10 user turns / 190.579 active
  seconds / 48 compactions; Claude seven turns / 195.541 seconds / 41 compactions.
  These started with `.dev0` metadata; their source bytes match the release.
  [Pilot summaries](pilots.json), [reconciliation](pilot-reconciliation.json),
  and compressed redacted native traces are in this directory.

Reproduce the artifact checks from the checkout root:

```powershell
.\.venv\Scripts\python.exe docs/evals/issue-59/verify_callback.py
.\.venv\Scripts\python.exe docs/evals/issue-59/verify_pilots.py
```

The pilot verifier recomputes native evidence and session identity from the raw
synthetic traces, verifies source hashes and elapsed-time sums, and checks every
recorded compaction's gold, budget, and upstream status. The initial turn must
prove the full failing-baseline/edit/passing-test workflow. Later turns require
actual native final tests and hidden checks, not gratuitous edits to already
correct code. An independent CLI audit executed this verifier successfully;
see [the review disposition](qa-review.json).

Remaining: PR/main and GitHub preview publication, followed by the requested
**27-session matrix** (three clients × three tasks × three repetitions), each
with more than three minutes of active native CLI work. The two pilots do not
replace that campaign. Its final receipt will be added after execution; until
then the full campaign is unverified. Use [the documented harness](../../cli-acceptance.md).

No downstream `ainode-litellm-prod` service was changed. The user selected merge
to Sift `main` as the production target. PyPI publication and the roadmap's broad
quality/adoption gates are separate from this GitHub preview and remain unproven.
