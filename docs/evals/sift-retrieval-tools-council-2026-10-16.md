# Sift retrieval tools design council, 2026-10-16

## Decision

Keep Sift's compactor stateless. If model-directed retrieval is tested, prototype an optional client-side MCP plain-code-search tool first. Defer AST parsing, LiteLLM-integrated tool execution, and omitted-conversation-history retrieval until a plain-search experiment shows value.

## Evidence and constraints

Sift currently receives one request in its LiteLLM Proxy callback, compacts source excerpts to a token target, and stores no conversation history or session state. The gateway cannot assume access to a caller's local workspace. LiteLLM owns provider protocols and tool-call transport. An MCP client tool can access the agent's local code while preserving Sift's single-pass role.

The council distinguished local code retrieval from omitted-history retrieval. Caller-owned history could be searched without adding gateway session storage, but that is a separate experiment with its own source-of-truth, privacy, provenance, and token-cost questions.

## Council recommendation

Gemini 4 Argon recommended a minimal client-side MCP plain-search prototype for local code, deferring AST and history retrieval. GPT-6.1 Sol agreed, adding explicit acceptance metrics: compare full-context, Sift-only, and Sift-plus-search over identical fixtures; require improved evidence retention over Sift, full-context answer quality, unchanged citation accuracy, lower cache-adjusted total token cost than full context, and p95 latency no greater than 1.2 times Sift-only. Record retrieval tokens, additional round trips, and prefix-cache hit rates. Stop if gains disappear after retrieval overhead/cache loss; do not add AST dependencies before plain search passes.

## Receipt

- Gemini 4 Argon request: `chatcmpl-agy-3f8616479423`; 3,032 reported tokens; 11.507 seconds.
- GPT-6.1 Sol request: `chatcmpl-codex-advisor-7063331906cb`; 975 reported tokens; 13.532 seconds.
- Packet: 1,755 characters; council mode.
- `decision_changed: false`: this confirmed the worker's MCP direction; it sharpened the separation between workspace search and caller-owned history retrieval and supplied measurable stop criteria.
- Two local invocations failed before any provider request: the first because `.runs` did not exist; the second because the `py` launcher resolved to an unavailable Windows Store Python alias. After creating the ignored directory and selecting the installed `python.exe`, the single council call completed. No provider retry occurred.

This is design advice, not implementation or acceptance evidence. No retrieval endpoint, MCP tool, parser dependency, or persistent store was added by this consultation.
