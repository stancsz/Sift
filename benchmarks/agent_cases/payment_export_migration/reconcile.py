"""Legacy AcmePay export reader, scheduled for migration."""

import argparse
import csv
import json
from pathlib import Path


def read_legacy(path: Path) -> dict[str, int]:
    """Read old type/reference/amount rows into a gross order total."""
    result: dict[str, int] = {}
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            reference = row["reference"]
            result[reference] = result.get(reference, 0) + int(row["amount"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legacy_export", type=Path)
    args = parser.parse_args()
    print(json.dumps(read_legacy(args.legacy_export), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
