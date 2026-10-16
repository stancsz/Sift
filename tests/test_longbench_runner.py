"""Guard the structured-answer scoring boundary used by the public QA screen."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


RUNNER_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "run_longbench_v2.py"
SPEC = importlib.util.spec_from_file_location("sift_longbench_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class LongBenchRunnerTests(unittest.TestCase):
    def test_accepts_each_schema_choice(self):
        for choice in "ABCD":
            with self.subTest(choice=choice):
                self.assertEqual(runner.extract_choice(f'{{"choice":"{choice}"}}'), choice)

    def test_rejects_answers_that_cannot_be_scored_unambiguously(self):
        invalid = (
            "B",
            '{"choice":"E"}',
            '{"choice":"B","explanation":"guess"}',
            '{"choice":2}',
            '{"choice":"B"} trailing text',
            "not json",
        )
        for answer in invalid:
            with self.subTest(answer=answer):
                self.assertIsNone(runner.extract_choice(answer))

    def test_selects_primary_comparison_without_optional_compressor(self):
        self.assertEqual(
            runner.validate_arms(["full", "sift", "recency"]),
            ("full", "sift", "recency"),
        )
        self.assertEqual(runner.validate_arms(None), runner.ARMS)

    def test_arm_selection_requires_full_and_sift_without_duplicates(self):
        for arms, message in (
            (["sift", "recency"], "both full and sift"),
            (["full", "sift", "sift"], "without duplicates"),
            ([], "without duplicates"),
            (["full", "sift", "unknown"], "Unknown arms"),
        ):
            with self.subTest(arms=arms):
                with self.assertRaisesRegex(runner.EvaluationError, message):
                    runner.validate_arms(arms)

    def test_compaction_target_is_forwarded_to_selector_and_recorded(self):
        messages = [
            {"role": "system", "content": "Use the records."},
            {"role": "user", "content": "old records"},
            {"role": "assistant", "content": "Ready."},
            {"role": "user", "content": "Find the value."},
        ]
        case = {"messages": messages}
        result = SimpleNamespace(messages=messages, audit={"forwarded_tokens": 8_000})
        with patch.object(runner, "compact_messages", return_value=result) as compact:
            with patch.object(runner, "exact_prompt_tokens", return_value=8_000):
                _, details = runner.messages_for_arm(
                    case, "sift", "http://tokenizer", target_tokens=8_192,
                )
        self.assertEqual(compact.call_args.kwargs["target"], 8_192)
        self.assertTrue(details["fits_arm_limit"])

    def test_run_rejects_nonpositive_target_before_io(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            runner.run(
                Path("missing-manifest"), Path("missing-dataset"),
                Path("unused-output"), "http://tokenizer", "http://model",
                1, 1, target_tokens=0,
            )


if __name__ == "__main__":
    unittest.main()
