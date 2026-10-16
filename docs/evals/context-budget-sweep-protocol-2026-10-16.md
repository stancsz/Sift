# Context-budget sweep protocol

**Status: study design, not a result or a selected default.** The purpose is to
find where additional selected context improves accepted answers enough to
justify its extra prefill, cache, and KV cost.

## Terms

- **Model context window** is the maximum rendered request plus generated output
  the model/runtime accepts.
- **Input target** is the maximum rendered request Sift forwards. It is an
  application policy, not a model setting and not a KV-cache allocation.
- **Output reserve** is the generation budget, including any reasoning tokens.
- **Runtime capacity** is the memory available for live KV state and concurrent
  requests. It must be measured from the selected backend and hardware.

For each request, require `input target + output reserve + measured template /
tokenizer safety margin <= model context window`. Count the complete rendered
request with that model's tokenizer. Sift currently accepts a fixed positive
target per configured model alias; it does not discover a route's context
window or adjust the target per request. Its target also does not promise the
provider will accept the request or that KV memory is available.

## Why sweep

A larger target can retain more evidence and reduce extraction loss. It also
increases prompt prefill and per-request KV state, and can lower concurrency.
More context does not guarantee better use of evidence: performance on long
inputs can depend on where evidence appears ([Lost in the Middle](https://arxiv.org/abs/2307.03172)).
The amount of task-relevant evidence, rather than the largest supported window,
should determine the useful target. Sift may help at every target by selecting
evidence from a larger raw history, but that benefit and answer quality must be
measured at each budget.

## Feasible first stage: current 32K Qwen runtime

The existing local Qwen benchmark declares a 32,768-token window and reserves
4,096 tokens for output, leaving a maximum of 28,672 exact input tokens before
any additional safety margin. Its current 24,576 Sift estimate is not the same
as an exact provider-token limit. The 32K runtime cannot test 32K input, much
less 48K or 64K input.

On a fresh, independently frozen set of tasks, compare estimated Sift targets
of 8,192, 16,384, 20,480, and 24,576. Add a fifth target only if the runtime
margin is measured and leaves room below 28,672. At every target compare full
context when it fits, Sift, and complete-unit recency at equal exact input
ceilings. Use the same model, generation reserve, prompt, tools, cache policy,
and tasks. Include cases where required evidence is actually beyond each
smaller target; otherwise the sweep cannot reveal a quality/retention benefit.

Existing LongBench runs at 24,576 are public development results and must not
be reused as a blind target-selection holdout. They can inform task strata and
engineering estimates only.

## Long-window stage

To test 32K through 64K selected inputs, use a model/runtime with at least a
73,728-token measured context window: 65,536 input plus a fixed 4,096 output
reserve and 4,096 template/tokenizer margin. Prefer the same model at a fixed
context setting for all arms. Compare 24,576, 32,768, 49,152, and 65,536 input targets, plus full
context when it fits. If a different model is required, treat it as a separate
replication, not a direct continuation of the 32K Qwen curve.

Before an inference run, confirm the intended context setting, tokenizer count,
KV cache capacity, concurrency, and memory placement from the backend. Record
OOMs, context rejections, and admission failures as capacity outcomes. Do not
infer KV capacity from the model's advertised context window.

## Optional dynamic policy arm

Only after the fixed-target curve is available, test one dynamic policy against
the best fixed target. Freeze the rule before using hidden cases. A minimal
candidate is `min(configured_input_ceiling, model_context - output_reserve -
safety_margin)`, with those inputs supplied by the route configuration. This
adapts to known route capacity; it does not estimate which individual task
needs more context. A task-adaptive selector would require an independently
validated demand signal and a separate arm.

Changing selected length or membership can change the shared prompt prefix and
therefore cache reuse. Test cold and warm/cache-reuse runs separately, retain
the same conversation prefix where the policy permits it, and report actual
cached tokens. Do not assume a larger target preserves cache hits.

## Measures and decision

Freeze independent cases, required evidence, scoring code, model/version,
runtime flags, Sift source hash, targets, output reserve, and run order before
generation. Randomize arms within case and target. Run at least three
generations per task/arm/target for screening; analyze at task level. Keep
timeouts, context errors, invalid outputs, and failed tasks in the denominator.

Report per target and task domain:

- accepted-task rate, answer accuracy, required-fact coverage, unsupported
  claims, and harmful full-correct/Sift-wrong task pairs;
- exact forwarded input, cached input, output and reasoning tokens;
- Sift preprocessing CPU/wall time and peak host memory;
- TTFT, end-to-end time, decode tokens/second, throughput under the same
  concurrency, and backend KV usage/admission failures;
- measured provider charges where applicable, and cost per accepted task.

Select the smallest target whose task-level quality meets the predeclared
acceptance criterion, then report its quality/latency/cost tradeoff against
larger budgets. Do not pick a target from token reduction, a single speed
metric, or a one-model result alone. Do not claim that larger targets make
answers sharper unless blinded scoring supports that claim.

## Current decision

Keep 24,576 as the existing benchmark setting, not as a proven optimum. The
next useful local result is a fresh 8K/16K/20K/24,576 sweep on a hidden task
set. A 32K-to-64K input comparison is not currently testable on the declared
32K local runtime; it needs a separate long-window runtime and its memory/KV
capacity checks. The existing Sift implementation can already run at explicit
targets, so this investigation does not require a runtime feature change.
