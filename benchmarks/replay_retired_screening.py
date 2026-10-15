"""Replay the disclosed, retired screening against the installed Sift source."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from sift import compact_messages
from sift.core import _render


def count(messages: list[dict]) -> int:
    return (len(json.dumps(messages)) + 3) // 4


def retained_text(messages: list[dict]) -> list[str]:
    text = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and content.startswith("Earlier conversation,"):
            text.extend(json.loads(line.split("] ", 1)[1])
                        for line in content.splitlines()[1:])
        else:
            text.append(_render(message))
    return text


def main() -> None:
    path = Path(__file__).with_name("retired_frozen_release_screening_2026-10-15.json")
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    total_hits = 0
    all_span_cases = 0
    for case in cases:
        original = deepcopy(case["messages"])
        result = compact_messages(original, count, target=case["target"],
                                  protocol=case["protocol"])
        quotes = retained_text(result.messages)
        hits = sum(any(span["text"] in text for text in quotes)
                   for span in case["required_spans"])
        total_hits += hits
        all_span_cases += hits == len(case["required_spans"])
        protected = all(case["messages"][index] in result.messages
                        for index in case["protected_message_indices"])
        print(f'{case["name"]}: {hits}/{len(case["required_spans"])} exact, '
              f'{result.audit["forwarded_tokens"]}/{case["target"]} estimate, '
              f'protected={protected}, immutable={original == case["messages"]}')
    print(f'TOTAL: {total_hits}/{sum(len(case["required_spans"]) for case in cases)} '
          f'exact spans, {all_span_cases}/{len(cases)} all-span cases')


if __name__ == "__main__":
    main()
