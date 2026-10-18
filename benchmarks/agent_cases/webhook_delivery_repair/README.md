# Webhook delivery repair (development fixture)

This is a public, authored development fixture for native-agent evaluation. It is not held-out evidence and must not be described as benchmark validation. All names, endpoints, payloads, and incident records are fictional.

## Task

Repair the existing Python webhook dispatcher in `dispatcher.py` so it follows the current contract in `docs/delivery_policy.md`. Read the policy, endpoint configuration, operational notes, and incident log before changing code. The incident log shows symptoms, not policy. `test_task.py` is the visible contract. Edit only `dispatcher.py`; do not change tests, policy, endpoint configuration, or logs. Use Python's standard library only.

Run the visible suite from this directory:

```sh
python -m unittest -q
```

The independent acceptance suite lives outside this case directory and is not part of the task prompt. The gold tests are separately frozen under `benchmarks/agent_gold/webhook_delivery_repair/`.
