# Deferred technical debt

- Historical excerpt indexes on the default selection path are relative to the
  eligible history span, after immutable leading instructions. Clarify this
  index coordinate system before external consumers treat it as a full-request
  index. Issue #59's harness follows the existing behavior; selection/index
  semantics were not changed as part of its error and client-compatibility fix.
