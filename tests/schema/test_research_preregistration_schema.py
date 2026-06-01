from __future__ import annotations

import copy
import csv
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/research_preregistration.schema.json")
PREFLIGHT_SCHEMA_PATH = Path("schemas/research_preflight_result.schema.json")
LEDGER_SCHEMA_PATH = Path("schemas/program_test_budget_ledger.schema.json")
BLOCKED_ARTIFACT_PATH = Path("research/preregistrations/a_share_minimal_data_burst_20260531.json")
CORRECTED_ARTIFACT_PATH = Path("research/preregistrations/a_share_minimal_data_burst_corrected_basis_20260531.json")
REDESIGNED_ARTIFACT_PATH = Path(
    "research/preregistrations/a_share_minimal_data_burst_full_universe_redesign_20260531.json"
)
PREFLIGHT_ARTIFACT_PATH = Path(
    "research/results/a_share_minimal_data_burst_corrected_basis_20260531/preflight_zero_signal_events_20260531.json"
)
REDESIGNED_PREFLIGHT_ARTIFACT_PATH = Path(
    "research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/preflight_event_count_20260531.json"
)
REDESIGNED_EVIDENCE_REPORT_PATH = Path(
    "research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json"
)
REDESIGNED_SIGNAL_EVENTS_PATH = Path(
    "research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/signal_events.csv"
)
REDESIGNED_MONTHLY_STATS_PATH = Path(
    "research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/monthly_stats.csv"
)
LEDGER_ARTIFACT_PATH = Path("research/ledgers/a_share_burst_program_test_budget_ledger_20260531.json")
ALPHA_AUDIT_SCHEMA_PATH = Path("schemas/alpha_plausibility_audit.schema.json")
EVIDENCE_REPORT_SCHEMA_PATH = Path("schemas/evidence_report.schema.json")


class ResearchPreregistrationSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_preflight_schema(self) -> dict:
        return json.loads(PREFLIGHT_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_ledger_schema(self) -> dict:
        return json.loads(LEDGER_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_evidence_report_schema(self) -> dict:
        return json.loads(EVIDENCE_REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_artifact(self, path: Path = BLOCKED_ARTIFACT_PATH) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_corrected_artifact(self) -> dict:
        return self._load_artifact(CORRECTED_ARTIFACT_PATH)

    def _load_preflight_artifact(self) -> dict:
        return self._load_artifact(PREFLIGHT_ARTIFACT_PATH)

    def _load_redesigned_preflight_artifact(self) -> dict:
        return self._load_artifact(REDESIGNED_PREFLIGHT_ARTIFACT_PATH)

    def _load_ledger_artifact(self) -> dict:
        return self._load_artifact(LEDGER_ARTIFACT_PATH)

    def _load_redesigned_evidence_report(self) -> dict:
        return self._load_artifact(REDESIGNED_EVIDENCE_REPORT_PATH)

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "research_preregistration")
        self.assertEqual(schema["properties"]["schema_version"]["enum"], ["1.0.0", "1.1.0"])
        self.assertIn("one frozen research-only test", schema["description"])
        self.assertIn("gated by an existing singleton program-level test-budget ledger", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_artifact_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        validator = Draft7Validator(self._load_schema())
        for artifact_path in [BLOCKED_ARTIFACT_PATH, CORRECTED_ARTIFACT_PATH, REDESIGNED_ARTIFACT_PATH]:
            with self.subTest(artifact_path=str(artifact_path)):
                errors = list(validator.iter_errors(self._load_artifact(artifact_path)))
                self.assertEqual(errors, [])

    def test_preflight_result_schema_and_artifact_validate_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_preflight_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "research_preflight_result")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertFalse(schema["additionalProperties"])

        validator = Draft7Validator(schema)
        for artifact in [self._load_preflight_artifact(), self._load_redesigned_preflight_artifact()]:
            with self.subTest(artifact_id=artifact["artifact_id"]):
                errors = list(validator.iter_errors(artifact))
                self.assertEqual(errors, [])

    def test_program_test_budget_ledger_schema_and_artifact_validate_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_ledger_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "program_test_budget_ledger")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertFalse(schema["additionalProperties"])

        errors = list(Draft7Validator(schema).iter_errors(self._load_ledger_artifact()))
        self.assertEqual(errors, [])

    def test_hypothesis_registration_reuses_alpha_audit_shape(self) -> None:
        schema = self._load_schema()
        alpha_schema = json.loads(ALPHA_AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            schema["$defs"]["hypothesisRegistration"]["required"],
            alpha_schema["$defs"]["hypothesisRegistration"]["required"],
        )
        for artifact_path in [BLOCKED_ARTIFACT_PATH, CORRECTED_ARTIFACT_PATH, REDESIGNED_ARTIFACT_PATH]:
            with self.subTest(artifact_path=str(artifact_path)):
                self.assertEqual(
                    set(self._load_artifact(artifact_path)["hypothesis_registration"]),
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

    def test_current_preregistration_is_blocked_until_corrected_basis_supersession(self) -> None:
        artifact = self._load_artifact()
        joined_notes = "\n".join(artifact["next_steps"] + artifact["limitations"])

        self.assertIn("BLOCKED_DO_NOT_RUN", joined_notes)
        self.assertIn("measurement-basis issue", joined_notes)
        self.assertIn("corrected-basis superseding preregistration", joined_notes)
        self.assertIn("not executable as promotion-relevant research-continuation evidence", joined_notes)

    def test_corrected_basis_preregistration_records_zero_event_preflight(self) -> None:
        artifact = self._load_corrected_artifact()
        joined_notes = "\n".join(artifact["next_steps"] + artifact["limitations"])
        benchmark_rule = artifact["frozen_test_design"]["benchmark_rule"]["benchmark_return_rule"]

        self.assertNotIn("BLOCKED_DO_NOT_RUN", joined_notes)
        self.assertIn("T+1 entry date open", benchmark_rule)
        self.assertIn("T+5 exit date close", benchmark_rule)
        self.assertIn("valid_signal_events = 0", joined_notes)
        self.assertIn("preflight_zero_signal_events_20260531.json", joined_notes)
        self.assertIn("a_share_burst_program_test_budget_ledger_20260531.json", joined_notes)
        self.assertIn("Do not run outcome / benchmark-excess calculation", joined_notes)
        self.assertEqual(
            artifact["test_budget"]["evidence_report_linkage"]["future_ref_value"],
            str(CORRECTED_ARTIFACT_PATH).replace("\\", "/"),
        )

    def test_corrected_basis_preflight_records_zero_valid_events(self) -> None:
        preflight = self._load_preflight_artifact()

        self.assertEqual(preflight["hypothesis_registration_ref"], str(CORRECTED_ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(preflight["preflight_status"], "failed_underpowered_zero_signal_events")
        self.assertFalse(preflight["execution_boundary"]["outcome_returns_computed"])
        self.assertFalse(preflight["execution_boundary"]["benchmark_excess_computed"])
        self.assertFalse(preflight["execution_boundary"]["provider_data_fetch_performed"])
        self.assertEqual(preflight["summary_counts"]["cohort_count"], 24)
        self.assertEqual(preflight["summary_counts"]["total_candidate_rows"], 360)
        self.assertEqual(preflight["summary_counts"]["tier1_rows"], 305)
        self.assertEqual(preflight["summary_counts"]["hard_filter_rows"], 301)
        self.assertEqual(preflight["summary_counts"]["hard_pct_5d_ge_6_rows"], 17)
        self.assertEqual(preflight["summary_counts"]["hard_amount_ratio_ge_1_5_rows"], 38)
        self.assertEqual(preflight["summary_counts"]["hard_is_breakout_true_rows"], 7)
        self.assertEqual(preflight["summary_counts"]["hard_all_three_signal_rows"], 0)
        self.assertEqual(preflight["evaluation_result"]["valid_signal_events"], 0)
        self.assertEqual(preflight["evaluation_result"]["minimum_effective_sample_required"], 30)
        self.assertFalse(preflight["evaluation_result"]["valid_signal_events_gate_passed"])
        self.assertFalse(preflight["evaluation_result"]["outcome_run_allowed_for_this_preregistration"])

    def test_redesigned_preflight_records_event_count_pass_without_outcome(self) -> None:
        preflight = self._load_redesigned_preflight_artifact()

        self.assertEqual(preflight["hypothesis_registration_ref"], str(REDESIGNED_ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(preflight["preflight_status"], "passed_event_count_preflight")
        self.assertEqual(preflight["decision"], "eligible_for_separate_outcome_run_after_review")
        self.assertFalse(preflight["execution_boundary"]["outcome_returns_computed"])
        self.assertFalse(preflight["execution_boundary"]["benchmark_excess_computed"])
        self.assertFalse(preflight["execution_boundary"]["provider_data_fetch_performed"])
        self.assertFalse(preflight["execution_boundary"]["egs_main_rerun_performed"])
        self.assertFalse(preflight["execution_boundary"]["cohort_regeneration_performed"])
        self.assertEqual(preflight["summary_counts"]["cohort_count"], 24)
        self.assertEqual(preflight["summary_counts"]["total_candidate_rows"], 19000)
        self.assertEqual(preflight["summary_counts"]["tier1_rows"], 967)
        self.assertEqual(preflight["summary_counts"]["tier2_rows"], 5326)
        self.assertEqual(preflight["summary_counts"]["hard_filter_rows"], 6159)
        self.assertEqual(preflight["summary_counts"]["hard_pct_5d_ge_6_rows"], 1635)
        self.assertEqual(preflight["summary_counts"]["hard_amount_ratio_ge_1_5_rows"], 1291)
        self.assertEqual(preflight["summary_counts"]["hard_is_breakout_true_rows"], 511)
        self.assertEqual(preflight["summary_counts"]["hard_all_three_signal_rows"], 134)
        self.assertEqual(preflight["evaluation_result"]["valid_signal_events"], 134)
        self.assertEqual(preflight["evaluation_result"]["minimum_effective_sample_required"], 30)
        self.assertTrue(preflight["evaluation_result"]["valid_signal_events_gate_passed"])
        self.assertFalse(preflight["evaluation_result"]["alpha_claim_allowed"])
        self.assertFalse(preflight["evaluation_result"]["outcome_run_allowed_for_this_preregistration"])
        self.assertIn("SR-DATA-003", "\n".join(preflight["diagnostic_notes"]))

    def test_redesigned_evidence_report_records_failed_outcome_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        report = self._load_redesigned_evidence_report()
        errors = list(Draft7Validator(self._load_evidence_report_schema()).iter_errors(report))

        self.assertEqual(errors, [])
        self.assertEqual(report["report_id"], "a_share_minimal_data_burst_full_universe_redesign_evidence_20260601")
        self.assertEqual(report["lane_id"], "a_share_burst_minimal_data")
        self.assertEqual(report["evidence_level"], "research_only")
        self.assertFalse(report["scope"]["data_fetch_allowed"])
        self.assertFalse(report["scope"]["strategy_rule_change_allowed"])
        self.assertEqual(
            report["research_experiment_log"]["hypothesis_registration_ref"],
            str(REDESIGNED_ARTIFACT_PATH).replace("\\", "/"),
        )
        self.assertEqual(
            report["research_experiment_log"]["production_promotion"]["promotion_status"],
            "blocked",
        )
        self.assertEqual(report["ship_gate_claim"]["claim_status"], "not_eligible")
        self.assertIn("falsified_or_redesign_required", report["research_experiment_log"]["result_summary"])
        self.assertAlmostEqual(report["cost_adjusted_return"]["net_excess_return_pct"], -2.8696001309, places=10)
        self.assertIn(
            "research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/signal_events.csv",
            report["research_experiment_log"]["reproducibility_artifacts"],
        )

    def test_redesigned_outcome_csvs_match_registered_evidence_report_counts(self) -> None:
        with REDESIGNED_SIGNAL_EVENTS_PATH.open(encoding="utf-8", newline="") as fh:
            signal_rows = list(csv.DictReader(fh))
        with REDESIGNED_MONTHLY_STATS_PATH.open(encoding="utf-8", newline="") as fh:
            monthly_rows = list(csv.DictReader(fh))
        selected_rows = [row for row in signal_rows if row["portfolio_selected"] == "True"]

        self.assertEqual(len(signal_rows), 134)
        self.assertEqual(len(monthly_rows), 24)
        self.assertIn("pending_count", monthly_rows[0])
        self.assertNotIn("other_pending_count", monthly_rows[0])
        self.assertEqual(len(selected_rows), 123)
        self.assertEqual(sum(row["ret_5d_status"] == "ok" for row in selected_rows), 116)
        self.assertEqual(sum(row["ret_5d_status"] == "pending_no_entry_limit_up" for row in selected_rows), 6)
        self.assertEqual(sum(row["ret_5d_status"] == "pending_missing_future_close" for row in selected_rows), 1)
        self.assertEqual(sum(int(row["raw_signal_events"]) for row in monthly_rows), 134)
        self.assertEqual(sum(int(row["selected_signal_events"]) for row in monthly_rows), 123)
        self.assertEqual(sum(int(row["available_count"]) for row in monthly_rows), 116)

    def test_preflight_schema_rejects_outcome_fetch_or_ship_gate_scope_creep_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_preflight_artifact())
        invalid["execution_boundary"]["outcome_returns_computed"] = True
        invalid["execution_boundary"]["benchmark_excess_computed"] = True
        invalid["execution_boundary"]["provider_data_fetch_performed"] = True
        invalid["execution_boundary"]["ship_gate_claim_allowed"] = True
        invalid["evaluation_result"]["alpha_claim_allowed"] = True

        errors = list(Draft7Validator(self._load_preflight_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])

    def test_preflight_schema_allows_negative_pct_max_but_keeps_amount_ratio_nonnegative(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        validator = Draft7Validator(self._load_preflight_schema())
        negative_pct = copy.deepcopy(self._load_preflight_artifact())
        negative_pct["summary_counts"]["max_pct_5d_all_rows"] = -0.5
        negative_pct["summary_counts"]["max_pct_5d_tier1"] = -1.25

        self.assertEqual(list(validator.iter_errors(negative_pct)), [])

        negative_amount_ratio = copy.deepcopy(negative_pct)
        negative_amount_ratio["summary_counts"]["max_amount_ratio_all_rows"] = -0.01

        self.assertNotEqual(list(validator.iter_errors(negative_amount_ratio)), [])

    def test_program_level_ledger_records_spent_preflight_and_requires_new_preregistration(self) -> None:
        ledger = self._load_ledger_artifact()

        self.assertEqual(ledger["schema_name"], "program_test_budget_ledger")
        self.assertEqual(ledger["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(ledger["creation_reason"]["triggering_preflight_ref"], str(PREFLIGHT_ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(ledger["creation_reason"]["triggering_preregistration_ref"], str(CORRECTED_ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 2)
        self.assertEqual(ledger["budget_policy"]["tests_available_without_new_review"], 0)
        self.assertTrue(ledger["budget_policy"]["next_test_requires_reviewed_preregistration"])
        self.assertEqual(len(ledger["test_spend_log"]), 2)
        spent = ledger["test_spend_log"][0]
        self.assertEqual(spent["preregistration_ref"], str(CORRECTED_ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(spent["result_ref"], str(PREFLIGHT_ARTIFACT_PATH).replace("\\", "/"))
        self.assertEqual(spent["status"], "spent_failed_preflight_zero_signal_events")
        self.assertEqual(spent["tests_spent"], 1)
        self.assertEqual(ledger["planned_tests"], [])

    def test_ledger_spend_log_points_to_redesigned_failed_outcome(self) -> None:
        ledger = self._load_ledger_artifact()
        spent = ledger["test_spend_log"][1]

        self.assertEqual(spent["test_id"], "a_share_minimal_data_burst_full_universe_redesign_20260531")
        self.assertEqual(
            spent["preregistration_ref"],
            str(REDESIGNED_ARTIFACT_PATH).replace("\\", "/"),
        )
        self.assertEqual(
            spent["result_ref"],
            "research/results/a_share_minimal_data_burst_full_universe_redesign_20260531/evidence_report.json",
        )
        self.assertEqual(spent["status"], "spent_failed_outcome_threshold")
        self.assertTrue(spent["promotion_relevant"])
        self.assertEqual(spent["tests_spent"], 1)
        self.assertIn("valid_signal_events = 134", spent["result_summary"])
        self.assertIn("mean_net_excess_csi1000_5d_pct = -2.8696001309", spent["result_summary"])
        self.assertIn("decision = falsified_or_redesign_required", spent["result_summary"])
        self.assertIn("No production use", spent["allowed_followup"])
        self.assertNotIn("SR-DATA-003", spent["allowed_followup"])
        self.assertTrue(
            any("spent and failed" in action for action in ledger["next_required_actions"])
        )

    def test_redesigned_preregistration_is_ledger_gated_full_universe_research_only(self) -> None:
        artifact = self._load_artifact(REDESIGNED_ARTIFACT_PATH)
        scope = artifact["scope"]
        universe = artifact["frozen_test_design"]["universe"]
        trigger = artifact["frozen_test_design"]["trigger_rule"]
        benchmark = artifact["frozen_test_design"]["benchmark_rule"]
        next_steps = "\n".join(artifact["next_steps"])

        self.assertEqual(artifact["schema_version"], "1.1.0")
        self.assertFalse(scope["production_use_allowed"])
        self.assertFalse(scope["provider_data_fetch_allowed"])
        self.assertFalse(scope["runner_change_allowed"])
        self.assertFalse(scope["ship_gate_claim_allowed"])
        self.assertFalse(scope["live_trading_or_minimal_live_allowed"])
        self.assertIn("_intermediate/egs_full_{YYYYMMDD}.csv", universe["source_universe_ref"])
        joined_filters = "\n".join(universe["eligibility_rule"] + universe["exclusion_rule"] + trigger["hard_filters"])
        self.assertIn("Use both Tier1 and Tier2", joined_filters)
        self.assertIn("Do not filter by steady-lane Tier1", joined_filters)
        self.assertNotIn("entry_flag must equal", joined_filters)
        self.assertIn("relative_strength", trigger["positive_signal_families"])
        self.assertIn("volume_expansion", trigger["positive_signal_families"])
        self.assertIn("breakout_quality", trigger["positive_signal_families"])
        self.assertIn("SR-DATA-003", benchmark["benchmark_return_rule"])
        self.assertIn("pre-outcome event-count", next_steps)

        budget = artifact["test_budget"]
        self.assertEqual(budget["promotion_relevant_tests_allowed"], 1)
        self.assertTrue(budget["program_level_ledger_required_before_run"])
        self.assertEqual(budget["program_level_ledger_ref"], str(LEDGER_ARTIFACT_PATH).replace("\\", "/"))
        self.assertTrue(artifact["ledger_trigger"]["program_level_ledger_required_now"])

    def test_ledger_schema_rejects_cardinality_or_review_gate_relaxation_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = copy.deepcopy(self._load_ledger_artifact())
        invalid["budget_policy"]["ledger_cardinality"] = "per_hypothesis"
        invalid["budget_policy"]["next_test_requires_reviewed_preregistration"] = False
        invalid["budget_policy"]["next_test_requires_user_approval"] = False
        invalid["planned_tests"].append(
            {
                "test_id": "silent_rescue_without_review",
                "planned_status": "reviewed_not_run",
                "created_at": "2026-05-31T00:00:00Z",
                "planned_preregistration_ref": "research/preregistrations/silent_rescue.json",
                "planned_result_ref": "research/results/silent_rescue/result.json",
                "promotion_relevant": False,
                "expected_tests_spent": 1,
                "approval_status": "reviewed_authorized",
                "design_summary": "Invalid because promotion_relevant cannot be false for ledger-gated planned tests.",
                "review_boundary": [
                    "schema should reject this planned test"
                ]
            }
        )

        errors = list(Draft7Validator(self._load_ledger_schema()).iter_errors(invalid))

        self.assertNotEqual(errors, [])

    def test_corrected_basis_supersession_only_changes_measurement_basis(self) -> None:
        blocked = self._load_artifact()
        corrected = self._load_corrected_artifact()

        for path in [
            ("scope",),
            ("frozen_test_design", "freeze_controls"),
            ("frozen_test_design", "universe"),
            ("frozen_test_design", "data_window"),
            ("frozen_test_design", "trigger_rule"),
            ("frozen_test_design", "entry_exit_rule"),
            ("frozen_test_design", "evaluation_threshold"),
            ("promotion_boundary",),
            ("ledger_trigger",),
        ]:
            with self.subTest(path=".".join(path)):
                left = blocked
                right = corrected
                for key in path:
                    left = left[key]
                    right = right[key]
                self.assertEqual(left, right)

        blocked_benchmark = blocked["frozen_test_design"]["benchmark_rule"]
        corrected_benchmark = corrected["frozen_test_design"]["benchmark_rule"]
        for key in ["primary_benchmark_id", "primary_benchmark_role", "secondary_diagnostics"]:
            self.assertEqual(blocked_benchmark[key], corrected_benchmark[key])
        self.assertNotEqual(blocked_benchmark["benchmark_return_rule"], corrected_benchmark["benchmark_return_rule"])

        blocked_budget = blocked["test_budget"]
        corrected_budget = corrected["test_budget"]
        for key in [
            "test_budget_status",
            "promotion_relevant_tests_allowed",
            "program_level_ledger_required_before_run",
            "program_level_ledger_ref",
            "disallowed_without_ledger",
        ]:
            self.assertEqual(blocked_budget[key], corrected_budget[key])

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
