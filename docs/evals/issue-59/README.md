# Issue #59 acceptance record

Ask: preserve machine-readable compaction failures, address the source-backed
follow-up findings, release a new preview, and exercise native coding clients
through Sift with real long-session work.

Current follow-up candidate: **0.11.1**, with a bounded historical-anchor
repair found by the 0.11.0 native campaign. The full local suite passed
**592 tests, one skipped** ([output](full-suite-recall-fix-r2.txt)). Both archives pass
strict metadata checks, clean no-extras installation and offline CLI/gold
checks for the earlier candidate ([package receipt](package-acceptance-0.11.1.json)); the revised package is being verified. The 27-session
matrix will run on the revised packaged wheel; publication of this patch is pending.

[Generic before/after verifier](verify_recall.py) reproduces the failures
on the archived released 0.11.0 core and none on the five repaired cases.
[Eighteen source-aligned capture replays](recall-native-replay.json) also change
from missing to retained source evidence, preserving active tails, catalogs
and target bounds. Raw native inputs stay in task-local cache; minimized
generic regressions are committed. The independent core review accepts only
this localized repair, not the full campaign or universal readiness. A first
0.11.1 wheel exposed diagnostic/source competition; its unchanged results
are preserved in [attempt 7](campaign-attempt-7/matrix.json). The revised anchor
can preserve both signals within the same budget, keeping diagnostic priority
if both cannot fit.

Historical acceptance for the upstream 0.11.0 preview:

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

Published: [PR #60](https://github.com/stancsz/sift/pull/60) merged to `main`
as `3abbb9af45ebea5194c65a919ccc41a188b60373`. The required smoke and
[full Python 3.11–3.14 CI](https://github.com/stancsz/sift/actions/runs/40415374396)
passed. The [v0.11.0 preview](https://github.com/stancsz/sift/releases/tag/v0.11.0)
contains the wheel/source archives identified in the package receipt. The tag
push used the owner's existing configured tag-rule bypass; no rule changed
and this is not independent tag approval.

Remaining: the requested
**27-session matrix** (three clients × three tasks × three repetitions), each
with more than three minutes of active native CLI work. The two pilots do not
replace that campaign. Its final receipt will be added after execution; until
then the full campaign is unverified. Use [the documented harness](../../cli-acceptance.md).

The [first wheel campaign](campaign-attempt-1/matrix.json) preserves six
qualifying sessions, a failed Claude expense workflow and an interrupted Codex
expense session. Claude's task, hidden tests, report, historical fact and API
checks passed, but it edited before the baseline; the strict workflow check
correctly rejected that turn. The follow-up harness clarifies the required
order and tests expenses first, without changing library code or weakening
acceptance. A complete campaign on that frozen harness is still required.

Subsequent attempts preserve provider disconnects separately:
[attempt 2](campaign-attempt-2/matrix.json),
[attempt 3](campaign-attempt-3/matrix.json), and
[attempt 4](campaign-attempt-4/matrix.json). Attempt 4 includes qualifying Claude
and Codex expense sessions. OpenCode completed all six turns, hidden tests and
daily reports, but its then-current all-HTTP-200 gate rejected two upstream
responses recovered by the native client. These historical verdicts are unchanged.

The [reviewed reporting policy](transport-policy-review.json) now separates
functional acceptance from transport cleanliness: only a specifically
classified provider disconnect recovered within a successful native session
can qualify with `transport_clean=false`. Fatal or unknown errors and every
Sift/functional failure still reject. Classification preserves upstream bytes
and status, adds no proxy retry, and has focused stream/negative regressions.
Provider transport reliability remains unresolved. See the harness documentation
for the exact marker/prefix limits and the [scheduler review](recovery-qa.json).

No downstream `ainode-litellm-prod` service was changed. The user selected merge
to Sift `main` as the production target. PyPI publication and the roadmap's broad
quality/adoption gates are separate from this GitHub preview and remain unproven.
