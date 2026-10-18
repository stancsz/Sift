# MDC-3 Change Audit — Evidence Index (read every file below before implementing)

You are auditing the change cycle around ticket **CHG-2026-1147** at the
fictional Meridian Grid data center **MDC-3** (Kestrel Point, Veridia). The
change window closed **2026-09-30 22:00:00 UTC**. Your program `case/audit.py`
must combine every source below into one JSON report (contract in
`case/audit.py` docstring and `case/test_task.py`).

Read **every** file listed here before editing `case/audit.py`. Several
conclusions require combining files; single-file or keyword scanning will be
wrong. All organizations, people, systems, and events are fictional.

## Policy (current versioned policy; older versions superseded)
- `case/docs/policy/change_management.md` — CURRENT policy v3 (window rules,
  approval matrix, rollback rule, report schema, telemetry thresholds).
- `case/docs/policy/v2_legacy.md` — SUPERSEDED policy v2 (stale; do not use
  for decisions; kept for the archive trail).
- `case/docs/policy/rollback_playbook.md` — rollback procedure (reference;
  not authoritative for the report).

## Change tickets
- `case/data/tickets.json` — unfiltered change-board export. Select rows with
  `site == "MDC-3"`; CHG-2026-1255 is an MDC-2 decoy. Use each selected
  ticket’s exact `link_scope`. CHG-2026-1147 carries
  `superseded_by: "CHG-2026-1188"` (see also the informal note below).

## Informal records (NOT authoritative — use only as leads)
- `case/docs/comms/ops_channel.md` — transcript of the #net-ops channel.
  Contains informal claims that contradict the authoritative records in
  several places, including the 1193 CRC/loss finding. When it disagrees
  with `tickets.json` or `controller_events.json`, authoritative records win.

## Controller and switch logs (authoritative event evidence)
- `case/logs/controller_events.jsonl` — controller event stream (ISO-8601 UTC
  timestamps; includes a `policy_version` field per event).
  For `unattributed_events`, count every event whose site is not MDC-3, whose
  change_id is missing or null, or whose change_id is absent from all MDC-3
  board tickets. A superseded but known MDC-3 ticket is still attributable.
- `case/logs/switch_fabric.log` — fabric switch syslog (local MDC-3 wall-clock
  timestamps, UTC+02:00 summer time during this period — convert to UTC).

## Maintenance windows
- `case/data/maintenance_windows.json` — approved maintenance windows for
  MDC-3 (UTC intervals).

## Telemetry
- `case/data/telemetry.jsonl` — per-hour link telemetry for MDC-3 uplinks
  (UTC start-of-hour; `avg_loss_pct`, `jitter_ms`, `rx_bytes_per_s`,
  `tx_bytes_per_s`). Several same-hour rows use near-match scopes; join on
  exact `site` and exact ticket `link_scope`, not a prefix or nearest value.

## Baseline
- `case/data/baseline.json` — normal-state baseline used for the
  `baseline_delta` judgment.

## Files you must produce / may edit
- `case/audit.py` — YOUR implementation (the only case file you may modify).
- `case/test_task.py` — visible baseline tests (do not modify; they describe
  the contract and fail against the starter stub).

Notes:
- All timestamps in the report must be normalized to UTC.
- Deterministic output: sort all lists, no timestamps of "now", no hostnames.
- The report schema and every judgment rule are in policy v3.
