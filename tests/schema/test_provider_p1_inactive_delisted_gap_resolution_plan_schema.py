from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_inactive_delisted_gap_resolution_plan.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_inactive_delisted_gap_resolution_plan_20260603.json")


class ProviderP1InactiveDelistedGapResolutionPlanSchemaTest(unittest.TestCase):
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
            "provider_p1_inactive_delisted_gap_resolution_plan",
        )
        self.assertIn("does not call FMP or SEC", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_security_master_provider_selection_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "resolution_plan_only_no_access_no_raw_parse_no_security_master")
        for field in [
            "fmp_endpoint_call_allowed",
            "sec_api_call_allowed",
            "broader_provider_sample_allowed",
            "data_fetch_allowed",
            "raw_payload_read_or_parse_allowed",
            "fixture_generation_allowed",
            "security_master_implementation_allowed",
            "field_mapping_implementation_allowed",
            "return_calculation_allowed",
            "corporate_action_reconciliation_allowed",
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

    def test_evidence_basis_uses_validation_summary_only_and_preserves_gap_facts(self) -> None:
        artifact = self._load_artifact()
        basis = artifact["evidence_basis"]

        self.assertEqual(basis["basis_type"], "tracked_validation_summary_only_no_raw_payload_parse_no_new_access")
        self.assertEqual(
            basis["validation_summary_ref"],
            "docs/provider_evidence_p1_us_validation_execution_summary_20260603.json",
        )
        self.assertFalse(basis["fmp_endpoint_calls_performed"])
        self.assertFalse(basis["sec_api_calls_performed"])
        self.assertFalse(basis["raw_payload_read_or_parsed"])
        self.assertFalse(basis["security_master_implemented"])
        self.assertTrue(basis["uses_tracked_no_secret_summary_only"])
        self.assertEqual(set(basis["inactive_or_delisted_candidates_reviewed"]), {"TWTR", "SIVB"})
        self.assertEqual(basis["fmp_success_by_symbol"], {"TWTR": 6, "SIVB": 1})
        self.assertEqual(basis["fmp_error_by_symbol"], {"TWTR": 0, "SIVB": 5})
        self.assertEqual(basis["fmp_http_402_symbols"], ["SIVB"])
        self.assertEqual(set(basis["sec_cik_missing_symbols"]), {"TWTR", "SIVB"})
        self.assertEqual(basis["sec_cik_missing_count"], 2)
        self.assertFalse(basis["inactive_delisted_coverage_proven"])
        self.assertTrue(basis["requires_later_security_master_review"])
        self.assertTrue(basis["requires_later_entitlement_or_alternate_source_review"])

    def test_gap_observations_are_complete_and_blocked(self) -> None:
        artifact = self._load_artifact()
        observations = {item["gap_id"]: item for item in artifact["gap_observations"]}
        expected = {
            "fmp_basic_sivb_endpoint_entitlement_gap",
            "sec_current_company_tickers_not_historical_security_master",
            "fmp_twtr_partial_success_not_universe_coverage",
            "two_symbol_inactive_sample_not_representative_security_master",
            "alternate_source_or_paid_access_decision_gap",
        }

        self.assertEqual(set(observations), expected)
        self.assertIn("HTTP 402", observations["fmp_basic_sivb_endpoint_entitlement_gap"]["evidence_summary"])
        self.assertEqual(
            set(observations["sec_current_company_tickers_not_historical_security_master"]["affected_symbols"]),
            {"TWTR", "SIVB"},
        )
        for gap_id, observation in observations.items():
            with self.subTest(gap_id=gap_id):
                self.assertTrue(observation["blocks_inactive_delisted_coverage_claim"])
                self.assertTrue(observation["blocks_security_master_claim"])
                self.assertFalse(observation["production_use_allowed"])
                self.assertFalse(observation["silent_default_allowed"])
                self.assertTrue(observation["required_resolution"])

    def test_resolution_tracks_do_not_authorize_implementation(self) -> None:
        artifact = self._load_artifact()
        tracks = {item["track_id"]: item for item in artifact["resolution_tracks"]}

        self.assertEqual(
            set(tracks),
            {
                "security_master_source_review",
                "fmp_basic_inactive_delisted_entitlement_review",
                "sec_historical_cik_or_symbol_lookup_review",
                "alternate_provider_or_paid_access_decision",
                "bounded_followup_packet_if_user_approved",
                "phase7c_consumption_gate",
            },
        )
        for track_id, track in tracks.items():
            with self.subTest(track_id=track_id):
                self.assertTrue(track["blocks_implementation"])
                self.assertFalse(track["authorizes_data_fetch"])
                self.assertFalse(track["authorizes_raw_payload_parse"])
                self.assertFalse(track["authorizes_security_master_implementation"])
                self.assertFalse(track["authorizes_field_mapping_implementation"])
                self.assertFalse(track["authorizes_provider_selection"])
                self.assertFalse(track["authorizes_datahub_or_runner_consumption"])
                self.assertFalse(track["authorizes_phase7c"])

    def test_future_packet_requirements_and_no_silent_default_policy(self) -> None:
        artifact = self._load_artifact()
        requirements = artifact["minimum_future_packet_requirements"]
        policy = artifact["no_silent_default_policy"]

        for value in requirements.values():
            self.assertTrue(value)

        self.assertTrue(policy["profile_success_is_not_inactive_delisted_coverage_proof"])
        self.assertTrue(policy["sec_cik_not_found_is_not_absence_of_issuer_proof"])
        self.assertTrue(policy["fmp_http_402_is_not_missing_data_default"])
        self.assertFalse(policy["current_ticker_file_allowed_as_historical_security_master"])
        self.assertFalse(policy["null_fill_allowed"])
        self.assertFalse(policy["zero_fill_allowed"])
        self.assertFalse(policy["drop_failed_inactive_symbols_allowed"])
        self.assertFalse(policy["latest_only_substitution_allowed"])
        self.assertFalse(policy["production_default_allowed"])
        self.assertFalse(policy["authorizes_datahub_or_runner_consumption"])

    def test_go_no_go_summary_allows_planning_only(self) -> None:
        artifact = self._load_artifact()
        summary = artifact["go_no_go_summary"]
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertTrue(summary["go_for_controlled_resolution_planning"])
        self.assertFalse(summary["go_for_raw_payload_parse"])
        self.assertFalse(summary["go_for_new_provider_call"])
        self.assertFalse(summary["go_for_security_master_implementation"])
        self.assertFalse(summary["go_for_provider_selection"])
        self.assertFalse(summary["go_for_datahub_or_runner_consumption"])
        self.assertIn("separate reviewed packet", joined_next)
        self.assertIn("performs no FMP endpoint calls", joined_limits)
        self.assertIn("does not resolve SR-PROVIDER-001", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["fmp_endpoint_call_allowed"] = True
        invalid["scope"]["security_master_implementation_allowed"] = True
        invalid["evidence_basis"]["raw_payload_read_or_parsed"] = True
        invalid["evidence_basis"]["inactive_delisted_coverage_proven"] = True
        invalid["gap_observations"][0]["silent_default_allowed"] = True
        invalid["resolution_tracks"][0]["authorizes_phase7c"] = True
        invalid["no_silent_default_policy"]["drop_failed_inactive_symbols_allowed"] = True
        invalid["prohibited_actions"]["provider_selection"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
