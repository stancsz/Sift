# Log rotation settings migration

`log_settings.py` converts the service's legacy JSON application config, which
contains a `logging` object, into a stable effective configuration artifact.
The bundled app, operations notes,
and release note are fictional maintenance materials.

Run the baseline suite from this directory:

```sh
python -m unittest -q
```

Implement the migration in `log_settings.py` only. `migrate_file(source,
destination, *, environ=None)` must read the legacy JSON object, resolve its
settings, and write a normalized JSON object. The CLI is:

```sh
python log_settings.py --config examples/legacy-logging.json --output effective.json
```

Settings are `file`, `level`, `max_bytes`, `backup_count`, and `compress`.
Built-in defaults are `var/log/service.log`, `INFO`, `10485760`, `5`, and
`false`. `migrate_file` reads these keys from the top-level `logging` object
and ignores other top-level application sections. `resolve_settings` receives
the inner logging object directly. Configuration keys in that object use
those names. Environment
variables use `APP_LOG_FILE`, `APP_LOG_LEVEL`, `APP_LOG_MAX_BYTES`,
`APP_LOG_BACKUP_COUNT`, and `APP_LOG_COMPRESS`; preserve the pre-migration
aliases `LOG_FILE`, `LOG_LEVEL`, `LOG_MAX_BYTES`, `LOG_BACKUPS`, and
`LOG_COMPRESS`.

Resolve each setting independently: defaults < file < legacy environment
aliases < canonical `APP_LOG_*` environment variables. When both names in one
environment family are present, the canonical name wins. Environment variable
names are case-sensitive. An explicitly supplied invalid value is an error,
even if a lower-precedence value is valid. Do not silently ignore, clamp, or
replace bad values. `file` must be a nonempty string; `level` is one of
`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (case-insensitive and
normalized to uppercase); `max_bytes` is a positive base-10 integer;
`backup_count` is an integer from 0 through 99; and `compress` is a JSON
boolean or an environment string `true`/`false` (case-insensitive). Integer
environment values contain ASCII decimal digits only, without signs or
whitespace. In JSON, integer settings must be integer values, not booleans or
floating-point values. `environ=None` means an empty environment mapping;
the CLI uses the process environment.

Reject a missing or non-object `logging` section, non-object JSON, duplicate
JSON keys anywhere in the input, unknown keys inside `logging`, invalid
settings, and malformed input with `ValueError` or a subclass. Do not mutate
the supplied environment mapping. The output has exactly the five setting
keys above, sorted lexicographically, compact UTF-8 JSON with one trailing
newline, and no timestamps or machine-specific paths beyond the resolved
`file` value. Create the output parent directory if needed. A failed
conversion must not leave a partial output file. Preserve readable errors on
stderr and use a nonzero CLI exit status on failure.

Read all three sources in `docs/` before editing. Their details settle the
legacy naming, precedence, and compatibility contract. Preserve the source
files and tests.
