from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_fmp_stable_endpoint_retry_summary.schema.json")
SUMMARY_PATH = Path("docs/provider_evidence_p1_us_fmp_stable_endpoint_retry_summary_20260602.json")


def minimal_valid_summary() -> dict:
    endpoint_results = []
    for symbol in ["AAPL", "MSFT"]:
        endpoint_results.append(
            {
                "provider_id": "financial_modeling_prep",
                "endpoint_family": "profile_or_company_metadata",
                "symbol": symbol,
                "status": "ok",
                "http_status": 200,
                "error_type": None,
                "raw_sample_ref": (
                    "provider_samples/us_egs_sample_validation_20260602/"
                    f"fmp_stable_retry/raw/financial_modeling_prep/{symbol}/profile_or_company_metadata.json"
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
            }
        )
    return {
        "schema_name": "provider_p1_fmp_stable_endpoint_retry_summary",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-02T00:00:00+00:00",
        "approval_ref": "docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json",
        "mapping_review_ref": "docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json",
        "schema_ref": "schemas/provider_p1_fmp_stable_endpoint_retry_summary.schema.json",
        "scope": {
            "phase": "7b-2",
            "purpose": "fmp_stable_endpoint_retry_summary",
            "validation_status": "completed",
            "fmp_endpoint_mode": "stable",
            "data_fetch_performed": True,
            "fmp_live_retry_performed": True,
            "manual_order_only": True,
            "ship_gate_relaxed": False,
            "provider_selection_allowed": False,
            "paid_access_allowed": False,
            "yfinance_allowed": False,
            "full_market_download_allowed": False,
            "provider_adapter_allowed": False,
            "datahub_table_implementation_allowed": False,
            "production_runner_consumption_allowed": False,
            "phase7c_authorized_by_this_summary": False,
            "production_ready_claim_allowed": False,
        },
        "environment": {
            "fmp_api_key_present": True,
            "fmp_api_key_source": "process",
            "secrets_logged": False,
        },
        "storage": {
            "raw_sample_storage_path": "provider_samples/us_egs_sample_validation_20260602/fmp_stable_retry/",
            "raw_samples_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
        },
        "sample_universe": {
            "symbols": ["AAPL", "MSFT"],
            "max_symbols": 2,
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": 40,
            "actual_total_endpoint_calls": 2,
            "within_budget": True,
        },
        "mapping_basis": {
            "mapping_verdict": "stable_endpoint_candidates_identified_not_live_validated",
            "stable_base_url": "https://financialmodelingprep.com/stable/",
            "stable_endpoint_candidates_count": 6,
        },
        "endpoint_results": endpoint_results,
        "symbol_results": [
            {
                "symbol": "AAPL",
                "fmp": {
                    "endpoints_ok": 1,
                    "endpoints_error": 0,
                    "statement_observed_date_fields_present": False,
                    "price_volume_fields_present": False,
                },
                "validation_observations": ["No production readiness is claimed."],
            },
            {
                "symbol": "MSFT",
                "fmp": {
                    "endpoints_ok": 1,
                    "endpoints_error": 0,
                    "statement_observed_date_fields_present": False,
                    "price_volume_fields_present": False,
                },
                "validation_observations": ["No production readiness is claimed."],
            },
        ],
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "phase7c_authorized": False,
            "ship_gate_evidence_claimed": False,
        },
        "limitations": [
            "Small sample only.",
            "No provider selection.",
            "No production readiness.",
            "No ship-gate evidence.",
        ],
        "next_steps": [
            "Review the stable retry summary.",
            "Do not broaden scope without approval.",
        ],
    }


class ProviderP1FmpStableEndpointRetrySummarySchemaTest(unittest.TestCase):
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
            "provider_p1_fmp_stable_endpoint_retry_summary",
        )
        self.assertIn("FMP stable-endpoint retry", schema["description"])
        self.assertIn("does not select a provider", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_minimal_summary_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(minimal_valid_summary()), [])

    def test_generated_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("FMP stable retry summary has not been generated yet")

        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate(summary), [])
        summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("apikey=", summary_text.lower())
        self.assertNotIn("FMP_API_KEY", summary_text)
        self.assertNotIn("Bearer ", summary_text)

    def test_scope_locks_block_provider_selection_paid_yfinance_datahub_and_phase7c(self) -> None:
        schema = self._load_schema()
        scope_schema = schema["properties"]["scope"]["properties"]
        storage_schema = schema["properties"]["storage"]["properties"]
        prohibited_schema = schema["properties"]["prohibited_claims"]["properties"]

        self.assertEqual(scope_schema["fmp_endpoint_mode"]["const"], "stable")
        self.assertNotIn("dry_run_env_only", scope_schema["validation_status"]["enum"])
        self.assertTrue(scope_schema["data_fetch_performed"]["const"])
        self.assertTrue(scope_schema["fmp_live_retry_performed"]["const"])
        self.assertTrue(scope_schema["manual_order_only"]["const"])
        for field in [
            "ship_gate_relaxed",
            "provider_selection_allowed",
            "paid_access_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_summary",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope_schema[field]["const"], field)
        self.assertEqual(
            storage_schema["raw_sample_storage_path"]["const"],
            "provider_samples/us_egs_sample_validation_20260602/fmp_stable_retry/",
        )
        self.assertFalse(storage_schema["tracked_summary_contains_raw_rows"]["const"])
        self.assertFalse(storage_schema["secrets_in_summary"]["const"])
        self.assertFalse(storage_schema["request_urls_in_summary"]["const"])
        for field in [
            "provider_selected",
            "full_market_download_performed",
            "yfinance_used",
            "paid_access_used",
            "phase7c_authorized",
            "ship_gate_evidence_claimed",
        ]:
            self.assertFalse(prohibited_schema[field]["const"], field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(minimal_valid_summary())
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["scope"]["paid_access_allowed"] = True
        invalid["scope"]["phase7c_authorized_by_this_summary"] = True
        invalid["prohibited_claims"]["full_market_download_performed"] = True
        invalid["sample_universe"]["symbols"].append("TSLA")

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
