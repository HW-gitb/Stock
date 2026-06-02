from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_us_egs_sample_validation_summary.schema.json")
SUMMARY_PATH = Path("docs/provider_evidence_p1_us_sample_validation_summary_20260602.json")


def minimal_valid_summary() -> dict:
    return {
        "schema_name": "provider_p1_us_egs_sample_validation_summary",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-02T00:00:00+00:00",
        "approval_ref": "docs/provider_evidence_p1_us_sample_validation_access_approval_20260602.json",
        "schema_ref": "schemas/provider_p1_us_egs_sample_validation_summary.schema.json",
        "scope": {
            "phase": "7b-2",
            "purpose": "us_egs_small_sample_validation_summary",
            "validation_status": "completed",
            "manual_order_only": True,
            "ship_gate_relaxed": False,
            "provider_selection_allowed": False,
            "datahub_table_implementation_allowed": False,
            "runner_change_allowed": False,
            "phase7c_authorized_by_this_summary": False,
            "production_ready_claim_allowed": False,
        },
        "environment": {
            "fmp_api_key_present": True,
            "fmp_api_key_source": "process",
            "sec_user_agent_present": True,
            "sec_user_agent_source": "process",
            "secrets_logged": False,
        },
        "storage": {
            "raw_sample_storage_path": "provider_samples/us_egs_sample_validation_20260602/",
            "raw_samples_gitignored": True,
            "tracked_summary_contains_raw_rows": False,
            "secrets_in_summary": False,
        },
        "sample_universe": {
            "symbols": ["AAPL", "MSFT"],
            "max_symbols": 2,
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": 40,
            "actual_total_endpoint_calls": 0,
            "within_budget": True,
        },
        "endpoint_results": [],
        "symbol_results": [
            {
                "symbol": "AAPL",
                "cik": "0000320193",
                "fmp": {
                    "endpoints_ok": 0,
                    "endpoints_error": 0,
                    "statement_observed_date_fields_present": False,
                    "price_volume_fields_present": False,
                },
                "sec_edgar": {
                    "cik_found": True,
                    "endpoints_ok": 0,
                    "endpoints_error": 0,
                    "submissions_observed_date_fields_present": False,
                    "companyfacts_core_tags_present": {
                        "revenue": False,
                        "net_income": False,
                        "assets": False,
                        "shares_outstanding": False,
                    },
                },
                "validation_observations": ["No production readiness is claimed."],
            },
            {
                "symbol": "MSFT",
                "cik": "0000789019",
                "fmp": {
                    "endpoints_ok": 0,
                    "endpoints_error": 0,
                    "statement_observed_date_fields_present": False,
                    "price_volume_fields_present": False,
                },
                "sec_edgar": {
                    "cik_found": True,
                    "endpoints_ok": 0,
                    "endpoints_error": 0,
                    "submissions_observed_date_fields_present": False,
                    "companyfacts_core_tags_present": {
                        "revenue": False,
                        "net_income": False,
                        "assets": False,
                        "shares_outstanding": False,
                    },
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
            "No ship-gate evidence.",
        ],
        "next_steps": [
            "Review the sample summary.",
            "Do not broaden scope without approval.",
        ],
    }


class ProviderP1UsEgsSampleValidationSummarySchemaTest(unittest.TestCase):
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
            "provider_p1_us_egs_sample_validation_summary",
        )
        self.assertIn("does not select a provider", schema["description"])
        self.assertIn("Raw provider/public API rows must stay under gitignored provider_samples/", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_minimal_summary_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(minimal_valid_summary()), [])

    def test_generated_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("sample validation summary has not been generated yet")

        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate(summary), [])
        summary_text = SUMMARY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("apikey=", summary_text.lower())
        self.assertNotIn("SEC_USER_AGENT=", summary_text)

    def test_scope_locks_block_provider_selection_datahub_runner_and_phase7c(self) -> None:
        schema = self._load_schema()
        scope_schema = schema["properties"]["scope"]["properties"]
        storage_schema = schema["properties"]["storage"]["properties"]
        prohibited_schema = schema["properties"]["prohibited_claims"]["properties"]

        for field in [
            "provider_selection_allowed",
            "datahub_table_implementation_allowed",
            "runner_change_allowed",
            "phase7c_authorized_by_this_summary",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope_schema[field]["const"], field)
        self.assertTrue(scope_schema["manual_order_only"]["const"])
        self.assertFalse(scope_schema["ship_gate_relaxed"]["const"])
        self.assertFalse(storage_schema["tracked_summary_contains_raw_rows"]["const"])
        self.assertFalse(storage_schema["secrets_in_summary"]["const"])
        self.assertEqual(
            storage_schema["raw_sample_storage_path"]["const"],
            "provider_samples/us_egs_sample_validation_20260602/",
        )
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
        invalid["scope"]["phase7c_authorized_by_this_summary"] = True
        invalid["prohibited_claims"]["full_market_download_performed"] = True
        invalid["sample_universe"]["symbols"].append("TSLA")

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
