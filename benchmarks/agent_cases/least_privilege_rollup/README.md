# Least-Privilege Grant Rollup — Agent Task

> Public synthetic development data, adapted from the IAM audit fixture. This is exposed diagnostic material, not a held-out benchmark.
> All four exports retain every event for a requested resource plus a date-spread sample of unrelated events.

## Task

Complete `audit_rollup.py` so it writes a deterministic `access_rollup.json` for the role request in `data/role_request.txt`. Read the policy notes and all four access-event exports before deciding what was used or blocked. The records arrive in historical partitions; file order does not define policy precedence.

## Rules

The inclusive UTC review window is 2026-07-18 through 2026-10-16. Match the requested subject exactly. Only an `ALLOW` event by that subject inside the window counts as normal use. `DENY`, break-glass events, other actors, and out-of-window events do not count.

A requested permission is `used` if it has at least one qualifying event. It is `unused` if it has none. A permission blocked by an active policy rule must appear in `policy_blocked`, even if it is also unused. An item can be approved only if it is used and not policy-blocked. Apply effective-date and explicit-supersession language in the policy notes.

## Output

Write one JSON object with `subject`, `review_window` (`start`, `end`), and these three arrays: `approved`, `unused`, and `policy_blocked`. Each array item contains exactly `action` and `resource`. Keep entries in original request order. Do not include generated timestamps, random values, or machine-specific paths.

## Constraints

- Edit only `audit_rollup.py`; running it may create `access_rollup.json`.
- Use Python's standard library.
- Run `python -m unittest -q` before and after editing. The starter should fail visibly.
- Preserve all source files and tests.
