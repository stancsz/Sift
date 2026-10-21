# Sift release-control audit — 2026-10-20

Read-only audit of current repository and public package state after PR #20 merged. No settings were changed and no release or PyPI upload was attempted.

## Current control disposition — 2026-10-21

Authenticated GitHub rechecks after PR #48 confirmed that `main` requires a PR
and Core smoke with admin enforcement, linear history and no force push/deletion;
the `pypi` environment permits its sole reviewer to self-approve and admins to
bypass; and tag ruleset `25458147` retains the owner's `always` bypass. No settings
were changed.

The coordinator accepts those recovery paths for the solo-maintainer 0.11
process under the user's standing release mandate. Independent read-only review
confirmed that this resolves goal action 3's explicit choice to accept or change
the controls. It does not establish independent human approval. The exact stable
tag/version/main-ancestry checks, full release verification and authenticated
pending Trusted Publisher check remain required. Quality, compatibility and
adoption disposition remain open. Older unresolved-control wording below is
historical and superseded by this decision; the factual bypass caveats remain.

An October 21 read-only recheck in the available Chrome profile opened
`https://pypi.org/manage/account/publishing/` and visibly redirected to PyPI's
login form. Pending Trusted Publisher configuration remains unverified. No
credentials were entered and no account settings or package uploads changed.

## Initial findings

| Control | Result | Evidence |
|---|---|---|
| Publish workflow entry | **Verified** | [`publish.yml`](../../.github/workflows/publish.yml) is `workflow_dispatch` only and both build and publish jobs run only when `github.ref == refs/heads/main`. The selected tag must be stable `vX.Y.Z` and match the package version. |
| PyPI deployment branch | **Verified, with bypass caveat** | GitHub's `pypi` environment has a custom deployment branch policy listing `main`: [environment](https://api.github.com/repos/stancsz/sift/environments/pypi), [allowed branches](https://api.github.com/repos/stancsz/sift/environments/pypi/deployment-branch-policies). Environment metadata reports `can_admins_bypass: true`. |
| Required deployment reviewer | **Configured, not independent** | The `pypi` environment lists `stancsz` as its sole required reviewer and `prevent_self_review: false`; the configured reviewer can approve their own deployment. The environment review is therefore not an independent approval gate. |
| Stable tag ruleset | **Active, owner-bypassable** | [Repository ruleset 25458147](https://api.github.com/repos/stancsz/sift/rulesets/25458147) matches `refs/tags/v*` and restricts creation, update, and deletion. `stancsz` is a bypass actor with mode `always`, so the rule does not prevent the owner from bypassing it. |
| `main` branch protection | **Not configured** | `GET /repos/stancsz/sift/branches/main/protection` returned HTTP 404 (“Branch not protected”). The PyPI environment separately limits deployments to `main`, but PR review/required-check protection for `main` is not established by that environment rule. |
| PyPI project and pending publisher | **Unverified** | `https://pypi.org/pypi/sift-context/json` returned HTTP 404. This shows no public project record at audit time, but the public endpoint does not expose whether the owner has configured a pending Trusted Publisher. Verify in the authenticated PyPI account before any release. |

## Release disposition

Do not describe the release controls as fully verified or independently gated. Before a stable publish, the owner should verify pending-publisher configuration in PyPI, decide whether an independent reviewer can be configured (and enable self-review prevention if so), and decide whether to add branch protection or required PR checks on `main`. Preserve the documented owner bypass behavior for tag/environment rules only if that is an intentional recovery path. Re-run this audit after any settings change and before the first publish.

This initial audit is configuration evidence only. It does not establish package correctness, quality parity, user adoption, or approval to publish.

## Read-only recheck after PR #22 — 2026-10-20

After PR #22 merged as `6fcec84`, a fresh read-only GitHub/PyPI check found the same control state: the `pypi` environment still lists only `main`, allows admin bypass, and permits its sole `stancsz` reviewer to self-approve; ruleset `25458147` still grants the owner an always-available bypass for `v*`; `GET /branches/main/protection` still returns 404; and `https://pypi.org/pypi/sift-context/json` still returns 404. This confirms that the recorded control gaps persist, but cannot verify the private pending-publisher setup. No settings were changed and no package was uploaded.

## Recheck after main branch hardening — 2026-10-20

After PR #27 merged, the authenticated owner added branch protection to `main`. The current GitHub API confirms:

- Pull requests are required, with zero approving reviews. The repository currently has one collaborator (`stancsz`), so this forces a PR workflow without inventing an independent human approval.
- `Core smoke (Python 3.12)` is required, with the up-to-date/strict requirement disabled to avoid rerunning the short smoke solely because the base branch moved. This can allow a PR tested against an older `main` to merge, with incompatibilities surfacing afterward. Admins are subject to the rule.
- Linear history is required; force pushes and branch deletion are disabled. Repository merge settings now disable merge commits and retain squash and rebase.

This closes the unprotected-`main` finding and creates a tested-PR process gate. It does not establish independent review. The `pypi` environment is unchanged: its only required reviewer can self-approve and admins can bypass. Ruleset `25458147` still grants the owner an always-available bypass for `v*` tags. The authenticated PyPI pending-publisher configuration is still unverified; public project JSON remains 404. No package was uploaded. Stable release remains blocked on held-out quality, adoption disposition, compatibility and release verification.

The new gate has since been exercised: PR #28 passed the required Core smoke in 43 seconds, then its merge to `main` passed the push-triggered smoke in 51 seconds ([PR workflow](https://github.com/stancsz/sift/actions/runs/39435760716), [main workflow](https://github.com/stancsz/sift/actions/runs/39435910330)); both full-matrix jobs were skipped as configured. PR #28 changed documentation only.

After PR #29 merged, current `main` is `033f9eb90e01387d9afda7c711c5ab9921a08296`. That documentation-only update's required Core smoke passed in 44 seconds and the post-merge `main` smoke passed in 51 seconds (PR workflow [39436258582](https://github.com/stancsz/sift/actions/runs/39436258582), main workflow [39436409508](https://github.com/stancsz/sift/actions/runs/39436409508)); both full-matrix jobs were skipped. These checks exercise current workflow/docs state, not a new Python-code revision. PyPI publisher setup and the existing bypass controls remain unchanged and unresolved.

## Recheck after PR #30 — 2026-10-20

PR #30 merged as `75ec711bd98322094bb902dd1ec21de0fa2fbb56`. Its required Core smoke passed in 48 seconds, the full matrix was skipped by design, and the push-triggered `main` smoke also passed in 48 seconds ([PR run 39440772186](https://github.com/stancsz/sift/actions/runs/39440772186), [main run 39440993052](https://github.com/stancsz/sift/actions/runs/39440993052)). It changed documentation only. A local Python 3.14.0 preview-build rehearsal on the same source produced the `0.11.0.dev0` wheel and sdist; both passed `twine check --strict`, and a fresh no-extras virtual environment installed the wheel, ran `sift serve --help`, and confirmed LiteLLM was absent. This does not verify the stable-tag workflow, authenticated PyPI publisher configuration, or a publish. No settings were changed and no package was uploaded.

## Recheck after PR #31 and release-path review — 2026-10-20

PR #31 merged as `ee9a126b56ed2126d420f9360003776ab3a5bb63`. Its required Core smoke passed in 48 seconds and the post-merge `main` smoke passed in 43 seconds (PR workflow [39442378404](https://github.com/stancsz/sift/actions/runs/39442378404), main workflow [39442538967](https://github.com/stancsz/sift/actions/runs/39442538967)); it changed documentation only. A fresh local run against that source passed 397 tests on Python 3.14.0 in 211.28 seconds, with 18 dependency warnings; source, tests, and packaging metadata exactly match tested source `29457b9`. The offline comparison returned 100/100 Sift hits and 0/100 head-tail hits in 0.461 CPU seconds.

The live GitHub API still reports `main` requires a PR and Core smoke, has zero required approvals, and enforces admins. The `pypi` environment still permits administrator bypass and self-review by its sole reviewer `stancsz`; the `v*` tag ruleset grants that account an always-available bypass. PyPI's public `sift-context` JSON endpoint returns 404, so pending Trusted Publisher setup remains unverified. No account settings were changed and no package was uploaded.

The repository-only workflow review found that `publish.yml` checked tag syntax and version equality but did not require the selected tag commit to be reachable from protected `main`. PR [#32](https://github.com/stancsz/sift/pull/32) adds `fetch-depth: 0` and a pre-build `git merge-base --is-ancestor` guard. Local predicate checks accept current `main` and reject the off-main pre-squash PR #31 head. An independent workflow review found the checkout/fetch behavior and ancestry guard sound. This closes only the off-main-tag path; it does not establish that the tag is current, signed, uniquely publishable, or independently approved, and it does not verify PyPI configuration. PR Core smoke run [39444623888](https://github.com/stancsz/sift/actions/runs/39444623888) passed in 44 seconds; PR #32 merged as `05dc830`. Post-merge main smoke [39444778027](https://github.com/stancsz/sift/actions/runs/39444778027) passed in 49 seconds. The full suite was skipped by design.

## Safe non-publishing rehearsal input

The release workflow now has a required boolean `dry_run` input defaulting to `true`. With the default, it performs tag ancestry/version checks, full tests, the offline comparison, distribution build/metadata checks, no-extras wheel/sdist smoke, and artifact upload, then skips the PyPI job. The workflow's PyPI publish job runs only when `dry_run` is explicitly false. This path requires an existing stable `vX.Y.Z` tag matching `pyproject.toml`; the current `0.11.0.dev0` version cannot be used for a rehearsal. Static `actionlint` validation and independent condition review passed, but no live workflow rehearsal has run yet. The dry-run path does not replace checking the pending publisher or remaining GitHub bypass controls.

## Current read-only recheck after PR #39 — 2026-10-20

PR #39 merged as `8333a1fab8edb182b037a995035edbaa121289c5` and changed project-state documentation only. Its required Core smoke passed in 49 seconds ([PR run 39456032597](https://github.com/stancsz/sift/actions/runs/39456032597)); the full matrix was skipped by design. The post-merge `main` smoke passed in run [39456187032](https://github.com/stancsz/sift/actions/runs/39456187032). This verifies the short smoke, not a fresh full-suite run.

The repository workflow remains `workflow_dispatch` only. Both jobs require the workflow ref to be `main`; the chosen tag must have strict stable `vX.Y.Z` syntax, match `pyproject.toml`, and point to a commit reachable from `main`. The build runs the full test suite and offline comparison, builds and validates wheel/sdist, smoke-installs both without optional dependencies, and uploads distributions. Publishing is skipped by default; when explicitly enabled, it uses the `pypi` environment and OIDC via `pypa/gh-action-pypi-publish@release/v1`. No publish workflow run exists. The package version is still `0.11.0.dev0`, so no valid stable-tag rehearsal can currently run.

GitHub's live API confirms that `main` requires a PR and `Core smoke (Python 3.12)`, enforces the rules for admins, requires linear history, and disables force pushes/deletion. It requires zero approving reviews and does not require the branch to be up to date (`strict: false`). The `pypi` environment allows only `main`, lists `stancsz` as its sole reviewer with self-review prevention disabled, and allows admin bypass. Ruleset `25458147` restricts `v*` tag creation/update/deletion but gives `stancsz` an always-available bypass. These are process controls, not independent approval.

The public PyPI JSON endpoint for `sift-context` still returns 404, and the latest GitHub release remains the `v0.10.0` pre-release. The authenticated PyPI publishing-settings page redirects to login in the available browser session, so pending Trusted Publisher configuration remains unverified. No account settings were changed, no human was contacted, and no release or package upload was attempted. Stable release remains not ready while held-out agent-task quality, usability disposition, broader compatibility, and the above publisher-control questions remain open.

PR #40 then merged this documentation-only recheck as `1b31df844abe291174ccdab4347ee33f1f804115`. Its required Core smoke passed in [39457294410](https://github.com/stancsz/sift/actions/runs/39457294410), and the post-merge `main` smoke passed in [39457481161](https://github.com/stancsz/sift/actions/runs/39457481161); both full matrices were skipped by design. No GitHub or PyPI settings changed after the read-only API check above, and no package was uploaded.

## Historical proposal before PR #44 merged (2026-10-20)

At the time of this proposal, the hosted rehearsal was still unrun and PR #44 was open. The proposal's test, offline-comparison, build, and package-smoke evidence is retained as a historical snapshot. Council usage: Gemini 2,905 prompt + 231 completion tokens; Sol 648 prompt + 274 completion tokens. `decision_changed: true`: the rehearsal was designed to support the current dev version without creating a public tag.

## Current recheck after PR #44 merge and hosted rehearsal (2026-10-20)

PR #44 merged as `362c70a96ecaeeaa4ad29c26bc445294ebae051f`. Its required Core smoke passed ([39474846606](https://github.com/stancsz/sift/actions/runs/39474846606)); post-merge Core smoke passed ([39475035244](https://github.com/stancsz/sift/actions/runs/39475035244)) and Pages deployed ([39475035303](https://github.com/stancsz/sift/actions/runs/39475035303)). The tagless, non-publishing hosted rehearsal [39475341440](https://github.com/stancsz/sift/actions/runs/39475341440) then completed successfully on `main`: 417 tests passed (18 warnings, 101.47 seconds), the offline comparison passed, wheel and sdist built and passed strict Twine checks, both distributions installed without optional dependencies, and both `sift serve --help` smokes passed with LiteLLM absent. The publish job was skipped (`dry_run=true`); artifacts were uploaded. The package version remains `0.11.0.dev0`; no stable release or package upload occurred.

The read-only GitHub settings recheck confirmed `main` requires a PR and Core smoke, zero approvals, admin enforcement, linear history, and no force push/deletion. The `pypi` environment allows deployments from `main`, but its sole required reviewer `stancsz` may self-approve and admins may bypass. The `v*` ruleset grants the repository owner an always-available bypass. The public PyPI project endpoint returned 404. The authenticated publishing-settings page redirected to login, so pending Trusted Publisher configuration remains unverified. These controls do not provide independent release approval; stable publication remains not ready pending account verification, control decisions, held-out quality, compatibility coverage, and an honest adoption disposition.
