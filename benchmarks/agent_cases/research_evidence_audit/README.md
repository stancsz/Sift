# Fictional research evidence audit

Audit the claim for **EXP-KITE-43** as of **2026-10-15T12:00:00Z**. These four JSONL documents are entirely fictional authored development fixtures, not real papers, product measurements, or held-out research evidence. Determine the latest report revision effective by the cutoff, join its analysis and dataset identifiers, apply the applicable correction, and distinguish task success from the latency subset. A published revision or correction can have a future effective time. Superseded claims are not current conclusions.

Run `python -m unittest -q` before editing. Investigate the four supplied evidence files with targeted searches or reads as useful. Edit **only `findings.json`**, with no scratch files, changes to evidence, or test edits. Produce exactly these JSON fields:

| Field | Meaning |
|---|---|
| `experiment_id` | Requested experiment |
| `as_of` | The requested UTC cutoff verbatim |
| `report_id` | Its report identifier |
| `report_revision` | Latest effective revision, integer |
| `analysis_run_id` | Analysis backing that revision |
| `dataset_id`, `dataset_revision` | Dataset and revision bound to that analysis |
| `correction_id` | Correction applicable to that revision |
| `evaluated_pairs` | Full task-success sample size, integer |
| `sift_successes`, `baseline_successes` | Corrected success counts, integers |
| `delta_successes` | Sift successes minus baseline successes, integer |
| `latency_sample_pairs` | Matched subset underlying reported latency, integer |
| `prefill_median_before_ms`, `prefill_median_after_ms` | Reported subset medians, integers |
| `conclusion` | One supported label below |
| `cost_claim_supported` | Boolean: whether these records establish monetary savings |
| `limitations` | Exact limitation codes from the applicable analysis record |
| `evidence` | Exact source citations supporting the complete chain |

Choose a conclusion from `latency_and_task_success_improved`, `latency_improved_with_lower_task_success`, `task_success_improved_without_latency_gain`, or `no_supported_comparison`. Do not infer full-task latency or billing results from prefill medians. Include the source limitations and do not conflate the full sample with the successful-pair latency subset.

Each evidence entry must have exactly `file`, `line`, and `quote`. Use a supplied evidence filename, a one-based line number, and the **entire exact JSONL line**, without its trailing newline. Cite experiment mapping, active revision/analysis binding, applicable correction, corrected results, dataset provenance, and limitations. Include at least one citation from every evidence file. Do not paraphrase quotes or use unrelated records as support.

Run `python -m unittest -q` after writing. Visible tests check shape and source integrity; independent acceptance checks evaluate the conclusions and supporting chain. Report test results and uncertainty honestly.
