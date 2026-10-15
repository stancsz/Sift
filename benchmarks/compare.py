"""Reproducible synthetic needle recall against a head/tail baseline.

This deliberately places each answer in the middle, so it probes that failure
mode rather than estimating performance on natural conversations.
"""

from __future__ import annotations

import json
import random
import time

from sift import compact_messages


def estimate(messages):
    return (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4


def head_tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = min(limit // 4, 2_048)
    return text[:head] + "\n[omitted]\n" + text[-(limit - head):]


def main() -> None:
    sift_hits = baseline_hits = 0
    sift_seconds = 0.0
    for seed in range(100):
        rng = random.Random(seed)
        key = f"KEY_{seed:03d}"
        fact = f"{key} = value-{seed * 17}"
        lines = [f"ordinary record {i} status normal" for i in range(120)]
        lines[rng.randrange(20, 100)] = fact
        history = "\n".join(lines)
        messages = [{"role": "system", "content": "Answer accurately"},
                    {"role": "user", "content": history},
                    {"role": "assistant", "content": "noted"},
                    {"role": "user", "content": f"What is {key}?"}]
        start = time.perf_counter()
        result = compact_messages(messages, estimate, target=300)
        sift_seconds += time.perf_counter() - start
        sift_hits += fact in result.messages[1]["content"]
        baseline_hits += fact in head_tail(history, 800)
        assert result.audit["forwarded_tokens"] <= 300
    print(json.dumps({"cases": 100, "sift_hits": sift_hits,
                      "head_tail_hits": baseline_hits,
                      "sift_cpu_seconds": round(sift_seconds, 3)}))


if __name__ == "__main__":
    main()
