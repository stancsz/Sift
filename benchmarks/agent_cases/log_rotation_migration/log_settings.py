"""Starter implementation for the logging settings migration."""

import argparse
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path


DEFAULTS = {
    "file": "var/log/service.log",
    "level": "INFO",
    "max_bytes": 10_485_760,
    "backup_count": 5,
    "compress": False,
}


_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_ENV_NAMES = {
    "file": ("LOG_FILE", "APP_LOG_FILE"),
    "level": ("LOG_LEVEL", "APP_LOG_LEVEL"),
    "max_bytes": ("LOG_MAX_BYTES", "APP_LOG_MAX_BYTES"),
    "backup_count": ("LOG_BACKUPS", "APP_LOG_BACKUP_COUNT"),
    "compress": ("LOG_COMPRESS", "APP_LOG_COMPRESS"),
}


def _validate(key, value, *, from_environment=False):
    if key == "file":
        if not isinstance(value, str) or not value:
            raise ValueError("file must be a nonempty string")
        return value
    if key == "level":
        if not isinstance(value, str) or value.upper() not in _LEVELS:
            raise ValueError("level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return value.upper()
    if key in ("max_bytes", "backup_count"):
        if from_environment:
            if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
                raise ValueError(f"{key} must contain ASCII decimal digits")
            value = int(value, 10)
        elif isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
        if key == "max_bytes" and value <= 0:
            raise ValueError("max_bytes must be positive")
        if key == "backup_count" and not 0 <= value <= 99:
            raise ValueError("backup_count must be between 0 and 99")
        return value
    if key == "compress":
        if from_environment:
            if not isinstance(value, str) or value.lower() not in ("true", "false"):
                raise ValueError("compress must be true or false")
            return value.lower() == "true"
        if not isinstance(value, bool):
            raise ValueError("compress must be a JSON boolean")
        return value
    raise ValueError(f"unknown logging setting: {key}")


def resolve_settings(config, environ=None):
    """Resolve each setting using defaults, file values, then env aliases."""
    if not isinstance(config, Mapping):
        raise ValueError("logging configuration must be an object")
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown logging setting: {sorted(unknown)[0]}")
    if environ is None:
        environ = {}
    if not isinstance(environ, Mapping):
        raise ValueError("environment must be a mapping")

    result = dict(DEFAULTS)
    for key, raw in config.items():
        result[key] = _validate(key, raw)
    for key, (legacy_name, canonical_name) in _ENV_NAMES.items():
        for name in (legacy_name, canonical_name):
            if name in environ:
                result[key] = _validate(key, environ[name], from_environment=True)
    return result


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def _load_config(source):
    try:
        raw = json.loads(
            Path(source).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid configuration JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("application configuration must be an object")
    if "logging" not in raw or not isinstance(raw["logging"], dict):
        raise ValueError("application configuration must contain a logging object")
    return raw["logging"]


def migrate_file(source, destination, *, environ=None):
    settings = resolve_settings(_load_config(source), environ=environ)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, target)
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return settings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Normalize service log rotation settings")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        migrate_file(args.config, args.output, environ=os.environ)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"log-settings: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
