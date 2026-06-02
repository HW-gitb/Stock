from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_coverage_count_access_packet_plan.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_coverage_count_access_packet_plan_20260602.json")


class ProviderP1CoverageCountAccessPacketPlanSchemaTest(unittest.TestCase):
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
            "provider_p1_coverage_count_access_packet_plan",
        )
        self.assertIn("does not execute coverage counts", schema["description"])
        self.assertIn("call FMP or SEC", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_execution_provider_calls_datahub_runner_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "access_packet_plan_only_no_execution_no_provider_call")
        self.assertTrue(scope["manual_order_only"])
        for field in [
            "coverage_count_execution_allowed",
            "fmp_endpoint_call_allowed",
            "sec_api_call_allowed",
            "data_fetch_allowed",
            "raw_payload_parse_allowed",
            "fixture_generation_allowed",
            "provider_selection_allowed",
            "provider_ranking_allowed",
            "new_token_or_trial_allowed",
            "paid_access_allowed",
            "provider_contact_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
            "provider_status_polling_allowed",
            "fallback_execution_allowed",
            "incident_log_writer_allowed",
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

    def test_review_basis_and_summary_keep_plan_no_access(self) -> None:
        artifact = self._load_artifact()
        basis = artifact["review_basis"]
        summary = artifact["current_scope_summary"]

        self.assertEqual(basis["basis_type"], "existing_repo_artifacts_no_new_external_review")
        self.assertFalse(basis["coverage_count_execution_performed"])
        self.assertFalse(basis["fmp_endpoint_calls_performed"])
        self.assertFalse(basis["sec_api_calls_performed"])
        self.assertFalse(basis["raw_payload_read_or_parsed"])
        self.assertFalse(basis["full_market_fetch_performed"])
        self.assertTrue(basis["uses_existing_reviewed_artifacts_only"])
        self.assertTrue(basis["requires_later_user_approved_coverage_access_packet"])
        self.assertEqual(summary["coverage_status"], "plan_only_no_coverage_counts_executed")
        self.assertEqual(summary["phase7c_effect"], "does_not_authorize_phase7c_or_datahub_consumption")

    def test_coverage_request_profiles_are_complete_and_non_authorizing(self) -> None:
        artifact = self._load_artifact()
        profiles = {item["profile_id"]: item for item in artifact["coverage_request_profiles"]}

        self.assertEqual(
            set(profiles),
            {
                "us_active_symbol_smoke_count",
                "us_fundamentals_endpoint_family_count",
                "us_market_data_endpoint_family_count",
                "us_security_master_or_delisting_gap_count",
            },
        )
        for profile_id, profile in profiles.items():
            with self.subTest(profile_id=profile_id):
                self.assertFalse(profile["allowed_until_approval"])
                self.assertTrue(profile["required_before_execution"])
                self.assertFalse(profile["authorizes_provider_call"])
                self.assertFalse(profile["authorizes_raw_parse"])
                self.assertFalse(profile["authorizes_full_market_download"])
                self.assertFalse(profile["authorizes_datahub_or_runner"])

    def test_access_packet_requirements_block_execution(self) -> None:
        artifact = self._load_artifact()
        requirements = {item["requirement_id"]: item for item in artifact["access_packet_requirements"]}
        required_ids = {
            "symbol_universe_definition",
            "endpoint_family_list",
            "max_symbol_count",
            "max_endpoint_call_count",
            "time_window_and_as_of",
            "rate_limit_and_retry_policy",
            "user_agent_policy_for_sec_if_any",
            "storage_retention_policy",
            "no_secret_summary_policy",
            "raw_payload_gitignore_policy",
            "coverage_metric_definitions",
            "pass_fail_thresholds",
            "fallback_and_incident_behavior",
            "manual_approval_marker",
        }

        self.assertEqual(set(requirements), required_ids)
        for requirement_id, requirement in requirements.items():
            with self.subTest(requirement_id=requirement_id):
                self.assertEqual(requirement["status"], "required_before_coverage_count_execution")
                self.assertTrue(requirement["blocks_execution"])
                self.assertFalse(requirement["authorizes_coverage_count_execution"])
                self.assertFalse(requirement["authorizes_provider_call"])
                self.assertFalse(requirement["authorizes_phase7c"])

    def test_count_metric_plan_and_no_silent_default_block_readiness_claims(self) -> None:
        artifact = self._load_artifact()
        metrics = {item["metric_id"]: item for item in artifact["count_metric_plan"]}
        policy = artifact["no_silent_default_policy"]

        self.assertEqual(
            set(metrics),
            {
                "active_symbol_count",
                "endpoint_success_count",
                "endpoint_error_count",
                "missing_required_field_count",
                "observed_date_field_presence_count",
                "price_ohlcv_presence_count",
                "corporate_action_field_presence_count",
                "delisting_inactive_gap_count",
            },
        )
        for metric_id, metric in metrics.items():
            with self.subTest(metric_id=metric_id):
                self.assertEqual(metric["metric_status"], "planned_not_executed")
                self.assertEqual(
                    metric["missing_or_ambiguous_behavior"],
                    "block_readiness_claim_no_silent_default",
                )
                self.assertFalse(metric["authorizes_coverage_claim"])
                self.assertFalse(metric["authorizes_data_fetch"])
        self.assertTrue(policy["two_symbol_sample_cannot_imply_universe_coverage"])
        self.assertTrue(policy["endpoint_response_shape_cannot_imply_coverage"])
        self.assertTrue(policy["missing_coverage_count_blocks_readiness_claim"])
        self.assertFalse(policy["silent_default_allowed"])
        self.assertFalse(policy["zero_fill_allowed"])
        self.assertFalse(policy["authorizes_coverage_count_execution"])
        self.assertFalse(policy["authorizes_phase7c"])

    def test_sources_next_steps_and_limits_preserve_provider_blockers(self) -> None:
        artifact = self._load_artifact()
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("p1_fmp_stable_retry_summary_20260602", source_ids)
        self.assertIn("p1_remaining_blocker_plan_20260602", source_ids)
        self.assertIn("p1_license_storage_retention_review_20260602", source_ids)
        self.assertIn("p1_sec_edgar_field_family_mapping_contract_20260602", source_ids)
        self.assertIn("provider_evidence_drift_monitor_contract", source_ids)
        self.assertIn("Do not execute coverage counts", joined_next)
        self.assertIn("no-secret", joined_next)
        self.assertIn("performs no web research", joined_limits)
        self.assertIn("cannot imply target-universe coverage", joined_limits)
        self.assertIn("does not resolve SR-PROVIDER-001", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["coverage_count_execution_allowed"] = True
        invalid["scope"]["fmp_endpoint_call_allowed"] = True
        invalid["scope"]["phase7c_authorized_by_this_artifact"] = True
        invalid["review_basis"]["coverage_count_execution_performed"] = True
        invalid["coverage_request_profiles"][0]["authorizes_provider_call"] = True
        invalid["access_packet_requirements"][0]["authorizes_coverage_count_execution"] = True
        invalid["count_metric_plan"][0]["authorizes_coverage_claim"] = True
        invalid["no_silent_default_policy"]["two_symbol_sample_cannot_imply_universe_coverage"] = False
        invalid["decision_gates"][0]["authorizes_phase7c"] = True
        invalid["prohibited_actions"]["coverage_count_execution"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
