from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

SCHEMA_PATH = Path("schemas/us_short_batch5_provider_live_post_probe_disposition.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_provider_live_post_probe_disposition_20260625.json")


class UsShortBatch5ProviderLivePostProbeDispositionSchemaTest(unittest.TestCase):
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
            "us_short_batch5_provider_live_post_probe_disposition",
        )
        self.assertIn("post-probe blocker disposition", schema["description"])
        self.assertIn("does not execute provider calls", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_and_completed_probe_trace_are_locked(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        trace = artifact["completed_probe_trace"]

        self.assertEqual(scope["market"], "US")
        self.assertEqual(scope["lane"], "us_short")
        self.assertEqual(scope["batch"], "batch5_provider_live")
        self.assertEqual(scope["artifact_status"], "post_probe_disposition_offline_only")
        self.assertTrue(scope["completed_probe_is_response_shape_only"])
        self.assertTrue(scope["small_sample_first_completed"])
        self.assertTrue(scope["broader_provider_live_still_requires_separate_authorization"])
        for field in [
            "provider_calls_executed_by_this_artifact",
            "raw_payloads_read_by_this_artifact",
            "network_access_required_for_this_artifact",
            "datahub_consumption_allowed",
            "production_storage_allowed",
            "provider_selection_allowed",
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

        self.assertEqual(trace["probe_summary_ref"], "docs/us_short_batch5_provider_live_probe_summary_20260625.json")
        self.assertEqual(trace["authorization_ref"], "user_chat_20260625_batch5_provider_live_probe_10_call_boundary")
        self.assertEqual(trace["actual_total_endpoint_calls"], 10)
        self.assertEqual(trace["actual_fmp_endpoint_calls"], 6)
        self.assertEqual(trace["actual_sec_public_api_calls"], 4)
        self.assertEqual(trace["retry_count"], 0)
        self.assertEqual(trace["endpoint_success_count"], 10)
        self.assertEqual(trace["endpoint_error_count"], 0)
        self.assertEqual(trace["symbols"], ["AAPL", "MSFT", "JPM"])
        self.assertTrue(trace["tracked_summary_contains_no_secrets_urls_or_raw_rows"])
        self.assertFalse(trace["datahub_consumption_performed"])
        self.assertFalse(trace["ship_gate_or_live_normalized_evidence_claimed"])

    def test_remaining_blockers_keep_provider_gates_closed(self) -> None:
        blockers = {
            blocker["blocker_id"]: blocker
            for blocker in self._load_artifact()["remaining_blocker_disposition"]
        }

        self.assertEqual(
            set(blockers),
            {
                "license_storage_retention_rights",
                "coverage_count_security_master",
                "pit_observed_date_semantics",
                "price_adjustment_corporate_actions",
                "sec_edgar_audit_parser_mapping",
                "fallback_incident_stability",
                "forward_universe_snapshot_real_capture",
                "datahub_runner_consumption",
                "live_normalized_evidence_ship_gate",
                "provider_selection_production_readiness",
            },
        )
        for blocker in blockers.values():
            self.assertFalse(blocker["authorizes_provider_call_now"], blocker)
            self.assertFalse(blocker["authorizes_datahub_or_runner_consumption"], blocker)
            self.assertFalse(blocker["authorizes_production_storage"], blocker)
            self.assertFalse(blocker["authorizes_ship_gate_or_live_normalized_evidence"], blocker)

        for blocker_id in [
            "coverage_count_security_master",
            "pit_observed_date_semantics",
            "price_adjustment_corporate_actions",
            "forward_universe_snapshot_real_capture",
        ]:
            self.assertTrue(blockers[blocker_id]["new_user_authorization_required_before_action"])
            self.assertTrue(blockers[blocker_id]["provider_live_or_network_needed"])
            self.assertEqual(blockers[blocker_id]["next_action_class"], "provider_live_requires_new_authorization")

        self.assertFalse(blockers["fallback_incident_stability"]["new_user_authorization_required_before_action"])
        self.assertFalse(blockers["fallback_incident_stability"]["provider_live_or_network_needed"])
        self.assertEqual(blockers["fallback_incident_stability"]["next_action_class"], "offline_schema_first_allowed")
        self.assertEqual(blockers["live_normalized_evidence_ship_gate"]["next_action_class"], "not_allowed_in_batch5_v1")

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["datahub_consumption_allowed"] = True
        invalid["scope"]["ship_gate_evidence_allowed"] = True
        invalid["completed_probe_trace"]["actual_total_endpoint_calls"] = 11
        invalid["completed_probe_trace"]["symbols"].append("NVDA")
        invalid["authorization_boundary_template"]["current_artifact_provider_call_budget"] = 1
        invalid["prohibited_actions"]["provider_live_call_authorized_by_this_artifact"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_blocker_disposition_drift_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        for blocker in invalid["remaining_blocker_disposition"]:
            if blocker["blocker_id"] == "coverage_count_security_master":
                blocker["new_user_authorization_required_before_action"] = False
            if blocker["blocker_id"] == "fallback_incident_stability":
                blocker["provider_live_or_network_needed"] = True
            if blocker["blocker_id"] == "live_normalized_evidence_ship_gate":
                blocker["next_action_class"] = "offline_schema_first_allowed"

        self.assertNotEqual(self._validate(invalid), [])

    def test_missing_or_reordered_required_blocker_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["remaining_blocker_disposition"].pop(6)
        invalid["remaining_blocker_disposition"].append(copy.deepcopy(invalid["remaining_blocker_disposition"][0]))

        self.assertNotEqual(self._validate(invalid), [])

    def test_next_rounds_and_authorization_template_preserve_stop_points(self) -> None:
        artifact = self._load_artifact()
        rounds = artifact["next_execution_rounds"]
        boundary = artifact["authorization_boundary_template"]
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertEqual(rounds[0]["round_id"], "batch5_offline_fallback_incident_stability_binding")
        self.assertFalse(rounds[0]["new_user_authorization_required_before_round"])
        self.assertFalse(rounds[0]["provider_live_or_network_allowed_in_round"])
        self.assertEqual(rounds[2]["round_id"], "batch5_future_provider_live_blocker_probe")
        self.assertTrue(rounds[2]["new_user_authorization_required_before_round"])
        self.assertTrue(rounds[2]["provider_live_or_network_allowed_in_round"])
        self.assertTrue(boundary["required_before_any_future_provider_live_or_network"])
        self.assertEqual(boundary["current_artifact_provider_call_budget"], 0)
        self.assertEqual(boundary["default_future_call_budget_without_new_authorization"], 0)
        self.assertIn("separate explicit user authorization", joined_next)
        self.assertIn("did not run provider/live/network", joined_limits)
        self.assertIn("does not resolve SR-PROVIDER-001", joined_limits)


if __name__ == "__main__":
    unittest.main()
