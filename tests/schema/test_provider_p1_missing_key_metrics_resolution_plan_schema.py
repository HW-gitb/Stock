from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_missing_key_metrics_resolution_plan.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_missing_key_metrics_resolution_plan_20260602.json")


class ProviderP1MissingKeyMetricsResolutionPlanSchemaTest(unittest.TestCase):
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
            "provider_p1_missing_key_metrics_resolution_plan",
        )
        self.assertIn("does not call FMP or SEC", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_raw_parse_derivation_datahub_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "resolution_plan_only_no_access_no_raw_parse_no_derivation")
        for field in [
            "fmp_endpoint_call_allowed",
            "sec_api_call_allowed",
            "broader_provider_sample_allowed",
            "data_fetch_allowed",
            "raw_payload_parse_allowed",
            "fixture_generation_allowed",
            "field_derivation_implementation_allowed",
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

    def test_review_basis_uses_summary_only_and_records_exact_missing_count(self) -> None:
        artifact = self._load_artifact()
        basis = artifact["review_basis"]

        self.assertEqual(basis["basis_type"], "tracked_summary_only_no_raw_payload_parse_no_new_access")
        self.assertEqual(
            basis["coverage_summary_ref"],
            "docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json",
        )
        self.assertFalse(basis["fmp_endpoint_calls_performed"])
        self.assertFalse(basis["sec_api_calls_performed"])
        self.assertFalse(basis["raw_payload_read_or_parsed"])
        self.assertFalse(basis["field_derivation_implemented"])
        self.assertFalse(basis["field_mapping_implemented"])
        self.assertTrue(basis["uses_tracked_no_secret_summary_only"])
        self.assertEqual(basis["missing_field_count_total"], 15)
        self.assertEqual(basis["missing_symbol_count"], 5)
        self.assertTrue(basis["requires_later_user_approved_field_presence_review"])
        self.assertTrue(basis["requires_later_derivation_lineage_review"])

    def test_missing_fields_are_complete_and_blocked(self) -> None:
        artifact = self._load_artifact()
        observations = {item["field_id"]: item for item in artifact["missing_field_observations"]}
        expected = {"peRatio", "revenuePerShare", "netIncomePerShare"}

        self.assertEqual(set(observations), expected)
        for field_id, observation in observations.items():
            with self.subTest(field_id=field_id):
                self.assertEqual(observation["endpoint_family"], "financial_ratios_or_key_metrics")
                self.assertEqual(observation["missing_symbol_count"], 5)
                self.assertEqual(observation["current_status"], "missing_in_fmp_stable_key_metrics_sample")
                self.assertEqual(
                    observation["candidate_resolution_class"],
                    "potentially_derivable_pending_field_presence_and_lineage_review",
                )
                self.assertFalse(observation["production_use_allowed"])
                self.assertFalse(observation["silent_default_allowed"])
                self.assertTrue(observation["required_before_resolution"])

    def test_candidate_derivations_do_not_authorize_implementation(self) -> None:
        artifact = self._load_artifact()
        paths = {item["target_field_id"]: item for item in artifact["candidate_derivation_paths"]}

        self.assertEqual(set(paths), {"peRatio", "revenuePerShare", "netIncomePerShare"})
        self.assertIn("price", paths["peRatio"]["candidate_formula_family"])
        self.assertIn("revenue", paths["revenuePerShare"]["candidate_formula_family"])
        self.assertIn("net_income", paths["netIncomePerShare"]["candidate_formula_family"])
        for target_id, path in paths.items():
            with self.subTest(target_id=target_id):
                self.assertEqual(path["current_status"], "candidate_only_blocked_pending_review")
                self.assertTrue(path["required_input_families"])
                self.assertTrue(path["pit_and_lineage_requirements"])
                self.assertFalse(path["authorizes_raw_parse"])
                self.assertFalse(path["authorizes_derivation_implementation"])
                self.assertFalse(path["authorizes_datahub_or_runner_consumption"])

    def test_gates_and_no_silent_default_keep_provider_blockers_open(self) -> None:
        artifact = self._load_artifact()
        gates = {item["gate_id"]: item for item in artifact["resolution_decision_gates"]}
        policy = artifact["no_silent_default_policy"]

        self.assertIn("field_presence_review_packet", gates)
        self.assertIn("derivation_formula_lineage_spec", gates)
        self.assertIn("phase7c_consumption_gate", gates)
        for gate_id, gate in gates.items():
            with self.subTest(gate_id=gate_id):
                self.assertTrue(gate["blocks_implementation"])
                self.assertFalse(gate["authorizes_data_fetch"])
                self.assertFalse(gate["authorizes_raw_payload_parse"])
                self.assertFalse(gate["authorizes_derivation_implementation"])
                self.assertFalse(gate["authorizes_field_mapping_implementation"])
                self.assertFalse(gate["authorizes_datahub_or_runner_consumption"])
                self.assertFalse(gate["authorizes_phase7c"])

        self.assertTrue(policy["missing_vendor_ratio_blocks_vendor_ratio_claim"])
        self.assertFalse(policy["derived_metric_allowed_without_review"])
        self.assertFalse(policy["null_fill_allowed"])
        self.assertFalse(policy["zero_fill_allowed"])
        self.assertFalse(policy["latest_price_substitution_allowed"])
        self.assertFalse(policy["current_profile_share_substitution_allowed"])
        self.assertFalse(policy["production_default_allowed"])

    def test_go_no_go_summary_allows_planning_only(self) -> None:
        artifact = self._load_artifact()
        summary = artifact["go_no_go_summary"]
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertTrue(summary["go_for_controlled_resolution_planning"])
        self.assertFalse(summary["go_for_raw_payload_parse"])
        self.assertFalse(summary["go_for_derivation_implementation"])
        self.assertFalse(summary["go_for_provider_selection"])
        self.assertFalse(summary["go_for_datahub_or_runner_consumption"])
        self.assertIn("separate explicit approval", joined_next)
        self.assertIn("performs no FMP endpoint calls", joined_limits)
        self.assertIn("does not resolve SR-PROVIDER-001", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["raw_payload_parse_allowed"] = True
        invalid["scope"]["field_derivation_implementation_allowed"] = True
        invalid["review_basis"]["raw_payload_read_or_parsed"] = True
        invalid["missing_field_observations"][0]["silent_default_allowed"] = True
        invalid["candidate_derivation_paths"][0]["authorizes_derivation_implementation"] = True
        invalid["resolution_decision_gates"][0]["authorizes_phase7c"] = True
        invalid["no_silent_default_policy"]["zero_fill_allowed"] = True
        invalid["prohibited_actions"]["provider_selection"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
