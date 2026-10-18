# Meridian Grid Change Management Policy — Version 3 (CURRENT)

- Policy ID: MGCMP-3
- Effective: 2026-07-01 (supersedes MGCMP-2 on 2026-07-01)
- Owner: Meridian Grid Network Operations (fictional)
- Scope: all Meridian Grid data centers, including MDC-3 (Kestrel Point, Veridia)

This is the AUTHORITATIVE policy. Any older policy document found in this
workspace (e.g. `v2_legacy.md`) is superseded and must not be used for
audit decisions, even when its text looks plausible.

## 1. Maintenance windows

- Every planned change must be fully contained within an approved
  maintenance window recorded in `data/maintenance_windows.json`.
- Containment means: every controller event attributed to the change
  (via the event's `change_id`) satisfies
  `window.start_utc <= event_ts <= window.end_utc`.
- Windows are UTC half-open intervals for *scheduling*, but audit
  containment uses inclusive bounds on both ends (an event exactly at
  `end_utc` is still inside the window).

## 2. Approval matrix

| Severity   | Required approval(s) on the ticket                          |
|------------|-------------------------------------------------------------|
| critical   | network engineering lead AND security officer (or CISO delegate) |
| major      | network engineering lead                                      |
| minor      | senior network engineer                                       |

- The requester may not approve their own change (self-approval is
  invalid and does not count).
- An approver must hold the named role **and** not be the requester.

## 3. Supersession

- A ticket with a non-null `superseded_by` is NOT audited as a change.
  The successor ticket is the effective change; the original is reported
  only as `superseded: true` and its window/approval fields are not
  evaluated (reported as `null`).
- If informal communications describe the superseded ticket as
  "the" change, the authoritative `tickets.json` wins.

## 4. Rollback

- A `change_id` whose controller stream contains a `rollback.executed`
  event is `rolled_back: true`.
- Rollback does not by itself fail the audit; it is reported.

## 5. Telemetry judgment

- Let `post` be the telemetry sample for the UTC hour immediately after
  the effective window's `end_utc`.
- `post_change_loss_pct` = `post.avg_loss_pct`
- `baseline_loss_pct` = baseline `avg_loss_pct` for the same link scope
- `loss_delta_pp` = `round(post - baseline, 4)`
- `baseline_delta` = `"elevated"` if `loss_delta_pp > 0.5`, else `"normal"`.

## 6. Report schema (exact)

`audit.py` must write a JSON object with EXACTLY these keys, in this key
order, lists sorted as noted:

```
{
  "schema_version": 3,
  "datacenter": "MDC-3",
  "window_closed_utc": "2026-09-30T22:00:00Z",
  "changes": [
    {
      "change_id": str,
      "severity": str,
      "status": "approved" | "rejected" | "rolled_back" | "superseded",
      "window_id": str | null,
      "in_window": bool | null,
      "approvals": {"requested_by": str, "approved_by": [str, ...]},
      "rolled_back": bool,
      "post_change_loss_pct": float,
      "baseline_loss_pct": float,
      "loss_delta_pp": float,
      "baseline_delta": "elevated" | "normal"
    }
  ],
  "superseded_changes": [ { "change_id": str, "superseded_by": str } ],
  "unattributed_events": int,
  "report_notes": [str, ...]
}
```

- `changes` contains one entry per effective (non-superseded) ticket for
  MDC-3, sorted by `change_id` ascending.
- `superseded_changes` lists each superseded ticket with its successor,
  sorted by `change_id`.
- `unattributed_events` = count of controller events whose `change_id`
  is not a known MDC-3 ticket (or is null/missing).
- `report_notes` = deterministic, sorted list of short strings; include
  exactly one note per notable judgment, each formatted
  `"<topic>: <detail>"` with topics from
  {`supersession`, `window`, `approval`, `rollback`, `telemetry`,
  `conflict`}. For this audit the required notes are:
  - `supersession: CHG-2026-1147 superseded by CHG-2026-1188`
  - `conflict: ops channel claim contradicts controller record for CHG-2026-1193`
  - `conflict: CHG-2026-1201 controller marker corroborated by switch record at UTC 2026-09-30T22:00:04Z`
  - `window: CHG-2026-1201 event at or after window end`
  - `approval: CHG-2026-1210 lacks an independent network engineering lead approval`
  - `rollback: CHG-2026-1210 rolled back`
  - `telemetry: CHG-2026-1188 baseline_delta elevated`

## 7. Determinism

- No wall-clock timestamps, hostnames, or environment values in output.
- All floats rounded to 4 decimal places. All lists sorted by their
  natural key. UTF-8 JSON, 2-space indent, trailing newline.
- All report timestamps are UTC with a `Z` suffix.
