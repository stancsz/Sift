# GitHub discovery and adoption baseline — 2026-10-20

## Snapshot

Read-only snapshot of the public repository metadata and GitHub's traffic endpoints, retrieved with the authenticated `gh` client on 2026-10-20. Traffic endpoints expose the most recent 14-day window; this response covers 2026-10-06 through 2026-10-19 UTC.

| Signal | Observed | Interpretation limit |
|---|---:|---|
| Stars | 1 | Total count, not users or adoption. |
| Forks | 0 | Does not measure local use. |
| Watchers/subscribers | 2 | Notification interest, not usage. |
| Repository views | 8 views / 3 unique visitors | Small and noisy exposure sample. |
| Clones | 2,634 clones / 486 unique cloners | A clone does not establish a successful install or first use; this volume may include automation and repeated project-work checkouts. |
| Popular referrers | None returned | No attributed discovery source in this response. |
| Popular paths | Overview: 3 / 2 unique; Actions workflow: 2 / 1; Actions: 1 / 1; PR #9: 1 / 1; v0.9.0 release: 1 / 1 | Small counts; page paths do not reveal why visitors arrived. |
| Open issues | 2, including opt-in usability issue #13 with one maintainer reminder and no volunteer replies | No participant feedback or session completion evidence. |

Repository description, homepage link, and the seven existing topics were present and aligned with context compaction, LiteLLM, inference, prompt caching, Python, and the project site.

## What this supports

This is a weak discovery baseline, not an adoption result. It shows very few repository page views and no referrers, alongside many clones that cannot be joined to successful installs or users. The 14-day response cannot tell whether the README or site caused interest, where the clones came from, or whether any visitor activated Sift. Do not report 486 unique cloners as users.

The README first screen now names coding-agent builders, their long-tool-history problem, Sift's exact-evidence/no-summary-call behavior, and the observed LongBench quality trade-off. It has one primary action: run the offline trace demo. The first-run task adds an optional comprehension check about what stays exact, what older content may be selected, when Sift refuses, and what the fixture does not prove. A later GitHub traffic window should be compared only after a dated, authorized distribution event; qualitative opt-in sessions remain the direct way to test comprehension and setup friction. Do not send outreach or publish a campaign without authorization.

Follow-up read-only inspection found one maintainer reminder on issue #13 and no volunteer replies or completed sessions. Up to three inference-free sessions are authorized, but no direct outreach has occurred. The adoption status therefore remains unvalidated.

## Reproduction

```powershell
gh api repos/stancsz/sift
gh api repos/stancsz/sift/traffic/views
gh api repos/stancsz/sift/traffic/clones
gh api repos/stancsz/sift/traffic/popular/referrers
gh api repos/stancsz/sift/traffic/popular/paths
```

GitHub's traffic API is a short rolling window. Save future snapshots regularly if a trend is needed; do not compare mismatched windows or infer causality from this single before/after-free observation.
