# Sift release-control audit — 2026-10-20

Read-only audit of current repository and public package state after PR #20 merged. No settings were changed and no release or PyPI upload was attempted.

## Findings

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
