# Meridian Grid Change Management Policy — Version 2 (SUPERSEDED — do not use)

- Policy ID: MGCMP-2
- Effective: 2025-03-01
- SUPERSEDED by MGCMP-3 on 2026-07-01. Retained for archive trail only.
- Any audit performed under MGCMP-3 must NOT apply the rules below.

## 1. Maintenance windows (v2, STALE)

- v2 used *scheduling-only* windows and considered a change in-window if
  any event fell inside the window (partial containment was acceptable).
- v2 treated windows as UTC **half-open** on both ends: an event exactly
  at `end_utc` was considered OUTSIDE the window.

## 2. Approval matrix (v2, STALE)

- v2 required only a network engineering lead for every severity, and
  self-approval by the requester was permitted for `minor` changes.

## 3. Supersession (v2, STALE)

- v2 had no supersession rule; tickets were audited individually and a
  `superseded_by` field was ignored.

## 4. Telemetry judgment (v2, STALE)

- v2 compared post-change loss against a fixed 0.10% absolute threshold
  rather than the recorded baseline, and used a 0.05 percentage point
  elevation tolerance.

## 5. Report schema (v2, STALE)

- v2 reports used `"schema_version": 2`, an `audit_date` key, and did not
  include `superseded_changes` or `report_notes`.

NOTE: Keeping this file in the workspace is intentional. It exists so that
an auditor (human or agent) must detect supersession and ignore it. Do not
apply any rule from this document to the MDC-3 audit.
