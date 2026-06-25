from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/us_short_batch5_provider_live_packet.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_provider_live_packet_20260625.json")


class UsShortBatch5ProviderLivePacketSchemaTest(unittest.TestCase):
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
        self.assertEqual(schema["properties"]["schema_name"]["const"], "us_short_batch5_provider_live_packet")
        self.assertIn("US-short batch5 provider/live first version", schema["description"])
        self.assertIn("does not execute provider calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_is_batch5_first_version_and_offline_only(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["market"], "US")
        self.assertEqual(scope["lane"], "us_short")
        self.assertEqual(scope["batch"], "batch5_provider_live")
        self.assertEqual(scope["first_version_status"], "offline_readiness_packet_recorded_for_review_not_executed")
        self.assertFalse(scope["provider_calls_executed_by_this_artifact"])
        self.assertFalse(scope["raw_payloads_read_by_this_artifact"])
        self.assertFalse(scope["network_access_required_for_this_artifact"])
        self.assertTrue(scope["small_sample_first_required"])
        self.assertTrue(scope["future_provider_live_probe_requires_explicit_user_authorization"])
        self.assertTrue(scope["future_provider_live_probe_requires_reviewed_execution_packet"])
        for field in [
            "provider_calls_allowed_without_future_authorization",
            "provider_selection_allowed",
            "provider_adapter_allowed",
            "datahub_consumption_allowed",
            "skill_runtime_allowed",
            "production_storage_allowed",
            "full_market_or_broad_universe_allowed",
            "yfinance_allowed",
            "web_x_allowed",
            "sec_parser_implementation_allowed",
            "field_mapping_or_derivation_implementation_allowed",
            "return_calculation_allowed",
            "corporate_action_reconciliation_allowed",
            "broker_or_order_automation_allowed",
            "paper_results_as_live_normalized_allowed",
            "ship_gate_evidence_allowed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_future_probe_boundary_is_exact_small_sample_not_authorization(self) -> None:
        artifact = self._load_artifact()
        sample = artifact["future_provider_live_probe_boundary"]["sample_universe"]
        budget = artifact["future_provider_live_probe_boundary"]["endpoint_call_budget"]
        families = {
            (row["provider_id"], row["endpoint_family"]): row
            for row in artifact["future_provider_live_probe_boundary"]["endpoint_families"]
        }

        self.assertEqual(sample["symbols"], ["AAPL", "MSFT", "JPM"])
        self.assertEqual(sample["active_symbols"], ["AAPL", "MSFT", "JPM"])
        self.assertEqual(sample["inactive_or_delisted_historical_scope"], "scoped_out_for_current_active_only_forward_model")
        self.assertTrue(sample["not_full_market_or_security_master"])
        self.assertEqual(budget["max_total_endpoint_calls"], 10)
        self.assertEqual(budget["fmp_planned_endpoint_calls"], 6)
        self.assertEqual(budget["sec_endpoint_calls"], 4)
        self.assertEqual(budget["retry_count_allowed"], 0)
        self.assertTrue(budget["abort_if_budget_exceeded"])
        self.assertFalse(budget["budget_authorized_by_this_artifact"])

        self.assertEqual(families[("financial_modeling_prep", "profile_or_company_metadata")]["call_count"], 3)
        self.assertEqual(families[("financial_modeling_prep", "historical_eod_price_volume")]["call_count"], 3)
        self.assertEqual(families[("sec_edgar", "company_tickers_mapping")]["call_count"], 1)
        self.assertEqual(families[("sec_edgar", "company_submissions")]["call_count"], 3)
        for row in families.values():
            self.assertFalse(row["authorizes_provider_call_now"], row)
            self.assertFalse(row["authorizes_datahub_or_runner_consumption"], row)
            self.assertFalse(row["authorizes_return_calculation"], row)
            self.assertFalse(row["authorizes_corporate_action_reconciliation"], row)

    def test_storage_preflight_and_prohibited_claims_are_locked(self) -> None:
        artifact = self._load_artifact()
        storage = artifact["storage_and_secret_boundary"]

        self.assertEqual(storage["future_raw_sample_storage_path"], "provider_samples/us_short_batch5_v1_provider_live_20260625/")
        self.assertEqual(
            storage["future_tracked_summary_path"],
            "docs/us_short_batch5_provider_live_probe_summary_20260625.json",
        )
        self.assertTrue(storage["provider_samples_gitignore_check_required"])
        self.assertTrue(storage["tracked_summary_must_exclude_raw_payloads"])
        self.assertTrue(storage["tracked_summary_must_exclude_request_urls"])
        self.assertTrue(storage["tracked_summary_must_exclude_secrets"])
        self.assertFalse(storage["tracked_summary_write_authorized_by_this_artifact"])
        self.assertFalse(storage["raw_payload_write_authorized_by_this_artifact"])
        self.assertFalse(storage["production_storage_authorized"])

        for field, value in artifact["preflight_gates"].items():
            self.assertTrue(value, field)
        for field, value in artifact["prohibited_claims"].items():
            self.assertFalse(value, field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_calls_allowed_without_future_authorization"] = True
        invalid["scope"]["datahub_consumption_allowed"] = True
        invalid["scope"]["yfinance_allowed"] = True
        invalid["future_provider_live_probe_boundary"]["sample_universe"]["symbols"].append("NVDA")
        invalid["future_provider_live_probe_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"] = 11
        invalid["future_provider_live_probe_boundary"]["endpoint_call_budget"]["budget_authorized_by_this_artifact"] = True
        invalid["future_provider_live_probe_boundary"]["endpoint_families"][0]["authorizes_provider_call_now"] = True
        invalid["storage_and_secret_boundary"]["tracked_summary_must_exclude_request_urls"] = False
        invalid["prohibited_claims"]["ship_gate_evidence_claimed"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_endpoint_family_call_count_drift_is_rejected_by_schema(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        for family in invalid["future_provider_live_probe_boundary"]["endpoint_families"]:
            if family["provider_id"] == "financial_modeling_prep" and family["endpoint_family"] == "profile_or_company_metadata":
                family["call_count"] = 1
            if family["provider_id"] == "sec_edgar" and family["endpoint_family"] == "company_tickers_mapping":
                family["call_count"] = 3

        self.assertNotEqual(self._validate(invalid), [])

    def test_next_steps_keep_double_authorization_gate(self) -> None:
        artifact = self._load_artifact()
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("separate explicit user authorization", joined_next)
        self.assertIn("max_total_endpoint_calls = 10", joined_next)
        self.assertIn("dry-run preflight only", joined_next)
        self.assertIn("performs no provider call", joined_limits)
        self.assertIn("does not authorize DataHub", joined_limits)
        self.assertIn("ship-gate", joined_limits)


if __name__ == "__main__":
    unittest.main()
