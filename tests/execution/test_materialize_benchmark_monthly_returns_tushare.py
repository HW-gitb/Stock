from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import runners.materialize_benchmark_monthly_returns_tushare as materializer
from runners.materialize_benchmark_monthly_returns_tushare import (
    API_FAMILIES,
    DEFAULT_OUT_DIR,
    MONTHLY_RETURN_METHOD,
    build_benchmark_payload,
    main,
    metadata_output_path,
    monthly_returns_from_rows,
    normalized_index_rows,
    return_output_path,
    selected_benchmarks,
    validate_date_range,
)


class FakeIndexDailyPro:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.frames = {
            "000852.SH": pd.DataFrame(
                [
                    {"ts_code": "000852.SH", "trade_date": "20260628", "close": 105.0},
                    {"ts_code": "000852.SH", "trade_date": "20260603", "close": 100.0},
                    {"ts_code": "000852.SH", "trade_date": "20260531", "close": 110.0},
                    {"ts_code": "000852.SH", "trade_date": "20260506", "close": 100.0},
                ]
            ),
            "000300.SH": pd.DataFrame(
                [
                    {"ts_code": "000300.SH", "trade_date": "20260506", "close": 4000.0},
                    {"ts_code": "000300.SH", "trade_date": "20260531", "close": 3960.0},
                    {"ts_code": "000300.SH", "trade_date": "20260603", "close": 3960.0},
                    {"ts_code": "000300.SH", "trade_date": "20260628", "close": 4000.0},
                ]
            ),
        }

    def index_daily(self, **kwargs):
        self.calls.append(kwargs)
        return self.frames[str(kwargs["ts_code"])]


class BenchmarkMonthlyReturnsMaterializerTest(unittest.TestCase):
    def test_build_benchmark_payload_uses_first_last_close_by_month(self) -> None:
        payload = build_benchmark_payload(
            FakeIndexDailyPro(),
            benchmark="csi1000",
            start_date="20260501",
            end_date="20260630",
            generated_at="2026-05-26T12:00:00+00:00",
        )

        self.assertEqual(payload["returns"], {"202605": 0.1, "202606": 0.05})
        metadata = payload["metadata"]
        self.assertEqual(metadata["benchmark"], "csi1000")
        self.assertEqual(metadata["role"], "primary")
        self.assertEqual(metadata["source"], "tushare:index_daily/000852.SH")
        self.assertEqual(metadata["api_families"], API_FAMILIES)
        self.assertEqual(metadata["monthly_return_method"], MONTHLY_RETURN_METHOD)
        self.assertEqual(metadata["date_range"], {"start_date": "20260501", "end_date": "20260630"})
        self.assertEqual(metadata["months"][0]["first_trade_date"], "20260506")
        self.assertEqual(metadata["months"][0]["last_trade_date"], "20260531")

    def test_cli_writes_primary_and_secondary_return_jsons_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            with mock.patch.object(materializer, "tushare_pro", return_value=FakeIndexDailyPro()):
                rc = main(
                    [
                        "--start-date",
                        "20260501",
                        "--end-date",
                        "20260630",
                        "--out-dir",
                        str(out_dir),
                        "--generated-at",
                        "2026-05-26T12:00:00+00:00",
                    ]
                )

            csi1000 = json.loads((out_dir / "benchmark_monthly_returns_csi1000.json").read_text(encoding="utf-8"))
            csi300 = json.loads((out_dir / "benchmark_monthly_returns_csi300.json").read_text(encoding="utf-8"))
            csi300_meta = json.loads(
                (out_dir / "benchmark_monthly_returns_csi300_metadata.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(rc, 0)
        self.assertEqual(csi1000, {"202605": 0.1, "202606": 0.05})
        self.assertEqual(csi300, {"202605": -0.01, "202606": 0.0101010101})
        self.assertEqual(csi300_meta["role"], "secondary")
        self.assertEqual(csi300_meta["source"], "tushare:index_daily/000300.SH")

    def test_output_paths_default_to_forward_aggregate_dir(self) -> None:
        self.assertEqual(
            return_output_path(DEFAULT_OUT_DIR, "csi1000"),
            DEFAULT_OUT_DIR / "benchmark_monthly_returns_csi1000.json",
        )
        self.assertEqual(
            metadata_output_path(DEFAULT_OUT_DIR, "csi1000"),
            DEFAULT_OUT_DIR / "benchmark_monthly_returns_csi1000_metadata.json",
        )

    def test_selected_benchmarks_defaults_to_primary_and_secondary(self) -> None:
        self.assertEqual(selected_benchmarks(None), ["csi1000", "csi300"])
        self.assertEqual(selected_benchmarks(["csi300", "csi300"]), ["csi300"])

    def test_invalid_dates_raise_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "start_date must be YYYYMMDD"):
            validate_date_range("2026-05-01", "20260630")
        with self.assertRaisesRegex(ValueError, "start_date must be <= end_date"):
            validate_date_range("20260630", "20260501")

    def test_single_row_month_is_rejected(self) -> None:
        rows = normalized_index_rows(
            pd.DataFrame([{"trade_date": "20260506", "close": 100.0}]),
            "20260501",
            "20260531",
        )

        with self.assertRaisesRegex(ValueError, "requires at least two index_daily rows"):
            monthly_returns_from_rows(rows)

    def test_missing_required_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_daily missing required columns"):
            normalized_index_rows(pd.DataFrame([{"trade_date": "20260506"}]), "20260501", "20260531")

    def test_non_positive_close_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "close values must be positive"):
            normalized_index_rows(
                pd.DataFrame(
                    [
                        {"trade_date": "20260506", "close": 100.0},
                        {"trade_date": "20260531", "close": 0.0},
                    ]
                ),
                "20260501",
                "20260531",
            )


if __name__ == "__main__":
    unittest.main()
