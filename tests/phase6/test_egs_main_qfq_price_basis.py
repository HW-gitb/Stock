"""EGS full-market qfq price-basis and cache-migration guards."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_qfq_price_basis_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _daily_row(trade_date, close, *, pre_close, high=None, low=None):
    return {
        "ts_code": "600000.SH",
        "trade_date": trade_date,
        "open": close,
        "high": high if high is not None else close * 1.1,
        "low": low if low is not None else close * 0.9,
        "close": close,
        "pre_close": pre_close,
        "pct_chg": (close / pre_close - 1.0) * 100.0,
        "vol": 1000.0,
        "amount": 100000.0,
    }


def _factor_row(trade_date, factor, code="600000.SH"):
    return {"ts_code": code, "trade_date": trade_date, "adj_factor": factor}


class _FakePro:
    def __init__(self, daily_by_date, factor_by_date):
        self.daily_by_date = daily_by_date
        self.factor_by_date = factor_by_date
        self.daily_calls = []
        self.factor_calls = []

    def daily(self, *, trade_date, fields):
        self.daily_calls.append((trade_date, fields))
        return self.daily_by_date[trade_date].copy()

    def adj_factor(self, *, trade_date, fields):
        self.factor_calls.append((trade_date, fields))
        return self.factor_by_date[trade_date].copy()


class EgsMainQfqPriceBasisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()

    def _two_day_frames(self):
        # A 2:1 ex-rights event: raw close halves, qfq close remains 5.0.
        daily = [
            pd.DataFrame([_daily_row("20260601", 10.0, pre_close=10.0)]),
            pd.DataFrame([_daily_row("20260602", 5.0, pre_close=10.0)]),
        ]
        factors = [
            pd.DataFrame([_factor_row("20260601", 1.0)]),
            pd.DataFrame([_factor_row("20260602", 2.0)]),
        ]
        return daily, factors

    def test_qfq_stats_ignore_ex_rights_raw_price_jump(self):
        daily, factors = self._two_day_frames()
        panel = self.egs._build_qfq_daily_all(
            daily, factors, "20260602", ["20260601", "20260602"]
        )
        self.egs.CONF["daily_stats_min_rows"] = 1
        stats = self.egs.precompute_stock_stats({"600000.SH"}, panel)

        self.assertAlmostEqual(float(panel.loc[panel["trade_date"] == "20260601", "qfq_close"].iloc[0]), 5.0)
        self.assertAlmostEqual(float(panel.loc[panel["trade_date"] == "20260602", "qfq_close"].iloc[0]), 5.0)
        self.assertAlmostEqual(float(stats.loc[0, "pct_5d"]), 0.0)
        self.assertEqual(stats.loc[0, "qfq_source_trade_date"], "20260602")

        qfq_rows = self.egs._rule6_daily_rows(
            panel, "600000.SH", ["20260602", "20260601"], price_basis="qfq"
        )
        raw_rows = self.egs._rule6_daily_rows(
            panel, "600000.SH", ["20260602", "20260601"], price_basis="raw"
        )
        self.assertAlmostEqual(qfq_rows[0]["pct_chg"], 0.0)
        self.assertAlmostEqual(raw_rows[0]["pct_chg"], -50.0)

    def test_missing_duplicate_or_future_factors_abort_the_batch(self):
        daily, factors = self._two_day_frames()
        factors[1] = pd.DataFrame([_factor_row("20260602", 2.0, code="000001.SZ")])
        with self.assertRaisesRegex(RuntimeError, "adj_factor coverage missing"):
            self.egs._build_qfq_daily_all(daily, factors, "20260602", ["20260601", "20260602"])

        daily, factors = self._two_day_frames()
        factors[1] = pd.DataFrame([
            _factor_row("20260602", 2.0), _factor_row("20260602", 2.0),
        ])
        with self.assertRaisesRegex(RuntimeError, "duplicate ts_code/trade_date"):
            self.egs._build_qfq_daily_all(daily, factors, "20260602", ["20260601", "20260602"])

        daily, factors = self._two_day_frames()
        factors[1] = pd.DataFrame([
            _factor_row("20260602", 2.0), _factor_row("20260603", 2.0),
        ])
        with self.assertRaisesRegex(RuntimeError, "future or unexpected"):
            self.egs._build_qfq_daily_all(daily, factors, "20260602", ["20260601", "20260602"])

    def test_raw_cache_cannot_be_reused_as_qfq_cache(self):
        daily, factors = self._two_day_frames()
        daily_by_date = {frame.iloc[0]["trade_date"]: frame for frame in daily}
        factor_by_date = {frame.iloc[0]["trade_date"]: frame for frame in factors}
        fake_pro = _FakePro(daily_by_date, factor_by_date)
        saved = {}
        cache_key = self.egs._daily_all_qfq_cache_key("20260602")
        raw_cache = pd.concat(daily, ignore_index=True)

        with patch.object(self.egs, "pro", fake_pro), \
             patch.object(self.egs, "load_cache", side_effect=lambda key: raw_cache if key == cache_key else None), \
             patch.object(self.egs, "save_cache", side_effect=lambda key, value: saved.setdefault(key, value)), \
             patch.object(self.egs, "safe_api", side_effect=lambda endpoint, **kwargs: endpoint(**kwargs)):
            panel = self.egs.get_daily_all(["20260602", "20260601"])

        self.assertEqual([call[0] for call in fake_pro.daily_calls], ["20260602", "20260601"])
        self.assertEqual([call[0] for call in fake_pro.factor_calls], ["20260602", "20260601"])
        self.assertIn(cache_key, saved)
        self.assertIn("qfq_close", panel.columns)
        self.assertTrue(panel["adj_factor_observed"].all())

    def test_qfq_cache_rejects_tampered_adjusted_prices(self):
        daily, factors = self._two_day_frames()
        panel = self.egs._build_qfq_daily_all(
            daily, factors, "20260602", ["20260601", "20260602"]
        )
        panel.loc[panel["trade_date"] == "20260601", [
            "qfq_open", "qfq_high", "qfq_low", "qfq_close",
        ]] *= 1.2
        with self.assertRaisesRegex(RuntimeError, "does not match observed adjustment factors"):
            self.egs._validate_cached_qfq_daily_all(panel, "20260602", ["20260601", "20260602"])

    def test_master_uses_same_day_qfq_quote_and_rejects_date_mismatch(self):
        df_l0 = pd.DataFrame([{"ts_code": "600000.SH", "pct_20d": 1.0}])
        stats = pd.DataFrame([{
            "ts_code": "600000.SH", "qfq_close": 5.0, "qfq_source_trade_date": "20260602",
        }])
        raw_quote = pd.DataFrame([{
            "ts_code": "600000.SH", "close": 10.0, "source_trade_date": "20260602",
        }])
        output = self.egs.build_master(df_l0, stats, raw_quote, pd.DataFrame(), {}, {})
        self.assertEqual(float(output.loc[0, "close"]), 5.0)
        self.assertEqual(float(output.loc[0, "raw_close"]), 10.0)

        stale_raw_quote = raw_quote.copy()
        stale_raw_quote.loc[0, "source_trade_date"] = "20260601"
        with self.assertRaisesRegex(RuntimeError, "does not match qfq candidate price date"):
            self.egs.build_master(df_l0, stats, stale_raw_quote, pd.DataFrame(), {}, {})


if __name__ == "__main__":
    unittest.main()
