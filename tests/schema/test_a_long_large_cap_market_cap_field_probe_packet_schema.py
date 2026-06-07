from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


PACKET_SCHEMA_PATH = Path("schemas/a_long_large_cap_market_cap_field_probe_packet.schema.json")
PACKET_PATH = Path("docs/a_long_large_cap_market_cap_field_probe_packet_20260607.json")
SUMMARY_SCHEMA_PATH = Path("schemas/a_long_large_cap_market_cap_field_probe_execution_summary.schema.json")


class ALongLargeCapMarketCapFieldProbePacketSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_packet_schema(self) -> dict:
        return self._load_json(PACKET_SCHEMA_PATH)

    def _load_summary_schema(self) -> dict:
        return self._load_json(SUMMARY_SCHEMA_PATH)

    def _load_packet(self) -> dict:
        return self._load_json(PACKET_PATH)

    def _validate_packet(self, payload: dict) -> list:
        return list(Draft7Validator(self._load_packet_schema()).iter_errors(payload))

    def test_packet_schema_summary_schema_and_artifact_validate(self) -> None:
        packet_schema = self._load_packet_schema()
        summary_schema = self._load_summary_schema()
        packet = self._load_packet()

        Draft7Validator.check_schema(packet_schema)
        Draft7Validator.check_schema(summary_schema)
        self.assertFalse(packet_schema["additionalProperties"])
        self.assertFalse(summary_schema["additionalProperties"])
        self.assertEqual(list(Draft7Validator(packet_schema).iter_errors(packet)), [])

    def test_scope_is_packet_not_execution_or_materialization(self) -> None:
        scope = self._load_packet()["scope"]

        self.assertEqual(scope["packet_status"], "execution_packet_recorded_for_review_not_executed")
        self.assertFalse(scope["provider_calls_executed_by_this_artifact"])
        self.assertFalse(scope["tushare_calls_executed_by_this_artifact"])
        self.assertFalse(scope["data_fetch_executed_by_this_artifact"])
        self.assertTrue(scope["ready_for_later_execution_after_independent_review"])
        self.assertTrue(scope["actual_tushare_calls_require_post_review_execute_command"])
        self.assertTrue(scope["daily_basic_market_cap_field_probe_allowed_after_gates"])
        for field_name in [
            "market_cap_field_freeze_allowed_by_this_artifact",
            "market_cap_materialization_allowed_by_this_artifact",
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
            self.assertFalse(scope[field_name], field_name)

    def test_probe_calls_budget_and_selection_rule_are_fixed(self) -> None:
        artifact = self._load_packet()
        boundary = artifact["probe_boundary"]
        calls = artifact["probe_calls"]
        selection = artifact["selection_rule"]
        budget = artifact["call_budget"]

        self.assertEqual(boundary["method"], "daily_basic")
        self.assertEqual(boundary["trade_dates"], ["20180131", "20211231", "20251231"])
        self.assertEqual(boundary["field_preference_order"], ["circ_mv", "total_mv"])
        self.assertTrue(boundary["not_full_96_month_pull"])
        self.assertTrue(boundary["not_signal_search"])
        self.assertEqual(len(calls), 3)
        self.assertEqual([call["kwargs"]["trade_date"] for call in calls], ["20180131", "20211231", "20251231"])
        for call in calls:
            self.assertEqual(call["method"], "daily_basic")
            self.assertEqual(call["kwargs"]["fields"], "ts_code,trade_date,circ_mv,total_mv")
            self.assertEqual(call["minimum_fields"], ["ts_code", "trade_date", "circ_mv", "total_mv"])
            self.assertFalse(call["authorizes_market_cap_field_freeze"])
            self.assertFalse(call["authorizes_market_cap_materialization"])
            self.assertFalse(call["authorizes_audit_rerun"])
            self.assertFalse(call["authorizes_signal_search"])
        self.assertEqual(selection["field_preference_order"], ["circ_mv", "total_mv"])
        self.assertEqual(selection["minimum_row_count_per_probe"], 1000)
        self.assertEqual(selection["minimum_non_null_ratio_for_selected_field"], 0.95)
        self.assertEqual(selection["minimum_positive_ratio_for_selected_field"], 0.95)
        self.assertTrue(selection["selection_after_execution_requires_independent_review"])
        self.assertTrue(selection["selected_field_freezes_before_materialization_only_after_reviewed_result"])
        self.assertEqual(budget["planned_total_endpoint_calls"], 3)
        self.assertEqual(budget["max_total_endpoint_calls"], 3)
        self.assertEqual(budget["retry_count_allowed"], 0)

    def test_storage_pre_execution_gates_and_claims_are_locked(self) -> None:
        artifact = self._load_packet()
        storage = artifact["storage_and_checkpoint_boundary"]

        self.assertEqual(storage["raw_output_root"], "data/a_long/raw/tushare/large_cap_market_cap_field_probe_20260607/")
        self.assertEqual(
            storage["tracked_summary_path"],
            "docs/a_long_large_cap_market_cap_field_probe_execution_summary_20260607.json",
        )
        self.assertTrue(storage["raw_output_root_must_be_gitignored"])
        self.assertTrue(storage["tracked_summary_must_exclude_raw_rows"])
        self.assertTrue(storage["tracked_summary_must_exclude_request_urls"])
        self.assertTrue(storage["tracked_summary_must_exclude_secret"])
        self.assertTrue(storage["checkpoint_resume_allowed"])
        self.assertFalse(storage["overwrite_existing_raw_without_resume_allowed"])
        for field_name, value in artifact["pre_execution_gates"].items():
            self.assertTrue(value, field_name)
        for field_name, value in artifact["prohibited_claims"].items():
            self.assertFalse(value, field_name)

    def test_scope_creep_is_rejected(self) -> None:
        invalid = copy.deepcopy(self._load_packet())
        invalid["scope"]["tushare_calls_executed_by_this_artifact"] = True
        invalid["scope"]["market_cap_materialization_allowed_by_this_artifact"] = True
        invalid["probe_boundary"]["trade_dates"] = ["20180131", "20211231"]
        invalid["probe_calls"][0]["kwargs"]["fields"] = "ts_code,trade_date,total_mv"
        invalid["selection_rule"]["minimum_row_count_per_probe"] = 1
        invalid["call_budget"]["planned_total_endpoint_calls"] = 4
        invalid["prohibited_claims"]["signal_search_authorized"] = True

        self.assertNotEqual(self._validate_packet(invalid), [])

    def test_next_steps_keep_execution_separate_from_signal_search(self) -> None:
        artifact = self._load_packet()
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("Independent review", joined_next)
        self.assertIn("separate user execute command", joined_next)
        self.assertIn("three fixed daily_basic", joined_next)
        self.assertIn("does not authorize materialization or signal search", joined_next)
        self.assertIn("performs no Tushare call", joined_limits)
        self.assertIn("not market-cap materialization", joined_limits)
        self.assertIn("No signal search", joined_limits)


if __name__ == "__main__":
    unittest.main()
