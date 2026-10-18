# Payment export migration

The `reconcile.py` command currently reads the old processor export format.
Migrate it to the current AcmePay settlement export and produce a useful
reconciliation report for operators. The bundled records are fictional,
authored development data, not customer or production exports.

Run the existing baseline and inspect the repository as you normally would:

```sh
python -m unittest -q
```

Implement this command:

```sh
python reconcile.py --orders orders.csv --events current_export.csv --as-of 2025-02-01
```

It writes one deterministic JSON object to stdout. Preserve exact integer
cents; do not use floating point for money. Only events settled by the supplied
UTC date affect settled balances. Preserve every source file and test. Edit only
`reconcile.py`, run the tests before and after the change, and report the result.

The export contains several orders and operational edge cases. Order and event
rows are not grouped. Investigate the current and old format notes and the
discrepancy report. The ORD-8101 note matches its $20 shortfall after the
partial refund; ORD-8102's “still paid” note is stale because a later full
refund settled on January 13. Handle replays, parent-linked refunds, and UTC
as-of filtering according to the current format. Report unmatched or
unreconciled records explicitly instead of silently counting them as paid.
For the supplied `--as-of 2025-02-01`, compare event instants to the UTC day
boundary: `2025-02-02T00:30:00+02:00` is before the cutoff, while
`2025-02-02T00:30:00Z` is after it.

The report has four top-level keys:

- `as_of`: the requested date
- `orders`: one row per order, sorted by `order_id`, with `order_id`,
  `expected_cents`, `settled_net_cents`, `status`, and `included_event_ids`
- `exceptions`: diagnostic objects sorted by `code`, then `event_id`
- `totals`: `expected_by_currency` and `settled_by_currency`, each mapping a
  currency code to integer cents

Order statuses are `paid`, `partial_refund`, `refunded`, `amount_mismatch`,
`currency_mismatch`, or `pending`, as appropriate. Every exception has `code`
and `event_id`; the required codes are `duplicate_event`, `orphan_refund`,
`amount_mismatch`, and `currency_mismatch`. `included_event_ids` contains unique
IDs sorted lexicographically; a duplicate replay is listed once. Pending,
orphaned, and currency-mismatched events do not contribute to order totals.
Settled amount mismatches remain visible in the order's net and exception
report. `settled_by_currency` sums the settled net for orders, grouped by their
order currency.

Use stable JSON formatting. A malformed file or conflicting reuse of an event
ID must fail with a nonzero exit status and a useful error. Do not modify
`orders.csv`, the event export, the notes, discrepancy report, or tests.
