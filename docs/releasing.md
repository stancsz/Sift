# Preparing and publishing a Sift release

Sift is not yet published to PyPI. The `0.11.0.dev0` source remains a preview until its quality, compatibility, and adoption gates in the [roadmap](../ROADMAP.md) are resolved.

## One-time PyPI setup

The `sift-context` project does not exist on PyPI yet. Configure a pending Trusted Publisher for its first upload with:

- Owner: `stancsz`
- Repository: `sift`
- Workflow: `publish.yml`
- GitHub environment: `pypi`

PyPI supports pending publishers for projects created by a first Trusted Publishing upload. The first successful publish creates the project and converts the pending publisher. See [PyPI's setup guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) and [GitHub Actions publisher requirements](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

In GitHub repository settings, protect the `pypi` environment with a required reviewer and restrict its allowed deployment branch to `main`. Protect `v*` tags so only the release owner can create or update them. The workflow can only run from `main`; the environment approval occurs after verification and before the OIDC publish job starts. See [GitHub deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments).

## Release procedure

1. Resolve the release gates in [the roadmap](../ROADMAP.md), and reconcile the version, README install instructions, release notes, and changelog (if present).
2. Set `project.version` in `pyproject.toml` to the intended stable version. Do not publish a `.dev`, alpha, beta, or release-candidate version through this workflow.
3. From the repository's default branch, manually run **Publish to PyPI** and provide the existing stable `vX.Y.Z` tag. The workflow checks out that exact tag, enforces the stable version format and match with `pyproject.toml`, runs the full test suite and offline comparison, builds wheel and source distributions, validates package metadata, smoke-tests both without optional dependencies, and saves SHA-256 checksums as a workflow artifact.
4. After those checks pass, the workflow publishes the two distributions to PyPI using Trusted Publishing. Verify the PyPI project page and install the uploaded version in a clean environment. Then create and publish the matching GitHub Release with reviewed release notes. A failed verification does not publish to PyPI or create a public GitHub Release.

The workflow accepts only an explicit `vX.Y.Z` tag matching the package version. Its publish job gets only the OIDC permission needed for PyPI; no long-lived PyPI token is stored in GitHub.
