"""Starter implementation for the least-privilege audit task.

The initial version is intentionally incomplete. It parses the role
request and emits a skeleton JSON that is missing the overgrant,
undergrant, constraint-violation, and citation analyses. A competent
agent should replace the body of `build_report` with logic that joins
the policy notes and the access-event logs per the README.

Only this file is editable. Re-run this script to regenerate
`access_audit_report.json`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUTPUT = ROOT / "access_audit_report.json"

SUBJECT = "alice.chen@stratus.example"
REQUESTED_ROLE = "data-eng-prod-read"
REQUEST_EFFECTIVE = "2026-11-01"
WINDOW_START = "2026-07-18"
WINDOW_END = "2026-10-16"


def load_request() -> list[dict]:
    text = (DATA / "role_request.txt").read_text(encoding="utf-8")
    perms: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        action, _, resource = line.partition(" ")
        if action and resource:
            perms.append({"action": action, "resource": resource})
    return perms


def build_report(perms: list[dict]) -> dict:
    # STUB: replace this body with a real least-privilege analysis.
    # The starter approves everything and skips overgrant/undergrant/
    # constraint-violation classification. Visible tests will fail.
    return {
        "subject": SUBJECT,
        "role": REQUESTED_ROLE,
        "request_effective": REQUEST_EFFECTIVE,
        "review_window": {"start": WINDOW_START, "end": WINDOW_END},
        "requested_permissions": perms,
        "approved_permissions": perms,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    perms = load_request()
    report = build_report(perms)
    OUTPUT.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
