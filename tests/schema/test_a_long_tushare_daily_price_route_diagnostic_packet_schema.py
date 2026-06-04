from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


PACKET_SCHEMA_PATH = Path("schemas/a_long_tushare_daily_price_route_diagnostic_packet.schema.json")
PACKET_PATH = Path("docs/a_long_tushare_daily_price_route_diagnostic_packet_20260604.json")
SUMMARY_SCHEMA_PATH = Path("schemas/a_long_tushare_daily_price_route_diagnostic_execution_summary.schema.json")


class ALongTushareDailyPriceRouteDiagnosticPacketSchemaTest(unittest.TestCase):
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
        self.assertEqual(schema["properties"]["schema_name"]["const"], "a_long_tushare_daily_price_route_diagnostic_packet")
        self.assertIn("two reviewed A-long Tushare daily probes", schema["description"])
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
            "a_long_tushare_daily_price_route_diagnostic_execution_summary",
        )
        self.assertIn("two-call", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_packet_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate_packet(self._load_packet()), [])

    def test_scope_is_packet_not_execution(self) -> None:
        scope = self._load_packet()["scope"]

        self.assertEqual(scope["packet_status"], "execution_packet_recorded_for_review_not_executed")
        self.assertFalse(scope["provider_calls_executed_by_this_artifact"])
        self.assertFalse(scope["tushare_calls_executed_by_this_artifact"])
        self.assertFalse(scope["data_fetch_executed_by_this_artifact"])
        self.assertTrue(scope["ready_for_later_execution_after_independent_review"])
        self.assertTrue(scope["actual_tushare_calls_require_post_review_execute_command"])
        self.assertTrue(scope["daily_price_route_diagnostic_allowed_after_gates"])
        for field in [
            "daily_price_route_repair_allowed_by_this_artifact",
            "broader_materialization_rerun_allowed_by_this_artifact",
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

    def test_boundary_calls_and_budget_are_fixed(self) -> None:
        artifact = self._load_packet()
        boundary = artifact["diagnostic_boundary"]
        calls = artifact["diagnostic_calls"]
        budget = artifact["call_budget"]

        self.assertEqual(
            boundary["diagnostic_id"],
            "a_long_daily_isolated_window_probe_000001_2018_2025_plus_2022_control",
        )
        self.assertEqual(boundary["fixed_symbol"], "000001.SZ")
        self.assertEqual(boundary["eight_year_window_start_date"], "20180101")
        self.assertEqual(boundary["eight_year_window_end_date"], "20251231")
        self.assertEqual(boundary["control_window_start_date"], "20220101")
        self.assertEqual(boundary["control_window_end_date"], "20221231")
        self.assertTrue(boundary["not_full_market"])
        self.assertTrue(boundary["not_full_universe"])
        self.assertTrue(boundary["not_broader_panel_rerun"])

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["call_id"], "daily_000001_SZ_2018_2025_isolated_probe")
        self.assertEqual(calls[0]["table_id"], "daily_price_eight_year_isolated_probe")
        self.assertEqual(calls[0]["kwargs"]["start_date"], "20180101")
        self.assertEqual(calls[0]["kwargs"]["end_date"], "20251231")
        self.assertEqual(calls[1]["call_id"], "daily_000001_SZ_2022_control_probe")
        self.assertEqual(calls[1]["table_id"], "daily_price_one_year_control_probe")
        self.assertEqual(calls[1]["kwargs"]["start_date"], "20220101")
        self.assertEqual(calls[1]["kwargs"]["end_date"], "20221231")
        for call in calls:
            self.assertEqual(call["method"], "daily")
            self.assertEqual(call["kwargs"]["fields"], "ts_code,trade_date,open,close,vol,amount")
            self.assertEqual(call["minimum_fields"], ["ts_code", "trade_date", "open", "close"])
            self.assertFalse(call["authorizes_price_route_repair"])
            self.assertFalse(call["authorizes_audit_rerun"])
            self.assertFalse(call["authorizes_signal_search"])
        self.assertEqual(budget["planned_total_endpoint_calls"], 2)
        self.assertEqual(budget["max_total_endpoint_calls"], 2)
        self.assertEqual(budget["retry_count_allowed"], 0)
        self.assertTrue(budget["abort_if_budget_exceeded"])

    def test_storage_gates_and_claims_are_locked(self) -> None:
        artifact = self._load_packet()
        storage = artifact["storage_and_checkpoint_boundary"]

        self.assertEqual(storage["raw_output_root"], "data/a_long/raw/tushare/daily_price_route_diagnostic_20260604/")
        self.assertEqual(
            storage["tracked_summary_path"],
            "docs/a_long_tushare_daily_price_route_diagnostic_execution_summary_20260604.json",
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
        invalid["diagnostic_boundary"]["fixed_symbol"] = "600519.SH"
        invalid["diagnostic_calls"][0]["kwargs"]["end_date"] = "20241231"
        invalid["call_budget"]["planned_total_endpoint_calls"] = 3
        invalid["storage_and_checkpoint_boundary"]["overwrite_existing_raw_without_resume_allowed"] = True
        invalid["prohibited_claims"]["a_long_data_ready"] = True

        self.assertNotEqual(self._validate_packet(invalid), [])

    def test_single_probe_shape_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_packet())
        invalid["diagnostic_call"] = invalid.pop("diagnostic_calls")[1]
        invalid["call_budget"]["planned_total_endpoint_calls"] = 1
        invalid["call_budget"]["max_total_endpoint_calls"] = 1

        self.assertNotEqual(self._validate_packet(invalid), [])

    def test_next_steps_keep_repair_audit_and_signal_blocked(self) -> None:
        artifact = self._load_packet()
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("Independent review", joined_next)
        self.assertIn("separate user execute command", joined_next)
        self.assertIn("2018-2025 isolated retest", joined_next)
        self.assertIn("pacing", joined_next)
        self.assertIn("chunked-daily repair packet", joined_next)
        self.assertIn("Do not run full audit or signal search", joined_next)
        self.assertIn("performs no Tushare call", joined_limits)
        self.assertIn("two fixed daily probes", joined_limits)
        self.assertIn("would not make data complete or alpha-ready", joined_limits)


if __name__ == "__main__":
    unittest.main()
