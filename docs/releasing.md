# Preparing and publishing a Sift release

Sift is not yet published to PyPI. The `0.11.0.dev0` source remains a preview until its quality, compatibility, and adoption gates in the [roadmap](../ROADMAP.md) are resolved.

## One-time PyPI setup

The `sift-context` project does not exist on PyPI yet. Configure a pending Trusted Publisher for its first upload with:

- Owner: `stancsz`
- Repository: `sift`
- Workflow: `publish.yml`
- GitHub environment: `pypi`

PyPI supports pending publishers for projects created by a first Trusted Publishing upload. The first successful publish creates the project and converts the pending publisher. See [PyPI's setup guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) and [GitHub Actions publisher requirements](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

`main` now requires a pull request and the `Core smoke (Python 3.12)` status check. The check is loose: it does not require the PR branch to be up to date with `main`, reducing rebuilds but allowing an older-base PR to merge and reveal incompatibilities afterward. The rule applies to admins; history must remain linear; force pushes and deletion are disabled. Zero approvals are required because the repository currently has one collaborator, so this is not an independent review gate. The repository still allows squash and rebase merges. The `pypi` environment is restricted to `main`, but its sole reviewer can self-approve and admins can bypass; the `v*` tag ruleset also retains an always-available owner bypass. Resolve those bypasses before claiming independent release controls. The workflow can only run from `main`; environment approval occurs after verification and before the OIDC publish job starts. See [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) and [GitHub environment management](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

**Configuration audit (2026-10-20):** The `pypi` environment exists and restricts deployments to `main`. It has `stancsz` as its sole required reviewer, but self-review is permitted and administrators can bypass. An active `v*` ruleset restricts tag creation, update, and deletion, with an always-available owner bypass. `main` requires a PR and the Core smoke with zero approvals; see the [release-control audit](evals/release-control-audit-2026-10-20.md) for the exact policy and remaining limitations. PR #32 adds a workflow check that the release tag points to a commit reachable from `main`; this does not remove the owner bypass or prove the tag is current. PyPI's public `sift-context` endpoint returns 404; this does not expose pending-publisher setup, which still needs an authenticated owner-side check. Do not call the current PyPI environment an independent approval gate until the self-review and bypass settings are resolved.

## Release procedure

1. Resolve the release gates in [the roadmap](../ROADMAP.md), and reconcile the version, README install instructions, release notes, and changelog (if present).
2. Set `project.version` in `pyproject.toml` to the intended stable version. Do not publish a `.dev`, alpha, beta, or release-candidate version through this workflow.
3. From the repository's default branch, manually run **Publish to PyPI** and provide an existing stable `vX.Y.Z` tag whose version matches `pyproject.toml`. Keep `dry_run` enabled (the default) for a non-publishing rehearsal. The workflow checks out that tag with full git history, verifies that its commit is reachable from `main`, then runs the full test suite and offline comparison, builds wheel and source distributions, validates package metadata, smoke-tests both without optional dependencies, and saves SHA-256 checksums as workflow artifacts. The selected tag must already exist and match a stable version; the current `0.11.0.dev0` version cannot be rehearsed as-is. The ancestry guard rejects off-main tags, but does not prove a tag is current, signed, or the intended release commit.
4. With `dry_run` enabled, the publish job is skipped, so it does not request OIDC or environment approval. Inspect the workflow result and artifacts. Only after every release gate and publisher setting is verified, rerun the same workflow and tag with `dry_run` disabled to enable the PyPI job. Verify the PyPI project page and install the uploaded version in a clean environment. Then create and publish the matching GitHub Release with reviewed release notes.

The workflow accepts only an explicit `vX.Y.Z` tag matching the package version. Its publish job gets only the OIDC permission needed for PyPI; no long-lived PyPI token is stored in GitHub.
