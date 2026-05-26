from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - environment guard
    Draft7Validator = None  # type: ignore[assignment]

from runners.backtest_execution import ROOT
from runners.materialize_execution_price_data import (
    CSV_API_FAMILIES,
    DEFAULT_OUT_DIR,
    main,
    materialize_payload,
    output_path,
    parse_symbols,
    read_csv_rows,
)


@unittest.skipIf(Draft7Validator is None, "jsonschema not installed")
class MaterializeExecutionPriceDataTest(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        fieldnames = [
            "ts_code",
            "trade_date",
            "open_qfq",
            "high_qfq",
            "low_qfq",
            "close_qfq",
            "pre_close_qfq",
            "adj_factor",
            "up_limit",
            "down_limit",
            "source_flags",
            "is_trade_day",
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def sample_rows(self) -> list[dict[str, str]]:
        return [
            {
                "ts_code": "600000.SH",
                "trade_date": "20260522",
                "open_qfq": "10.10",
                "high_qfq": "10.80",
                "low_qfq": "10.00",
                "close_qfq": "10.50",
                "pre_close_qfq": "10.00",
                "adj_factor": "1.20",
                "up_limit": "11.00",
                "down_limit": "9.00",
                "source_flags": "daily,adj_factor,stk_limit",
            },
            {
                "ts_code": "600001.SH",
                "trade_date": "20260522",
                "open_qfq": "20.10",
                "high_qfq": "20.80",
                "low_qfq": "20.00",
                "close_qfq": "20.50",
                "pre_close_qfq": "20.00",
                "adj_factor": "1.10",
                "up_limit": "22.00",
                "down_limit": "18.00",
                "source_flags": "daily|adj_factor|stk_limit",
            },
        ]

    def test_cli_writes_schema_valid_execution_price_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "prices.csv"
            out_path = Path(tmpdir) / "execution_price_data.json"
            self.write_csv(csv_path, self.sample_rows())

            rc = main(
                [
                    "--as-of",
                    "20260522",
                    "--csv-path",
                    str(csv_path),
                    "--out-path",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
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
            self.assertEqual(payload["date_range"], {"start_date": "20260522", "end_date": "20260522"})
            self.assertEqual(payload["symbols"], ["600000.SH", "600001.SH"])
            self.assertEqual(
                payload["source"]["api_families"],
                CSV_API_FAMILIES,
            )
            self.assertEqual(payload["rows"][1]["source_flags"], ["daily", "adj_factor", "stk_limit"])
            self.assertIn(f"Materialized from CSV: {csv_path}", payload["limitations"])

    def test_parse_symbols_normalizes_duplicates_and_empty_values(self) -> None:
        self.assertEqual(parse_symbols(" 600001.SH,600000.SH,,600001.SH "), ["600000.SH", "600001.SH"])

    def test_parse_symbols_rejects_empty_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "no non-empty symbol"):
            parse_symbols(" , ")

    def test_output_path_defaults_to_execution_price_data_dir(self) -> None:
        self.assertEqual(
            output_path("20260522", None),
            DEFAULT_OUT_DIR / "execution_price_data_20260522.json",
        )

    def test_symbol_filter_uses_requested_symbols_only(self) -> None:
        payload = materialize_payload(
            self.sample_rows(),
            "20260522",
            symbols=["600001.SH"],
            generated_at="2026-05-26T00:00:00+00:00",
        )

        self.assertEqual(payload["symbols"], ["600001.SH"])
        self.assertEqual([row["ts_code"] for row in payload["rows"]], ["600001.SH"])

    def test_selected_symbols_must_have_as_of_rows(self) -> None:
        rows = self.sample_rows()
        rows[1] = dict(rows[1])
        rows[1]["trade_date"] = "20260523"

        with self.assertRaisesRegex(ValueError, "--as-of price row"):
            materialize_payload(rows, "20260522", symbols=["600000.SH", "600001.SH"])

    def test_date_range_must_cover_as_of(self) -> None:
        with self.assertRaisesRegex(ValueError, "date_range must cover --as-of"):
            materialize_payload(
                self.sample_rows(),
                "20260522",
                start_date="20260523",
                end_date="20260524",
            )

    def test_non_trade_day_rows_raise_clear_error(self) -> None:
        rows = self.sample_rows()
        rows[0] = dict(rows[0])
        rows[0]["is_trade_day"] = "false"

        with self.assertRaisesRegex(ValueError, "is_trade_day=false"):
            materialize_payload(rows, "20260522")

    def test_missing_required_csv_columns_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "prices.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["ts_code", "trade_date"])
                writer.writeheader()
                writer.writerow({"ts_code": "600000.SH", "trade_date": "20260522"})

            with self.assertRaisesRegex(ValueError, "CSV missing required columns"):
                read_csv_rows(csv_path)


if __name__ == "__main__":
    unittest.main()
