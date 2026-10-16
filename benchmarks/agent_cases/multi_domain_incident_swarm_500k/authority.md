# Source authority and contradiction handling

Use this ranking for the specific question each source can answer. Authority is
question-specific, not a blanket ranking:

1. Immutable IAM audit records establish which principal performed which
   authorization action and which session was issued.
2. Raw network flow records establish observed source, destination, bytes, and
   allow/deny outcome. They do not alone prove what payload was transmitted.
3. Signed deployment/change records establish deployed configuration and
   sequence. An approval reference establishes that a reference was attached,
   not that the change was safe or authorized for every action.
4. Settlement ledger records establish whether a payment posting occurred and
   its amount. A duplicate external copy does not itself create a second
   settlement posting.
5. The current incident runbook establishes required response ordering.
6. Customer and security tickets establish reports, impact claims, and actions
   recorded by responders. They do not override raw audit or settlement facts.
7. Chat, dashboards, and routine synthetic records are leads only. Treat them
   as unverified when they conflict with primary source records.

For each conflict, name the source IDs, say which source controls that question,
and retain the lower-ranked account as a discrepancy when it cannot be resolved.
Absence of a record is not proof that an event did not occur.
