"""Type-strict checks for aggregate-only rehearsal output."""

import unittest

from benchmarks.quarantine_rehearsal import json_exact_match


EXPECTED = {
    "schema_version": 1,
    "benchmark": "synthetic-quarantine-rehearsal",
    "tasks_completed": 2,
    "arms": [
        {"name": "full", "task_count": 2, "accepted_count": 1, "input_tokens": 2800},
        {"name": "sift", "task_count": 2, "accepted_count": 2, "input_tokens": 1600},
    ],
}


class AggregateJsonValidationTests(unittest.TestCase):
    def test_accepts_the_exact_expected_aggregate(self):
        self.assertTrue(json_exact_match(EXPECTED, EXPECTED))

    def test_rejects_boolean_for_integer_schema_version(self):
        malformed = {**EXPECTED, "schema_version": True}
        self.assertFalse(json_exact_match(malformed, EXPECTED))

    def test_rejects_boolean_for_nested_integer_count(self):
        malformed = {**EXPECTED, "arms": [dict(EXPECTED["arms"][0]), EXPECTED["arms"][1]]}
        malformed["arms"][0]["accepted_count"] = True
        self.assertFalse(json_exact_match(malformed, EXPECTED))

    def test_rejects_extra_nested_fields(self):
        malformed = {**EXPECTED, "arms": [dict(EXPECTED["arms"][0]), EXPECTED["arms"][1]]}
        malformed["arms"][0]["task_ids"] = ["private"]
        self.assertFalse(json_exact_match(malformed, EXPECTED))


if __name__ == "__main__":
    unittest.main()
