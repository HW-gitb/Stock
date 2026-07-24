import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_third_knife_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class ThirdKnifeClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()

    def test_canonical_price_clock_is_validated_and_used_for_trade_calendar(self):
        calls = []

        def trade_cal(**kwargs):
            calls.append(kwargs)
            if kwargs["start_date"] == kwargs["end_date"]:
                dates = [kwargs["end_date"]]
            else:
                dates = ["20260717", "20260716"]
            return pd.DataFrame([{"cal_date": value, "is_open": 1} for value in dates])

        old = (self.egs.TODAY, self.egs.TODAY_DT, self.egs.PRICE_AS_OF, self.egs.PRICE_AS_OF_DT)
        try:
            self.egs.pro = SimpleNamespace(trade_cal=trade_cal)
            with patch.object(self.egs, "load_cache", return_value=None), \
                 patch.object(self.egs, "save_cache"):
                self.egs.set_asof("20260720", price_as_of="20260717")
                dates = self.egs.get_trade_dates(2)
            self.assertEqual(self.egs.PRICE_AS_OF, "20260717")
            self.assertEqual(calls[-1]["end_date"], "20260717")
            self.assertEqual(dates, ["20260717", "20260716"])
        finally:
            self.egs.TODAY, self.egs.TODAY_DT, self.egs.PRICE_AS_OF, self.egs.PRICE_AS_OF_DT = old

    def test_qfq_cache_key_binds_price_data_through(self):
        self.assertIn("20260717", self.egs._daily_all_qfq_cache_key("20260717"))
        self.assertNotEqual(
            self.egs._daily_all_qfq_cache_key("20260720"),
            self.egs._daily_all_qfq_cache_key("20260717"),
        )


if __name__ == "__main__":
    unittest.main()
