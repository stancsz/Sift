# Relation binding public development diagnostic

**Status: frozen protocol, not a holdout or release gate.** This is one public
LongBench v2 case used to diagnose whether record-level preservation changes
answerability. Its public source and answer are known. Results must not be
presented as independent quality, parity, or generalization evidence.

## Frozen case and source audit

- Dataset: `zai-org/LongBench-v2`, revision
  `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`, SHA-256
  `15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2`.
- Case: `6713066fbb02136c067d3214`.
- The tested history is the exact `player_data` JSON array, excluding the
  separate `round_records` array. Its SHA-256 is
  `1cad38d92ebb8e324ee45adc6c090a97aa9dce6aee50bccfff707eb580e9b7b9`.
- The source-derived mapping is `player_7` to a round-four bid of 40. The
  official answer is D, which maps to `player_7`.
- The exact user question SHA-256 is
  `f16d6c046bfb758f4d5edc6c1f0dfccabd3e2684830e3efda2ad3e5c9670afa5`.
- Full-context Qwen token count is 26,077, within the 28,672 input cap for a
  32,768 context with 4,096 reserved for output.

The relation audit decodes Sift's quoted tool excerpts and requires every line
of the source `player_7` record to appear in exact order and contiguously in a
single compacted source excerpt stream. Sift did not preserve the complete
record. The research-only whole-record candidate preserved it and selected 9
of 10 complete player records. This checks source structure only; it does not
predict the model answer.

## Frozen implementation and arms

- Sift core: commit `59494ba60474404d9330b36304a39d46ad0cfcfe`, source SHA-256
  `88521ac93678bbc241149248e0b7162dfe3a79595b400559f98811be3b6fc9d5`.
- Research-only whole-record candidate SHA-256:
  `adb0668cf30fb07d7af9a0be6920e4f217b47ca94e893e80532f7957b4a630e4`.
  Its source and two boundary tests are tracked in commit `bbdb1eb`.
- Runner: `benchmarks/run_relation_binding_public_dev.py`, SHA-256
  `89afc734a86676e8d6619a6343a1b0e81083db00b3427e07f21893bc19a34921`.
- Source: `tests/test_relation_binding_public_dev.py` checks exact ordered
  record retention and rejects missing or interleaved lines.

Four randomized arms receive the same system prompt, tool-cycle wrapper,
question, output schema, model, seed per repeat, and generation settings:

1. Full context: 26,077 exact prompt tokens.
2. Frozen Sift at the 24,576 estimated-token target: 5,760 exact prompt tokens.
3. Research-only whole-record selection at that same target: 23,484 exact
   prompt tokens, 9 of 10 records.
4. Oracle evidence: source-derived player/bid mappings only, 456 exact prompt
   tokens. This is a diagnostic control, not a deployable compressor.

Use local `qwen3.8-27b`, temperature 0.1, top-p 0.8, top-k 20, a 16-token
output cap, strict JSON choice output, and three repeats per arm. Prompt caching
is disabled. There are no retries or provider API charges. Randomize arm order
within each repeat. Aggregate the three answers by strict majority; a tie or
abnormal terminal response is incorrect. Publish all per-call answers and
latencies.

## Interpretation and stop rules

The primary outcome is exact choice accuracy by arm. Report the exact prompt
tokens, per-arm correctness across all three calls, majority result, TTFT,
end-to-end time, terminal status, and token usage. The whole-record candidate
must pass the exact target and preserve the gold source record. Stop before
inference if it does not. A single public case cannot establish statistically
meaningful quality or cost conclusions.

Interpret a Sift miss as extraction-related only if full context and oracle
evidence answer correctly, Sift answers incorrectly, and the gold record is
not intact in Sift's forwarded request. If the oracle also fails, classify the
result as reasoning/prompt risk. If Sift answers correctly, this case does not
show a quality regression, even when the record audit is incomplete.

Do not change the frozen selector or candidate based on the result and then
reuse this case as confirmation. A result can only motivate a separately
authored, independently frozen evaluation. No Astra price or savings claim is
made by this local diagnostic.

## Reproduction

From a checkout containing the frozen Sift source under
`.runs/relation-binding-frozen-source/src` and the pinned dataset cache:

```powershell
$env:PYTHONPATH = (Join-Path (Resolve-Path '.runs\relation-binding-frozen-source').Path 'src') + ';benchmarks'
python benchmarks\run_relation_binding_public_dev.py --prepare-only --output .runs\relation-binding-public-development-2026-10-16\preflight.json
python benchmarks\run_relation_binding_public_dev.py --output docs\results\relation-binding-public-development-2026-10-16.json
```

The runner validates the dataset, core, and candidate hashes before inference.
The preflight currently passes the token bounds and structural checks. Its
targeted test set passes 4/4 total: two retention-audit checks and two
whole-record candidate boundary checks.
The [completed result](relation-binding-public-development-results-2026-10-16.md)
and [raw call record](../results/relation-binding-public-development-2026-10-16.json)
are published separately.

To materialize the exact committed core bytes before running the commands,
create `.runs/relation-binding-frozen-source/src/sift` and copy the package
initializer and core blob from Git without text conversion:

```powershell
@'
from pathlib import Path
from subprocess import run

commit = "59494ba60474404d9330b36304a39d46ad0cfcfe"
target = Path(".runs/relation-binding-frozen-source/src/sift")
target.mkdir(parents=True, exist_ok=True)
for name in ("__init__.py", "core.py"):
    blob = run(["git", "cat-file", "blob", f"{commit}:src/sift/{name}"],
               check=True, capture_output=True).stdout
    (target / name).write_bytes(blob)
'@ | python -
```

The installed `python` command needs the repository's evaluation dependencies,
including `requests` and `pytest` for the checks.

The artifact links and the source-materialization instructions above were
added after inference. The exact pre-inference protocol snapshot is recorded
by commit and SHA-256 in the [result report](relation-binding-public-development-results-2026-10-16.md).
