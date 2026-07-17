"""Live-only forward comparison tests; all inputs are synthetic/local."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_theme_forward_comparison import evaluate_theme_forward_comparison  # noqa: E402


def _row(as_of: str, ts_code: str = "000001.SZ", *, live: bool = True, run_id: str | None = None) -> dict:
    row = {
        "as_of": as_of, "ts_code": ts_code, "run_id": run_id or f"run-{as_of}",
        "candidate_digest": f"digest-{as_of}", "industry_heat_score": 20.0,
        "industry_trend": "headwind", "industry_trend_source_as_of": as_of,
        "industry_trend_classifier_version": "industry_heat_trend_v1",
        "industry_trend_source_id": "A-EGS.industry_heat_score",
        "industry_trend_headwind_max": 20.0, "industry_trend_tailwind_min": 80.0,
        "industry_trend_configuration_fingerprint": "a" * 64,
        "industry_trend_validation_status": "valid",
        "raw_concept_ids": json.dumps(["c1", "c6"]),
        "canonical_themes_json": json.dumps([{"theme_id": "physical_ai", "role": "core"}]),
        "canonical_theme_ids": json.dumps(["physical_ai"]),
        "canonical_theme_roles": json.dumps({"physical_ai": "core"}),
        "canonical_theme_role_confidence": json.dumps({"physical_ai": "medium"}),
        "theme_taxonomy_configuration_fingerprint": "b" * 64,
        "theme_taxonomy_source_as_of": as_of,
        "theme_taxonomy_l3_provider": "hithink_finance",
        "theme_taxonomy_l3_snapshot_date": as_of,
        "theme_taxonomy_l3_coverage_digest": "c" * 64,
        "theme_taxonomy_l3_coverage_complete": True,
        "theme_taxonomy_l3_scoring_universe": "a_share_main_board",
        "theme_taxonomy_l3_validation_status": "verified_complete",
        "theme_heat_score": 80.0, "theme_breadth_pass": True,
        "theme_persistence_mult": 1.0, "theme_fit_score": 0.8, "theme_fit_pass": True,
        "forward_live": live, "historical_replay": not live,
    }
    for window in (5, 10, 20):
        row[f"ret_{window}d_status"] = "ok"
        row[f"ret_{window}d_t1_net"] = 0.01
        row[f"ret_{window}d_excess_csi300"] = 0.002
        row[f"ret_{window}d_excess_csi1000"] = -0.001
    return row


class ThemeForwardComparisonTests(unittest.TestCase):
    def test_manual_review_is_due_at_12_live_weeks_but_never_auto_promotes(self):
        dates = pd.date_range("2026-01-02", periods=12, freq="7D").strftime("%Y%m%d")
        packet = evaluate_theme_forward_comparison(pd.DataFrame([_row(day) for day in dates]))
        self.assertEqual(packet["review_status"], "review_due")
        self.assertTrue(packet["manual_review_required"])
        self.assertFalse(packet["comparison_boundary"]["automatic_promotion"])
        role = next(group for group in packet["groups"]
                    if group["dimension"] == "business_role" and group["key"] == "core")
        self.assertEqual(role["horizons"]["20d"]["net"]["matured_count"], 12)

    def test_historical_replay_is_excluded_from_counted_forward_evidence(self):
        tracker = pd.DataFrame([_row("20260102"), _row("20260109", live=False)])
        packet = evaluate_theme_forward_comparison(tracker)
        self.assertEqual(packet["forward_live_rows_counted"], 1)
        self.assertEqual(packet["excluded_non_live_or_replay_rows"], 1)
        self.assertEqual(packet["review_status"], "accumulating")

    def test_same_day_identity_drift_is_rejected(self):
        rows = [_row("20260102", "000001.SZ", run_id="run-a"),
                _row("20260102", "000002.SZ", run_id="run-b")]
        with self.assertRaisesRegex(ValueError, "ambiguous/missing run identity"):
            evaluate_theme_forward_comparison(pd.DataFrame(rows))

    def test_unavailable_industry_signal_is_excluded_without_losing_valid_forward_rows(self):
        unavailable = _row("20260102", "000002.SZ")
        unavailable["industry_trend_validation_status"] = "unavailable"
        unavailable["industry_trend"] = "unknown"
        packet = evaluate_theme_forward_comparison(pd.DataFrame([_row("20260102"), unavailable]))
        self.assertEqual(packet["forward_live_rows_counted"], 1)
        self.assertEqual(packet["excluded_non_live_or_replay_rows"], 0)
        self.assertEqual(packet["excluded_unavailable_industry_rows"], 1)

    def test_all_unavailable_industry_signal_reports_insufficient_data(self):
        unavailable = _row("20260102")
        unavailable["industry_trend_validation_status"] = "unavailable"
        unavailable["industry_trend"] = "unknown"
        packet = evaluate_theme_forward_comparison(pd.DataFrame([unavailable]))
        self.assertEqual(packet["forward_live_rows_counted"], 0)
        self.assertEqual(packet["review_status"], "insufficient_data")
        self.assertEqual(packet["groups"], [])

    def test_unavailable_industry_signal_does_not_relax_same_day_identity(self):
        unavailable = _row("20260102", "000002.SZ", run_id="other-run")
        unavailable["industry_trend_validation_status"] = "unavailable"
        with self.assertRaisesRegex(ValueError, "ambiguous/missing run identity"):
            evaluate_theme_forward_comparison(pd.DataFrame([_row("20260102"), unavailable]))

    def test_taxonomy_source_clock_must_equal_its_forward_cohort(self):
        stale_taxonomy = _row("20260102")
        stale_taxonomy["theme_taxonomy_source_as_of"] = "20260101"
        with self.assertRaisesRegex(ValueError, "theme taxonomy source-clock mismatch"):
            evaluate_theme_forward_comparison(pd.DataFrame([stale_taxonomy]))

    def test_boolean_industry_score_is_not_valid_forward_lineage(self):
        malformed = _row("20260102")
        malformed["industry_heat_score"] = True
        with self.assertRaisesRegex(ValueError, "invalid industry_trend value lineage"):
            evaluate_theme_forward_comparison(pd.DataFrame([malformed]))

    def test_forward_live_taxonomy_requires_complete_hithink_receipt(self):
        malformed = _row("20260102")
        malformed["theme_taxonomy_l3_provider"] = "legacy_tushare_snapshot"
        malformed["theme_taxonomy_l3_validation_status"] = "legacy_snapshot"
        with self.assertRaisesRegex(ValueError, "lacks a HiThink taxonomy provider receipt"):
            evaluate_theme_forward_comparison(pd.DataFrame([malformed]))


if __name__ == "__main__":
    unittest.main()
