# Dynamic budgets for local inference

The defaults describe a reference 69,632-token local profile, not model discovery or a universal context size. Set `context_window` and reservations from the model's actual loaded configuration. This pure library API is separate from the LiteLLM hook's explicit static model targets; it is not automatically enabled there.

`sift.dynamic.compact_dynamic` chooses a working budget before delegating to the existing deterministic CPU compactor. It accepts the same message protocols and caller-supplied token counter as `compact_messages`.

```python
from sift import compact_dynamic

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

The target adapts to the native raw request size under one unchanged configuration. Requests at or below `preferred_target` use that anchor (bounded by available capacity); larger requests use `ceil(raw_tokens / compression_ratio)`, with `compression_ratio=8` by default. Targets stay between `min_target` and `min(max_target, context_window - output_reserve - fixed_tokens)`. The ratio must be finite and at least one. The anchor preserves small requests; it is not a fixed forwarding target or a difficulty classifier. For example, an 80k history gets a 24,576 budget, a 256k history gets 32k, and a 1M history gets 65,536 when the window supports it. Actual forwarded counts may be smaller.

All integer limits reject booleans. The character/node bounds run before counting, and the native raw ceiling is enforced before selection. Insufficient capacity or oversized mandatory content fails closed. System/current work and complete protected tool groups retain the existing compactor's guarantees.

The caller owns the counter and must account for the actual model template, tools, and fixed request fields. When the counter already includes tool/schema overhead, do not also reserve that overhead in `fixed_tokens`; the local gateway uses that field only for 256 decoder headroom tokens. An estimate does not establish model context fit. The local gateway uses the native full-request tokenizer for selection and independently counts the final request before forwarding. Do not call a 1M-byte history a 1M-token test.

With a loaded 40,960 context window and 4,096 output tokens plus 256 headroom reserved, the supported adaptive range is 24,576–36,608. A 69,888 window supports up to 65,536 with those reservations. Choosing a larger target never resizes GPU KV capacity or frees VRAM. The adapter is not a learned memory store or a guarantee of information retention. Original source material should remain available for retrieval.

The [local-inference integration](https://github.com/stancsz/local-inference) uses this API as a mandatory boundary in front of llama.cpp's native Anthropic Messages endpoint. Consult its runtime evidence for actual model throughput and task acceptance; this adapter's unit tests establish neither.
