from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/provider_p1_incident_log_contract.schema.json")
ARTIFACT_PATH = Path("docs/provider_evidence_p1_us_incident_log_contract_20260602.json")


class ProviderP1IncidentLogContractSchemaTest(unittest.TestCase):
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
            "provider_p1_incident_log_contract",
        )
        self.assertIn("does not create log files", schema["description"])
        self.assertIn("does not create log files, implement a writer", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_locks_no_logging_provider_calls_status_polling_or_phase7c(self) -> None:
        artifact = self._load_artifact()
        scope = artifact["scope"]
        contract = artifact["incident_log_contract"]
        prohibited = artifact["prohibited_actions"]

        self.assertEqual(scope["purpose"], "p1_incident_log_contract_design")
        self.assertEqual(scope["contract_status"], "schema_first_contract_no_logging_implementation")
        self.assertFalse(scope["incident_log_write_implemented"])
        self.assertFalse(scope["log_storage_path_created"])
        self.assertTrue(scope["manual_order_only"])
        self.assertTrue(contract["no_actual_incident_records_created"])
        self.assertFalse(contract["authorizes_log_writer"])
        self.assertFalse(contract["authorizes_status_polling"])
        self.assertFalse(contract["authorizes_data_fetch"])
        self.assertTrue(contract["raw_payloads_must_be_gitignored"])
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

    def test_required_record_fields_are_complete_and_no_secret_bearing(self) -> None:
        artifact = self._load_artifact()
        fields = {item["field_name"]: item for item in artifact["required_record_fields"]}

        self.assertEqual(
            set(fields),
            {
                "incident_id",
                "detected_at",
                "detected_by",
                "source_family",
                "provider_candidate",
                "endpoint_family",
                "affected_symbols_or_universe",
                "affected_date_window",
                "incident_type",
                "severity",
                "trigger_summary",
                "evidence_artifact_refs",
                "raw_payload_storage_ref",
                "secret_scan_status",
                "immediate_action",
                "production_use_blocked",
                "fallback_execution_performed",
                "provider_calls_performed_by_log_contract",
                "status_page_polled_by_log_contract",
                "manual_review_owner",
                "review_status",
                "disposition",
                "replay_or_revalidation_requirement",
                "scope_locks",
            },
        )
        for field_name, field in fields.items():
            with self.subTest(field_name=field_name):
                self.assertTrue(field["required_for_record"])
                self.assertFalse(field["secret_or_request_url_allowed"])
                self.assertTrue(field["field_role"])

        self.assertIn("no raw rows", fields["affected_symbols_or_universe"]["field_role"])
        self.assertIn("Must remain false", fields["provider_calls_performed_by_log_contract"]["field_role"])
        self.assertIn("no provider selection", fields["scope_locks"]["field_role"])

    def test_incident_type_mappings_match_playbook_and_remain_default_blocking(self) -> None:
        artifact = self._load_artifact()
        mappings = {item["incident_type"]: item for item in artifact["incident_type_mappings"]}

        self.assertEqual(
            set(mappings),
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
        for incident_type, mapping in mappings.items():
            with self.subTest(incident_type=incident_type):
                self.assertEqual(mapping["incident_type"], mapping["playbook_incident_ref"])
                self.assertIn("record_incident", mapping["required_actions"])
                self.assertGreaterEqual(len(mapping["required_log_field_refs"]), 5)
                self.assertTrue(mapping["blocks_production_use_until_review"])
                self.assertFalse(mapping["authorizes_status_polling"])
                self.assertFalse(mapping["authorizes_provider_selection"])
                self.assertFalse(mapping["authorizes_data_fetch"])
                self.assertFalse(mapping["authorizes_fallback_execution"])
                self.assertFalse(mapping["authorizes_adapter_or_datahub"])
                self.assertFalse(mapping["authorizes_runner_consumption"])
                self.assertFalse(mapping["authorizes_phase7c"])

        self.assertIn(
            "freeze_latest_only_claims",
            mappings["pit_or_observed_date_ambiguity"]["required_actions"],
        )

    def test_storage_review_and_next_steps_keep_contract_design_only(self) -> None:
        artifact = self._load_artifact()
        storage = artifact["storage_and_retention_policy"]
        review = artifact["review_and_replay_policy"]
        source_ids = {item["artifact_id"] for item in artifact["source_artifact_refs"]}
        joined_limits = "\n".join(artifact["limitations"])
        joined_next = "\n".join(artifact["next_steps"])

        self.assertIn("p1_fallback_incident_stability_playbook_20260602", source_ids)
        self.assertIn("p1_remaining_blocker_plan_20260602", source_ids)
        self.assertFalse(storage["logs_created_by_this_artifact"])
        self.assertFalse(storage["local_storage_rights_resolved"])
        self.assertFalse(storage["retention_rights_resolved"])
        self.assertFalse(storage["request_urls_allowed_in_tracked_files"])
        self.assertFalse(storage["secrets_allowed_in_tracked_files"])
        self.assertFalse(storage["authorizes_storage_or_retention"])
        self.assertTrue(storage["raw_payloads_must_be_gitignored"])
        self.assertFalse(review["automatic_replay_allowed"])
        self.assertFalse(review["provider_status_polling_allowed"])
        self.assertFalse(review["provider_data_rerun_allowed_by_contract"])
        self.assertFalse(review["fallback_execution_allowed_by_contract"])
        self.assertIn("creates no logs", joined_limits)
        self.assertIn("not storage authorization", joined_limits)
        self.assertIn("Keep SR-PROVIDER-001 open", joined_next)
        self.assertIn("log writer", joined_next)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["incident_log_write_implemented"] = True
        invalid["scope"]["provider_status_polling_allowed"] = True
        invalid["scope"]["data_fetch_allowed"] = True
        invalid["incident_log_contract"]["authorizes_log_writer"] = True
        invalid["storage_and_retention_policy"]["secrets_allowed_in_tracked_files"] = True
        invalid["incident_type_mappings"][0]["authorizes_fallback_execution"] = True
        invalid["prohibited_actions"]["incident_log_writer_implementation"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
