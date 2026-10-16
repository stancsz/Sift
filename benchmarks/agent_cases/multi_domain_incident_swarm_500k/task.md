# Incident reconstruction task

Produce `incident_report.json` and `remediation_plan.md` from this packet.
Reconstruct what happened in incident `CHG-88421`, determine whether customer
data was exposed, explain whether the payment export was posted more than once,
and provide a correctly ordered response plan. Join evidence across deployment
and change events, IAM audit, network flows, payment settlement, customer impact,
and the runbook. Separate observed facts from inference and state what remains
unknown. Do not infer safety from a later rollback or from a ticket/dashboard
summary.

`incident_report.json` must have `findings`, an array of objects with
`finding_id`, `claim`, `disposition`, and `evidence_ids` (an array of exact
`source_id` values from the packet). Include findings `root_cause`,
`confirmed_exposure`, `payment_reconciliation`, `customer_impact`, and
`containment_order`. Every material factual finding must cite the records that
support it. Do not cite a source that does not exist. Include a `limitations`
array for unresolved facts.

The key facts are sparse. Check the full timeline and reconcile evidence across
systems. Preserve contradictions and rank evidence using `authority.md`.
The target of this task is a careful, auditable incident report, not a code
change. Run the visible fixture acceptance tests and report exact commands and
results.

Treat this as a cross-domain swarm task. Delegate four bounded, read-only
investigations to named agents: `deployment_auditor` checks the change and
rollback timeline; `identity_auditor` checks the principal, permissions, and
session; `network_payment_auditor` joins flow evidence to settlement state;
`response_auditor` checks customer reports, source authority, and the runbook.
Each agent must return exact source IDs, supported facts, contradictions, and
unknowns. The parent is the only writer and must reconcile overlapping claims
before producing the two deliverables. Do not count repeated reads as
delegation: the run trace must show four distinct agent calls and their
workstream results.
