# Service logging configuration (operations guide, 2023)

The original service reads the `logging` object from its JSON config file.
Supported file keys are `file`, `level`, `max_bytes`, `backup_count`, and
`compress`. Missing values use the service defaults documented in the
configuration example.

The old deployment environment uses `LOG_FILE`, `LOG_LEVEL`, `LOG_MAX_BYTES`,
`LOG_BACKUPS`, and `LOG_COMPRESS`. These override the JSON file value for the
matching setting. `LOG_BACKUPS` is the old spelling of the file setting
`backup_count`. The environment strings for byte limits and backup counts are
decimal integers; compression accepts `true` or `false`, without regard to
letter case. Empty `LOG_FILE` is not a valid path.

Rotation is performed by Python's size-based rotating file handler. Set
`max_bytes` above zero. `backup_count=0` disables retained backup files;
values above 99 have not been supported by the service.
