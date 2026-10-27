# Sift 0.11.1 — preview

This patch repairs a historical-source retention failure found during the
native CLI campaign after 0.11.0. Repeated task instructions could crowd out a
short retention statement while the stable historical anchor kept only an
archive header. The anchor now reuses Sift's existing independent coverage
signal selection alongside an earlier diagnostic. Both fit within the existing
anchor budget; diagnostics retain priority when only one fits. Untrusted quotation, protected active
work and hard token limits remain enforced.

Five generic regressions cover competing task echoes, source positions,
topic changes, budgets, identifier queries and diagnostic/source coexistence.
The archived 0.11.0 core fails their source-retention assertions; the repaired
core passes all five tests. The full local suite passed **592 tests, one skipped**. See the
[issue #59 acceptance record](evals/issue-59/README.md) for the native campaign's
actual completed coverage and independent reviews.

The harness also gains explicit checkpoint resume, preserved failed attempts,
and separate functional/transport reporting. A specifically classified provider
disconnect can qualify only after a later identical request succeeds and the
native session passes every task check. Fatal or unknown errors still fail.
This adds no proxy retry or provider change.

This is a GitHub preview. PyPI publication, downstream gateway rollout,
universal bug freedom and the broader roadmap's quality/adoption gates are
separate from this patch's acceptance.
