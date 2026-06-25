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

SCHEMA_PATH = Path("schemas/us_short_batch5_fallback_incident_stability_binding.schema.json")
ARTIFACT_PATH = Path("docs/us_short_batch5_fallback_incident_stability_binding_20260625.json")


class UsShortBatch5FallbackIncidentStabilityBindingSchemaTest(unittest.TestCase):
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
            "us_short_batch5_fallback_incident_stability_binding",
        )
        self.assertIn("US-short batch5", schema["description"])
        self.assertIn("does not poll", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        self.assertEqual(self._validate(self._load_artifact()), [])

    def test_scope_is_offline_default_deny_binding(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["market"], "US")
        self.assertEqual(scope["lane"], "us_short")
        self.assertEqual(scope["batch"], "batch5_provider_live")
        self.assertEqual(scope["artifact_status"], "fallback_incident_stability_binding_offline_only")
        self.assertTrue(scope["binds_existing_p1_playbook"])
        self.assertTrue(scope["default_deny_binding"])
        for field in [
            "provider_calls_executed_by_this_artifact",
            "network_access_required_for_this_artifact",
            "provider_status_polling_allowed",
            "fallback_execution_allowed",
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

    def test_source_refs_and_binding_trace_are_locked(self) -> None:
        artifact = self._load_artifact()
        refs = {row["artifact_id"]: row for row in artifact["source_artifact_refs"]}
        trace = artifact["binding_trace"]

        for ref_id in [
            "us_short_system_design",
            "us_short_batch5_provider_live_post_probe_disposition_20260625",
            "provider_p1_fallback_incident_stability_playbook_20260602",
            "provider_p1_incident_log_contract_20260602",
            "sr_provider_001",
        ]:
            self.assertIn(ref_id, refs)

        self.assertEqual(
            trace["post_probe_disposition_ref"],
            "docs/us_short_batch5_provider_live_post_probe_disposition_20260625.json",
        )
        self.assertEqual(
            trace["p1_playbook_ref"],
            "docs/provider_evidence_p1_us_fallback_incident_stability_playbook_20260602.json",
        )
        self.assertEqual(trace["p1_playbook_status"], "schema_first_design_no_provider_calls")
        self.assertEqual(trace["binding_mode"], "batch5_default_deny_contract")
        self.assertTrue(trace["response_shape_probe_remains_non_production"])
        self.assertFalse(trace["authorizes_provider_status_polling"])
        self.assertFalse(trace["authorizes_fallback_execution"])
        self.assertFalse(trace["authorizes_datahub_or_runner_consumption"])

    def test_field_family_bindings_keep_no_fetch_no_consumption(self) -> None:
        bindings = {
            row["family_id"]: row
            for row in self._load_artifact()["field_family_bindings"]
        }

        self.assertEqual(
            set(bindings),
            {
                "fundamentals",
                "price_volume_liquidity",
                "corporate_actions",
                "security_master_coverage",
                "sec_edgar_audit",
                "benchmark_gics",
            },
        )
        for binding in bindings.values():
            self.assertEqual(binding["binding_status"], "bound_to_default_deny_playbook")
            self.assertFalse(binding["authorizes_provider_call_now"], binding)
            self.assertFalse(binding["authorizes_data_fetch"], binding)
            self.assertFalse(binding["authorizes_adapter_or_datahub"], binding)
            self.assertFalse(binding["authorizes_runner_consumption"], binding)
            self.assertFalse(binding["authorizes_provider_selection"], binding)
            self.assertFalse(binding["silent_default_allowed"], binding)
            self.assertFalse(binding["zero_fill_allowed"], binding)
            self.assertFalse(binding["latest_only_backfill_allowed"], binding)

    def test_incident_bindings_keep_execution_blocked_until_review(self) -> None:
        incidents = {
            row["incident_id"]: row
            for row in self._load_artifact()["incident_bindings"]
        }

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
        for incident in incidents.values():
            self.assertTrue(incident["requires_incident_log"], incident)
            self.assertFalse(incident["production_use_allowed_until_review"], incident)
            self.assertFalse(incident["fallback_may_be_used_without_new_data"], incident)
            self.assertFalse(incident["authorizes_status_polling"], incident)
            self.assertFalse(incident["authorizes_data_fetch"], incident)
            self.assertFalse(incident["authorizes_adapter_or_datahub"], incident)
            self.assertFalse(incident["authorizes_runner_consumption"], incident)

    def test_drift_monitor_bindings_do_not_poll_or_fetch(self) -> None:
        dimensions = {
            row["dimension"]: row
            for row in self._load_artifact()["drift_monitor_bindings"]
        }

        self.assertEqual(
            set(dimensions),
            {
                "coverage_count",
                "freshness_latency",
                "schema_or_field_semantics",
                "pit_as_of_integrity",
                "corporate_action_revision",
                "authorization_cost_quota",
                "provider_incident",
                "outlier_revision_rate",
            },
        )
        for binding in dimensions.values():
            self.assertEqual(binding["binding_status"], "design_binding_only_not_runtime_monitor")
            self.assertFalse(binding["authorizes_status_polling"], binding)
            self.assertFalse(binding["authorizes_data_fetch"], binding)
            self.assertFalse(binding["authorizes_datahub_or_runner_consumption"], binding)

    def test_scope_creep_is_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_status_polling_allowed"] = True
        invalid["scope"]["fallback_execution_allowed"] = True
        invalid["scope"]["datahub_consumption_allowed"] = True
        invalid["binding_trace"]["authorizes_fallback_execution"] = True
        invalid["prohibited_actions"]["ship_gate_or_live_normalized_evidence_authorized"] = True

        self.assertNotEqual(self._validate(invalid), [])

    def test_missing_required_binding_rows_are_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["field_family_bindings"].pop()
        invalid["field_family_bindings"].append(copy.deepcopy(invalid["field_family_bindings"][0]))
        invalid["incident_bindings"].pop()
        invalid["incident_bindings"].append(copy.deepcopy(invalid["incident_bindings"][0]))
        invalid["drift_monitor_bindings"].pop()
        invalid["drift_monitor_bindings"].append(copy.deepcopy(invalid["drift_monitor_bindings"][0]))

        self.assertNotEqual(self._validate(invalid), [])

    def test_runtime_execution_mutants_are_rejected_when_jsonschema_available(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["field_family_bindings"][0]["authorizes_data_fetch"] = True
        invalid["incident_bindings"][0]["production_use_allowed_until_review"] = True
        invalid["drift_monitor_bindings"][0]["authorizes_status_polling"] = True
        invalid["implementation_gates"][0]["authorizes_implementation_now"] = True

        self.assertNotEqual(self._validate(invalid), [])


if __name__ == "__main__":
    unittest.main()
