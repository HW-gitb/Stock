from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_coverage_count_execution_summary.schema.json")
SUMMARY_PATH = Path("docs/provider_evidence_p1_us_coverage_count_execution_summary_20260602.json")


def minimal_valid_summary() -> dict:
    endpoint_results = []
    for symbol in ["AAPL", "MSFT", "NVDA", "JPM", "XOM"]:
        endpoint_results.append(
            {
                "provider_id": "financial_modeling_prep",
                "endpoint_family": "profile_or_company_metadata",
                "symbol": symbol,
                "status": "ok",
                "http_status": 200,
                "error_type": None,
                "raw_sample_ref": (
                    "provider_samples/us_egs_coverage_count_20260602/"
                    f"fmp_stable/raw/financial_modeling_prep/{symbol}/profile_or_company_metadata.json"
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
        "schema_name": "provider_p1_coverage_count_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-02T00:00:00+00:00",
        "approval_ref": "docs/provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json",
        "schema_ref": "schemas/provider_p1_coverage_count_execution_summary.schema.json",
        "scope": {
            "phase": "7b-2",
            "purpose": "fmp_stable_coverage_count_execution_summary",
            "validation_status": "completed",
            "coverage_count_execution_performed": True,
            "fmp_stable_endpoint_calls_performed": True,
            "count_only_response_inspection_performed": True,
            "raw_payload_storage_performed": True,
            "sec_api_calls_performed": False,
            "yfinance_used": False,
            "full_market_download_performed": False,
            "provider_status_polling_performed": False,
            "fallback_execution_performed": False,
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
            "ship_gate_relaxed": False,
            "production_ready_claim_allowed": False,
        },
        "environment": {
            "fmp_api_key_present": True,
            "fmp_api_key_source": "process",
            "secrets_logged": False,
        },
        "storage": {
            "raw_sample_storage_path": "provider_samples/us_egs_coverage_count_20260602/fmp_stable/",
            "raw_samples_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
        },
        "sample_universe": {
            "symbols": ["AAPL", "MSFT", "NVDA", "JPM", "XOM"],
            "max_symbols": 5,
            "universe_role": "bounded_active_symbol_smoke_not_full_market",
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": 30,
            "actual_total_endpoint_calls": 5,
            "within_budget": True,
        },
        "endpoint_results": endpoint_results,
        "symbol_results": [
            {
                "symbol": symbol,
                "fmp": {
                    "endpoints_ok": 1,
                    "endpoints_error": 0,
                    "all_endpoint_families_successful": False,
                    "missing_required_field_count": 0,
                    "statement_observed_date_endpoint_count": 0,
                    "price_ohlcv_fields_present": False,
                },
                "validation_observations": ["No production readiness is claimed."],
            }
            for symbol in ["AAPL", "MSFT", "NVDA", "JPM", "XOM"]
        ],
        "aggregate_count_metrics": {
            "endpoint_success_count": 5,
            "endpoint_error_count": 0,
            "symbol_all_endpoint_success_count": 0,
            "missing_required_field_count": 0,
            "statement_observed_date_endpoint_count": 0,
            "price_ohlcv_presence_count": 0,
            "endpoint_family_row_counts": [
                {"endpoint_family": "profile_or_company_metadata", "min_row_count": 1, "max_row_count": 1},
                {"endpoint_family": "income_statement", "min_row_count": None, "max_row_count": None},
                {"endpoint_family": "balance_sheet_statement", "min_row_count": None, "max_row_count": None},
                {"endpoint_family": "cash_flow_statement", "min_row_count": None, "max_row_count": None},
                {"endpoint_family": "financial_ratios_or_key_metrics", "min_row_count": None, "max_row_count": None},
                {"endpoint_family": "historical_eod_price_volume", "min_row_count": None, "max_row_count": None},
            ],
        },
        "coverage_smoke_decision": {
            "decision": "bounded_coverage_smoke_completed_keep_sr_provider_001_open",
            "sr_provider_001_closed": False,
            "provider_selection_allowed": False,
            "phase7c_allowed": False,
            "rationale": "Small coverage smoke only.",
        },
        "prohibited_claims": {
            "provider_selected": False,
            "provider_ranked": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "sec_api_used": False,
            "paid_access_used": False,
            "raw_rows_in_tracked_summary": False,
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
            "production_ready_claimed": False,
        },
        "limitations": [
            "Five-symbol active-name smoke only.",
            "No provider selection.",
            "No production readiness.",
            "No ship-gate evidence.",
        ],
        "next_steps": [
            "Review the coverage-count summary.",
            "Do not broaden scope without approval.",
        ],
    }


class ProviderP1CoverageCountExecutionSummarySchemaTest(unittest.TestCase):
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
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "provider_p1_coverage_count_execution_summary",
        )
        self.assertIn("does not select a provider", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_minimal_summary_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(minimal_valid_summary()), [])

    def test_generated_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("coverage-count execution summary has not been generated yet")

        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self._validate(summary), [])
        summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("apikey=", summary_text.lower())
        self.assertNotIn("FMP_API_KEY", summary_text)
        self.assertNotIn("Bearer ", summary_text)

    def test_scope_locks_block_broad_provider_use(self) -> None:
        summary = minimal_valid_summary()
        scope = summary["scope"]

        self.assertTrue(scope["coverage_count_execution_performed"])
        self.assertTrue(scope["fmp_stable_endpoint_calls_performed"])
        for field in [
            "sec_api_calls_performed",
            "yfinance_used",
            "full_market_download_performed",
            "provider_status_polling_performed",
            "fallback_execution_performed",
            "fixture_generation_performed",
            "return_calculation_performed",
            "corporate_action_reconciliation_performed",
            "field_mapping_or_parser_implementation_performed",
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_summary",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(minimal_valid_summary())
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["scope"]["phase7c_authorized_by_this_summary"] = True
        invalid["sample_universe"]["symbols"].append("TSLA")
        invalid["prohibited_claims"]["full_market_download_performed"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
