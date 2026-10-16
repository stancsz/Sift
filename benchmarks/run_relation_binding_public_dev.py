"""Run a one-case public development diagnostic for relation preservation.

This is not a blind holdout or an agent-task acceptance benchmark. It freezes a
source-derived LongBench v2 subdocument, applies the committed Sift selector,
and compares it with the research-only whole-record candidate and an oracle
evidence control. No provider service is used; inference goes to local Qwen.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import random
import sys
import time
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

from prepare_longbench_v2 import (  # noqa: E402
    DATASET_REVISION,
    DATASET_SHA256,
    exact_prompt_tokens,
    file_sha256,
    iter_json_array,
)
from relation_binding_candidate import (  # noqa: E402
    _array_records,
    compact_messages as compact_whole_records,
)
from sift import compact_messages  # noqa: E402
from sift import core  # noqa: E402


CASE_ID = "6713066fbb02136c067d3214"
FROZEN_COMMIT = "59494ba60474404d9330b36304a39d46ad0cfcfe"
FROZEN_CORE_SHA256 = "88521ac93678bbc241149248e0b7162dfe3a79595b400559f98811be3b6fc9d5"
WHOLE_RECORD_SHA256 = "adb0668cf30fb07d7af9a0be6920e4f217b47ca94e893e80532f7957b4a630e4"
TARGET_TOKENS = 24_576
FULL_INPUT_LIMIT = 28_672
MODEL = "qwen3.8-27b"
ARMS = ("full", "sift", "whole_record", "oracle")
SYSTEM = (
    "Answer the multiple-choice question using only the supplied context. "
    "Return exactly one option letter: A, B, C, or D."
)
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"choice": {"type": "string", "enum": ["A", "B", "C", "D"]}},
    "required": ["choice"],
    "additionalProperties": False,
}


class EvaluationError(RuntimeError):
    """The frozen public development diagnostic cannot run safely."""


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _round_four_bid(player: dict[str, Any]) -> int:
    messages = player.get("prompt", [])
    for index, item in enumerate(messages):
        content = item.get("content", "")
        if item.get("role") != "user" or "Game Results for Round 4:" not in content:
            continue
        for later in messages[index + 1:]:
            if later.get("role") == "assistant":
                value = json.loads(later.get("content", "")).get("bid_amount")
                if type(value) is int or (isinstance(value, str) and value.isdecimal()):
                    return int(value)
                break
            if later.get("role") == "user":
                break
    raise EvaluationError(f"round-four bid is absent for {player.get('id')!r}")


def _question(row: dict[str, Any]) -> str:
    choices = "\n".join(
        f"({letter}) {row[f'choice_{letter}'].strip()}" for letter in "ABCD"
    )
    return (
        f"What is the correct answer to this question: {row['question'].strip()}\n"
        f"Choices:\n{choices}\nReturn only the letter A, B, C, or D."
    )


def _preserves_source_record(messages: list[dict], record: str, *, role: str) -> bool:
    """Require one exact, ordered record in quoted source excerpts."""
    expected = [line.strip() for line in record.splitlines()]
    if not expected:
        return False
    prefix = re.compile(r"^\[message (\d+) " + re.escape(role) + r"\] (.*)$")
    excerpts_by_message: dict[int, list[str]] = {}
    for message in messages:
        content = message.get("content")
        if not isinstance(content, str):
            continue
        for line in content.splitlines():
            match = prefix.match(line)
            if not match:
                continue
            try:
                excerpt = json.loads(match.group(2))
            except json.JSONDecodeError:
                continue
            if isinstance(excerpt, str):
                excerpts_by_message.setdefault(int(match.group(1)), []).extend(
                    part.strip() for part in excerpt.splitlines()
                )
    return any(
        any(lines[start:start + len(expected)] == expected
            for start in range(len(lines) - len(expected) + 1))
        for lines in excerpts_by_message.values()
    )
def _messages(context: str, question: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": "Read the archived game-session player logs before answering.",
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "public-longbench-read",
                "type": "function",
                "function": {"name": "read_game_log", "arguments": "{}"},
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "public-longbench-read",
            "content": context,
        },
        {"role": "user", "content": question},
    ]


def prepare_case(data_path: Path, tokenizer_url: str) -> tuple[dict, dict[str, list[dict]]]:
    if not data_path.is_file() or file_sha256(data_path) != DATASET_SHA256:
        raise EvaluationError("pinned LongBench v2 data file is missing or has the wrong hash")
    row = next((item for item in iter_json_array(data_path)
                if item.get("_id") == CASE_ID or item.get("id") == CASE_ID), None)
    if row is None:
        raise EvaluationError(f"pinned dataset does not contain case {CASE_ID}")

    source = json.loads(row["context"])
    players = source.get("player_data")
    if not isinstance(players, list) or len(players) != 10:
        raise EvaluationError("source case player_data shape changed")
    bids = {player["id"]: _round_four_bid(player) for player in players}
    highest_player = max(bids, key=bids.get)
    highest_bid = bids[highest_player]
    choice_map = {letter: row[f"choice_{letter}"].strip() for letter in "ABCD"}
    gold = row["answer"]
    if highest_player != "player_7" or highest_bid != 40 or choice_map.get(gold) != highest_player:
        raise EvaluationError("source-derived relation does not match the pinned official key")

    # The exact public subdocument containing the per-player relation is used
    # across all arms. The unrelated round_records array is excluded by design.
    player_json = json.dumps(players, ensure_ascii=False, indent=2)
    question = _question(row)
    full = _messages(player_json, question)
    tokenizer = lambda messages: exact_prompt_tokens(tokenizer_url, messages)
    full_tokens = tokenizer(full)
    if not TARGET_TOKENS < full_tokens <= FULL_INPUT_LIMIT:
        raise EvaluationError(
            f"derived prompt must be above target and fit model: {full_tokens} tokens"
        )

    sift_result = compact_messages(
        full, tokenizer, target=TARGET_TOKENS, raw_limit=1_000_000, protocol="openai"
    )
    whole_messages, whole_audit = compact_whole_records(
        full, tokenizer, target=TARGET_TOKENS
    )
    oracle_facts = [
        {"player_id": player_id, "round_four_bid": bid}
        for player_id, bid in sorted(bids.items())
    ]
    oracle = _messages(json.dumps(oracle_facts, ensure_ascii=False, indent=2), question)

    _, _, _, source_records = _array_records(player_json)
    player7_source = next(
        item.text for item in source_records if json.loads(item.text).get("id") == "player_7"
    )
    by_arm = {
        "full": full,
        "sift": sift_result.messages,
        "whole_record": whole_messages,
        "oracle": oracle,
    }
    audits = {
        "full": {"compacted": False, "input_tokens": full_tokens},
        "sift": dict(sift_result.audit),
        "whole_record": dict(whole_audit),
        "oracle": {"compacted": False, "input_tokens": tokenizer(oracle)},
    }
    for arm, messages in by_arm.items():
        count = tokenizer(messages)
        audits[arm]["exact_prompt_tokens"] = count
        if arm != "full" and count > TARGET_TOKENS:
            raise EvaluationError(f"{arm} exceeds the exact target: {count}")

    case = {
        "case_id": CASE_ID,
        "dataset": "zai-org/LongBench-v2",
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "source_context_sha256": _digest_bytes(row["context"].encode("utf-8")),
        "player_data_sha256": _digest_bytes(player_json.encode("utf-8")),
        "question_sha256": _digest_bytes(question.encode("utf-8")),
        "official_answer_key": gold,
        "gold_player_id": highest_player,
        "gold_round_four_bid": highest_bid,
        "choice_map": choice_map,
        "full_fits_model_cap": full_tokens <= FULL_INPUT_LIMIT,
        "arm_audits": audits,
        "sift_preserves_player7_record": _preserves_source_record(
            sift_result.messages, player7_source, role="tool"
        ),
        "whole_record_preserves_player7_object": player7_source in whole_messages[3]["content"],
    }
    return case, by_arm


def _parse_choice(text: str) -> str | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or set(value) != {"choice"}:
        return None
    choice = value["choice"]
    return choice if choice in {"A", "B", "C", "D"} else None


def generate(messages: list[dict], *, server_url: str, seed: int) -> dict:
    started = time.perf_counter()
    first_visible = None
    parts: list[str] = []
    usage = None
    finish_reason = None
    status = None
    request_body = {
        "model": MODEL,
        "seed": seed,
        "temperature": 0.1,
        "top_p": 0.8,
        "top_k": 20,
        "max_tokens": 16,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "mcqa_choice", "strict": True, "schema": RESPONSE_SCHEMA},
        },
        "cache_prompt": False,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    try:
        with requests.post(
            server_url.rstrip("/") + "/v1/chat/completions",
            json={**request_body, "messages": messages},
            stream=True,
            timeout=(30, 600),
        ) as response:
            status = response.status_code
            if status != 200:
                return {
                    "http_status": status,
                    "normal": False,
                    "failure": "non_200_response",
                    "body_excerpt": response.text[:1000],
                    "end_to_end_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                item = line[5:].strip()
                if item == "[DONE]":
                    break
                chunk = json.loads(item)
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                for choice in chunk.get("choices", []):
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                    text = (choice.get("delta") or {}).get("content")
                    if isinstance(text, str) and text:
                        if first_visible is None:
                            first_visible = time.perf_counter()
                        parts.append(text)
    except (requests.RequestException, json.JSONDecodeError) as error:
        return {
            "http_status": status,
            "normal": False,
            "failure": type(error).__name__,
            "end_to_end_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    finished = time.perf_counter()
    text = "".join(parts)
    output_tokens = (usage or {}).get("completion_tokens")
    return {
        "http_status": status,
        "normal": finish_reason == "stop",
        "finish_reason": finish_reason,
        "text": text,
        "choice": _parse_choice(text),
        "usage": usage,
        "ttft_ms": round((first_visible - started) * 1000, 3) if first_visible else None,
        "end_to_end_ms": round((finished - started) * 1000, 3),
        "client_decode_tokens_per_second": (
            round(output_tokens / (finished - first_visible), 3)
            if output_tokens and first_visible and finished > first_visible else None
        ),
        "request_sha256": _digest_bytes(json.dumps(
            {**request_body, "messages": messages}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")),
    }


def run(args: argparse.Namespace) -> dict:
    source_hash = _digest_bytes(Path(core.__file__).read_bytes())
    candidate_hash = file_sha256(ROOT / "benchmarks" / "relation_binding_candidate.py")
    if source_hash != FROZEN_CORE_SHA256:
        raise EvaluationError(f"wrong frozen Sift core: {source_hash}")
    if candidate_hash != WHOLE_RECORD_SHA256:
        raise EvaluationError(f"whole-record candidate changed: {candidate_hash}")

    case, by_arm = prepare_case(args.dataset_path, args.tokenizer_url)
    if not args.prepare_only and case["sift_preserves_player7_record"]:
        raise EvaluationError(
            "the public case does not separate Sift from whole-record preservation"
        )
    if not case["whole_record_preserves_player7_object"]:
        raise EvaluationError("the whole-record candidate dropped the gold source record")
    case["frozen_git_commit"] = FROZEN_COMMIT
    case["sift_core_sha256"] = source_hash
    case["whole_record_candidate_sha256"] = candidate_hash
    case["runner_sha256"] = file_sha256(Path(__file__))
    result = {
        "schema_version": 1,
        "status": "prepared",
        "evaluation": "single public LongBench-derived mechanism diagnostic; not blind or promotion evidence",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "case": case,
        "execution": {
            "arms": list(ARMS),
            "repeats": args.repeats,
            "target_tokens": TARGET_TOKENS,
            "full_input_cap": FULL_INPUT_LIMIT,
            "model": MODEL,
            "temperature": 0.1,
            "top_p": 0.8,
            "top_k": 20,
            "max_output_tokens": 16,
            "prompt_cache": False,
            "retries": 0,
            "provider_api_spend": 0,
            "seed": args.seed,
        },
        "samples": [],
    }
    if args.prepare_only:
        result["status"] = "prepared_only"
        return result

    rng = random.Random(args.seed)
    for repeat in range(args.repeats):
        order = list(ARMS)
        rng.shuffle(order)
        for arm in order:
            sample = generate(by_arm[arm], server_url=args.server_url,
                              seed=args.seed + repeat)
            sample.update({
                "case_id": CASE_ID,
                "arm": arm,
                "repeat": repeat + 1,
                "expected": case["official_answer_key"],
                "correct": sample.get("choice") == case["official_answer_key"],
            })
            result["samples"].append(sample)
            print(json.dumps({"arm": arm, "repeat": repeat + 1,
                              "http_status": sample.get("http_status"),
                              "choice": sample.get("choice"),
                              "normal": sample.get("normal")}), flush=True)
    counts = Counter(
        sample["choice"] for sample in result["samples"]
        if sample.get("normal") and sample.get("choice") is not None
    )
    result["task_majority"] = {
        "choice_counts": dict(counts),
        "choice": max(counts, key=counts.get) if counts else None,
        "tie": bool(counts and list(counts.values()).count(max(counts.values())) > 1),
        "accepted": bool(counts and list(counts.values()).count(max(counts.values())) == 1),
    }
    result["status"] = "complete"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-path", type=Path,
        default=Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json",
    )
    parser.add_argument("--tokenizer-url", default="http://127.0.0.1:8088")
    parser.add_argument("--server-url", default="http://127.0.0.1:8088")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if args.repeats != 3:
        parser.error("this preregistered development run uses exactly three repeats")
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "sift_core_sha256": result["case"]["sift_core_sha256"],
                      "runner_sha256": result["case"]["runner_sha256"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
