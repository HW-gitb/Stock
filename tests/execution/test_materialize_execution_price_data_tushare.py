from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import pandas as pd

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - environment guard
    Draft7Validator = None  # type: ignore[assignment]

from runners.backtest_execution import ROOT
import runners.backtest_execution as execution_runner
import runners.materialize_execution_price_data_tushare as materializer
from runners.materialize_execution_price_data_tushare import (
    DEFAULT_OUT_DIR,
    TUSHARE_API_FAMILIES,
    add_calendar_days,
    build_payload_from_tushare,
    cache_path_for_request,
    load_cached_payload,
    main,
    output_path,
    resolve_date_range,
    symbols_from_analysis_input,
    validate_payload_matches_request,
    write_payload,
)
from tests.support.analysis_input_payload import cloned_minimal_analysis_input_payload


class FakeTusharePro:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.daily_by_symbol = {
            "600000.SH": pd.DataFrame(
                [
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260522",
                        "open": 10.0,
                        "high": 10.8,
                        "low": 9.9,
                        "close": 10.5,
                        "pre_close": 9.8,
                    },
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260525",
                        "open": 10.6,
                        "high": 11.0,
                        "low": 10.4,
                        "close": 10.9,
                        "pre_close": 10.5,
                    },
                ]
            ),
            "600001.SH": pd.DataFrame(
                [
                    {
                        "ts_code": "600001.SH",
                        "trade_date": "20260522",
                        "open": 20.0,
                        "high": 20.8,
                        "low": 19.9,
                        "close": 20.5,
                        "pre_close": 19.8,
                    }
                ]
            ),
        }
        self.adj_by_symbol = {
            "600000.SH": pd.DataFrame(
                [
                    {"ts_code": "600000.SH", "trade_date": "20260522", "adj_factor": 2.0},
                    {"ts_code": "600000.SH", "trade_date": "20260525", "adj_factor": 2.0},
                ]
            ),
            "600001.SH": pd.DataFrame(
                [{"ts_code": "600001.SH", "trade_date": "20260522", "adj_factor": 3.0}]
            ),
        }
        self.limit_by_symbol = {
            "600000.SH": pd.DataFrame(
                [
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260522",
                        "up_limit": 10.78,
                        "down_limit": 8.82,
                    },
                    {
                        "ts_code": "600000.SH",
                        "trade_date": "20260525",
                        "up_limit": 11.55,
                        "down_limit": 9.45,
                    },
                ]
            )
        }

    def trade_cal(self, **kwargs):
        self.calls.append("trade_cal")
        return pd.DataFrame({"cal_date": ["20260522", "20260525"]})

    def daily(self, **kwargs):
        self.calls.append(f"daily:{kwargs['ts_code']}")
        return self.daily_by_symbol.get(kwargs["ts_code"], pd.DataFrame())

    def adj_factor(self, **kwargs):
        self.calls.append(f"adj_factor:{kwargs['ts_code']}")
        return self.adj_by_symbol.get(kwargs["ts_code"], pd.DataFrame())

    def stk_limit(self, **kwargs):
        self.calls.append(f"stk_limit:{kwargs['ts_code']}")
        return self.limit_by_symbol.get(kwargs["ts_code"], pd.DataFrame())


@unittest.skipIf(Draft7Validator is None, "jsonschema not installed")
class TushareExecutionPriceDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._analysis_input_tmp = tempfile.TemporaryDirectory()
        cls.analysis_input_path = Path(cls._analysis_input_tmp.name) / "analysis_input.json"
        cls.analysis_input_path.write_text(
            json.dumps(cloned_minimal_analysis_input_payload()), encoding="utf-8"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._analysis_input_tmp.cleanup()

    def test_build_payload_from_tushare_is_schema_valid(self) -> None:
        payload = build_payload_from_tushare(
            FakeTusharePro(),
            symbols=["600000.SH", "600001.SH"],
            as_of="20260522",
            start_date="20260522",
            end_date="20260525",
            generated_at="2026-05-26T00:00:00+00:00",
        )
        schema = json.loads(
            (ROOT / "schemas" / "execution_price_data.schema.json").read_text(
                encoding="utf-8"
            )
        )
        errors = sorted(
            Draft7Validator(schema).iter_errors(payload),
            key=lambda item: list(item.path),
        )

        self.assertEqual(errors, [])
        self.assertEqual(payload["source"]["api_families"], TUSHARE_API_FAMILIES)
        self.assertEqual(payload["source"]["calendar_source"], "tushare.trade_cal")
        self.assertEqual(payload["symbols"], ["600000.SH", "600001.SH"])
        first_row = payload["rows"][0]
        self.assertEqual(first_row["ts_code"], "600000.SH")
        self.assertEqual(first_row["trade_date"], "20260522")
        self.assertEqual(first_row["open_qfq"], 20.0)
        self.assertEqual(first_row["up_limit"], 21.56)
        self.assertEqual(first_row["source_flags"], ["daily", "adj_factor", "stk_limit"])
        no_limit_row = [row for row in payload["rows"] if row["ts_code"] == "600001.SH"][0]
        self.assertIsNone(no_limit_row["up_limit"])
        self.assertEqual(no_limit_row["source_flags"], ["daily", "adj_factor"])

    def test_missing_as_of_row_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "--as-of price row"):
            build_payload_from_tushare(
                FakeTusharePro(),
                symbols=["600000.SH", "600002.SH"],
                as_of="20260522",
                start_date="20260522",
                end_date="20260525",
                generated_at="2026-05-26T00:00:00+00:00",
            )

    def test_non_trading_as_of_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a trading day per Tushare trade_cal"):
            build_payload_from_tushare(
                FakeTusharePro(),
                symbols=["600000.SH"],
                as_of="20260524",
                start_date="20260522",
                end_date="20260525",
                generated_at="2026-05-26T00:00:00+00:00",
            )

    def test_symbols_from_analysis_input_fixture(self) -> None:
        self.assertEqual(
            symbols_from_analysis_input(self.analysis_input_path),
            ["600000.SH", "600001.SH"],
        )

    def test_resolve_date_range_defaults_and_validates(self) -> None:
        self.assertEqual(resolve_date_range("20260522", None, None, 3), ("20260522", "20260525"))
        self.assertEqual(add_calendar_days("20260131", 5), "20260205")
        self.assertEqual(add_calendar_days("20261231", 5), "20270105")
        with self.assertRaisesRegex(ValueError, "date_range must cover --as-of"):
            resolve_date_range("20260522", "20260523", "20260525", 3)

    def test_output_and_cache_path_helpers(self) -> None:
        self.assertEqual(
            output_path("20260522", None),
            DEFAULT_OUT_DIR / "execution_price_data_tushare_20260522.json",
        )
        self.assertEqual(
            cache_path_for_request(Path("cache"), ["600001.SH", "600000.SH"], "20260522", "20260525"),
            cache_path_for_request(Path("cache"), ["600000.SH", "600001.SH"], "20260522", "20260525"),
        )

    def test_cache_roundtrip_validates_payload(self) -> None:
        payload = build_payload_from_tushare(
            FakeTusharePro(),
            symbols=["600000.SH"],
            as_of="20260522",
            start_date="20260522",
            end_date="20260525",
            generated_at="2026-05-26T00:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            write_payload(payload, path)

            cached = load_cached_payload(path)

        self.assertEqual(cached, payload)

    def test_cached_payload_must_match_request(self) -> None:
        payload = build_payload_from_tushare(
            FakeTusharePro(),
            symbols=["600000.SH"],
            as_of="20260522",
            start_date="20260522",
            end_date="20260525",
            generated_at="2026-05-26T00:00:00+00:00",
        )

        validate_payload_matches_request(
            payload,
            symbols=["600000.SH"],
            as_of="20260522",
            start_date="20260522",
            end_date="20260525",
        )
        with self.assertRaisesRegex(ValueError, "symbols do not match"):
            validate_payload_matches_request(
                payload,
                symbols=["600001.SH"],
                as_of="20260522",
                start_date="20260522",
                end_date="20260525",
            )

    def test_cli_reuses_cache_without_fetch(self) -> None:
        payload = build_payload_from_tushare(
            FakeTusharePro(),
            symbols=["600000.SH"],
            as_of="20260522",
            start_date="20260522",
            end_date="20260525",
            generated_at="2026-05-26T00:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            out_path = Path(tmpdir) / "out.json"
            cache_path = cache_path_for_request(
                cache_dir,
                ["600000.SH"],
                "20260522",
                "20260525",
            )
            write_payload(payload, cache_path)

            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--analysis-input",
                    str(self.analysis_input_path),
                    "--symbols",
                    "600000.SH",
                    "--end-date",
                    "20260525",
                    "--cache-dir",
                    str(cache_dir),
                    "--out-path",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), payload)

    def test_tushare_pro_requires_token_before_importing_client(self) -> None:
        with mock.patch.dict(os.environ, {"TUSHARE_TOKEN": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "TUSHARE_TOKEN is required"):
                materializer.tushare_pro()

    def test_cli_refresh_bypasses_matching_cache(self) -> None:
        stale_payload = build_payload_from_tushare(
            FakeTusharePro(),
            symbols=["600000.SH"],
            as_of="20260522",
            start_date="20260522",
            end_date="20260525",
            generated_at="stale-cache",
        )
        fake = FakeTusharePro()
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            out_path = Path(tmpdir) / "out.json"
            cache_path = cache_path_for_request(cache_dir, ["600000.SH"], "20260522", "20260525")
            write_payload(stale_payload, cache_path)

            with mock.patch.object(materializer, "tushare_pro", return_value=fake):
                rc = main(
                    [
                        "--as-of",
                        "20260522",
                        "--symbols",
                        "600000.SH",
                        "--end-date",
                        "20260525",
                        "--cache-dir",
                        str(cache_dir),
                        "--out-path",
                        str(out_path),
                        "--refresh",
                    ]
                )
            generated_at = json.loads(out_path.read_text(encoding="utf-8"))["generated_at"]

        self.assertEqual(rc, 0)
        self.assertIn("daily:600000.SH", fake.calls)
        self.assertNotEqual(generated_at, "stale-cache")

    def test_cli_symbols_override_analysis_input(self) -> None:
        fake = FakeTusharePro()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "out.json"
            with mock.patch.object(materializer, "tushare_pro", return_value=fake):
                rc = main(
                    [
                        "--as-of",
                        "20260522",
                        "--analysis-input",
                        str(self.analysis_input_path),
                        "--symbols",
                        "600000.SH",
                        "--end-date",
                        "20260525",
                        "--cache-dir",
                        str(Path(tmpdir) / "cache"),
                        "--out-path",
                        str(out_path),
                    ]
                )
            payload = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload["symbols"], ["600000.SH"])
        self.assertNotIn("daily:600001.SH", fake.calls)

    def test_materialized_tushare_payload_can_feed_execution_runner(self) -> None:
        payload = build_payload_from_tushare(
            FakeTusharePro(),
            symbols=["600000.SH", "600001.SH"],
            as_of="20260522",
            start_date="20260522",
            end_date="20260525",
            generated_at="2026-05-26T00:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            price_path = Path(tmpdir) / "execution_price_data.json"
            out_dir = Path(tmpdir) / "execution"
            write_payload(payload, price_path)

            rc = execution_runner.main(
                [
                    "--as-of",
                    "20260522",
                    "--input-path",
                    str(self.analysis_input_path),
                    "--price-data",
                    str(price_path),
                    "--portfolio-allocation",
                    str(ROOT / "tests" / "fixtures" / "portfolio_allocation_minimal.json"),
                    "--cash-buffer-state",
                    str(ROOT / "tests" / "fixtures" / "cash_buffer_state_minimal.json"),
                    "--time-stop-days",
                    "1",
                    "--out-dir",
                    str(out_dir),
                ]
            )

            report = json.loads((out_dir / "execution_report.json").read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(report["schema_version"], "1.4.0")
        self.assertEqual(report["metrics"]["trade_count"], 0)
        self.assertFalse(report["ship_gate_evaluation"]["full_size_allowed"])
        self.assertEqual(
            report["data_lineage"]["api_families"]["execution_price"],
            TUSHARE_API_FAMILIES,
        )
        self.assertEqual(report["ship_gate_evaluation"]["status"], "not_evaluable")
        self.assertFalse(report["ship_gate_evaluation"]["full_size_allowed"])


if __name__ == "__main__":
    unittest.main()
