from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/us_short_batch5_massive_quota_access_bounded_probe_packet.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_massive_quota_access_bounded_probe_packet_20260706.json")


class UsShortBatch5MassiveQuotaAccessBoundedProbePacketSchemaTest(unittest.TestCase):
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
            "us_short_batch5_massive_quota_access_bounded_probe_packet",
        )
        self.assertIn("Massive quota/access bounded probe", schema["description"])
        self.assertIn("does not execute provider calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_no_provider_selection_and_no_full_market(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_claims"]

        self.assertEqual(scope["contract_status"], "bounded_probe_packet_no_access_not_executed")
        self.assertEqual(scope["provider"], "Massive")
        self.assertEqual(scope["market"], "US")
        self.assertEqual(scope["route"], "US-short")
        self.assertEqual(scope["purpose"], "quota_access_response_shape_probe_packet")
        self.assertTrue(scope["manual_order_only"])
        for field in [
            "network_access_performed",
            "provider_calls_performed",
            "provider_status_polling_performed",
            "raw_payload_read_or_parsed",
            "raw_payload_written",
            "source_packet_written",
            "data_context_written",
            "provider_selection_allowed",
            "provider_switch_claimed",
            "yfinance_allowed",
            "fmp_allowed",
            "sec_calls_allowed_by_this_packet",
            "full_market_fetch_allowed",
            "grouped_daily_full_market_allowed",
            "provider_contact_allowed",
            "new_token_or_trial_allowed",
            "paid_access_allowed",
            "datahub_allowed",
            "production_storage_allowed",
            "production_runner_consumption_allowed",
            "ship_gate_or_live_normalized_evidence_claimed",
            "broker_or_order_execution_allowed",
            "a_share_crossing_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_future_probe_boundary_is_exact_twelve_call_massive_only_probe(self) -> None:
        artifact = self._load_artifact()
        boundary = artifact["future_bounded_probe_boundary"]
        sample = boundary["sample_universe"]
        budget = boundary["endpoint_call_budget"]
        families = {item["endpoint_family"]: item for item in boundary["endpoint_families"]}

        self.assertEqual(boundary["authorization_status"], "recorded_for_future_post_review_execution_not_executed")
        self.assertTrue(boundary["requires_post_review_execution_command"])
        self.assertTrue(boundary["requires_network_tool_approval_at_execution_time"])
        self.assertEqual(sample["symbols"], ["AAPL", "MSFT", "JPM"])
        self.assertTrue(sample["active_symbols_only"])
        self.assertTrue(sample["not_full_market_or_security_master"])
        self.assertEqual(budget["max_total_endpoint_calls"], 12)
        self.assertEqual(budget["massive_planned_endpoint_calls"], 12)
        self.assertEqual(budget["retry_count_allowed"], 0)
        self.assertTrue(budget["abort_if_budget_exceeded"])
        self.assertFalse(budget["full_cut5_budget_cleared_by_this_probe"])

        self.assertEqual(set(families), {"ticker_overview", "news", "splits", "dividends"})
        for family_id, family in families.items():
            with self.subTest(family_id=family_id):
                self.assertEqual(family["provider_id"], "massive")
                self.assertEqual(family["call_count"], 3)
                self.assertTrue(family["raw_shape_parse_allowed_after_future_authorization"])
                self.assertFalse(family["authorizes_provider_call_now"])
                self.assertFalse(family["authorizes_full_candidate_run"])
                self.assertFalse(family["authorizes_source_packet_write"])
                self.assertFalse(family["authorizes_datahub_or_runner_consumption"])

    def test_quota_validation_cannot_clear_cut5_budget_or_analyst_gap(self) -> None:
        artifact = self._load_artifact()
        quota = artifact["quota_validation_limits"]
        gaps = {item["gap_id"]: item for item in artifact["unresolved_gates_after_probe"]}

        self.assertEqual(quota["cut5_eligible_count"], 2404)
        self.assertEqual(quota["current_cut5_forecast_total_calls"], 12021)
        self.assertEqual(quota["massive_no_analyst_scenario_total_calls"], 9617)
        self.assertFalse(quota["account_plan_quota_verified"])
        self.assertTrue(quota["account_plan_or_quota_header_required_to_continue"])
        self.assertFalse(quota["quota_header_absence_clears_full_budget"])
        self.assertFalse(quota["tiny_probe_can_clear_full_cut5_budget"])
        self.assertFalse(quota["full_cut5_budget_cleared"])
        self.assertEqual(quota["analyst_gap_status"], "unresolved_not_probeable_with_reviewed_massive_docs")
        self.assertIn("analyst_grades_no_massive_equivalent_found", gaps)
        self.assertIn("massive_full_cut5_call_budget_not_cleared_by_tiny_probe", gaps)
        self.assertIn("massive_license_storage_retention_unreviewed_for_cut5", gaps)
        for gate in gaps.values():
            with self.subTest(gate_id=gate["gap_id"]):
                self.assertTrue(gate["blocks_full_cut5_live_run"])
                self.assertFalse(gate["authorizes_provider_call_now"])

    def test_storage_summary_and_secret_boundary_are_locked(self) -> None:
        artifact = self._load_artifact()
        storage = artifact["future_storage_and_summary_contract"]

        self.assertEqual(
            storage["future_raw_sample_storage_path"],
            "provider_samples/us_short_batch5_massive_quota_access_probe_20260706/raw/",
        )
        self.assertEqual(
            storage["future_tracked_summary_path"],
            "docs/us_short_batch5_massive_quota_access_probe_summary_20260706.json",
        )
        self.assertTrue(storage["provider_samples_gitignore_check_required"])
        self.assertTrue(storage["tracked_summary_must_exclude_raw_payloads"])
        self.assertTrue(storage["tracked_summary_must_exclude_request_urls"])
        self.assertTrue(storage["tracked_summary_must_exclude_secrets"])
        self.assertTrue(storage["tracked_summary_must_exclude_authorization_headers"])
        self.assertFalse(storage["tracked_summary_write_authorized_by_this_artifact"])
        self.assertFalse(storage["raw_payload_write_authorized_by_this_artifact"])
        self.assertFalse(storage["production_storage_authorized"])

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_calls_performed"] = True
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["scope"]["full_market_fetch_allowed"] = True
        invalid["scope"]["yfinance_allowed"] = True
        invalid["future_bounded_probe_boundary"]["endpoint_call_budget"]["max_total_endpoint_calls"] = 12021
        invalid["future_bounded_probe_boundary"]["endpoint_families"][0]["authorizes_provider_call_now"] = True
        invalid["future_bounded_probe_boundary"]["endpoint_families"][0]["call_count"] = 2404
        invalid["quota_validation_limits"]["full_cut5_budget_cleared"] = True
        invalid["quota_validation_limits"]["analyst_gap_status"] = "resolved_by_massive"
        invalid["unresolved_gates_after_probe"][0]["blocks_full_cut5_live_run"] = False
        invalid["future_storage_and_summary_contract"]["tracked_summary_must_exclude_request_urls"] = False
        invalid["prohibited_claims"]["provider_selected"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
