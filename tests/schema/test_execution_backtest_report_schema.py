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
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.2.0")
        self.assertIn("contract remains unfrozen", schema["description"])
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
                "capital_context",
                "execution_assumptions",
                "data_lineage",
                "outputs",
                "metrics",
                "ship_gate_evaluation",
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
        self.assertIn(
            "missing_price_data",
            assumptions["properties"]["event_log"]["properties"]["event_codes"]["items"]["enum"],
        )
        self.assertIn(
            "cash_constrained",
            assumptions["properties"]["event_log"]["properties"]["event_codes"]["items"]["enum"],
        )

        event_codes = assumptions["properties"]["event_log"]["properties"]["event_codes"]
        self.assertEqual(event_codes["minItems"], 2)
        self.assertIn("grow-only", event_codes["description"])
        self.assertEqual(
            [item["contains"]["const"] for item in event_codes["allOf"]],
            ["entry", "exit"],
        )

        position_sizing = assumptions["properties"]["position_sizing"]
        self.assertEqual(position_sizing["properties"]["capital_basis"]["enum"], ["bucket_capital"])
        self.assertIn("bucket_ceiling_pct", position_sizing["required"])

    def test_lineage_string_lists_are_non_empty(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(schema["$defs"]["stringList"]["minItems"], 1)

    def test_capital_context_is_required_and_bucket_aware(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        capital_context = schema["$defs"]["capitalContext"]
        self.assertIn("capital_context", schema["required"])
        self.assertIn("bucket_capital", capital_context["required"])
        self.assertEqual(capital_context["properties"]["capital_basis"]["enum"], ["bucket_capital"])
        self.assertEqual(
            capital_context["properties"]["cross_market_cash_fungible"]["const"],
            False,
        )
        self.assertEqual(capital_context["properties"]["manual_execution_only"]["const"], True)
        self.assertIn("failure_mode", schema["$defs"]["shipGateSnapshot"]["required"])

    def test_ship_gate_evaluation_is_required_and_metric_complete(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertIn("ship_gate_evaluation", schema["required"])
        ship_gate = schema["$defs"]["shipGateEvaluation"]
        self.assertEqual(ship_gate["properties"]["policy_logic"]["enum"], ["and"])
        self.assertEqual(
            ship_gate["properties"]["failure_mode"]["const"],
            "paper_or_minimal_size_or_risk_filter_only",
        )
        self.assertEqual(ship_gate["properties"]["manual_execution_only"]["const"], True)

        metric_results = schema["$defs"]["shipGateMetricResults"]
        self.assertEqual(
            metric_results["required"],
            ["monthly_alpha_t_stat", "sharpe", "max_drawdown", "forward_live_months"],
        )
        metric_result = schema["$defs"]["shipGateMetricResult"]
        self.assertEqual(metric_result["properties"]["passed"]["type"], ["boolean", "null"])


if __name__ == "__main__":
    unittest.main()
