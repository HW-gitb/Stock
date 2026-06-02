from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_fallback_incident_stability_playbook.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json")


class ProviderP1FallbackIncidentStabilityPlaybookSchemaTest(unittest.TestCase):
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
            "provider_p1_fallback_incident_stability_playbook",
        )
        self.assertIn("does not fetch data", schema["description"])
        self.assertIn("does not fetch data, poll provider status pages", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_access_polling_execution_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["purpose"], "p1_fallback_incident_stability_playbook_design")
        self.assertEqual(scope["playbook_status"], "schema_first_design_no_provider_calls")
        self.assertTrue(scope["manual_order_only"])
        for field in [
            "provider_selection_allowed",
            "provider_ranking_allowed",
            "new_token_or_trial_allowed",
            "paid_access_allowed",
            "yfinance_allowed",
            "full_market_download_allowed",
            "data_fetch_allowed",
            "provider_status_polling_allowed",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "production_runner_consumption_allowed",
            "fallback_execution_allowed",
            "phase7c_authorized_by_this_artifact",
            "strategy_rule_change_allowed",
            "broker_or_order_automation_allowed",
            "ship_gate_relaxed",
            "production_ready_claim_allowed",
        ]:
            self.assertFalse(scope[field], field)
        for value in prohibited.values():
            self.assertFalse(value)

    def test_field_family_playbooks_are_complete_and_default_deny(self) -> None:
        artifact = self._load_artifact()
        playbooks = {item["family_id"]: item for item in artifact["field_family_playbooks"]}

        self.assertEqual(
            set(playbooks),
            {
                "fundamentals",
                "price_volume_liquidity",
                "corporate_actions",
                "security_master_coverage",
                "sec_edgar_audit",
                "benchmark_gics",
            },
        )
        for family_id, playbook in playbooks.items():
            with self.subTest(family_id=family_id):
                self.assertGreaterEqual(len(playbook["fallback_order"]), 2)
                self.assertTrue(playbook["hard_block_triggers"])
                self.assertTrue(playbook["manual_review_triggers"])
                self.assertFalse(playbook["silent_default_allowed"])
                self.assertFalse(playbook["zero_fill_allowed"])
                self.assertFalse(playbook["latest_only_backfill_allowed"])
                self.assertFalse(playbook["authorizes_provider_selection"])
                self.assertFalse(playbook["authorizes_data_fetch"])
                self.assertFalse(playbook["authorizes_adapter_or_datahub"])
                self.assertFalse(playbook["authorizes_runner_consumption"])
                self.assertFalse(playbook["authorizes_phase7c"])
                for step in playbook["fallback_order"]:
                    self.assertFalse(step["authorizes_data_fetch"])

        self.assertIn("Optional yfinance smoke check", playbooks["price_volume_liquidity"]["fallback_order"][1]["source_role"])
        self.assertEqual(playbooks["benchmark_gics"]["primary_candidate_status"], "blocked_until_licensed_feed")

    def test_incident_matrix_records_and_blocks_until_review(self) -> None:
        artifact = self._load_artifact()
        incidents = {item["incident_id"]: item for item in artifact["incident_response_matrix"]}

        self.assertEqual(
            set(incidents),
            {
                "quota_or_rate_limit",
                "http_5xx_or_provider_outage",
                "http_401_403_auth_scope",
                "schema_or_field_semantics_drift",
                "stale_or_missing_rows",
                "pit_or_observed_date_ambiguity",
                "corporate_action_adjustment_conflict",
                "sec_edgar_audit_conflict",
            },
        )
        for incident_id, incident in incidents.items():
            with self.subTest(incident_id=incident_id):
                self.assertIn("record_incident", incident["required_actions"])
                self.assertTrue(incident["requires_incident_log"])
                self.assertFalse(incident["production_use_allowed_until_review"])
                self.assertFalse(incident["authorizes_provider_selection"])
                self.assertFalse(incident["authorizes_data_fetch"])
                self.assertFalse(incident["authorizes_adapter_or_datahub"])
                self.assertFalse(incident["authorizes_runner_consumption"])
                self.assertFalse(incident["authorizes_phase7c"])

        self.assertEqual(incidents["stale_or_missing_rows"]["default_action"], "block_production_use")
        self.assertEqual(incidents["pit_or_observed_date_ambiguity"]["default_action"], "freeze_latest_only_claims")

    def test_sources_limitations_and_next_steps_keep_playbook_design_only(self) -> None:
        artifact = self._load_artifact()
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_limits = "\n".join(artifact["limitations"])
        joined_next = "\n".join(artifact["next_steps"])
        joined_not_proven = "\n".join(artifact["stable_retry_boundary"]["not_proven"])

        self.assertIn("p1_remaining_blocker_plan_20260602", source_ids)
        self.assertIn("p1_coverage_fallback_incident_candidates_20260528", source_ids)
        self.assertIn("provider_evidence_drift_monitor_contract", source_ids)
        self.assertIn("does not poll any provider status page", joined_not_proven)
        self.assertIn("performs no web research", joined_limits)
        self.assertIn("do not prove provider stability", joined_limits)
        self.assertIn("license / storage / retention review", joined_next)
        self.assertIn("status monitoring", joined_next)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_selection_allowed"] = True
        invalid["scope"]["provider_status_polling_allowed"] = True
        invalid["scope"]["data_fetch_allowed"] = True
        invalid["prohibited_actions"]["fallback_execution"] = True
        invalid["field_family_playbooks"][0]["silent_default_allowed"] = True
        invalid["field_family_playbooks"][0]["fallback_order"][0]["authorizes_data_fetch"] = True
        invalid["incident_response_matrix"][0]["production_use_allowed_until_review"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
