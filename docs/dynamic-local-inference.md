# Dynamic budgets for local inference

`sift.dynamic.compact_dynamic` chooses a working budget before delegating to the existing deterministic CPU compactor. It accepts the same message protocols and caller-supplied token counter as `compact_messages`.

```python
from sift.dynamic import compact_dynamic

result = compact_dynamic(
    messages,
    count_tokens,
    context_window=69_632,
    output_reserve=4_096,
    min_target=24_576,
    max_target=65_536,
    preferred_target=32_768,
    fixed_tokens=tool_schema_and_template_tokens,
    raw_limit=1_050_000,
    protocol="anthropic",
)
```

The target is bounded by the preferred target, maximum target, and `context_window - output_reserve - fixed_tokens`. It is clamped to the minimum target only when that minimum fits; otherwise the adapter fails closed. All token limits must be integers; booleans are rejected. Mandatory current work retains the existing compactor's fail-closed behavior.

The caller owns the counter and must account for the actual model template, tools, and fixed request fields. An estimate does not establish model context fit. A proxy may select excerpts with a cheap estimate and independently enforce the final native template token count before forwarding. Do not call a 1M-byte history a 1M-token test.

The adapter is a per-request budget policy, not a learned memory store or a guarantee of information retention. Changing hardware/context profiles or output reservation changes the available working set. Original source material should remain available for retrieval.

The [local-inference integration](https://github.com/stancsz/local-inference) uses this API as a mandatory boundary in front of llama.cpp's native Anthropic Messages endpoint. Consult its runtime evidence for actual model throughput and task acceptance; this adapter's unit tests establish neither.
