"""Tests for the A-short 50ETF IV feed feasibility probe (PIT-safe).

`computable` must mean PIT-safe BS-inversion-ready: real dates; trade_date<=as_of (no future
leak); 510050 underlier identity + enough positive-close PIT days; valid quotes across enough
DAYS (not rows) and >=2 future maturities; ATM-bracketed. Pure logic + schema + consistency.
Synthetic fixtures; no live Tushare / no fetch. Covers the six Codex PIT/date-quality probes.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_iv_feed_probe import (  # noqa: E402
    assess_opt_coverage, build_probe_summary, validate_probe_summary_consistency, UNDERLYING,
)

SCHEMA_PATH = ROOT / "schemas" / "a_short_iv_feed_probe_summary.schema.json"
AS_OF = "20260630"
PIT_DATES = [f"202606{d + 1:02d}" for d in range(20)]      # all <= AS_OF
FUTURE_DATES = [f"202607{d + 1:02d}" for d in range(20)]   # all > AS_OF


def _good_basic(n=40):
    rows = []
    for i in range(n):
        rows.append({"ts_code": f"100000{i:02d}.SH",
                     "call_put": "C" if i % 2 == 0 else "P",
                     "exercise_price": 2.0 + (i % 10) * 0.1,                 # 2.0..2.9, straddles 2.5
                     "maturity_date": "20260725" if i < n // 2 else "20260822"})  # both valid & > AS_OF
    return pd.DataFrame(rows)


def _daily(dates, contracts=40, settle=0.1, close=0.1):
    rows = []
    for td in dates:
        for i in range(contracts):
            rows.append({"ts_code": f"100000{i:02d}.SH", "trade_date": td,
                         "settle": settle, "close": close, "vol": 100, "oi": 500})
    return pd.DataFrame(rows)


def _underlier(dates, close=2.5, ts=UNDERLYING):
    return pd.DataFrame([{"ts_code": ts, "trade_date": td, "close": close} for td in dates])


def _assess(basic=None, daily=None, und=None, as_of=AS_OF):
    return assess_opt_coverage(_good_basic() if basic is None else basic,
                               _daily(PIT_DATES) if daily is None else daily,
                               _underlier(PIT_DATES) if und is None else und, as_of)


class AssessHappyPath(unittest.TestCase):
    def test_computable_when_all_ok(self):
        a = _assess()
        self.assertTrue(a["computable"], a["reasons"])
        self.assertEqual(a["reasons"], [])
        self.assertTrue(a["underlier_is_510050"])
        self.assertGreaterEqual(a["n_quotable_future_maturities"], 2)
        self.assertGreaterEqual(a["valid_quote_days"], 15)
        self.assertGreaterEqual(a["underlier_valid_days"], 15)
        self.assertTrue(a["atm_bracketed"])


class CodexPitDateQualityCases(unittest.TestCase):
    def test_future_trade_dates_excluded(self):
        a = _assess(daily=_daily(FUTURE_DATES), und=_underlier(FUTURE_DATES))
        self.assertEqual(a["opt_pit_coverage_days"], 0)   # all future dropped by PIT
        self.assertFalse(a["computable"])

    def test_valid_quotes_concentrated_one_day(self):
        daily = _daily(PIT_DATES)
        daily["settle"] = 0.0
        daily["close"] = 0.0
        daily.loc[daily["trade_date"] == PIT_DATES[0], "close"] = 0.1   # only one day has quotes
        a = _assess(daily=daily)
        self.assertEqual(a["valid_quote_days"], 1)
        self.assertFalse(a["computable"])

    def test_only_one_future_maturity_quotable(self):
        daily = _daily(PIT_DATES)
        far = [f"100000{i:02d}.SH" for i in range(20, 40)]   # the 20260822 maturity contracts
        daily.loc[daily["ts_code"].isin(far), ["settle", "close"]] = 0.0  # no quotes for 2nd maturity
        a = _assess(daily=daily)
        self.assertEqual(a["n_quotable_future_maturities"], 1)
        self.assertFalse(a["computable"])

    def test_underlier_one_positive_close_day(self):
        und = _underlier(PIT_DATES)
        und["close"] = 0.0
        und.loc[0, "close"] = 2.5
        a = _assess(und=und)
        self.assertEqual(a["underlier_valid_days"], 1)
        self.assertFalse(a["computable"])

    def test_wrong_underlier_symbol(self):
        a = _assess(und=_underlier(PIT_DATES, ts="000300.SH"))
        self.assertFalse(a["underlier_is_510050"])
        self.assertFalse(a["computable"])

    def test_nondate_maturity_strings(self):
        basic = _good_basic()
        basic["maturity_date"] = ["yyyyyyyy" if i < 20 else "zzzzzzzz" for i in range(len(basic))]
        a = _assess(basic=basic)
        self.assertEqual(a["n_valid_date_maturities"], 0)
        self.assertEqual(a["n_future_maturities"], 0)
        self.assertFalse(a["computable"])


class AsOfAndLatestUsableCases(unittest.TestCase):
    def test_invalid_as_of_calendar_date(self):
        a = _assess(as_of="20260631")          # June has 30 days -> not a real date
        self.assertFalse(a["as_of_is_valid_date"])
        self.assertFalse(a["computable"])

    def test_latest_date_all_zero_falls_back_to_prior_usable_day(self):
        daily = _daily(PIT_DATES)
        daily.loc[daily["trade_date"] == PIT_DATES[-1], ["settle", "close"]] = 0.0
        a = _assess(daily=daily)
        self.assertEqual(a["latest_usable_date"], PIT_DATES[-2])  # not the zeroed latest common date
        self.assertEqual(a["valid_quote_days"], 19)
        self.assertTrue(a["computable"], a["reasons"])

    def test_atm_uses_latest_usable_date_not_stale_window(self):
        # On the latest usable date, zero out the >=2.5 strikes; whole-window still has them.
        high = [f"100000{i:02d}.SH" for i in range(40) if (i % 10) >= 5]   # strikes 2.5..2.9
        daily = _daily(PIT_DATES)
        m = daily["ts_code"].isin(high) & (daily["trade_date"] == PIT_DATES[-1])
        daily.loc[m, ["settle", "close"]] = 0.0
        a = _assess(daily=daily)
        self.assertEqual(a["latest_usable_date"], PIT_DATES[-1])
        self.assertFalse(a["atm_bracketed"])    # only low strikes quoted on the latest date
        self.assertFalse(a["computable"])


class AssessOtherGates(unittest.TestCase):
    def test_missing_opt_daily_field(self):
        a = _assess(daily=_daily(PIT_DATES).drop(columns=["oi"]))
        self.assertFalse(a["computable"])
        self.assertIn("oi", a["opt_daily_missing_fields"])

    def test_missing_maturity_field(self):
        a = _assess(basic=_good_basic().drop(columns=["maturity_date"]))
        self.assertFalse(a["computable"])
        self.assertIn("maturity_date", a["opt_basic_missing_fields"])

    def test_too_few_contracts(self):
        a = _assess(basic=_good_basic(n=6), daily=_daily(PIT_DATES, contracts=6))
        self.assertFalse(a["computable"])

    def test_calls_only(self):
        basic = _good_basic()
        basic["call_put"] = "C"
        self.assertFalse(_assess(basic=basic)["computable"])

    def test_no_basic_daily_overlap(self):
        daily = _daily(PIT_DATES)
        daily["ts_code"] = "999999.SH"
        a = _assess(daily=daily)
        self.assertEqual(a["basic_daily_overlap_count"], 0)
        self.assertFalse(a["computable"])

    def test_strikes_not_bracketing_spot(self):
        basic = _good_basic()
        basic["exercise_price"] = [1.0 + (i % 10) * 0.1 for i in range(len(basic))]  # 1.0..1.9 < 2.5
        a = _assess(basic=basic)
        self.assertFalse(a["atm_bracketed"])
        self.assertFalse(a["computable"])


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.summary = build_probe_summary(_assess(), as_of=AS_OF, generated_at="2026-06-10T00:00:00+08:00")

    def test_valid_passes(self):
        validate_probe_summary_consistency(self.summary)

    def test_top_vs_assessment_mismatch_rejected(self):
        s = copy.deepcopy(self.summary)
        s["computable"] = not s["assessment"]["computable"]
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_computable_with_reasons_rejected(self):
        s = copy.deepcopy(self.summary)
        s["assessment"]["reasons"] = ["planted"]
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_computable_with_failed_counter_rejected(self):
        s = copy.deepcopy(self.summary)
        s["assessment"]["valid_quote_days"] = 1
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_has_required_fields_mismatch_rejected(self):
        s = copy.deepcopy(self.summary)
        s["assessment"]["opt_daily_has_required_fields"] = False
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_computable_with_invalid_as_of_rejected(self):
        s = copy.deepcopy(self.summary)
        s["as_of"] = "20260631"
        s["assessment"]["as_of_is_valid_date"] = False
        with self.assertRaises(ValueError):
            validate_probe_summary_consistency(s)

    def test_computable_with_invalid_latest_usable_date_rejected(self):
        for value in (None, "notadate", "20260631", "20260701"):
            with self.subTest(value=value):
                s = copy.deepcopy(self.summary)
                s["assessment"]["latest_usable_date"] = value
                with self.assertRaises(ValueError):
                    validate_probe_summary_consistency(s)

    def test_computable_with_invalid_spot_or_strike_basis_rejected(self):
        mutations = [
            ("spot_ref", None),
            ("spot_ref", 0),
            ("n_strikes_with_valid_quotes", 0),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                s = copy.deepcopy(self.summary)
                s["assessment"][field] = value
                with self.assertRaises(ValueError):
                    validate_probe_summary_consistency(s)


class ProbeSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.summary = build_probe_summary(_assess(), as_of=AS_OF, generated_at="2026-06-10T00:00:00+08:00")

    def _reject(self, s):
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)

    def test_valid_summary(self):
        jsonschema.validate(self.summary, self.schema)

    def test_boundary_all_false(self):
        for k in ("production", "real_money", "satisfies_ship_gate", "builds_iv_feed"):
            self.assertFalse(self.summary["boundary"][k])

    def test_threshold_drift_rejected(self):
        s = copy.deepcopy(self.summary)
        s["thresholds"]["min_valid_quote_days"] = 1
        self._reject(s)

    def test_builds_iv_feed_true_rejected(self):
        s = copy.deepcopy(self.summary)
        s["boundary"]["builds_iv_feed"] = True
        self._reject(s)

    def test_extra_field_rejected(self):
        s = copy.deepcopy(self.summary)
        s["unexpected"] = 1
        self._reject(s)

    def test_schema_computable_contradiction_rejected(self):
        s = copy.deepcopy(self.summary)
        s["computable"] = True
        s["assessment"]["computable"] = False
        self._reject(s)

    def test_schema_computable_requires_latest_spot_and_strikes(self):
        mutations = [
            ("latest_usable_date", None),
            ("latest_usable_date", "notadate"),
            ("spot_ref", None),
            ("spot_ref", 0),
            ("n_strikes_with_valid_quotes", 0),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                s = copy.deepcopy(self.summary)
                s["assessment"][field] = value
                self._reject(s)


if __name__ == "__main__":
    unittest.main()
