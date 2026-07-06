from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/us_short_batch5_massive_alt_cut5_access_budget_source_packet_plan.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_massive_alt_cut5_access_budget_source_packet_plan_20260706.json")


class UsShortBatch5MassiveAltCut5AccessBudgetSourcePacketPlanSchemaTest(unittest.TestCase):
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
            "us_short_batch5_massive_alt_cut5_access_budget_source_packet_plan",
        )
        self.assertIn("Massive alternative", schema["description"])
        self.assertIn("does not execute provider calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_provider_selection_yfinance_datahub_or_ship_gate(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_claims"]

        self.assertEqual(scope["contract_status"], "plan_only_no_access_no_provider_selection")
        self.assertTrue(scope["manual_order_only"])
        for field in [
            "network_access_performed",
            "provider_calls_performed",
            "raw_payload_read_or_parsed",
            "raw_payload_written",
            "source_packet_written",
            "data_context_written",
            "massive_calls_authorized_by_this_artifact",
            "fmp_calls_authorized_by_this_artifact",
            "sec_calls_authorized_by_this_artifact",
            "provider_selection_allowed",
            "provider_ranking_allowed",
            "provider_switch_claimed",
            "yfinance_allowed",
            "full_market_fetch_allowed",
            "provider_status_polling_allowed",
            "provider_contact_allowed",
            "new_token_or_trial_allowed",
            "paid_access_allowed",
            "datahub_allowed",
            "production_storage_allowed",
            "production_runner_consumption_allowed",
            "ship_gate_or_live_normalized_evidence_claimed",
            "broker_or_order_execution_allowed",
            "a_share_crossing_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_official_doc_review_and_source_refs_are_public_docs_only(self) -> None:
        artifact = self._load_artifact()
        doc_review = artifact["official_doc_review"]
        source_ids = {item["source_id"] for item in artifact["source_refs"]}

        self.assertEqual(doc_review["provider"], "Massive")
        self.assertEqual(doc_review["review_status"], "public_docs_review_only_no_access_no_call")
        self.assertEqual(doc_review["official_doc_url"], "https://massive.com/docs/rest/stocks/overview")
        self.assertTrue(doc_review["public_web_docs_reviewed"])
        self.assertFalse(doc_review["provider_call_performed"])
        self.assertFalse(doc_review["account_entitlement_verified"])
        self.assertFalse(doc_review["analyst_endpoint_found_in_reviewed_overview"])

        self.assertIn("massive_stocks_overview_public_docs_20260706", source_ids)
        self.assertIn("massive_splits_public_docs_20260706", source_ids)
        self.assertIn("massive_dividends_public_docs_20260706", source_ids)
        self.assertIn("massive_news_public_docs_20260706", source_ids)
        self.assertIn("massive_financial_ratios_public_docs_20260706", source_ids)
        self.assertIn("us_short_batch5_full_candidate_pass2_preflight_summary_20260706", source_ids)
        self.assertIn("sr_provider_001", source_ids)

    def test_replacement_map_separates_replacements_retained_sources_and_gap(self) -> None:
        components = {item["component_id"]: item for item in self._load_artifact()["provider_substitution_map"]}

        self.assertEqual(
            set(components),
            {
                "ticker_reference_company_metadata",
                "market_price_ohlcv_volume",
                "news_catalyst_source",
                "corporate_action_splits_dividends",
                "financials_ratios_optional",
                "analyst_grades",
                "sec_audit_submissions",
            },
        )
        self.assertEqual(
            components["analyst_grades"]["replacement_status"],
            "unresolved_source_gap_no_massive_equivalent_found",
        )
        self.assertEqual(
            components["sec_audit_submissions"]["replacement_status"],
            "retained_sec_source_not_replaced_by_massive",
        )
        self.assertEqual(
            components["news_catalyst_source"]["replacement_status"],
            "retained_existing_massive_source_requires_access_budget_review",
        )
        for component_id, component in components.items():
            with self.subTest(component_id=component_id):
                self.assertFalse(component["replacement_allowed_by_this_artifact"])
                self.assertFalse(component["authorizes_provider_call"])
                self.assertFalse(component["authorizes_source_packet_write"])
                self.assertFalse(component["call_budget_cleared"])

    def test_call_budget_model_does_not_clear_live_run_or_hide_analyst_gap(self) -> None:
        artifact = self._load_artifact()
        budget = artifact["call_budget_model"]
        scenarios = {item["scenario_id"]: item for item in budget["scenarios"]}

        self.assertEqual(budget["candidate_eligible_count"], 2404)
        self.assertEqual(budget["current_cut5_forecast_total_calls"], 12021)
        self.assertEqual(budget["known_fmp_basic_daily_call_limit"], 250)
        self.assertFalse(budget["total_call_budget_cleared"])
        self.assertFalse(budget["massive_account_call_limit_verified"])
        self.assertFalse(budget["output_coverage_complete"])
        self.assertEqual(
            budget["analyst_gap_disposition"],
            "unresolved_source_gap_no_massive_equivalent_found",
        )
        self.assertEqual(
            set(scenarios),
            {
                "current_fmp_cut5_forecast",
                "massive_like_for_like_without_analyst",
                "massive_plus_ticker_overview_metadata",
            },
        )
        self.assertEqual(scenarios["current_fmp_cut5_forecast"]["planned_total_calls"], 12021)
        self.assertEqual(scenarios["massive_like_for_like_without_analyst"]["planned_total_calls"], 9617)
        self.assertEqual(scenarios["massive_plus_ticker_overview_metadata"]["planned_total_calls"], 12021)
        for scenario_id, scenario in scenarios.items():
            with self.subTest(scenario_id=scenario_id):
                self.assertFalse(scenario["call_budget_cleared"])
                self.assertFalse(scenario["output_coverage_complete"])
                self.assertFalse(scenario["authorizes_provider_call"])

    def test_source_packet_plan_blocks_execution_until_named_gates_close(self) -> None:
        artifact = self._load_artifact()
        plan = artifact["source_packet_plan"]
        gap_ids = {item["gap_id"] for item in artifact["unresolved_source_gaps"]}
        gate_ids = {item["gate_id"] for item in plan["pre_execution_gates"]}

        self.assertFalse(plan["ready_for_reviewed_live_execution"])
        self.assertFalse(plan["source_packet_schema_change_authorized"])
        self.assertFalse(plan["source_packet_runner_change_authorized"])
        self.assertFalse(plan["provider_calls_authorized"])
        self.assertEqual(plan["missing_component_behavior"], "fail_closed_do_not_silent_neutral_fill")

        self.assertIn("analyst_grades_no_massive_equivalent_found_in_reviewed_overview", gap_ids)
        self.assertIn("massive_account_entitlement_and_call_budget_unverified", gap_ids)
        self.assertIn("massive_license_storage_retention_unreviewed_for_cut5", gap_ids)
        self.assertIn("corporate_action_reconciliation_semantics_unproven", gap_ids)
        self.assertIn("source_packet_schema_and_runner_not_updated_for_massive_replacement", gap_ids)

        self.assertIn("massive_access_entitlement_budget_review", gate_ids)
        self.assertIn("analyst_grade_gap_disposition", gate_ids)
        self.assertIn("license_storage_retention_review", gate_ids)
        self.assertIn("corporate_action_semantics_and_reconciliation_review", gate_ids)
        self.assertIn("reviewed_massive_source_packet_schema_runner_change", gate_ids)
        self.assertIn("explicit_user_live_execution_approval", gate_ids)
        for gap in artifact["unresolved_source_gaps"]:
            with self.subTest(gap_id=gap["gap_id"]):
                self.assertTrue(gap["blocks_live_run"])
                self.assertFalse(gap["no_silent_default_allowed"])
                self.assertFalse(gap["authorizes_provider_call"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_calls_performed"] = True
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["scope"]["yfinance_allowed"] = True
        invalid["scope"]["datahub_allowed"] = True
        invalid["official_doc_review"]["provider_call_performed"] = True
        invalid["call_budget_model"]["total_call_budget_cleared"] = True
        invalid["call_budget_model"]["analyst_gap_disposition"] = "resolved_by_massive"
        invalid["provider_substitution_map"][5]["replacement_status"] = "candidate_replacement_requires_access_budget_review"
        invalid["provider_substitution_map"][5]["replacement_allowed_by_this_artifact"] = True
        invalid["source_packet_plan"]["ready_for_reviewed_live_execution"] = True
        invalid["source_packet_plan"]["provider_calls_authorized"] = True
        invalid["unresolved_source_gaps"][0]["blocks_live_run"] = False
        invalid["unresolved_source_gaps"][0]["no_silent_default_allowed"] = True
        invalid["prohibited_claims"]["provider_selected"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
