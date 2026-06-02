from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_sec_edgar_field_family_mapping_contract.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_sec_edgar_field_family_mapping_contract_20260602.json")


class ProviderP1SecEdgarFieldFamilyMappingContractSchemaTest(unittest.TestCase):
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
            "provider_p1_sec_edgar_field_family_mapping_contract",
        )
        self.assertIn("does not perform SEC API calls", schema["description"])
        self.assertIn("generate fixtures", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_parser_mapping_fixture_datahub_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "field_family_mapping_contract_only_no_access_no_parser")
        for field in [
            "sec_api_call_allowed",
            "raw_payload_parse_allowed",
            "fixture_generation_allowed",
            "parser_implementation_allowed",
            "field_mapping_implementation_allowed",
            "broader_sec_reconstruction_allowed",
            "data_fetch_allowed",
            "fmp_endpoint_call_allowed",
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
            "alpha_validation_claim_allowed",
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
        self.assertFalse(basis["sec_api_calls_performed"])
        self.assertFalse(basis["raw_payload_read_or_parsed"])
        self.assertFalse(basis["fixture_generated"])
        self.assertFalse(basis["parser_implemented"])
        self.assertFalse(basis["field_mapping_implemented"])
        self.assertTrue(basis["uses_existing_reviewed_artifacts_only"])
        self.assertTrue(basis["requires_later_user_approved_sec_access_packet"])
        self.assertTrue(basis["requires_later_parser_implementation_review"])
        self.assertTrue(basis["requires_later_field_mapping_review"])
        self.assertEqual(summary["field_family_mapping_status"], "contract_only_no_taxonomy_mapping_implemented")
        self.assertEqual(summary["fixture_status"], "blocked_pending_minimized_fixture_policy_review")

    def test_audit_field_families_are_complete_and_non_authorizing(self) -> None:
        artifact = self._load_artifact()
        families = {item["field_family_id"]: item for item in artifact["audit_field_family_mappings"]}
        required_families = {
            "company_identity_cik_ticker",
            "filing_metadata_accession",
            "accepted_filed_timestamps",
            "fiscal_period_context",
            "income_statement_audit",
            "balance_sheet_audit",
            "cash_flow_audit",
            "shares_outstanding_audit",
            "taxonomy_units_currency",
            "amendment_restatement_chain",
        }

        self.assertEqual(set(families), required_families)
        self.assertEqual(families["income_statement_audit"]["audit_role"], "in_scope_audit_only")
        self.assertEqual(families["shares_outstanding_audit"]["mapping_status"], "blocked_audit_only_not_production_provider")
        for family_id, family in families.items():
            with self.subTest(family_id=family_id):
                self.assertTrue(family["required_before_audit_mapping_use"])
                self.assertTrue(family["blocks_broader_parser_or_datahub"])
                self.assertFalse(family["authorizes_sec_api_call"])
                self.assertFalse(family["authorizes_raw_payload_parse"])
                self.assertFalse(family["authorizes_fixture_generation"])
                self.assertFalse(family["authorizes_parser_implementation"])
                self.assertFalse(family["authorizes_field_mapping_implementation"])
                self.assertFalse(family["authorizes_datahub_or_runner_consumption"])

    def test_lineage_requirements_are_complete_and_block_broader_parser_or_datahub(self) -> None:
        artifact = self._load_artifact()
        requirements = {item["requirement_id"]: item for item in artifact["parser_lineage_requirements"]}
        required_ids = {
            "cik_ticker_identity",
            "accession_number",
            "submission_ref",
            "form_type",
            "accepted_timestamp",
            "filed_date",
            "report_period_date",
            "fiscal_year_period",
            "amendment_or_restatement_flag",
            "taxonomy_tag",
            "taxonomy_extension",
            "unit_and_currency",
            "period_start_end_dates",
            "context_dimensions",
            "source_endpoint_and_params",
            "as_of_eligibility_rule",
        }

        self.assertEqual(set(requirements), required_ids)
        for requirement_id, requirement in requirements.items():
            with self.subTest(requirement_id=requirement_id):
                self.assertEqual(requirement["status"], "required_before_sec_audit_mapping_or_datahub")
                self.assertTrue(requirement["blocks_broader_parser_or_datahub"])
                self.assertFalse(requirement["authorizes_sec_api_call"])
                self.assertFalse(requirement["authorizes_raw_payload_parse"])
                self.assertFalse(requirement["authorizes_fixture_generation"])
                self.assertFalse(requirement["authorizes_parser_implementation"])
                self.assertFalse(requirement["authorizes_field_mapping_implementation"])
                self.assertFalse(requirement["authorizes_datahub_or_runner_consumption"])

    def test_cross_check_policy_keeps_sec_audit_only_no_silent_default(self) -> None:
        artifact = self._load_artifact()
        policy = artifact["cross_check_policy"]

        self.assertEqual(policy["policy_status"], "audit_expectations_only_no_parser_mapping")
        self.assertFalse(policy["sec_replaces_fmp_production_fundamentals"])
        self.assertFalse(policy["sec_price_source_allowed"])
        self.assertFalse(policy["sec_strict_free_float_authority_allowed"])
        self.assertTrue(policy["anomaly_review_requires_sec_ref"])
        self.assertTrue(policy["missing_sec_mapping_blocks_audit_claim"])
        self.assertTrue(policy["missing_taxonomy_context_blocks_audit_claim"])
        self.assertFalse(policy["silent_default_allowed"])
        self.assertFalse(policy["zero_fill_allowed"])
        self.assertFalse(policy["authorizes_sec_api_call"])
        self.assertFalse(policy["authorizes_parser_implementation"])
        self.assertFalse(policy["authorizes_field_mapping_implementation"])
        self.assertFalse(policy["authorizes_datahub_or_runner_consumption"])

    def test_sources_next_steps_and_limits_preserve_provider_blockers(self) -> None:
        artifact = self._load_artifact()
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("p1_sec_edgar_audit_parser_scope_contract_20260602", source_ids)
        self.assertIn("p1_license_storage_retention_review_20260602", source_ids)
        self.assertIn("p1_remaining_blocker_plan_20260602", source_ids)
        self.assertIn("p1_us_egs_sample_summary_20260602", source_ids)
        self.assertIn("coverage-count access-packet planning", joined_next)
        self.assertIn("generate fixtures", joined_next)
        self.assertIn("performs no SEC API calls", joined_limits)
        self.assertIn("It does not resolve SR-PROVIDER-001", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["sec_api_call_allowed"] = True
        invalid["scope"]["fixture_generation_allowed"] = True
        invalid["scope"]["parser_implementation_allowed"] = True
        invalid["scope"]["field_mapping_implementation_allowed"] = True
        invalid["review_basis"]["sec_api_calls_performed"] = True
        invalid["audit_field_family_mappings"][0]["authorizes_fixture_generation"] = True
        invalid["parser_lineage_requirements"][0]["authorizes_raw_payload_parse"] = True
        invalid["cross_check_policy"]["sec_replaces_fmp_production_fundamentals"] = True
        invalid["decision_gates"][0]["authorizes_phase7c"] = True
        invalid["prohibited_actions"]["sec_api_call"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
