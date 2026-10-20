"""Build and verify an offline-only, prepare-only MiniMax LongBench plan.

This module deliberately has no network, provider, dispatch, or credential path.
It first screens all 503 rows without decoding answer labels, then freezes the
344 historically screened eligible IDs before reading their answer keys.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from typing import Any, Iterator

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sift import CompactionError, compact_messages  # noqa: E402

DATASET_REVISION = "2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9"
DATASET_SHA256 = "15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2"
TOKENIZER_SHA256 = "bb1f1626cf01448f1e3b6036d0a061ffc66c91d9046aada14ea23a5441b5ad6e"
TEMPLATE_SHA256 = "11421244f67553498e5c8112dae02802025bcc4305ec45ad380af95c96f9fe64"
ROUTE_SHA256 = "c46e271219d7e5890339adf79aafd4e0a58ecdae0908e365d691f4522b07db14"
LIVE_ROUTE_SHA256 = "2985604149f14d6d6ca44c0221780d889058e42ac4f613588a85022eea81c78e"
CURRENT_ROUTE_SHA256 = "440b9279c3300026e83e1bdcc3d20ac38df032328e0c7f87e1bcc4e75868bc7c"
DEFAULT_DATASET = ROOT / ".runs" / "longbench-v2-data-pinned.json"
DEFAULT_TOKENIZER = ROOT / "tmp" / "minimax-m3-tokenizer.json"
DEFAULT_TEMPLATE = ROOT / "tmp" / "minimax-m3-chat-template.jinja"
DEFAULT_ROUTE = ROOT / "docs/evals/longbench-v2-minimax-stage2-route-2026-10-17.json"
LIVE_ROUTE = ROOT / "docs/evals/longbench-v2-openrouter-minimax-m3-endpoints-2026-10-17T1126Z.json"
CURRENT_ROUTE = ROOT / "docs/evals/longbench-v2-openrouter-minimax-m3-endpoints-2026-10-20T0750Z.json"
DEFAULT_OUTPUT = ROOT / "docs/evals/longbench-v2-minimax-344-manifest-2026-10-17.json"
SPEC_PATH = ROOT / "docs/evals/longbench-v2-minimax-paired-study-spec-2026-10-17.md"
PRIMARY_N = 344
OUTSIDE_N = 159
EXTENSION_N = 111
FULL_EXCLUSION_N = 48
FAIL_CLOSED_N = 31
CONFIGURED_TARGET = 32_768
SAFETY_MARGIN = 128
EFFECTIVE_TARGET = CONFIGURED_TARGET - SAFETY_MARGIN
MAX_FULL_LOCAL = 150_000
PROVIDER_LIMIT = 524_288
PROJECTION = 3.25
INPUT_RATE = 0.30
OUTPUT_RATE = 1.20
OUTPUT_CAP = 64
REPEATS = 3
STUDY_SEED = 20261018

SYSTEM_PROMPT = "Answer the multiple-choice question using only the supplied context. Return exactly one option letter: A, B, C, or D."
CONTEXT_PREFIX = "<text>\n"
CONTEXT_SUFFIX = "\n</text>"
QUESTION_SUFFIX = "\nReturn only the letter A, B, C, or D."
THINKING_INSTRUCTIONS = (
    "\n\n<thinking_instructions>\n"
    "You have a thinking capability that allows you to reason step by step before responding. "
    "When thinking is enabled, wrap your reasoning in <mm:think></mm:think> tags before your response. "
    "When thinking is disabled, begin your response directly after the </mm:think> prefix. "
    "When thinking is adaptive, decide on your own whether to think for the current turn.\n"
    "Current thinking mode: disabled. Do not output any thinking process.\n"
    "</thinking_instructions>"
)
PROMPT_FIELDS = {"_id", "domain", "sub_domain", "difficulty", "length", "context", "question",
                 "choice_A", "choice_B", "choice_C", "choice_D"}
ANSWER_FIELDS = PROMPT_FIELDS | {"answer"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _skip_value(source: str, position: int) -> int:
    if position >= len(source):
        raise ValueError("Unexpected end while parsing JSON")
    first = source[position]
    if first == '"':
        position += 1
        escaped = False
        while position < len(source):
            char = source[position]
            position += 1
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                return position
        raise ValueError("Unterminated string")
    if first in "[{":
        stack = ["]" if first == "[" else "}"]
        position += 1
        in_string = escaped = False
        while position < len(source) and stack:
            char = source[position]
            position += 1
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "[":
                stack.append("]")
            elif char == "{":
                stack.append("}")
            elif char in "]}":
                if char != stack.pop():
                    raise ValueError("Mismatched JSON delimiters")
        if stack or in_string:
            raise ValueError("Unterminated JSON container")
        return position
    start = position
    while position < len(source) and source[position] not in ",]} \t\r\n":
        position += 1
    if position == start:
        raise ValueError("Invalid JSON primitive")
    return position


def _select_fields(raw: str, fields: set[str]) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(raw) and raw[pos].isspace():
        pos += 1
    if pos >= len(raw) or raw[pos] != "{":
        raise ValueError("Expected dataset row object")
    pos += 1
    selected: dict[str, Any] = {}
    while True:
        while pos < len(raw) and raw[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(raw):
            raise ValueError("Unterminated dataset object")
        if raw[pos] == "}":
            return selected
        key, key_end = decoder.raw_decode(raw, pos)
        if not isinstance(key, str) or key in selected:
            raise ValueError("Malformed or duplicate dataset field")
        pos = key_end
        while pos < len(raw) and raw[pos].isspace():
            pos += 1
        if pos >= len(raw) or raw[pos] != ":":
            raise ValueError("Expected JSON colon")
        pos += 1
        while pos < len(raw) and raw[pos].isspace():
            pos += 1
        if key in fields:
            try:
                selected[key], pos = decoder.raw_decode(raw, pos)
            except json.JSONDecodeError as error:
                raise ValueError(f"Malformed selected field {key!r}, row chars={len(raw)}, position={pos}") from error
        else:
            pos = _skip_value(raw, pos)


def iter_rows(path: Path, fields: set[str], selected_ids: set[str] | None = None) -> Iterator[dict[str, Any]]:
    buffer = ""
    started = item_started = False
    item_start = depth = 0
    item_parts: list[str] = []
    in_string = escaped = False
    with path.open(encoding="utf-8") as source:
        while chunk := source.read(2 * 1024 * 1024):
            buffer += chunk
            if not started:
                opening = buffer.find("[")
                if opening < 0:
                    buffer = buffer[-1:]
                    continue
                buffer = buffer[opening + 1:]
                started = True
            position = 0
            while position < len(buffer):
                char = buffer[position]
                if not item_started:
                    if char in " \t\r\n,":
                        position += 1
                        continue
                    if char == "]":
                        return
                    if char != "{":
                        raise ValueError("Expected top-level array object")
                    item_started, item_start = True, position
                    depth, in_string, escaped = 0, False, False
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                elif char == '"':
                    in_string = True
                elif char in "[{":
                    depth += 1
                elif char in "]}":
                    depth -= 1
                    if depth == 0:
                        raw = "".join(item_parts) + buffer[item_start:position + 1]
                        if selected_ids is None:
                            yield _select_fields(raw, fields)
                        else:
                            identity = _select_fields(raw, {"_id"})
                            case_id = str(identity.get("_id", ""))
                            if case_id in selected_ids:
                                yield _select_fields(raw, fields)
                        item_parts = []
                        item_started = False
                position += 1
            if item_started:
                item_parts.append(buffer[item_start:])
                item_start = 0
            buffer = ""
    if item_started:
        raise ValueError("Dataset ended inside an object")


def make_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    choices = "\n".join(f"({letter}) {str(row[f'choice_{letter}']).strip()}" for letter in "ABCD")
    question = (f"What is the correct answer to this question: {str(row['question']).strip()}\n"
                f"Choices:\n{choices}{QUESTION_SUFFIX}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": CONTEXT_PREFIX + str(row["context"]).strip() + CONTEXT_SUFFIX},
        {"role": "assistant", "content": "Ready."},
        {"role": "user", "content": question},
    ]


def render_minimax(messages: list[dict[str, str]], generation_prompt: bool = True) -> str:
    bos, eos, bod = "]~b]", "[e~[", "]~!b["
    think_end = "</mm:think>"
    system = ("Your model version is MiniMax-M3, developed by MiniMax. Knowledge cutoff: January 2026. "
              "Founded in early 2022, MiniMax is a global AI foundation model company committed to "
              "advancing the frontiers of AI towards AGI.")
    rendered = f"{bod}{bos}system\n{system}{THINKING_INSTRUCTIONS}{eos}\n"
    developer = messages[0]["content"] if messages and messages[0]["role"] == "system" else "You are a helpful assistant."
    rendered += f"{bos}developer\n{developer}{eos}\n"
    for message in messages[1:] if messages and messages[0]["role"] == "system" else messages:
        role = message["role"]
        if role == "user":
            rendered += f"{bos}user\n{message['content']}{eos}\n"
        elif role == "assistant":
            rendered += f"{bos}ai\n{think_end}{message.get('content', '')}{eos}\n"
        else:
            raise ValueError(f"Unsupported MiniMax prompt role: {role}")
    if generation_prompt:
        rendered += f"{bos}ai\n{think_end}"
    return rendered


def messages_hash(messages: list[dict[str, str]]) -> str:
    return canonical_hash(messages)


def count_tokens(tokenizer: Tokenizer, messages: list[dict[str, str]]) -> int:
    return len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)


def scan_and_select(dataset: Path, tokenizer_path: Path, template_path: Path,
                    frozen_ids: set[str] | None = None,
                    parent_summary: dict[str, Any] | None = None) -> tuple[list[dict], dict]:
    for p in (dataset, tokenizer_path, template_path, ROOT / "src/sift/core.py", ROOT / "benchmarks/prepare_longbench_v2.py",
              ROOT / "benchmarks/prepare_longbench_v2_minimax.py", ROOT / "benchmarks/run_longbench_v2_minimax.py",
              ROOT / "src/sift/__init__.py", SPEC_PATH):
        if not p.is_file():
            raise FileNotFoundError(p)
    expected = {dataset: DATASET_SHA256, tokenizer_path: TOKENIZER_SHA256, template_path: TEMPLATE_SHA256}
    for p, digest in expected.items():
        if sha256_file(p) != digest:
            raise ValueError(f"Pinned source hash mismatch: {p}")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    scanned: list[dict[str, Any]] = []
    seen: set[str] = set()
    failures: Counter[str] = Counter()
    for row in iter_rows(dataset, PROMPT_FIELDS, frozen_ids):
        case_id = str(row.get("_id", ""))
        if not case_id or case_id in seen:
            raise ValueError("Missing or duplicate LongBench task ID")
        seen.add(case_id)
        if not all(isinstance(row.get(field), str) for field in ("domain", "sub_domain", "difficulty", "length", "context", "question", *(f"choice_{x}" for x in "ABCD"))):
            raise ValueError(f"Malformed prompt row: {case_id}")
        messages = make_messages(row)
        full_count = count_tokens(tokenizer, messages)
        projected_full = math.ceil(full_count * PROJECTION)
        try:
            compacted = compact_messages(
                messages,
                lambda candidate: count_tokens(tokenizer, candidate),
                target=EFFECTIVE_TARGET,
                raw_limit=1_000_000,
                protocol="openai",
            )
            sift_messages = compacted.messages
            sift_count = count_tokens(tokenizer, sift_messages)
        except CompactionError as exc:
            sift_messages, sift_count = None, None
            failure = exc.code
            failures[failure] += 1
        else:
            failure = None
            if sift_count > EFFECTIVE_TARGET:
                raise ValueError(f"Default Sift exceeded the frozen target for {case_id}: {sift_count}")
        scanned.append({
            "id": case_id, "domain": row["domain"], "sub_domain": row["sub_domain"],
            "difficulty": row["difficulty"], "length": row["length"],
            "source_prompt_sha256": messages_hash(messages),
            "full_local_tokens": full_count, "full_projected_provider_tokens": projected_full,
            "sift_local_tokens": sift_count,
            "sift_prompt_sha256": messages_hash(sift_messages) if sift_messages is not None else None,
            "sift_fail_closed_code": failure,
            "full_eligible": full_count <= MAX_FULL_LOCAL and projected_full <= PROVIDER_LIMIT,
            # Keep compacted messages out of the manifest; source row plus frozen hashes rebuild them.
            "_messages": messages, "_sift_messages": sift_messages,
        })
    if frozen_ids is None:
        if len(scanned) != 503:
            raise ValueError(f"Expected 503 rows, observed {len(scanned)}")
        primary = [r for r in scanned if r["full_eligible"] and r["sift_local_tokens"] is not None]
        if len(primary) != PRIMARY_N:
            raise ValueError(f"Current implementation yields {len(primary)} primary cases, expected {PRIMARY_N}")
        primary_ids = {r["id"] for r in primary}
        outside = [r for r in scanned if r["id"] not in primary_ids]
        ext = [r for r in outside if r["full_local_tokens"] > MAX_FULL_LOCAL and r["full_local_tokens"] <= PROVIDER_LIMIT and r["sift_local_tokens"] is not None]
        full_excluded = [r for r in outside if r["full_local_tokens"] > PROVIDER_LIMIT]
        if len(outside) != OUTSIDE_N or len(ext) != EXTENSION_N or len(full_excluded) != FULL_EXCLUSION_N:
            raise ValueError(f"Historical split mismatch: outside={len(outside)}, extension={len(ext)}, full_excluded={len(full_excluded)}")
        if sum(r["sift_fail_closed_code"] is not None for r in full_excluded) != FAIL_CLOSED_N:
            raise ValueError("Fail-closed cases within full-prompt exclusions differ from the protocol")
    else:
        primary = [r for r in scanned if r["full_eligible"] and r["sift_local_tokens"] is not None]
        primary_ids = {r["id"] for r in primary}
        if (len(scanned) != PRIMARY_N or len(primary) != PRIMARY_N or primary_ids != frozen_ids
                or parent_summary is None):
            raise ValueError("Frozen primary IDs no longer satisfy current eligibility; prepare a newly reviewed cohort")
        ext = [{"id": value} for value in parent_summary.get("extension_ids", [])]
        failed_ids = set(parent_summary.get("fail_closed_ids_within_full_prompt_exclusions", []))
        full_excluded = [{"id": value, "sift_fail_closed_code": "historical_exclusion" if value in failed_ids else None}
                         for value in parent_summary.get("full_prompt_exclusion_ids", [])]
        if len(ext) != EXTENSION_N or len(full_excluded) != FULL_EXCLUSION_N:
            raise ValueError("Frozen parent cohort has incomplete exclusion metadata")
    # Eligibility has now been fixed without decoding any answer values.
    ids = {r["id"] for r in primary}
    answer_rows = list(iter_rows(dataset, ANSWER_FIELDS, ids))
    by_id = {str(r["_id"]): r for r in answer_rows}
    if set(by_id) != ids or len(answer_rows) != PRIMARY_N:
        raise ValueError("Answer-key pass did not reproduce the frozen eligible ID set")
    for r in primary:
        answer = by_id[r["id"]].get("answer")
        if answer not in {"A", "B", "C", "D"}:
            raise ValueError(f"Malformed answer key for eligible case {r['id']}")
        r["answer_key"] = answer
        r["context_chars"] = len(by_id[r["id"]]["context"])
    return primary, {"scanned": scanned, "failures": failures, "extension": ext, "full_excluded": full_excluded}


def request_body(case: dict, arm: str, repeat: int) -> dict:
    return {
        "model": "minimax/minimax-m3",
        "messages": case["_messages"] if arm == "full" else case["_sift_messages"],
        "temperature": 0.1,
        "top_p": 0.8,
        "seed": STUDY_SEED + repeat + 1,
        "max_tokens": OUTPUT_CAP,
        "reasoning": {"enabled": False},
        "stream": True,
        "stream_options": {"include_usage": True},
        "provider": {"only": ["minimax"], "allow_fallbacks": False},
    }


def build_manifest(dataset: Path, tokenizer: Path, template: Path, route: Path,
                   frozen_cohort_manifest: Path | None = None) -> dict:
    dataset, tokenizer, template, route = (path.resolve() for path in (dataset, tokenizer, template, route))
    if frozen_cohort_manifest is not None:
        frozen_cohort_manifest = frozen_cohort_manifest.resolve()
    expected_route_hashes = {
        DEFAULT_ROUTE.resolve(): ROUTE_SHA256,
        LIVE_ROUTE.resolve(): LIVE_ROUTE_SHA256,
        CURRENT_ROUTE.resolve(): CURRENT_ROUTE_SHA256,
    }
    if not route.is_file() or expected_route_hashes.get(route) != sha256_file(route):
        raise ValueError("Route snapshot must be one of the reviewed historical or live-route snapshots")
    parent = None
    frozen_ids = None
    if frozen_cohort_manifest is not None:
        if (frozen_cohort_manifest.resolve() != (ROOT / "docs/evals/longbench-v2-minimax-344-manifest-live-route-2026-10-17.json").resolve()
                or sha256_file(frozen_cohort_manifest) != "a13822840ceeb3648be58496d9814703a02dca0f70227226a9883a34f0ed4665"):
            raise ValueError("Frozen cohort refresh requires the reviewed 344-task live-route manifest")
        parent = json.loads(frozen_cohort_manifest.read_text(encoding="utf-8"))
        frozen_ids = {str(case.get("id", "")) for case in parent.get("cases", [])}
        if len(frozen_ids) != PRIMARY_N or "" in frozen_ids:
            raise ValueError("Frozen parent manifest does not contain exactly 344 distinct IDs")
    cases, scan = scan_and_select(dataset, tokenizer, template, frozen_ids,
                                  parent.get("cohort_summary") if parent else None)
    route_json = json.loads(route.read_text(encoding="utf-8"))
    pricing = route_json.get("pricing_usd_per_token", route_json.get("pricing", {}))
    prompt_rate = pricing.get("prompt")
    completion_rate = pricing.get("completion")
    if (route_json.get("requested_model") != "minimax/minimax-m3" or
            route_json.get("max_prompt_tokens") != PROVIDER_LIMIT or
            prompt_rate != "0.0000003" or completion_rate != "0.0000012"):
        raise ValueError("Historical route snapshot does not match the frozen planning assumptions")
    source_paths = {
        "builder": Path(__file__).resolve(),
        "spec": SPEC_PATH,
        "dataset": dataset,
        "tokenizer": tokenizer,
        "chat_template": template,
        "sift_core": ROOT / "src/sift/core.py",
        "sift_package_init": ROOT / "src/sift/__init__.py",
        "prompt_builder": ROOT / "benchmarks/prepare_longbench_v2.py",
        "renderer": ROOT / "benchmarks/prepare_longbench_v2_minimax.py",
        "route_snapshot": route,
    }
    source_hashes = {key: sha256_file(path) for key, path in source_paths.items()}
    cases_out = []
    jobs = []
    for case in cases:
        cases_out.append({
            "id": case["id"], "answer_key": case["answer_key"], "domain": case["domain"],
            "sub_domain": case["sub_domain"], "difficulty": case["difficulty"], "length": case["length"],
            "source_prompt_sha256": case["source_prompt_sha256"],
            "full_prompt_sha256": case["source_prompt_sha256"],
            "sift_prompt_sha256": case["sift_prompt_sha256"],
            "full_local_prompt_tokens": case["full_local_tokens"],
            "sift_local_prompt_tokens": case["sift_local_tokens"],
            "eligibility_rationale": "Full local prompt <=150,000; historical 3.25x projection <=524,288; current default Sift compaction succeeds and is <=32,640 tokens.",
        })
    rng = random.Random(STUDY_SEED)
    for case in cases:
        block = []
        for arm in ("full", "sift"):
            for repeat in range(REPEATS):
                body = request_body(case, arm, repeat)
                local_count = case["full_local_tokens"] if arm == "full" else case["sift_local_tokens"]
                block.append({
                    "case_id": case["id"], "arm": arm, "repeat": repeat,
                    "matched_seed_parameter": body["seed"],
                    "canonical_request_body_sha256": canonical_hash(body),
                    "projected_provider_prompt_count": math.ceil(local_count * PROJECTION),
                })
        rng.shuffle(block)
        jobs.extend(block)
    job_keys = {(j["case_id"], j["arm"], j["repeat"]) for j in jobs}
    if len(jobs) != 2064 or len(job_keys) != 2064:
        raise ValueError("Planned job identities are not unique or count is wrong")
    arm_counts = Counter(j["arm"] for j in jobs)
    if arm_counts != {"full": 1032, "sift": 1032}:
        raise ValueError("Planned arm counts differ from protocol")
    primary_ids = {c["id"] for c in cases_out}
    extension_ids = {r["id"] for r in scan["extension"]}
    excluded_ids = {r["id"] for r in scan["full_excluded"]}
    if primary_ids & (extension_ids | excluded_ids) or len(extension_ids) != 111 or len(excluded_ids) != 48:
        raise ValueError("Extension or exclusion IDs entered the primary cohort")
    # Stable chronology/route metadata remains explicitly historical, never a live route claim.
    route_assumptions = {
        "snapshot_path": route.relative_to(ROOT).as_posix(),
        "snapshot_sha256": source_hashes["route_snapshot"],
        "checked_utc": route_json["checked_utc"],
        "requested_model": route_json["requested_model"],
        "provider": route_json.get("provider_name", route_json.get("provider")),
        "endpoint_model_id": route_json.get("model_id") or route_json.get("endpoint_model_id") or route_json.get("provider_endpoint", "").split("|")[-1].strip(),
        "route_tag": route_json.get("tag", route_json.get("endpoint_tag")),
        "max_prompt_tokens": PROVIDER_LIMIT,
        "max_completion_tokens": route_json["max_completion_tokens"],
        "input_usd_per_million": INPUT_RATE,
        "output_usd_per_million": OUTPUT_RATE,
        "status": ("dated_live_route_metadata_snapshot_not_dispatch_authorization"
                   if route in {LIVE_ROUTE.resolve(), CURRENT_ROUTE.resolve()}
                   else "dated_historical_planning_assumptions_only_not_live_validation; refresh route, account usage, and unsettled requests before dispatch"),
        "authorizes_dispatch": False,
    }
    full_input_per_repeat = sum(c["full_local_prompt_tokens"] for c in cases_out)
    sift_input_per_repeat = sum(c["sift_local_prompt_tokens"] for c in cases_out)
    total_projected_input = (full_input_per_repeat + sift_input_per_repeat) * REPEATS
    total_output_cap = len(jobs) * OUTPUT_CAP
    reserve_input_usd = 1.5 * total_projected_input * INPUT_RATE / 1_000_000
    reserve_output_usd = total_output_cap * OUTPUT_RATE / 1_000_000
    manifest = {
        "schema_version": 1,
        "status": "prepared_only_no_dispatch",
        "dispatch_authorized": False,
        "dataset": {
            "id": "zai-org/LongBench-v2", "revision": DATASET_REVISION, "split": "train",
            "row_count": 503, "sha256": source_hashes["dataset"],
            "eligibility_scan_answer_blind": True,
        },
        "route_assumptions": route_assumptions,
        "protocol": {
            "study_seed": STUDY_SEED, "randomization": "within-task block; fixed-seed shuffle of six arm/repeat jobs",
            "arms": ["full", "sift"], "repeats_per_arm": REPEATS,
            "temperature": 0.1, "top_p": 0.8, "reasoning": {"enabled": False},
            "max_tokens": OUTPUT_CAP, "stream": True, "stream_options": {"include_usage": True},
            "provider": {"only": ["minimax"], "allow_fallbacks": False},
            "generation_seed_formula": "study_seed + repeat + 1 with zero-based repeat index (0, 1, 2); matched between arms",
            "seed_determinism": "unestablished; seed is a matched request parameter, not a deterministic-output guarantee",
            "request_body_hash": "SHA-256 over UTF-8 canonical JSON (sorted keys, compact separators, ensure_ascii=false) of the exact body object described by this protocol and frozen messages",
            "source_prompt_system": SYSTEM_PROMPT,
            "source_prompt_final_suffix": "Return only the letter A, B, C, or D.",
            "strict_scoring": "Only a trimmed output exactly equal to one capital letter A, B, C, or D is scorable.",
            "requested_model": "minimax/minimax-m3",
        },
        "sift": {
            "configured_target_tokens": CONFIGURED_TARGET, "safety_margin_tokens": SAFETY_MARGIN,
            "effective_target_tokens": EFFECTIVE_TARGET,
            "protocol": "openai", "compact_function": "sift.compact_messages",
        },
        "source_hashes": source_hashes,
        "cohort_summary": {
            "scanned_rows": 503, "primary_case_count": len(cases_out), "jobs_total": len(jobs),
            "jobs_by_arm": dict(arm_counts), "outside_primary_count": OUTSIDE_N,
            "extension_candidate_count": len(extension_ids), "full_prompt_exclusion_count": len(excluded_ids),
            "fail_closed_within_full_prompt_exclusions": sum(r["sift_fail_closed_code"] is not None for r in scan["full_excluded"]),
            "extension_ids": sorted(extension_ids),
            "full_prompt_exclusion_ids": sorted(excluded_ids),
            "fail_closed_ids_within_full_prompt_exclusions": sorted(r["id"] for r in scan["full_excluded"] if r["sift_fail_closed_code"] is not None),
            "fail_closed_code_counts_all_scan": dict(sorted(scan["failures"].items())),
            "schedule_sha256": canonical_hash(jobs),
            "modeled_reserve": {
                "status": "historical route pricing and 1.5x uncached-input reserve assumption; not a quote, liability, live route validation, or spend authorization",
                "formula": "(1.5 * (sum Full local inputs + sum Sift local inputs) * repeats * input_usd_per_million + job_count * max_tokens * output_usd_per_million) / 1e6",
                "input_usd_per_million": INPUT_RATE,
                "output_usd_per_million": OUTPUT_RATE,
                "input_safety_multiplier": 1.5,
                "full_input_tokens_per_repeat_local": full_input_per_repeat,
                "sift_input_tokens_per_repeat_local": sift_input_per_repeat,
                "projected_input_tokens_three_repeats": total_projected_input,
                "maximum_output_tokens_all_jobs": total_output_cap,
                "reserved_input_usd": round(reserve_input_usd, 10),
                "reserved_output_usd": round(reserve_output_usd, 10),
                "total_reserve_usd": round(reserve_input_usd + reserve_output_usd, 10),
            },
            "untouched_task_count": 0,
            "scope_note": "Primary historical 344 cohort only. The 455 local-fit pool is not dispatched; 111 extension candidates and 48 full-prompt exclusions stay out of cases/jobs.",
        },
        "cases": cases_out,
        "jobs": jobs,
        "network_audit": {
            "dispatch_authorized": False, "provider_initialized": False,
            "network_calls": 0, "actual_dispatch_started": False,
            "api_key_read": False, "network_imports": [],
        },
    }
    if parent is not None:
        manifest["cohort_refresh"] = {
            "parent_manifest_path": frozen_cohort_manifest.relative_to(ROOT).as_posix(),
            "parent_manifest_sha256": sha256_file(frozen_cohort_manifest),
            "selection": "retained the previously reviewed 344 IDs; recomputed prompt hashes, token counts, and Sift compaction with the current source tree",
            "answer_labels_read_after_id_set_frozen": True,
        }
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--route-snapshot", type=Path, default=DEFAULT_ROUTE)
    parser.add_argument("--frozen-cohort-manifest", type=Path,
                        help="Refresh current prompts for IDs from the reviewed 344-task cohort without rescanning/compacting all 503 rows.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Rebuild offline and verify byte-identical existing manifest")
    args = parser.parse_args()
    manifest = build_manifest(args.dataset, args.tokenizer, args.template, args.route_snapshot,
                              args.frozen_cohort_manifest)
    encoded = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not args.output.is_file():
            raise FileNotFoundError(args.output)
        actual = args.output.read_text(encoding="utf-8")
        if actual != encoded:
            raise ValueError("Prepared manifest differs from deterministic offline rebuild")
        print(json.dumps({"check": "passed", "output_sha256": sha256_file(args.output),
                          "scanned_rows": 503, "primary_cases": len(manifest["cases"]),
                          "jobs": len(manifest["jobs"]), "jobs_by_arm": manifest["cohort_summary"]["jobs_by_arm"]}, indent=2))
        return
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing manifest: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "output_sha256": sha256_file(args.output),
                      "scanned_rows": 503, "primary_cases": len(manifest["cases"]),
                      "jobs": len(manifest["jobs"]), "jobs_by_arm": manifest["cohort_summary"]["jobs_by_arm"]}, indent=2))


if __name__ == "__main__":
    main()
