# Least-Privilege IAM Audit — Agent Task

> **Public-data notice.** This is authored, fictional development data. It is not a held-out benchmark or production security evidence.

## Task

You are reviewing an access request for Alice Chen (`alice.chen@stratus.example`) at Stratus Cloud. Inspect the request, policy notes, and access-event logs. Complete `audit_iam.py` so running it writes a deterministic JSON report to `access_audit_report.json`.

The evidence is split across several files because the source records arrive in separate historical exports. Use normal investigation methods: search, targeted reads, or broader inspection as useful. Do not assume file order means policy precedence. The older policy can remain in force when a later section narrows a different rule.

## Read-only inputs

- `data/role_request.txt` — requested actions and resources, requester, subject, role, justification, and effective date.
- `data/policy_notes.md` — policy rules with effective dates and explicit supersession notes.
- `data/audit_events_2024_legacy.log` — historical events outside the review interval.
- `data/audit_events_2025_archive.log` — archived events outside the review interval.
- `data/audit_events_2026_q3.log` — current-year events, including dates before and inside the review interval.
- `data/audit_events_2026_q4.log` — recent events through and after the review cutoff.

All event rows use:

`timestamp_utc | actor | action | resource | result`

## Report contract

The JSON object must contain these keys:

- `subject`, `role`, and `request_effective`
- `review_window` with inclusive UTC `start` and `end` dates
- `requested_permissions`: the parsed request entries (`action`, `resource`)
- `approved_permissions`: requested entries with at least one in-window normal `ALLOW` and no active policy conflict
- `overgrants`: requested entries with zero in-window normal `ALLOW` events; this can overlap with policy violations
- `undergrants`: unrequested action/resource/count objects with at least five in-window normal `ALLOW` events for the subject; each object includes `action`, `resource`, and `allow_count`
- `constraint_violations`: requested entries conflicting with a policy constraint in force at the request's effective date
- `citations`: references for each finding, each containing a case-relative `file` and one-based `line`

The fixed review interval is **2026-07-18 through 2026-10-16 inclusive**, in UTC. Use this interval as written. Ignore events outside it. A `DENY` or break-glass event is not evidence of normal use. Match the actor exactly to the requested subject.

A policy section is in force only when its effective date is before the request date and no later section explicitly supersedes it. A later rule that narrows another section does not silently erase unrelated restrictions. A policy conflict blocks approval even when access history contains an `ALLOW`.

Keep report ordering deterministic. Do not include the current time, random values, or machine-specific paths. Preserve integer/string types and do not mutate source files.

## Constraints and verification

- Edit only `audit_iam.py`; the generated `access_audit_report.json` is the only other file the script may write.
- Use Python's standard library only.
- Run `python -m unittest -q` before and after editing. The starter must fail the visible tests; your implementation must pass both visible tests and the independent gold suite.
- The visible tests check schema and representative findings. The gold suite checks exact classifications, time filtering, policy precedence, and citation integrity.
- Do not change logs, notes, request, tests, or acceptance checks.

The role request asks for analytics S3/KMS access, a PII bucket, and two production database permissions. Read the evidence before deciding which items may be approved, should be removed as unused, or violate an active rule.
