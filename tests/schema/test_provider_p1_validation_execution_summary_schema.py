from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_validation_execution_summary.schema.json")
SUMMARY_PATH = Path("docs/provider_evidence_p1_us_validation_execution_summary_20260603.json")


def minimal_valid_summary() -> dict:
    endpoint_results = []
    for symbol in ["AAPL", "MSFT", "JPM", "TWTR", "SIVB"]:
        endpoint_results.append(
            {
                "provider_id": "financial_modeling_prep",
                "endpoint_family": "profile_or_company_metadata",
                "symbol": symbol,
                "status": "ok",
                "http_status": 200,
                "error_type": None,
                "raw_sample_ref": (
                    "provider_samples/us_egs_validation_packet_20260603/"
                    f"raw/financial_modeling_prep/{symbol}/profile_or_company_metadata.json"
                ),
                "raw_sample_ref_gitignored": True,
                "fmp_endpoint_mode": "stable",
                "payload_shape": {
                    "payload_type": "list",
                    "top_level_key_count": None,
                    "row_count": 1,
                },
                "field_presence": {
                    "symbol": True,
                    "companyName": True,
                    "marketCap": True,
                },
                "missing_required_fields": [],
            }
        )
    return {
        "schema_name": "provider_p1_validation_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-03T00:00:00+00:00",
        "execution_packet_ref": "docs/provider_evidence_p1_us_validation_execution_packet_20260603.json",
        "authorization_ref": "docs/provider_evidence_p1_us_validation_authorization_packet_20260603.json",
        "schema_ref": "schemas/provider_p1_validation_execution_summary.schema.json",
        "scope": {
            "phase": "7b-2",
            "purpose": "p1_bounded_provider_validation_execution_summary",
            "validation_status": "completed_with_skips",
            "provider_validation_execution_performed": True,
            "fmp_stable_endpoint_calls_performed": True,
            "sec_edgar_public_api_calls_performed": True,
            "validation_only_raw_payload_parse_performed": True,
            "raw_payload_storage_performed": True,
            "split_or_dividend_endpoint_calls_performed": False,
            "fixture_generation_performed": False,
            "return_calculation_performed": False,
            "corporate_action_reconciliation_performed": False,
            "field_mapping_or_parser_implementation_performed": False,
            "provider_selection_allowed": False,
            "provider_adapter_allowed": False,
            "datahub_table_implementation_allowed": False,
            "production_runner_consumption_allowed": False,
            "phase7c_authorized_by_this_summary": False,
            "manual_order_only": True,
            "ship_gate_evidence_claimed": False,
            "production_ready_claim_allowed": False,
        },
        "pre_execution_checks": {
            "independent_review_pass_confirmed": True,
            "post_review_execute_command_confirmed": True,
            "provider_samples_gitignore_confirmed": True,
            "environment_precheck_passed": True,
            "fmp_api_key_present": True,
            "sec_user_agent_present": True,
            "budget_precheck_passed": True,
            "no_new_token_trial_paid_or_contact_used": True,
            "yfinance_not_used": True,
            "full_market_fetch_not_used": True,
            "sec_fair_access_user_agent_present": True,
        },
        "environment": {
            "fmp_api_key_present": True,
            "fmp_api_key_source": "process",
            "sec_user_agent_present": True,
            "sec_user_agent_source": "process",
            "environment_values_logged": False,
            "secrets_logged": False,
        },
        "storage": {
            "raw_sample_storage_path": "provider_samples/us_egs_validation_packet_20260603/",
            "raw_samples_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
            "sec_user_agent_value_in_summary": False,
        },
        "sample_universe": {
            "symbols": ["AAPL", "MSFT", "JPM", "TWTR", "SIVB"],
            "active_symbols": ["AAPL", "MSFT", "JPM"],
            "inactive_or_delisted_candidate_symbols": ["TWTR", "SIVB"],
            "inactive_or_delisted_candidates_are_best_effort": True,
            "universe_role": "bounded_validation_sample_not_full_market_or_security_master",
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": 41,
            "planned_fmp_endpoint_calls": 30,
            "planned_sec_endpoint_calls": 11,
            "actual_total_endpoint_calls": 5,
            "actual_fmp_endpoint_calls": 5,
            "actual_sec_endpoint_calls": 0,
            "skipped_endpoint_count": 6,
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": True,
        },
        "endpoint_results": endpoint_results,
        "skipped_endpoint_results": [
            {
                "provider_id": "financial_modeling_prep",
                "endpoint_family": "stock_split_candidate",
                "symbol": None,
                "skipped_reason": "blocked_pending_current_template_review",
                "call_count": 0,
                "raw_parse_allowed_for_validation": False,
            },
            {
                "provider_id": "financial_modeling_prep",
                "endpoint_family": "dividend_or_distribution_candidate",
                "symbol": None,
                "skipped_reason": "blocked_pending_current_template_review",
                "call_count": 0,
                "raw_parse_allowed_for_validation": False,
            },
            {
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions",
                "symbol": "TWTR",
                "skipped_reason": "sec_cik_not_found_in_company_tickers_mapping",
                "call_count": 0,
                "raw_parse_allowed_for_validation": False,
            },
            {
                "provider_id": "sec_edgar",
                "endpoint_family": "companyfacts",
                "symbol": "TWTR",
                "skipped_reason": "sec_cik_not_found_in_company_tickers_mapping",
                "call_count": 0,
                "raw_parse_allowed_for_validation": False,
            },
            {
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions",
                "symbol": "SIVB",
                "skipped_reason": "sec_cik_not_found_in_company_tickers_mapping",
                "call_count": 0,
                "raw_parse_allowed_for_validation": False,
            },
            {
                "provider_id": "sec_edgar",
                "endpoint_family": "companyfacts",
                "symbol": "SIVB",
                "skipped_reason": "sec_cik_not_found_in_company_tickers_mapping",
                "call_count": 0,
                "raw_parse_allowed_for_validation": False,
            },
        ],
        "symbol_results": [
            {
                "symbol": symbol,
                "sample_role": "active" if symbol in {"AAPL", "MSFT", "JPM"} else "inactive_or_delisted_candidate_best_effort",
                "fmp": {
                    "endpoints_ok": 1,
                    "endpoints_error": 0,
                    "all_endpoint_families_attempted": False,
                    "statement_observed_date_endpoint_count": 0,
                    "price_ohlcv_fields_present": False,
                    "key_metrics_missing_direct_fields": [],
                },
                "sec_edgar": {
                    "cik_found": symbol not in {"TWTR", "SIVB"},
                    "cik": "0000000001" if symbol not in {"TWTR", "SIVB"} else None,
                    "endpoints_attempted": 0,
                    "endpoints_ok": 0,
                    "endpoints_error": 0,
                    "endpoints_skipped": 0 if symbol not in {"TWTR", "SIVB"} else 2,
                },
                "validation_observations": ["No production readiness is claimed."],
            }
            for symbol in ["AAPL", "MSFT", "JPM", "TWTR", "SIVB"]
        ],
        "aggregate_validation_metrics": {
            "endpoint_success_count": 5,
            "endpoint_error_count": 0,
            "skipped_endpoint_count": 6,
            "fmp_endpoint_success_count": 5,
            "fmp_endpoint_error_count": 0,
            "sec_endpoint_success_count": 0,
            "sec_endpoint_error_count": 0,
            "sec_cik_found_count": 3,
            "sec_cik_missing_count": 2,
            "fmp_statement_observed_date_endpoint_count": 0,
            "fmp_price_ohlcv_presence_count": 0,
            "fmp_key_metrics_missing_direct_field_count": 0,
            "corporate_action_endpoint_call_count": 0,
        },
        "validation_decision": {
            "decision": "bounded_validation_execution_completed_keep_sr_provider_001_open",
            "sr_provider_001_closed": False,
            "provider_selection_allowed": False,
            "phase7c_allowed": False,
            "rationale": "Small validation sample only.",
        },
        "prohibited_claims": {
            "provider_selected": False,
            "provider_ranked": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "new_token_trial_or_provider_contact_used": False,
            "raw_rows_in_tracked_summary": False,
            "request_urls_in_tracked_summary": False,
            "fixture_generated": False,
            "return_calculation_performed": False,
            "corporate_action_reconciliation_performed": False,
            "field_mapping_or_parser_implemented": False,
            "provider_status_polled": False,
            "fallback_executed": False,
            "datahub_or_adapter_implemented": False,
            "production_runner_consumption_authorized": False,
            "phase7c_authorized": False,
            "ship_gate_evidence_claimed": False,
            "alpha_evidence_claimed": False,
            "production_ready_claimed": False,
            "current_terms_cleared": False,
            "production_storage_rights_cleared": False,
            "inactive_delisted_coverage_proven": False,
            "pit_proven_at_scale": False,
            "price_adjustment_proven_at_scale": False,
            "corporate_actions_proven_at_scale": False,
            "sec_parser_proven_at_scale": False,
            "fmp_corporate_action_endpoint_template_proven": False,
        },
        "limitations": [
            "Five-symbol sample only.",
            "No provider selection.",
            "No DataHub.",
            "No ship-gate evidence.",
        ],
        "next_steps": [
            "Review the summary.",
            "Do not broaden scope without approval.",
        ],
    }


class ProviderP1ValidationExecutionSummarySchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

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
        self.assertEqual(schema["properties"]["schema_name"]["const"], "provider_p1_validation_execution_summary")
        self.assertIn("does not select or rank a provider", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_minimal_summary_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(minimal_valid_summary()), [])

    def test_generated_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("validation execution summary has not been generated yet")

        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self._validate(summary), [])
        summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
        for forbidden in ["apikey=", "financialmodelingprep.com/", "sec.gov/"]:
            self.assertNotIn(forbidden, summary_text.lower())
        for forbidden in ["FMP_API_KEY", "SEC_USER_AGENT", "Bearer "]:
            self.assertNotIn(forbidden, summary_text)

    def test_scope_locks_block_implementation_and_ship_gate_claims(self) -> None:
        summary = minimal_valid_summary()
        scope = summary["scope"]

        self.assertFalse(scope["split_or_dividend_endpoint_calls_performed"])
        for field in [
            "fixture_generation_performed",
            "return_calculation_performed",
            "corporate_action_reconciliation_performed",
            "field_mapping_or_parser_implementation_performed",
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_summary",
            "ship_gate_evidence_claimed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(minimal_valid_summary())
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["scope"]["phase7c_authorized_by_this_summary"] = True
        invalid["sample_universe"]["symbols"].append("TSLA")
        invalid["prohibited_claims"]["request_urls_in_tracked_summary"] = True
        invalid["endpoint_call_budget"]["retry_count_used"] = 1

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
