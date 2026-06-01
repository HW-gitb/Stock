import unittest
from pathlib import Path

from runners import data_canary


class DataCanaryAdvisoryBoundaryTest(unittest.TestCase):
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
