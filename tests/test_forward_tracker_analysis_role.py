"""The policy comparator needs the official final/watch split in its tracker."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.forward_tracker import (  # noqa: E402
    SCHEMA_COLUMNS, TRACKER_STRING_COLUMNS, _candidate_row, _decision_cohort_matches,
)


class ForwardTrackerAnalysisRoleTests(unittest.TestCase):
    def test_capture_preserves_analysis_role(self):
        row = _candidate_row("20260725", "2026-07-25T10:00:00+08:00", "run", "a" * 64,
                             {"ts_code": "000001.SZ", "analysis_role": "final"}, l3_mode="today")
        self.assertIn("analysis_role", SCHEMA_COLUMNS)
        self.assertEqual(row["analysis_role"], "final")
        self.assertIn("ret_10d_t1_net_unit", SCHEMA_COLUMNS)
        self.assertEqual(row["ret_10d_t1_net_unit"], "percentage_points")
        self.assertIn("runtime_configuration_fingerprint", SCHEMA_COLUMNS)

    def test_capture_preserves_runtime_configuration_fingerprint(self):
        row = _candidate_row(
            "20260725", "2026-07-25T10:00:00+08:00", "run", "a" * 64,
            {"ts_code": "000001.SZ", "analysis_role": "final"}, l3_mode="today",
            runtime_configuration_fingerprint="b" * 64,
        )
        self.assertEqual(row["runtime_configuration_fingerprint"], "b" * 64)

    def test_capture_projects_theme_source_and_l3_snapshot_without_rewriting_clocks(self):
        taxonomy = {
            "source_as_of": "20260810",
            "l3_provenance": {
                "provider": "hithink_finance",
                "snapshot_date": "20260810",
                "coverage_digest": "c" * 64,
                "coverage_complete": True,
                "scoring_universe": "a_share_main_board",
                "validation_status": "verified_complete",
            },
        }
        row = _candidate_row(
            "20260810", "2026-08-10T15:00:00+08:00", "run", "a" * 64,
            {"ts_code": "000001.SZ", "analysis_role": "final",
             "catalyst": {"theme_taxonomy": taxonomy}},
            l3_mode="today", decision_as_of="20260810", run_date="20260810",
            price_data_through="20260807",
        )
        self.assertEqual(row["theme_taxonomy_source_as_of"], "20260810")
        self.assertEqual(row["theme_taxonomy_l3_snapshot_date"], "20260810")
        self.assertEqual(row["price_data_through"], "20260807")

    def test_same_identity_with_runtime_or_strategy_drift_is_not_identical(self):
        row = _candidate_row(
            "20260725", "2026-07-25T10:00:00+08:00", "run", "a" * 64,
            {"ts_code": "000001.SZ", "analysis_role": "final"}, l3_mode="today",
            runtime_configuration_fingerprint="b" * 64,
        )
        existing = pd.DataFrame([row], columns=SCHEMA_COLUMNS)
        changed_runtime = existing.copy()
        changed_runtime["runtime_configuration_fingerprint"] = "c" * 64
        changed_field = existing.copy()
        changed_field["theme_fit_pass"] = True
        self.assertFalse(_decision_cohort_matches(existing, changed_runtime))
        self.assertFalse(_decision_cohort_matches(existing, changed_field))

    def test_csv_roundtrip_missing_values_remain_idempotently_identical(self):
        row = _candidate_row(
            "20260725", "2026-07-25T10:00:00+08:00", "run", "a" * 64,
            {"ts_code": "000001.SZ", "analysis_role": "final"}, l3_mode="today",
            runtime_configuration_fingerprint="b" * 64,
        )
        incoming = pd.DataFrame([row], columns=SCHEMA_COLUMNS)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tracker.csv"
            incoming.to_csv(path, index=False, encoding="utf-8-sig")
            roundtripped = pd.read_csv(path, dtype=TRACKER_STRING_COLUMNS)
        self.assertTrue(_decision_cohort_matches(roundtripped, incoming))


if __name__ == "__main__":
    unittest.main()
