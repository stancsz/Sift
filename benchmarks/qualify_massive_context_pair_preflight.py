"""Qualify a provider-blocked full/Sift request pair from gateway logs.

The callback records only counts and a request fingerprint. This utility does
not need request bodies or provider credentials and rejects any pair for which
provider usage was recorded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


_PREFLIGHT_EVENT = "sift_benchmark_preflight"
_PROVIDER_EVENT = "sift_benchmark_provider_usage"
_REQUIRED_FIELDS = {
    "run_id", "arm", "model", "request_seq", "fingerprint",
    "raw_tokens", "forwarded_tokens", "target", "minimum_raw_tokens",
    "status",
}
_FIELD = re.compile(r"([a-z_]+)=([^\s]+)")


def _parse_event(log_text: str) -> tuple[dict[str, str] | None, list[str], int]:
    """Return one event's fields and parse failures; count marker occurrences."""
    occurrences = sum(line.count(_PREFLIGHT_EVENT) for line in log_text.splitlines())
    if occurrences != 1:
        return None, (["missing_preflight_event"] if occurrences == 0
                      else ["duplicate_preflight_event"]), occurrences

    line = next(line for line in log_text.splitlines() if _PREFLIGHT_EVENT in line)
    _, suffix = line.split(_PREFLIGHT_EVENT, 1)
    fields: dict[str, str] = {}
    failures: list[str] = []
    cursor = 0
    for match in _FIELD.finditer(suffix):
        if suffix[cursor:match.start()].strip():
            failures.append("malformed_preflight_event")
        key, value = match.groups()
        if key in fields:
            failures.append("duplicate_preflight_field")
        fields[key] = value
        cursor = match.end()
    if suffix[cursor:].strip():
        failures.append("malformed_preflight_event")
    missing = sorted(_REQUIRED_FIELDS - fields.keys())
    if missing:
        failures.append("missing_preflight_fields:" + ",".join(missing))
    return fields, sorted(set(failures)), occurrences


def _as_nonnegative_int(value: str | None) -> int | None:
    if value is None or not re.fullmatch(r"[0-9]+", value):
        return None
    return int(value)


def _validated_event(
    log_text: str, *, expected_arm: str, run_id: str,
    min_raw_tokens: int, max_raw_tokens: int, target_tokens: int | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    fields, failures, _ = _parse_event(log_text)
    if fields is None:
        return None, failures
    if failures:
        return None, failures

    if fields["arm"] != expected_arm:
        failures.append(f"{expected_arm}_arm_mismatch")
    if fields["run_id"] != run_id:
        failures.append(f"{expected_arm}_run_id_mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", fields["fingerprint"]):
        failures.append(f"{expected_arm}_invalid_fingerprint")
    if not fields["model"]:
        failures.append(f"{expected_arm}_missing_model")
    request_seq = _as_nonnegative_int(fields["request_seq"])
    if request_seq is None or request_seq <= 0:
        failures.append(f"{expected_arm}_invalid_request_seq")
    raw = _as_nonnegative_int(fields["raw_tokens"])
    forwarded = _as_nonnegative_int(fields["forwarded_tokens"])
    event_target = _as_nonnegative_int(fields["target"])
    event_minimum = _as_nonnegative_int(fields["minimum_raw_tokens"])
    if raw is None:
        failures.append(f"{expected_arm}_invalid_raw_tokens")
    elif not min_raw_tokens <= raw <= max_raw_tokens:
        failures.append(f"{expected_arm}_raw_tokens_outside_band")
    if forwarded is None:
        failures.append(f"{expected_arm}_invalid_forwarded_tokens")
    if event_minimum is None or event_minimum < min_raw_tokens:
        failures.append(f"{expected_arm}_configured_raw_floor_too_low")
    if fields["status"] != "provider_blocked":
        failures.append(f"{expected_arm}_not_provider_blocked")

    if expected_arm == "full":
        if event_target != 1_000_000:
            failures.append("full_target_must_be_1000000")
        if raw is not None and forwarded is not None and forwarded != raw:
            failures.append("full_forwarded_differs_from_raw")
    else:
        if target_tokens is None or target_tokens <= 0:
            failures.append("invalid_sift_target")
        elif event_target != target_tokens:
            failures.append("sift_target_mismatch")
        if event_target is None or event_target <= 0:
            failures.append("sift_event_target_invalid")
        elif forwarded is not None and forwarded > event_target:
            failures.append("sift_forwarded_above_target")

    return {
        "arm": expected_arm,
        "run_id": fields["run_id"],
        "model": fields["model"],
        "request_seq": request_seq,
        "fingerprint": fields["fingerprint"],
        "input_tokens": raw,
        "forwarded_tokens": forwarded,
        "target": event_target,
        "minimum_raw_tokens": event_minimum,
        "status": fields["status"],
    }, failures


def qualify_pair(
    *, full_log: str, sift_log: str, run_id: str, target_tokens: int,
    min_raw_tokens: int = 500_000, max_raw_tokens: int = 900_000,
) -> dict[str, Any]:
    """Return a JSON-serializable qualification record for a preflight pair."""
    failures: list[str] = []
    if not run_id:
        failures.append("invalid_run_id")
    if type(target_tokens) is not int or target_tokens <= 0:
        failures.append("invalid_sift_target")
    if (type(min_raw_tokens) is not int or type(max_raw_tokens) is not int
            or min_raw_tokens <= 0 or max_raw_tokens < min_raw_tokens):
        failures.append("invalid_raw_token_band")

    full, full_failures = _validated_event(
        full_log, expected_arm="full", run_id=run_id,
        min_raw_tokens=min_raw_tokens, max_raw_tokens=max_raw_tokens,
        target_tokens=None,
    )
    sift, sift_failures = _validated_event(
        sift_log, expected_arm="sift", run_id=run_id,
        min_raw_tokens=min_raw_tokens, max_raw_tokens=max_raw_tokens,
        target_tokens=target_tokens,
    )
    failures.extend(full_failures)
    failures.extend(sift_failures)

    if full is not None and sift is not None:
        if full["fingerprint"] != sift["fingerprint"]:
            failures.append("request_fingerprint_mismatch")
        if full["run_id"] != sift["run_id"]:
            failures.append("pair_run_id_mismatch")
        if full["minimum_raw_tokens"] != sift["minimum_raw_tokens"]:
            failures.append("configured_raw_floor_mismatch")

    if _PROVIDER_EVENT in full_log or _PROVIDER_EVENT in sift_log:
        failures.append("provider_usage_event_present")

    return {
        "schema_version": 1,
        "qualified": not failures,
        "failures": sorted(set(failures)),
        "run_id": run_id,
        "target_tokens": target_tokens,
        "raw_token_band": {"minimum": min_raw_tokens, "maximum": max_raw_tokens},
        "full_event": full,
        "sift_event": sift,
        "note": "Provider-free qualification only; it verifies callback counts and pair identity, not agent acceptance or provider ingestion.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-log", type=Path, required=True)
    parser.add_argument("--sift-log", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target", type=int, required=True,
                        help="positive Sift token target used for the Sift arm")
    parser.add_argument("--min-raw-tokens", type=int, default=500_000)
    parser.add_argument("--max-raw-tokens", type=int, default=900_000)
    args = parser.parse_args()

    try:
        full_text = args.full_log.read_text(encoding="utf-8")
        sift_text = args.sift_log.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        result = {
            "schema_version": 1,
            "qualified": False,
            "failures": ["log_read_failed:" + type(error).__name__],
            "run_id": args.run_id,
            "target_tokens": args.target,
            "raw_token_band": {"minimum": args.min_raw_tokens,
                                "maximum": args.max_raw_tokens},
            "full_event": None,
            "sift_event": None,
        }
    else:
        result = qualify_pair(
            full_log=full_text, sift_log=sift_text, run_id=args.run_id,
            target_tokens=args.target, min_raw_tokens=args.min_raw_tokens,
            max_raw_tokens=args.max_raw_tokens,
        )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
