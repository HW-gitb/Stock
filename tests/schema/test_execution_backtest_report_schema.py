from __future__ import annotations

import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/execution_backtest_report.schema.json")


class ExecutionBacktestReportSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "execution_backtest_report")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["required"],
            [
                "schema_name",
                "schema_version",
                "generated_at",
                "preset",
                "mode",
                "settings",
                "inputs",
                "execution_assumptions",
                "data_lineage",
                "outputs",
                "metrics",
                "date_warnings",
                "limitations",
            ],
        )

        settings = schema["$defs"]["settings"]
        self.assertEqual(settings["properties"]["primary_input"]["const"], "analysis_input")
        for removed_key in ("cost_pct", "max_position_pct", "max_positions", "time_stop_days"):
            self.assertNotIn(removed_key, settings["required"])
            self.assertNotIn(removed_key, settings["properties"])

    def test_schema_contract_names_phase5_assumption_blocks(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        assumptions = schema["$defs"]["executionAssumptions"]
        self.assertEqual(
            assumptions["required"],
            [
                "entry_timing",
                "limit_up_unbuyable",
                "price_adjustment",
                "transaction_cost",
                "stop_loss",
                "take_profit",
                "time_stop",
                "position_sizing",
                "portfolio_circuit_breaker",
                "cooldown",
                "event_log",
            ],
        )
        self.assertIn(
            "entry_unbuyable",
            assumptions["properties"]["event_log"]["properties"]["event_codes"]["items"]["enum"],
        )
        self.assertIn(
            "missing_stop",
            assumptions["properties"]["event_log"]["properties"]["event_codes"]["items"]["enum"],
        )

        event_codes = assumptions["properties"]["event_log"]["properties"]["event_codes"]
        self.assertEqual(event_codes["minItems"], 2)
        self.assertEqual(
            [item["contains"]["const"] for item in event_codes["allOf"]],
            ["entry", "exit"],
        )

    def test_lineage_string_lists_are_non_empty(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(schema["$defs"]["stringList"]["minItems"], 1)


if __name__ == "__main__":
    unittest.main()
