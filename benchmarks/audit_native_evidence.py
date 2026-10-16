"""Verify that exact gold spans were forwarded before a Claude direct edit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evidence_retention import (
    assess_pre_edit_retention,
    first_direct_edit_timestamp_ns,
    load_required_spans,
    parse_selection_events,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-log", required=True, type=Path)
    parser.add_argument("--native-trace", required=True, type=Path)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--editable", required=True, action="append")
    args = parser.parse_args()

    spans = load_required_spans(args.manifest)
    with args.gateway_log.open(encoding="utf-8") as gateway_log:
        events = parse_selection_events(gateway_log)
    edit_time = first_direct_edit_timestamp_ns(
        args.native_trace, args.workspace, set(args.editable),
    )
    report = assess_pre_edit_retention(
        events, edit_time, {span.span_id for span in spans},
    )
    report["first_edit_utc_ns"] = edit_time
    report["evidence_span_count"] = len(spans)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "verified_before_edit" else 2


if __name__ == "__main__":
    raise SystemExit(main())
