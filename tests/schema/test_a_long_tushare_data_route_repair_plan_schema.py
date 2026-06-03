from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/a_long_tushare_data_route_repair_plan.schema.json")
ARTIFACT_PATH = Path("docs/a_long_tushare_data_route_repair_plan_20260603.json")


class ALongTushareDataRouteRepairPlanSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_artifact(self) -> dict:
        return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._load_schema()).iter_errors(payload))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "a_long_tushare_data_route_repair_plan",
        )
        self.assertIn("forbids data fetch", schema["description"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_plain_result_says_data_is_not_usable_now(self) -> None:
        artifact = self._load_artifact()
        plain = artifact["plain_result"]

        self.assertFalse(plain["data_can_be_used_now"])
        self.assertIn("不能找 alpha", plain["simple_result"])
        self.assertIn("没有抓数据", plain["why"])

    def test_scope_locks_no_fetch_audit_signal_datahub_or_ship_gate(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "route_plan_only_no_fetch_no_audit_no_signal")
        self.assertTrue(scope["route_plan_only"])
        self.assertTrue(scope["existing_tushare_account_candidate_only"])
        for field in [
            "provider_call_allowed_by_this_artifact",
            "tushare_call_allowed_by_this_artifact",
            "data_fetch_allowed_by_this_artifact",
            "audit_rerun_allowed_by_this_artifact",
            "signal_search_allowed",
            "alpha_backtest_allowed",
            "new_data_purchase_allowed",
            "provider_expansion_allowed",
            "datahub_allowed",
            "production_use_allowed",
            "ship_gate_claim_allowed",
            "full_size_manual_use_allowed",
            "broker_or_order_automation_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_required_route_components_are_exact_and_blocking(self) -> None:
        artifact = self._load_artifact()
        components = {item["component_id"]: item for item in artifact["required_route_components"]}

        self.assertEqual(
            set(components),
            {
                "calendar_schedule",
                "pit_universe_survivorship",
                "raw_pit_fundamentals",
                "restatement_revision_lineage",
                "industry_taxonomy_history",
                "total_return_and_benchmark",
                "terminal_delisting_return",
            },
        )
        self.assertIn("Tushare income", components["raw_pit_fundamentals"]["candidate_api_families"])
        self.assertIn("ann_date", components["raw_pit_fundamentals"]["minimum_required_fields"])
        self.assertIn("Tushare dividend", components["total_return_and_benchmark"]["candidate_api_families"])
        self.assertIn("delist_date", components["terminal_delisting_return"]["minimum_required_fields"])
        for component in components.values():
            self.assertTrue(component["blocks_signal_search_if_missing"])
            self.assertTrue(component["no_silent_default_allowed"])
            self.assertEqual(component["status_after_this_artifact"], "route_defined_pending_reviewed_execution")

    def test_route_rejects_a_short_cache_or_akshare_substitution(self) -> None:
        artifact = self._load_artifact()
        decision = artifact["route_decision"]
        policy = artifact["no_silent_default_policy"]

        self.assertFalse(decision["a_short_derived_financial_cache_allowed"])
        self.assertFalse(policy["derived_a_short_cache_substitution_allowed"])
        self.assertFalse(policy["latest_only_fundamental_substitution_allowed"])
        self.assertFalse(policy["drop_delisted_holding_allowed"])
        self.assertFalse(policy["close_to_close_benchmark_fallback_allowed"])
        self.assertFalse(policy["current_active_list_as_history_allowed"])
        self.assertFalse(policy["akshare_substitution_allowed_without_review"])

    def test_storage_plan_keeps_raw_rows_ignored_and_tracked_summary_clean(self) -> None:
        artifact = self._load_artifact()
        storage = artifact["storage_plan"]
        gitignore = Path(".gitignore").read_text(encoding="utf-8")

        self.assertEqual(storage["raw_storage_root"], "data/a_long/raw/tushare/")
        self.assertTrue(storage["raw_storage_gitignored_required"])
        self.assertFalse(storage["tracked_summary_may_contain_raw_rows"])
        self.assertFalse(storage["tracked_summary_may_contain_secret"])
        self.assertIn("data/a_long/raw/", gitignore)
        self.assertIn("api_family", storage["lineage_fields_required"])
        self.assertEqual(storage["overwrite_policy"], "append_or_versioned_snapshot_only_no_silent_overwrite")

    def test_next_packet_only_allows_field_presence_validation(self) -> None:
        artifact = self._load_artifact()
        boundary = artifact["next_execution_packet_boundary"]
        policy = artifact["pass_fail_policy"]

        self.assertEqual(boundary["packet_type"], "a_long_tushare_route_validation_packet")
        self.assertTrue(boundary["requires_independent_review_pass"])
        self.assertTrue(boundary["requires_user_execute_after_review"])
        self.assertEqual(boundary["allowed_provider_family"], "existing_tushare_account")
        self.assertEqual(boundary["allowed_goal"], "confirm field_presence_endpoint_behavior_and_storage_shape_only")
        self.assertIn("full 2018-2025 materialization", boundary["forbidden_in_next_packet"])
        self.assertEqual(policy["route_validation_pass_allows"], "create_reviewed_incremental_materialization_packet_only")
        self.assertEqual(policy["audit_pass_allows"], "create_later_reviewed_signal_search_preregistration_limited_to_declared_usable_window")

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["tushare_call_allowed_by_this_artifact"] = True
        invalid["scope"]["signal_search_allowed"] = True
        invalid["plain_result"]["data_can_be_used_now"] = True
        invalid["route_decision"]["a_short_derived_financial_cache_allowed"] = True
        invalid["required_route_components"][0]["blocks_signal_search_if_missing"] = False
        invalid["storage_plan"]["tracked_summary_may_contain_raw_rows"] = True
        invalid["no_silent_default_policy"]["zero_return_fill_allowed"] = True
        invalid["prohibited_actions"]["data_fetch"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
