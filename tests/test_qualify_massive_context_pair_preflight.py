import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.qualify_massive_context_pair_preflight import qualify_pair


class MassiveContextPairPreflightTests(unittest.TestCase):
    def setUp(self):
        self.run_id = "massive-20261016-a"
        self.fingerprint = "a" * 64
        self.full = self.event(
            "full", input_tokens=612_000, forwarded_tokens=612_000, target="none")
        self.sift = self.event(
            "sift", input_tokens=612_000, forwarded_tokens=32_100, target="32768")

    def event(self, arm, *, input_tokens, forwarded_tokens, target):
        return (
            "INFO sift_benchmark_preflight "
            f"run_id={self.run_id} arm={arm} model=minimax-m3-{arm} "
            f"request_seq=1 fingerprint={self.fingerprint} "
            f"raw_tokens={input_tokens} forwarded_tokens={forwarded_tokens} "
            f"target={1_000_000 if arm == 'full' else target} "
            f"minimum_raw_tokens=500000 status=provider_blocked"
        )

    def qualify(self, full=None, sift=None, target=32_768):
        return qualify_pair(
            full_log=self.full if full is None else full,
            sift_log=self.sift if sift is None else sift,
            run_id=self.run_id, target_tokens=target,
        )

    def test_matching_provider_blocked_pair_qualifies(self):
        result = self.qualify()
        self.assertTrue(result["qualified"], result)
        self.assertEqual([], result["failures"])
        self.assertEqual(612_000, result["full_event"]["input_tokens"])
        self.assertEqual(32_100, result["sift_event"]["forwarded_tokens"])

    def test_mismatched_request_fingerprint_fails(self):
        sift = self.sift.replace(self.fingerprint, "b" * 64)
        result = self.qualify(sift=sift)
        self.assertFalse(result["qualified"])
        self.assertIn("request_fingerprint_mismatch", result["failures"])

    def test_raw_input_below_500k_fails(self):
        full = self.event(
            "full", input_tokens=499_999, forwarded_tokens=499_999, target="none")
        result = self.qualify(full=full)
        self.assertFalse(result["qualified"])
        self.assertIn("full_raw_tokens_outside_band", result["failures"])

    def test_duplicate_preflight_event_fails_closed(self):
        result = self.qualify(full=self.full + "\n" + self.full)
        self.assertFalse(result["qualified"])
        self.assertIn("duplicate_preflight_event", result["failures"])

    def test_provider_usage_event_disqualifies_either_arm(self):
        sift = self.sift + "\nINFO sift_benchmark_provider_usage arm=sift status=ok"
        result = self.qualify(sift=sift)
        self.assertFalse(result["qualified"])
        self.assertIn("provider_usage_event_present", result["failures"])

    def test_duplicate_field_fails_closed(self):
        duplicate = self.full + " raw_tokens=612000"
        result = self.qualify(full=duplicate)
        self.assertFalse(result["qualified"])
        self.assertIn("duplicate_preflight_field", result["failures"])

    def test_missing_field_fails_closed(self):
        missing = self.full.replace(f"fingerprint={self.fingerprint} ", "")
        result = self.qualify(full=missing)
        self.assertFalse(result["qualified"])
        self.assertIn("missing_preflight_fields:fingerprint", result["failures"])

    def test_sift_target_must_match_requested_positive_target(self):
        result = self.qualify(target=16_384)
        self.assertFalse(result["qualified"])
        self.assertIn("sift_target_mismatch", result["failures"])


if __name__ == "__main__":
    unittest.main()
