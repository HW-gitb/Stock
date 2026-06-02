from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_sec_edgar_audit_parser_scope_contract.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_sec_edgar_audit_parser_scope_contract_20260602.json")


class ProviderP1SecEdgarAuditParserScopeContractSchemaTest(unittest.TestCase):
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
            "provider_p1_sec_edgar_audit_parser_scope_contract",
        )
        self.assertIn("does not perform SEC API calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_parser_datahub_runner_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "scope_contract_only_no_access_no_parser")
        for field in [
            "sec_api_call_allowed",
            "broader_sec_reconstruction_allowed",
            "data_fetch_allowed",
            "parser_implementation_allowed",
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
        self.assertFalse(basis["sec_api_calls_performed"])
        self.assertFalse(basis["raw_payload_read_or_parsed"])
        self.assertFalse(basis["parser_implemented"])
        self.assertTrue(basis["uses_existing_reviewed_artifacts_only"])
        self.assertTrue(basis["requires_later_user_approved_sec_access_packet"])
        self.assertEqual(summary["audit_role"], "fundamentals_anomaly_review_only")
        self.assertEqual(summary["price_source_status"], "out_of_scope_not_a_price_source")
        self.assertEqual(summary["free_float_status"], "out_of_scope_not_strict_free_float_authority")

    def test_audit_role_boundaries_do_not_authorize_production_use(self) -> None:
        artifact = self._load_artifact()
        boundaries = {item["boundary_id"]: item for item in artifact["audit_role_boundaries"]}
        required_boundaries = {
            "fundamentals_anomaly_audit",
            "fmp_cross_check_support",
            "price_source",
            "strict_free_float_authority",
            "production_fundamentals_provider",
            "security_master",
            "alpha_validation",
            "datahub_source",
        }

        self.assertEqual(set(boundaries), required_boundaries)
        self.assertEqual(boundaries["fundamentals_anomaly_audit"]["role_status"], "in_scope_audit_only")
        self.assertEqual(boundaries["fmp_cross_check_support"]["role_status"], "in_scope_audit_only")
        self.assertEqual(boundaries["price_source"]["role_status"], "out_of_scope")
        self.assertEqual(boundaries["strict_free_float_authority"]["role_status"], "out_of_scope")
        self.assertEqual(boundaries["alpha_validation"]["role_status"], "out_of_scope")
        for boundary_id, boundary in boundaries.items():
            self.assertFalse(boundary["authorizes_data_fetch"], boundary_id)
            self.assertFalse(boundary["authorizes_production_use"], boundary_id)
            self.assertFalse(boundary["authorizes_datahub_or_runner_consumption"], boundary_id)

    def test_lineage_requirements_are_complete_and_block_broader_reconstruction(self) -> None:
        artifact = self._load_artifact()
        requirements = {item["requirement_id"]: item for item in artifact["parser_lineage_requirements"]}
        required_ids = {
            "cik_ticker_identity_link",
            "accession_number",
            "accepted_timestamp",
            "filed_date",
            "form_type",
            "fiscal_year_period",
            "amendment_and_restatement_chain",
            "taxonomy_tag_and_extension",
            "unit_and_currency",
            "period_start_end",
            "fact_context_and_dimensions",
            "source_endpoint_and_request_params",
            "as_of_eligibility_rule",
        }

        self.assertEqual(set(requirements), required_ids)
        for requirement_id, requirement in requirements.items():
            self.assertEqual(requirement["status"], "required_before_broader_sec_parser_or_datahub")
            self.assertTrue(requirement["blocks_broader_reconstruction"], requirement_id)
            self.assertFalse(requirement["authorizes_data_fetch"], requirement_id)
            self.assertFalse(requirement["authorizes_parser_implementation"], requirement_id)
            self.assertFalse(requirement["authorizes_datahub_or_runner_consumption"], requirement_id)

    def test_fair_access_and_artifact_policy_remain_expectations_only(self) -> None:
        artifact = self._load_artifact()
        fair_access = artifact["fair_access_policy"]
        artifact_policy = artifact["artifact_policy"]

        self.assertEqual(fair_access["policy_status"], "policy_expectations_only_no_sec_calls")
        self.assertFalse(fair_access["sec_api_calls_authorized"])
        self.assertFalse(fair_access["bulk_reconstruction_authorized"])
        self.assertTrue(fair_access["reviewed_access_packet_required"])
        self.assertTrue(fair_access["rate_limit_policy_required"])
        self.assertTrue(fair_access["incident_logging_required"])
        self.assertEqual(
            artifact_policy["raw_payload_policy"],
            "gitignored_sample_only_until_later_parser_artifact_contract",
        )
        self.assertEqual(artifact_policy["tracked_summary_policy"], "no_secret_no_raw_rows_summary_only")
        self.assertFalse(artifact_policy["production_storage_authorized"])
        self.assertFalse(artifact_policy["datahub_storage_authorized"])
        self.assertFalse(artifact_policy["tracked_raw_rows_authorized"])

    def test_sources_and_next_steps_preserve_provider_blockers(self) -> None:
        artifact = self._load_artifact()
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("p1_remaining_blocker_plan_20260602", source_ids)
        self.assertIn("p1_license_storage_retention_review_20260602", source_ids)
        self.assertIn("p1_us_egs_sample_summary_20260602", source_ids)
        self.assertIn("p1_public_sources_snapshot_20260528", source_ids)
        self.assertIn("broader reconstruction blocked", joined_next)
        self.assertIn("fundamentals anomaly audit support only", joined_next)
        self.assertIn("performs no SEC API calls", joined_limits)
        self.assertIn("does not resolve SR-PROVIDER-001", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["sec_api_call_allowed"] = True
        invalid["scope"]["parser_implementation_allowed"] = True
        invalid["review_basis"]["sec_api_calls_performed"] = True
        invalid["audit_role_boundaries"][2]["authorizes_production_use"] = True
        invalid["parser_lineage_requirements"][0]["authorizes_data_fetch"] = True
        invalid["fair_access_policy"]["sec_api_calls_authorized"] = True
        invalid["artifact_policy"]["datahub_storage_authorized"] = True
        invalid["decision_gates"][0]["authorizes_phase7c"] = True
        invalid["prohibited_actions"]["sec_api_call"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
