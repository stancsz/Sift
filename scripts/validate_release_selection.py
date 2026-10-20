"""Validate the source selector for Sift's non-publishing or PyPI release run."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import tomllib


_STABLE_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_DEV_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.dev(?:0|[1-9][0-9]*)\Z"
)


def validate_release_selection(version: str, *, dry_run: bool, tag: str) -> None:
    """Reject invalid version/tag combinations before any build or publish step."""
    if tag:
        if _STABLE_VERSION.fullmatch(version) is None:
            raise ValueError("a tag can be selected only for a stable vX.Y.Z package version")
        if tag != f"v{version}":
            raise ValueError(f"release tag {tag!r} does not match package version {version!r}")
        return

    if not dry_run:
        raise ValueError("publishing requires an existing stable vX.Y.Z tag")
    if _DEV_VERSION.fullmatch(version) is None:
        raise ValueError("a tagless dry run requires a .devN version")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", choices=("true", "false"), required=True)
    parser.add_argument("--tag", default="", help="stable vX.Y.Z tag; required for publishing")
    args = parser.parse_args()

    try:
        project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        version = project["project"]["version"]
        validate_release_selection(version, dry_run=args.dry_run == "true", tag=args.tag)
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError, ValueError) as error:
        print(f"release selection invalid: {error}", file=sys.stderr)
        return 1

    print(f"release selection valid: version={version}, dry_run={args.dry_run}, tag={args.tag or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
