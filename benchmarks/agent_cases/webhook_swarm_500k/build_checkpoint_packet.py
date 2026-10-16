"""Build one deterministic historical-context packet from this task fixture.

No API/model/provider call is made. Seed this packet into a persisted client
session as historical tool/file-result context, not as the final user message.
Qualify raw input by counting the prepared checkpoint with the deployed
LiteLLM route and its real system prompt/tool schemas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TASK = (
    "Implement the webhook reliability migration in the supplied repository. "
    "Use the delivery, migration, operations, and rollout contracts; reconcile "
    "every row in the legacy snapshot; preserve source identity; alias only the "
    "40 identical resharding replays; and quarantine, with their original row "
    "data, all 20 changed-payload conflicts. Do not drop either cohort or infer "
    "that records are irrelevant because there are many. Implement the API and "
    "worker contracts, update operations behavior, run the visible tests, and "
    "report assumptions or remaining risks.\n\n"
    "The corpus below is a frozen context packet for checkpoint preparation. "
    "Seed it as historical tool/file-result context, then issue the short final "
    "task request separately. Do not place this packet in the active user turn: "
    "the experiment measures compaction of historical context. File separators "
    "are included for provenance; source bytes after each separator are copied "
    "verbatim."
)
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache"}
EXCLUDE_FILES = {"swarm_context.md"}


def files() -> list[Path]:
    result = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_PARTS for part in rel.parts):
            continue
        if path.name in EXCLUDE_FILES:
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in {
            ".json", ".jsonl", ".md", ".py", ".sql", ".txt"
        }:
            continue
        result.append(path)
    return result


def packet_bytes() -> tuple[bytes, dict]:
    sections = [TASK]
    source = files()
    hashes = {}
    for path in source:
        relative = path.relative_to(ROOT).as_posix()
        raw = path.read_bytes()
        hashes[relative] = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8")
        sections.append(f"\n\n===== SOURCE FILE: {relative} =====\n{text}")
    packet = "".join(sections).encode("utf-8")
    return packet, {
        "packet_sha256": hashlib.sha256(packet).hexdigest(),
        "packet_bytes": len(packet),
        "source_file_count": len(source),
        "source_sha256": hashes,
        "delivery": "historical tool/file-result context in a prepared session",
        "message_count": None,
        "token_count": None,
        "token_count_method": (
            "Not measured in fixture authoring. Prepare a persisted client "
            "checkpoint with these bytes as historical tool/file-result context, "
            "then count the actual full request (including system prompt and tool "
            "schemas) with the deployed LiteLLM route. Cross-check provider input "
            "usage. Do not put the packet in the active user turn or sum tokens "
            "across requests."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet, metadata = packet_bytes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(packet)
    metadata["output"] = str(args.output)
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
