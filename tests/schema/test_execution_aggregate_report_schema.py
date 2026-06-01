from __future__ import annotations

import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/execution_aggregate_report.schema.json")


class ExecutionAggregateReportSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertIn("/1.1.3/", schema["$id"])
        self.assertEqual(schema["properties"]["schema_name"]["const"], "execution_aggregate_report")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.1.3")
        self.assertIn("multi-period aggregation", schema["description"])
        self.assertIn("reviewed forward-live evidence", schema["description"])
        self.assertIn("zero-trade", schema["description"])
        self.assertIn("excludes zero-trade", schema["description"])
        self.assertIn("capacity/concurrency-adjusted", schema["description"])
        self.assertIn("forward_live_evidence.schema.json", schema["description"])
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
                "metrics",
                "ship_gate_evaluation",
                "limitations",
            ],
        )

    def test_schema_keeps_ship_gate_and_manual_boundary(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        ship_gate = schema["$defs"]["shipGateEvaluation"]
        self.assertEqual(ship_gate["properties"]["policy_logic"]["enum"], ["and"])
        self.assertEqual(ship_gate["properties"]["manual_execution_only"]["const"], True)
        self.assertEqual(
            ship_gate["properties"]["failure_mode"]["const"],
            "paper_or_minimal_size_or_risk_filter_only",
        )
        self.assertIn(
            "production-mode",
            ship_gate["properties"]["full_size_allowed"]["description"],
        )
        self.assertIn(
            "capacity/concurrency-adjusted",
            ship_gate["properties"]["full_size_allowed"]["description"],
        )
        metric_results = schema["$defs"]["shipGateMetricResults"]
        self.assertEqual(
            metric_results["required"],
            ["monthly_alpha_t_stat", "sharpe", "max_drawdown", "forward_live_months"],
        )
        self.assertEqual(
            schema["$defs"]["shipGateMetricResult"]["properties"]["passed"]["type"],
            ["boolean", "null"],
        )

    def test_monthly_series_is_report_return_not_alpha(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        settings = schema["$defs"]["settings"]
        self.assertEqual(
            settings["properties"]["monthly_return_method"]["enum"],
            ["mean_report_total_return_by_month"],
        )
        metrics = schema["$defs"]["aggregateMetrics"]
        self.assertIn("monthly_alpha_t_stat", metrics["required"])
        self.assertIn("benchmark_excess_return_source", settings["required"])
        self.assertIn("forward_live_evidence_source", settings["required"])
        self.assertEqual(
            settings["properties"]["forward_live_evidence_source"]["type"],
            ["string", "null"],
        )


if __name__ == "__main__":
    unittest.main()
