# MDC-3 Fabric Rollback Playbook (reference)

Fictional operational runbook. Reference material for operators; it is NOT
authoritative for the audit report schema or judgments.

## Scope
Covers link-flap and route-flap rollbacks on the MDC-3 fabric
(toes-sw-01, toes-sw-02) and the Meridian Grid controller (mgc-ctl-01).

## Procedure (summary)
1. Operator confirms the rollback trigger from the controller event
   stream (`change_id` must be present on every rolled-back event).
2. Execute `mgcctl rollback --change <id>`; the controller emits
   `rollback.executed` with the same `change_id`.
3. Verify telemetry returns to baseline within one hourly sample.
4. File a post-rollback note in the #net-ops channel.

## Known quirks (fictional)
- The controller sometimes emits `rollback.executed` twice when the
  operator double-presses; deduplicate by event id when counting.
- Switch syslog timestamps are local wall-clock (UTC+02:00 in summer);
  the controller stream is always UTC. Mixing the two clocks is the most
  common audit error.
