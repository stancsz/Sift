# LongBench v2 exposure audit review

## Review history

- Claude Code's read-only review found the first ID-only sample builder safe at the value-decoding boundary but too narrow in file coverage: it omitted most `.runs` artifacts and used overly broad ID-field handling.
- The replacement inventory scans JSON-family artifacts recursively under `.runs`, `docs/evals`, and `docs/results`; it excludes generic provider/request/commit IDs, hashes the pinned dataset without parsing its JSON, and records the generated report as an explicit self-exclusion.
- A separate Codex reviewer checked the corrected inventory and report: source counts and ID sets were internally consistent; the 503-row universe, 230 outcome IDs, 196 mechanism IDs, 250-ID union, 253 disjoint IDs, and zero untouched count matched the report; there were no scan errors.

## Remaining limits

The inventory does not parse non-JSON logs or external provider history. The report therefore describes a broad local artifact audit, not proof that every exposure channel was searched. It also records that all 503 tasks were prompt/label-census-exposed, so no task qualifies as an untouched holdout.

No LongBench prompt, answer, or model-response values were decoded or serialized. No OpenRouter benchmark requests were sent.
