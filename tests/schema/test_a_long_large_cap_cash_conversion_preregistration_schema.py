from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


SCHEMA_PATH = Path("schemas/a_long_large_cap_cash_conversion_preregistration.schema.json")
ARTIFACT_PATH = Path("research/preregistrations/a_long_large_cap_cash_conversion_20260607.json")
LEDGER_SCHEMA_PATH = Path("schemas/program_test_budget_ledger.schema.json")
LEDGER_ARTIFACT_PATH = Path("research/ledgers/a_long_large_cap_cash_conversion_program_test_budget_ledger_20260607.json")


class ALongLargeCapCashConversionPreregistrationSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_schema(self) -> dict:
        return self._load_json(SCHEMA_PATH)

    def _load_artifact(self) -> dict:
        return self._load_json(ARTIFACT_PATH)

    def _load_ledger(self) -> dict:
        return self._load_json(LEDGER_ARTIFACT_PATH)

    def _validate(self, payload: dict) -> list:
        schema = self._load_schema()
        Draft7Validator.check_schema(schema)
        return list(Draft7Validator(schema).iter_errors(payload))

    def test_schema_artifact_and_ledger_validate_when_jsonschema_available(self) -> None:
        schema = self._load_schema()
        artifact = self._load_artifact()
        ledger_schema = self._load_json(LEDGER_SCHEMA_PATH)
        ledger = self._load_ledger()

        Draft7Validator.check_schema(schema)
        Draft7Validator.check_schema(ledger_schema)
        self.assertEqual(list(Draft7Validator(schema).iter_errors(artifact)), [])
        self.assertEqual(list(Draft7Validator(ledger_schema).iter_errors(ledger)), [])

    def test_scope_is_research_only_pending_review_and_blocks_data_fetch_and_run(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertTrue(scope["research_only"])
        self.assertTrue(scope["manual_order_only"])
        self.assertTrue(scope["diagnostic_derived_not_prior_rescue"])
        self.assertTrue(scope["new_hypothesis_not_prior_reslice"])
        self.assertTrue(scope["reuses_reviewed_materialized_market_cap_universe"])
        self.assertEqual(scope["preregistration_review_status"], "passed_independent_review_ready_for_freeze")
        for field_name in [
            "new_data_fetch_required",
            "signal_search_executed_by_this_artifact",
            "signal_search_authorized_by_this_artifact",
            "data_fetch_allowed_by_this_artifact",
            "provider_call_allowed_by_this_artifact",
            "datahub_allowed",
            "production_use_allowed",
            "ship_gate_claim_allowed",
            "full_size_manual_use_allowed",
            "broker_or_order_automation_allowed",
        ]:
            with self.subTest(field_name=field_name):
                self.assertFalse(scope[field_name])

    def test_review_status_is_review_passed_and_execution_gate_is_explicit(self) -> None:
        artifact = self._load_artifact()
        required = artifact["planned_test_budget"]["required_preregistration_review_status_for_execution"]
        self.assertEqual(required, "passed_independent_review_ready_for_freeze")
        # After Codex independent-review PASS, the committed design records the review-passed state.
        self.assertEqual(artifact["scope"]["preregistration_review_status"], "passed_independent_review_ready_for_freeze")
        self.assertEqual(artifact["scope"]["preregistration_review_status"], required)
        # Review-passed still does not by itself authorize a run; the run gate stays off.
        self.assertFalse(artifact["planned_test_budget"]["signal_search_run_authorized_now"])
        # A pending review status still schema-validates (enum) but would not satisfy the execution gate.
        pending = copy.deepcopy(artifact)
        pending["scope"]["preregistration_review_status"] = "pending_independent_review"
        self.assertEqual(self._validate(pending), [])
        self.assertNotEqual(pending["scope"]["preregistration_review_status"], required)
        # An out-of-enum review status is rejected.
        bad = copy.deepcopy(artifact)
        bad["scope"]["preregistration_review_status"] = "self_approved"
        self.assertTrue(self._validate(bad))

    def test_diagnostic_derivation_is_honest_in_sample_clue_not_rescue(self) -> None:
        derivation = self._load_artifact()["diagnostic_derivation"]

        self.assertTrue(derivation["derived_from_diagnostic"])
        self.assertFalse(derivation["is_prior_quality_rescue"])
        self.assertEqual(
            derivation["evidence_status"],
            "persistent_in_sample_clue_not_robust_out_of_sample_proof",
        )
        self.assertTrue(derivation["vs_csi300_evidence_is_single_sample"])
        self.assertTrue(derivation["in_sample_clue_requires_forward_live_for_validation"])
        self.assertTrue(derivation["no_factor_definition_search_motivated_by_prior_result"])
        self.assertFalse(derivation["old_result_reslice_allowed"])
        self.assertFalse(derivation["old_composite_or_diagnostic_relabel_as_pass_allowed"])

    def test_prior_falsified_result_cannot_be_rescued(self) -> None:
        boundary = self._load_artifact()["prior_result_boundary"]

        self.assertEqual(
            boundary["prior_result_ref"],
            "research/results/a_long_large_cap_pure_quality_20260607/execution_summary.json",
        )
        self.assertEqual(boundary["prior_research_verdict"], "falsified_large_cap_pure_quality_under_frozen_rules")
        self.assertEqual(boundary["prior_candidate_alpha_clue_count"], 0)
        self.assertEqual(
            boundary["new_design_reason"],
            "test_diagnostic_derived_cash_conversion_earnings_quality_as_standalone_primary",
        )
        self.assertFalse(boundary["old_result_reslice_allowed"])
        self.assertFalse(boundary["old_single_factor_diagnostic_rescue_allowed"])
        self.assertFalse(boundary["threshold_relaxation_allowed"])
        self.assertFalse(boundary["benchmark_rescue_allowed"])
        self.assertFalse(boundary["horizon_rescue_allowed"])

    def test_data_reuse_requires_no_new_fetch_and_points_to_reviewed_audits(self) -> None:
        reuse = self._load_artifact()["data_reuse"]

        self.assertTrue(reuse["no_new_provider_call_required"])
        self.assertTrue(reuse["no_new_daily_basic_pull_required"])
        self.assertEqual(
            reuse["market_cap_audit_report_ref"],
            "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json",
        )
        self.assertEqual(
            reuse["full_main_board_audit_report_ref"],
            "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
        )
        self.assertEqual(reuse["selected_market_cap_field"], "circ_mv")
        self.assertEqual(reuse["monthly_as_of_count"], 96)
        self.assertTrue(reuse["separate_review_required_before_signal_run"])
        self.assertTrue(reuse["separate_user_execute_required_before_signal_run"])

    def test_primary_signal_is_single_factor_cash_conversion_unchanged_definition(self) -> None:
        signal = self._load_artifact()["frozen_design"]["signal_rule"]

        self.assertEqual(signal["primary_signal_id"], "cash_conversion_percentile")
        self.assertEqual(signal["primary_signal_type"], "single_factor_percentile")
        self.assertEqual(signal["primary_factor"], "cash_conversion")
        self.assertEqual(
            signal["primary_factor_definition"],
            "operating_cash_flow_n_cashflow_act_div_abs_net_income_attr_parent_same_period",
        )
        self.assertTrue(signal["factor_definition_unchanged_from_diagnostic"])
        self.assertFalse(signal["factor_definition_change_allowed"])
        self.assertEqual(signal["cash_conversion_min_abs_net_income"], 10000000.0)
        self.assertTrue(signal["cash_conversion_small_denominator_guard_required"])
        self.assertTrue(signal["cash_conversion_same_period_end_date_required"])
        self.assertTrue(signal["percentile_rank_required"])
        self.assertFalse(signal["zscore_allowed"])
        self.assertFalse(signal["multi_factor_composite_allowed"])
        self.assertFalse(signal["single_factor_winner_take_all_from_prior_result_allowed"])
        self.assertEqual(
            set(signal["diagnostic_factors"]),
            {"profitability_quality", "balance_sheet_strength", "earnings_stability"},
        )
        self.assertFalse(signal["diagnostic_factor_can_rescue_primary_failure"])

    def test_neutralization_is_marginal_double_0_5_0_5(self) -> None:
        neutral = self._load_artifact()["frozen_design"]["neutralization_rule"]

        self.assertEqual(neutral["primary_view"], "industry_and_size_neutral")
        self.assertEqual(neutral["neutralization_method"], "marginal_double_neutralization")
        self.assertEqual(
            neutral["combined_score_rule"],
            "0_5_industry_neutral_percentile_plus_0_5_size_neutral_percentile",
        )
        self.assertFalse(neutral["crossed_industry_size_bucket_allowed"])
        self.assertEqual(neutral["size_bucket_count"], 5)
        self.assertEqual(neutral["minimum_size_bucket_count_for_primary_percentile"], 50)
        self.assertTrue(neutral["size_coverage_gate_applies_to_cohort_forming_months_only"])

    def test_decision_cell_is_two_tier_single_cell_504d_csi300(self) -> None:
        design = self._load_artifact()["frozen_design"]
        cell = design["decision_cell"]
        measurement = design["measurement_rule"]
        benchmark = design["benchmark_rule"]

        self.assertEqual(cell["cell_id"], "primary_cash_conversion_industry_size_neutral_504d_csi300")
        self.assertEqual(cell["signal"], "cash_conversion_percentile")
        self.assertEqual(cell["horizon_trading_days"], 504)
        self.assertEqual(cell["benchmark"], "CSI300")
        self.assertEqual(cell["top_fraction"], 0.2)
        self.assertEqual(cell["minimum_top_count_per_month"], 10)
        self.assertTrue(cell["decision_is_two_tier"])
        self.assertEqual(cell["multiple_testing_adjustment_for_decision"], "not_applicable_single_primary_cell")

        clue = cell["statistical_alpha_clue_gates"]
        self.assertTrue(clue["mean_net_excess_must_be_positive"])
        self.assertEqual(clue["minimum_hac_t_stat"], 2.0)
        self.assertEqual(clue["minimum_monthly_cohorts"], 48)
        self.assertTrue(clue["sub_period_both_halves_mean_excess_positive_required"])

        tradeable = cell["tradeable_candidate_gates"]
        self.assertEqual(
            tradeable["risk_gate_metric"],
            "rolling_overlapping_portfolio_relative_nav_max_drawdown_vs_csi300",
        )
        self.assertEqual(tradeable["minimum_allowed_relative_nav_drawdown"], -0.15)
        self.assertTrue(tradeable["risk_gate_affects_tradeable_label_only_not_alpha_clue"])

        self.assertEqual(measurement["primary_horizon_trading_days"], 504)
        self.assertEqual(measurement["round_trip_cost"], 0.0026)
        self.assertEqual(benchmark["primary_benchmark"], "CSI300")
        self.assertFalse(benchmark["both_benchmark_pass_required"])

    def test_risk_gate_is_relative_nav_drawdown_frozen_and_tradeable_tier_only(self) -> None:
        risk = self._load_artifact()["frozen_design"]["risk_gate"]

        self.assertEqual(risk["method"], "rolling_overlapping_monthly_tranche_portfolio_nav")
        self.assertEqual(risk["primary_risk_metric"], "max_drawdown_of_relative_nav")
        self.assertEqual(risk["relative_nav_formula"], "strategy_nav_divided_by_benchmark_nav")
        self.assertEqual(
            risk["benchmark_construction"],
            "option_a_parallel_same_as_of_schedule_horizon_and_ramp_holding_csi300_total_return_instead_of_selected_basket",
        )
        self.assertEqual(
            risk["benchmark_nav_basis"],
            "same_schedule_rolling_overlapping_csi300_total_return_tranche_portfolio",
        )
        self.assertEqual(risk["startup_ramp_convention"], "average_over_active_tranches_only_no_idle_cash_position")
        self.assertFalse(risk["cost_applied_to_benchmark_tranches"])
        self.assertEqual(risk["minimum_allowed_relative_nav_drawdown"], -0.15)
        self.assertTrue(risk["threshold_frozen_before_run"])
        self.assertEqual(risk["absolute_strategy_nav_drawdown_role"], "diagnostic_only")
        self.assertFalse(risk["summed_overlapping_cohort_excess_drawdown_as_gate_allowed"])
        self.assertTrue(risk["risk_gate_affects_tradeable_label_only_not_alpha_clue"])

    def test_sub_period_split_is_effective_cohort_median_not_calendar_year(self) -> None:
        sub = self._load_artifact()["frozen_design"]["sub_period_robustness"]

        self.assertEqual(sub["split_rule"], "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves")
        self.assertFalse(sub["natural_calendar_year_split_allowed"])
        self.assertTrue(sub["requires_both_halves_mean_excess_positive"])
        self.assertTrue(sub["report_each_half_hac_t_stat"])

    def test_anti_p_hacking_blocks_definition_and_composite_search(self) -> None:
        controls = self._load_artifact()["frozen_design"]["anti_p_hacking_controls"]

        self.assertEqual(controls["test_budget_units"], 1)
        self.assertFalse(controls["parameter_sweep_allowed"])
        self.assertFalse(controls["factor_definition_search_allowed"])
        self.assertFalse(controls["multi_factor_composite_search_allowed"])
        self.assertFalse(controls["post_result_rescue_slicing_allowed"])
        self.assertTrue(controls["risk_gate_threshold_frozen_before_run"])
        self.assertTrue(controls["new_ledger_required_before_any_followup"])

    def test_ledger_is_spent_singleton_in_committed_post_execution_state(self) -> None:
        # The cash_conversion singleton was spent by the reviewed user-executed signal search, so the
        # design-slice unspent/pending shape no longer holds. The spent ledger still schema-validates.
        artifact = self._load_artifact()
        ledger = self._load_ledger()

        self.assertEqual(artifact["planned_test_budget"]["ledger_ref"], str(LEDGER_ARTIFACT_PATH).replace("\\", "/"))
        self.assertFalse(artifact["planned_test_budget"]["signal_search_run_authorized_now"])
        self.assertFalse(artifact["planned_test_budget"]["new_data_fetch_authorized_now"])
        self.assertEqual(ledger["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(ledger["lane_id"], "a_long_research")
        self.assertEqual(ledger["family_id"], "a_long_large_cap_cash_conversion_v1")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 1)
        self.assertEqual(ledger["budget_policy"]["tests_available_without_new_review"], 0)
        self.assertEqual(ledger["planned_tests"], [])
        self.assertEqual(len(ledger["test_spend_log"]), 1)
        spent = ledger["test_spend_log"][0]
        self.assertEqual(spent["test_id"], "a_long_large_cap_cash_conversion_20260607")
        self.assertEqual(spent["status"], "spent_passed_research_continue_only")
        self.assertEqual(spent["tests_spent"], 1)
        self.assertIn("rerun", spent["allowed_followup"])

    def test_frozen_decision_thresholds_are_exact_consts(self) -> None:
        base = self._load_artifact()
        mutations = [
            ("neutralization", "minimum_size_bucket_count_for_primary_percentile", 999),
            ("neutralization", "minimum_size_bucket_count_for_primary_percentile", 10),
            ("top_count", "minimum_top_count_per_month", 999),
            ("top_count", "minimum_top_count_per_month", 5),
            ("cohorts", "minimum_monthly_cohorts", 999),
            ("cohorts", "minimum_monthly_cohorts", 24),
        ]
        for target, field, value in mutations:
            payload = copy.deepcopy(base)
            if target == "neutralization":
                payload["frozen_design"]["neutralization_rule"][field] = value
            elif target == "top_count":
                payload["frozen_design"]["decision_cell"][field] = value
            else:
                payload["frozen_design"]["decision_cell"]["statistical_alpha_clue_gates"][field] = value
            with self.subTest(field=field, value=value):
                self.assertTrue(
                    self._validate(payload),
                    f"mutating frozen threshold {field}={value} must fail schema validation",
                )

    def test_scope_creep_is_rejected_by_schema(self) -> None:
        payload = copy.deepcopy(self._load_artifact())
        payload["scope"]["signal_search_authorized_by_this_artifact"] = True
        payload["scope"]["new_data_fetch_required"] = True
        payload["diagnostic_derivation"]["old_result_reslice_allowed"] = True
        payload["frozen_design"]["signal_rule"]["multi_factor_composite_allowed"] = True
        payload["frozen_design"]["signal_rule"]["factor_definition_change_allowed"] = True
        payload["frozen_design"]["neutralization_rule"]["crossed_industry_size_bucket_allowed"] = True
        payload["frozen_design"]["risk_gate"]["summed_overlapping_cohort_excess_drawdown_as_gate_allowed"] = True
        payload["frozen_design"]["decision_cell"]["tradeable_candidate_gates"][
            "risk_gate_affects_tradeable_label_only_not_alpha_clue"
        ] = False
        payload["prohibited_claims"]["validated_alpha"] = True

        errors = self._validate(payload)

        self.assertGreaterEqual(len(errors), 5)


if __name__ == "__main__":
    unittest.main()
