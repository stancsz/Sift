#!/usr/bin/env python3
"""Answer-blind receipt coverage audit for the frozen 18-ID LongBench union.

The two result files contain model outputs. This script never loads them as JSON
objects: it streams JSON and skips every field not on a narrow metadata allowlist.
Skipped values, including outputs/SSE/errors, are neither decoded nor retained.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, BinaryIO, TextIO


ROOT = Path(__file__).resolve().parents[1]
UNION_PATH = Path("docs/evals/longbench-v2-candidate-census-union-2026-10-18.json")
SOURCES = (
    Path("docs/results/longbench-v2-minimax-m3-100-2026-10-16.json"),
    Path("docs/results/longbench-v2-minimax-field-pruning-pilot-2026-10-17.json"),
)
HISTORICAL_MANIFEST = Path("docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json")
PILOT_PREFLIGHT = Path("docs/evals/longbench-v2-minimax-field-pruning-pilot-preflight-2026-10-17.json")
OUT_PATH = Path("docs/evals/longbench-v2-candidate-trace-metadata-audit-2026-10-18.json")

# Only values useful for receipt matching and cost attribution may be retained.
SAFE_SCALARS = {
    "case_id", "task_id", "repeat", "arm", "job_id", "run_id", "request_id",
    "status", "http_status", "provider", "provider_name", "provider_slug",
    "provider_endpoint", "provider_endpoint_id", "model_endpoint_id", "requested_model", "model",
    "endpoint", "route", "route_policy", "allow_fallbacks", "local_rendered_prompt_tokens",
    "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens",
    "cached_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
    "cache_write_tokens",
    "upstream_cost", "upstream_inference_cost", "upstream_inference_cost_usd",
    "upstream_inference_prompt_cost", "upstream_inference_completions_cost",
    "provider_cost", "billed_cost", "cost", "cost_usd", "is_byok", "seed",
    "generation_seed", "generation_seed_formula", "created_utc", "completed_utc", "latency_ms", "ttft_ms",
    "cli_seed", "workers", "randomization",
}
SAFE_STRUCTURES = {
    "run", "metadata", "manifest", "results", "records", "samples", "cases",
    "requests", "jobs", "items", "calls", "data", "usage", "costs", "route",
    "provider", "endpoint", "route_policy", "request_provider_policy", "provider_endpoint", "cost_details",
    "response", "provider_metadata", "endpoint_metadata", "execution_preflight",
    "request_metadata", "response_metadata", "config", "provider_policy", "prompt_tokens_details",
}
SAFE_ARRAYS = {"only", "arms", "repeats"}
FORBIDDEN_KEYS = {
    "answer", "answers", "choice", "choices", "expected", "correct", "responses_body",
    "body", "raw_body", "raw_response", "raw_sse", "sse", "content", "prompt",
    "messages", "error", "errors", "exception", "traceback", "raw_error", "finish_reason",
}
USAGE_KEYS = {
    "prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens",
    "cached_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "cost",
    "cost_usd", "upstream_cost", "upstream_inference_cost", "upstream_inference_cost_usd",
    "provider_cost", "billed_cost", "is_byok",
}
COST_DETAIL_KEYS = {
    "upstream_inference_cost",
    "upstream_inference_prompt_cost",
    "upstream_inference_completions_cost",
}
CACHE_DETAIL_KEYS = {"cached_tokens", "cache_write_tokens"}


class UnsafeJSON(ValueError):
    pass


class StreamingWhitelistJSON:
    """Small JSON tokenizer that materializes only whitelisted metadata values."""

    def __init__(self, stream: TextIO):
        self.stream = stream
        self.buf = ""
        self.pos = 0
        self.eof = False

    def _fill(self) -> None:
        if self.pos < len(self.buf) or self.eof:
            return
        self.buf = self.stream.read(65536)
        self.pos = 0
        self.eof = not self.buf

    def _peek(self) -> str:
        self._fill()
        return self.buf[self.pos] if self.pos < len(self.buf) else ""

    def _take(self) -> str:
        ch = self._peek()
        if ch:
            self.pos += 1
        return ch

    def _ws(self) -> None:
        while self._peek() and self._peek() in " \t\r\n":
            self.pos += 1

    def _expect(self, wanted: str) -> None:
        got = self._take()
        if got != wanted:
            raise UnsafeJSON(f"invalid JSON structure; expected {wanted!r}")

    def _string(self, *, keep: bool) -> str | None:
        self._expect('"')
        chars: list[str] | None = [] if keep else None
        while True:
            ch = self._take()
            if not ch:
                raise UnsafeJSON("unterminated JSON string")
            if chars is not None:
                chars.append(ch)
            if ch == '"':
                break
            if ch == "\\":
                esc = self._take()
                if not esc or esc not in '"\\/bfnrtu':
                    raise UnsafeJSON("invalid JSON string escape")
                if chars is not None:
                    chars.append(esc)
                if esc == "u":
                    for _ in range(4):
                        hx = self._take()
                        if not hx or hx not in "0123456789abcdefABCDEF":
                            raise UnsafeJSON("invalid JSON unicode escape")
                        if chars is not None:
                            chars.append(hx)
            elif ord(ch) < 0x20:
                raise UnsafeJSON("unescaped control character in JSON string")
        if chars is None:
            return None
        raw = '"' + "".join(chars[:-1]) + '"'
        try:
            val = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UnsafeJSON("malformed JSON string") from exc
        if not isinstance(val, str):
            raise UnsafeJSON("string decoder returned a non-string")
        return val

    def _skip_number_or_literal(self) -> None:
        token: list[str] = []
        while (ch := self._peek()) and ch not in " \t\r\n,]}:":
            token.append(ch)
            self.pos += 1
            if len(token) > 128:
                raise UnsafeJSON("invalid oversized JSON primitive")
        try:
            json.loads("".join(token))
        except json.JSONDecodeError as exc:
            raise UnsafeJSON("malformed JSON primitive") from exc

    def _skip_value(self) -> None:
        self._ws()
        ch = self._peek()
        if ch == '"':
            self._string(keep=False)
        elif ch == "{":
            self._take(); self._ws()
            if self._peek() == "}":
                self._take(); return
            while True:
                self._ws(); self._string(keep=False); self._ws(); self._expect(":")
                self._skip_value(); self._ws()
                sep = self._take()
                if sep == "}": return
                if sep != ",": raise UnsafeJSON("invalid object while skipping")
        elif ch == "[":
            self._take(); self._ws()
            if self._peek() == "]":
                self._take(); return
            while True:
                self._skip_value(); self._ws()
                sep = self._take()
                if sep == "]": return
                if sep != ",": raise UnsafeJSON("invalid array while skipping")
        elif ch in "-0123456789tfn":
            self._skip_number_or_literal()
        else:
            raise UnsafeJSON("invalid JSON value while skipping")

    def _safe_value(self, key_context: str | None = None) -> Any:
        self._ws()
        ch = self._peek()
        if ch == "{":
            self._take(); self._ws()
            result: dict[str, Any] = {}
            if self._peek() == "}":
                self._take(); return result
            while True:
                self._ws()
                key = self._string(keep=True)
                assert key is not None
                low = key.casefold()
                self._ws(); self._expect(":"); self._ws()
                if low in FORBIDDEN_KEYS:
                    self._skip_value()
                elif key_context == "prompt_tokens_details" and low in CACHE_DETAIL_KEYS:
                    val = self._safe_scalar()
                    if type(val) is not int or val < 0:
                        raise UnsafeJSON("cache-token detail must be a nonnegative integer")
                    result[key] = val
                elif key_context == "cost_details" and low in COST_DETAIL_KEYS:
                    val = self._safe_scalar()
                    if type(val) not in (int, float):
                        raise UnsafeJSON("cost detail must be a numeric provider receipt")
                    result[key] = val
                elif low in SAFE_ARRAYS and self._peek() == "[":
                    result[key] = self._safe_scalar_array()
                elif low in SAFE_STRUCTURES and self._peek() in "{[":
                    value = self._safe_value(low)
                    if value:
                        result[key] = value
                elif low in SAFE_SCALARS and self._peek() in "{[":
                    self._skip_value()
                elif low in SAFE_SCALARS:
                    val = self._safe_scalar()
                    if val is not _OMIT:
                        result[key] = val
                elif low in SAFE_STRUCTURES:
                    self._skip_value()
                else:
                    self._skip_value()
                self._ws()
                sep = self._take()
                if sep == "}": break
                if sep != ",": raise UnsafeJSON("invalid object structure")
            return result
        if ch == "[":
            self._take(); self._ws()
            values: list[Any] = []
            if self._peek() == "]":
                self._take(); return values
            while True:
                self._ws()
                # Arrays can be receipt collections under structural parents;
                # scalar values are intentionally discarded.
                if self._peek() in "{[":
                    values.append(self._safe_value())
                else:
                    self._skip_value()
                self._ws()
                sep = self._take()
                if sep == "]": break
                if sep != ",": raise UnsafeJSON("invalid array structure")
            return values
        return self._safe_scalar()

    def _safe_scalar(self) -> Any:
        self._ws()
        ch = self._peek()
        if ch == '"':
            return self._string(keep=True)
        token_chars: list[str] = []
        while (ch := self._peek()) and ch not in " \t\r\n,]}":
            token_chars.append(ch)
            self.pos += 1
            if len(token_chars) > 128:
                raise UnsafeJSON("invalid oversized metadata primitive")
        token = "".join(token_chars)
        if token == "true": return True
        if token == "false": return False
        if token == "null": return None
        try:
            value = json.loads(token)
        except (json.JSONDecodeError, TypeError) as exc:
            raise UnsafeJSON("malformed metadata scalar") from exc
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float) and not math.isfinite(value):
                raise UnsafeJSON("non-finite metadata number")
            return value
        return _OMIT

    def _safe_scalar_array(self) -> list[Any]:
        self._expect("[")
        values: list[Any] = []
        self._ws()
        if self._peek() == "]":
            self._take()
            return values
        while True:
            self._ws()
            if self._peek() in "{[":
                self._skip_value()
            else:
                value = self._safe_scalar()
                if value is not _OMIT:
                    values.append(value)
            self._ws()
            sep = self._take()
            if sep == "]":
                return values
            if sep != ",":
                raise UnsafeJSON("invalid scalar metadata array")

    def read(self) -> Any:
        result = self._safe_value()
        self._ws()
        if self._peek():
            raise UnsafeJSON("trailing data after JSON document")
        return result


_OMIT = object()


def safe_stream_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as raw:
        with io.TextIOWrapper(raw, encoding="utf-8", errors="strict") as text:
            return StreamingWhitelistJSON(text).read()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_receipt_records(value: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        normalized = {k.casefold(): v for k, v in value.items()}
        cid = normalized.get("case_id", normalized.get("task_id"))
        if isinstance(cid, str) and normalized.get("arm") is not None:
            out.append(value)
        for child in value.values():
            _find_receipt_records(child, out)
    elif isinstance(value, list):
        for child in value:
            _find_receipt_records(child, out)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_safe_json(path: Path) -> dict[str, Any]:
    value = safe_stream_json(ROOT / path)
    if not isinstance(value, dict):
        raise UnsafeJSON(f"expected object at {path}")
    return value


def _candidate_ids(path: Path) -> tuple[list[str], dict[str, list[str]], str]:
    # Candidate census is a frozen answer-blind manifest, not a model result.
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    ids_block = data.get("ids")
    if not isinstance(ids_block, dict):
        raise UnsafeJSON("candidate-union artifact has no ids object")
    groups = {k: v for k, v in ids_block.items() if k in {"field_pruning", "query_directed"}}
    if any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in groups.values()):
        raise UnsafeJSON("candidate groups are malformed")
    union = sorted(set(groups["field_pruning"]) | set(groups["query_directed"]))
    if len(union) != 18 or set(groups["field_pruning"]) & set(groups["query_directed"]):
        raise UnsafeJSON("candidate union does not match frozen 9+9 disjoint expectation")
    return union, groups, sha256_file(ROOT / path)


def _get_safe_preflight() -> dict[str, Any]:
    # Stream metadata through the same whitelist: prepared jobs contain labels
    # and seeds, but no answer-bearing fields are needed for route provenance.
    raw = safe_stream_json(ROOT / PILOT_PREFLIGHT)
    config = raw.get("config", {})
    if not isinstance(config, dict):
        raise UnsafeJSON("pilot preflight config malformed")
    return {
        "route": {
            "requested_model": raw.get("model"),
            "provider_only": config.get("provider_policy", {}).get("only"),
            "allow_fallbacks": config.get("provider_policy", {}).get("allow_fallbacks"),
        },
        "workers": config.get("workers"),
        "repeats": config.get("repeats"),
        "arms": config.get("arms"),
        "cli_seed": config.get("cli_seed"),
        "randomization": config.get("randomization"),
        "generation_seed_formula": config.get("generation_seed_formula"),
    }


def _get_safe_historical_route() -> dict[str, Any]:
    # The frozen manifest contains an answer_key per case; the streaming reader
    # skips the entire cases subtree and retains only route/model metadata.
    data = safe_stream_json(ROOT / HISTORICAL_MANIFEST)
    if not isinstance(data, dict):
        raise UnsafeJSON("historical manifest malformed")
    endpoint = data.get("provider_endpoint", {})
    policy = endpoint.get("request_provider_policy", {}) if isinstance(endpoint, dict) else {}
    return {
        "provider": endpoint.get("provider_name") if isinstance(endpoint, dict) else None,
        "provider_slug": endpoint.get("provider_slug") if isinstance(endpoint, dict) else None,
        "provider_endpoint_id": endpoint.get("model_endpoint_id") if isinstance(endpoint, dict) else None,
        "allow_fallbacks": policy.get("allow_fallbacks") if isinstance(policy, dict) else None,
        "only": policy.get("only") if isinstance(policy, dict) else None,
    }


def _receipt_fields(record: dict[str, Any]) -> dict[str, Any]:
    # Flatten only safe fields. Unknown/missing usage remains null.
    out: dict[str, Any] = {}
    low = {k.casefold(): v for k, v in record.items()}
    for key in ("case_id", "task_id", "repeat", "arm", "job_id", "request_id", "status", "http_status",
                "provider", "provider_name", "provider_slug", "provider_endpoint", "provider_endpoint_id",
                "requested_model", "model", "endpoint", "route", "route_policy", "allow_fallbacks",
                "local_rendered_prompt_tokens", "prompt_tokens", "completion_tokens", "total_tokens",
                "input_tokens", "output_tokens", "cached_tokens", "upstream_cost", "upstream_inference_cost",
                "upstream_inference_cost_usd", "provider_cost", "billed_cost", "cost", "cost_usd", "is_byok",
                "seed", "generation_seed", "latency_ms", "ttft_ms"):
        if key in low:
            out[key] = low[key]
    if "arm" in out and out["arm"] in {"sift", "default"}:
        out["arm"] = "default_sift"
    def find_usage(node: Any) -> dict[str, Any] | None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.casefold() == "usage" and isinstance(value, dict):
                    return value
            for value in node.values():
                found = find_usage(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find_usage(value)
                if found is not None:
                    return found
        return None

    usage = find_usage(record)
    if isinstance(usage, dict):
        for key, value in usage.items():
            if key.casefold() in USAGE_KEYS:
                out[f"usage_{key.casefold()}"] = value
    def find_cost_details(node: Any) -> dict[str, Any] | None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.casefold() == "cost_details" and isinstance(value, dict):
                    return value
            for value in node.values():
                found = find_cost_details(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find_cost_details(value)
                if found is not None:
                    return found
        return None

    cost_details = find_cost_details(record)
    if isinstance(cost_details, dict):
        for key, value in cost_details.items():
            if key.casefold() in COST_DETAIL_KEYS and type(value) in (int, float):
                out[f"cost_details_{key.casefold()}"] = value

    def find_prompt_tokens_details(node: Any) -> dict[str, Any] | None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key.casefold() == "prompt_tokens_details" and isinstance(value, dict):
                    return value
            for value in node.values():
                found = find_prompt_tokens_details(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = find_prompt_tokens_details(value)
                if found is not None:
                    return found
        return None

    prompt_details = find_prompt_tokens_details(record)
    if isinstance(prompt_details, dict):
        for key in CACHE_DETAIL_KEYS:
            value = prompt_details.get(key)
            if type(value) is int and value >= 0:
                out[f"prompt_tokens_details_{key}"] = value
    # Avoid duplicate alias task_id/case_id in output; canonicalize to case_id.
    out["case_id"] = low.get("case_id", low.get("task_id"))
    return out


def build_audit() -> dict[str, Any]:
    ids, groups, union_sha = _candidate_ids(UNION_PATH)
    cohort = set(ids)
    preflight = _get_safe_preflight()
    historical_route = _get_safe_historical_route()
    source_definitions = [
        (SOURCES[0], "historical_100_task_full_default"),
        (SOURCES[1], "field_pruning_pilot"),
    ]
    all_receipts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_info: list[dict[str, Any]] = []
    source_records: dict[str, list[dict[str, Any]]] = {}
    for relpath, source_kind in source_definitions:
        safe_tree = safe_stream_json(ROOT / relpath)
        found: list[dict[str, Any]] = []
        _find_receipt_records(safe_tree, found)
        records = [_receipt_fields(item) for item in found]
        selected = [r for r in records if r.get("case_id") in cohort]
        source_records[source_kind] = selected
        route_metadata = historical_route if source_kind == "historical_100_task_full_default" else preflight["route"]
        route_metadata = dict(route_metadata)
        observed_models = sorted({str(r["model"]) for r in selected if r.get("model") is not None})
        if observed_models:
            route_metadata["observed_models"] = observed_models
        source_info.append({
            "source": relpath.as_posix(),
            "sha256": sha256_file(ROOT / relpath),
            "source_kind": source_kind,
            "metadata_receipt_rows_seen": len(records),
            "candidate_receipt_rows": len(selected),
            "route_metadata": route_metadata,
            "route_metadata_source": HISTORICAL_MANIFEST.as_posix() if source_kind == "historical_100_task_full_default" else PILOT_PREFLIGHT.as_posix(),
            "route_metadata_source_sha256": sha256_file(ROOT / (HISTORICAL_MANIFEST if source_kind == "historical_100_task_full_default" else PILOT_PREFLIGHT)),
        })
        for record in selected:
            all_receipts[str(record["case_id"])].append({**record, "source_kind": source_kind})

    # Fail closed: only the known arm names and candidate source files are in scope.
    for cid, receipts in all_receipts.items():
        for receipt in receipts:
            if receipt.get("arm") not in {"full", "default_sift", "field_pruning", "query_directed"}:
                raise UnsafeJSON(f"unexpected arm label in metadata for candidate {cid}")

    # A true three-arm candidate comparison requires same task/repeat in the
    # concurrent field pilot. Historical full/default records are separately labeled.
    pilot_by: dict[tuple[str, str], set[str]] = defaultdict(set)
    historical_by: dict[tuple[str, str], set[str]] = defaultdict(set)
    for cid, receipts in all_receipts.items():
        for r in receipts:
            rep = str(r.get("repeat"))
            if r.get("source_kind") == "field_pruning_pilot":
                pilot_by[(cid, rep)].add(str(r.get("arm")))
            else:
                historical_by[(cid, rep)].add(str(r.get("arm")))

    per_id: list[dict[str, Any]] = []
    for cid in ids:
        receipts = all_receipts.get(cid, [])
        counts: dict[str, int] = defaultdict(int)
        repeat_sets: dict[str, set[str]] = defaultdict(set)
        for r in receipts:
            arm = str(r.get("arm"))
            counts[arm] += 1
            repeat_sets[arm].add(str(r.get("repeat")))
        candidate_group = "field_pruning" if cid in groups["field_pruning"] else "query_directed"
        pilot_triplets = sorted(rep for (task, rep), arms in pilot_by.items()
                               if task == cid and {"full", "default_sift", "field_pruning"} <= arms)
        historical_pairs = sorted(rep for (task, rep), arms in historical_by.items()
                                  if task == cid and "full" in arms and "default_sift" in arms)
        if pilot_triplets:
            comparison = "concurrent_paired"
        elif historical_pairs:
            comparison = "historical_matched"
        else:
            comparison = "missing"
        # Exact safe receipt fields remain attached for downstream cost replay.
        safe_receipts = [{k: v for k, v in r.items() if k != "source_kind"} | {"source_kind": r["source_kind"]}
                         for r in receipts]
        per_id.append({
            "case_id": cid,
            "candidate_group": candidate_group,
            "receipt_counts_by_arm": dict(sorted(counts.items())),
            "repeat_labels_by_arm": {k: sorted(v) for k, v in sorted(repeat_sets.items())},
            "concurrent_paired_triplet_repeats": pilot_triplets,
            "historical_full_default_matched_repeats": historical_pairs,
            "comparison_classification": comparison,
            "receipts": safe_receipts,
        })

    summary = {
        "candidate_ids": len(ids),
        "field_pruning_ids": len(groups["field_pruning"]),
        "query_directed_ids": len(groups["query_directed"]),
        "ids_with_historical_full_default": sum(x["comparison_classification"] in {"historical_matched", "concurrent_paired"} for x in per_id),
        "ids_with_concurrent_field_pruning_triplets": sum(bool(x["concurrent_paired_triplet_repeats"]) for x in per_id),
        "ids_with_query_directed_candidate_receipts": sum(any(r.get("arm") == "query_directed" for r in x["receipts"]) for x in per_id),
        "ids_with_no_receipts": sum(not x["receipts"] for x in per_id),
    }
    return {
        "schema_version": 1,
        "status": "answer_blind_metadata_only_audit",
        "source_scope": "Only the frozen 18-ID candidate union and the two named raw result files were processed; output/answer-bearing keys were skipped by the streaming parser.",
        "candidate_union": {"source": UNION_PATH.as_posix(), "sha256": union_sha, "ids": ids,
                            "groups": groups, "count": len(ids)},
        "sources": source_info,
        "field_pruning_pilot_protocol": {k: v for k, v in preflight.items() if k != "route"},
        "summary": summary,
        "per_id": per_id,
        "interpretation": [
            "concurrent_paired means Full, default Sift, and field_pruning share a task/repeat block in the field-pruning pilot; requests were one worker and arm order was randomized within each block.",
            "historical_matched means Full/default Sift records share task/repeat labels in the older 100-task run; this is not a new candidate-arm comparison.",
            "No query_directed candidate arm receipt was found in the two in-scope sources.",
            "Usage and cost are copied only from explicitly whitelisted metadata fields. Missing fields remain absent; this artifact does not infer billed costs from local token counts.",
            "For BYOK receipts, usage_cost=0 is not zero upstream inference spend; positive upstream pass-through cost is recorded separately in cost_details.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / OUT_PATH)
    parser.add_argument("--check", action="store_true", help="build and compare with the saved audit")
    args = parser.parse_args()
    audit = build_audit()
    text = json.dumps(audit, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        existing = args.output.read_text(encoding="utf-8")
        if json.loads(existing) != audit:
            raise SystemExit("saved audit differs from current answer-blind metadata extraction")
        print(f"verified {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
        print(json.dumps(audit["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
