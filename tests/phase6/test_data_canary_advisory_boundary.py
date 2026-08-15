import unittest
import sys
from pathlib import Path
from unittest.mock import patch

from runners import data_canary


class DataCanaryAdvisoryBoundaryTest(unittest.TestCase):
    def test_invalid_official_binding_is_skipped_and_bounded_fallback_continues(self) -> None:
        with patch.object(data_canary, "_find_candidates",
                          side_effect=[ValueError("binding drift"), Path("valid.csv")]) as find:
            path, as_of = data_canary._find_latest_candidates_within(days=1)
        self.assertEqual(path, Path("valid.csv"))
        self.assertIsNotNone(as_of)
        self.assertEqual(find.call_count, 2)

    def test_direct_candidate_binding_failure_is_a_no_candidates_skip(self) -> None:
        with patch.object(data_canary, "ak", object()), \
                patch.object(data_canary, "_find_candidates",
                             side_effect=ValueError("binding drift")), \
                patch.object(data_canary, "_write_log", return_value=Path("canary.json")) as write_log, \
                patch.object(sys, "argv", ["data_canary.py", "--as-of", "20260727"]):
            result = data_canary.main()
        self.assertEqual(result, 0)
        self.assertEqual(write_log.call_args.args[0]["status"], "skipped_no_candidates")

    def test_skip_payload_carries_non_evidence_scope(self) -> None:
        payload = data_canary._skip_payload(
            "20260601",
            "skipped_no_candidates",
            "No candidates.",
        )

        self.assertEqual(payload["evidence_role"], "advisory_sidecar")
        self.assertEqual(
            payload["gate_effect"],
            "never_blocks_screening_or_ship_gate",
        )
        self.assertIs(payload["data_passed_claim"], False)
        self.assertIs(payload["ship_gate_evidence"], False)
        self.assertIn("must not be used as data_passed", payload["scope_note"])
        self.assertEqual(
            payload["summary"]["overall_status"],
            "skipped_no_candidates",
        )

    def test_console_summary_avoids_pipeline_pass_language(self) -> None:
        message = data_canary._advisory_summary_message(
            overall="ok",
            missing=0,
            n_error=0,
            n_warn=0,
            sample_size=5,
            row_count=10,
            tier="Tier1",
            out=Path("logs/data_canary_20260601.json"),
        )

        self.assertIn("[ADVISORY-OK]", message)
        self.assertNotIn("[OK]", message)
        self.assertIn("not a data-pass", message)
        self.assertIn("not a ship-gate signal", message)


if __name__ == "__main__":
    unittest.main()
