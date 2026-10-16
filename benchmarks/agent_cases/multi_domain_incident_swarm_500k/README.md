# Multi-domain incident swarm (500K pilot)

Fictional, deterministic development fixture for reconstructing one production
incident across deployment changes, IAM audit, network telemetry, payment
settlement, customer tickets, and the response runbook. It contains 3,500
provenance-tagged records with synthetic distractors and a few rare correlated
facts spread across the beginning, middle, and end of the stream.

Use the complete historical packet and produce `incident_report.json` and
`remediation_plan.md`. Run the four read-only investigations named in
`task.md`, then have the parent reconcile their exact source IDs, conflicts,
and unknowns. The report must separate observed facts from inference, rank
conflicting sources by `authority.md`, and state what the evidence cannot
establish. Follow the output schema and containment ordering specified in
`task.md`. Run `python -m unittest -q` before delivery.

Rebuild from the repository root with:

```powershell
python benchmarks/build_multi_domain_swarm_500k.py --write-packet
```

`agent_gold/multi_domain_incident_swarm_500k/input_manifest.json` contains a
checksum and byte count for every input row. Its LiteLLM token count is a
packet-only estimate using the pinned 1.103.0 tokenizer. It is not evidence that
a prepared Claude checkpoint or deployed MiniMax route accepted 500K tokens.
The packet is one task message for corpus sizing; actual evaluation must seed it
as historical context and count the complete prepared request.
