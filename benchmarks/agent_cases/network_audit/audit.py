"""MDC-3 change audit report generator (implement me).

Contract (authoritative details: `case/docs/policy/change_management.md`
section 6; visible baseline tests: `case/test_task.py`):

1. Read EVERY source file listed in `case/README.md` (policy, tickets,
   maintenance windows, controller events, switch syslog, telemetry,
   baseline). Do not infer from keywords alone.
2. Combine them into a single JSON report written to `report.json` in the
   current working directory.
3. Report schema (exact keys, in this order):

       {
         "schema_version": 3,
         "datacenter": "MDC-3",
         "window_closed_utc": "2026-09-30T22:00:00Z",
         "changes": [ ... one per EFFECTIVE (non-superseded) MDC-3 ticket,
                      sorted by change_id ascending ... ],
         "superseded_changes": [ {"change_id": ..., "superseded_by": ...} ],
         "unattributed_events": <int>,
         "report_notes": [ ... sorted short strings ... ]
       }

   Each change entry:

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

4. Judgment rules are those of the CURRENT policy (MGCMP-3). Older policy
   versions in the workspace are superseded. Authoritative records beat
   informal channel claims. All timestamps normalize to UTC; switch syslog
   is local wall-clock with an explicit offset.
5. Deterministic output only: no wall-clock "now" values, sorted lists,
   floats rounded to 4 decimals, UTF-8, 2-space indent, trailing newline.

The starter stub below is intentionally non-functional and fails the
baseline tests in `case/test_task.py`.
"""


def main() -> None:
    # TODO: implement the audit per the contract above.
    raise NotImplementedError("audit not implemented")


if __name__ == "__main__":
    main()
