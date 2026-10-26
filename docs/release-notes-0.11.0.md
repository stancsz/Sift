# Sift 0.11.0 — preview

> **Status:** GitHub preview release. This is not a PyPI publication or a claim that the roadmap's quality and adoption gates have passed. Package version and tag are `0.11.0` / `v0.11.0`.

## Issue #59 and native client reliability

- Preserve the core error code in `x-sift-error-code`, complete the HTTP status map, and expose diagnostics for both protected-set overflows. Existing detail strings stay intact.
- Add explicit active-capacity-only `on_overflow="passthrough"`; default rejection, raw/input-size safeguards, unsupported-input rejection, and overload handling remain enforced. Concurrency is configurable with default two.
- Export `compact_dynamic` and document its reference-profile defaults. It does not silently alter LiteLLM budgets.
- Fix live OpenCode continuation on plain assistant `reasoning_content`: preserve retained reasoning, exclude old reasoning from excerpts, and charge a counting floor when necessary.
- Preserve Codex `additional_tools` catalogs and sealed reasoning exactly. Serialized counting copies never reach the provider. Malformed shapes, incomplete tool batches, stateful references, and unsupported media remain rejected.
- Add the [three-client acceptance campaign](cli-acceptance.md), covering engineering repairs, migration features, and daily expense reports. See issue #59 receipts for actual executed results; a harness's existence is not a passed campaign.

## Highlights

- **Run Sift as a standalone proxy without LiteLLM.** The new `sift serve` command accepts an OpenAI Chat Completions-compatible `--base-url`, including a local Ollama URL. It binds locally, preserves tool and streaming fields, and can read an upstream API key from an environment variable. The CLI also offers `sift compact` for offline JSON compaction. The explicit `byte-estimate` counter estimates UTF-8 request size; it is not the model tokenizer and cannot guarantee provider context fit. The standalone proxy supports Chat Completions only, and provider coverage remains limited.
- **Try a no-inference first run.** The GitHub Pages site has an offline trace demo, and the repository includes a deterministic loopback fixture that demonstrates request compaction without starting a model or sending an inference request. The bundled Ollama example checks a synthetic buried-setting task: one local run with `qwen3.5:9b` passed its answer checks; `qwen3.5:4b` did not. These examples do not establish general answer quality.
- **Make local verification the broad path.** The full test suite and offline comparison can run locally; required pull-request CI stays a short Python 3.12 Core smoke. The release rehearsal also ran all **417 tests** and the offline comparison on hosted Python 3.12.
- **Retain the measured LongBench trade-off.** On an exposed 344-question LongBench v2 cohort, Sift used **59.66% fewer provider-reported prompt tokens** than full context, while task-majority accuracy was **5.25 percentage points lower** (42.27% Full versus 37.03% Sift; task-cluster 95% interval −10.20 to −0.29 pp). The questions and labels were public and exposed during development. This is not blind evidence, quality parity, or coding-agent task-success evidence. Receipt costs are cache-sensitive and are not invoice totals.

A fresh-request repeat on the same exposed 344-question cohort finished all
2,064 attempts, with 2,059 usage records and 339 complete paired questions.
It found 59.56% fewer recorded prompt tokens and task-majority scores of
41.89% Full versus 40.12% Sift (−1.77 pp; 95% interval −6.49 to +2.95).
Our own uncached calculation totals $27.6854307; five unknown attempts were not
retried. This is a public-cohort repeat, not proof of quality parity or improvement.
See the [final report](results/longbench-v2-minimax-fresh-344-2026-10-21.md).

## Packaging and release checks

The non-publishing rehearsal on October 20, 2026, built a wheel and source distribution, passed strict Twine metadata checks, and installed both archives without optional dependencies. The CLI help smoke passed for both, and each clean environment confirmed LiteLLM was absent. The run uploaded distribution and checksum artifacts; its publish job was skipped, and no PyPI upload occurred. See [the rehearsal run](https://github.com/stancsz/sift/actions/runs/39475341440).

This preview changes the default selection target from 24,576 in `v0.10.0` to **32,768 estimated input tokens**. Set a target explicitly for your route, leave room for output, and treat the byte estimate as approximate. These checks do not establish PyPI availability or completion of the stable-adoption gates.

The October 21 local verification of source `e19828a` passed **505 tests** on
Python 3.14.0 in 152.35 seconds. Its nine release-selection/workflow checks
also passed separately. An isolated snapshot with only its version changed to `0.11.0` built a
wheel and sdist that passed strict Twine checks. That historical checkout remained
`0.11.0.dev0`; those unpublished archives did not establish that the remaining
quality, adoption or publishing gates have passed.

Independent package QA checked source correspondence, both clean installs and
dependency-free CLI use. The full-suite count is from the builder's execution
receipt; the nine release guards also passed independently. See the [local
packaging result](results/release-candidate-0.11.0-local-2026-10-21.json).
