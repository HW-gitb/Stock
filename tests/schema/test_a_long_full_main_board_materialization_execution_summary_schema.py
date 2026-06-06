from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


SCHEMA_PATH = Path("schemas/a_long_full_main_board_materialization_execution_summary.schema.json")


class ALongFullMainBoardMaterializationExecutionSummarySchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "a_long_full_main_board_materialization_execution_summary",
        )
        self.assertIn("not alpha evidence", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_scope_locks_down_downstream_execution(self) -> None:
        scope = self._load_schema()["$defs"]["scope"]["properties"]

        self.assertEqual(scope["full_market_or_cross_board_pull_executed"]["const"], False)
        self.assertEqual(scope["data_integrity_audit_executed"]["const"], False)
        self.assertEqual(scope["signal_search_executed"]["const"], False)
        self.assertEqual(scope["alpha_backtest_executed"]["const"], False)
        self.assertEqual(scope["production_use_allowed"]["const"], False)
        self.assertEqual(scope["ship_gate_claim_allowed"]["const"], False)
        self.assertEqual(scope["broker_or_order_automation_allowed"]["const"], False)

    def test_budget_and_boundary_are_const_locked(self) -> None:
        schema = self._load_schema()
        execution = schema["$defs"]["execution"]["properties"]
        boundary = schema["$defs"]["executionBoundary"]["properties"]
        prior = schema["$defs"]["priorIndustryRepairDependency"]["properties"]
        table_rollup = schema["properties"]["table_rollup"]

        self.assertEqual(table_rollup["minItems"], 14)
        self.assertEqual(table_rollup["maxItems"], 14)
        self.assertEqual(execution["planned_total_endpoint_calls"]["const"], 23718)
        self.assertEqual(execution["max_total_endpoint_calls"]["const"], 24000)
        self.assertEqual(execution["base_call_count"]["const"], 9)
        self.assertEqual(execution["calls_per_symbol"]["const"], 7)
        self.assertEqual(boundary["expected_active_count"]["const"], 3200)
        self.assertEqual(boundary["expected_delisted_count"]["const"], 187)
        self.assertEqual(boundary["reviewed_no_industry_exception_count"]["const"], 191)
        self.assertEqual(prior["extra_tushare_calls_in_this_runner_for_sw_repair"]["const"], 0)

    def test_summary_does_not_embed_endpoint_results(self) -> None:
        manifest = self._load_schema()["$defs"]["endpointManifest"]["properties"]

        self.assertEqual(manifest["tracked_summary_embeds_endpoint_results"]["const"], False)


if __name__ == "__main__":
    unittest.main()
