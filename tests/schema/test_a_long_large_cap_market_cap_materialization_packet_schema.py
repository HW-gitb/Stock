from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


PACKET_SCHEMA_PATH = Path("schemas/a_long_large_cap_market_cap_materialization_packet.schema.json")
PACKET_PATH = Path("docs/a_long_large_cap_market_cap_materialization_packet_20260607.json")
SUMMARY_SCHEMA_PATH = Path("schemas/a_long_large_cap_market_cap_materialization_execution_summary.schema.json")


class ALongLargeCapMarketCapMaterializationPacketSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_packet(self) -> dict:
        return self._load_json(PACKET_PATH)

    def _validate_packet(self, payload: dict) -> list:
        schema = self._load_json(PACKET_SCHEMA_PATH)
        Draft7Validator.check_schema(schema)
        return list(Draft7Validator(schema).iter_errors(payload))

    def test_packet_and_summary_schemas_are_valid(self) -> None:
        packet_schema = self._load_json(PACKET_SCHEMA_PATH)
        summary_schema = self._load_json(SUMMARY_SCHEMA_PATH)
        packet = self._load_packet()

        Draft7Validator.check_schema(packet_schema)
        Draft7Validator.check_schema(summary_schema)
        self.assertEqual(list(Draft7Validator(packet_schema).iter_errors(packet)), [])

    def test_scope_allows_later_materialization_only_after_gates(self) -> None:
        scope = self._load_packet()["scope"]

        self.assertTrue(scope["research_only"])
        self.assertTrue(scope["ready_for_later_execution_after_independent_review"])
        self.assertTrue(scope["actual_tushare_calls_require_post_review_execute_command"])
        self.assertTrue(scope["network_access_required_for_later_execution"])
        self.assertTrue(scope["market_cap_materialization_allowed_after_gates"])
        self.assertTrue(scope["manual_order_only"])
        for field_name in [
            "provider_calls_executed_by_this_artifact",
            "tushare_calls_executed_by_this_artifact",
            "data_fetch_executed_by_this_artifact",
            "raw_payloads_read_by_this_artifact",
            "audit_rerun_allowed_by_this_artifact",
            "signal_search_allowed",
            "alpha_backtest_allowed",
            "datahub_allowed",
            "production_use_allowed",
            "ship_gate_claim_allowed",
            "full_size_manual_use_allowed",
            "broker_or_order_automation_allowed",
        ]:
            with self.subTest(field_name=field_name):
                self.assertFalse(scope[field_name])

    def test_boundary_freezes_circ_mv_and_96_monthly_asofs(self) -> None:
        boundary = self._load_packet()["materialization_boundary"]

        self.assertEqual(boundary["selected_market_cap_field"], "circ_mv")
        self.assertEqual(boundary["fields"], "ts_code,trade_date,circ_mv")
        self.assertEqual(boundary["monthly_as_of_count"], 96)
        self.assertEqual(len(boundary["monthly_as_of_dates"]), 96)
        self.assertEqual(boundary["monthly_as_of_dates"][0], "20180131")
        self.assertEqual(boundary["monthly_as_of_dates"][-1], "20251231")
        self.assertEqual(len(set(boundary["monthly_as_of_dates"])), 96)
        self.assertEqual(boundary["board_scope"], "main_board_only")
        self.assertTrue(boundary["main_board_filter_required"])
        self.assertEqual(boundary["universe_size_n"], 500)
        self.assertFalse(boundary["universe_size_n_search_allowed"])
        self.assertFalse(boundary["top_500_selection_written_to_tracked_summary"])
        self.assertTrue(boundary["selection_time_namechange_veto_deferred_to_later_audit_signal"])
        self.assertTrue(boundary["not_signal_search"])

    def test_call_generation_and_storage_are_locked(self) -> None:
        packet = self._load_packet()
        rule = packet["call_generation_rule"]
        storage = packet["storage_and_hygiene"]
        budget = packet["call_budget"]

        self.assertEqual(rule["method"], "daily_basic")
        self.assertEqual(rule["call_id_template"], "daily_basic_market_cap_{trade_date}")
        self.assertEqual(rule["fields"], "ts_code,trade_date,circ_mv")
        self.assertEqual(rule["minimum_fields"], ["ts_code", "trade_date", "circ_mv"])
        self.assertEqual(rule["selected_market_cap_field"], "circ_mv")
        self.assertTrue(rule["one_call_per_monthly_as_of_date"])
        self.assertFalse(rule["authorizes_audit_rerun"])
        self.assertFalse(rule["authorizes_signal_search"])
        self.assertEqual(budget["max_total_endpoint_calls"], 96)
        self.assertEqual(budget["planned_total_endpoint_calls"], 96)
        self.assertEqual(budget["retry_count_allowed"], 0)
        self.assertEqual(storage["raw_output_root"], "data/a_long/raw/tushare/large_cap_market_cap_materialization_20260607/")
        self.assertTrue(storage["tracked_summary_must_not_contain_raw_rows"])
        self.assertTrue(storage["tracked_summary_must_not_contain_top500_symbols"])
        self.assertFalse(storage["raw_retention_authorizes_production_storage"])

    def test_gates_and_prohibited_claims_remain_closed(self) -> None:
        packet = self._load_packet()

        self.assertTrue(all(packet["pre_execution_gates"].values()))
        self.assertTrue(all(value is False for value in packet["prohibited_claims"].values()))

    def test_schema_rejects_scope_creep(self) -> None:
        payload = copy.deepcopy(self._load_packet())
        payload["scope"]["signal_search_allowed"] = True
        payload["materialization_boundary"]["selected_market_cap_field"] = "total_mv"
        payload["materialization_boundary"]["universe_size_n"] = 300
        payload["call_generation_rule"]["fields"] = "ts_code,trade_date,total_mv"
        payload["storage_and_hygiene"]["tracked_summary_must_not_contain_top500_symbols"] = False
        payload["prohibited_claims"]["market_cap_materialized"] = True

        errors = self._validate_packet(payload)

        self.assertGreaterEqual(len(errors), 6)


if __name__ == "__main__":
    unittest.main()
