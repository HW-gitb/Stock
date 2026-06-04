from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


PACKET_SCHEMA_PATH = Path("schemas/a_long_tushare_broader_materialization_packet.schema.json")
PACKET_PATH = Path("docs/a_long_tushare_broader_materialization_packet_20260604.json")
SUMMARY_SCHEMA_PATH = Path("schemas/a_long_tushare_broader_materialization_execution_summary.schema.json")


class ALongTushareBroaderMaterializationPacketSchemaTest(unittest.TestCase):
    def _load_packet_schema(self) -> dict:
        return json.loads(PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_summary_schema(self) -> dict:
        return json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_packet(self) -> dict:
        return json.loads(PACKET_PATH.read_text(encoding="utf-8"))

    def _validate_packet(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_packet_schema()).iter_errors(payload))

    def test_packet_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_packet_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "a_long_tushare_broader_materialization_packet")
        self.assertIn("performs no Tushare call", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_summary_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_summary_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "a_long_tushare_broader_materialization_execution_summary",
        )
        self.assertIn("Raw rows stay under gitignored", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_packet_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate_packet(self._load_packet()), [])

    def test_scope_is_execution_packet_not_execution(self) -> None:
        scope = self._load_packet()["scope"]

        self.assertEqual(scope["packet_status"], "execution_packet_recorded_for_review_not_executed")
        self.assertFalse(scope["provider_calls_executed_by_this_artifact"])
        self.assertFalse(scope["tushare_calls_executed_by_this_artifact"])
        self.assertFalse(scope["data_fetch_executed_by_this_artifact"])
        self.assertTrue(scope["ready_for_later_execution_after_independent_review"])
        self.assertTrue(scope["actual_tushare_calls_require_post_review_execute_command"])
        self.assertTrue(scope["full_period_panel_materialization_allowed_after_gates"])
        for field in [
            "full_universe_materialization_allowed",
            "full_market_materialization_allowed",
            "audit_rerun_allowed_by_this_artifact",
            "signal_search_allowed",
            "alpha_backtest_allowed",
            "datahub_allowed",
            "production_use_allowed",
            "ship_gate_claim_allowed",
            "full_size_manual_use_allowed",
            "broker_or_order_automation_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_boundary_and_budget_are_fixed(self) -> None:
        artifact = self._load_packet()
        boundary = artifact["broader_materialization_boundary"]
        budget = artifact["call_budget"]

        self.assertEqual(boundary["materialization_id"], "a_long_tushare_full_period_panel_2018_2025")
        self.assertEqual(boundary["start_date"], "20180101")
        self.assertEqual(boundary["end_date"], "20251231")
        self.assertEqual(
            boundary["active_symbols"],
            ["000001.SZ", "600519.SH", "300750.SZ", "601318.SH", "600036.SH", "000651.SZ", "002415.SZ", "600276.SH"],
        )
        self.assertEqual(boundary["delisted_symbols"], ["000666.SZ"])
        self.assertEqual(boundary["benchmark_indices"], ["000300.SH", "000852.SH"])
        self.assertTrue(boundary["full_period_panel"])
        self.assertTrue(boundary["not_full_market"])
        self.assertTrue(boundary["not_full_universe"])
        self.assertTrue(boundary["previous_thin_slice_audit_pass_required"])
        self.assertEqual(budget["planned_total_endpoint_calls"], 71)
        self.assertEqual(budget["max_total_endpoint_calls"], 80)
        self.assertEqual(budget["retry_count_allowed"], 0)
        self.assertTrue(budget["abort_if_budget_exceeded"])

    def test_tables_are_bounded_and_do_not_authorize_downstream_use(self) -> None:
        tables = {row["table_id"]: row for row in self._load_packet()["materialization_tables"]}

        self.assertEqual(
            set(tables),
            {
                "trade_calendar",
                "stock_basic_active",
                "stock_basic_delisted",
                "income",
                "balancesheet",
                "cashflow",
                "fina_indicator",
                "industry_classification",
                "industry_membership",
                "daily_price_adj_factor_dividend",
                "benchmark_index_daily",
            },
        )
        self.assertEqual(tables["income"]["planned_calls"], 9)
        self.assertEqual(tables["daily_price_adj_factor_dividend"]["planned_calls"], 27)
        self.assertEqual(tables["benchmark_index_daily"]["planned_calls"], 2)
        for table in tables.values():
            self.assertTrue(table["raw_parse_allowed_for_summary_shape_only"])
            self.assertFalse(table["authorizes_return_calculation"])
            self.assertFalse(table["authorizes_factor_derivation"])
            self.assertFalse(table["authorizes_audit_rerun"])
            self.assertFalse(table["authorizes_signal_search"])

    def test_storage_gates_and_claims_are_locked(self) -> None:
        artifact = self._load_packet()
        storage = artifact["storage_and_checkpoint_boundary"]

        self.assertEqual(storage["raw_output_root"], "data/a_long/raw/tushare/materialization_full_period_panel_20260604/")
        self.assertEqual(
            storage["tracked_summary_path"],
            "docs/a_long_tushare_broader_materialization_execution_summary_20260604.json",
        )
        self.assertTrue(storage["checkpoint_resume_allowed"])
        self.assertTrue(storage["existing_raw_payload_reuse_allowed"])
        self.assertFalse(storage["overwrite_existing_raw_without_resume_allowed"])
        self.assertFalse(storage["raw_retention_authorizes_production_storage"])
        for field, value in artifact["pre_execution_gates"].items():
            self.assertTrue(value, field)
        for field, value in artifact["prohibited_claims"].items():
            self.assertFalse(value, field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_packet())
        invalid["scope"]["tushare_calls_executed_by_this_artifact"] = True
        invalid["scope"]["full_market_materialization_allowed"] = True
        invalid["broader_materialization_boundary"]["active_symbols"].append("000002.SZ")
        invalid["broader_materialization_boundary"]["not_full_market"] = False
        invalid["call_budget"]["planned_total_endpoint_calls"] = 200
        invalid["storage_and_checkpoint_boundary"]["overwrite_existing_raw_without_resume_allowed"] = True
        invalid["materialization_tables"][0]["authorizes_audit_rerun"] = True
        invalid["prohibited_claims"]["a_long_data_ready"] = True

        self.assertNotEqual(self._validate_packet(invalid), [])

    def test_next_steps_keep_audit_and_signal_blocked(self) -> None:
        artifact = self._load_packet()
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("Independent review", joined_next)
        self.assertIn("separate user execute command", joined_next)
        self.assertIn("full-period panel data-integrity audit", joined_next)
        self.assertIn("signal-search preregistration", joined_next)
        self.assertIn("performs no Tushare call", joined_limits)
        self.assertIn("not full-market or full-universe", joined_limits)
        self.assertIn("would not prove data integrity", joined_limits)


if __name__ == "__main__":
    unittest.main()
