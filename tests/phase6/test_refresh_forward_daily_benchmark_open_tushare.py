import pickle
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import runners.backtest_rank as backtest_rank
from runners.refresh_forward_daily_benchmark_open_tushare import (
    CACHE_UPDATE_METHOD,
    refresh_forward_daily_benchmark_open,
)


class FakeBenchmarkPro:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.frames = {
            "000300.SH": pd.DataFrame(
                [
                    {"ts_code": "000300.SH", "trade_date": "20240131", "open": 3900.0, "close": 3910.0},
                    {"ts_code": "000300.SH", "trade_date": "20240430", "open": 4100.0, "close": 4110.0},
                ]
            ),
            "000852.SH": pd.DataFrame(
                [
                    {"ts_code": "000852.SH", "trade_date": "20240131", "open": 5900.0, "close": 5910.0},
                    {"ts_code": "000852.SH", "trade_date": "20240430", "open": 6100.0, "close": 6110.0},
                ]
            ),
        }

    def index_daily(self, **kwargs):
        self.calls.append(kwargs)
        return self.frames[str(kwargs["ts_code"])]

    def daily(self, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError(f"unexpected stock daily fetch: {kwargs}")

    def adj_factor(self, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError(f"unexpected adj_factor fetch: {kwargs}")

    def stk_limit(self, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError(f"unexpected stk_limit fetch: {kwargs}")

    def trade_cal(self, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError(f"unexpected trade_cal fetch: {kwargs}")


def _close_only_cache() -> dict:
    close_only = pd.DataFrame(
        [
            {"trade_date": "20240131", "close": 3000.0},
            {"trade_date": "20240430", "close": 3100.0},
        ]
    )
    return {
        "meta": {
            "start_date": "20240131",
            "end_date": "20240430",
            "adj": "qfq_via_adj_factor",
            "benchmarks": ["csi300", "csi1000"],
        },
        "stocks": pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20240131", "open": 10.0, "close": 10.5},
            ]
        ),
        "limits": pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20240131", "up_limit": 11.0, "down_limit": 9.0},
            ]
        ),
        "benchmarks": {"csi300": close_only.copy(), "csi1000": close_only.copy()},
    }


def _write_cache(path: Path, payload: dict) -> None:
    with path.open("wb") as handle:
        pickle.dump(payload, handle)


def _read_cache(path: Path) -> dict:
    with path.open("rb") as handle:
        return pickle.load(handle)


class RefreshForwardDailyBenchmarkOpenTests(unittest.TestCase):
    def test_refresh_patches_only_benchmark_frames_and_preserves_stock_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "forward_daily.pkl"
            _write_cache(cache_path, _close_only_cache())

            pro = FakeBenchmarkPro()
            summary = refresh_forward_daily_benchmark_open(
                pro,
                cache_path=cache_path,
                generated_at="2026-06-01T12:00:00+00:00",
            )
            cached = _read_cache(cache_path)

        self.assertEqual([call["ts_code"] for call in pro.calls], ["000300.SH", "000852.SH"])
        self.assertTrue(all(call["fields"] == "ts_code,trade_date,open,close" for call in pro.calls))
        self.assertEqual(summary["update_method"], CACHE_UPDATE_METHOD)
        self.assertEqual(summary["stock_rows_preserved"], 1)
        self.assertEqual(summary["limit_rows_preserved"], 1)
        self.assertEqual(cached["stocks"].iloc[0]["ts_code"], "000001.SZ")
        self.assertEqual(cached["limits"].iloc[0]["up_limit"], 11.0)
        self.assertEqual(cached["meta"]["benchmark_open_patch"]["generated_at"], "2026-06-01T12:00:00+00:00")
        for name in ["csi300", "csi1000"]:
            self.assertEqual(list(cached["benchmarks"][name].columns), ["trade_date", "open", "close"])
            self.assertEqual(len(cached["benchmarks"][name]), 2)

    def test_patched_cache_is_reusable_by_backtest_without_refetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "forward_daily.pkl"
            _write_cache(cache_path, _close_only_cache())
            refresh_forward_daily_benchmark_open(FakeBenchmarkPro(), cache_path=cache_path)

            with mock.patch.object(backtest_rank, "FORWARD_DAILY_CACHE", cache_path), mock.patch.object(
                backtest_rank,
                "_tushare_pro",
                side_effect=AssertionError("unexpected forward_daily refetch"),
            ):
                payload = backtest_rank.fetch_forward_daily(["20240131"], 5, refresh=False)

        self.assertEqual(set(payload["benchmarks"]), {"csi300", "csi1000"})
        self.assertEqual(list(payload["benchmarks"]["csi300"].columns), ["trade_date", "open", "close"])

    def test_dry_run_does_not_mutate_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "forward_daily.pkl"
            _write_cache(cache_path, _close_only_cache())

            summary = refresh_forward_daily_benchmark_open(
                FakeBenchmarkPro(),
                cache_path=cache_path,
                dry_run=True,
            )
            cached = _read_cache(cache_path)

        self.assertTrue(summary["dry_run"])
        self.assertEqual(list(cached["benchmarks"]["csi300"].columns), ["trade_date", "close"])
        self.assertNotIn("benchmark_open_patch", cached["meta"])


if __name__ == "__main__":
    unittest.main()
