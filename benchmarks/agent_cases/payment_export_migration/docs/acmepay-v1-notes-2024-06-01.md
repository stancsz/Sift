# AcmePay settlement export v1 (retired)

This note describes the old `type,reference,amount` CSV export. Refunds were
represented as negative amounts in `amount`. The old importer treats all rows
as gross order adjustments.

This format was replaced for new exports in January 2025. Do not apply these
field names or refund-sign rules to the current settlement export.
