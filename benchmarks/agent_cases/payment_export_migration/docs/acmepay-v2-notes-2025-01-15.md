# AcmePay settled-events-v2 notes (effective 2025-01-15)

The current CSV columns are `event_id,occurred_at,event_type,order_ref,amount,currency,status,parent_event_id`.

- `event_type` is `charge` or `refund`. A refund's amount is a positive integer
  number of cents. Link a refund to its original charge by `parent_event_id`;
  its row's `order_ref` is only a hint, not the authoritative link.
- Only rows with status `settled` affect settled totals. Pending events do not
  count as collected funds.
- An exact replay with the same `event_id` and identical fields is idempotent.
  If one `event_id` occurs with different field values, reject the export as
  conflicting input.
- A refund whose parent charge is absent is an orphan. Report it, but do not
  apply it to an order.
- Compare amounts in integer cents. A settled charge must match the order's
  currency and expected amount; an amount mismatch remains in the order's net
  and has an exception, while a currency mismatch does not enter its net and
  has an exception. Linked settled refunds reduce the matched order's net.
- `occurred_at` values can have different UTC offsets. Compare instants, not
  their local timestamp strings. The command's `--as-of` date is UTC; events
  after the end of that UTC date are outside the report.
- Processor fees are absent from this export and are not included in order
  totals.

These v2 rules supersede the June 2024 v1 notes.
