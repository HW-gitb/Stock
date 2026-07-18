import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import jsonschema
import pandas as pd

from runners.a_short_crash_veto_tracker import (
    build_summary,
    decide_design,
    detect_crash_codes,
    evaluate_cohort,
    latest_settled_trade_date,
    main,
    match_controls,
    run_update,
)
from runners.a_short_m67_render import render_weekly_markdown
from runners.a_short_weekly_pipeline import build_weekly_report


ROOT = Path(__file__).resolve().parents[1]


class CrashVetoTrackerTest(unittest.TestCase):
    def test_confirmed_day_window_includes_fifth_but_not_sixth(self):
        dates = [f"202607{14-i:02d}" for i in range(7)]

        def rows(code, crash_index):
            out = []
            for i, day in enumerate(dates):
                if i == crash_index:
                    out.append({"ts_code": code, "trade_date": day, "open": 10.0, "high": 10.0,
                                "low": 9.0, "close": 9.1, "pre_close": 10.0, "pct_chg": -9.0})
                else:
                    out.append({"ts_code": code, "trade_date": day, "open": 9.2, "high": 9.4,
                                "low": 9.0, "close": 9.2, "pre_close": 9.2, "pct_chg": 0.0})
            return out

        daily = pd.DataFrame(rows("FIFTH.SZ", 5) + rows("SIXTH.SZ", 6))
        self.assertEqual(detect_crash_codes(daily, {"FIFTH.SZ", "SIXTH.SZ"}, 4), set())
        self.assertEqual(detect_crash_codes(daily, {"FIFTH.SZ", "SIXTH.SZ"}, 5), {"FIFTH.SZ"})

    def test_latest_settled_boundary_uses_egs_daily_max_not_wall_clock(self):
        daily = pd.DataFrame({"trade_date": ["20260710", "20260713", "bad", None]})
        self.assertEqual(latest_settled_trade_date(daily), "20260713")

    def test_controls_exclude_members_and_prefer_same_l2(self):
        features = pd.DataFrame([
            {"ts_code": "M", "l1_name": "L1", "l2_name": "L2", "total_mv": 100, "pct_20d": 1, "avg_amount_20d": 1000},
            {"ts_code": "A", "l1_name": "L1", "l2_name": "L2", "total_mv": 101, "pct_20d": 1, "avg_amount_20d": 1000},
            {"ts_code": "B", "l1_name": "L1", "l2_name": "L2", "total_mv": 99, "pct_20d": 1, "avg_amount_20d": 1000},
            {"ts_code": "C", "l1_name": "L1", "l2_name": "L2", "total_mv": 102, "pct_20d": 1, "avg_amount_20d": 1000},
            {"ts_code": "D", "l1_name": "OTHER", "l2_name": "OTHER", "total_mv": 100, "pct_20d": 1, "avg_amount_20d": 1000},
        ]).set_index("ts_code", drop=False)
        matched = match_controls(["M"], ["M", "A", "B", "C", "D"], features)
        self.assertEqual(set(matched["M"]), {"A", "B", "C"})
        self.assertNotIn("M", matched["M"])

    @staticmethod
    def _price_cache(codes):
        dates = [f"202607{d:02d}" for d in range(1, 12)]
        rows = []
        for code, exit_close in codes.items():
            for i, day in enumerate(dates):
                rows.append({"ts_code": code, "trade_date": day, "open": 10.0, "high": 10.5,
                             "low": 9.5, "close": exit_close if i in (5, 10) else 10.0,
                             "adj_factor": 1.0, "up_limit": 11.0})
        return {"trade_dates": dates, "stocks": pd.DataFrame(rows), "coverage": {}}

    def test_evaluation_keeps_missing_rows_visible(self):
        cohort = {"as_of": "20260701", "member_count": 2, "members": [
            {"ts_code": "M1", "controls": ["C1", "C2", "C3"]},
            {"ts_code": "MISSING", "controls": ["C1", "C2", "C3"]},
        ]}
        metric = evaluate_cohort(cohort, self._price_cache({"M1": 11.0, "C1": 10.0, "C2": 10.0, "C3": 10.0}), 5)
        self.assertEqual(metric["paired_count"], 1)
        self.assertEqual(metric["status_counts"]["missing_or_suspended_entry"], 1)
        self.assertGreater(metric["mean_paired_excess_pct"], 9.0)

    def test_decision_requires_both_horizons_and_downside_not_worse(self):
        good = {"status": "ready", "paired_count": 30, "mean_paired_excess_pct": 1.2,
                "outperform_rate": 0.65, "blocked_mean_mae_pct": -3.0, "control_mean_mae_pct": -3.2,
                "blocked_loss_gt_5_rate": 0.1, "control_loss_gt_5_rate": 0.1}
        good_decision = decide_design(good, good)
        self.assertEqual(good_decision[0], "change_candidate")
        self.assertIn("设计需要调整", good_decision[1])
        pending = dict(good, paired_count=10)
        self.assertEqual(decide_design(good, pending)[0], "insufficient_keep")
        bad = dict(good, mean_paired_excess_pct=-1.5, outperform_rate=0.3)
        self.assertEqual(decide_design(bad, bad)[0], "keep")

    def test_summary_and_weekly_report_keep_legacy_and_incremental_separate(self):
        state = {"cohorts": [
            {"cohort_id": "crash-veto-" + "1" * 20, "as_of": "20260714", "scope": "legacy_official_4d",
             "rule_confirmed_days": 4, "member_count": 245, "members": [{"ts_code": "OLD", "controls": ["C"]}]},
            {"cohort_id": "crash-veto-" + "2" * 20, "as_of": "20260714", "scope": "active_5d_incremental_rank_impact",
             "rule_confirmed_days": 5, "member_count": 55, "members": [{"ts_code": "NEW", "controls": ["C"]}]},
        ]}
        summary = build_summary(state, {"trade_dates": [], "stocks": pd.DataFrame()}, "20260714")
        self.assertEqual([v["member_count"] for v in summary["variants"]], [245, 55])
        self.assertEqual(summary["final_decision"]["basis_cohort_ids"],
                         ["crash-veto-" + "1" * 20, "crash-veto-" + "2" * 20])
        self.assertIn("245", summary["one_week_plain"])
        schema = json.loads((ROOT / "schemas" / "a_short_crash_veto_tracking.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(summary, schema)
        weekly = build_weekly_report([], "20260714", "2026-07-14T00:00:00+08:00", crash_veto_tracking=summary)
        rendered = render_weekly_markdown(weekly)
        self.assertIn("最终结论", rendered)
        self.assertIn("旧4日口径官方被拦组", rendered)
        self.assertIn("新增第5日实际多拦组", rendered)

    def test_weekly_entry_wires_tracker_non_blocking_and_passes_summary(self):
        script = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        self.assertIn("a_short_crash_veto_tracker.py update", script)
        self.assertIn("--crash-veto-summary", script)
        self.assertIn("formal selection/M6.7 continues unchanged", script)

    def test_cli_failure_keeps_diagnostic_message_but_redacts_provider_secret(self):
        stream = StringIO()
        with mock.patch("runners.a_short_crash_veto_tracker.run_update", side_effect=RuntimeError(
            "provider denied https://api.example.test/?token=top-secret TUSHARE_TOKEN=top-secret"
        )), redirect_stdout(stream):
            rc = main(["update", "--as-of", "20260714"])

        output = stream.getvalue()
        self.assertEqual(rc, 2)
        self.assertIn("RuntimeError: provider denied", output)
        self.assertNotIn("https://", output)
        self.assertNotIn("top-secret", output)
        self.assertNotIn("details suppressed", output)

    def test_cohort_is_frozen_before_provider_refresh_failure(self):
        cohort = {"cohort_id": "crash-veto-" + "3" * 20, "as_of": "20260714",
                  "scope": "official_all_crash_veto", "rule_confirmed_days": 5,
                  "member_count": 0, "members": []}

        def fake_capture(state, _as_of, _days):
            state["cohorts"].append(cohort)
            return 0

        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            with mock.patch("runners.a_short_crash_veto_tracker.capture_official", side_effect=fake_capture), \
                    mock.patch("runners.a_short_crash_veto_tracker.refresh_prices_for_mature_cohorts",
                               side_effect=RuntimeError("provider down")):
                with self.assertRaises(RuntimeError):
                    run_update("20260714", 5, state_path, Path(td) / "summary.json",
                               Path(td) / "prices.pkl", True)
            frozen = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(frozen["cohorts"][0]["cohort_id"], cohort["cohort_id"])


if __name__ == "__main__":
    unittest.main()
