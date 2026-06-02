from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_fmp_price_adjustment_corporate_action_semantics_contract.schema.json")
ARTIFACT_PATH = Path(
    "docs/provider_evidence_p1_us_fmp_price_adjustment_corporate_action_semantics_contract_20260602.json"
)


class ProviderP1FmpPriceAdjustmentCorporateActionSemanticsContractSchemaTest(unittest.TestCase):
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
            "provider_p1_fmp_price_adjustment_corporate_action_semantics_contract",
        )
        self.assertIn("does not call FMP endpoints", schema["description"])
        self.assertIn("reconcile corporate actions", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_return_calculation_datahub_runner_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["contract_status"], "semantics_contract_only_no_access_no_price_mapping")
        for field in [
            "fmp_endpoint_call_allowed",
            "broader_fmp_sample_allowed",
            "data_fetch_allowed",
            "raw_payload_parse_allowed",
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
            "strategy_rule_change_allowed",
            "broker_or_order_automation_allowed",
            "ship_gate_relaxed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_review_basis_and_summary_keep_price_semantics_no_access(self) -> None:
        artifact = self._load_artifact()
        basis = artifact["review_basis"]
        summary = artifact["current_scope_summary"]

        self.assertEqual(basis["basis_type"], "existing_repo_artifacts_no_new_external_review")
        self.assertFalse(basis["fmp_endpoint_calls_performed"])
        self.assertFalse(basis["raw_payload_read_or_parsed"])
        self.assertFalse(basis["price_return_calculation_performed"])
        self.assertFalse(basis["corporate_action_reconciliation_performed"])
        self.assertFalse(basis["field_mapping_implemented"])
        self.assertTrue(basis["uses_existing_reviewed_artifacts_only"])
        self.assertTrue(basis["requires_later_user_approved_fmp_access_packet"])
        self.assertTrue(basis["requires_later_adjustment_corporate_action_validation_review"])
        self.assertEqual(
            summary["eod_shape_evidence"],
            "ohlcv_change_changePercent_vwap_present_in_two_symbol_sample_only",
        )
        self.assertEqual(summary["adjustment_semantics_status"], "contract_only_adjusted_unadjusted_not_validated")
        self.assertEqual(summary["corporate_action_status"], "contract_only_split_dividend_delisting_not_reconciled")
        self.assertEqual(
            summary["return_liquidity_use_status"],
            "blocked_until_adjustment_corporate_action_missing_session_review",
        )

    def test_market_data_semantics_do_not_authorize_return_or_liquidity_use(self) -> None:
        artifact = self._load_artifact()
        families = {item["field_family_id"]: item for item in artifact["market_data_semantics"]}
        required_families = {
            "historical_eod_ohlcv",
            "adjusted_unadjusted_price_mode",
            "split_adjustment_factor",
            "dividend_cash_distribution",
            "delisting_inactive_status",
            "zero_volume_halt_missing_session",
            "liquidity_vwap_turnover",
            "calendar_timezone",
        }

        self.assertEqual(set(families), required_families)
        self.assertEqual(
            families["adjusted_unadjusted_price_mode"]["semantics_status"],
            "blocked_pending_adjustment_validation",
        )
        self.assertEqual(
            families["split_adjustment_factor"]["semantics_status"],
            "blocked_pending_corporate_action_reconciliation",
        )
        self.assertEqual(
            families["delisting_inactive_status"]["semantics_status"],
            "blocked_pending_security_master_coverage_validation",
        )
        self.assertEqual(
            families["zero_volume_halt_missing_session"]["semantics_status"],
            "blocked_pending_calendar_missing_session_policy",
        )
        self.assertEqual(families["liquidity_vwap_turnover"]["semantics_status"], "blocked_pending_liquidity_policy")
        for family_id, family in families.items():
            with self.subTest(family_id=family_id):
                self.assertTrue(family["required_before_return_or_liquidity_use"])
                self.assertFalse(family["authorizes_data_fetch"])
                self.assertFalse(family["authorizes_field_mapping_implementation"])
                self.assertFalse(family["authorizes_datahub_or_runner_consumption"])

    def test_price_lineage_requirements_are_complete_and_block_return_or_liquidity_use(self) -> None:
        artifact = self._load_artifact()
        requirements = {item["requirement_id"]: item for item in artifact["price_lineage_requirements"]}
        required_ids = {
            "provider_symbol_and_identifier",
            "endpoint_mode_and_version",
            "request_parameters",
            "fetch_timestamp",
            "trade_date",
            "market_calendar_session",
            "exchange_timezone_and_close_time",
            "open_high_low_close_volume",
            "price_adjustment_mode",
            "split_factor_or_event_ref",
            "dividend_event_ref",
            "corporate_action_effective_date",
            "delisting_or_inactive_status",
            "zero_volume_halt_policy",
            "missing_session_policy",
            "return_eligibility_rule",
            "liquidity_metric_rule",
            "as_of_eligibility_rule",
        }

        self.assertEqual(set(requirements), required_ids)
        for requirement_id, requirement in requirements.items():
            with self.subTest(requirement_id=requirement_id):
                self.assertEqual(requirement["status"], "required_before_return_liquidity_or_datahub")
                self.assertTrue(requirement["blocks_return_or_liquidity_use"])
                self.assertFalse(requirement["authorizes_data_fetch"])
                self.assertFalse(requirement["authorizes_field_mapping_implementation"])
                self.assertFalse(requirement["authorizes_datahub_or_runner_consumption"])

    def test_no_silent_default_policy_blocks_ambiguous_price_and_corporate_action_use(self) -> None:
        artifact = self._load_artifact()
        policy = artifact["no_silent_default_policy"]

        self.assertEqual(policy["policy_status"], "policy_expectations_only_no_price_mapping")
        self.assertTrue(policy["missing_adjustment_mode_blocks_return_use"])
        self.assertTrue(policy["missing_split_or_dividend_policy_blocks_return_use"])
        self.assertTrue(policy["missing_delisting_or_inactive_policy_blocks_universe_use"])
        self.assertTrue(policy["missing_session_or_zero_volume_policy_blocks_or_flags_use"])
        self.assertTrue(policy["unadjusted_price_cannot_be_silent_default"])
        self.assertFalse(policy["split_or_dividend_backfill_without_event_ref_allowed"])
        self.assertFalse(policy["silent_default_allowed"])
        self.assertFalse(policy["zero_fill_allowed"])
        self.assertFalse(policy["authorizes_data_fetch"])
        self.assertFalse(policy["authorizes_datahub_or_runner_consumption"])

    def test_sources_next_steps_and_limitations_preserve_provider_blockers(self) -> None:
        artifact = self._load_artifact()
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("p1_remaining_blocker_plan_20260602", source_ids)
        self.assertIn("p1_fmp_stable_retry_summary_20260602", source_ids)
        self.assertIn("p1_market_data_candidates_20260528", source_ids)
        self.assertIn("p1_coverage_fallback_incident_candidates_20260528", source_ids)
        self.assertIn("p1_fmp_pit_semantics_contract_20260602", source_ids)
        self.assertIn("Do not run additional FMP endpoints", joined_next)
        self.assertIn("SEC parser field-family mapping contract", joined_next)
        self.assertIn("performs no FMP endpoint calls", joined_limits)
        self.assertIn("does not resolve SR-PROVIDER-001", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["fmp_endpoint_call_allowed"] = True
        invalid["scope"]["return_calculation_allowed"] = True
        invalid["review_basis"]["price_return_calculation_performed"] = True
        invalid["market_data_semantics"][0]["authorizes_data_fetch"] = True
        invalid["price_lineage_requirements"][0]["blocks_return_or_liquidity_use"] = False
        invalid["no_silent_default_policy"]["silent_default_allowed"] = True
        invalid["decision_gates"][0]["authorizes_phase7c"] = True
        invalid["prohibited_actions"]["corporate_action_reconciliation"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
