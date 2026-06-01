import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import runners.forward_tracker as forward_tracker


def _cache_payload(benchmarks: dict[str, pd.DataFrame]) -> dict:
    return {
        "meta": {
            "start_date": "20240101",
            "end_date": "20240229",
            "adj": "qfq_via_adj_factor",
            "benchmarks": sorted(forward_tracker.BENCHMARKS.keys()),
        },
        "stocks": pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20240131"}]),
        "limits": pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20240131"}]),
        "benchmarks": benchmarks,
    }


class ForwardTrackerCacheGuardTests(unittest.TestCase):
    def _write_cache(self, path: Path, benchmarks: dict[str, pd.DataFrame]) -> None:
        with path.open("wb") as f:
            pickle.dump(_cache_payload(benchmarks), f)

    def test_cache_coverage_rejects_close_only_benchmark_frames_before_refetch(self) -> None:
        close_only = pd.DataFrame([
            {"trade_date": "20240131", "close": 3000.0},
            {"trade_date": "20240229", "close": 3100.0},
        ])
        benchmarks = {name: close_only.copy() for name in forward_tracker.BENCHMARKS}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            self._write_cache(cache_path, benchmarks)
            with patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path):
                ok, msg = forward_tracker._check_cache_coverage(["20240131"], 20)

        self.assertFalse(ok)
        self.assertIn("same-anchor", msg)
        self.assertIn("trade_date/open/close", msg)
        self.assertIn("csi300", msg)
        self.assertIn("csi1000", msg)

    def test_cache_coverage_accepts_same_anchor_benchmark_frames(self) -> None:
        same_anchor = pd.DataFrame([
            {"trade_date": "20240131", "open": 3000.0, "close": 3010.0},
            {"trade_date": "20240229", "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            self._write_cache(cache_path, benchmarks)
            with patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path):
                ok, msg = forward_tracker._check_cache_coverage(["20240131"], 20)

        self.assertTrue(ok)
        self.assertEqual(msg, "ok")

    def test_benchmark_cache_hint_uses_benchmark_only_helper(self) -> None:
        hint = "\n".join(
            forward_tracker._cache_refresh_hint(
                "forward_daily cache benchmark input is not same-anchor ready"
            )
        )

        self.assertIn("refresh_forward_daily_benchmark_open_tushare.py", hint)
        self.assertIn("CSI300/CSI1000 index_daily", hint)
        self.assertNotIn("--refresh-forward-daily", hint)


if __name__ == "__main__":
    unittest.main()
