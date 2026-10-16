"""Freeze a deterministic LongBench v2 QA sample for the local Qwen screen.

This evaluation-only preparation command uses the official public dataset and
the local llama.cpp tokenizer endpoint. It makes no generation requests and
does not change the Sift selector.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from urllib.request import Request, urlopen


DATASET_REVISION = "2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9"
DATASET_URL = (
    f"https://huggingface.co/datasets/zai-org/LongBench-v2/resolve/"
    f"{DATASET_REVISION}/data.json"
)
DATASET_BYTES = 465_490_535
DATASET_SHA256 = "15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2"
MODEL_CONTEXT = 32_768
OUTPUT_RESERVE = 4_096
FULL_INPUT_LIMIT = MODEL_CONTEXT - OUTPUT_RESERVE
SIFT_TARGET = 24_576
MAX_CHARS_FOR_FULL_FIT_SCAN = 500_000
MAX_ABOVE_TARGET_PER_DOMAIN = 4

SYSTEM_PROMPT = (
    "Answer the multiple-choice question using only the supplied context. "
    "Return exactly one option letter: A, B, C, or D."
)
CONTEXT_PREFIX = "<text>\n"
CONTEXT_SUFFIX = "\n</text>"
QUESTION_SUFFIX = "\nReturn only the letter A, B, C, or D."


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_dataset(path: Path) -> None:
    if path.is_file() and path.stat().st_size == DATASET_BYTES:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    request = Request(DATASET_URL, headers={"User-Agent": "sift-eval/0.1"})
    with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        while chunk := response.read(4 * 1024 * 1024):
            output.write(chunk)
    if temporary.stat().st_size != DATASET_BYTES:
        raise ValueError("Downloaded LongBench v2 file has an unexpected size")
    temporary.replace(path)


def iter_json_array(path: Path):
    """Yield one object at a time from the dataset's large top-level array."""
    decoder = json.JSONDecoder()
    buffer = ""
    position = 0
    started = False
    with path.open(encoding="utf-8") as source:
        while chunk := source.read(2 * 1024 * 1024):
            buffer += chunk
            if not started:
                opening = buffer.find("[")
                if opening < 0:
                    continue
                buffer = buffer[opening + 1:]
                started = True
            while True:
                while position < len(buffer) and buffer[position] in " \t\r\n,":
                    position += 1
                if position >= len(buffer) or buffer[position] == "]":
                    break
                try:
                    row, end = decoder.raw_decode(buffer, position)
                except json.JSONDecodeError:
                    break
                yield row
                position = end
            if position:
                buffer = buffer[position:]
                position = 0


def make_messages(row: dict) -> list[dict[str, str]]:
    choices = "\n".join(
        f"({letter}) {row[f'choice_{letter}'].strip()}" for letter in "ABCD"
    )
    question = (
        f"What is the correct answer to this question: {row['question'].strip()}\n"
        f"Choices:\n{choices}{QUESTION_SUFFIX}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": CONTEXT_PREFIX + row["context"].strip() + CONTEXT_SUFFIX},
        {"role": "assistant", "content": "Ready."},
        {"role": "user", "content": question},
    ]


def exact_prompt_tokens(base_url: str, messages: list[dict[str, str]]) -> int:
    payload = json.dumps({"messages": messages}, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + "/v1/chat/completions/input_tokens",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.loads(response.read())
    count = result.get("input_tokens")
    if type(count) is not int or count < 0:
        raise ValueError("Tokenizer endpoint returned an invalid input_tokens value")
    return count


def prompt_sha256(messages: list[dict[str, str]]) -> str:
    canonical = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def selection(candidates: list[dict], seed: int, *, target_tokens: int = SIFT_TARGET,
              sample_size: int | None = None) -> tuple[list[dict], dict]:
    if sample_size is not None:
        eligible = [item for item in candidates
                    if item["exact_full_prompt_tokens"] > target_tokens]
        if len(eligible) < sample_size:
            raise ValueError(
                f"Requested {sample_size} above-target tasks, found {len(eligible)}"
            )
        rng = random.Random(seed)
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for candidate in eligible:
            groups[(candidate["domain"], candidate["difficulty"])].append(candidate)
        for group in groups.values():
            rng.shuffle(group)
        # Round-robin through domain/difficulty strata to avoid letting the
        # largest LongBench categories dominate a 100-task diagnostic sample.
        keys = sorted(groups)
        chosen = []
        while len(chosen) < sample_size:
            advanced = False
            for key in keys:
                if groups[key]:
                    chosen.append(groups[key].pop())
                    advanced = True
                    if len(chosen) == sample_size:
                        break
            if not advanced:
                raise ValueError("Stratified sample exhausted before reaching requested size")
        chosen.sort(key=lambda item: (item["domain"], item["difficulty"], item["id"]))
        summary = {
            "candidate_count_full_fit": len(candidates),
            "eligible_above_target": len(eligible),
            "selected_count": len(chosen),
            "selected_by_domain": dict(Counter(item["domain"] for item in chosen)),
            "selected_by_difficulty": dict(Counter(item["difficulty"] for item in chosen)),
            "selected_by_budget": dict(Counter("above_target" for _ in chosen)),
            "policy": f"Seeded round-robin sample of {sample_size} above-target tasks across domain and difficulty strata.",
        }
        return chosen, summary

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for candidate in candidates:
        band = "above_target" if candidate["exact_full_prompt_tokens"] > target_tokens else "below_target"
        groups[(candidate["domain"], band)].append(candidate)

    rng = random.Random(seed)
    chosen: list[dict] = []
    for domain in sorted({item["domain"] for item in candidates}):
        above = groups.get((domain, "above_target"), [])
        rng.shuffle(above)
        chosen.extend(above[:MAX_ABOVE_TARGET_PER_DOMAIN])
        below = groups.get((domain, "below_target"), [])
        if below:
            # One negative control below each budget half, where available.
            lower = [item for item in below if item["exact_full_prompt_tokens"] <= 16_384]
            upper = [item for item in below if item["exact_full_prompt_tokens"] > 16_384]
            for stratum in (lower, upper):
                if stratum:
                    chosen.append(rng.choice(stratum))

    chosen.sort(key=lambda item: (item["domain"], item["id"]))
    summary = {
        "candidate_count_full_fit": len(candidates),
        "selected_count": len(chosen),
        "selected_by_domain": dict(Counter(item["domain"] for item in chosen)),
        "selected_by_budget": dict(Counter(
            "above_target" if item["exact_full_prompt_tokens"] > SIFT_TARGET else "below_target"
            for item in chosen
        )),
    }
    return chosen, summary


def prepare(dataset_path: Path, tokenizer_url: str, output_path: Path, seed: int,
            model_context: int = MODEL_CONTEXT,
            output_reserve: int = OUTPUT_RESERVE,
            target_tokens: int = SIFT_TARGET,
            sample_size: int | None = None) -> dict:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen selection: {output_path}")
    download_dataset(dataset_path)
    actual_hash = file_sha256(dataset_path)
    if actual_hash != DATASET_SHA256:
        raise ValueError("LongBench v2 data.json SHA-256 did not match the pinned file")

    candidates = []
    scanned = 0
    skipped_long = 0
    for row in iter_json_array(dataset_path):
        scanned += 1
        if len(row["context"]) > MAX_CHARS_FOR_FULL_FIT_SCAN:
            skipped_long += 1
            continue
        messages = make_messages(row)
        count = exact_prompt_tokens(tokenizer_url, messages)
        if count <= model_context - output_reserve:
            candidates.append({
                "id": row["_id"],
                "domain": row["domain"],
                "sub_domain": row["sub_domain"],
                "difficulty": row["difficulty"],
                "length": row["length"],
                "answer_key": row["answer"],
                "context_chars": len(row["context"]),
                "exact_full_prompt_tokens": count,
                "prompt_sha256": prompt_sha256(messages),
            })
    if scanned != 503:
        raise ValueError(f"Expected 503 LongBench v2 rows, observed {scanned}")

    selected, summary = selection(
        candidates, seed, target_tokens=target_tokens, sample_size=sample_size,
    )
    wrapper = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": CONTEXT_PREFIX + "<CONTEXT>" + CONTEXT_SUFFIX},
        {"role": "assistant", "content": "Ready."},
        {"role": "user", "content": "<QUESTION_AND_CHOICES>" + QUESTION_SUFFIX},
    ]
    report = {
        "schema_version": 1,
        "status": "frozen public benchmark sample; no generations made during preparation",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "split": "train (503 public benchmark rows)",
            "license": "apache-2.0",
            "data_file": "data.json",
            "data_file_bytes": DATASET_BYTES,
            "data_file_sha256": actual_hash,
            "dataset_card": "https://huggingface.co/datasets/zai-org/LongBench-v2",
        },
        "source": {
            "sift_core_sha256": hashlib.sha256(Path("src/sift/core.py").read_bytes()).hexdigest(),
            "model": "Qwen3.8-27B IQ3_S, local llama.cpp",
            "tokenizer_endpoint": tokenizer_url.rstrip("/"),
            "model_context_tokens": model_context,
            "output_reserve_tokens": output_reserve,
            "full_input_limit_exact_tokens": model_context - output_reserve,
            "sift_target_estimated_tokens": target_tokens,
            "wrapper_sha256": prompt_sha256(wrapper),
            "wrapper_note": "LongBench question adapted to a prior context message plus a final user query so the extractive selector can use the active question; all arms receive identical messages.",
        },
        "selection": {
            "seed": seed,
            "scan_rows": scanned,
            "skipped_contexts_over_char_prefilter": skipped_long,
            "full_fit_candidates": len(candidates),
            "policy": (
                "Per domain, randomly select up to four full-fit cases above the 24,576-token target; "
                "also select one below-target case in each available <=16,384 and 16,385-24,576 band."
            ),
            **summary,
        },
        "cases": selected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", type=Path, default=(
        Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"
    ))
    parser.add_argument("--tokenizer-url", default="http://127.0.0.1:8088")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261016)
    parser.add_argument("--model-context", type=int, default=MODEL_CONTEXT)
    parser.add_argument("--output-reserve", type=int, default=OUTPUT_RESERVE)
    parser.add_argument("--target", type=int, default=SIFT_TARGET)
    parser.add_argument("--sample-size", type=int,
                        help="Freeze this many above-target tasks, balanced across domain and difficulty.")
    args = parser.parse_args()
    result = prepare(args.dataset_path, args.tokenizer_url, args.output, args.seed,
                     args.model_context, args.output_reserve, args.target, args.sample_size)
    print(json.dumps({"selection": result["selection"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
