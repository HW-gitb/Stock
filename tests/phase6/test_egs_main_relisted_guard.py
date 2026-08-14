import importlib.util
import sys
import tempfile
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
        spec = importlib.util.spec_from_file_location("egs_main_relisted_guard_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class EgsMainRelistedGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def setUp(self) -> None:
        self.old_lookback = self.egs_main.CONF["suspend_lookback"]
        self.egs_main.CONF["suspend_lookback"] = 5

    def tearDown(self) -> None:
        self.egs_main.CONF["suspend_lookback"] = self.old_lookback

    def test_lookback_cutoff_is_inclusive_window_not_extra_day(self) -> None:
        trade_dates = ["20260530", "20260529", "20260528", "20260527", "20260526", "20260523"]

        self.assertEqual(
            self.egs_main._lookback_cutoff_trade_date(trade_dates, 5),
            "20260526",
        )

    def test_relisted_filter_reuses_supplied_daily_panel_and_v2_cache(self) -> None:
        trade_dates = ["20260530", "20260529", "20260528", "20260527", "20260526", "20260523"]
        all_daily = pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": "20260526"},
            {"ts_code": "000001.SZ", "trade_date": "20260527"},
            {"ts_code": "000002.SZ", "trade_date": "20260523"},
            {"ts_code": "000002.SZ", "trade_date": "20260526"},
            {"ts_code": "000003.SZ", "trade_date": "20260530"},
        ])
        saved = {}

        def fake_save_cache(key, value):
            saved[key] = value

        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache", side_effect=fake_save_cache), \
             patch.object(self.egs_main, "get_daily_all", side_effect=AssertionError("unexpected daily fetch")):
            relisted = self.egs_main.get_relisted_stocks(trade_dates, all_daily=all_daily)

        self.assertEqual(relisted, {"000001.SZ", "000003.SZ"})
        self.assertEqual(saved["relisted_20260530_v2"], {"000001.SZ", "000003.SZ"})

    def test_relisted_filter_without_supplied_panel_fetches_once_for_compatibility(self) -> None:
        trade_dates = ["20260530", "20260529", "20260528", "20260527", "20260526", "20260523"]
        all_daily = pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": "20260526"},
            {"ts_code": "000001.SZ", "trade_date": "20260527"},
            {"ts_code": "000002.SZ", "trade_date": "20260523"},
            {"ts_code": "000002.SZ", "trade_date": "20260526"},
            {"ts_code": "000003.SZ", "trade_date": "20260530"},
        ])
        saved = {}

        with patch.object(self.egs_main, "load_cache", return_value=None), \
             patch.object(self.egs_main, "save_cache", side_effect=lambda key, value: saved.setdefault(key, value)), \
             patch.object(self.egs_main, "get_daily_all", return_value=all_daily) as fetch:
            relisted = self.egs_main.get_relisted_stocks(trade_dates)

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(relisted, {"000001.SZ", "000003.SZ"})
        self.assertEqual(saved, {"relisted_20260530_v2": {"000001.SZ", "000003.SZ"}})

    def test_run_egs_passes_existing_daily_panel_to_relisted_filter(self) -> None:
        trade_dates = ["20260814", "20260813", "20260812"]
        all_daily = pd.DataFrame([
            {"ts_code": "600000.SH", "trade_date": "20260814"},
        ])
        universe = pd.DataFrame([{"ts_code": "600000.SH", "name": "sample"}])

        class StopAtRelisted(RuntimeError):
            pass

        def stop_at_relisted(received_dates, *, all_daily=None):
            self.assertEqual(received_dates, trade_dates)
            self.assertIs(all_daily, all_daily_panel)
            raise StopAtRelisted

        all_daily_panel = all_daily
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as output_root, \
             patch.dict(self.egs_main.CONF, {}, clear=False), \
             patch.object(self.egs_main, "get_trade_dates", return_value=trade_dates), \
             patch.object(self.egs_main, "get_trade_calendar_context", return_value={}), \
             patch.object(self.egs_main, "_require_nonempty_stock_universe", return_value=universe), \
             patch.object(self.egs_main, "get_sw_industry_map", return_value={}), \
             patch.object(self.egs_main, "get_csi300_return", return_value=0.0), \
             patch.object(self.egs_main, "get_daily_all", return_value=all_daily) as fetch, \
             patch.object(self.egs_main, "get_suspend_info", return_value=set()), \
             patch.object(self.egs_main, "get_daily_basic", return_value=pd.DataFrame()), \
             patch.object(self.egs_main, "get_relisted_stocks", side_effect=stop_at_relisted):
            with self.assertRaises(StopAtRelisted):
                self.egs_main.run_egs(
                    backtest_mode=True,
                    output_root=output_root,
                    price_as_of=trade_dates[0],
                )

        self.assertEqual(fetch.call_count, 1)

    def test_relisted_cutoff_uses_oldest_available_date_for_short_history(self) -> None:
        trade_dates = ["20260530", "20260529", "20260528"]

        self.assertEqual(
            self.egs_main._lookback_cutoff_trade_date(trade_dates, 5),
            "20260528",
        )


if __name__ == "__main__":
    unittest.main()
