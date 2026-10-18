# Logging configuration v2 (2025-02)

The service now exposes canonical environment names prefixed with `APP_LOG_`:
`APP_LOG_FILE`, `APP_LOG_LEVEL`, `APP_LOG_MAX_BYTES`,
`APP_LOG_BACKUP_COUNT`, and `APP_LOG_COMPRESS`. Existing deployments can keep
the unprefixed `LOG_*` names during the migration window.

For one setting, precedence is built-in default, JSON file, legacy environment
name, then canonical environment name. The canonical name wins if both
environment names for the same setting are present. This is per-setting
precedence: setting `APP_LOG_LEVEL` does not suppress a file value for
`max_bytes`. Environment names are case-sensitive. If a higher-precedence
value is present but invalid, startup must fail; operators need to see the
mistake instead of unknowingly running with a lower-precedence value.

The accepted levels are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`.
Level matching ignores case and the effective value is uppercase. Paths must
be nonempty strings. Byte limits must be positive decimal integers. Backup
counts must be decimal integers between 0 and 99 inclusive. Compression is a
boolean in JSON and `true` or `false` in the environment, ignoring case.
Unknown JSON keys are configuration errors. The normalized artifact is a
sorted JSON object with only the five effective settings; it contains no
generation time. Stable bytes let deployment tooling compare the artifact
across repeated conversions.
