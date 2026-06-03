from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_fmp_entitlement_corporate_action_no_access_diagnostic_20260603.json")


class ProviderP1FmpEntitlementCorporateActionNoAccessDiagnosticSchemaTest(unittest.TestCase):
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
            "provider_p1_fmp_entitlement_corporate_action_no_access_diagnostic",
        )
        self.assertIn("does not execute provider calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_calls_reprobe_selection_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "diagnostic_only_no_new_provider_call_no_reprobe")
        self.assertTrue(scope["docs_only_review"])
        self.assertTrue(scope["public_docs_web_review_performed"])
        self.assertTrue(scope["existing_gitignored_error_wrapper_read_allowed"])
        for field in [
            "fmp_endpoint_call_allowed",
            "sec_api_call_allowed",
            "new_provider_data_fetch_allowed",
            "sivb_reprobe_allowed",
            "corporate_action_endpoint_call_allowed",
            "raw_payload_rows_parse_allowed",
            "fixture_generation_allowed",
            "return_calculation_allowed",
            "corporate_action_reconciliation_allowed",
            "field_mapping_implementation_allowed",
            "provider_selection_allowed",
            "provider_ranking_allowed",
            "new_token_or_trial_allowed",
            "paid_access_allowed",
            "provider_contact_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_artifact",
            "ship_gate_relaxed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_evidence_basis_preserves_sivb_wrapper_and_twtr_comparison_facts(self) -> None:
        basis = self._load_artifact()["evidence_basis"]

        self.assertEqual(
            basis["basis_type"],
            "official_fmp_docs_plus_tracked_summary_plus_existing_error_wrappers_no_new_call",
        )
        self.assertFalse(basis["fmp_endpoint_calls_performed"])
        self.assertFalse(basis["new_provider_data_fetch_performed"])
        self.assertTrue(basis["existing_gitignored_error_wrappers_read"])
        self.assertFalse(basis["raw_payload_rows_parsed"])
        self.assertFalse(basis["sivb_reprobe_performed"])
        self.assertFalse(basis["corporate_action_endpoint_calls_performed"])
        self.assertFalse(basis["sivb_existing_raw_wrappers_body_text_available"])
        self.assertEqual(basis["sivb_existing_raw_wrappers_non_json_bytes"], 215)
        self.assertTrue(basis["twtr_success_refutes_universal_delisted_block"])
        self.assertTrue(basis["issue_narrowed_to_sivb_or_sivb_endpoint_families"])

    def test_split_and_dividend_templates_are_identified_but_not_authorized(self) -> None:
        mapping = self._load_artifact()["fmp_docs_mapping_review"]
        templates = {item["endpoint_family"]: item for item in mapping["endpoint_templates"]}

        self.assertEqual(
            set(templates),
            {"stock_split_candidate", "dividend_or_distribution_candidate"},
        )
        self.assertEqual(
            templates["stock_split_candidate"]["stable_candidate_template"],
            "https://financialmodelingprep.com/stable/splits?symbol={symbol}",
        )
        self.assertEqual(
            templates["dividend_or_distribution_candidate"]["stable_candidate_template"],
            "https://financialmodelingprep.com/stable/dividends?symbol={symbol}",
        )
        self.assertFalse(mapping["sample_live_validated"])
        self.assertFalse(mapping["endpoint_call_authorized_by_this_artifact"])
        for template in templates.values():
            self.assertTrue(template["template_identified"])
            self.assertFalse(template["sample_live_validated"])
            self.assertEqual(template["planned_call_count_in_this_artifact"], 0)
            self.assertFalse(template["authorizes_endpoint_call"])
            self.assertFalse(template["authorizes_corporate_action_reconciliation"])

    def test_basic_entitlement_review_does_not_claim_endpoint_clearance_or_paid_wall(self) -> None:
        review = self._load_artifact()["basic_entitlement_docs_review"]
        findings = {item["endpoint_family_or_plan_area"]: item for item in review["endpoint_family_entitlement_findings"]}

        self.assertEqual(review["plan_review_status"], "public_docs_review_not_endpoint_level_entitlement_clearance")
        self.assertEqual(review["user_confirmed_account_plan"], "FMP Basic")
        self.assertFalse(review["endpoint_level_basic_entitlement_cleared"])
        self.assertFalse(review["sivb_402_paid_wall_conclusion_allowed"])
        self.assertTrue(review["requires_limited_access_modal_or_reprobe_evidence"])
        self.assertIn("statements_and_key_metrics", findings)
        self.assertIn("historical_eod_price_volume", findings)
        self.assertIn("split_dividend_corporate_actions", findings)
        self.assertIn("inactive_delisted_or_delisted_companies", findings)
        for finding in findings.values():
            self.assertFalse(finding["classification_use_allowed"])

    def test_sivb_402_hypotheses_are_complete_and_unconfirmed(self) -> None:
        classification = self._load_artifact()["sivb_http_402_classification"]
        hypotheses = {item["hypothesis_id"]: item for item in classification["open_hypotheses"]}

        self.assertEqual(classification["classification_status"], "open_hypothesis_set_not_conclusive")
        self.assertEqual(classification["affected_symbol"], "SIVB")
        self.assertEqual(classification["http_status"], 402)
        self.assertEqual(classification["failed_endpoint_count"], 5)
        self.assertEqual(classification["twtr_comparison_endpoint_success_count"], 6)
        self.assertTrue(classification["twtr_success_refutes_universal_delisted_block"])
        self.assertFalse(classification["direct_paid_wall_conclusion_allowed"])
        self.assertFalse(classification["missing_data_default_allowed"])
        self.assertEqual(
            set(hypotheses),
            {
                "basic_endpoint_family_entitlement",
                "symbol_specific_receivership_bankruptcy_lifecycle",
                "historical_or_delisted_data_paid_tier",
                "transient_quota_or_provider_incident",
            },
        )
        for hypothesis in hypotheses.values():
            self.assertEqual(hypothesis["status"], "open_unconfirmed")
            self.assertFalse(hypothesis["current_artifact_conclusion_allowed"])
            self.assertTrue(hypothesis["evidence_needed_to_confirm"])

    def test_runner_capture_and_future_reprobe_shape_remain_no_access(self) -> None:
        artifact = self._load_artifact()
        capture = artifact["runner_error_body_capture_contract"]
        reprobe = artifact["future_reprobe_packet_shape"]
        policy = artifact["no_silent_default_policy"]
        go_no_go = artifact["go_no_go_summary"]

        self.assertEqual(
            capture["existing_behavior_before_this_slice"],
            "existing_sivb_raw_wrappers_record_non_json_response_bytes_only",
        )
        self.assertTrue(capture["gitignored_raw_body_capture_required_for_future_reprobe"])
        self.assertFalse(capture["live_reprobe_performed_by_this_slice"])
        self.assertFalse(capture["tracked_summary_body_text_allowed"])
        self.assertTrue(capture["assert_no_secret_summary_must_remain"])
        self.assertFalse(reprobe["reprobe_authorized_by_this_artifact"])
        self.assertTrue(reprobe["requires_separate_reviewed_execution_packet"])
        self.assertEqual(reprobe["symbols"], ["SIVB"])
        self.assertEqual(reprobe["max_total_endpoint_calls"], 5)
        self.assertEqual(reprobe["retry_count_allowed"], 0)
        self.assertEqual(reprobe["spend_usd"], 0)
        self.assertFalse(reprobe["provider_selection_allowed"])
        self.assertFalse(reprobe["phase7c_allowed"])
        self.assertTrue(policy["fmp_http_402_is_not_missing_data_default"])
        self.assertFalse(policy["paid_wall_conclusion_without_body_or_plan_evidence_allowed"])
        self.assertFalse(policy["drop_failed_inactive_symbols_allowed"])
        self.assertTrue(go_no_go["go_for_docs_mapping_and_runner_capture_hardening"])
        self.assertFalse(go_no_go["go_for_sivb_reprobe"])
        self.assertFalse(go_no_go["go_for_split_dividend_endpoint_call"])
        self.assertFalse(go_no_go["go_for_phase7c"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["fmp_endpoint_call_allowed"] = True
        invalid["scope"]["sivb_reprobe_allowed"] = True
        invalid["fmp_docs_mapping_review"]["endpoint_templates"][0]["sample_live_validated"] = True
        invalid["basic_entitlement_docs_review"]["endpoint_level_basic_entitlement_cleared"] = True
        invalid["sivb_http_402_classification"]["direct_paid_wall_conclusion_allowed"] = True
        invalid["runner_error_body_capture_contract"]["live_reprobe_performed_by_this_slice"] = True
        invalid["future_reprobe_packet_shape"]["reprobe_authorized_by_this_artifact"] = True
        invalid["no_silent_default_policy"]["drop_failed_inactive_symbols_allowed"] = True
        invalid["prohibited_actions"]["provider_selection"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
