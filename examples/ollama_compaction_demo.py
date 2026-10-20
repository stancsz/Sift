"""Show Sift compacting an old deployment log through a local Ollama model."""

from __future__ import annotations

import argparse
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def build_messages() -> list[dict[str, str]]:
    log_lines = [
        f"kubelet poll #{minute:03d}: atlas-api pod ready, revision r1842, no new events"
        for minute in range(60)
    ]
    log_lines.insert(
        31,
        "2026-10-18T09:31:00Z rollout finding: readiness probe used initialDelaySeconds=5, "
        "which did not allow sufficient time for image and database initialization; "
        "operator-approved fix is initialDelaySeconds=25.",
    )
    log_lines.extend(
        f"kubelet poll #{minute + 60:03d}: atlas-api pod ready, revision r1842, no new events"
        for minute in range(60)
    )
    history = "\n".join(log_lines)
    return [
        {
            "role": "system",
            "content": "Answer the operator's question from the deployment history. Be concise and preserve exact values.",
        },
        {
            "role": "user",
            "content": "Review this rollout history and remember the cause of the failed deployment:\n" + history,
        },
        {"role": "assistant", "content": "I reviewed the rollout history and will keep the relevant finding available."},
        {"role": "user", "content": "What readiness-probe initialDelaySeconds value did the operator approve, and why?"},
    ]


def answers_buried_setting(answer: str) -> bool:
    has_approved_value = re.search(
        r"\binitialDelaySeconds\s*[:=]\s*25\b", answer, re.IGNORECASE
    )
    has_previous_value = re.search(
        r"\binitialDelaySeconds\s*[:=]\s*5\b", answer, re.IGNORECASE
    )
    has_readiness_reason = "readiness" in answer.casefold() and "probe" in answer.casefold()
    has_insufficient_time_reason = re.search(
        r"(?:did not|didn't|does not|doesn't) allow (?:enough|sufficient) time"
        r"|insufficient time|too (?:short|brief) (?:a )?time|not enough time",
        answer,
        re.IGNORECASE,
    )
    return bool(
        has_approved_value
        and has_previous_value
        and has_readiness_reason
        and has_insufficient_time_reason
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:4011/v1/chat/completions")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    body = json.dumps({"model": args.model, "messages": build_messages()}).encode("utf-8")
    request = Request(args.url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=args.timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            compacted = response.headers.get("x-sift-compacted", "false")
            estimated = response.headers.get("x-sift-estimated-input-tokens", "unknown")
            forwarded = response.headers.get("x-sift-estimated-forwarded-tokens", "unknown")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"Sift returned HTTP {error.code}: {detail}")
        return 1
    except (URLError, TimeoutError) as error:
        print(f"Could not reach Sift at {args.url}: {error}")
        return 1

    choices = result.get("choices", [])
    answer = choices[0].get("message", {}).get("content") if choices else None
    if compacted.lower() != "true":
        print(f"Sift reported x-sift-compacted={compacted!r}; expected 'true'.")
        print(f"estimated input: {estimated}; forwarded: {forwarded}")
        return 1
    if not answer:
        print("The backend returned no assistant text.")
        return 1

    print(f"Sift compacted the request: {estimated} estimated input tokens -> {forwarded} forwarded")
    print(f"Backend answer: {answer.strip()}")
    if not answers_buried_setting(answer):
        print(
            "Could not verify the expected finding: the answer must identify the approved "
            "25-second readiness-probe delay and the previous 5-second setting."
        )
        return 1
    print("This is a synthetic quick-start demonstration, not an evaluation of answer quality.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
