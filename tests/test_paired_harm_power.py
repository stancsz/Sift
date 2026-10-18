import unittest

from benchmarks.paired_harm_power import plan_sample_size


class PairedHarmPowerTests(unittest.TestCase):
    def test_zero_harm_floor_is_149_independent_tasks(self):
        plan = plan_sample_size(0.0)
        self.assertEqual(plan["tasks"], 149)
        self.assertEqual(plan["critical_harmful_discordances"], 0)
        self.assertLessEqual(plan["type_i_probability"], 0.05)
        self.assertGreater(0.98**148, 0.05)

    def test_planning_sensitivity_uses_fixed_exact_error_and_power_gates(self):
        expected = {0.005: 386, 0.01: 969, 0.015: 4318}
        for assumed_rate, expected_tasks in expected.items():
            with self.subTest(assumed_rate=assumed_rate):
                plan = plan_sample_size(assumed_rate)
                self.assertEqual(plan["tasks"], expected_tasks)
                self.assertLessEqual(plan["type_i_probability"], 0.05)
                self.assertGreaterEqual(plan["power"], 0.80)

    def test_rejects_an_assumption_at_or_above_the_margin(self):
        with self.assertRaises(ValueError):
            plan_sample_size(0.02)


if __name__ == "__main__":
    unittest.main()
