"""Freeze a MiniMax M3 LongBench v2 sample using its published tokenizer."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from urllib.request import Request, urlopen

from tokenizers import Tokenizer

from prepare_longbench_v2 import (
    DATASET_REVISION,
    DATASET_SHA256,
    download_dataset,
    file_sha256,
    iter_json_array,
    make_messages,
    prompt_sha256,
)


MODEL_ID = "minimax/minimax-m3"
HF_TOKENIZER_URL = "https://huggingface.co/MiniMaxAI/MiniMax-M3/resolve/main/tokenizer.json"
HF_TEMPLATE_URL = "https://huggingface.co/MiniMaxAI/MiniMax-M3/resolve/main/chat_template.jinja"
SIFT_TARGETS = (16_384, 24_576, 32_768, 49_152, 65_536)
MIN_FULL_TOKENS = 16_385
MAX_FULL_TOKENS = 900_000
PER_STRATUM = 2
SEED = 20261016
THINKING_INSTRUCTIONS = (
    "\n\n<thinking_instructions>\n"
    "You have a thinking capability that allows you to reason step by step before responding. "
    "When thinking is enabled, wrap your reasoning in <mm:think></mm:think> tags before your response. "
    "When thinking is disabled, begin your response directly after the </mm:think> prefix. "
    "When thinking is adaptive, decide on your own whether to think for the current turn.\n"
    "Current thinking mode: disabled. Do not output any thinking process.\n"
    "</thinking_instructions>"
)
STRATA = (
    (16_385, 32_768, "16-32k"),
    (32_769, 65_536, "32-64k"),
    (65_537, 131_072, "64-128k"),
    (131_073, 262_144, "128-256k"),
    (262_145, MAX_FULL_TOKENS, "256k-900k"),
)


def fetch(url: str, path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "sift-eval/0.1"})
    with urlopen(request, timeout=120) as response, path.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def render_minimax(messages: list[dict[str, str]], *, generation_prompt: bool = True) -> str:
    """Render the benchmark's text-only messages with MiniMax's published template."""
    bos, eos, bod = "]~b]", "[e~[", "]~!b["
    ns, think_end = "]<]minimax[>[", "</mm:think>"
    system = "Your model version is MiniMax-M3, developed by MiniMax. Knowledge cutoff: January 2026. Founded in early 2022, MiniMax is a global AI foundation model company committed to advancing the frontiers of AI towards AGI."
    rendered = f"{bod}{bos}system\n{system}{THINKING_INSTRUCTIONS}{eos}\n"
    developer = messages[0]["content"] if messages and messages[0]["role"] == "system" else "You are a helpful assistant."
    rendered += f"{bos}developer\n{developer}{eos}\n"
    for message in messages[1:] if messages and messages[0]["role"] == "system" else messages:
        role = message["role"]
        if role == "user":
            rendered += f"{bos}user\n{message['content']}{eos}\n"
        elif role == "assistant":
            content = message.get("content", "")
            rendered += f"{bos}ai\n{think_end}{content}{eos}\n"
        else:
            raise ValueError(f"Unsupported role in frozen LongBench prompt: {role}")
    if generation_prompt:
        rendered += f"{bos}ai\n{think_end}"
    return rendered


def select(candidates: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    selected = []
    for lower, upper, label in STRATA:
        group = [row for row in candidates if lower <= row["m3_rendered_prompt_tokens"] <= upper]
        rng.shuffle(group)
        selected.extend({**row, "stratum": label} for row in group[:PER_STRATUM])
    selected.sort(key=lambda row: (row["stratum"], row["id"]))
    return selected


def prepare(dataset_path: Path, tokenizer_path: Path, template_path: Path, output_path: Path) -> dict:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen selection: {output_path}")
    download_dataset(dataset_path)
    if file_sha256(dataset_path) != DATASET_SHA256:
        raise ValueError("LongBench v2 data.json SHA-256 did not match pinned revision")
    fetch(HF_TOKENIZER_URL, tokenizer_path)
    fetch(HF_TEMPLATE_URL, template_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    candidates = []
    scanned = 0
    for row in iter_json_array(dataset_path):
        scanned += 1
        messages = make_messages(row)
        count = len(tokenizer.encode(render_minimax(messages), add_special_tokens=False).ids)
        if MIN_FULL_TOKENS <= count <= MAX_FULL_TOKENS:
            candidates.append({
                "id": row["_id"],
                "domain": row["domain"],
                "sub_domain": row["sub_domain"],
                "difficulty": row["difficulty"],
                "length": row["length"],
                "answer_key": row["answer"],
                "context_chars": len(row["context"]),
                "m3_rendered_prompt_tokens": count,
                "prompt_sha256": prompt_sha256(messages),
            })
    if scanned != 503:
        raise ValueError(f"Expected 503 LongBench v2 rows, observed {scanned}")
    cases = select(candidates)
    if not cases:
        raise ValueError("No eligible LongBench cases in the configured M3 strata")
    report = {
        "schema_version": 1,
        "status": "frozen public development sample; no generations made during preparation",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "id": "zai-org/LongBench-v2",
            "revision": DATASET_REVISION,
            "split": "train (503 public rows)",
            "data_file_sha256": DATASET_SHA256,
            "license": "apache-2.0",
        },
        "model": {
            "id": MODEL_ID,
            "context_tokens": 1_048_576,
            "tokenizer_source": HF_TOKENIZER_URL,
            "tokenizer_sha256": file_sha256(tokenizer_path),
            "chat_template_source": HF_TEMPLATE_URL,
            "chat_template_sha256": file_sha256(template_path),
            "counting_note": "Tokenizer counts the rendered published M3 chat template, with reasoning disabled. Provider-reported prompt usage is authoritative and will be recorded per request.",
        },
        "sift": {
            "core_sha256": hashlib.sha256((Path(__file__).resolve().parents[1] / "src/sift/core.py").read_bytes()).hexdigest(),
            "targets": list(SIFT_TARGETS),
            "safety_margin_tokens": 128,
        },
        "selection": {
            "seed": SEED,
            "scanned_rows": scanned,
            "eligible_rows_16k_to_900k": len(candidates),
            "sample_per_stratum": PER_STRATUM,
            "strata": [label for _, _, label in STRATA],
            "selected_by_stratum": dict(Counter(row["stratum"] for row in cases)),
            "policy": "Select two deterministic random rows per MiniMax-tokenizer prompt-length stratum; public development data only.",
        },
        "cases": cases,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", type=Path, default=(Path.home() / ".cache" / "sift-longbench-v2" / DATASET_REVISION / "data.json"))
    parser.add_argument("--tokenizer", type=Path, default=root / "tmp" / "minimax-m3-tokenizer.json")
    parser.add_argument("--template", type=Path, default=root / "tmp" / "minimax-m3-chat-template.jinja")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.dataset_path, args.tokenizer, args.template, args.output)
    print(json.dumps({"selection": result["selection"], "cases": result["cases"], "output": str(args.output)}, indent=2))
