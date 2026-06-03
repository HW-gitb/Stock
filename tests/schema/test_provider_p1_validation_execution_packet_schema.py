from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_validation_execution_packet.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_validation_execution_packet_20260603.json")


class ProviderP1ValidationExecutionPacketSchemaTest(unittest.TestCase):
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
            "provider_p1_validation_execution_packet",
        )
        self.assertIn("fixes the five-symbol sample", schema["description"])
        self.assertIn("does not itself execute provider calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_consumes_authorization_but_does_not_execute(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["packet_status"], "execution_packet_recorded_for_review_not_executed")
        self.assertTrue(scope["consumes_authorization_packet"])
        self.assertFalse(scope["provider_calls_executed_by_this_artifact"])
        self.assertFalse(scope["raw_payloads_read_by_this_artifact"])
        self.assertTrue(scope["ready_for_later_execution_after_independent_review"])
        self.assertTrue(scope["actual_provider_calls_require_post_review_execute_command"])
        self.assertTrue(scope["network_access_required_for_later_execution"])
        self.assertTrue(scope["fmp_existing_key_use_allowed"])
        self.assertTrue(scope["sec_edgar_public_api_allowed"])
        self.assertTrue(scope["raw_payload_parse_for_validation_allowed"])
        for field in [
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_artifact",
            "ship_gate_evidence_allowed",
            "production_ready_claim_allowed",
            "broker_or_order_automation_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_sample_universe_is_exact_and_not_full_market(self) -> None:
        universe = self._load_artifact()["sample_universe"]

        self.assertEqual(universe["symbols"], ["AAPL", "MSFT", "JPM", "TWTR", "SIVB"])
        self.assertEqual(universe["active_symbols"], ["AAPL", "MSFT", "JPM"])
        self.assertEqual(universe["inactive_or_delisted_candidate_symbols"], ["TWTR", "SIVB"])
        self.assertEqual(universe["max_symbols"], 5)
        self.assertTrue(universe["inactive_or_delisted_candidates_are_best_effort"])
        self.assertTrue(universe["not_full_market_or_security_master"])
        self.assertTrue(universe["symbol_failures_block_readiness_claim_not_execution_summary"])

    def test_endpoint_budget_and_families_are_bounded(self) -> None:
        artifact = self._load_artifact()
        budget = artifact["endpoint_call_budget"]
        families = {(row["provider_id"], row["endpoint_family"]): row for row in artifact["endpoint_families"]}

        self.assertEqual(budget["max_authorized_by_authorization_packet"], 60)
        self.assertEqual(budget["max_total_endpoint_calls"], 41)
        self.assertEqual(budget["fmp_planned_endpoint_calls"], 30)
        self.assertEqual(budget["fmp_blocked_candidate_endpoint_calls"], 0)
        self.assertEqual(budget["sec_endpoint_calls"], 11)
        self.assertEqual(budget["retry_count_allowed"], 0)
        self.assertTrue(budget["abort_if_budget_exceeded"])
        self.assertEqual(len(families), 11)

        expected_fmp = [
            "profile_or_company_metadata",
            "income_statement",
            "balance_sheet_statement",
            "cash_flow_statement",
            "financial_ratios_or_key_metrics",
            "historical_eod_price_volume",
        ]
        for endpoint_family in expected_fmp:
            row = families[("financial_modeling_prep", endpoint_family)]
            self.assertEqual(row["call_count"], 5)
            self.assertEqual(row["endpoint_mapping_status"], "stable_template_reviewed_in_prior_mapping")
            self.assertTrue(row["raw_parse_allowed_for_validation"])
            self.assertFalse(row["authorizes_datahub_or_runner"])

        for endpoint_family in ["stock_split_candidate", "dividend_or_distribution_candidate"]:
            row = families[("financial_modeling_prep", endpoint_family)]
            self.assertEqual(row["call_count"], 0)
            self.assertEqual(row["endpoint_mapping_status"], "blocked_pending_current_template_review")
            self.assertFalse(row["raw_parse_allowed_for_validation"])
            self.assertIn("blocked unless", row["notes"])

        self.assertEqual(families[("sec_edgar", "company_tickers_mapping")]["call_count"], 1)
        self.assertEqual(families[("sec_edgar", "company_submissions")]["call_count"], 5)
        self.assertEqual(families[("sec_edgar", "companyfacts")]["call_count"], 5)

    def test_validation_tasks_allow_feasibility_only(self) -> None:
        tasks = {row["task_id"]: row for row in self._load_artifact()["validation_tasks"]}

        self.assertEqual(
            set(tasks),
            {
                "fmp_pit_row_observed_date_validation",
                "fmp_key_metrics_field_presence_validation",
                "fmp_price_adjustment_field_presence_validation",
                "fmp_corporate_action_endpoint_gap_validation",
                "sec_company_identity_mapping_validation",
                "sec_submissions_parser_feasibility_validation",
                "sec_companyfacts_field_family_feasibility_validation",
                "inactive_delisted_candidate_probe",
            },
        )
        for task_id, task in tasks.items():
            self.assertFalse(task["implementation_allowed"], task_id)
            self.assertFalse(task["readiness_or_scale_claim_allowed"], task_id)
        self.assertFalse(tasks["fmp_corporate_action_endpoint_gap_validation"]["raw_parse_allowed_for_validation"])
        self.assertTrue(tasks["sec_companyfacts_field_family_feasibility_validation"]["raw_parse_allowed_for_validation"])

    def test_environment_storage_gates_and_claims_are_locked(self) -> None:
        artifact = self._load_artifact()

        for field, value in artifact["environment_precheck"].items():
            if field in [
                "new_token_trial_paid_or_provider_contact_allowed",
                "yfinance_allowed",
                "full_market_fetch_allowed",
            ]:
                self.assertFalse(value, field)
            else:
                self.assertTrue(value, field)

        storage = artifact["storage_and_secret_boundary"]
        self.assertEqual(storage["raw_sample_storage_path"], "provider_samples/us_egs_validation_packet_20260603/")
        self.assertEqual(
            storage["tracked_summary_path"],
            "docs/provider_evidence_p1_us_validation_execution_summary_20260603.json",
        )
        self.assertTrue(storage["raw_sample_storage_must_be_gitignored"])
        self.assertTrue(storage["tracked_summary_must_exclude_raw_payloads"])
        self.assertTrue(storage["tracked_summary_must_exclude_request_urls"])
        for field in [
            "api_key_logging_allowed",
            "authorization_header_logging_allowed",
            "sec_user_agent_value_logging_allowed",
            "secrets_in_repo_allowed",
            "raw_retention_authorizes_production_storage",
        ]:
            self.assertFalse(storage[field], field)

        for field, value in artifact["pre_execution_gates"].items():
            self.assertTrue(value, field)
        for field, value in artifact["prohibited_claims"].items():
            self.assertFalse(value, field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_calls_executed_by_this_artifact"] = True
        invalid["sample_universe"]["symbols"].append("NVDA")
        invalid["endpoint_call_budget"]["max_total_endpoint_calls"] = 61
        invalid["environment_precheck"]["yfinance_allowed"] = True
        invalid["storage_and_secret_boundary"]["api_key_logging_allowed"] = True
        invalid["endpoint_families"][0]["authorizes_return_calculation"] = True
        invalid["endpoint_families"][0]["authorizes_datahub_or_runner"] = True
        invalid["validation_tasks"][0]["implementation_allowed"] = True
        invalid["prohibited_claims"]["provider_selected"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_next_steps_keep_corporate_action_and_sr_provider_blocked(self) -> None:
        artifact = self._load_artifact()
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("Independent review must verify this packet", joined_next)
        self.assertIn("30 planned FMP stable calls", joined_next)
        self.assertIn("11 planned SEC public calls", joined_next)
        self.assertIn("split / dividend endpoint template", joined_next)
        self.assertIn("SR-PROVIDER-001 open", joined_next)
        self.assertIn("performs no provider call", joined_limits)
        self.assertIn("zero-call", joined_limits)
        self.assertIn("separate explicit approval and reviewed decision", joined_limits)


if __name__ == "__main__":
    unittest.main()
