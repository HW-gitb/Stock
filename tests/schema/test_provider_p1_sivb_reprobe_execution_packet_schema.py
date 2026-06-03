from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_sivb_reprobe_execution_packet.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_sivb_reprobe_execution_packet_20260603.json")


class ProviderP1SivbReprobeExecutionPacketSchemaTest(unittest.TestCase):
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
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "provider_p1_sivb_reprobe_execution_packet",
        )
        self.assertIn("SIVB-only FMP HTTP 402 re-probe", schema["description"])
        self.assertIn("does not execute provider calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_is_packet_only_and_does_not_execute(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["packet_status"], "execution_packet_contract_recorded_for_review_not_executed")
        self.assertFalse(scope["provider_calls_executed_by_this_artifact"])
        self.assertFalse(scope["raw_payloads_read_by_this_artifact"])
        self.assertFalse(scope["runner_implemented_by_this_artifact"])
        self.assertTrue(scope["ready_for_later_execution_after_independent_review"])
        self.assertTrue(scope["actual_provider_calls_require_post_review_execute_command"])
        self.assertTrue(scope["network_access_required_for_later_execution"])
        self.assertTrue(scope["fmp_existing_key_use_allowed"])
        self.assertEqual(scope["spend_usd"], 0)
        for field in [
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_artifact",
            "ship_gate_evidence_allowed",
            "production_ready_claim_allowed",
            "broker_or_order_automation_allowed",
            "new_token_trial_paid_or_provider_contact_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_sample_universe_is_sivb_only(self) -> None:
        universe = self._load_artifact()["sample_universe"]

        self.assertEqual(universe["symbols"], ["SIVB"])
        self.assertEqual(universe["max_symbols"], 1)
        self.assertEqual(universe["active_symbols"], [])
        self.assertEqual(universe["inactive_or_delisted_candidate_symbols"], ["SIVB"])
        self.assertTrue(universe["not_full_market_or_security_master"])
        self.assertFalse(universe["security_master_implementation_allowed"])

    def test_budget_and_endpoint_families_are_exactly_five_failed_fmp_families(self) -> None:
        artifact = self._load_artifact()
        budget = artifact["endpoint_call_budget"]
        families = {row["endpoint_family"]: row for row in artifact["endpoint_families"]}

        self.assertEqual(budget["max_total_endpoint_calls"], 5)
        self.assertEqual(budget["fmp_planned_endpoint_calls"], 5)
        self.assertEqual(budget["sec_endpoint_calls"], 0)
        self.assertEqual(budget["retry_count_allowed"], 0)
        self.assertTrue(budget["abort_if_budget_exceeded"])
        self.assertTrue(budget["budget_precheck_required"])
        self.assertEqual(
            set(families),
            {
                "income_statement",
                "balance_sheet_statement",
                "cash_flow_statement",
                "financial_ratios_or_key_metrics",
                "historical_eod_price_volume",
            },
        )
        for row in families.values():
            self.assertEqual(row["provider_id"], "financial_modeling_prep")
            self.assertEqual(row["symbol"], "SIVB")
            self.assertEqual(row["call_count"], 1)
            self.assertEqual(row["previous_http_status"], 402)
            self.assertTrue(row["capture_non_json_body_in_raw"])
            self.assertTrue(row["classification_signal_allowed"])
            self.assertFalse(row["tracked_summary_body_text_allowed"])
            self.assertFalse(row["tracked_summary_request_url_allowed"])
            self.assertFalse(row["authorizes_return_calculation"])
            self.assertFalse(row["authorizes_corporate_action_reconciliation"])
            self.assertFalse(row["authorizes_fixture_generation"])
            self.assertFalse(row["authorizes_field_mapping_implementation"])
            self.assertFalse(row["authorizes_provider_selection"])
            self.assertFalse(row["authorizes_datahub_or_runner"])

    def test_environment_storage_and_pre_execution_gates_are_locked(self) -> None:
        artifact = self._load_artifact()

        env = artifact["environment_precheck"]
        self.assertTrue(env["fmp_key_required_before_any_network_call"])
        self.assertTrue(env["fmp_key_must_not_be_logged"])
        self.assertTrue(env["abort_before_network_if_fmp_key_missing"])
        self.assertTrue(env["existing_fmp_key_only"])
        self.assertFalse(env["new_token_trial_paid_or_provider_contact_allowed"])
        self.assertFalse(env["yfinance_allowed"])
        self.assertFalse(env["full_market_fetch_allowed"])

        storage = artifact["storage_and_secret_boundary"]
        self.assertEqual(storage["raw_sample_storage_path"], "provider_samples/us_egs_sivb_reprobe_20260603/")
        self.assertEqual(
            storage["tracked_summary_path"],
            "docs/provider_evidence_p1_us_sivb_reprobe_execution_summary_20260603.json",
        )
        self.assertTrue(storage["raw_sample_storage_must_be_gitignored"])
        self.assertTrue(storage["capture_non_json_body_in_raw"])
        self.assertTrue(storage["tracked_summary_must_exclude_raw_payloads"])
        self.assertTrue(storage["tracked_summary_must_exclude_error_body_text"])
        self.assertTrue(storage["tracked_summary_must_exclude_request_urls"])
        self.assertFalse(storage["api_key_logging_allowed"])
        self.assertFalse(storage["secrets_in_repo_allowed"])
        self.assertTrue(storage["assert_no_secret_summary_must_remain"])

        for field, value in artifact["pre_execution_gates"].items():
            self.assertTrue(value, field)

    def test_classification_strategy_is_signal_only_and_complete(self) -> None:
        strategy = self._load_artifact()["classification_strategy"]
        hypotheses = {row["hypothesis_id"]: row for row in strategy["hypothesis_map"]}

        self.assertTrue(strategy["read_captured_402_body_for_classification"])
        self.assertEqual(strategy["classification_output"], "category_signal_only_no_body_text_no_url")
        self.assertFalse(strategy["tracked_summary_body_text_allowed"])
        self.assertFalse(strategy["tracked_summary_request_url_allowed"])
        self.assertFalse(strategy["direct_paid_wall_conclusion_without_body_or_plan_evidence_allowed"])
        self.assertEqual(
            set(hypotheses),
            {
                "endpoint_entitlement",
                "symbol_lifecycle",
                "historical_or_delisted_paid_tier",
                "transient_quota_or_provider_incident",
            },
        )
        for row in hypotheses.values():
            self.assertFalse(row["body_text_copied_to_summary"])
            self.assertFalse(row["current_artifact_conclusion_allowed"])
            self.assertTrue(row["evidence_required_to_confirm"])

    def test_no_silent_default_and_prohibited_claims_stay_closed(self) -> None:
        artifact = self._load_artifact()
        policy = artifact["no_silent_default_policy"]

        self.assertTrue(policy["fmp_http_402_is_not_missing_data_default"])
        self.assertTrue(policy["twtr_success_is_not_inactive_delisted_coverage_proof"])
        for field in [
            "null_fill_allowed",
            "zero_fill_allowed",
            "drop_failed_symbol_allowed",
            "latest_only_substitution_allowed",
            "production_default_allowed",
        ]:
            self.assertFalse(policy[field], field)
        for field, value in artifact["prohibited_claims"].items():
            self.assertFalse(value, field)

    def test_source_refs_include_required_prior_artifacts(self) -> None:
        refs = {row["artifact_id"]: row for row in self._load_artifact()["source_artifact_refs"]}

        self.assertIn("p1_validation_authorization_packet_20260603", refs)
        self.assertIn("p1_validation_execution_summary_20260603", refs)
        self.assertIn("p1_fmp_entitlement_corporate_action_diagnostic_20260603", refs)
        self.assertIn("sr_provider_001", refs)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_calls_executed_by_this_artifact"] = True
        invalid["scope"]["runner_implemented_by_this_artifact"] = True
        invalid["sample_universe"]["symbols"] = ["SIVB", "AAPL"]
        invalid["sample_universe"]["active_symbols"] = ["AAPL"]
        invalid["endpoint_call_budget"]["max_total_endpoint_calls"] = 6
        invalid["endpoint_call_budget"]["retry_count_allowed"] = 1
        invalid["endpoint_families"][0]["endpoint_family"] = "profile_or_company_metadata"
        invalid["endpoint_families"][0]["tracked_summary_body_text_allowed"] = True
        invalid["storage_and_secret_boundary"]["tracked_summary_must_exclude_request_urls"] = False
        invalid["classification_strategy"]["direct_paid_wall_conclusion_without_body_or_plan_evidence_allowed"] = True
        invalid["prohibited_claims"]["provider_selected"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_next_steps_keep_double_gate_and_sr_provider_open(self) -> None:
        artifact = self._load_artifact()
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("Independent review must verify", joined_next)
        self.assertIn("user later gives an execute command", joined_next)
        self.assertIn("category signal", joined_next)
        self.assertIn("SR-PROVIDER-001 open", joined_next)
        self.assertIn("performs no provider call", joined_limits)
        self.assertIn("implements no runner", joined_limits)
        self.assertIn("does not prove why SIVB returned HTTP 402", joined_limits)
        self.assertIn("Phase 7c", joined_limits)


if __name__ == "__main__":
    unittest.main()
