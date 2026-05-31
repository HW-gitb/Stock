from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/research_preregistration.schema.json")
ARTIFACT_PATH = Path("research/preregistrations/a_share_minimal_data_burst_20260531.json")
ALPHA_AUDIT_SCHEMA_PATH = Path("schemas/alpha_plausibility_audit.schema.json")
EVIDENCE_REPORT_SCHEMA_PATH = Path("schemas/evidence_report.schema.json")


class ResearchPreregistrationSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_artifact(self) -> dict:
        return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "research_preregistration")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("one frozen research-only test", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        errors = list(Draft7Validator(self._load_schema()).iter_errors(self._load_artifact()))

        self.assertEqual(errors, [])

    def test_hypothesis_registration_reuses_alpha_audit_shape(self) -> None:
        schema = self._load_schema()
        alpha_schema = json.loads(ALPHA_AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            schema["$defs"]["hypothesisRegistration"]["required"],
            alpha_schema["$defs"]["hypothesisRegistration"]["required"],
        )
        self.assertEqual(
            set(self._load_artifact()["hypothesis_registration"]),
            set(alpha_schema["$defs"]["hypothesisRegistration"]["required"]),
        )

    def test_scope_locks_research_out_of_production_provider_and_phase7c(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertEqual(scope["purpose"], "single_frozen_test_research_preregistration")
        self.assertEqual(scope["lane_id"], "a_share_burst_minimal_data")
        self.assertEqual(scope["registration_status"], "registered_not_run")
        self.assertEqual(scope["research_status"], "research_only_not_run")
        self.assertTrue(scope["manual_order_only"])
        for field_name in {
            "production_use_allowed",
            "direct_production_feed_allowed",
            "provider_selection_allowed",
            "provider_contact_or_account_creation_allowed",
            "trial_or_token_request_allowed",
            "paid_access_approved",
            "sample_row_collection_allowed",
            "provider_data_fetch_allowed",
            "new_data_fetch_allowed_by_this_artifact",
            "provider_adapter_allowed",
            "datahub_table_implementation_allowed",
            "runner_change_allowed",
            "production_strategy_rule_change_allowed",
            "broker_or_order_automation_allowed",
            "ship_gate_claim_allowed",
            "live_trading_or_minimal_live_allowed",
            "phase7c_authorized_by_this_artifact",
        }:
            with self.subTest(field_name=field_name):
                self.assertFalse(scope[field_name])

    def test_single_frozen_test_design_and_budget_are_locked(self) -> None:
        artifact = self._load_artifact()
        freeze = artifact["frozen_test_design"]["freeze_controls"]
        budget = artifact["test_budget"]
        entry_exit = artifact["frozen_test_design"]["entry_exit_rule"]
        benchmark = artifact["frozen_test_design"]["benchmark_rule"]

        self.assertTrue(all(value is True for key, value in freeze.items() if key.endswith("_frozen")))
        self.assertFalse(freeze["parameter_search_allowed"])
        self.assertFalse(freeze["variant_search_allowed"])
        self.assertFalse(freeze["benchmark_sweep_allowed"])
        self.assertFalse(freeze["holding_period_sweep_allowed"])
        self.assertEqual(entry_exit["holding_period_trading_days"], 5)
        self.assertEqual(benchmark["primary_benchmark_id"], "CSI1000")
        self.assertEqual(benchmark["primary_benchmark_role"], "promotion_relevant_single_test")
        self.assertTrue(all(not item["promotion_relevant"] for item in benchmark["secondary_diagnostics"]))
        self.assertEqual(budget["promotion_relevant_tests_allowed"], 1)
        self.assertFalse(budget["program_level_ledger_required_before_run"])
        self.assertIsNone(budget["program_level_ledger_ref"])
        self.assertIn("research_experiment_log.hypothesis_registration_ref", budget["evidence_report_linkage"]["future_evidence_report_field"])

    def test_thresholds_define_one_research_continuation_gate(self) -> None:
        artifact = self._load_artifact()
        threshold = artifact["frozen_test_design"]["evaluation_threshold"]
        criteria = {item["metric"]: item for item in threshold["criteria"]}

        self.assertEqual(threshold["decision_label_if_all_pass"], "research_continue_only")
        self.assertEqual(threshold["decision_label_if_any_fail"], "falsified_or_redesign_required")
        self.assertEqual(criteria["valid_signal_events"]["operator"], ">=")
        self.assertEqual(criteria["valid_signal_events"]["threshold_value"], 30)
        self.assertEqual(criteria["monthly_clustered_t_stat_net_excess_csi1000_5d"]["operator"], ">=")
        self.assertEqual(criteria["monthly_clustered_t_stat_net_excess_csi1000_5d"]["threshold_value"], 1.5)
        self.assertEqual(criteria["entry_unbuyable_rate"]["operator"], "<=")
        self.assertEqual(criteria["entry_unbuyable_rate"]["threshold_value"], 0.25)

    def test_evidence_report_linkage_uses_existing_ref_without_schema_extension(self) -> None:
        artifact = self._load_artifact()
        evidence_report_schema = json.loads(EVIDENCE_REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
        research_log_props = evidence_report_schema["$defs"]["researchExperimentLog"]["properties"]

        self.assertIn("hypothesis_registration_ref", research_log_props)
        self.assertNotIn("program_test_budget", research_log_props)
        self.assertNotIn("tests_spent", research_log_props)
        self.assertFalse(artifact["test_budget"]["evidence_report_linkage"]["add_fields_to_evidence_report_schema_allowed"])

    def test_in_sample_research_registers_confirmation_path(self) -> None:
        artifact = self._load_artifact()
        next_steps = "\n".join(artifact["next_steps"]).lower()

        self.assertEqual(artifact["evidence_integrity_plan"]["evidence_window_type"], "in_sample")
        self.assertIn("separate confirmation path", next_steps)
        self.assertIn("2026+ held-out / forward cohorts", next_steps)
        self.assertIn("12 months live-normalized forward evidence", next_steps)
        self.assertIn("does not authorize promotion without that confirmation", next_steps)

    def test_ledger_trigger_is_singleton_program_level_not_per_hypothesis(self) -> None:
        trigger = self._load_artifact()["ledger_trigger"]

        self.assertFalse(trigger["program_level_ledger_required_now"])
        self.assertEqual(trigger["ledger_cardinality_if_triggered"], "singleton_program_level")
        self.assertTrue(
            any("threshold" in item.lower() for item in trigger["trigger_events"])
        )
        self.assertTrue(
            any("benchmark" in item.lower() for item in trigger["trigger_events"])
        )

    def test_authorization_or_fishing_mutation_is_rejected_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["production_use_allowed"] = True
        invalid["scope"]["provider_data_fetch_allowed"] = True
        invalid["frozen_test_design"]["freeze_controls"]["parameter_search_allowed"] = True
        invalid["test_budget"]["promotion_relevant_tests_allowed"] = 2
        invalid["test_budget"]["program_level_ledger_required_before_run"] = True
        invalid["promotion_boundary"]["ship_gate_evidence_claim_allowed"] = True

        errors = list(Draft7Validator(self._load_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
