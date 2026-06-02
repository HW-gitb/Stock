from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_fmp_endpoint_mapping_review.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_fmp_current_endpoint_mapping_review_20260602.json")


class ProviderP1FmpEndpointMappingReviewSchemaTest(unittest.TestCase):
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
            "provider_p1_fmp_endpoint_mapping_review",
        )
        self.assertIn("does not perform a live retry", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_retry_provider_selection_yfinance_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        retry_gate = artifact["retry_gate"]

        self.assertTrue(scope["docs_only_review"])
        self.assertFalse(scope["data_fetch_performed"])
        self.assertFalse(scope["fmp_live_retry_performed"])
        self.assertFalse(scope["provider_selection_allowed"])
        self.assertFalse(scope["paid_access_allowed"])
        self.assertFalse(scope["yfinance_allowed"])
        self.assertFalse(scope["full_market_download_allowed"])
        self.assertFalse(scope["provider_adapter_allowed"])
        self.assertFalse(scope["datahub_table_implementation_allowed"])
        self.assertFalse(scope["production_runner_change_allowed"])
        self.assertFalse(scope["phase7c_authorized_by_this_artifact"])
        self.assertFalse(scope["production_ready_claim_allowed"])
        self.assertFalse(scope["ship_gate_evidence_claimed"])
        self.assertFalse(retry_gate["retry_authorized_by_this_artifact"])
        self.assertEqual(
            retry_gate["allowed_retry_scope_if_user_approves"]["symbols"],
            ["AAPL", "MSFT"],
        )
        self.assertEqual(retry_gate["allowed_retry_scope_if_user_approves"]["spend_usd"], 0)
        for blocked in [
            "new_fmp_token",
            "fmp_trial_request",
            "paid_upgrade",
            "yfinance_check",
            "full_market_download",
            "provider_selection",
            "provider_adapter",
            "datahub_table",
            "production_runner_consumption",
            "phase7c_authorization",
            "ship_gate_claim",
        ]:
            self.assertIn(blocked, retry_gate["blocked_actions"])

    def test_mapping_covers_all_failed_sample_endpoint_families_with_stable_candidates(self) -> None:
        artifact = self._load_artifact()
        mappings = {
            item["endpoint_family"]: item
            for item in artifact["mapping_review"]["endpoint_mappings"]
        }

        self.assertEqual(
            set(mappings),
            {
                "profile_or_company_metadata",
                "income_statement",
                "balance_sheet_statement",
                "cash_flow_statement",
                "financial_ratios_or_key_metrics",
                "historical_eod_price_volume",
            },
        )
        for mapping in mappings.values():
            self.assertTrue(mapping["failed_legacy_template"].startswith("https://financialmodelingprep.com/api/v3/"))
            self.assertTrue(mapping["stable_candidate_template"].startswith("https://financialmodelingprep.com/stable/"))
            self.assertFalse(mapping["sample_live_validated"])
            self.assertTrue(mapping["official_doc_source_ids"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["fmp_live_retry_performed"] = True
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["retry_gate"]["retry_authorized_by_this_artifact"] = True
        invalid["retry_gate"]["allowed_retry_scope_if_user_approves"]["symbols"].append("TSLA")
        invalid["mapping_review"]["endpoint_mappings"][0]["sample_live_validated"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_next_steps_do_not_skip_review_or_broaden_scope(self) -> None:
        artifact = self._load_artifact()
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("review", joined_next.lower())
        self.assertIn("existing FMP key", joined_next)
        self.assertIn("AAPL / MSFT", joined_next)
        self.assertIn("Do not proceed to yfinance", joined_next)
        self.assertIn("full-market fetch", joined_next)
        self.assertIn("Phase 7c", joined_next)
        self.assertIn("no FMP stable endpoint has been live-retried", joined_limits)
        self.assertIn("Limit / timeseries parameter parity", joined_limits)


if __name__ == "__main__":
    unittest.main()
