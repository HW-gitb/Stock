from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_remaining_blocker_resolution_plan.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_remaining_blocker_resolution_plan_20260602.json")


class ProviderP1RemainingBlockerResolutionPlanSchemaTest(unittest.TestCase):
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
            "provider_p1_remaining_blocker_resolution_plan",
        )
        self.assertIn("does not fetch data", schema["description"])
        self.assertIn("does not fetch data, select a provider", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_selection_datahub_runner_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["purpose"], "p1_remaining_blocker_resolution_plan_after_fmp_stable_retry")
        self.assertEqual(scope["plan_status"], "plan_only_no_new_access")
        self.assertTrue(scope["manual_order_only"])
        for field in [
            "provider_selection_allowed",
            "provider_ranking_allowed",
            "new_token_or_trial_allowed",
            "paid_access_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
            "data_fetch_allowed",
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

    def test_remaining_blocker_tracks_are_complete_and_non_authorizing(self) -> None:
        artifact = self._load_artifact()
        tracks = {item["blocker_id"]: item for item in artifact["blocker_resolution_tracks"]}

        self.assertEqual(
            set(tracks),
            {
                "coverage_counts",
                "license_storage_retention_rights",
                "pit_observed_date_semantics",
                "price_adjustment_corporate_actions",
                "sec_edgar_audit_parser_feasibility",
                "fallback_incident_stability",
                "production_readiness_phase7c_gate",
            },
        )
        for blocker_id, track in tracks.items():
            with self.subTest(blocker_id=blocker_id):
                self.assertEqual(track["status"], "blocked_pending_review_or_approval")
                self.assertTrue(track["required_resolution_items"])
                self.assertTrue(track["review_refs_required"])
                self.assertFalse(track["authorizes_provider_selection"])
                self.assertFalse(track["authorizes_data_fetch"])
                self.assertFalse(track["authorizes_adapter_or_datahub"])
                self.assertFalse(track["authorizes_runner_consumption"])
                self.assertFalse(track["authorizes_phase7c"])

        self.assertTrue(tracks["coverage_counts"]["requires_user_approval_before_data_or_access"])
        self.assertEqual(
            tracks["license_storage_retention_rights"]["allowed_next_action_type"],
            "docs_or_user_decision_only",
        )

    def test_sources_and_limitations_keep_stable_retry_as_narrow_evidence(self) -> None:
        artifact = self._load_artifact()
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_not_proven = "\n".join(artifact["current_evidence_summary"]["not_proven_by_current_evidence"])
        joined_next = "\n".join(artifact["next_steps"])
        joined_limits = "\n".join(artifact["limitations"])

        self.assertIn("p1_fmp_stable_retry_summary_20260602", source_ids)
        self.assertIn("p1_sample_validation_access_approval_20260602", source_ids)
        self.assertIn("provider_evidence_drift_monitor_contract", source_ids)
        self.assertIn("coverage counts", joined_not_proven)
        self.assertIn("PIT", joined_not_proven)
        self.assertIn("license", joined_not_proven)
        self.assertIn("Do not run additional provider data by default", joined_next)
        self.assertIn("license / storage / retention review", joined_next)
        self.assertIn("performs no web research", joined_limits)
        self.assertIn("not provider selection", joined_limits)
        self.assertIn("not a price source", joined_limits)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["scope"]["data_fetch_allowed"] = True
        invalid["scope"]["phase7c_authorized_by_this_artifact"] = True
        invalid["prohibited_actions"]["yfinance_check"] = True
        invalid["blocker_resolution_tracks"][0]["authorizes_data_fetch"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
