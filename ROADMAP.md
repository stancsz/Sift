# Roadmap to adoption

Sift reduces repeated agent history with deterministic, extractive compaction. Its current limits matter: selected LongBench runs show a quality trade-off, and no held-out study yet proves reliable task completion, lower total cost, or faster work in real coding agents.

## Available now

The tested `v0.10.0` release is a Python library and LiteLLM Proxy callback. The unreleased `0.11.0.dev0` source also adds a LiteLLM-free `sift` command for OpenAI Chat Completions clients, including Ollama and other compatible base URLs. Its explicit `byte-estimate` mode measures UTF-8 request size; it is not a provider tokenizer and cannot guarantee context fit.

## Current adoption work

- **Reliable local checks:** the full offline suite now passes in the repository virtual environment (359 tests on Python 3.14). Pull requests receive a 39-test core/invariant/CLI smoke check; the cross-version full suite and offline comparison run weekly and manually.
- **Clear first use:** the live site explains the workflow and trade-offs, but its current Ollama example is still a tiny pass-through request. A revised long-history compaction demo is local and awaits rendered review before publication.
- **Public site:** GitHub Pages is live at <https://stancsz.github.io/sift/> with the problem, workflow, quick starts, measured evidence, limits, and contribution path. The pending quick-start revision must pass visual QA and a fresh Pages deployment before the published version is considered current.
- **Broader quality evidence:** a 344-case/three-repeat paired LongBench v2 cohort is prepared, but all task IDs are exposed development data and the paid run remains behind exposure, route, account, and numeric-cap gates. Add independently authored held-out coding and research tasks, compare accepted outcomes against full context and protocol-preserving controls, and measure total task cost and time.
- **Compatibility:** check real client and tool-call behavior for the standalone CLI and existing LiteLLM paths before a stable release.
- **Release:** the workflow and Pages deployment have passed on GitHub. Decide whether the standalone `0.11.0` candidate meets release gates, then package and publish it to PyPI.

## Evidence today

The [evaluation record](docs/evaluation.md) summarizes the completed 600-response LongBench v2 study, a broader but incomplete matched checkpoint, and task-specific native-agent checks. All LongBench questions were exposed during development. The results are not blind validation, accepted-task quality, or proof of parity. Keep claims scoped to those datasets, denominators, and limitations.

See the [algorithm contract](docs/algorithm.md), [project site](https://stancsz.github.io/sift/), and [contribution guide](README.md#reproduce-and-contribute).
