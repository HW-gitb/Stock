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

SCHEMA_PATH = Path("schemas/us_short_batch5_incident_log_storage_contract.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_incident_log_storage_contract_20260625.json")

EXPECTED_INCIDENT_MAPPINGS = {
    "quota_or_rate_limit": {
        "default_severity": "production_blocker",
        "required_actions": [
            "record_incident",
            "block_production_use",
            "fallback_path_review",
        ],
    },
    "http_5xx_or_provider_outage": {
        "default_severity": "production_blocker",
        "required_actions": [
            "record_incident",
            "block_production_use",
            "manual_review",
        ],
    },
    "http_401_403_auth_scope": {
        "default_severity": "evidence_blocker",
        "required_actions": [
            "record_incident",
            "manual_review",
            "fallback_path_review",
        ],
    },
    "schema_or_field_semantics_drift": {
        "default_severity": "production_blocker",
        "required_actions": [
            "record_incident",
            "manual_review",
            "rerun_provider_evidence",
        ],
    },
    "stale_or_missing_rows": {
        "default_severity": "production_blocker",
        "required_actions": [
            "record_incident",
            "block_production_use",
            "fallback_path_review",
        ],
    },
    "pit_or_observed_date_ambiguity": {
        "default_severity": "evidence_blocker",
        "required_actions": [
            "record_incident",
            "freeze_latest_only_claims",
            "manual_review",
        ],
    },
    "corporate_action_adjustment_conflict": {
        "default_severity": "evidence_blocker",
        "required_actions": [
            "record_incident",
            "manual_review",
            "rerun_provider_evidence",
        ],
    },
    "sec_edgar_audit_conflict": {
        "default_severity": "evidence_blocker",
        "required_actions": [
            "record_incident",
            "manual_review",
            "use_reviewed_audit_source_only",
        ],
    },
}


class UsShortBatch5IncidentLogStorageContractSchemaTest(unittest.TestCase):
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
            "us_short_batch5_incident_log_storage_contract",
        )
        self.assertIn("US-short batch5", schema["description"])
        self.assertIn("does not implement a writer", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_is_offline_no_access_no_execution(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["market"], "US")
        self.assertEqual(scope["lane"], "us_short")
        self.assertEqual(scope["batch"], "batch5_provider_live")
        self.assertEqual(scope["artifact_status"], "incident_log_storage_contract_offline_only")
        for field in [
            "provider_calls_executed_by_this_artifact",
            "network_access_required_for_this_artifact",
            "provider_status_polling_allowed",
            "fallback_execution_allowed",
            "incident_log_writer_implemented",
            "runtime_incident_records_created",
            "runtime_log_storage_created",
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
            "yfinance_allowed",
            "web_x_allowed",
            "broker_or_order_automation_allowed",
        ]:
            self.assertFalse(scope[field], field)

    def test_source_refs_and_trace_are_locked(self) -> None:
        artifact = self._load_artifact()
        refs = {row["artifact_id"]: row for row in artifact["source_artifact_refs"]}
        trace = artifact["contract_trace"]

        for ref_id in [
            "us_short_system_design",
            "us_short_batch5_fallback_incident_stability_binding_20260625",
            "provider_p1_incident_log_contract_20260602",
            "provider_p1_fallback_incident_stability_playbook_20260602",
            "sr_provider_001",
        ]:
            self.assertIn(ref_id, refs)

        self.assertEqual(
            trace["fallback_binding_ref"],
            "docs/us_short_batch5_fallback_incident_stability_binding_20260625.json",
        )
        self.assertEqual(
            trace["p1_incident_log_contract_ref"],
            "docs/provider_evidence_p1_us_incident_log_contract_20260602.json",
        )
        self.assertEqual(trace["contract_mode"], "batch5_no_access_storage_contract")
        self.assertFalse(trace["authorizes_writer"])
        self.assertFalse(trace["authorizes_runtime_storage"])
        self.assertFalse(trace["authorizes_provider_status_polling"])
        self.assertFalse(trace["authorizes_fallback_execution"])
        self.assertFalse(trace["authorizes_datahub_or_runner_consumption"])

    def test_storage_contract_uses_gitignored_us_short_private_root_only(self) -> None:
        storage = self._load_artifact()["storage_contract"]

        self.assertEqual(
            storage["future_private_incident_log_root"],
            "state/us_short/runs_private/provider_incidents/",
        )
        self.assertEqual(
            storage["future_private_incident_log_pattern"],
            "state/us_short/runs_private/provider_incidents/<YYYYMMDD>/incident_log.jsonl",
        )
        self.assertEqual(
            storage["future_private_summary_pattern"],
            "state/us_short/runs_private/provider_incidents/<YYYYMMDD>/incident_summary.json",
        )
        self.assertEqual(
            storage["future_raw_payload_root"],
            "provider_samples/us_short_batch5_provider_incidents/",
        )
        self.assertTrue(storage["future_paths_must_be_gitignored"])
        self.assertFalse(storage["paths_created_by_this_artifact"])
        self.assertFalse(storage["authorizes_runtime_write"])
        self.assertFalse(storage["authorizes_production_storage"])
        self.assertFalse(storage["request_urls_allowed_in_tracked_files"])
        self.assertFalse(storage["secrets_allowed_in_tracked_files"])
        self.assertFalse(storage["raw_rows_allowed_in_tracked_files"])
        self.assertTrue(storage["tracked_docs_are_contract_only"])

    def test_record_contract_and_incident_mappings_remain_default_blocking(self) -> None:
        artifact = self._load_artifact()
        fields = {row["field_name"]: row for row in artifact["record_contract"]["required_fields"]}
        mappings = {row["incident_type"]: row for row in artifact["incident_type_mappings"]}

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
        for field in fields.values():
            self.assertTrue(field["required_for_future_record"])
            self.assertFalse(field["secret_or_request_url_allowed"])
            self.assertFalse(field["raw_payload_allowed"])

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
        for mapping in mappings.values():
            self.assertEqual(mapping["storage_status"], "future_private_record_only")
            self.assertIn("record_incident", mapping["required_actions"])
            self.assertTrue(mapping["blocks_production_use_until_review"])
            self.assertFalse(mapping["authorizes_status_polling"])
            self.assertFalse(mapping["authorizes_data_fetch"])
            self.assertFalse(mapping["authorizes_fallback_execution"])
            self.assertFalse(mapping["authorizes_adapter_or_datahub"])
            self.assertFalse(mapping["authorizes_runner_consumption"])
            self.assertFalse(mapping["authorizes_ship_gate_or_live_normalized_evidence"])

    def test_incident_mappings_match_p1_owner_contract_exactly(self) -> None:
        mappings = {
            row["incident_type"]: row
            for row in self._load_artifact()["incident_type_mappings"]
        }

        self.assertEqual(set(mappings), set(EXPECTED_INCIDENT_MAPPINGS))
        for incident_type, expected in EXPECTED_INCIDENT_MAPPINGS.items():
            with self.subTest(incident_type=incident_type):
                mapping = mappings[incident_type]
                self.assertEqual(mapping["source_binding_incident_ref"], incident_type)
                self.assertEqual(mapping["default_severity"], expected["default_severity"])
                self.assertEqual(mapping["required_actions"], expected["required_actions"])

    def test_implementation_gates_and_prohibited_actions_stay_blocked(self) -> None:
        artifact = self._load_artifact()
        gates = {row["gate_id"]: row for row in artifact["implementation_gates"]}

        for gate_id in [
            "incident_log_writer_requires_separate_review",
            "runtime_storage_creation_requires_separate_review",
            "provider_status_polling_separate_authorization",
            "fallback_execution_separate_authorization",
            "datahub_runner_consumption_blocked",
            "production_storage_blocked",
            "live_normalized_ship_gate_blocked",
            "future_provider_live_probe_separate_authorization",
        ]:
            self.assertIn(gate_id, gates)

        for gate in gates.values():
            self.assertFalse(gate["authorizes_implementation_now"], gate)
            self.assertFalse(gate["authorizes_provider_live_or_network"], gate)
            self.assertFalse(gate["authorizes_datahub_or_runner"], gate)

        for value in artifact["prohibited_actions"].values():
            self.assertFalse(value)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["incident_log_writer_implemented"] = True
        invalid["scope"]["provider_status_polling_allowed"] = True
        invalid["storage_contract"]["authorizes_runtime_write"] = True
        invalid["incident_type_mappings"][0]["authorizes_fallback_execution"] = True
        invalid["prohibited_actions"]["ship_gate_or_live_normalized_evidence_authorized"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_missing_required_record_or_incident_rows_are_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["record_contract"]["required_fields"].pop()
        invalid["record_contract"]["required_fields"].append(
            copy.deepcopy(invalid["record_contract"]["required_fields"][0])
        )
        invalid["incident_type_mappings"].pop()
        invalid["incident_type_mappings"].append(copy.deepcopy(invalid["incident_type_mappings"][0]))

        self.assertNotEqual(self._validate(invalid), [])

    def test_private_path_and_raw_leak_mutants_are_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["storage_contract"]["future_private_incident_log_root"] = "logs/provider_incidents/"
        invalid["storage_contract"]["request_urls_allowed_in_tracked_files"] = True
        invalid["record_contract"]["required_fields"][0]["raw_payload_allowed"] = True
        invalid["record_contract"]["tracked_record_policy"]["raw_payload_fields_allowed"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_incident_mapping_traceback_mutants_are_rejected_when_jsonschema_available(self) -> None:
        for field, value in [
            ("source_binding_incident_ref", "sec_edgar_audit_conflict"),
            ("default_severity", "warning_only"),
            ("required_actions", ["record_incident", "foo"]),
        ]:
            with self.subTest(field=field):
                invalid = copy.deepcopy(self._load_artifact())
                invalid["incident_type_mappings"][0][field] = value

                self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
