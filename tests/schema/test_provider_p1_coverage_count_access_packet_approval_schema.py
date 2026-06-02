from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_coverage_count_access_packet_approval.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_coverage_count_access_packet_approval_20260602.json")


class ProviderP1CoverageCountAccessPacketApprovalSchemaTest(unittest.TestCase):
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
            "provider_p1_coverage_count_access_packet_approval",
        )
        self.assertIn("bounded FMP stable endpoint count run", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_allows_only_exact_coverage_packet(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]

        self.assertTrue(scope["coverage_count_execution_allowed"])
        self.assertTrue(scope["fmp_stable_endpoint_calls_allowed"])
        self.assertTrue(scope["count_only_response_inspection_allowed"])
        self.assertTrue(scope["raw_payload_storage_allowed"])
        for field in [
            "sec_api_calls_allowed",
            "yfinance_allowed",
            "new_token_or_trial_allowed",
            "paid_access_allowed",
            "full_market_download_allowed",
            "provider_status_polling_allowed",
            "fallback_execution_allowed",
            "fixture_generation_allowed",
            "field_mapping_or_parser_implementation_allowed",
            "return_calculation_allowed",
            "corporate_action_reconciliation_allowed",
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_approval",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_universe_endpoint_budget_and_storage_are_bounded(self) -> None:
        artifact = self._load_artifact()

        self.assertEqual(artifact["sample_universe"]["symbols"], ["AAPL", "MSFT", "NVDA", "JPM", "XOM"])
        self.assertEqual(artifact["sample_universe"]["max_symbols"], 5)
        self.assertFalse(artifact["sample_universe"]["inactive_or_delisted_in_scope"])
        self.assertEqual(len(artifact["endpoint_families"]), 6)
        self.assertEqual(artifact["endpoint_call_budget"]["max_total_endpoint_calls"], 30)
        self.assertEqual(artifact["endpoint_call_budget"]["retry_count_allowed"], 0)
        self.assertEqual(artifact["cost_and_access_boundary"]["approved_spend_usd"], 0)
        self.assertTrue(artifact["cost_and_access_boundary"]["existing_fmp_key_only"])
        self.assertEqual(
            artifact["storage_and_secret_boundary"]["raw_sample_storage_path"],
            "provider_samples/us_egs_coverage_count_20260602/fmp_stable/",
        )
        self.assertFalse(artifact["storage_and_secret_boundary"]["request_urls_in_summary_allowed"])
        self.assertFalse(artifact["storage_and_secret_boundary"]["api_key_logging_allowed"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["sec_api_calls_allowed"] = True
        invalid["scope"]["phase7c_authorized_by_this_approval"] = True
        invalid["sample_universe"]["symbols"].append("TSLA")
        invalid["prohibited_claims"]["provider_selected"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
