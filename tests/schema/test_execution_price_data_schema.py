from __future__ import annotations

import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/execution_price_data.schema.json")


class ExecutionPriceDataSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "execution_price_data")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["preset"]["enum"], ["a_short"])
        self.assertEqual(schema["properties"]["data_provider"]["enum"], ["tushare"])

    def test_source_requires_minimum_execution_api_families(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        api_families = schema["$defs"]["source"]["properties"]["api_families"]
        self.assertEqual(api_families["minItems"], 4)
        self.assertTrue(api_families["uniqueItems"])
        self.assertNotIn("enum", api_families["items"])
        self.assertEqual(api_families["items"]["minLength"], 1)
        self.assertEqual(
            [item["contains"]["const"] for item in api_families["allOf"]],
            ["daily", "adj_factor", "stk_limit", "trade_cal"],
        )

    def test_price_rows_define_qfq_ohlc_and_limit_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        price_row = schema["$defs"]["priceRow"]
        for required_key in (
            "ts_code",
            "trade_date",
            "is_trade_day",
            "open_qfq",
            "high_qfq",
            "low_qfq",
            "close_qfq",
            "pre_close_qfq",
            "adj_factor",
            "up_limit",
            "down_limit",
            "source_flags",
        ):
            self.assertIn(required_key, price_row["required"])
            self.assertIn(required_key, price_row["properties"])

        self.assertEqual(
            price_row["properties"]["up_limit"]["$ref"],
            "#/$defs/positiveNumberNullable",
        )
        self.assertEqual(
            price_row["properties"]["down_limit"]["$ref"],
            "#/$defs/positiveNumberNullable",
        )
        self.assertTrue(price_row["properties"]["is_trade_day"]["const"])

    def test_minimal_valid_instance_passes_schema(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        instance = {
            "schema_name": "execution_price_data",
            "schema_version": "1.0.0",
            "generated_at": "2026-05-26T00:00:00+08:00",
            "preset": "a_short",
            "data_provider": "tushare",
            "source": {
                "api_families": ["daily", "adj_factor", "stk_limit", "trade_cal"],
                "adjustment_mode": "qfq_via_adj_factor",
                "price_basis": "daily_eod",
                "calendar_source": "tushare.trade_cal",
                "pit_policy": "trade_date_eod",
            },
            "date_range": {
                "start_date": "20260501",
                "end_date": "20260526",
            },
            "symbols": ["000001.SZ"],
            "rows": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260525",
                    "is_trade_day": True,
                    "open_qfq": 10.0,
                    "high_qfq": 10.8,
                    "low_qfq": 9.9,
                    "close_qfq": 10.5,
                    "pre_close_qfq": 9.8,
                    "adj_factor": 102.5,
                    "up_limit": 10.78,
                    "down_limit": 8.82,
                    "source_flags": ["daily", "adj_factor", "stk_limit"],
                }
            ],
            "limitations": ["Phase 5 contract only; provider fetch is not implemented yet."],
        }

        Draft7Validator(schema).validate(instance)

    def test_empty_rows_and_non_trade_day_rows_are_rejected(self) -> None:
        try:
            from jsonschema import Draft7Validator
            from jsonschema.exceptions import ValidationError
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        instance = {
            "schema_name": "execution_price_data",
            "schema_version": "1.0.0",
            "generated_at": "2026-05-26T00:00:00+08:00",
            "preset": "a_short",
            "data_provider": "tushare",
            "source": {
                "api_families": ["daily", "adj_factor", "stk_limit", "trade_cal"],
                "adjustment_mode": "qfq_via_adj_factor",
                "price_basis": "daily_eod",
                "calendar_source": "tushare.trade_cal",
                "pit_policy": "trade_date_eod",
            },
            "date_range": {
                "start_date": "20260501",
                "end_date": "20260526",
            },
            "symbols": ["000001.SZ"],
            "rows": [],
            "limitations": ["Phase 5 contract only; provider fetch is not implemented yet."],
        }

        validator = Draft7Validator(schema)
        with self.assertRaises(ValidationError):
            validator.validate(instance)

        instance["rows"] = [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260524",
                "is_trade_day": False,
                "open_qfq": 10.0,
                "high_qfq": 10.8,
                "low_qfq": 9.9,
                "close_qfq": 10.5,
                "pre_close_qfq": 9.8,
                "adj_factor": 102.5,
                "up_limit": None,
                "down_limit": None,
                "source_flags": ["trade_cal"],
            }
        ]
        with self.assertRaises(ValidationError):
            validator.validate(instance)


if __name__ == "__main__":
    unittest.main()
