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

SCHEMA_PATH = Path("schemas/us_short_batch5_license_storage_retention_decision.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_license_storage_retention_decision_20260625.json")

EXPECTED_RIGHTS = {
    "already_produced_raw_sample_retention",
    "tracked_no_secret_summary",
    "production_raw_storage",
    "normalized_datahub_storage",
    "derived_reports_or_factor_outputs",
    "non_display_analytical_use",
    "export_or_redistribution",
    "retention_after_plan_lapse_or_account_change",
    "broader_or_future_sample_calls",
}

EXPECTED_CLASSIFICATIONS = {
    "financial_modeling_prep": {
        "already_produced_raw_sample_retention": "allowed_gitignored_reviewed_sample_only",
        "tracked_no_secret_summary": "allowed_tracked_no_secret_summary_only",
        "production_raw_storage": "blocked_pending_current_terms_user_decision",
        "normalized_datahub_storage": "blocked_pending_current_terms_user_decision",
        "derived_reports_or_factor_outputs": "blocked_pending_current_terms_user_decision",
        "non_display_analytical_use": "blocked_pending_current_terms_user_decision",
        "export_or_redistribution": "blocked_pending_current_terms_user_decision",
        "retention_after_plan_lapse_or_account_change": "blocked_pending_current_terms_user_decision",
        "broader_or_future_sample_calls": "blocked_requires_new_provider_live_authorization",
    },
    "sec_edgar": {
        "already_produced_raw_sample_retention": "allowed_gitignored_reviewed_sample_only",
        "tracked_no_secret_summary": "allowed_tracked_no_secret_summary_only",
        "production_raw_storage": "blocked_pending_parser_fair_access_artifact_contract",
        "normalized_datahub_storage": "blocked_pending_parser_fair_access_artifact_contract",
        "derived_reports_or_factor_outputs": "blocked_pending_parser_fair_access_artifact_contract",
        "non_display_analytical_use": "blocked_pending_parser_fair_access_artifact_contract",
        "export_or_redistribution": "blocked_pending_parser_fair_access_artifact_contract",
        "retention_after_plan_lapse_or_account_change": "not_applicable",
        "broader_or_future_sample_calls": "blocked_requires_new_provider_live_authorization",
    },
}

CLASSIFICATION_ALTERNATES = {
    "allowed_gitignored_reviewed_sample_only": "blocked_pending_current_terms_user_decision",
    "allowed_tracked_no_secret_summary_only": "blocked_pending_current_terms_user_decision",
    "blocked_pending_current_terms_user_decision": "allowed_gitignored_reviewed_sample_only",
    "blocked_pending_parser_fair_access_artifact_contract": "blocked_pending_current_terms_user_decision",
    "blocked_requires_new_provider_live_authorization": "blocked_pending_current_terms_user_decision",
    "not_applicable": "blocked_pending_current_terms_user_decision",
}


class UsShortBatch5LicenseStorageRetentionDecisionSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        self.assertTrue(path.exists(), f"missing required file: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_schema(self) -> dict:
        return self._load_json(SCHEMA_PATH)

    def _load_artifact(self) -> dict:
        return self._load_json(ARTIFACT_PATH)

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
            "us_short_batch5_license_storage_retention_decision",
        )
        self.assertIn("US-short batch5", schema["description"])
        self.assertIn("does not refresh current terms", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_and_basis_are_docs_only_no_access(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        basis = artifact["decision_basis"]

        self.assertEqual(scope["market"], "US")
        self.assertEqual(scope["lane"], "us_short")
        self.assertEqual(scope["batch"], "batch5_provider_live")
        self.assertEqual(scope["artifact_status"], "license_storage_retention_decision_offline_only")
        for field in [
            "provider_calls_executed_by_this_artifact",
            "network_access_required_for_this_artifact",
            "current_terms_web_refresh_performed",
            "provider_contact_performed",
            "legal_advice_claimed",
            "raw_payloads_read_by_this_artifact",
            "raw_payloads_written_by_this_artifact",
            "provider_selection_allowed",
            "provider_ranking_allowed",
            "datahub_consumption_allowed",
            "runner_consumption_allowed",
            "production_storage_allowed",
            "production_ready_claim_allowed",
            "ship_gate_evidence_allowed",
            "live_normalized_evidence_allowed",
            "future_provider_live_call_authorized",
            "yfinance_allowed",
            "web_x_allowed",
            "broker_or_order_automation_allowed",
        ]:
            self.assertFalse(scope[field], field)

        self.assertEqual(basis["basis_type"], "existing_repo_artifacts_no_new_external_review")
        self.assertTrue(basis["uses_existing_reviewed_artifacts_only"])
        self.assertTrue(basis["requires_later_current_terms_or_user_decision_before_production_use"])
        self.assertTrue(basis["batch5_probe_is_response_shape_only"])

    def test_source_refs_and_probe_trace_are_locked(self) -> None:
        artifact = self._load_artifact()
        source_ids = {row["artifact_id"] for row in artifact["source_artifact_refs"]}
        trace = artifact["probe_storage_trace"]

        for ref_id in [
            "us_short_system_design",
            "us_short_batch5_provider_live_post_probe_disposition_20260625",
            "us_short_batch5_provider_live_probe_summary_20260625",
            "provider_p1_license_storage_retention_review_20260602",
            "sr_provider_001",
        ]:
            self.assertIn(ref_id, source_ids)

        self.assertEqual(trace["probe_summary_ref"], "docs/us_short_batch5_provider_live_probe_summary_20260625.json")
        self.assertEqual(trace["actual_total_endpoint_calls"], 10)
        self.assertEqual(trace["symbols"], ["AAPL", "MSFT", "JPM"])
        self.assertEqual(
            trace["raw_payload_root"],
            "provider_samples/us_short_batch5_v1_provider_live_20260625/raw/",
        )
        self.assertTrue(trace["raw_payload_root_is_gitignored"])
        self.assertFalse(trace["tracked_summary_contains_secret_url_or_raw_rows"])
        self.assertFalse(trace["authorizes_broader_raw_retention"])

    def test_decision_summary_keeps_sample_only_and_blocks_production(self) -> None:
        summary = self._load_artifact()["decision_summary"]

        self.assertEqual(summary["decision_status"], "reviewed_sample_only_non_production_use")
        self.assertTrue(summary["already_produced_batch5_raw_samples_may_remain_gitignored"])
        self.assertTrue(summary["tracked_no_secret_summaries_may_remain_tracked"])
        self.assertFalse(summary["current_fmp_basic_evidence_sufficient_for_production_storage"])
        self.assertFalse(summary["current_sec_public_evidence_sufficient_for_broad_parser_use"])
        self.assertFalse(summary["current_evidence_sufficient_for_datahub_or_runner_consumption"])
        self.assertFalse(summary["current_evidence_sufficient_for_provider_selection"])
        self.assertFalse(summary["current_evidence_sufficient_for_live_normalized_or_ship_gate"])

    def test_rights_matrix_keeps_fmp_and_sec_blocks_distinct(self) -> None:
        rights_by_provider = {
            row["provider_id"]: {right["right_id"]: right for right in row["rights"]}
            for row in self._load_artifact()["rights_matrix"]
        }

        self.assertEqual(set(rights_by_provider), {"financial_modeling_prep", "sec_edgar"})
        for provider_id, rights in rights_by_provider.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(set(rights), EXPECTED_RIGHTS)
                self.assertEqual(
                    rights["already_produced_raw_sample_retention"]["classification"],
                    "allowed_gitignored_reviewed_sample_only",
                )
                self.assertEqual(
                    rights["tracked_no_secret_summary"]["classification"],
                    "allowed_tracked_no_secret_summary_only",
                )
                self.assertEqual(
                    rights["broader_or_future_sample_calls"]["classification"],
                    "blocked_requires_new_provider_live_authorization",
                )
                for right in rights.values():
                    self.assertFalse(right["authorizes_future_provider_call"], right)
                    self.assertFalse(right["authorizes_datahub_or_runner_consumption"], right)
                    self.assertFalse(right["authorizes_production_storage"], right)
                    self.assertFalse(right["authorizes_ship_gate_or_live_normalized_evidence"], right)
                    self.assertTrue(right["required_before_status_can_improve"], right)

        for provider_id, expected_classifications in EXPECTED_CLASSIFICATIONS.items():
            for right_id, expected_classification in expected_classifications.items():
                with self.subTest(provider_id=provider_id, right_id=right_id):
                    self.assertEqual(
                        rights_by_provider[provider_id][right_id]["classification"],
                        expected_classification,
                    )

    def test_schema_rejects_provider_right_classification_drift_when_jsonschema_available(self) -> None:
        for provider_id, expected_classifications in EXPECTED_CLASSIFICATIONS.items():
            for right_id, expected_classification in expected_classifications.items():
                invalid = copy.deepcopy(self._load_artifact())
                provider = next(row for row in invalid["rights_matrix"] if row["provider_id"] == provider_id)
                right = next(row for row in provider["rights"] if row["right_id"] == right_id)
                right["classification"] = CLASSIFICATION_ALTERNATES[expected_classification]

                with self.subTest(provider_id=provider_id, right_id=right_id):
                    self.assertNotEqual(self._validate(invalid), [])

    def test_stop_points_and_future_authorization_boundary_are_locked(self) -> None:
        artifact = self._load_artifact()
        stop_points = {row["stop_point_id"]: row for row in artifact["stop_points"]}
        boundary = artifact["future_authorization_boundary_template"]

        for stop_id in [
            "current_terms_web_refresh",
            "legal_review_or_terms_interpretation",
            "provider_contact_trial_or_paid_access",
            "future_provider_live_or_network_probe",
            "datahub_runner_or_production_storage",
            "live_normalized_or_ship_gate_claim",
        ]:
            self.assertIn(stop_id, stop_points)
            self.assertTrue(stop_points[stop_id]["must_stop_for_separate_user_authorization_or_review"])
            self.assertFalse(stop_points[stop_id]["authorized_by_this_decision"])

        self.assertTrue(boundary["required_before_any_future_provider_live_or_network"])
        self.assertEqual(boundary["default_future_call_budget_without_new_authorization"], 0)
        for field in [
            "must_state_symbols",
            "must_state_endpoints",
            "must_state_call_budget",
            "must_state_retry_policy",
            "must_state_write_locations",
            "must_state_secret_and_raw_privacy_boundary",
            "must_state_validation_method",
            "must_state_non_authorized_paths",
        ]:
            self.assertTrue(boundary[field], field)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["network_access_required_for_this_artifact"] = True
        invalid["decision_basis"]["current_terms_web_refresh_performed"] = True
        invalid["decision_summary"]["current_evidence_sufficient_for_datahub_or_runner_consumption"] = True
        invalid["rights_matrix"][0]["rights"][2]["authorizes_production_storage"] = True
        invalid["stop_points"][0]["authorized_by_this_decision"] = True
        invalid["prohibited_actions"]["ship_gate_or_live_normalized_evidence_authorized"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
