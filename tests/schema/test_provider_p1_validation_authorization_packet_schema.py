from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_validation_authorization_packet.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json")


class ProviderP1ValidationAuthorizationPacketSchemaTest(unittest.TestCase):
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
            "provider_p1_validation_authorization_packet",
        )
        self.assertIn("FMP Basic / existing-key", schema["description"])
        self.assertIn("does not itself execute provider calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_authorization_scope_is_recorded_but_not_executed(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]

        self.assertEqual(
            scope["authorization_status"],
            "user_approved_boundary_recorded_for_review_not_executed",
        )
        self.assertFalse(scope["artifact_executes_provider_calls"])
        self.assertTrue(scope["authorizes_future_validation_run_within_scope"])
        self.assertTrue(scope["actual_execution_requires_reviewed_execution_packet"])
        self.assertTrue(scope["fmp_existing_key_use_allowed"])
        self.assertTrue(scope["sec_edgar_public_api_allowed"])
        self.assertTrue(scope["raw_payload_parse_for_validation_allowed"])
        for field in [
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_artifact",
            "ship_gate_relaxed",
            "ship_gate_evidence_allowed",
            "production_ready_claim_allowed",
            "broker_or_order_automation_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_access_sample_storage_and_secret_bounds_are_locked(self) -> None:
        artifact = self._load_artifact()
        access = artifact["access_boundary"]
        sample = artifact["sample_boundary"]
        storage = artifact["storage_and_secret_boundary"]
        roles = {
            role["provider_id"]: role["allowed_in_validation_packet"]
            for role in artifact["provider_roles"]
        }

        self.assertEqual(access["approved_spend_usd"], 0)
        self.assertEqual(access["fmp_account_plan_confirmed_by_user"], "Basic")
        self.assertTrue(access["existing_fmp_key_only"])
        self.assertTrue(access["sec_public_api_allowed"])
        self.assertTrue(access["sec_fair_access_required"])
        for field in [
            "fmp_new_token_request_allowed",
            "fmp_trial_request_allowed",
            "fmp_paid_plan_or_upgrade_allowed",
            "provider_contact_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
            "current_terms_legal_review_completed",
            "production_storage_rights_authorized",
        ]:
            self.assertFalse(access[field], field)

        self.assertEqual(sample["sample_size_range_min"], 5)
        self.assertEqual(sample["sample_size_range_max"], 10)
        self.assertEqual(sample["max_symbols"], 10)
        self.assertEqual(sample["max_total_endpoint_calls"], 60)
        self.assertEqual(sample["retry_count_allowed"], 0)
        self.assertTrue(sample["active_symbols_required"])
        self.assertTrue(sample["inactive_or_delisted_candidates_required_if_source_supports"])
        self.assertFalse(sample["exact_symbol_list_fixed_by_this_artifact"])
        self.assertTrue(sample["exact_symbol_list_required_before_execution"])
        self.assertFalse(sample["full_market_or_broad_universe_allowed"])
        self.assertEqual(
            roles,
            {
                "financial_modeling_prep": True,
                "sec_edgar": True,
                "yfinance": False,
            },
        )
        self.assertEqual(storage["raw_sample_storage_root"], "provider_samples/")
        self.assertTrue(storage["raw_payload_storage_must_be_gitignored"])
        self.assertTrue(storage["tracked_summary_allowed"])
        self.assertTrue(storage["tracked_summary_must_exclude_raw_payloads"])
        self.assertTrue(storage["tracked_summary_must_exclude_request_urls"])
        self.assertFalse(storage["api_key_logging_allowed"])
        self.assertFalse(storage["authorization_header_logging_allowed"])
        self.assertFalse(storage["sec_user_agent_value_logging_allowed"])
        self.assertFalse(storage["secrets_in_repo_allowed"])
        self.assertFalse(storage["raw_retention_authorizes_production_storage"])

    def test_validation_permissions_allow_feasibility_only(self) -> None:
        permissions = self._load_artifact()["validation_permissions"]

        for field in [
            "raw_payload_parse_for_validation_allowed",
            "pit_row_validation_allowed",
            "price_adjustment_validation_allowed",
            "corporate_action_validation_allowed",
            "sec_parser_feasibility_allowed",
            "sec_field_mapping_feasibility_allowed",
            "field_presence_review_allowed",
        ]:
            self.assertTrue(permissions[field], field)
        for field in [
            "fixture_generation_allowed",
            "derivation_implementation_allowed",
            "field_mapping_implementation_allowed",
            "parser_implementation_allowed",
            "return_calculation_allowed",
            "provider_selection_allowed",
            "datahub_or_runner_consumption_allowed",
        ]:
            self.assertFalse(permissions[field], field)

    def test_pre_execution_gates_and_prohibited_claims_stay_closed(self) -> None:
        artifact = self._load_artifact()

        for field, value in artifact["pre_execution_gates"].items():
            self.assertTrue(value, field)
        for field, value in artifact["prohibited_claims"].items():
            self.assertFalse(value, field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["access_boundary"]["fmp_paid_plan_or_upgrade_allowed"] = True
        invalid["access_boundary"]["yfinance_allowed"] = True
        invalid["sample_boundary"]["max_symbols"] = 11
        invalid["sample_boundary"]["max_total_endpoint_calls"] = 61
        invalid["sample_boundary"]["full_market_or_broad_universe_allowed"] = True
        invalid["storage_and_secret_boundary"]["api_key_logging_allowed"] = True
        invalid["validation_permissions"]["fixture_generation_allowed"] = True
        invalid["prohibited_claims"]["provider_selected"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_next_steps_and_limitations_preserve_review_boundary(self) -> None:
        artifact = self._load_artifact()
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("5-10 symbol list", joined_next)
        self.assertIn("inactive / delisted candidate check if FMP Basic or SEC EDGAR can support it", joined_next)
        self.assertIn("raw payloads only to validate PIT row", joined_next)
        self.assertIn("separate explicit approval and reviewed decision", joined_next)
        self.assertIn("performs no provider call", joined_limits)
        self.assertIn("not legal advice", joined_limits)
        self.assertIn("SR-PROVIDER-001 remains open", joined_limits)


if __name__ == "__main__":
    unittest.main()
