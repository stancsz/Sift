# Roadmap to adoption

Sift reduces repeated agent history with deterministic, extractive compaction. Its current limits matter: selected LongBench runs show a quality trade-off, and no held-out study yet proves reliable task completion, lower total cost, or faster work in real coding agents.

## Available now

The tested `v0.10.0` release is a Python library and LiteLLM Proxy callback. The unreleased `0.11.0.dev0` source adds a LiteLLM-free `sift` command for OpenAI Chat Completions clients, including Ollama and other compatible base URLs. Its explicit `byte-estimate` mode measures UTF-8 request size; it is not a provider tokenizer and cannot guarantee context fit.

## Current adoption work

- **Reliable local checks:** run the full offline suite locally. Pull requests receive a fast core/invariant/CLI smoke check; the cross-version full suite runs weekly and manually.
- **Clear first use:** explain what Sift changes in an agent request, show a runnable Ollama example, and place quality limits next to the token-saving claim.
- **Public site:** publish a static GitHub Pages site with the problem, workflow, quick starts, measured evidence, limits, and contribution path.
- **Broader quality evidence:** add independently authored held-out coding and research tasks, compare accepted outcomes against full context and protocol-preserving controls, and measure total task cost and time.
- **Compatibility:** check real client and tool-call behavior for the standalone CLI and existing LiteLLM paths before a stable release.
- **Release:** verify the new CI workflows on GitHub, publish the Pages site, then decide whether to release `0.11.0` and package Sift on PyPI.

## Evidence today

The [evaluation record](docs/evaluation.md) summarizes the completed 600-response LongBench v2 study, a broader but incomplete matched checkpoint, and task-specific native-agent checks. All LongBench questions were exposed during development. The results are not blind validation, accepted-task quality, or proof of parity. Keep claims scoped to those datasets, denominators, and limitations.

See the [algorithm contract](docs/algorithm.md), [project site](https://stancsz.github.io/sift/), and [contribution guide](README.md#reproduce-and-contribute).
