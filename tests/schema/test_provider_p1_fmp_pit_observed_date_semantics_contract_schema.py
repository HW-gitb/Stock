from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_fmp_pit_observed_date_semantics_contract.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_fmp_pit_observed_date_semantics_contract_20260602.json")


class ProviderP1FmpPitObservedDateSemanticsContractSchemaTest(unittest.TestCase):
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
            "provider_p1_fmp_pit_observed_date_semantics_contract",
        )
        self.assertIn("does not call FMP endpoints", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_field_mapping_datahub_runner_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "semantics_contract_only_no_access_no_field_mapping")
        for field in [
            "fmp_endpoint_call_allowed",
            "broader_fmp_sample_allowed",
            "data_fetch_allowed",
            "raw_payload_parse_allowed",
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
            "strategy_rule_change_allowed",
            "broker_or_order_automation_allowed",
            "ship_gate_relaxed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_review_basis_and_summary_keep_contract_no_access(self) -> None:
        artifact = self._load_artifact()
        basis = artifact["review_basis"]
        summary = artifact["current_scope_summary"]

        self.assertEqual(basis["basis_type"], "existing_repo_artifacts_no_new_external_review")
        self.assertFalse(basis["fmp_endpoint_calls_performed"])
        self.assertFalse(basis["raw_payload_read_or_parsed"])
        self.assertFalse(basis["field_mapping_implemented"])
        self.assertTrue(basis["uses_existing_reviewed_artifacts_only"])
        self.assertTrue(basis["requires_later_user_approved_fmp_access_packet"])
        self.assertTrue(basis["requires_later_field_level_validation_review"])
        self.assertEqual(
            summary["statement_observed_date_evidence"],
            "filingDate_and_acceptedDate_present_in_two_symbol_sample_only",
        )
        self.assertEqual(summary["pit_semantics_status"], "contract_only_field_level_pit_not_validated")
        self.assertEqual(
            summary["latest_endpoint_status"],
            "blocked_for_historical_pit_until_asof_semantics_review",
        )

    def test_field_family_semantics_do_not_authorize_historical_use(self) -> None:
        artifact = self._load_artifact()
        families = {item["field_family_id"]: item for item in artifact["field_family_semantics"]}
        required_families = {
            "income_statement",
            "balance_sheet_statement",
            "cash_flow_statement",
            "key_metrics",
            "company_profile",
            "historical_eod_price_volume",
        }

        self.assertEqual(set(families), required_families)
        self.assertEqual(families["income_statement"]["historical_pit_status"], "blocked_pending_field_level_validation")
        self.assertEqual(families["company_profile"]["historical_pit_status"], "blocked_not_observed_date_bearing")
        self.assertEqual(
            families["historical_eod_price_volume"]["historical_pit_status"],
            "blocked_pending_adjustment_and_corporate_action_review",
        )
        for family_id, family in families.items():
            with self.subTest(family_id=family_id):
                self.assertTrue(family["required_before_historical_use"])
                self.assertFalse(family["latest_or_current_endpoint_historical_use_allowed"])
                self.assertFalse(family["authorizes_data_fetch"])
                self.assertFalse(family["authorizes_field_mapping_implementation"])
                self.assertFalse(family["authorizes_datahub_or_runner_consumption"])

    def test_lineage_requirements_are_complete_and_block_historical_use(self) -> None:
        artifact = self._load_artifact()
        requirements = {item["requirement_id"]: item for item in artifact["pit_lineage_requirements"]}
        required_ids = {
            "provider_symbol_and_identifier",
            "endpoint_mode_and_version",
            "request_parameters",
            "fetch_timestamp",
            "filing_date",
            "accepted_date",
            "report_period_date",
            "fiscal_year_period",
            "statement_type",
            "revision_or_restatement_behavior",
            "latest_endpoint_exclusion_rule",
            "currency_unit_scaling",
            "duplicate_or_missing_field_policy",
            "sec_cross_check_ref",
            "as_of_eligibility_rule",
        }

        self.assertEqual(set(requirements), required_ids)
        for requirement_id, requirement in requirements.items():
            with self.subTest(requirement_id=requirement_id):
                self.assertEqual(requirement["status"], "required_before_historical_fmp_use_or_datahub")
                self.assertTrue(requirement["blocks_historical_use"])
                self.assertFalse(requirement["authorizes_data_fetch"])
                self.assertFalse(requirement["authorizes_field_mapping_implementation"])
                self.assertFalse(requirement["authorizes_datahub_or_runner_consumption"])

    def test_no_silent_default_policy_blocks_latest_only_and_missing_dates(self) -> None:
        artifact = self._load_artifact()
        policy = artifact["no_silent_default_policy"]

        self.assertEqual(policy["policy_status"], "policy_expectations_only_no_field_mapping")
        self.assertTrue(policy["missing_filing_or_accepted_date_blocks_historical_use"])
        self.assertTrue(policy["latest_only_values_block_historical_use"])
        self.assertTrue(policy["missing_or_ambiguous_revision_blocks_historical_use"])
        self.assertTrue(policy["sec_cross_check_required_for_anomaly_review"])
        self.assertFalse(policy["silent_default_allowed"])
        self.assertFalse(policy["zero_fill_allowed"])
        self.assertFalse(policy["authorizes_data_fetch"])
        self.assertFalse(policy["authorizes_datahub_or_runner_consumption"])

    def test_sources_and_next_steps_preserve_provider_blockers(self) -> None:
        artifact = self._load_artifact()
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("p1_remaining_blocker_plan_20260602", source_ids)
        self.assertIn("p1_fmp_stable_retry_summary_20260602", source_ids)
        self.assertIn("p1_fmp_current_endpoint_mapping_review_20260602", source_ids)
        self.assertIn("p1_fundamentals_observed_date_candidates_20260528", source_ids)
        self.assertIn("p1_license_storage_retention_review_20260602", source_ids)
        self.assertIn("Do not run additional FMP endpoints", joined_next)
        self.assertIn("FMP price-adjustment / corporate-action semantics contract", joined_next)
        self.assertIn("performs no FMP endpoint calls", joined_limits)
        self.assertIn("does not resolve SR-PROVIDER-001", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["fmp_endpoint_call_allowed"] = True
        invalid["scope"]["field_mapping_implementation_allowed"] = True
        invalid["review_basis"]["fmp_endpoint_calls_performed"] = True
        invalid["field_family_semantics"][0]["latest_or_current_endpoint_historical_use_allowed"] = True
        invalid["pit_lineage_requirements"][0]["authorizes_data_fetch"] = True
        invalid["no_silent_default_policy"]["silent_default_allowed"] = True
        invalid["decision_gates"][0]["authorizes_phase7c"] = True
        invalid["prohibited_actions"]["fmp_endpoint_call"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
