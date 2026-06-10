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
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_iv_feed_build import (  # noqa: E402
    bs_price, implied_vol, atm_iv_for_maturity, constant_maturity_iv,
    build_daily_iv, rolling_percentile_252, build_feed_summary,
    validate_feed_summary_consistency, write_feed, MIN_ROLL_OBS,
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
        s["series"].append({"trade_date": "29991231", "iv_value": 0.2, "iv_percentile_252d": None})
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

    def test_too_few_dates_aborts_without_writing(self):
        from runners.a_short_iv_feed_build import main as build_main
        beh, last = _fake_market(20)        # < MIN_ROLL_OBS → no usable latest percentile
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "feed.json"
            with self.assertRaises(SystemExit):
                build_main(["--as-of", last, "--out", str(out), "--confirm-fetch-authorized"],
                           pro_factory=lambda: _FakePro(beh))
            self.assertFalse(out.exists())


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


if __name__ == "__main__":
    unittest.main()
