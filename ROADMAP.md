# Roadmap to adoption

Sift reduces repeated agent history with deterministic, extractive compaction. Its current limits matter: selected LongBench runs show a quality trade-off, and no held-out study yet proves reliable task completion, lower total cost, or faster work in real coding agents.

## Available now

The tested `v0.10.0` release is a Python library and LiteLLM Proxy callback. The unreleased `0.11.0.dev0` source also adds a LiteLLM-free `sift` command for OpenAI Chat Completions clients, including Ollama and other compatible base URLs. Its explicit `byte-estimate` mode measures UTF-8 request size; it is not a provider tokenizer and cannot guarantee context fit.

## Current adoption work

- **Reliable local checks:** the latest `python -m pytest tests -q` runs passed all 363 tests in isolated Python 3.14.0 (91.76s) and Python 3.11.14 (104.51s; 17 dependency warnings in each run). Pull requests get a 43-test Python 3.12 core/invariant/CLI/demo smoke; run #180 passed in 24 seconds on head `c79a4c2`, with the full matrix skipped on PRs. The full matrix remains weekly/manual; `benchmarks/compare.py` passed 100/100 in 0.335 CPU seconds.
- **Clear first use:** the production site's Ollama example is still the small `1 + 1` pass-through. Draft [PR #2](https://github.com/stancsz/sift/pull/2) replaces it with a long-history deployment-setting retrieval demo and clarifies that Sift selects context for the next agent step. This source revision has not been rendered and independently reviewed; it is not published.
- **Public site:** GitHub Pages is live at <https://stancsz.github.io/sift/> with the problem, workflow, quick starts, measured evidence, limits, and contribution path. The production site remains behind the PR revision. Do not promote that revision until desktop and narrow rendered review pass and a fresh Pages deployment is checked against the accepted commit.
- **Broader quality evidence:** a 344-pair/three-repeat LongBench v2 cohort (2,064 generations) is prepared. Every task ID is exposed development data, not a holdout. Its current planning reserve is about $41.87; dispatch still requires exposure and unresolved-attempt reconciliation, fresh route/pricing checks, verified account funds, and an explicit user cap. Separately prepare genuinely held-out agent tasks with frozen scoring; report accepted outcomes, resource trade-offs, limits, and failures together.
- **Adoption evidence:** the Advisor council recommended three inference-free first-run sessions with developers who already use long-context workflows. The [session protocol](docs/evals/first-run-usability-protocol-2026-10-18.md) is independently reviewed and ready as a gated plan. No external participants have been contacted; sessions still need owner-authorized recruitment and a reviewed rendered preview. Record comprehension, setup time, blockers, relevance, and voluntary follow-through. Walkthrough completion is not adoption.
- **Compatibility:** automated checks cover non-streaming/SSE, incremental streaming, active tool-call/result turns, Bearer-key forwarding, and upstream errors. Independent review accepted this scope. Live Ollama compaction passed, but live tool execution and broader named-client compatibility remain unverified; check these before a stable release.
- **Release:** the workflow and current Pages deployment have passed on GitHub, but neither proves the standalone `0.11.0` candidate is ready. Resolve visual, compatibility, evaluation and adoption gates before packaging or publishing it to PyPI.

## Evidence today

The [evaluation record](docs/evaluation.md) summarizes the completed 600-response LongBench v2 study, a broader but incomplete matched checkpoint, and task-specific native-agent checks. All LongBench questions were exposed during development. The results are not blind validation, accepted-task quality, or proof of parity. Keep claims scoped to those datasets, denominators, and limitations.

See the [algorithm contract](docs/algorithm.md), [project site](https://stancsz.github.io/sift/), and [contribution guide](README.md#reproduce-and-contribute).
