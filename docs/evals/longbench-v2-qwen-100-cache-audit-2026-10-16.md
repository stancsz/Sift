# LongBench v2 100-task cache-protocol audit, 2026-10-16

This note records a protocol limitation discovered while the frozen 100-task
Qwen run was in progress. It does not modify the frozen sample or alter the
active run.

The runner sends `cache_prompt: false`, which disables the request-level prefix
reuse path. The serving container runs llama.cpp `0.6.0-dev` build `11610`,
commit `091b6a7fc`, with `--parallel 1`; its command omits `--cache-ram 0` and
`--no-cache-idle-slots`. Server logs repeatedly report that prompt-cache
entries are being evicted. Upstream documents the server RAM cache and idle-slot
cache as separately controlled mechanisms; the request field alone does not
disable them ([pinned server source](https://github.com/ggml-org/llama.cpp/blob/091b6a7fc561b78da90a0ed2d524ec995458c657/tools/server/server-context.cpp),
[pinned server options](https://github.com/ggml-org/llama.cpp/blob/091b6a7fc561b78da90a0ed2d524ec995458c657/tools/server/README.md)).

The frozen protocol's phrase “prompt cache disabled” was therefore too broad:
it described the request payload, not every cache mechanism in the server. No
cross-task answer leakage has been demonstrated in this run. Upstream reports
of cache-state contamination are relevant risk evidence, but their exact
reproduction conditions do not establish corruption in this serial,
one-slot run ([issue #27148](https://github.com/ggml-org/llama.cpp/issues/27148),
[issue #30129](https://github.com/ggml-org/llama.cpp/issues/30129)).

Treat this run as exploratory and do not use its scores as clean quality-parity
evidence. Preserve the completed calls for forensic comparison. A confirmatory
rerun must keep the frozen manifest, prompts, model, scoring and serial request
order, while launching the server with RAM and idle-slot caches explicitly
disabled (`--cache-ram 0 --no-cache-idle-slots`) in addition to the request's
`cache_prompt: false`. Record the actual server command and build with the
results. Timing from the initial run is cache-condition-specific and should not
be compared with a cache-disabled run as if only Sift changed.
