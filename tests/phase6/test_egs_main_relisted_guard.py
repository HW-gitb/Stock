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

    def test_relisted_filter_uses_five_trading_date_window_and_v2_cache(self) -> None:
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
             patch.object(self.egs_main, "get_daily_all", return_value=all_daily):
            relisted = self.egs_main.get_relisted_stocks(trade_dates)

        self.assertEqual(relisted, {"000001.SZ", "000003.SZ"})
        self.assertEqual(saved["relisted_20260530_v2"], {"000001.SZ", "000003.SZ"})

    def test_relisted_cutoff_uses_oldest_available_date_for_short_history(self) -> None:
        trade_dates = ["20260530", "20260529", "20260528"]

        self.assertEqual(
            self.egs_main._lookback_cutoff_trade_date(trade_dates, 5),
            "20260528",
        )


if __name__ == "__main__":
    unittest.main()
