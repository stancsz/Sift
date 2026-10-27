"""Reproduce recall regression before and after the localized anchor repair."""
import gzip
import io
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tests import test_issue59_history_recall as cases


def main():
    sources = json.loads(gzip.decompress((Path(__file__).parent / "release-0.11.0-sources.json.gz").read_bytes()))
    baseline = types.ModuleType("sift_issue59_released_baseline")
    sys.modules[baseline.__name__] = baseline
    exec(compile(sources["sift/core.py"], "released-0.11.0-core.py", "exec"), baseline.__dict__)
    current = cases.compact_messages
    results = {}
    try:
        for label, implementation in (("released_0_11_0", baseline.compact_messages), ("current", current)):
            cases.compact_messages = implementation
            output = io.StringIO()
            result = unittest.TextTestRunner(stream=output).run(unittest.defaultTestLoader.loadTestsFromTestCase(cases.HistoryRecallTests))
            results[label] = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                              "failed_cases": [str(test) for test, _ in result.failures]}
    finally:
        cases.compact_messages = current
    assert results["released_0_11_0"]["failures"] > 0 and results["released_0_11_0"]["errors"] == 0
    assert results["current"]["failures"] == results["current"]["errors"] == 0
    print(json.dumps({"verified": True, "scope": "Generic source-history regressions, not live matrix acceptance", "results": results}, indent=2))


if __name__ == "__main__":
    main()
