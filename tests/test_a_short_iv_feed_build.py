"""Tests for the A-short 50ETF IV feed build (BS inversion → ATM/constant-maturity → 252d pct).

Verifies the numerics (BS price↔implied-vol round-trip recovers the input sigma; ATM IV;
constant-maturity variance interpolation), the PIT-safe daily build, the 252d rolling percentile,
consistency + the validated write path, and the schema. Synthetic fixtures; no live Tushare.
"""
from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_iv_feed_build import (  # noqa: E402
    bs_price, implied_vol, atm_iv_for_maturity, constant_maturity_iv,
    build_daily_iv, rolling_percentile_252, build_feed_summary, build_m05_state,
    validate_feed_summary_consistency, validate_feed_artifact, write_feed, MIN_ROLL_OBS,
    realized_vol, HV_WINDOW, HV_ANNUALIZE, rule3_status_from_percentile,
    _trade_calendar_sha256, _calendar_session_positions, _feed_dates_are_adjacent,
)

SCHEMA_PATH = ROOT / "schemas" / "a_short_iv_feed.schema.json"
AS_OF = "20260609"
R, Q = 0.02, 0.0


class BlackScholesTests(unittest.TestCase):
    def test_price_implied_vol_round_trip(self):
        for cp in ("C", "P"):
            for sig in (0.12, 0.20, 0.35):
                price = bs_price(2.9, 2.9, 30 / 365, R, Q, sig, cp)
                iv = implied_vol(price, 2.9, 2.9, 30 / 365, R, Q, cp)
                self.assertIsNotNone(iv)
                self.assertAlmostEqual(iv, sig, places=4)

    def test_price_out_of_bounds_returns_none(self):
        self.assertIsNone(implied_vol(-1.0, 2.9, 2.9, 0.1, R, Q, "C"))
        self.assertIsNone(implied_vol(5.0, 2.9, 2.9, 0.1, R, Q, "C"))   # absurdly high price


class AtmAndConstantMaturityTests(unittest.TestCase):
    def test_atm_iv_recovers_sigma(self):
        spot, sig, T = 2.9, 0.25, 40 / 365
        rows = []
        for K in (2.7, 2.8, 2.9, 3.0, 3.1):
            for cp in ("C", "P"):
                rows.append({"exercise_price": K, "call_put": cp,
                             "price": bs_price(spot, K, T, R, Q, sig, cp)})
        iv = atm_iv_for_maturity(spot, pd.DataFrame(rows), T, R, Q)
        self.assertAlmostEqual(iv, sig, places=3)

    def test_constant_maturity_interpolates_between(self):
        v = constant_maturity_iv(0.20, 20 / 365, 0.30, 50 / 365, 30 / 365)
        self.assertGreater(v, 0.20)
        self.assertLess(v, 0.30)

    def test_constant_maturity_equal_legs_is_that_sigma(self):
        v = constant_maturity_iv(0.22, 18 / 365, 0.22, 46 / 365, 30 / 365)
        self.assertAlmostEqual(v, 0.22, places=6)

    def test_constant_maturity_needs_both_legs(self):
        self.assertIsNone(constant_maturity_iv(0.2, 20 / 365, None, 50 / 365, 30 / 365))


def _synthetic(dates, near_mat, next_mat, spot=2.9, sigma=0.2):
    basic, daily, und = [], [], []
    for m in (near_mat, next_mat):
        for K in (2.7, 2.8, 2.9, 3.0, 3.1):
            for cp in ("C", "P"):
                code = f"{m}{int(K*1000)}{cp}.SH"
                basic.append({"ts_code": code, "call_put": cp, "exercise_price": K, "maturity_date": m})
    for d in dates:
        und.append({"ts_code": "510050.SH", "trade_date": d, "close": spot})
        for m in (near_mat, next_mat):
            T = (pd.to_datetime(m, format="%Y%m%d") - pd.to_datetime(d, format="%Y%m%d")).days / 365.0
            if T <= 0:
                continue
            for K in (2.7, 2.8, 2.9, 3.0, 3.1):
                for cp in ("C", "P"):
                    code = f"{m}{int(K*1000)}{cp}.SH"
                    px = bs_price(spot, K, T, R, Q, sigma, cp)
                    daily.append({"ts_code": code, "trade_date": d, "settle": px, "close": px})
    return pd.DataFrame(basic), pd.DataFrame(daily), pd.DataFrame(und)


class BuildDailyIvTests(unittest.TestCase):
    def test_recovers_constant_sigma_and_is_pit(self):
        dates = ["20260603", "20260604", "20260605", "20260608", "20260609", "20260710"]  # last > as_of
        basic, daily, und = _synthetic(dates, "20260730", "20260828", spot=2.9, sigma=0.2)
        out = build_daily_iv(basic, daily, und, AS_OF)
        self.assertGreater(len(out), 0)
        self.assertNotIn("20260710", out["trade_date"].tolist())   # PIT: future excluded
        for v in out["iv_value"]:
            self.assertAlmostEqual(v, 0.2, places=2)

    def test_single_maturity_day_skipped(self):
        # only ONE future maturity present -> no constant-maturity interp -> no row
        dates = ["20260605", "20260609"]
        basic, daily, und = _synthetic(dates, "20260730", "20260828")
        basic = basic[basic["maturity_date"] == "20260730"]
        daily = daily[daily["ts_code"].str.startswith("20260730")]
        out = build_daily_iv(basic, daily, und, AS_OF)
        self.assertEqual(len(out), 0)


class RollingPercentileTests(unittest.TestCase):
    def test_percentile_none_below_min_obs(self):
        df = pd.DataFrame({"trade_date": [f"2026{i:04d}" for i in range(MIN_ROLL_OBS - 1)],
                           "iv_value": [0.2] * (MIN_ROLL_OBS - 1)})
        # use real-ish dates to keep ordering deterministic
        df["trade_date"] = [f"202601{i+1:02d}" if i < 28 else f"202602{i-27:02d}" for i in range(len(df))]
        out = rolling_percentile_252(df)
        self.assertTrue(all(p is None for p in out["iv_percentile_252d"]))

    def test_percentile_of_increasing_series(self):
        n = MIN_ROLL_OBS + 5
        dates = [(pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]
        df = pd.DataFrame({"trade_date": dates, "iv_value": [0.1 + 0.001 * i for i in range(n)]})
        out = rolling_percentile_252(df)
        self.assertEqual(out["iv_percentile_252d"].iloc[-1], 100.0)   # last is the max
        # None below min-obs becomes NaN in a mixed float column; build_feed_summary maps NaN→None
        self.assertTrue(pd.isna(out["iv_percentile_252d"].iloc[MIN_ROLL_OBS - 2]))


class M05StateTests(unittest.TestCase):
    def _series(self, iv_values, percentiles):
        dates = [(pd.Timestamp("2026-06-01") + pd.tseries.offsets.BDay(i)).strftime("%Y%m%d")
                 for i in range(len(iv_values))]
        return pd.DataFrame({"trade_date": dates, "iv_value": iv_values,
                             "iv_percentile_252d": percentiles})

    def test_five_low_days_then_strict_rise_triggers_and_releases_on_one_day(self):
        df = self._series(
            [0.20, 0.08, 0.08, 0.08, 0.08, 0.08, 0.14, 0.20, 0.20],
            [50.0, 5.0, 5.0, 5.0, 5.0, 5.0, 95.0, 50.0, 50.0],
        )
        out = build_m05_state(df, trade_calendar=df["trade_date"].tolist())
        self.assertEqual(out.loc[5, "awakening_status"], "unknown")
        self.assertEqual(out.loc[6, "awakening_status"], "active")
        self.assertEqual(out.loc[6, "iv_change_abs_1d_pctpt"], 6.0)
        self.assertEqual(out.loc[6, "cash_reclaim_pct"], 20.0)
        self.assertEqual(out.loc[6, "awakening_baseline_iv"], 0.2)
        self.assertEqual(out.loc[6, "awakening_trigger_date"], "20260609")
        self.assertEqual(out.loc[7, "awakening_status"], "inactive")
        self.assertEqual(out.loc[7, "cash_reclaim_pct"], 0.0)
        self.assertEqual(out.loc[7, "awakening_release_date"], "20260610")
        self.assertEqual(out.loc[8, "awakening_status"], "inactive")
        self.assertEqual(out.loc[8, "cash_reclaim_pct"], 0.0)
        self.assertEqual(out.loc[8, "awakening_release_date"], "20260610")

    def test_low_run_or_rise_at_boundary_does_not_trigger(self):
        four_low = self._series(
            [0.20, 0.08, 0.08, 0.08, 0.08, 0.14],
            [50.0, 5.0, 5.0, 5.0, 5.0, 95.0],
        )
        self.assertNotEqual(build_m05_state(four_low, trade_calendar=four_low["trade_date"].tolist()).iloc[-1]["awakening_status"], "active")
        five_low_boundary = self._series(
            [0.20, 0.08, 0.08, 0.08, 0.08, 0.08, 0.13],
            [50.0, 5.0, 5.0, 5.0, 5.0, 5.0, 95.0],
        )
        self.assertNotEqual(build_m05_state(five_low_boundary, trade_calendar=five_low_boundary["trade_date"].tolist()).iloc[-1]["awakening_status"], "active")

    def test_rule3_boundaries_are_fail_closed(self):
        self.assertEqual(rule3_status_from_percentile(None), "unknown")
        self.assertEqual(rule3_status_from_percentile(80.0), "normal")
        self.assertEqual(rule3_status_from_percentile(80.1), "reduce_new_position_50pct")
        self.assertEqual(rule3_status_from_percentile(90.0), "reduce_new_position_50pct")
        self.assertEqual(rule3_status_from_percentile(90.1), "no_trade")
        self.assertEqual(rule3_status_from_percentile(float("nan")), "unknown")

    def test_missing_inputs_do_not_clear_active_state(self):
        df = self._series(
            [0.20, 0.08, 0.08, 0.08, 0.08, 0.08, 0.14, 0.20],
            [50.0, 5.0, 5.0, 5.0, 5.0, 5.0, 95.0, None],
        )
        out = build_m05_state(df, trade_calendar=df["trade_date"].tolist())
        self.assertEqual(out.iloc[-1]["awakening_status"], "active")
        self.assertEqual(out.iloc[-1]["cash_reclaim_pct"], 20.0)

    def test_weekday_gap_cannot_be_counted_as_one_day_iv_jump_or_trigger(self):
        df = pd.DataFrame({
            "trade_date": ["20260601", "20260602", "20260603", "20260604",
                           "20260605", "20260608", "20260618"],
            "iv_value": [0.20, 0.08, 0.08, 0.08, 0.08, 0.08, 0.14],
            "iv_percentile_252d": [50.0, 5.0, 5.0, 5.0, 5.0, 5.0, 95.0],
        })
        calendar = pd.date_range("20260601", "20260618", freq="B").strftime("%Y%m%d").tolist()
        out = build_m05_state(df, trade_calendar=calendar)
        self.assertTrue(pd.isna(out.iloc[-1]["iv_change_abs_1d_pctpt"]))
        self.assertNotEqual(out.iloc[-1]["awakening_status"], "active")

    def test_exchange_holiday_is_adjacent_but_missing_open_session_is_not(self):
        df = pd.DataFrame({
            "trade_date": ["20260617", "20260618", "20260622", "20260623", "20260624", "20260625", "20260626"],
            "iv_value": [0.20, 0.08, 0.08, 0.08, 0.08, 0.08, 0.14],
            "iv_percentile_252d": [50.0, 5.0, 5.0, 5.0, 5.0, 5.0, 95.0],
        })
        # 20260619 is an exchange holiday in this synthetic calendar, so the
        # Friday-to-Monday observation is one adjacent session step.
        holiday_calendar = df["trade_date"].tolist()
        active = build_m05_state(df, trade_calendar=holiday_calendar)
        self.assertEqual(active.iloc[-1]["awakening_status"], "active")
        # If that date is a real open session but its IV row is missing, the
        # same series must fail closed instead of manufacturing a jump.
        open_session_calendar = [*holiday_calendar[:2], "20260619", *holiday_calendar[2:]]
        blocked = build_m05_state(df, trade_calendar=open_session_calendar)
        self.assertNotEqual(blocked.iloc[-1]["awakening_status"], "active")

    def test_calendar_unavailable_is_visible_and_cannot_trigger(self):
        df = self._series(
            [0.20, 0.08, 0.08, 0.08, 0.08, 0.08, 0.14],
            [50.0, 5.0, 5.0, 5.0, 5.0, 5.0, 95.0],
        )
        summary = build_feed_summary(df, AS_OF, "t")
        self.assertEqual(summary["calendar"]["status"], "calendar_unavailable")
        self.assertNotEqual(summary["awakening"]["status"], "active")
        validate_feed_summary_consistency(summary)

    def test_duplicate_trade_date_is_rejected_before_state_machine(self):
        df = self._series([0.20, 0.08, 0.08], [50.0, 5.0, 5.0])
        df.loc[2, "trade_date"] = df.loc[1, "trade_date"]
        with self.assertRaises(ValueError):
            build_m05_state(df)

    def test_state_machine_builds_calendar_lookup_once(self):
        df = self._series(
            [0.20, 0.08, 0.08, 0.08, 0.08, 0.08, 0.14, 0.20, 0.20],
            [50.0, 5.0, 5.0, 5.0, 5.0, 5.0, 95.0, 50.0, 50.0],
        )
        with patch(
            "runners.a_short_iv_feed_build._calendar_session_positions",
            wraps=_calendar_session_positions,
        ) as build_positions:
            build_m05_state(df, trade_calendar=df["trade_date"].tolist())
        self.assertEqual(build_positions.call_count, 1)

    def test_adjacency_fallback_matches_precomputed_index(self):
        calendar = ["20260601", "20260602", "20260603"]
        positions = _calendar_session_positions(tuple(calendar))
        cases = (
            ("20260601", "20260602", True),
            ("20260601", "20260603", False),
            ("20260603", "20260602", False),
            ("bad", "20260602", False),
        )
        for d0, d1, expected in cases:
            self.assertEqual(_feed_dates_are_adjacent(d0, d1, calendar), expected)
            self.assertEqual(
                _feed_dates_are_adjacent(
                    d0, d1, calendar, calendar_positions=positions,
                ),
                expected,
            )


class ConsistencyAndWriteTests(unittest.TestCase):
    def _good_summary(self):
        dates = ["20260603", "20260604", "20260605", "20260608", "20260609"]
        basic, daily, und = _synthetic(dates, "20260730", "20260828")
        iv = build_daily_iv(basic, daily, und, AS_OF)
        return build_feed_summary(iv, AS_OF, "2026-06-10T00:00:00+08:00")

    def test_valid_summary_passes_and_writes(self):
        s = self._good_summary()
        validate_feed_summary_consistency(s)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "iv_feed.json"
            write_feed(s, str(out))
            self.assertTrue(out.exists())

    def test_future_date_in_series_rejected_no_file(self):
        s = self._good_summary()
        s["series"].append({"trade_date": "29991231", "iv_value": 0.2, "iv_percentile_252d": None, "hv_value": None})
        s["n_days"] = len(s["series"])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "iv_feed.json"
            with self.assertRaises(Exception):
                write_feed(s, str(out))
            self.assertFalse(out.exists())

    def test_nonpositive_iv_rejected(self):
        s = self._good_summary()
        if s["series"]:
            s["series"][0]["iv_value"] = 0.0
            with self.assertRaises(ValueError):
                validate_feed_summary_consistency(s)

    def test_invalid_calendar_as_of_rejected(self):
        s = self._good_summary()
        s["as_of"] = "20260631"   # June has 30 days
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(s)

    def _bound_summary(self):
        dates = ["20260601", "20260602", "20260603", "20260604", "20260605", "20260608", "20260609"]
        frame = pd.DataFrame({
            "trade_date": dates,
            "iv_value": [0.20, 0.08, 0.08, 0.08, 0.08, 0.08, 0.14],
            "iv_percentile_252d": [50.0, 5.0, 5.0, 5.0, 5.0, 5.0, 95.0],
            "hv_value": [None] * len(dates),
        })
        return build_feed_summary(
            frame, AS_OF, "t", trade_calendar=dates,
            trade_dates_probed=dates,
        )

    def _independent_bound_summary(self):
        calendar_dates = [
            "20260601", "20260602", "20260603", "20260604",
            "20260605", "20260608", "20260609",
        ]
        realized_dates = calendar_dates[:-1]
        frame = pd.DataFrame({
            "trade_date": realized_dates,
            "iv_value": [0.20, 0.08, 0.08, 0.08, 0.08, 0.14],
            "iv_percentile_252d": [50.0, 5.0, 5.0, 5.0, 5.0, 95.0],
            "hv_value": [None] * len(realized_dates),
        })
        return build_feed_summary(
            frame, AS_OF, "t", trade_calendar=calendar_dates,
            calendar_source="tushare.trade_cal+fund_daily",
            trade_dates_probed=calendar_dates,
            independent_trade_dates=realized_dates,
        )

    def test_calendar_binding_records_probe_hash_and_recomputes_from_probe(self):
        summary = self._bound_summary()
        self.assertEqual(summary["calendar"]["status"], "available")
        self.assertEqual(summary["calendar"]["trade_dates"], summary["calendar"]["probed_trade_dates"])
        self.assertIn(summary["awakening"]["status"], {"unknown", "inactive", "active"})
        validate_feed_artifact(summary)
        validate_feed_artifact(summary, trade_calendar=summary["calendar"]["trade_dates"],
                                trade_dates_probed=summary["calendar"]["probed_trade_dates"])

    def test_independent_fund_daily_binding_drives_recompute(self):
        summary = self._independent_bound_summary()
        calendar = summary["calendar"]
        self.assertEqual(calendar["source"], "tushare.trade_cal+fund_daily")
        self.assertEqual(calendar["independent_source"], "tushare.fund_daily")
        self.assertNotEqual(calendar["independent_trade_dates"], calendar["trade_dates"])
        validate_feed_artifact(
            summary,
            trade_calendar=calendar["trade_dates"],
            trade_dates_probed=calendar["probed_trade_dates"],
            independent_trade_dates=calendar["independent_trade_dates"],
        )

    def test_unrealized_calendar_tail_does_not_change_m05_state(self):
        summary = self._independent_bound_summary()
        no_tail = copy.deepcopy(summary)
        no_tail_calendar = no_tail["calendar"]
        no_tail_calendar["trade_dates"].pop()
        no_tail_calendar["probed_trade_dates"].pop()
        no_tail_calendar["coverage_end"] = no_tail_calendar["trade_dates"][-1]
        no_tail_calendar["n_trade_dates"] = len(no_tail_calendar["trade_dates"])
        no_tail_calendar["trade_dates_sha256"] = _trade_calendar_sha256(
            no_tail_calendar["trade_dates"]
        )
        no_tail_calendar["probed_trade_dates_sha256"] = _trade_calendar_sha256(
            no_tail_calendar["probed_trade_dates"]
        )
        validate_feed_artifact(summary)
        validate_feed_artifact(no_tail)
        state_fields = (
            "iv_change_abs_1d_pctpt", "rule3_status", "awakening_status",
            "cash_reclaim_pct", "awakening_baseline_iv",
            "awakening_trigger_date", "awakening_release_date",
        )
        self.assertEqual(
            [[row[field] for field in state_fields] for row in summary["series"]],
            [[row[field] for field in state_fields] for row in no_tail["series"]],
        )

    def test_series_must_end_at_independent_realized_end(self):
        summary = self._independent_bound_summary()
        summary["series"][-1]["trade_date"] = "20260607"
        with self.assertRaisesRegex(ValueError, "最新 realized observation"):
            validate_feed_summary_consistency(summary)

    def test_series_date_after_independent_realized_end_is_rejected(self):
        summary = self._independent_bound_summary()
        future_row = copy.deepcopy(summary["series"][-1])
        future_row["trade_date"] = "20260609"
        summary["series"].append(future_row)
        summary["n_days"] = len(summary["series"])
        with self.assertRaisesRegex(ValueError, "超过 fund_daily realized_end"):
            validate_feed_summary_consistency(summary)

    def test_independent_date_gap_is_rejected_even_with_self_consistent_trade_cal(self):
        summary = self._independent_bound_summary()
        calendar = summary["calendar"]
        calendar["trade_dates"] = [*calendar["trade_dates"][:2], "20260606", *calendar["trade_dates"][2:]]
        calendar["coverage_start"] = calendar["trade_dates"][0]
        calendar["coverage_end"] = calendar["trade_dates"][-1]
        calendar["n_trade_dates"] = len(calendar["trade_dates"])
        calendar["trade_dates_sha256"] = _trade_calendar_sha256(calendar["trade_dates"])
        calendar["probed_trade_dates"] = list(calendar["trade_dates"])
        calendar["probed_trade_dates_sha256"] = _trade_calendar_sha256(calendar["probed_trade_dates"])
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(summary)

    def test_external_independent_dates_are_checked_at_write_door(self):
        summary = self._independent_bound_summary()
        with self.assertRaises(ValueError):
            validate_feed_artifact(
                summary,
                trade_calendar=summary["calendar"]["trade_dates"],
                trade_dates_probed=summary["calendar"]["probed_trade_dates"],
                independent_trade_dates=[*summary["calendar"]["independent_trade_dates"], "20260610"],
            )

    def test_new_source_requires_independent_binding(self):
        summary = self._independent_bound_summary()
        summary["calendar"].pop("independent_trade_dates")
        with self.assertRaises(ValueError):
            validate_feed_artifact(summary)

    def test_deleted_calendar_session_is_rejected_not_recomputed_as_active(self):
        summary = self._bound_summary()
        summary["calendar"]["trade_dates"].remove("20260605")
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(summary)

    def test_inserted_non_session_is_rejected_not_used_for_adjacency(self):
        summary = self._bound_summary()
        summary["calendar"]["trade_dates"].insert(5, "20260606")
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(summary)

    def test_external_calendar_window_must_match_bound_calendar(self):
        summary = self._bound_summary()
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(summary, trade_calendar=[
                *summary["calendar"]["trade_dates"][:5], "20260606",
                *summary["calendar"]["trade_dates"][5:]
            ])

    def test_future_calendar_date_is_rejected(self):
        summary = self._bound_summary()
        summary["calendar"]["trade_dates"].append("20260610")
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(summary)

    def test_short_date_is_rejected_by_read_side_schema_gate(self):
        summary = self._bound_summary()
        summary["series"][0]["trade_date"] = "2026101"
        with self.assertRaises(ValueError):
            validate_feed_artifact(summary)

    def test_schema_version_downgrade_cannot_skip_m05_recompute(self):
        summary = self._bound_summary()
        summary["schema_version"] = "1.1.0"
        summary["series"][-1]["awakening_status"] = "active"
        summary["series"][-1]["cash_reclaim_pct"] = 20.0
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(summary)
        with self.assertRaises(ValueError):
            validate_feed_artifact(summary)

    def test_schema_version_downgrade_with_awakening_only_is_rejected(self):
        summary = self._bound_summary()
        summary["schema_version"] = "1.1.0"
        summary["series"] = [
            {key: value for key, value in row.items()
             if key not in {"iv_change_abs_1d_pctpt", "rule3_status", "awakening_status",
                            "cash_reclaim_pct", "awakening_baseline_iv",
                            "awakening_trigger_date", "awakening_release_date"}}
            for row in summary["series"]
        ]
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(summary)
        with self.assertRaises(ValueError):
            validate_feed_artifact(summary)


class _FakePro:
    def __init__(self, b):
        self._b = b

    def __getattr__(self, n):
        def call(**kw):
            x = self._b.get(n, pd.DataFrame())
            if isinstance(x, Exception):
                raise x
            if callable(x) and not isinstance(x, pd.DataFrame):
                return x(**kw)
            return x
        return call


def _fake_market(n_dates):
    near_mat, next_mat = "20260731", "20260828"
    dates = [(pd.Timestamp("2026-01-02") + pd.tseries.offsets.BDay(i)).strftime("%Y%m%d") for i in range(n_dates)]
    basic_rows = []
    for m in (near_mat, next_mat):
        for K in (2.7, 2.8, 2.9, 3.0, 3.1):
            for cp in ("C", "P"):
                basic_rows.append({"ts_code": f"{m}{int(K*1000)}{cp}.SH", "name": f"50ETF购{int(K*1000)}",
                                   "call_put": cp, "exercise_price": K, "maturity_date": m})

    def opt_daily(**kw):
        d = kw["trade_date"]
        rows = []
        for m in (near_mat, next_mat):
            T = (pd.to_datetime(m, format="%Y%m%d") - pd.to_datetime(d, format="%Y%m%d")).days / 365.0
            if T <= 0:
                continue
            for K in (2.7, 2.8, 2.9, 3.0, 3.1):
                for cp in ("C", "P"):
                    px = bs_price(2.9, K, T, R, Q, 0.2, cp)
                    rows.append({"ts_code": f"{m}{int(K*1000)}{cp}.SH", "trade_date": d,
                                 "settle": px, "close": px})
        return pd.DataFrame(rows)

    beh = {"opt_basic": pd.DataFrame(basic_rows), "trade_cal": pd.DataFrame({"cal_date": dates}),
           "opt_daily": opt_daily,
           "fund_daily": pd.DataFrame([{"ts_code": "510050.SH", "trade_date": d, "close": 2.9} for d in dates])}
    return beh, dates[-1]


class BuildMainRegressionTests(unittest.TestCase):
    def test_enough_dates_writes_nonnull_latest_percentile(self):
        from runners.a_short_iv_feed_build import main as build_main
        beh, last = _fake_market(70)        # 70 IV days >= MIN_ROLL_OBS
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "feed.json"
            build_main(["--as-of", last, "--out", str(out), "--confirm-fetch-authorized"],
                       pro_factory=lambda: _FakePro(beh))
            self.assertTrue(out.exists())
            feed = json.loads(out.read_text(encoding="utf-8"))
            self.assertIsNotNone(feed["series"][-1]["iv_percentile_252d"])

    def test_price_clock_mismatch_exits_with_its_own_code_and_writes_nothing(self):
        from runners.a_short_iv_feed_build import CLOCK_MISMATCH_EXIT_CODE, main as build_main
        beh, last = _fake_market(70)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "feed.json"
            with self.assertRaises(SystemExit) as ctx:
                build_main(["--as-of", last, "--price-data-through", "20991231",
                            "--out", str(out), "--confirm-fetch-authorized"],
                           pro_factory=lambda: _FakePro(beh))
            # The wrapper maps this exact code to `clock_mismatch`; a generic
            # failure code would degrade the week as a build failure instead.
            self.assertEqual(ctx.exception.code, CLOCK_MISMATCH_EXIT_CODE)
            self.assertFalse(out.exists())

    def test_matching_price_clock_still_writes_the_feed(self):
        from runners.a_short_iv_feed_build import main as build_main
        beh, last = _fake_market(70)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "feed.json"
            build_main(["--as-of", last, "--price-data-through", last,
                        "--out", str(out), "--confirm-fetch-authorized"],
                       pro_factory=lambda: _FakePro(beh))
            self.assertTrue(out.exists())

    def test_too_few_dates_aborts_without_writing(self):
        from runners.a_short_iv_feed_build import main as build_main
        beh, last = _fake_market(20)        # < MIN_ROLL_OBS → no usable latest percentile
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "feed.json"
            with self.assertRaises(SystemExit):
                build_main(["--as-of", last, "--out", str(out), "--confirm-fetch-authorized"],
                           pro_factory=lambda: _FakePro(beh))
            self.assertFalse(out.exists())

    def test_non_provider_failure_clears_stale_failure_receipt(self):
        from runners.a_short_iv_feed_build import main as build_main
        beh, last = _fake_market(20)        # insufficient history, not a provider failure
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "feed.json"
            receipt = Path(d) / "iv_feed_failure.json"
            receipt.write_text('{"stale": true}', encoding="utf-8")
            with self.assertRaises(SystemExit):
                build_main([
                    "--as-of", last, "--out", str(out),
                    "--failure-receipt-out", str(receipt),
                    "--confirm-fetch-authorized",
                ], pro_factory=lambda: _FakePro(beh))
            self.assertFalse(receipt.exists())

    def test_provider_failure_writes_sanitized_receipt_not_partial_feed(self):
        from runners.a_short_iv_feed_build import main as build_main
        beh, last = _fake_market(70)
        beh["opt_daily"] = RuntimeError(
            "network timeout url=https://api.example.invalid/?token=SECRET123 raw_rows=[1]"
        )
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "feed.json"
            receipt = Path(d) / "iv_feed_failure.json"
            with self.assertRaises(SystemExit):
                build_main([
                    "--as-of", last, "--out", str(out),
                    "--failure-receipt-out", str(receipt),
                    "--confirm-fetch-authorized",
                ], pro_factory=lambda: _FakePro(beh))
            self.assertFalse(out.exists())
            payload = json.loads(receipt.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "failed")
        self.assertTrue(payload["opt_daily_fail_fast_triggered"])
        self.assertEqual(payload["failures"][0]["endpoint"], "opt_daily")
        serialized = json.dumps(payload, ensure_ascii=False)
        for leak in ("SECRET123", "token=", "url=", "raw_rows", "api.example.invalid", "RuntimeError"):
            self.assertNotIn(leak, serialized)


class FeedSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        dates = ["20260603", "20260604", "20260605", "20260608", "20260609"]
        basic, daily, und = _synthetic(dates, "20260730", "20260828")
        self.summary = build_feed_summary(build_daily_iv(basic, daily, und, AS_OF), AS_OF, "t")

    def _reject(self, s):
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)

    def test_valid(self):
        jsonschema.validate(self.summary, self.schema)

    def test_params_drift_rejected(self):
        s = copy.deepcopy(self.summary)
        s["params"]["risk_free"] = 0.05
        self._reject(s)

    def test_boundary_production_true_rejected(self):
        s = copy.deepcopy(self.summary)
        s["boundary"]["production"] = True
        self._reject(s)

    def test_iv_value_zero_rejected(self):
        s = copy.deepcopy(self.summary)
        if s["series"]:
            s["series"][0]["iv_value"] = 0.0
            self._reject(s)

    def test_extra_field_rejected(self):
        s = copy.deepcopy(self.summary)
        s["unexpected"] = 1
        self._reject(s)

    def test_schema_version_is_1_2_0(self):
        self.assertEqual(self.summary["schema_version"], "1.2.0")

    def test_legacy_schema_label_cannot_carry_m05_shape(self):
        s = copy.deepcopy(self.summary)
        s["schema_version"] = "1.1.0"
        self._reject(s)

    def test_hv_value_null_and_nonneg_ok(self):
        jsonschema.validate(self.summary, self.schema)         # 5-date fixture → hv_value 全 None,仍合法
        s = copy.deepcopy(self.summary)
        if s["series"]:
            s["series"][0]["hv_value"] = 0.25
            jsonschema.validate(s, self.schema)
            s["series"][0]["hv_value"] = 0.0                   # 0 已实现波动(退化但合法)
            jsonschema.validate(s, self.schema)

    def test_negative_hv_rejected(self):
        s = copy.deepcopy(self.summary)
        if s["series"]:
            s["series"][0]["hv_value"] = -0.1
            self._reject(s)

    def test_missing_hv_value_rejected(self):
        s = copy.deepcopy(self.summary)
        if s["series"]:
            del s["series"][0]["hv_value"]
            self._reject(s)

    def test_missing_hv_window_param_rejected(self):
        s = copy.deepcopy(self.summary)
        del s["params"]["hv_window"]
        self._reject(s)


def _varying_market(n=25, near_mat="20260730", next_mat="20260828"):
    """变动 spot 的合成市场(→ 正 HV);≥22 日使末期 HV 窗满。"""
    dates = [(pd.Timestamp("2026-04-01") + pd.tseries.offsets.BDay(i)).strftime("%Y%m%d") for i in range(n)]
    basic, daily, und = [], [], []
    for m in (near_mat, next_mat):
        for K in (2.7, 2.8, 2.9, 3.0, 3.1):
            for cp in ("C", "P"):
                basic.append({"ts_code": f"{m}{int(K*1000)}{cp}.SH", "call_put": cp,
                              "exercise_price": K, "maturity_date": m})
    for i, d in enumerate(dates):
        spot = 2.9 + 0.03 * math.sin(i)        # 变动 spot → 非零已实现波动
        und.append({"ts_code": "510050.SH", "trade_date": d, "close": spot})
        for m in (near_mat, next_mat):
            T = (pd.to_datetime(m, format="%Y%m%d") - pd.to_datetime(d, format="%Y%m%d")).days / 365.0
            if T <= 0:
                continue
            for K in (2.7, 2.8, 2.9, 3.0, 3.1):
                for cp in ("C", "P"):
                    px = bs_price(spot, K, T, R, Q, 0.2, cp)
                    daily.append({"ts_code": f"{m}{int(K*1000)}{cp}.SH", "trade_date": d, "settle": px, "close": px})
    return pd.DataFrame(basic), pd.DataFrame(daily), pd.DataFrame(und), dates[-1]


class RealizedVolTests(unittest.TestCase):
    def _expected(self, closes, window=HV_WINDOW, annualize=HV_ANNUALIZE):
        import statistics
        vals = [c for c in closes if c is not None][-(window + 1):]
        rets = [math.log(vals[i] / vals[i - 1]) for i in range(1, len(vals))]
        return round(statistics.stdev(rets) * math.sqrt(annualize), 6)

    def test_matches_sample_std_annualized(self):
        closes = [2.0 + 0.05 * math.sin(i) + 0.002 * i for i in range(30)]
        self.assertAlmostEqual(realized_vol(closes), self._expected(closes), places=9)

    def test_flat_series_zero_vol(self):
        self.assertEqual(realized_vol([2.5] * (HV_WINDOW + 1)), 0.0)

    def test_insufficient_window_none(self):
        self.assertIsNone(realized_vol([2.0 + 0.01 * i for i in range(HV_WINDOW)]))   # 仅 window 根 < window+1

    def test_nonpositive_or_nonfinite_dropped_then_none(self):
        self.assertIsNone(realized_vol([2.0] * HV_WINDOW + [-1.0]))   # 去掉非正后 < window+1
        self.assertIsNone(realized_vol([float("nan")] * (HV_WINDOW + 2)))
        self.assertIsNone(realized_vol([None] * (HV_WINDOW + 2)))

    def test_more_volatile_has_higher_hv(self):
        calm = [2.0 + 0.005 * math.sin(i) for i in range(30)]
        wild = [2.0 + 0.05 * math.sin(i) for i in range(30)]
        self.assertGreater(realized_vol(wild), realized_vol(calm))


class FeedHvIntegrationTests(unittest.TestCase):
    def test_build_daily_iv_has_hv_column_pit(self):
        basic, daily, und, last = _varying_market(25)
        out = build_daily_iv(basic, daily, und, last)
        self.assertIn("hv_value", out.columns)
        self.assertTrue(pd.isna(out["hv_value"].iloc[0]))      # 早期窗口不足 → None
        self.assertFalse(pd.isna(out["hv_value"].iloc[-1]))    # 末期窗口足 → 正值
        self.assertGreater(float(out["hv_value"].iloc[-1]), 0.0)

    def test_summary_has_hv_and_param_and_validates(self):
        basic, daily, und, last = _varying_market(25)
        s = build_feed_summary(build_daily_iv(basic, daily, und, last), last, "t")
        self.assertEqual(s["params"]["hv_window"], HV_WINDOW)
        self.assertIn("hv_value", s["series"][-1])
        self.assertGreater(s["series"][-1]["hv_value"], 0.0)
        validate_feed_summary_consistency(s)

    def test_validate_rejects_negative_hv(self):
        basic, daily, und, last = _varying_market(25)
        s = build_feed_summary(build_daily_iv(basic, daily, und, last), last, "t")
        s["series"][-1]["hv_value"] = -0.01
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(s)

    def test_m05_state_mutation_is_rejected(self):
        basic, daily, und, last = _varying_market(25)
        s = build_feed_summary(build_daily_iv(basic, daily, und, last), last, "t")
        s["awakening"]["status"] = "active" if s["awakening"]["status"] != "active" else "inactive"
        with self.assertRaises(ValueError):
            validate_feed_summary_consistency(s)

    def test_legacy_1_1_feed_remains_readable_until_consumer_cut(self):
        basic, daily, und = _synthetic(["20260603", "20260604"], "20260730", "20260828")
        s = build_feed_summary(build_daily_iv(basic, daily, und, AS_OF), AS_OF, "t")
        s["schema_version"] = "1.1.0"
        s.pop("awakening", None)
        s.pop("calendar", None)
        for row in s["series"]:
            for key in ("iv_change_abs_1d_pctpt", "rule3_status", "awakening_status",
                        "cash_reclaim_pct", "awakening_baseline_iv",
                        "awakening_trigger_date", "awakening_release_date"):
                row.pop(key, None)
        validate_feed_summary_consistency(s)
        validate_feed_artifact(s)


if __name__ == "__main__":
    unittest.main()
