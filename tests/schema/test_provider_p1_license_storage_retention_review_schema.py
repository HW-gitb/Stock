from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_license_storage_retention_review.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_license_storage_retention_review_20260602.json")


class ProviderP1LicenseStorageRetentionReviewSchemaTest(unittest.TestCase):
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
            "provider_p1_license_storage_retention_review",
        )
        self.assertIn("does not perform web research", schema["description"])
        self.assertIn("does not", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_selection_datahub_runner_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["review_status"], "no_access_blocker_classification_existing_repo_evidence")
        for field in [
            "data_fetch_allowed",
            "provider_selection_allowed",
            "provider_ranking_allowed",
            "new_token_or_trial_allowed",
            "paid_access_allowed",
            "provider_contact_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "phase7c_authorized_by_this_artifact",
            "strategy_rule_change_allowed",
            "broker_or_order_automation_allowed",
            "ship_gate_relaxed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_review_basis_disclaims_current_terms_refresh_and_legal_advice(self) -> None:
        artifact = self._load_artifact()
        basis = artifact["review_basis"]
        summary = artifact["current_classification_summary"]

        self.assertEqual(basis["basis_type"], "existing_repo_artifacts_no_new_external_review")
        self.assertFalse(basis["current_terms_web_refresh_performed"])
        self.assertFalse(basis["provider_contact_performed"])
        self.assertFalse(basis["legal_advice_claimed"])
        self.assertTrue(basis["uses_existing_reviewed_artifacts_only"])
        self.assertTrue(basis["requires_later_current_terms_review_before_paid_or_production_use"])
        self.assertEqual(summary["fmp_license_storage_status"], "blocked_beyond_user_approved_two_symbol_sample")
        self.assertEqual(summary["production_storage_policy"], "blocked_until_current_terms_and_user_decision_review")

    def test_rights_matrix_keeps_broad_storage_and_datahub_blocked(self) -> None:
        artifact = self._load_artifact()
        rights_by_provider = {
            provider["provider_id"]: {right["right_id"]: right for right in provider["rights"]}
            for provider in artifact["rights_matrix"]
        }

        self.assertEqual(set(rights_by_provider), {"financial_modeling_prep", "sec_edgar"})
        required_rights = {
            "local_raw_sample_storage",
            "tracked_no_secret_summary",
            "production_raw_storage",
            "normalized_datahub_storage",
            "derived_reports_or_factor_outputs",
            "non_display_use",
            "export_or_redistribution",
            "cache_retention_after_lapse",
            "professional_or_business_use",
            "full_market_or_broader_sample",
        }
        for provider_id, rights in rights_by_provider.items():
            with self.subTest(provider_id=provider_id):
                self.assertEqual(set(rights), required_rights)
                self.assertIn(
                    rights["local_raw_sample_storage"]["classification"],
                    {"allowed_narrow_sample_only"},
                )
                self.assertEqual(
                    rights["tracked_no_secret_summary"]["classification"],
                    "allowed_tracked_summary_only",
                )
                for right_id, right in rights.items():
                    self.assertFalse(right["authorizes_broader_access"], right_id)
                    self.assertFalse(right["authorizes_data_fetch"], right_id)
                    self.assertFalse(right["authorizes_datahub_or_runner_consumption"], right_id)
                    self.assertTrue(right["required_before_status_can_improve"], right_id)

        self.assertEqual(
            rights_by_provider["financial_modeling_prep"]["production_raw_storage"]["classification"],
            "blocked_pending_current_terms_review",
        )
        self.assertEqual(
            rights_by_provider["financial_modeling_prep"]["normalized_datahub_storage"]["classification"],
            "blocked_pending_current_terms_review",
        )
        self.assertEqual(
            rights_by_provider["sec_edgar"]["production_raw_storage"]["classification"],
            "blocked_pending_parser_and_fair_access_contract",
        )

    def test_sources_and_next_steps_preserve_provider_blockers(self) -> None:
        artifact = self._load_artifact()
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("p1_remaining_blocker_plan_20260602", source_ids)
        self.assertIn("p1_sample_validation_access_approval_20260602", source_ids)
        self.assertIn("p1_authorization_cost_stability_snapshot_20260528", source_ids)
        self.assertIn("p1_fmp_stable_retry_summary_20260602", source_ids)
        self.assertIn("current terms review", joined_next)
        self.assertIn("SEC EDGAR broader reconstruction blocked", joined_next)
        self.assertIn("not legal advice", joined_limits)
        self.assertIn("does not resolve SR-PROVIDER-001", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["data_fetch_allowed"] = True
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["review_basis"]["current_terms_web_refresh_performed"] = True
        invalid["rights_matrix"][0]["rights"][2]["authorizes_datahub_or_runner_consumption"] = True
        invalid["decision_gates"][0]["authorizes_phase7c"] = True
        invalid["prohibited_actions"]["paid_upgrade"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
