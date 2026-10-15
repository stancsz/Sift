# Algorithm and acceptance contract

Sift solves a bounded selection problem over **historical evidence**, not a summarization problem. The caller passes the same token-counting function used by its inference route. The output is accepted only when that counter reports `forwarded_tokens <= target`.

## Selection

1. Validate the raw estimate against `raw_limit`. Under target, return a copy unchanged.
2. For oversized requests, reject unsupported content and instruction messages after dialogue. Identify the latest real user turn; Anthropic user messages containing only tool results do not start a new turn.
3. Preserve the leading instruction prefix and all messages from that turn onward. If they nearly fill the target, fail explicitly.
4. Walk backward over earlier real user turns. Keep at most four whole turns, subject to an 8,192-token cap and half of the remaining target. This prevents retaining a tool result without its initiating turn.
5. Render older supported text/tool content as source text. Scan lines and bounded substrings without copying the remaining suffix of a long line. Rank bounded candidates using current-query term overlap, failure/decision signals, and recency. Keep at most 256 candidates, with a bounded 65,536-hash deduplication window.
6. Select up to 96 candidates. Quote them with source message indices and roles, order them chronologically, and place them in a user-role historical-data message. A binary search uses the caller's counter to select the largest fitting prefix of ranked candidates. No excerpt means an explicit capacity error.

The algorithm is deterministic for a fixed input and counter. It scans the old text once; candidate storage is bounded independently of raw intake size. The caller's counter is invoked for the raw input, active/recent-turn checks, and at most a logarithmic number of final candidate checks. These counts can dominate CPU time if the caller's tokenizer is expensive.

## Evidence and failure boundaries

The test corpus asks for facts buried in build logs, payment events, appointments, file errors, and research citations. A separate seeded test moves a unique fact through 100 middle positions. `benchmarks/compare.py` uses the same placements and reports 100/100 Sift retention against 0/100 for a head/tail excerpt with an 800-character allowance. The test deliberately favors query-aware middle retrieval, so it does not estimate general recall on real conversations. The tests assert exact retention, hard budget compliance, unchanged active messages, and no mutation. The intended next acceptance step is a held-out corpus of real, consented agent traces with human-labeled must-retain spans.

The summary states that older content is untrusted historical data. This is a role and provenance convention, not a security boundary against prompt injection. Sift refuses media it cannot represent and refuses to erase oversized active work. It does not repair provider errors, retry calls, or generate replacement answers.
