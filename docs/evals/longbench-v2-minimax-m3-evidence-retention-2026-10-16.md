# MiniMax LongBench v2 evidence-retention audit

This is a source-first, offline follow-up to the [MiniMax M3 screen](longbench-v2-minimax-m3-results-2026-10-16.md). The required evidence was derived from the pinned source before reviewing arm outputs. No provider requests are made by the audit.

## Method

The audit checks complete source evidence rather than asking a model to explain an answer. For the Yelp CSV question, it parses the original CSV and identifies every row whose comment contains “mexican,” then counts unique exact comment strings. A comment counts as retained when any complete original CSV row containing that exact string is present; duplicate rows may differ in review ID. For the game question, it derives every round's complete player-contribution vector from the original JSON. The audit decodes Sift's JSON-quoted excerpts before checking source evidence. It verifies the dataset, prompt, tokenizer, template, manifest, and selector-source hashes.

The report preserves the corrected pre-change selector ablation and the CSV-aware candidate. The ablation disables CSV record parsing and its quoted-anchor ranking boost. This is a narrow diagnostic with two questions, not a gold-span annotation for LongBench v2 or proof that the changes improve overall answer accuracy.

## Results

| Case and selector | Full | 16K | 24K | 32K | 48K | 64K |
|---|---:|---:|---:|---:|---:|---:|
| Yelp, CSV feature disabled: unique comments retained | 41/41 | 6/41 | 7/41 | 7/41 | 8/41 | 8/41 |
| Yelp, CSV-aware candidate: unique comments retained | 41/41 | 41/41 | 41/41 | 41/41 | 41/41 | 41/41 |
| Game, CSV feature disabled: full round vectors retained | 20/20 | 17/20 | 17/20 | 17/20 | Original prompt fits | Original prompt fits |
| Game, CSV-aware candidate: full round vectors retained | 20/20 | 17/20 | 17/20 | 17/20 | Original prompt fits | Original prompt fits |

The candidate retained all 41 distinct matching comments at every tested budget. It emits the CSV column header once, followed by atomic source rows, and boosts rows matching an explicitly quoted user term. For the separate game case, retention was unchanged at 17 of 20 vectors.

## Interpretation

This is a strong case-specific retention improvement. It does not show that all CSV schemas, exhaustive questions, or answer quality improve. The game-vector omissions remain a separate known limitation. A single post-hoc MiniMax M3 check on the immediately preceding selector revision returned the correct choice at 16K and the wrong choice at 64K; the full-context request was also wrong in that check. The later physical-line-bound change was verified not to alter either retained-evidence fixture, but the answer check was not rerun on this exact source hash. The earlier frozen run had different outcomes. These one-shot results are noisy and do not establish a quality lift. See the [post-hoc answer check](../results/longbench-v2-minimax-m3-csv-candidate-answer-check-2026-10-16.json).

The CSV parser is intentionally bounded: a simple unique header within the first eight lines, at least two named columns, consistent row widths, source size up to 8 MB, 100,000 physical lines, 20,000 data rows, and 8,192 characters per record. Other or malformed tables fall back to generic slices. The selector does not claim complete coverage when some rows are omitted. This initial regression is one public CSV task; add distinct structured-data fixtures before describing CSV support as generally mature.

## Artifacts

- [Frozen protocol and aggregate results](longbench-v2-minimax-m3-results-2026-10-16.md)
- [Corrected selector-ablation evidence output](../results/longbench-v2-minimax-m3-evidence-retention-2026-10-16.json)
- [CSV-aware candidate evidence output](../results/longbench-v2-minimax-m3-evidence-retention-candidate-2026-10-16.json)
- [Candidate benchmark manifest](longbench-v2-minimax-m3-csv-candidate-manifest-2026-10-16.json)
- [Post-hoc MiniMax answer check](../results/longbench-v2-minimax-m3-csv-candidate-answer-check-2026-10-16.json)
- [Offline audit script](../../benchmarks/audit_longbench_v2_minimax_evidence.py)
- [Advisor council receipt](sift-advisor-council-research-validity-2026-10-16.md)
- [Retrieval-tools design council](sift-retrieval-tools-council-2026-10-16.md)
