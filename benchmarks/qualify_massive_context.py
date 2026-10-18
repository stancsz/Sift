"""Qualify one native-agent arm's first 500K+ request using local and API usage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any


_EVENT = "sift_benchmark_selection "
_PROVIDER_EVENT = "sift_benchmark_provider_usage "


def _route_events(text: str) -> list[dict[str, Any]]:
    result = []
    for line in text.splitlines():
        if _EVENT not in line:
            continue
        fields = dict(re.findall(r"([a-z_]+)=([^\s]+)", line.split(_EVENT, 1)[1]))
        try:
            fields["request_seq"] = int(fields["request_seq"])
            fields["observed_utc_ns"] = int(fields["observed_utc_ns"])
        except (KeyError, ValueError):
            continue
        for name in ("input_tokens", "forwarded_tokens", "target"):
            if name in fields and fields[name] != "none":
                try:
                    fields[name] = int(fields[name])
                except ValueError:
                    fields[name] = None
        result.append(fields)
    return result


def _provider_events(text: str) -> list[dict[str, Any]]:
    result = []
    for line in text.splitlines():
        if _PROVIDER_EVENT not in line:
            continue
        fields = dict(re.findall(r"([a-z_]+)=([^\s]+)", line.split(_PROVIDER_EVENT, 1)[1]))
        try:
            fields["request_seq"] = int(fields["request_seq"])
            fields["observed_utc_ns"] = int(fields["observed_utc_ns"])
        except (KeyError, ValueError):
            continue
        for name in ("provider_reported_input_total", "input_tokens", "cache_creation_input_tokens",
                     "cache_read_input_tokens", "output_tokens"):
            if name in fields and fields[name] != "unknown":
                try:
                    fields[name] = int(fields[name])
                except ValueError:
                    fields[name] = None
        result.append(fields)
    return result


def _timestamp_ns(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return int(parsed.astimezone(timezone.utc).timestamp() * 1_000_000_000)


def qualify(
    *, arm: str, route_events: list[dict[str, Any]], client_report: dict[str, Any],
    provider_events: list[dict[str, Any]] | None = None,
    request_seq: int, min_raw_tokens: int, max_raw_tokens: int,
    target_tokens: int | None, max_usage_delta_percent: float,
) -> dict[str, Any]:
    event = next((item for item in route_events
                  if item.get("selector") == arm and item.get("request_seq") == request_seq), None)
    failures: list[str] = []
    if event is None:
        failures.append("missing_route_event")
    elif event.get("status") != "ok":
        failures.append("route_counter_failed")

    provider_event = next((item for item in (provider_events or [])
                           if item.get("arm") == arm and item.get("request_seq") == request_seq), None)
    if provider_event is not None and provider_event.get("status") != "ok":
        provider_event = None

    usage_records = client_report.get("client_reported_request_usage")
    if not isinstance(usage_records, list):
        usage_records = []
    event_ns = event.get("observed_utc_ns") if event else None
    candidates = []
    for item in usage_records:
        if not isinstance(item, dict) or type(item.get("provider_reported_input_total")) is not int:
            continue
        start_ns = _timestamp_ns(item.get("started_at"))
        if type(event_ns) is int and type(start_ns) is int and start_ns >= event_ns:
            candidates.append((start_ns - event_ns, item))
    matched_usage = min(candidates, key=lambda pair: pair[0])[1] if candidates else None
    if matched_usage is None and provider_event is None:
        failures.append("missing_per_request_provider_usage")

    if event is not None:
        raw = event.get("input_tokens")
        forwarded = event.get("forwarded_tokens")
        if type(raw) is not int or not min_raw_tokens <= raw <= max_raw_tokens:
            failures.append("raw_input_outside_qualification_band")
        if arm == "full" and forwarded != raw:
            failures.append("full_arm_did_not_preserve_request")
        if arm == "sift" and (type(forwarded) is not int or type(target_tokens) is not int
                               or forwarded > target_tokens):
            failures.append("sift_forwarded_above_target")

    if event is not None and (matched_usage is not None or provider_event is not None):
        route_raw = event.get("input_tokens")
        provider_total = (provider_event.get("provider_reported_input_total")
                          if provider_event is not None else matched_usage.get("provider_reported_input_total"))
        if type(provider_total) is not int:
            failures.append("provider_input_total_unavailable")
        elif provider_total <= 0:
            failures.append("provider_input_total_empty")
        elif arm == "full" and provider_total < min_raw_tokens:
            failures.append("provider_input_below_qualification_floor")
        elif arm == "full" and type(route_raw) is int and route_raw > 0:
            difference = abs(provider_total - route_raw) / route_raw * 100
            if difference > max_usage_delta_percent:
                failures.append("route_provider_usage_delta_too_large")
        elif arm == "sift" and type(target_tokens) is int and provider_total > target_tokens * (1 + max_usage_delta_percent / 100):
            failures.append("provider_input_above_sift_target_tolerance")

    task_accepted = client_report.get("accepted")
    if task_accepted is not True:
        failures.append("task_not_accepted")
    return {
        "schema_version": 1,
        "qualified": not failures,
        "scale_qualified": not any(name.startswith((
            "missing_route", "route_counter", "raw_input", "full_arm", "sift_forwarded",
            "missing_per_request", "provider_input", "route_provider",
        )) for name in failures),
        "failures": failures,
        "arm": arm,
        "route_event": ({key: event.get(key) for key in (
            "selector", "model", "request_seq", "observed_utc_ns", "target", "status",
            "input_tokens", "forwarded_tokens", "count_method",
        )} if event else None),
        "client_reported_request_usage": matched_usage,
        "provider_usage_event": ({key: provider_event.get(key) for key in (
            "arm", "model", "request_seq", "observed_utc_ns", "status", "input_tokens",
            "provider_reported_input_total", "input_total_method", "cache_creation_input_tokens",
            "cache_read_input_tokens", "output_tokens",
        )} if provider_event else None),
        "usage_match_method": "exact benchmark request sequence from body-free LiteLLM provider-response callback; client stream timestamp fallback",
        "thresholds": {
            "min_raw_tokens": min_raw_tokens, "max_raw_tokens": max_raw_tokens,
            "target_tokens": target_tokens,
            "max_usage_delta_percent": max_usage_delta_percent,
        },
        "task_accepted": task_accepted,
        "usage_note": "Claude stream usage is per-response API usage echoed to the client, not an invoice. LiteLLM route counts are local estimates; the comparison is an explicit reconciliation check, not token identity.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("full", "sift"), required=True)
    parser.add_argument("--gateway-log", type=Path, required=True)
    parser.add_argument("--client-report", type=Path, required=True)
    parser.add_argument("--request-seq", type=int, default=1)
    parser.add_argument("--target-tokens", type=int)
    parser.add_argument("--min-raw-tokens", type=int, default=500_000)
    parser.add_argument("--max-raw-tokens", type=int, default=900_000)
    parser.add_argument("--max-usage-delta-percent", type=float, default=25.0)
    args = parser.parse_args()
    if args.request_seq <= 0 or args.min_raw_tokens <= 0 or args.max_raw_tokens < args.min_raw_tokens:
        parser.error("request sequence and raw token range must be positive and ordered")
    if args.arm == "sift" and (args.target_tokens is None or args.target_tokens <= 0):
        parser.error("Sift qualification requires --target-tokens")
    if args.max_usage_delta_percent < 0:
        parser.error("usage delta tolerance must be nonnegative")

    try:
        logs = args.gateway_log.read_text(encoding="utf-8", errors="replace")
        client = json.loads(args.client_report.read_text(encoding="utf-8"))
        if not isinstance(client, dict):
            raise ValueError("client report must be a JSON object")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(f"cannot read qualification inputs: {type(error).__name__}")
    result = qualify(
        arm=args.arm, route_events=_route_events(logs), provider_events=_provider_events(logs),
        client_report=client,
        request_seq=args.request_seq, min_raw_tokens=args.min_raw_tokens,
        max_raw_tokens=args.max_raw_tokens, target_tokens=args.target_tokens,
        max_usage_delta_percent=args.max_usage_delta_percent,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
