# Public development gold: incremental build planner

Ported without changing the original five acceptance checks in `test_build_holdout.py` or the later two README contract regressions in `test_postrun_contract.py`. These seven checks are all predeclared for the new portable case. Their earlier experimental chronology remains in the original test module docstring. This is public development evidence, not a private held-out benchmark.

The client receives only `benchmarks/agent_cases/build_planner`. Copy these `test_*.py` files into a separate post-run acceptance workspace containing the delivered implementation and unchanged case files. The case has six visible tests; the combined acceptance workspace has thirteen tests. No reference implementation or answer file is included in either directory.
