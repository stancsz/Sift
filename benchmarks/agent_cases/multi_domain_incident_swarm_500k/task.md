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
`finding_id`, `claim`, `disposition`, `facts`, and `evidence_ids` (an array of
exact `source_id` values from the packet). `claim` is the concise summary; its
factual content must agree with the machine-checkable `facts` object. Use the
canonical claim sentences below so the acceptance suite can reject a false
summary rather than accepting correct citations beside contradictory prose.
Include findings `root_cause`,
`confirmed_exposure`, `payment_reconciliation`, `customer_impact`, and
`containment_order`. Every material factual finding must cite the records that
support it. Do not cite a source that does not exist. Include a `limitations`
array for unresolved facts and a top-level `uncertainty` object with exactly
the two required unresolved questions shown below.

Each finding's `facts` object must contain exactly these keys and JSON types:

- `root_cause`: strings `change_id`, `egress_policy`, `principal`, `action`,
  `resource`, `session`, `destination`, and `egress_action`; booleans
  `owner_tag_present` and `policy_exception_present`.
- `confirmed_exposure`: booleans `unauthorized_egress_observed`,
  `customer_reported_export_at_sink`, `payload_contents_independently_verified`,
  and `rollback_prevented_exposure`. This finding confirms the unauthorized
  egress and customer report; it does not claim that raw payload bytes were
  independently inspected.
- `payment_reconciliation`: strings `export_id`, `settlement_status`, and
  `currency`; integer `amount_minor`; booleans `settlement_total_matches` and
  `duplicate_settlement_posting`.
- `customer_impact`: strings `ticket_id`, `customer_id`, and `severity`;
  booleans `reported_confidential_export_at_third_party_endpoint` and
  `payload_contents_independently_verified`.
- `containment_order`: `actions`, an array of six exact action strings in the
  order specified by the authoritative runbook, and boolean
  `rollback_after_containment`.

The `claim` strings must be exactly:

- `root_cause`: `CHG-88421 attached net-export-17; exporter-prod assumed finance-export-writer without the owner tag and sent data to the unapproved sink 198.51.100.77.`
- `confirmed_exposure`: `Unauthorized egress to the unapproved sink is confirmed, and the customer reported the payout export there; the payload contents are not independently verified.`
- `payment_reconciliation`: `EXP-771204 posted once for 4,819,920 USD minor units; the settlement matches and no duplicate posting is evidenced.`
- `customer_impact`: `Customer org-0042 reported that a confidential payout export appeared at a third-party endpoint in P1 ticket CS-88421.`
- `containment_order`: `Follow the runbook containment sequence, then roll back CHG-88421.`

Set top-level `uncertainty` to
`{"unknown_facts":["exact_payload_received_by_external_sink","whether_observed_flow_contained_only_one_export"]}`.
The report must not claim that the exact payload is verified, that no
unauthorized egress occurred, that the settlement was duplicated, or that the
rollback prevented exposure.

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
