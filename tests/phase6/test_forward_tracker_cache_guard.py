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


def _tracker_row(as_of: str, ts_code: str) -> dict:
    row = {col: pd.NA for col in forward_tracker.SCHEMA_COLUMNS}
    row.update({
        "as_of": as_of,
        "captured_at": "2026-06-01T00:00:00+00:00",
        "ts_code": ts_code,
        "name": ts_code,
        "tier": "Tier1",
        "final_score": 60,
        "ret_5d_status": "pending_capture",
        "ret_10d_status": "pending_capture",
        "ret_20d_status": "pending_capture",
    })
    return row


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

    def test_write_tracker_uses_same_directory_temp_file_and_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker_path = Path(tmp) / "forward_tracker.csv"
            df = pd.DataFrame([
                _tracker_row("20240202", "000002.SZ"),
                _tracker_row("20240131", "000001.SZ"),
            ])

            with (
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker.os, "replace", wraps=forward_tracker.os.replace) as replace_spy,
            ):
                forward_tracker._write_tracker(df)

            replace_spy.assert_called_once()
            tmp_arg, target_arg = replace_spy.call_args.args
            tmp_path = Path(tmp_arg)
            self.assertEqual(Path(target_arg), tracker_path)
            self.assertEqual(tmp_path.parent, tracker_path.parent)
            self.assertTrue(tmp_path.name.startswith(f".{tracker_path.name}."))
            self.assertTrue(tmp_path.name.endswith(".tmp"))
            self.assertFalse(tmp_path.exists())

            written = pd.read_csv(tracker_path, dtype={"as_of": str, "ts_code": str})
            self.assertEqual(list(written.columns), forward_tracker.SCHEMA_COLUMNS)
            self.assertEqual(written["as_of"].tolist(), ["20240131", "20240202"])
            self.assertEqual(written["ts_code"].tolist(), ["000001.SZ", "000002.SZ"])

    def test_write_tracker_preserves_existing_file_when_csv_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker_path = Path(tmp) / "forward_tracker.csv"
            tracker_path.write_text("original\n", encoding="utf-8")
            df = pd.DataFrame([_tracker_row("20240131", "000001.SZ")])

            with (
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(pd.DataFrame, "to_csv", side_effect=RuntimeError("boom")),
            ):
                with self.assertRaises(RuntimeError):
                    forward_tracker._write_tracker(df)

            self.assertEqual(tracker_path.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(list(tracker_path.parent.glob(f".{tracker_path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
