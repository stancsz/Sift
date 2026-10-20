"""Prepare or explicitly dispatch the frozen 100-task or 344-task MiniMax study.

Default invocation is offline. The prepared artifact contains hashes and counts,
never prompt or answer text. Dispatch has no resume mode: any prior/ambiguous
dispatch must be reconciled out of band before starting a new output file.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any

import requests
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION, DATASET_SHA256, file_sha256, make_messages, prompt_sha256,
)
from audit_longbench_v2_target_sweep import iter_selected_dataset_rows  # noqa: E402
from prepare_longbench_v2_minimax import render_minimax  # noqa: E402
from sift import CompactionError, compact_messages  # noqa: E402

MANIFEST = ROOT / "docs/evals/longbench-v2-minimax-stage1-100-manifest-2026-10-18.json"
MANIFEST_344 = ROOT / "docs/evals/longbench-v2-minimax-344-manifest-2026-10-17.json"
MANIFEST_344_LIVE_ROUTE = ROOT / "docs/evals/longbench-v2-minimax-344-manifest-live-route-2026-10-17.json"
MANIFEST_344_CURRENT = ROOT / "docs/evals/longbench-v2-minimax-344-manifest-current-main-2026-10-20.json"
PARENT = ROOT / "docs/evals/longbench-v2-minimax-344-manifest-2026-10-17.json"
HISTORICAL = ROOT / "docs/evals/longbench-v2-minimax-m3-100-manifest-2026-10-16.json"
DATASET_DEFAULT = ROOT / ".runs/longbench-v2-data-pinned.json"
TOKENIZER_DEFAULT = ROOT / "tmp/minimax-m3-tokenizer.json"
TEMPLATE_DEFAULT = ROOT / "tmp/minimax-m3-chat-template.jinja"
OUTPUT_DEFAULT = ROOT / ".runs/longbench-v2-minimax-stage1-100-run.json"
CONTINUATION_OUTPUT = ROOT / ".runs/longbench-v2-minimax-344-continuation-2026-10-20.json"
CONTINUATION_CLAIM = ROOT / ".runs/longbench-v2-minimax-344-continuation-claimed-2026-10-20.json"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "minimax/minimax-m3"
TARGET = 32_768
SAFETY_MARGIN = 128
OUTPUT_CAP = 64
REPEATS = 3
STUDY_SEED = 20261018
MAX_RATIO = 1.05
INPUT_FACTOR = 1.5
INPUT_PRICE = 0.30  # dated planning rate; dispatch cap must be approved separately
OUTPUT_PRICE = 1.20
PROJECTION = 3.25
PROVIDER_LIMIT = 524_288
MANIFEST_SHA256_STAGE1 = "52a7515d9bec715ccc17c85295b2e111d97cb2bffc00bd71fc9ed933cb22fce2"
MANIFEST_SHA256_344 = "6364b4a21e5775fb4cd574e501286db64320cd4cde2b083250b07ec13ea6abc0"
MANIFEST_SHA256_344_LIVE_ROUTE = "a13822840ceeb3648be58496d9814703a02dca0f70227226a9883a34f0ed4665"
MANIFEST_SHA256_344_CURRENT = "eaddd0d337111c6ab3c36d3f4a68dae4f002c94964de39beec620280f9c657c2"
UNKNOWN_503_REPORT_SHA256 = "d0b964b1a44e9f7b42edea7bc7f7761586dbd9e9b616f11fd13a3d9d624ed14a"
UNKNOWN_503_JOB_IDS = {
    "6725db8bbb02136c067d84eb:full:1",
    "66f5605a821e116aacb3381f:full:1",
    "67191791bb02136c067d406c:full:1",
    "66ed23ce821e116aacb1ee84:full:1",
}
UNKNOWN_503_UNRECEIPTED_ATTEMPTS = {
    ("66f954a5bb02136c067c511a:full:1", 1, 400),
    ("6725db8bbb02136c067d84eb:full:1", 1, None),
    ("66f3a311821e116aacb2de19:full:1", 1, 400),
    ("66f5605a821e116aacb3381f:full:1", 1, None),
    ("67191791bb02136c067d406c:full:1", 1, None),
    ("66ed24c5821e116aacb1eee6:full:1", 1, 400),
    ("66ed23ce821e116aacb1ee84:full:1", 2, None),
}
UNKNOWN_600_REPORT_SHA256 = "fb42c2232e003a95465fb225eca98fd55816af82c40904225cee4fbad9f9e72b"
UNKNOWN_600_UNRECEIPTED_ATTEMPTS = {
    ("6725db46bb02136c067d84b4:sift:2", 1, None),
    ("672494e5bb02136c067d7697:full:2", 1, None),
    ("67286036bb02136c067d9092:full:1", 1, None),
    ("67189156bb02136c067d3b8d:sift:0", 1, None),
    ("66ebdadd5a08c7b9b35e0e5b:full:1", 1, None),
}
UNKNOWN_344_REPORT_SHA256 = "20e1106b1f4c27c801f0411d433a06c7e1def9ed48be4b0b3df7431671e30356"
UNKNOWN_344_MANIFEST_SHA256 = MANIFEST_SHA256_344_CURRENT
UNKNOWN_344_JOB_IDS = {"66f53892821e116aacb33225:full:2"}
ROUTE_SNAPSHOT_HISTORICAL = ROOT / "docs/evals/longbench-v2-minimax-stage2-route-2026-10-17.json"
ROUTE_SNAPSHOT_LIVE = ROOT / "docs/evals/longbench-v2-openrouter-minimax-m3-endpoints-2026-10-17T1126Z.json"
ROUTE_SNAPSHOT_CURRENT = ROOT / "docs/evals/longbench-v2-openrouter-minimax-m3-endpoints-2026-10-20T0750Z.json"


class StageError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def safe_repo_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise StageError(f"Manifest path escapes repository: {relative}") from error
    if not path.is_file():
        raise StageError(f"Required frozen source is missing: {relative}")
    return path


def verify_provenance(manifest: dict, manifest_path: Path, dataset: Path,
                      tokenizer_path: Path, template_path: Path) -> tuple[str, dict]:
    is_stage1 = "selection" in manifest
    mode = "stage1_100" if is_stage1 else "primary_344"
    resolved_manifest = manifest_path.resolve()
    accepted_manifests = {
        MANIFEST.resolve(): MANIFEST_SHA256_STAGE1,
        MANIFEST_344.resolve(): MANIFEST_SHA256_344,
        MANIFEST_344_LIVE_ROUTE.resolve(): MANIFEST_SHA256_344_LIVE_ROUTE,
        MANIFEST_344_CURRENT.resolve(): MANIFEST_SHA256_344_CURRENT,
    }
    expected_manifest_hash = accepted_manifests.get(resolved_manifest)
    if expected_manifest_hash is None:
        raise StageError("Only a reviewed frozen Stage 1 or 344-task manifest is accepted")
    if file_sha256(manifest_path) != expected_manifest_hash:
        raise StageError(f"Reviewed {mode} manifest hash mismatch")
    if manifest.get("dispatch_authorized") is not False:
        raise StageError("Stage manifest must remain dispatch_authorized=false")
    if manifest.get("status") != "prepared_only_no_dispatch":
        raise StageError("Unexpected prepared manifest status")
    if is_stage1:
        if manifest_path.resolve() != MANIFEST.resolve():
            raise StageError("The 100-task mode accepts only the frozen Stage 1 manifest")
        if manifest.get("evidence_class") != "exposed_development_sample_not_blind_holdout":
            raise StageError("Stage evidence class changed")
        if manifest.get("parent_manifest") != PARENT.relative_to(ROOT).as_posix():
            raise StageError("Unexpected parent manifest reference")
        if manifest.get("historical_sample_manifest") != HISTORICAL.relative_to(ROOT).as_posix():
            raise StageError("Unexpected historical sample reference")
        parent = json.loads(PARENT.read_text(encoding="utf-8"))
        historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))
        if file_sha256(PARENT) != manifest.get("parent_manifest_sha256"):
            raise StageError("Parent manifest hash mismatch")
        if file_sha256(HISTORICAL) != manifest.get("historical_sample_manifest_sha256"):
            raise StageError("Historical sample manifest hash mismatch")
        if parent.get("schema_version") != 1 or len(parent.get("cases", [])) != 344:
            raise StageError("Parent manifest is not the reviewed 344-case artifact")
        ids = manifest.get("selection", {}).get("ids")
        if (not isinstance(ids, list) or len(ids) != 100 or len(set(ids)) != 100
                or manifest.get("selection", {}).get("selected_count") != 100):
            raise StageError("Stage manifest must select exactly 100 distinct IDs")
        parent_ids = {case.get("id") for case in parent["cases"]}
        historical_ids = {case.get("id") for case in historical.get("cases", [])}
        if not set(ids) <= parent_ids or set(ids) != historical_ids:
            raise StageError("Stage IDs do not equal the historical sample within parent cohort")
        if len(manifest.get("cases", [])) != 100:
            raise StageError("Stage case metadata count is not 100")
        by_id = {case.get("id"): case for case in manifest["cases"]}
        if set(by_id) != set(ids):
            raise StageError("Stage case metadata does not match selected ID set")
    else:
        if manifest_path.resolve() not in {MANIFEST_344.resolve(), MANIFEST_344_LIVE_ROUTE.resolve(), MANIFEST_344_CURRENT.resolve()}:
            raise StageError("The 344-task mode accepts only a reviewed frozen primary manifest")
        ids = [case.get("id") for case in manifest.get("cases", [])]
        if len(ids) != 344 or len(set(ids)) != 344:
            raise StageError("Primary manifest must contain exactly 344 distinct cases")
        if len(manifest.get("jobs", [])) != 2064:
            raise StageError("Primary manifest must contain exactly 2,064 frozen jobs")
        if manifest_path.resolve() == MANIFEST_344_CURRENT.resolve():
            refresh = manifest.get("cohort_refresh", {})
            parent_path = safe_repo_path(refresh.get("parent_manifest_path", ""))
            parent = json.loads(parent_path.read_text(encoding="utf-8"))
            parent_ids = {case.get("id") for case in parent.get("cases", [])}
            if (parent_path.resolve() != MANIFEST_344_LIVE_ROUTE.resolve()
                    or file_sha256(parent_path) != MANIFEST_SHA256_344_LIVE_ROUTE
                    or refresh.get("parent_manifest_sha256") != MANIFEST_SHA256_344_LIVE_ROUTE
                    or set(ids) != parent_ids
                    or refresh.get("answer_labels_read_after_id_set_frozen") is not True):
                raise StageError("Current-source refresh does not preserve the reviewed answer-blind parent cohort")
    if manifest.get("dataset", {}).get("revision") != DATASET_REVISION:
        raise StageError("Dataset revision mismatch")
    dataset_digest = manifest["dataset"].get("sha256") or manifest["dataset"].get("data_file_sha256")
    if dataset_digest != DATASET_SHA256:
        raise StageError("Dataset digest in manifest mismatch")
    if file_sha256(dataset) != DATASET_SHA256:
        raise StageError("Local dataset digest mismatch")
    sources = manifest.get("source_hashes", {})
    parent_sources = parent.get("source_hashes", {}) if is_stage1 else sources
    required = {
        "builder": ROOT / "benchmarks/prepare_longbench_v2_minimax_344.py",
        "spec": ROOT / "docs/evals/longbench-v2-minimax-paired-study-spec-2026-10-17.md",
        "sift_core": ROOT / "src/sift/core.py",
        "sift_package_init": ROOT / "src/sift/__init__.py",
        "prompt_builder": ROOT / "benchmarks/prepare_longbench_v2.py",
        "renderer": ROOT / "benchmarks/prepare_longbench_v2_minimax.py",
    }
    for key, path in required.items():
        if not path.is_file():
            raise StageError(f"Missing frozen source for {key}: {path}")
        actual = file_sha256(path)
        if actual != sources.get(key) or actual != parent_sources.get(key):
            raise StageError(f"Frozen source hash mismatch: {key}")
    if file_sha256(tokenizer_path) != manifest["source_hashes"].get("tokenizer"):
        raise StageError("Tokenizer hash mismatch")
    if file_sha256(template_path) != manifest["source_hashes"].get("chat_template"):
        raise StageError("Chat template hash mismatch")
    if file_sha256(dataset) != manifest["source_hashes"].get("dataset"):
        raise StageError("Dataset source hash mismatch")
    route = manifest.get("route_assumptions", {})
    route_path = safe_repo_path(route.get("snapshot_path", ""))
    expected_route_path = (
        ROUTE_SNAPSHOT_CURRENT if resolved_manifest == MANIFEST_344_CURRENT.resolve()
        else ROUTE_SNAPSHOT_LIVE if resolved_manifest == MANIFEST_344_LIVE_ROUTE.resolve()
        else ROUTE_SNAPSHOT_HISTORICAL
    )
    if (route_path.resolve() != expected_route_path.resolve()
            or file_sha256(route_path) != route.get("snapshot_sha256")):
        raise StageError("Dated route snapshot provenance mismatch")
    if (route.get("requested_model") != MODEL or route.get("provider", "").casefold() != "minimax"
            or route.get("authorizes_dispatch") is not False):
        raise StageError("Route assumptions must identify MiniMax and explicitly deny dispatch authorization")
    route_snapshot = json.loads(route_path.read_text(encoding="utf-8"))
    snapshot_model = route_snapshot.get("model_id", route_snapshot.get("endpoint_model_id"))
    if snapshot_model is not None and snapshot_model != route.get("endpoint_model_id"):
        # The legacy endpoint snapshot distinguishes the requested model alias
        # from its provider_endpoint string; the refreshed snapshot has a model_id.
        provider_endpoint = route_snapshot.get("provider_endpoint", "")
        if route.get("endpoint_model_id") not in provider_endpoint:
            raise StageError("Route endpoint ID does not match its hashed snapshot")
    if route_snapshot.get("requested_model") != MODEL:
        raise StageError("Route snapshot requested model does not match the frozen request model")
    snapshot_provider = route_snapshot.get("provider_name", route_snapshot.get("provider", ""))
    if "minimax" not in str(snapshot_provider).casefold():
        raise StageError("Route snapshot is not a MiniMax provider endpoint")
    expected_tag = route.get("route_tag")
    snapshot_tag = route_snapshot.get("tag", route_snapshot.get("endpoint_tag"))
    if expected_tag and snapshot_tag not in {expected_tag, expected_tag.rsplit("/", 1)[-1]}:
        raise StageError("Route provider tag does not match its hashed snapshot")
    snapshot_pricing = route_snapshot.get("pricing")
    snapshot_prompt = (snapshot_pricing or {}).get("prompt")
    snapshot_completion = (snapshot_pricing or {}).get("completion")
    if snapshot_prompt is None or snapshot_completion is None:
        snapshot_pricing = route_snapshot.get("pricing_usd_per_token", {})
        snapshot_prompt = snapshot_pricing.get("prompt")
        snapshot_completion = snapshot_pricing.get("completion")
        price_scale = 1_000_000
    else:
        price_scale = 1_000_000
    try:
        if (not math.isclose(float(snapshot_prompt) * price_scale, float(route["input_usd_per_million"]), rel_tol=0, abs_tol=1e-9)
                or not math.isclose(float(snapshot_completion) * price_scale, float(route["output_usd_per_million"]), rel_tol=0, abs_tol=1e-9)):
            raise StageError("Route snapshot prices do not match frozen reserve assumptions")
    except (TypeError, ValueError, KeyError) as error:
        raise StageError("Route snapshot prices are missing or malformed") from error
    protocol = manifest.get("protocol", {})
    expected = {
        "study_seed": STUDY_SEED, "arms": ["full", "sift"],
        "repeats_per_arm": REPEATS, "temperature": 0.1, "top_p": 0.8,
        "reasoning": {"enabled": False},
        "max_tokens": OUTPUT_CAP, "stream": True,
        "stream_options": {"include_usage": True},
        "provider": {"only": ["minimax"], "allow_fallbacks": False},
        "requested_model": MODEL,
    }
    if is_stage1:
        expected["planned_requests"] = 600
    for key, value in expected.items():
        if protocol.get(key) != value:
            raise StageError(f"Frozen protocol mismatch: {key}")
    target = manifest.get("sift", {}).get("configured_target_tokens")
    if target is None:
        target = manifest.get("sift", {}).get("target_tokens")
    if target != TARGET:
        raise StageError("Sift target mismatch")
    return mode, {"ids": ids}


def count_prompt(tokenizer: Tokenizer, messages: list[dict[str, str]]) -> int:
    return len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)


def build_jobs(manifest: dict, mode: str, dataset: Path, tokenizer_path: Path) -> tuple[list[dict], dict]:
    ids = manifest["selection"]["ids"] if mode == "stage1_100" else [case["id"] for case in manifest["cases"]]
    selected = set(ids)
    fields = {"_id", "context", "question", "choice_A", "choice_B", "choice_C", "choice_D", "answer"}
    rows: dict[str, dict] = {}
    for row in iter_selected_dataset_rows(dataset, selected, fields):
        case_id = str(row.get("_id", ""))
        if case_id in rows:
            raise StageError(f"Duplicate dataset ID: {case_id}")
        rows[case_id] = row
    if set(rows) != selected:
        raise StageError("Pinned dataset does not contain the exact selected ID set")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    metadata = {case["id"]: case for case in manifest["cases"]}
    cases = []
    for case_index, case_id in enumerate(ids, start=1):
        row, frozen = rows[case_id], metadata[case_id]
        if (row.get("answer") != frozen.get("answer_key")
                or not isinstance(row.get("answer"), str)
                or row["answer"] not in {"A", "B", "C", "D"}):
            raise StageError(f"Answer key mismatch: {case_id}")
        messages = make_messages(row)
        source_prompt_hash = frozen.get("source_prompt_sha256", frozen.get("full_prompt_sha256"))
        insertion_order_prompt_hash = prompt_sha256(messages)
        # The reviewed 344 artifact predates this adapter and froze sorted-key
        # hashes. Validate that legacy representation only for provenance;
        # all newly emitted prompt hashes use the original insertion-order function.
        legacy_frozen_hash = canonical_hash(messages)
        if source_prompt_hash not in {insertion_order_prompt_hash, legacy_frozen_hash}:
            raise StageError(f"Source prompt hash mismatch: {case_id}")
        full_count = count_prompt(tokenizer, messages)
        frozen_full_count = frozen.get("full_local_prompt_tokens", frozen.get("full_local_tokens"))
        frozen_sift_count = frozen.get("sift_local_prompt_tokens", frozen.get("sift_local_tokens"))
        if full_count != frozen_full_count:
            raise StageError(f"Full prompt token count mismatch: {case_id}")
        def count_candidate(candidate: list[dict[str, str]]) -> int:
            # compact_messages performs its own initial count. Reuse the exact
            # count already used to validate this unchanged message list.
            if candidate is messages:
                return full_count
            return count_prompt(tokenizer, candidate)
        sift_started = time.perf_counter()
        try:
            compacted = compact_messages(messages, count_candidate,
                                         target=TARGET - SAFETY_MARGIN, raw_limit=1_000_000,
                                         protocol="openai")
        except CompactionError as error:
            raise StageError(f"Current Sift failed closed for selected case {case_id}: {error.code}") from error
        sift_preprocessing_ms = (time.perf_counter() - sift_started) * 1000
        sift_messages = compacted.messages
        sift_count = compacted.audit.get("forwarded_tokens")
        if type(sift_count) is not int or sift_count < 0:
            raise StageError(f"Sift did not return a valid forwarded-token count for {case_id}")
        if sift_count != frozen_sift_count:
            raise StageError(f"Sift prompt token count mismatch: {case_id}")
        sift_hash = frozen.get("sift_prompt_sha256")
        sift_prompt_ordered_hash = prompt_sha256(sift_messages)
        if sift_hash not in {sift_prompt_ordered_hash, canonical_hash(sift_messages)}:
            raise StageError(f"Sift prompt hash mismatch: {case_id}")
        cases.append({"id": case_id, "answer": row["answer"],
                      "domain": frozen.get("domain", row.get("domain")),
                      "sub_domain": frozen.get("sub_domain", row.get("sub_domain")),
                      "messages": {"full": messages, "sift": sift_messages},
                      "prompt_hashes": {"full": insertion_order_prompt_hash, "sift": sift_prompt_ordered_hash},
                      "counts": {"full": full_count, "sift": sift_count},
                      "sift_preprocessing_ms": sift_preprocessing_ms, "frozen": frozen})
        if case_index % 25 == 0 or case_index == len(ids):
            print(f"Reconstructed prompts: {case_index}/{len(ids)} tasks", flush=True)
    rng = random.Random(STUDY_SEED)
    jobs: list[dict] = []
    for case in cases:
        block = []
        for arm in ("full", "sift"):
            for repeat in range(REPEATS):
                body = {
                    "model": MODEL, "messages": case["messages"][arm], "temperature": 0.1,
                    "top_p": 0.8, "seed": STUDY_SEED + repeat + 1,
                    "max_tokens": OUTPUT_CAP, "reasoning": {"enabled": False},
                    "stream": True, "stream_options": {"include_usage": True},
                    "provider": {"only": ["minimax"], "allow_fallbacks": False},
                }
                block.append({"case_id": case["id"], "arm": arm, "repeat": repeat,
                              "seed": body["seed"], "body": body,
                              "body_sha256": canonical_hash(body),
                              "prompt_sha256": case["prompt_hashes"][arm],
                              "domain": case["domain"], "sub_domain": case["sub_domain"],
                              "local_prompt_tokens": case["counts"][arm],
                              "local_cost_estimate_usd": (
                                  case["counts"][arm] * INPUT_FACTOR * INPUT_PRICE
                                  + OUTPUT_CAP * OUTPUT_PRICE
                              ) / 1_000_000,
                              "projected_provider_prompt_tokens": math.ceil(case["counts"][arm] * PROJECTION),
                              "sift_preprocessing_ms": case["sift_preprocessing_ms"] if arm == "sift" else None,
                              "expected": case["answer"]})
        rng.shuffle(block)
        jobs.extend(block)
    if mode == "primary_344":
        frozen_jobs = manifest["jobs"]
        frozen_by_key = {(job.get("case_id"), job.get("arm"), job.get("repeat")): job for job in frozen_jobs}
        if len(frozen_by_key) != 2064 or len(frozen_jobs) != 2064:
            raise StageError("Frozen 344 job identities are not unique")
        expected_schedule_hash = manifest.get("cohort_summary", {}).get("schedule_sha256")
        if canonical_hash(frozen_jobs) != expected_schedule_hash:
            raise StageError("Frozen 344 schedule hash does not match its manifest commitment")
        generated_by_key = {(job["case_id"], job["arm"], job["repeat"]): job for job in jobs}
        if set(generated_by_key) != set(frozen_by_key):
            raise StageError("Reconstructed 344 job identities differ from the frozen schedule")
        for key, job in generated_by_key.items():
            frozen = frozen_by_key[key]
            if (job["body_sha256"] != frozen.get("canonical_request_body_sha256")
                    or job["seed"] != frozen.get("matched_seed_parameter")
                    or job["projected_provider_prompt_tokens"] != frozen.get("projected_provider_prompt_count")):
                raise StageError(f"Reconstructed request differs from frozen 344 job: {key}")
        # Use the frozen manifest order exactly; list order is part of the reviewed schedule.
        order = {(job["case_id"], job["arm"], job["repeat"]): index for index, job in enumerate(frozen_jobs)}
        jobs.sort(key=lambda job: order[(job["case_id"], job["arm"], job["repeat"])])
    keys = [(job["case_id"], job["arm"], job["repeat"]) for job in jobs]
    counts = Counter(job["arm"] for job in jobs)
    expected_n = 600 if mode == "stage1_100" else 2064
    per_arm = expected_n // 2
    if len(keys) != expected_n or len(set(keys)) != expected_n or counts != {"full": per_arm, "sift": per_arm}:
        raise StageError("Generated job schedule is incomplete or nonunique")
    if any(job["projected_provider_prompt_tokens"] > PROVIDER_LIMIT for job in jobs):
        raise StageError("Projected prompt exceeds dated provider limit")
    return jobs, {case["id"]: case for case in cases}


def cost_receipt(usage: Any) -> tuple[float | None, str]:
    if not isinstance(usage, dict) or usage.get("is_byok") is not True:
        return None, "missing_or_non_byok_usage"
    details = usage.get("cost_details")
    upstream = details.get("upstream_inference_cost") if isinstance(details, dict) else None
    direct = usage.get("cost")
    nums = [value for value in (upstream, direct) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and value >= 0]
    if (upstream is None or not isinstance(upstream, (int, float)) or isinstance(upstream, bool)
            or not math.isfinite(float(upstream)) or upstream <= 0):
        return None, "missing_upstream_cost"
    if direct is not None and (not isinstance(direct, (int, float)) or isinstance(direct, bool)
                               or not math.isfinite(float(direct)) or direct < 0):
        return None, "invalid_openrouter_cost"
    return max(nums), "upstream_and_openrouter" if direct is not None else "upstream"


def recorded_unknown_outcome_reserve(report_path: Path, input_price: float = INPUT_PRICE,
                                     output_price: float = OUTPUT_PRICE) -> dict:
    """Reserve one full-route maximum for every exact unreceipted attempt row."""
    if not report_path.is_file():
        raise StageError("Unknown outcomes require the exact recorded private run artifact")
    digest = file_sha256(report_path)
    if digest not in {UNKNOWN_503_REPORT_SHA256, UNKNOWN_600_REPORT_SHA256,
                      UNKNOWN_344_REPORT_SHA256}:
        raise StageError("Unknown outcomes require a pinned report SHA-256")
    try:
        prior = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise StageError(f"Recorded unknown-outcome artifact is unreadable: {error}") from error
    if digest == UNKNOWN_503_REPORT_SHA256:
        expected_ids = UNKNOWN_503_JOB_IDS
        unknown_ids = prior.get("unknown_outcome_job_ids")
        if (prior.get("status") != "prefix_incomplete" or not isinstance(unknown_ids, list)
                or set(unknown_ids) != expected_ids or len(unknown_ids) != len(expected_ids)):
            raise StageError("Recorded unknown-outcome artifact differs from the reviewed 503-run ledger")
        schedule_rows = {row.get("job_id"): row for row in prior.get("schedule", [])
                         if isinstance(row, dict) and isinstance(row.get("job_id"), str)}
        samples = [row for row in prior.get("samples", []) if isinstance(row, dict)]
        for job_id in expected_ids:
            frozen = schedule_rows.get(job_id)
            attempts = [row for row in samples if row.get("job_id") == job_id]
            if (not isinstance(frozen, dict) or frozen.get("arm") != "full"
                    or type(frozen.get("local_prompt_tokens")) is not int
                    or frozen["local_prompt_tokens"] <= 0
                    or not any(row.get("usage") is None and row.get("failure") for row in attempts)):
                raise StageError(f"503 unknown outcome lacks its frozen unreceipted request record: {job_id}")
        expected_attempts = UNKNOWN_503_UNRECEIPTED_ATTEMPTS
    elif digest == UNKNOWN_600_REPORT_SHA256:
        if (prior.get("status") != "complete" or prior.get("full_schedule_complete") is not True
                or prior.get("full_schedule_jobs") != 600
                or prior.get("dispatch_prefix_count") != 600
                or prior.get("attempted_jobs") != 605 or prior.get("completed_jobs") != 600
                or prior.get("in_flight") is not None):
            raise StageError("Recorded unknown-outcome artifact differs from the reviewed 600-run ledger")
        samples = [row for row in prior.get("samples", []) if isinstance(row, dict)]
        expected_attempts = UNKNOWN_600_UNRECEIPTED_ATTEMPTS
    else:
        expected_ids = UNKNOWN_344_JOB_IDS
        in_flight = prior.get("in_flight")
        job_id = next(iter(expected_ids))
        sample = next((row for row in prior.get("samples", [])
                       if isinstance(row, dict) and row.get("job_id") == job_id), None)
        if (prior.get("status") != "safety_guard_stopped"
                or prior.get("manifest_sha256") != UNKNOWN_344_MANIFEST_SHA256
                or prior.get("stop_reason") != "missing_or_invalid_cost_receipt:missing_or_non_byok_usage"
                or prior.get("completed_jobs") != 542
                or not isinstance(in_flight, dict)
                or in_flight.get("job_id") != job_id
                or in_flight.get("state") != "unknown_outcome_requires_external_reconciliation"
                or not isinstance(sample, dict)
                or sample.get("http_status") != 529
                or sample.get("usage") is not None
                or sample.get("provider_reported_cost_usd") is not None
                or sample.get("failure") != "http_status_not_200"):
            raise StageError("Recorded 344-run artifact differs from the reviewed unreceipted 529 outcome")
        samples = [sample]
        expected_attempts = {(job_id, None, 529)}
    actual_attempt_rows = []
    for row in samples:
        # A response without both a provider response ID and usage receipt cannot
        # settle the upstream charge. Preserve even explicit 4xx attempts.
        if not row.get("response_id") or row.get("usage") is None:
            actual_attempt_rows.append((row.get("job_id"), row.get("attempt_number"), row.get("http_status")))
    actual_attempts = set(actual_attempt_rows)
    if len(actual_attempt_rows) != len(expected_attempts) or actual_attempts != expected_attempts:
        raise StageError("Pinned report unreceipted attempt rows differ from the reviewed ledger")
    per_attempt = {}
    per_attempt_reserve = (PROVIDER_LIMIT * input_price + OUTPUT_CAP * output_price) / 1_000_000
    for job_id, attempt_number, http_status in sorted(expected_attempts, key=str):
        key = f"{job_id}#attempt={attempt_number if attempt_number is not None else 'unknown'}"
        if key in per_attempt:
            raise StageError("Pinned report contains duplicate unreceipted attempt identities")
        per_attempt[key] = per_attempt_reserve
    source_jobs = sorted({row[0] for row in expected_attempts})
    return {
        "source_report_path": str(report_path.resolve()),
        "source_report_sha256": digest,
        "source_unknown_job_ids": source_jobs,
        "source_unreceipted_attempts": [
            {"job_id": job_id, "attempt_number": attempt_number, "http_status": http_status}
            for job_id, attempt_number, http_status in sorted(expected_attempts, key=str)
        ],
        "reserve_method": "one full current-provider prompt limit plus 64 output tokens per unreceipted attempt",
        "per_attempt_reserves_usd": per_attempt,
        "total_reserve_usd": sum(per_attempt.values()),
    }


def validate_stopped_344_continuation(report_path: Path, jobs: list[dict]) -> tuple[list[dict], float]:
    """Return only unattempted frozen jobs from the exact stopped 344 report.

    The 529 request is deliberately excluded and preserved as an unknown outcome.
    The function validates the complete schedule and every already-attempted row
    before permitting an offline continuation plan to be built.
    """
    if not report_path.is_file() or file_sha256(report_path) != UNKNOWN_344_REPORT_SHA256:
        raise StageError("Continuation requires the exact pinned private 344-run report")
    try:
        prior = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise StageError(f"Stopped 344-run report is unreadable: {error}") from error
    expected_unknown_id = next(iter(UNKNOWN_344_JOB_IDS))
    schedule = prior.get("schedule")
    samples = prior.get("samples")
    in_flight = prior.get("in_flight")
    if (prior.get("status") != "safety_guard_stopped"
            or prior.get("manifest_sha256") != UNKNOWN_344_MANIFEST_SHA256
            or prior.get("stop_reason") != "missing_or_invalid_cost_receipt:missing_or_non_byok_usage"
            or prior.get("completed_jobs") != 542
            or prior.get("planned_jobs") != 2064
            or not isinstance(schedule, list) or len(schedule) != 2064
            or prior.get("schedule_sha256") != canonical_hash(schedule)
            or not isinstance(samples, list) or len(samples) != 542
            or not isinstance(in_flight, dict)
            or in_flight.get("index") != 541
            or in_flight.get("job_id") != expected_unknown_id
            or in_flight.get("state") != "unknown_outcome_requires_external_reconciliation"):
        raise StageError("Stopped report is not the expected intact 344-task checkpoint")
    if len(jobs) != 2064:
        raise StageError("Reconstructed frozen schedule does not contain all 2,064 jobs")
    expected_by_key = {
        (job["case_id"], job["arm"], job["repeat"]): job for job in jobs
    }
    if len(expected_by_key) != 2064:
        raise StageError("Reconstructed schedule has duplicate job identities")
    for index, row in enumerate(schedule):
        if not isinstance(row, dict) or row.get("index") != index:
            raise StageError("Stopped report schedule index/order is invalid")
        key = (row.get("case_id"), row.get("arm"), row.get("repeat"))
        job = expected_by_key.get(key)
        ordered_job = jobs[index]
        ordered_key = (ordered_job["case_id"], ordered_job["arm"], ordered_job["repeat"])
        if (job is None or key != ordered_key or row.get("body_sha256") != job["body_sha256"]
                or row.get("prompt_sha256") != job["prompt_sha256"]
                or row.get("seed") != job["seed"]
                or row.get("local_prompt_tokens") != job["local_prompt_tokens"]):
            raise StageError(f"Stopped report schedule differs from reconstructed frozen job {index}")
    receipt_total = 0.0
    seen = set()
    for index, sample in enumerate(samples):
        row = schedule[index]
        job_id = f'{row["case_id"]}:{row["arm"]}:{row["repeat"]}'
        if (not isinstance(sample, dict) or sample.get("job_id") != job_id
                or sample.get("request_body_sha256") != row["body_sha256"]
                or job_id in seen):
            raise StageError(f"Stopped report sample does not match frozen schedule position {index}")
        seen.add(job_id)
        if index == 541:
            if (job_id != expected_unknown_id or sample.get("http_status") != 529
                    or sample.get("usage") is not None
                    or sample.get("provider_reported_cost_usd") is not None):
                raise StageError("The final attempted 344 job is not the pinned unreceipted 529")
            continue
        if index > 541:
            raise StageError("Stopped report contains samples beyond its 542-request prefix")
        actual, _ = cost_receipt(sample.get("usage"))
        recorded = sample.get("provider_reported_cost_usd")
        if (sample.get("http_status") != 200 or actual is None
                or sample.get("returned_model") != MODEL
                or str(sample.get("provider", "")).casefold() != "minimax"
                or sample.get("sse_done_received") is not True
                or sample.get("failure") is not None
                or not isinstance(recorded, (int, float)) or isinstance(recorded, bool)
                or not math.isclose(actual, float(recorded), rel_tol=0, abs_tol=1e-12)):
            raise StageError(f"Prior response lacks a valid provider receipt at schedule position {index}")
        receipt_total += actual
    if not math.isclose(receipt_total, float(prior.get("settled_actual_cost_usd", -1)),
                        rel_tol=0, abs_tol=1e-8):
        raise StageError("Prior settled-cost total differs from its provider receipts")
    return jobs[542:], receipt_total


def claim_single_use_continuation(source_path: Path, output_path: Path, spend_cap_usd: float,
                                  claim_path: Path = CONTINUATION_CLAIM) -> None:
    """Atomically consume the one allowed continuation of the pinned checkpoint."""
    if output_path.resolve() != CONTINUATION_OUTPUT.resolve():
        raise StageError(f"Continuation output must use the single-use path: {CONTINUATION_OUTPUT}")
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim = {
        "source_report_sha256": UNKNOWN_344_REPORT_SHA256,
        "source_report_path": str(source_path.resolve()),
        "output_path": str(output_path.resolve()),
        "spend_cap_usd": spend_cap_usd,
        "claimed_utc": datetime.now(timezone.utc).isoformat(),
        "semantics": "single-use; never delete or reuse after any dispatch attempt",
    }
    try:
        with claim_path.open("x", encoding="utf-8") as handle:
            json.dump(claim, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise StageError("The one allowed continuation has already been claimed; do not replay the suffix") from error


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def live_account_route_preflight(api_key: str, manifest: dict, cap: float,
                                 jobs: list[dict], no_unsettled_attested: bool,
                                 provider_billing_attested: bool,
                                 provider_billing_authorized_unverified: bool = False,
                                 prior_unknown_outcome_explicitly_accepted: bool = False,
                                 prior_unknown_outcome_reserve_usd: float = 0.0) -> dict:
    """Refresh MiniMax route metadata and require operator-settlement attestations.

    OpenRouter credits are diagnostics only for BYOK inference, which is billed
    by the upstream MiniMax account. This preflight cannot verify that account's
    actual balance or impose a provider-side hard spend cap.
    """
    if not no_unsettled_attested:
        raise StageError("Explicitly attest that no additional unresolved requests exist outside the three pinned reports and no dispatch is active")
    if not prior_unknown_outcome_explicitly_accepted:
        raise StageError("This study has known unresolved provider outcomes; accept and reserve their exact recorded reports")
    if (not math.isfinite(prior_unknown_outcome_reserve_usd)
            or prior_unknown_outcome_reserve_usd < 0
            or prior_unknown_outcome_reserve_usd <= 0):
        raise StageError("Known unknown-outcome reserves must be finite, positive, and explicitly accepted")
    if not provider_billing_attested and not provider_billing_authorized_unverified:
        raise StageError("Confirm MiniMax-side billing headroom, or explicitly record user-authorized spend with provider balance unverified")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    endpoint_url = "https://openrouter.ai/api/v1/models/minimax/minimax-m3/endpoints"
    try:
        endpoint_response = requests.get(endpoint_url, headers=headers, timeout=(10, 30))
        credits_response = requests.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=(10, 30))
        key_response = requests.get("https://openrouter.ai/api/v1/key", headers=headers, timeout=(10, 30))
        endpoint_response.raise_for_status()
        credits_response.raise_for_status()
        key_response.raise_for_status()
        endpoint_data = endpoint_response.json().get("data", {})
        endpoints = endpoint_data.get("endpoints", [])
        credit_data = credits_response.json().get("data", {})
        key_data = key_response.json().get("data", {})
    except Exception as error:
        raise StageError(f"Live OpenRouter account/route preflight failed closed: {type(error).__name__}: {error}") from error
    if not isinstance(credit_data, dict) or not isinstance(key_data, dict):
        raise StageError("OpenRouter credits/key diagnostics returned malformed metadata")
    if (type(key_data.get("is_management_key")) is not bool
            or type(key_data.get("include_byok_in_limit")) is not bool):
        raise StageError("OpenRouter key diagnostics lack BYOK accounting metadata")
    if key_data["is_management_key"] is not False:
        raise StageError("Use an OpenRouter inference key for preflight and dispatch")
    if key_data["include_byok_in_limit"] is not False:
        raise StageError("OpenRouter BYOK limit semantics changed; re-evaluate account and cap handling")
    candidates = [endpoint for endpoint in endpoints if isinstance(endpoint, dict)
                  and str(endpoint.get("provider_name", "")).strip().casefold() == "minimax"]
    if not candidates:
        raise StageError("Live OpenRouter endpoint list has no MiniMax provider route")
    expected_endpoint_id = manifest.get("route_assumptions", {}).get("endpoint_model_id")
    exact = [endpoint for endpoint in candidates
             if endpoint.get("model_id") == expected_endpoint_id
             and endpoint.get("tag") == manifest.get("route_assumptions", {}).get("route_tag")]
    if len(exact) != 1:
        raise StageError("Live MiniMax route is missing or ambiguous versus the frozen endpoint model ID")
    endpoint = exact[0]
    max_prompt_tokens = endpoint.get("max_prompt_tokens")
    max_completion_tokens = endpoint.get("max_completion_tokens")
    if (type(max_prompt_tokens) is not int or max_prompt_tokens <= 0
            or type(max_completion_tokens) is not int or max_completion_tokens <= 0):
        raise StageError("Live MiniMax endpoint lacks explicit prompt and completion limits; refusing dispatch")
    required_prompt = max(job["projected_provider_prompt_tokens"] for job in jobs)
    if required_prompt > max_prompt_tokens or OUTPUT_CAP > max_completion_tokens:
        raise StageError("Frozen Stage schedule exceeds live MiniMax prompt/completion limits")
    pricing = endpoint.get("pricing")
    if not isinstance(pricing, dict):
        raise StageError("Live MiniMax route omitted pricing")
    try:
        input_rate = float(pricing["prompt"])
        output_rate = float(pricing["completion"])
    except (KeyError, TypeError, ValueError) as error:
        raise StageError("Live MiniMax route pricing is malformed") from error
    if not (math.isfinite(input_rate) and math.isfinite(output_rate) and input_rate > 0 and output_rate > 0):
        raise StageError("Live MiniMax route pricing is invalid")
    cache_rate = pricing.get("cache_read")
    if cache_rate is not None:
        try:
            cache_rate = float(cache_rate)
        except (TypeError, ValueError) as error:
            raise StageError("Live MiniMax cache-read pricing is malformed") from error
        if not math.isfinite(cache_rate) or cache_rate < 0:
            raise StageError("Live MiniMax cache-read pricing is invalid")
    # Validate only that a credits diagnostics response arrived. It is not the
    # settlement source for MiniMax BYOK, and its exact values stay out of logs.
    return {"checked_utc": datetime.now(timezone.utc).isoformat(),
            "endpoint_model_id": endpoint.get("model_id"), "provider": endpoint.get("provider_name"),
            "route_tag": endpoint.get("tag"),
            "input_usd_per_million": input_rate * 1_000_000,
            "output_usd_per_million": output_rate * 1_000_000,
            "cache_read_usd_per_million": cache_rate * 1_000_000 if cache_rate is not None else None,
            "max_prompt_tokens": max_prompt_tokens,
            "max_completion_tokens": max_completion_tokens,
            "openrouter_credits_endpoint_response": "ok; diagnostics only; excluded from BYOK cap coverage",
            "openrouter_key_metadata_check": "ok",
            "is_management_key": key_data["is_management_key"],
            "include_byok_in_limit": key_data["include_byok_in_limit"],
            "byok_usage_metadata_present": "byok_usage" in key_data,
            "provider_billing_headroom_attested": provider_billing_attested,
            "provider_billing_status": ("headroom_attested" if provider_billing_attested
                                        else "user_authorized_balance_unverified"),
            "approved_run_cap_usd": cap,
            "prior_unknown_outcome_reserve_usd": prior_unknown_outcome_reserve_usd,
            "prior_in_flight_reconciliation": (
                "explicit operator attestation; API does not prove all upstream settlements"
                if no_unsettled_attested else
                "recorded unknown outcome explicitly accepted; not externally reconciled"
                if prior_unknown_outcome_explicitly_accepted else "unverified"),
            "note": "Client-side spend guard only; a single upstream request may exceed its reservation before receipt settlement."}


def prepare_report(manifest_path: Path, manifest: dict, mode: str, jobs: list[dict], output: Path) -> dict:
    input_tokens = sum(job["local_prompt_tokens"] for job in jobs)
    estimated = (input_tokens * INPUT_FACTOR * INPUT_PRICE + len(jobs) * OUTPUT_CAP * OUTPUT_PRICE) / 1_000_000
    arm_counts = Counter(job["arm"] for job in jobs)
    schedule = [{"index": index, "case_id": job["case_id"], "arm": job["arm"], "repeat": job["repeat"],
                 "seed": job["seed"], "prompt_sha256": job["prompt_sha256"],
                 "body_sha256": job["body_sha256"],
                 "domain": job["domain"], "sub_domain": job["sub_domain"],
                 "local_prompt_tokens": job["local_prompt_tokens"],
                 "local_cost_estimate_usd": job["local_cost_estimate_usd"],
                 "projected_provider_prompt_tokens": job["projected_provider_prompt_tokens"]}
                for index, job in enumerate(jobs)]
    source_hashes = manifest["source_hashes"]
    frozen_runner_hash = source_hashes.get("runner")
    report = {
        "schema_version": 1, "status": "prepared_only_no_dispatch", "actual_dispatch_started": False,
        "dispatch_authorized_by_manifest": False,
        "evidence_class": manifest.get("evidence_class", "reviewed_primary_344_cohort"),
        "manifest_sha256": file_sha256(manifest_path),
        "parent_manifest_sha256": manifest.get("parent_manifest_sha256"),
        "historical_sample_manifest_sha256": manifest.get("historical_sample_manifest_sha256"),
        "execution_runner_sha256": file_sha256(Path(__file__).resolve()),
        "frozen_source_runner_sha256": frozen_runner_hash,
        "runner_hash_semantics": "frozen_source_runner_sha256 records the legacy runner used when the parent cohort was prepared; execution_runner_sha256 records this adapter. They are not interchangeable.",
        "prepared_utc": datetime.now(timezone.utc).isoformat(),
        "cohort": mode, "planned_jobs": len(jobs),
        "arm_counts": dict(arm_counts),
        "source_hashes": source_hashes,
        "protocol": manifest["protocol"], "schedule": schedule,
        "schedule_sha256": canonical_hash(schedule),
        "budget_estimate": {"local_input_tokens": input_tokens, "input_reserve_factor": INPUT_FACTOR,
                            "dated_input_usd_per_million": INPUT_PRICE,
                            "dated_output_usd_per_million": OUTPUT_PRICE,
                            "max_output_tokens": len(jobs) * OUTPUT_CAP,
                            "estimated_reserve_usd": estimated,
                            "is_live_quote_or_authorization": False},
        "request_and_answer_text_excluded": True,
    }
    return report


def dispatch(jobs: list[dict], cases: dict, report: dict, output: Path,
             cap: float, api_key: str, live_route: dict,
             prior_unknown_outcome_reserve_usd: float = 0.0,
             prior_settled_cost_usd: float = 0.0,
             process_started_perf: float | None = None,
             process_started_utc: str | None = None) -> dict:
    input_price = live_route["input_usd_per_million"]
    output_price = live_route["output_usd_per_million"]
    if input_price != INPUT_PRICE or output_price != OUTPUT_PRICE:
        raise StageError("Live price differs from frozen reserve rates; prepare a refreshed reviewed plan before dispatch")
    if (not math.isfinite(prior_settled_cost_usd) or prior_settled_cost_usd < 0
            or not math.isfinite(prior_unknown_outcome_reserve_usd)
            or prior_unknown_outcome_reserve_usd < 0):
        raise StageError("Prior settled cost and unknown-outcome reserve must be finite and nonnegative")
    estimate = report["budget_estimate"]["estimated_reserve_usd"]
    minimum_cap = estimate + prior_unknown_outcome_reserve_usd + prior_settled_cost_usd
    if not math.isfinite(cap) or cap <= 0 or cap < minimum_cap:
        raise StageError(f"Approved cap must be finite, positive, and at least the refreshed estimate plus prior reserve ${minimum_cap:.6f}")
    # No automatic retry/resume: an ambiguous request is written as in-flight and blocks later runs.
    report["status"] = "dispatching"
    report["actual_dispatch_started"] = True
    report["dispatch_spend_cap_usd"] = cap
    report["prior_unknown_outcome_reserve_usd"] = prior_unknown_outcome_reserve_usd
    report["prior_settled_cost_usd"] = prior_settled_cost_usd
    report["dispatch_started_utc"] = datetime.now(timezone.utc).isoformat()
    report["samples"] = []
    report["in_flight"] = None
    atomic_write(output, report)
    settled = 0.0
    started = time.perf_counter()
    for index, job in enumerate(jobs):
        reserve = (job["local_prompt_tokens"] * INPUT_FACTOR * input_price + OUTPUT_CAP * output_price) / 1_000_000
        if prior_unknown_outcome_reserve_usd + prior_settled_cost_usd + settled + reserve > cap:
            report["status"] = "budget_guard_stopped_before_request"
            report["stop_reason"] = "next_request_reservation_exceeds_approved_cap"
            break
        report["in_flight"] = {"index": index, "job_id": f'{job["case_id"]}:{job["arm"]}:{job["repeat"]}',
                               "reserved_cost_usd": reserve, "state": "request_started"}
        atomic_write(output, report)
        started_utc = datetime.now(timezone.utc).isoformat()
        request_started = time.perf_counter()
        first_content_at = None
        raw_events: list[str] = []
        fragments: list[str] = []
        usage = None
        returned_model = provider = response_id = finish_reason = None
        status = None
        failure = None
        sse_done_received = False
        try:
            with requests.post(API_URL, json=job["body"],
                               headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                               stream=True, timeout=(30, 600)) as response:
                status = response.status_code
                if status != 200:
                    raw_events.append(response.text)
                    failure = "http_status_not_200"
                else:
                    for line in response.iter_lines(decode_unicode=True):
                        if not line or not line.startswith("data:"):
                            continue
                        event = line[5:].strip()
                        raw_events.append(event)
                        if event == "[DONE]":
                            sse_done_received = True
                            break
                        chunk = json.loads(event)
                        usage = chunk.get("usage") if chunk.get("usage") is not None else usage
                        provider = chunk.get("provider") or provider
                        returned_model = chunk.get("model") or returned_model
                        response_id = chunk.get("id") or response_id
                        for choice in chunk.get("choices", []):
                            if choice.get("finish_reason") is not None:
                                finish_reason = choice["finish_reason"]
                            delta = choice.get("delta") or {}
                            if isinstance(delta.get("content"), str):
                                if delta["content"] and first_content_at is None:
                                    first_content_at = time.perf_counter()
                                fragments.append(delta["content"])
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
        if status == 200 and not sse_done_received and failure is None:
            failure = "missing_sse_done"
        text = "".join(fragments)
        request_finished = time.perf_counter()
        actual, receipt_source = cost_receipt(usage)
        ratio = None
        if isinstance(usage, dict) and type(usage.get("prompt_tokens")) is int and usage["prompt_tokens"] > 0:
            ratio = usage["prompt_tokens"] / job["local_prompt_tokens"]
        choice = text.strip()
        successful_response = (
            status == 200 and returned_model == MODEL and isinstance(provider, str)
            and provider.strip().casefold() == "minimax" and finish_reason == "stop"
            and failure is None and sse_done_received
        )
        sample = {
            "job_id": f'{job["case_id"]}:{job["arm"]}:{job["repeat"]}',
            "case_id": job["case_id"], "arm": job["arm"], "repeat": job["repeat"],
            "domain": job["domain"], "sub_domain": job["sub_domain"],
            "request_body_sha256": job["body_sha256"], "http_status": status,
            "requested_model": MODEL, "returned_model": returned_model, "provider": provider,
            "response_id": response_id, "usage": usage,
            "local_cost_estimate_usd": job["local_cost_estimate_usd"],
            "sift_preprocessing_ms": job.get("sift_preprocessing_ms"),
            "provider_reported_cost_usd": actual,
            "reserved_cost_usd": reserve,
            "cost_receipt_source": receipt_source, "local_prompt_tokens": job["local_prompt_tokens"],
            "provider_local_input_ratio": ratio, "answer": text, "choice": choice if choice in "ABCD" and len(choice) == 1 else None,
            "expected": job["expected"],
            "correct": successful_response and choice == job["expected"]
            if choice in "ABCD" and len(choice) == 1 else False,
            "finish_reason": finish_reason, "sse_done_received": sse_done_received,
            "failure": failure, "raw_sse_events": raw_events,
            "request_started_utc": started_utc, "response_completed_utc": datetime.now(timezone.utc).isoformat(),
            "ttft_ms": (first_content_at - request_started) * 1000 if first_content_at is not None else None,
            "total_request_wall_ms": (request_finished - request_started) * 1000,
        }
        report["samples"].append(sample)
        report["in_flight"] = None
        if actual is None:
            report["status"] = "safety_guard_stopped"
            report["stop_reason"] = f"missing_or_invalid_cost_receipt:{receipt_source}"
            report["in_flight"] = {
                "index": index, "job_id": sample["job_id"], "reserved_cost_usd": reserve,
                "state": "unknown_outcome_requires_external_reconciliation",
                "response_id": response_id,
            }
        else:
            settled += actual
            report["segment_settled_actual_cost_usd"] = settled
            report["settled_actual_cost_usd"] = prior_settled_cost_usd + settled
            valid_route = status == 200 and returned_model == MODEL and isinstance(provider, str) and provider.casefold() == "minimax"
            if not valid_route:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "model_or_provider_attribution_mismatch"
            elif ratio is None:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "missing_provider_prompt_usage"
            elif ratio > MAX_RATIO:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "provider_local_input_ratio_exceeded"
            elif not sse_done_received:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "missing_sse_done_terminal_event"
            elif actual > reserve:
                report["status"] = "budget_guard_overrun"
                report["stop_reason"] = "actual_request_cost_exceeded_its_reservation"
            elif prior_unknown_outcome_reserve_usd + prior_settled_cost_usd + settled > cap:
                report["status"] = "budget_guard_overrun"
                report["stop_reason"] = "actual_reported_cost_exceeded_cap"
            elif failure is not None or finish_reason not in {"stop", "length"}:
                report["status"] = "safety_guard_stopped"
                report["stop_reason"] = "request_failed_or_incomplete"
        atomic_write(output, report)
        if report.get("status") in {"safety_guard_stopped", "budget_guard_overrun"}:
            # Request was sequential; its response/usage is settled before stopping. Never resume automatically.
            break
    else:
        report["status"] = "complete"
    if report.get("status") == "complete":
        report["in_flight"] = None
    report["completed_jobs"] = len(report["samples"])
    report["elapsed_wall_seconds"] = time.perf_counter() - started
    if process_started_perf is not None:
        report["process_wall_seconds"] = time.perf_counter() - process_started_perf
    if process_started_utc is not None:
        report["process_started_utc"] = process_started_utc
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_write(output, report)
    return report


def main() -> int:
    process_started_perf = time.perf_counter()
    process_started_utc = datetime.now(timezone.utc).isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST,
                        help="Frozen Stage 1 100-task manifest or reviewed primary 344-task manifest.")
    parser.add_argument("--dataset", type=Path, default=DATASET_DEFAULT)
    parser.add_argument("--tokenizer", type=Path, default=TOKENIZER_DEFAULT)
    parser.add_argument("--template", type=Path, default=TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--prepare-only", action="store_true", help="Explicitly prepare offline; this is also the default mode.")
    parser.add_argument("--dispatch", action="store_true", help="Explicitly send paid MiniMax requests.")
    parser.add_argument("--spend-cap-usd", type=float, help="User-approved aggregate cap for this run; required with --dispatch.")
    parser.add_argument("--confirm-no-unsettled-requests", action="store_true",
                        help="Attest that no additional unresolved requests exist outside the three pinned reports and no dispatch is active; their reserves still apply.")
    parser.add_argument("--confirm-provider-billing-covers-cap", action="store_true",
                        help="Attest that MiniMax-side billing headroom covers the full approved BYOK spend cap.")
    parser.add_argument("--authorize-unverified-provider-billing", action="store_true",
                        help="Proceed under the explicit user spend cap when MiniMax-side balance is not observable; the cap remains client-side.")
    parser.add_argument("--accept-recorded-unknown-outcomes", action="store_true",
                        help="Explicitly accept previously recorded outcomes whose upstream usage cannot be reconciled.")
    parser.add_argument("--prior-unknown-outcome-report", type=Path, action="append",
                        help="Exact private report for a known unreceipted run (repeat once for each of the three pinned reports).")
    parser.add_argument("--continue-after-known-unknown-report", type=Path,
                        help="Continue only the unattempted suffix after validating the exact stopped 344-run report; the failed request is skipped permanently.")
    args = parser.parse_args()
    if args.dispatch != (args.spend_cap_usd is not None):
        raise StageError("Use --dispatch and --spend-cap-usd together; otherwise run offline")
    if args.confirm_no_unsettled_requests and not args.dispatch:
        raise StageError("--confirm-no-unsettled-requests is valid only with --dispatch")
    if args.confirm_provider_billing_covers_cap and not args.dispatch:
        raise StageError("--confirm-provider-billing-covers-cap is valid only with --dispatch")
    if args.authorize_unverified_provider_billing and not args.dispatch:
        raise StageError("--authorize-unverified-provider-billing is valid only with --dispatch")
    if args.accept_recorded_unknown_outcomes and not args.dispatch:
        raise StageError("--accept-recorded-unknown-outcomes is valid only with --dispatch")
    if args.prior_unknown_outcome_report and not args.dispatch:
        raise StageError("--prior-unknown-outcome-report is valid only with --dispatch")
    if args.continue_after_known_unknown_report and not args.dispatch:
        raise StageError("--continue-after-known-unknown-report is valid only with --dispatch")
    if args.continue_after_known_unknown_report:
        if args.output.resolve() != CONTINUATION_OUTPUT.resolve():
            raise StageError(f"Continuation output must use the single-use path: {CONTINUATION_OUTPUT}")
        if CONTINUATION_CLAIM.exists():
            raise StageError("The one allowed continuation has already been claimed; do not replay the suffix")
    api_key = None
    if args.dispatch:
        if args.confirm_provider_billing_covers_cap == args.authorize_unverified_provider_billing:
            raise StageError("Choose exactly one provider-billing attestation or explicit unverified-balance authorization")
        if (not args.confirm_no_unsettled_requests or not args.accept_recorded_unknown_outcomes
                or not args.prior_unknown_outcome_report):
            raise StageError("This study requires a no-additional-unknowns attestation and acceptance of all three exact reports")
        if len(args.prior_unknown_outcome_report) != 3:
            raise StageError("This study requires all three exact reports for its known unreceipted attempts")
        if not math.isfinite(args.spend_cap_usd) or args.spend_cap_usd <= 0:
            raise StageError("--spend-cap-usd must be finite and positive")
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise StageError("OPENROUTER_API_KEY is required for dispatch and read-only preflight")
    prior_report = None
    if args.output.exists():
        if not args.dispatch:
            raise StageError(f"Refusing to overwrite existing run artifact: {args.output}")
        try:
            prior_report = json.loads(args.output.read_text(encoding="utf-8"))
        except Exception as error:
            raise StageError(f"Existing run artifact is unreadable; reconcile it first: {error}") from error
        if (prior_report.get("status") != "prepared_only_no_dispatch"
                or prior_report.get("actual_dispatch_started") is not False):
            raise StageError(f"Refusing to continue or overwrite an existing dispatch; reconcile in-flight requests first: {args.output}")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    mode, _ = verify_provenance(manifest, args.manifest, args.dataset, args.tokenizer, args.template)
    if args.dispatch and mode == "primary_344" and not args.continue_after_known_unknown_report:
        raise StageError("The 344-task cohort already has a stopped dispatch; only its validated unattempted suffix may be continued")
    jobs, cases = build_jobs(manifest, mode, args.dataset, args.tokenizer)
    continuation_prior_settled = 0.0
    continuation_evidence = None
    if args.continue_after_known_unknown_report:
        if mode != "primary_344" or args.manifest.resolve() != MANIFEST_344_CURRENT.resolve():
            raise StageError("Continuation is allowed only for the current frozen 344-task manifest")
        if args.output.resolve() == args.continue_after_known_unknown_report.resolve():
            raise StageError("Continuation output must be a new artifact; the stopped source report is immutable")
        jobs, continuation_prior_settled = validate_stopped_344_continuation(
            args.continue_after_known_unknown_report, jobs)
        continuation_evidence = {
            "source_report_path": str(args.continue_after_known_unknown_report.resolve()),
            "source_report_sha256": UNKNOWN_344_REPORT_SHA256,
            "previously_settled_cost_usd": continuation_prior_settled,
            "prior_sample_count": 542,
            "skipped_unknown_job_id": next(iter(UNKNOWN_344_JOB_IDS)),
            "remaining_frozen_jobs": len(jobs),
        }
    report = prepare_report(args.manifest, manifest, mode, jobs, args.output)
    if continuation_evidence is not None:
        report["continuation_source_evidence"] = continuation_evidence
        report["continuation_schedule_start_index"] = 542
    report["prompt_build_wall_seconds"] = time.perf_counter() - process_started_perf
    report["process_started_utc"] = process_started_utc
    report["timing_semantics"] = {
        "sift_preprocessing_ms": "one measured Sift compaction per task, repeated across that task's three Sift response samples",
        "elapsed_wall_seconds": "dispatch loop only; excludes local prompt reconstruction and live route preflight",
        "process_wall_seconds": "process start through dispatch completion, including local prompt reconstruction and live route preflight",
        "sse_done_received": "true only when the stream terminates with the provider's [DONE] marker"
    }
    if prior_report is not None:
        if (prior_report.get("manifest_sha256") != report.get("manifest_sha256")
                or prior_report.get("schedule") != report.get("schedule")
                or prior_report.get("execution_runner_sha256") != report.get("execution_runner_sha256")):
            raise StageError("Existing prepared artifact differs from reconstructed manifest/schedule/runner")
    if not args.dispatch:
        atomic_write(args.output, report)
        print(json.dumps({"status": report["status"], "cohort": mode, "planned_jobs": len(jobs),
                          "estimated_reserve_usd": report["budget_estimate"]["estimated_reserve_usd"],
                          "output": str(args.output)}, indent=2))
        return 0
    estimate = report["budget_estimate"]["estimated_reserve_usd"]
    unknown_evidence = None
    prior_unknown_reserve = 0.0
    if args.accept_recorded_unknown_outcomes:
        unknown_evidence = [recorded_unknown_outcome_reserve(path) for path in args.prior_unknown_outcome_report]
        accepted_hashes = {entry["source_report_sha256"] for entry in unknown_evidence}
        required_hashes = {UNKNOWN_503_REPORT_SHA256, UNKNOWN_600_REPORT_SHA256,
                           UNKNOWN_344_REPORT_SHA256}
        if len(accepted_hashes) != len(unknown_evidence) or accepted_hashes != required_hashes:
            raise StageError("Supply each of the three exact pinned unreceipted-attempt reports once; no report may be omitted or duplicated")
        prior_unknown_reserve = sum(entry["total_reserve_usd"] for entry in unknown_evidence)
        report["prior_unknown_outcome_evidence"] = unknown_evidence
    report["prior_unknown_outcome_reserve_usd"] = prior_unknown_reserve
    report["previously_settled_cost_usd"] = continuation_prior_settled
    if args.spend_cap_usd < estimate + prior_unknown_reserve + continuation_prior_settled:
        report["status"] = "not_started_estimated_budget_exceeded"
        report["stop_reason"] = "cap_below_estimate_plus_prior_unknown_reserve"
        atomic_write(args.output, report)
        minimum = estimate + prior_unknown_reserve + continuation_prior_settled
        raise StageError(f"No requests sent: cap ${args.spend_cap_usd:.6f} < remaining estimate plus unknown reserve and prior settled spend ${minimum:.6f}")
    live_route = live_account_route_preflight(api_key, manifest, args.spend_cap_usd,
                                              jobs, args.confirm_no_unsettled_requests,
                                              args.confirm_provider_billing_covers_cap,
                                              args.authorize_unverified_provider_billing,
                                              args.accept_recorded_unknown_outcomes,
                                              prior_unknown_reserve)
    if continuation_evidence is not None:
        claim_single_use_continuation(args.continue_after_known_unknown_report,
                                      args.output, args.spend_cap_usd)
    # Live route metadata must match the dated reserve before any paid request.
    report["live_route_validation"] = live_route
    result = dispatch(jobs, cases, report, args.output, args.spend_cap_usd, api_key, live_route,
                      prior_unknown_outcome_reserve_usd=prior_unknown_reserve,
                      prior_settled_cost_usd=continuation_prior_settled,
                      process_started_perf=process_started_perf,
                      process_started_utc=process_started_utc)
    print(json.dumps({"status": result["status"], "completed_jobs": result["completed_jobs"],
                      "actual_cost_usd": result.get("settled_actual_cost_usd"), "output": str(args.output)}, indent=2))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StageError as error:
        raise SystemExit(f"Stage 1 stopped: {error}")
