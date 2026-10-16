"""Preflight and freeze a native-agent fixture before any task inference.

The flattened token count is a corpus-sizing proxy. It does not include the
native client's tool schema or prove that an actual multi-turn request crosses
the compaction target; the native run must still record that evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen


SYSTEM = (
    "You are a coding agent. Read the task and its evidence, then implement "
    "the requested program."
)
TEXT_SUFFIXES = {
    ".csv", ".json", ".jsonl", ".log", ".md", ".py", ".rst", ".text",
    ".toml", ".txt", ".yaml", ".yml",
}


def case_files(case: Path) -> list[Path]:
    files = []
    for path in sorted(case.rglob("*")):
        if "__pycache__" in path.relative_to(case).parts:
            continue
        if path.is_symlink():
            raise ValueError(f"Symlink is not allowed in a frozen case: {path}")
        if path.is_file():
            if path.suffix.lower() not in TEXT_SUFFIXES:
                raise ValueError(f"Unsupported non-text case file: {path}")
            files.append(path)
    if not files:
        raise ValueError("Case directory contains no text input files")
    return files


def input_hashes(case: Path, files: list[Path]) -> dict[str, str]:
    return {
        path.relative_to(case).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def acceptance_hashes(gold: Path) -> dict[str, str]:
    tests = sorted(path for path in gold.rglob("test_*.py") if path.is_file())
    if not tests:
        raise ValueError("Gold directory contains no test_*.py acceptance files")
    if any(path.is_symlink() for path in tests):
        raise ValueError("Symlink is not allowed in gold acceptance tests")
    return {
        path.relative_to(gold).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tests
    }


def flattened_messages(case: Path, files: list[Path]) -> list[dict[str, str]]:
    sections = []
    for path in files:
        relative = path.relative_to(case).as_posix()
        content = path.read_text(encoding="utf-8")
        sections.append(f"[{relative}]\n{content}")
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\n".join(sections)},
    ]


def count_tokens(tokenizer_url: str, messages: list[dict[str, str]]) -> int:
    body = json.dumps(
        {"messages": messages, "chat_template_kwargs": {"enable_thinking": False}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        tokenizer_url.rstrip("/") + "/v1/chat/completions/input_tokens",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.loads(response.read())
    value = result.get("input_tokens")
    if type(value) is not int or value < 0:
        raise ValueError("Tokenizer endpoint returned invalid input_tokens")
    return value


def create_manifest(
    case: Path,
    gold: Path,
    manifest_path: Path,
    *,
    tokenizer_url: str,
    min_source_tokens: int,
    max_source_tokens: int,
) -> dict:
    case = case.resolve(strict=True)
    gold = gold.resolve(strict=True)
    manifest_path = manifest_path.resolve()
    if manifest_path == case or case in manifest_path.parents:
        raise ValueError("Manifest must be outside the case directory")
    if manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite manifest: {manifest_path}")
    if min_source_tokens < 1 or max_source_tokens < min_source_tokens:
        raise ValueError("Token bounds must satisfy 1 <= min_source_tokens <= max_source_tokens")

    files = case_files(case)
    input_sha256 = input_hashes(case, files)
    acceptance_sha256 = acceptance_hashes(gold)
    token_count = count_tokens(tokenizer_url, flattened_messages(case, files))
    if not min_source_tokens <= token_count <= max_source_tokens:
        raise ValueError(
            f"Flattened source count {token_count} is outside the required range "
            f"[{min_source_tokens}, {max_source_tokens}]; manifest was not written"
        )

    manifest = {
        "schema": 1,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_sha256": input_sha256,
        "acceptance_sha256": acceptance_sha256,
        "source_prompt_tokens": token_count,
        "source_prompt_tokenizer": tokenizer_url.rstrip("/"),
        "source_prompt_method": (
            "Qwen chat-template count of the system prompt plus every case file "
            "once, flattened into one user message; excludes native tool schemas "
            "and is not an actual multi-turn request measurement"
        ),
        "required_source_prompt_token_range": [min_source_tokens, max_source_tokens],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tokenizer-url", default="http://127.0.0.1:8088")
    parser.add_argument("--min-source-tokens", type=int, required=True)
    parser.add_argument("--max-source-tokens", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = create_manifest(
            args.case,
            args.gold,
            args.manifest,
            tokenizer_url=args.tokenizer_url,
            min_source_tokens=args.min_source_tokens,
            max_source_tokens=args.max_source_tokens,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(f"fixture preflight failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "manifest": str(args.manifest),
        "source_prompt_tokens": manifest["source_prompt_tokens"],
        "input_files": len(manifest["input_sha256"]),
        "acceptance_files": len(manifest["acceptance_sha256"]),
        "actual_native_request_still_required": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
