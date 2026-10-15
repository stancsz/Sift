# Roadmap to a mature Sift

Sift's goal is to make long agent sessions cheaper and faster while preserving the evidence needed to finish correctly. The core should remain a small CPU library, with installation and useful operation through LiteLLM's native callback mechanism.

A mature release needs evidence across real Claude Code and Codex tasks, not only successful extraction examples. A smaller prompt that causes retries or incorrect work can increase total cost. These gates define the work still required; they do not declare the current release production-proven.

## Current foundation

Version 0.9.1 provides deterministic extraction, caller-owned hard input budgets, exact essential active work, neighboring diagnostic evidence, bounded identifier joins, failed-test identifiers, and fixed tool-cycle boundaries for prefix reuse. Its optional callback targets LiteLLM Proxy 1.103.0 and supports Chat Completions, Anthropic Messages, and a stateless text Responses subset. Admission and cancellation keep CPU work bounded, including queued callers. Selected live checks confirm protocol compatibility and cache reuse inside one boundary. Native client tasks include independent acceptance failures, plus one accepted below-budget Claude research control. A source-checkout harness now preserves native traces, checks real failing-to-passing test loops and separate gold artifacts, and probes Codex sandbox readiness before inference. Public fixtures and an isolated recency comparison gateway are available; they do not replace a held-out corpus or completed whole-task comparisons. See [the evaluation record](docs/evaluation.md).

## 1. Establish trustworthy agent acceptance

Build a held-out corpus of consented Claude Code and Codex sessions spanning software repair, billing/data transformations, scheduling, policy changes, research evidence, and long tool-output analysis. Label required facts and acceptance conditions before tuning. Keep development examples separate from held-out cases.

Each task must check its final artifact with independent assertions and record terminal status, allowed write scope, tool failures, retries, and completion time. Include conflicting revisions, stale failures, indirect references, and facts without direct query overlap. A visible test pass or a retained string is insufficient for task acceptance.

**Gate:** publish reproducible fixture definitions, client/runtime versions, denominators, failures, and held-out results for both clients. Compare Sift with protocol-preserving baselines at the same forwarded-token budget. Report uncompressed results where the provider context permits them. Set quality thresholds from this baseline before evaluating candidates.

## 2. Prove total cost and latency benefits

Measure the same tasks and query sequences with and without Sift, controlling model, hardware/provider, output cap, input budget, and concurrency. Separate cold prompts, appended warm prompts, changed queries, group rollover, oversized tool results, and eviction. Repeat runs and report spread as well as averages.

Record raw and forwarded provider tokens, cached tokens, Sift CPU time, time to first token, total response time, generated tokens per second, and whole-task turns. Cost accounting must include uncached input, cached input, output, retries, and any auxiliary calls under the provider's dated prices. Estimated tokens must stay distinguishable from provider usage.

**Gate:** demonstrate lower total cost and/or latency while meeting the predetermined task-quality threshold. Publish negative and inconclusive results. A warm response following a cold response alone cannot prove a Sift speedup.

## 3. Make LiteLLM installation dependable

Keep LiteLLM responsible for public protocols, provider transport, streaming, retries, and terminal outcomes. Verify callback ordering, routing aliases, request immutability, tools, usage, and error handling against the exact supported version. Exercise cancellation and resource cleanup under concurrent requests. The stateless Responses subset and native Codex transport now have live evidence; stateful/opaque Responses remain unsupported, and successful transport does not establish correct task artifacts.

Improve admission using the route's actual tokenizer and complete serialized request where available, with explicit output and overhead reserves. Fail clearly when supported counting is unavailable or essential active work cannot fit. Document estimate drift instead of treating a gateway target as a provider guarantee.

**Gate:** a clean tagged install reproduces live requests through every advertised protocol and client, including failure and cancellation paths. Publish a supported version matrix and an upgrade procedure for the private LiteLLM counting integration. Publish to PyPI only after package installation and release provenance are reproducible.

## 4. Improve extraction from observed misses

Use held-out retention and task failures to choose algorithm changes. Investigate stale diagnostic handling, cross-turn dependencies, evidence without lexical overlap, and cache disruption at group boundaries. Preserve original roles, exact essential work, provenance, bounded CPU/memory, and the hard input budget.

For source-heavy workloads, evaluate bounded syntax or AST extraction as an opt-in candidate only when real traces show a useful gap. Compare it against the existing text selector on the same code, budgets, and acceptance tests. Measure parser/dependency cost and behavior on malformed or partial files; retain plain extraction as the predictable fallback. Add no parser framework or runtime service without measured value.

**Gate:** each added mechanism fixes a reproducible miss, improves held-out results, and has a documented cache/latency tradeoff. Keep or reject it using the same acceptance gates as the existing algorithm.

## 5. Publish an honest, maintainable tool

Keep the README, examples, GitHub description, topics, labels, and release notes consistent with verified capabilities. Maintain a clear problem statement, installation path, logo, license, and benchmark instructions. Explain remaining limitations alongside results. Avoid maturity or savings claims that exceed the evidence.

**Gate:** a new user can install the tagged package, configure a supported LiteLLM route, observe its compaction audit, and reproduce the public benchmarks from the documented steps. Release notes link changes to behavioral evidence and identify compatibility or semantic changes.

The next decision is driven by acceptance evidence: first make native client runs and their accounting reproducible, then improve whichever extraction or integration failure most limits successful, economical tasks.
