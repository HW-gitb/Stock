import importlib.util
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from engine.a_short_csi300_window import CSI300_LIVE_WINDOW_SESSIONS


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
            "trade_date": (pd.Timestamp("2026-05-29") - pd.Timedelta(days=i)).strftime("%Y%m%d"),
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
        self.assertTrue(stats["pct_20d"].isna().all())
        self.assertEqual(stats["price_observation_count"].tolist(), [5])
        self.assertFalse(bool(stats.loc[0, "has_crash_veto"]))

    def test_eight_closes_never_impersonate_longer_momentum_windows(self) -> None:
        self.egs_main.CONF["daily_stats_min_rows"] = 1

        stats = self.egs_main.precompute_stock_stats(
            {"600000.SH"}, _daily_rows("600000.SH", 8)
        )

        self.assertEqual(int(stats.loc[0, "price_observation_count"]), 8)
        self.assertTrue(math.isnan(float(stats.loc[0, "pct_20d"])))
        self.assertTrue(math.isnan(float(stats.loc[0, "pct_60d"])))
        self.assertAlmostEqual(
            float(stats.loc[0, "pct_5d"]),
            (10.0 / 10.05 - 1) * 100,
        )

    def test_sixty_one_closes_compute_exact_session_returns(self) -> None:
        self.egs_main.CONF["daily_stats_min_rows"] = 1

        stats = self.egs_main.precompute_stock_stats(
            {"600000.SH"}, _daily_rows("600000.SH", 61)
        )

        self.assertEqual(int(stats.loc[0, "price_observation_count"]), 61)
        for sessions, column in ((5, "pct_5d"), (20, "pct_20d"), (60, "pct_60d")):
            with self.subTest(column=column):
                self.assertAlmostEqual(
                    float(stats.loc[0, column]),
                    (10.0 / (10.0 + sessions * 0.01) - 1) * 100,
                )

    def test_qfq_window_is_long_enough_for_the_longest_declared_lookback(self) -> None:
        self.assertEqual(self.egs_main.DAILY_STATS_MAX_LOOKBACK_SESSIONS, 60)
        self.assertEqual(self.egs_main.DAILY_STATS_REQUIRED_CLOSES, 61)
        self.assertEqual(self.egs_main.DAILY_ALL_QFQ_WINDOW_TRADING_DAYS, 65)
        self.assertEqual(
            self.egs_main.DAILY_ALL_QFQ_WINDOW_TRADING_DAYS,
            CSI300_LIVE_WINDOW_SESSIONS,
        )
        self.egs_main._validate_daily_qfq_window(65)

        with self.assertRaisesRegex(RuntimeError, "window=60, required=61"):
            self.egs_main._validate_daily_qfq_window(60)

        with patch.object(self.egs_main, "DAILY_ALL_QFQ_WINDOW_TRADING_DAYS", 60):
            with self.assertRaisesRegex(RuntimeError, "configuration is shorter.*window=60, required=61"):
                self.egs_main._validate_daily_qfq_window(60)

    def test_qfq_fetch_rejects_a_short_trade_date_window_before_cache_or_provider(self) -> None:
        dates = [
            (pd.Timestamp("20260602") - pd.Timedelta(days=i)).strftime("%Y%m%d")
            for i in range(60)
        ]
        with self.assertRaisesRegex(RuntimeError, "window is too short.*window=60, required=61"):
            self.egs_main.get_daily_all(
                dates,
                price_as_of=dates[0],
            )

    def test_short_history_count_is_main_board_only(self) -> None:
        stocks = pd.DataFrame({
            "ts_code": ["600000.SH", "300001.SZ", "000001.SZ"],
        })
        stats = pd.DataFrame({
            "ts_code": ["600000.SH", "300001.SZ", "000001.SZ"],
            "price_observation_count": [8, 8, 61],
        })

        self.assertEqual(
            self.egs_main._short_history_candidate_count(stocks, stats),
            1,
        )

    def test_250_symbols_with_six_closes_are_all_excluded_at_l0(self) -> None:
        self.egs_main.CONF["daily_stats_min_rows"] = 1
        codes = [f"{600000 + i:06d}.SH" for i in range(250)]
        stocks = pd.DataFrame({
            "ts_code": codes,
            "name": [f"name-{i}" for i in range(250)],
            "list_status": ["L"] * 250,
        })
        all_daily = pd.concat([_daily_rows(code, 6) for code in codes], ignore_index=True)
        stats = self.egs_main.precompute_stock_stats(set(codes), all_daily)
        exclusion_counts = {}

        filtered = self.egs_main.filter_l0(
            stocks,
            stats,
            set(),
            {},
            set(),
            set(),
            exclusion_counts=exclusion_counts,
        )

        self.assertTrue(filtered.empty)
        self.assertEqual(exclusion_counts["short_history_momentum"], 250)


if __name__ == "__main__":
    unittest.main()
