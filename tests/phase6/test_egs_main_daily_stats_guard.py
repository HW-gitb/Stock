import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_daily_stats_guard_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _daily_rows(code: str, n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append({
            "ts_code": code,
            "trade_date": f"202605{29 - (i % 20):02d}",
            "open": 10.0,
            "high": 10.6,
            "low": 9.8,
            "close": 10.0 + i * 0.01,
            "qfq_open": 10.0,
            "qfq_high": 10.6,
            "qfq_low": 9.8,
            "qfq_close": 10.0 + i * 0.01,
            "pre_close": 9.9 + i * 0.01,
            "pct_chg": 1.0,
            "vol": 1000.0,
            "amount": 200000.0,
        })
    return pd.DataFrame(rows)


class EgsMainDailyStatsGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def setUp(self) -> None:
        self.old_min_rows = self.egs_main.CONF["daily_stats_min_rows"]
        self.egs_main.CONF["daily_stats_min_rows"] = 1000

    def tearDown(self) -> None:
        self.egs_main.CONF["daily_stats_min_rows"] = self.old_min_rows

    def test_empty_daily_payload_rejects_neutral_stats(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "all_daily is empty"):
            self.egs_main.precompute_stock_stats({"600000.SH"}, pd.DataFrame())

    def test_tiny_daily_payload_rejects_neutral_stats(self) -> None:
        all_daily = _daily_rows("600000.SH", 999)

        with self.assertRaisesRegex(RuntimeError, "999 rows below daily_stats_min_rows=1000"):
            self.egs_main.precompute_stock_stats({"600000.SH"}, all_daily)

    def test_daily_payload_with_no_stock_universe_match_rejects(self) -> None:
        all_daily = _daily_rows("600000.SH", 1000)

        with self.assertRaisesRegex(RuntimeError, "after stock-universe match: 0 rows"):
            self.egs_main.precompute_stock_stats({"000001.SZ"}, all_daily)

    def test_sufficient_daily_payload_still_computes_stats(self) -> None:
        self.egs_main.CONF["daily_stats_min_rows"] = 5
        all_daily = _daily_rows("600000.SH", 5)

        stats = self.egs_main.precompute_stock_stats({"600000.SH"}, all_daily)

        self.assertEqual(stats["ts_code"].tolist(), ["600000.SH"])
        self.assertTrue(stats["avg_amount_20d"].notna().all())
        self.assertTrue(stats["pct_20d"].notna().all())
        self.assertFalse(bool(stats.loc[0, "has_crash_veto"]))


if __name__ == "__main__":
    unittest.main()
