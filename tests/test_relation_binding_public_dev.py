"""Checks that the public diagnostic audits intact source records."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

from run_relation_binding_public_dev import _preserves_source_record


def _summary(excerpts: list[str]) -> list[dict]:
    lines = ["Earlier conversation, lossily excerpted by Sift."]
    lines.extend(f"[message 2 tool] {json.dumps(text)}" for text in excerpts)
    return [{"role": "user", "content": "\n".join(lines)}]


def test_relation_audit_requires_complete_ordered_record():
    record = '{\n  "id": "player_7",\n  "round_four": 40\n}'
    assert _preserves_source_record(
        _summary(record.splitlines()), record, role="tool"
    )


def test_relation_audit_rejects_missing_or_interleaved_record_lines():
    record = '{\n  "id": "player_7",\n  "round_four": 40\n}'
    assert not _preserves_source_record(
        _summary(['{', '  "id": "player_7",', '}']), record, role="tool"
    )
    assert not _preserves_source_record(
        _summary(['{', '  "id": "player_7",', '  "other": 1,',
                  '  "round_four": 40', '}']),
        record,
        role="tool",
    )
