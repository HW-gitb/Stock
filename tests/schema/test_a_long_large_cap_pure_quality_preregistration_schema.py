from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


SCHEMA_PATH = Path("schemas/a_long_large_cap_pure_quality_preregistration.schema.json")
ARTIFACT_PATH = Path("research/preregistrations/a_long_large_cap_pure_quality_20260607.json")
LEDGER_SCHEMA_PATH = Path("schemas/program_test_budget_ledger.schema.json")
LEDGER_ARTIFACT_PATH = Path("research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json")


class ALongLargeCapPureQualityPreregistrationSchemaTest(unittest.TestCase):
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

    def test_scope_blocks_data_probe_signal_run_provider_datahub_and_ship_gate(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertTrue(scope["research_only"])
        self.assertTrue(scope["manual_order_only"])
        self.assertTrue(scope["new_hypothesis_not_prior_reslice"])
        self.assertEqual(scope["preregistration_review_status"], "passed_independent_review_ready_for_freeze")
        for field_name in [
            "daily_basic_pull_allowed_by_this_artifact",
            "market_cap_probe_allowed_by_this_artifact",
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

    def test_prior_no_alpha_result_cannot_be_rescued_or_resliced(self) -> None:
        boundary = self._load_artifact()["prior_result_boundary"]

        self.assertEqual(boundary["prior_research_verdict"], "no_alpha_found_under_frozen_rules")
        self.assertEqual(boundary["prior_candidate_alpha_clue_count"], 0)
        self.assertEqual(boundary["prior_tests_spent_count"], 1)
        self.assertEqual(
            boundary["new_design_reason"],
            "separate_core_quality_from_size_premium_inside_a_large_mid_cap_pit_universe",
        )
        self.assertFalse(boundary["old_result_reslice_allowed"])
        self.assertFalse(boundary["old_single_factor_diagnostic_rescue_allowed"])
        self.assertFalse(boundary["threshold_relaxation_allowed"])
        self.assertFalse(boundary["benchmark_rescue_allowed"])
        self.assertFalse(boundary["horizon_rescue_allowed"])

    def test_daily_basic_market_cap_dependency_is_gated_and_pending(self) -> None:
        gate = self._load_artifact()["data_dependency_gate"]

        self.assertEqual(gate["market_cap_source_required_for_future_run"], "Tushare daily_basic by trade_date")
        self.assertFalse(gate["daily_basic_pull_allowed_now"])
        self.assertFalse(gate["daily_basic_probe_allowed_now"])
        self.assertTrue(gate["availability_probe_required_before_materialization"])
        self.assertTrue(gate["availability_probe_completed_before_materialization"])
        self.assertEqual(
            gate["market_cap_field_probe_execution_summary_ref"],
            "docs/a_long_large_cap_market_cap_field_probe_execution_summary_20260607.json",
        )
        self.assertEqual(gate["market_cap_field_preference_order"], ["circ_mv", "total_mv"])
        self.assertEqual(gate["selected_market_cap_field_status"], "circ_mv")
        self.assertTrue(gate["selected_market_cap_field_must_be_frozen_before_run"])
        self.assertEqual(gate["planned_monthly_as_of_call_count_estimate"], 96)
        self.assertTrue(gate["raw_storage_must_be_gitignored"])
        self.assertTrue(gate["tracked_summary_must_not_contain_raw_rows"])
        self.assertTrue(gate["separate_review_required_before_probe_or_pull"])
        self.assertTrue(gate["separate_user_execute_required_before_probe_or_pull"])

    def test_universe_locks_top_500_main_board_pit_market_cap_without_n_search(self) -> None:
        universe = self._load_artifact()["frozen_design"]["universe_rule"]

        self.assertEqual(universe["board_scope"], "main_board_only")
        self.assertEqual(universe["as_of_frequency"], "monthly")
        self.assertEqual(universe["universe_size_n"], 500)
        self.assertFalse(universe["universe_size_n_search_allowed"])
        self.assertEqual(universe["selection_basis"], "top_500_by_pit_market_cap_as_of_each_as_of_date")
        self.assertEqual(
            universe["market_cap_field_choice_status"],
            "circ_mv_reviewed_probe_passed_frozen_for_materialization",
        )
        self.assertTrue(universe["include_later_delisted_names_at_pre_delisting_asofs"])
        self.assertTrue(universe["pit_list_delist_required"])
        self.assertTrue(universe["selection_time_namechange_veto_required"])
        self.assertEqual(
            universe["reviewed_data_quality_exclusion_boundary_ref"],
            "docs/a_long_large_cap_data_quality_exclusion_decision_20260607.json",
        )
        exclusion_policy = universe["reviewed_data_quality_exclusion_policy"]
        self.assertEqual(exclusion_policy["excluded_symbols"], ["000043.SZ"])
        self.assertEqual(exclusion_policy["affected_as_of_dates"], ["20191129"])
        self.assertEqual(exclusion_policy["max_excluded_symbols"], 1)
        self.assertEqual(exclusion_policy["max_excluded_observations"], 1)
        self.assertTrue(exclusion_policy["drop_excluded_symbols_before_signal_scoring"])
        self.assertTrue(exclusion_policy["backfill_next_main_board_by_circ_mv"])
        self.assertTrue(exclusion_policy["materialized_top500_rederivation_unchanged"])
        self.assertFalse(exclusion_policy["threshold_rescue_allowed"])
        self.assertTrue(universe["st_star_bse_chinext_excluded"])

    def test_primary_signal_is_three_factor_percentile_composite_and_earnings_stability_is_diagnostic(self) -> None:
        signal = self._load_artifact()["frozen_design"]["signal_rule"]
        policy = signal["factor_measurement_policy"]

        self.assertEqual(signal["primary_signal_id"], "core_quality_composite_percentile_3factor")
        self.assertEqual(signal["primary_signal_type"], "equal_weight_percentile_composite")
        self.assertEqual(
            set(signal["component_factors"]),
            {"profitability_quality", "cash_conversion", "balance_sheet_strength"},
        )
        self.assertEqual(signal["component_weighting"], "equal_weight_one_third_each")
        self.assertTrue(signal["percentile_rank_required"])
        self.assertFalse(signal["zscore_composite_allowed"])
        self.assertFalse(signal["single_factor_pass_can_define_alpha"])
        self.assertEqual(signal["earnings_stability_role"], "frozen_diagnostic_only_not_primary")
        self.assertFalse(signal["earnings_stability_can_rescue_primary_failure"])
        self.assertEqual(policy["profitability_quality_basis"], "annualized_ytd_roe_from_fina_indicator_roe")
        self.assertFalse(policy["raw_fina_indicator_roe_direct_cross_section_allowed"])
        self.assertEqual(policy["cash_conversion_min_abs_net_income"], 10000000.0)
        self.assertTrue(policy["cash_conversion_small_denominator_guard_required"])
        self.assertFalse(policy["mixed_ytd_quarter_sequence_allowed"])

    def test_primary_view_is_industry_and_size_neutral_and_diagnostics_are_not_primary(self) -> None:
        neutralization = self._load_artifact()["frozen_design"]["neutralization_rule"]

        self.assertEqual(neutralization["primary_view"], "industry_and_size_neutral")
        self.assertEqual(neutralization["neutralization_method"], "marginal_double_neutralization")
        self.assertEqual(
            neutralization["primary_score_construction"],
            "equal_weight_average_of_marginal_industry_neutral_and_marginal_size_neutral_percentile_scores",
        )
        self.assertEqual(neutralization["industry_neutral_score_rule"], "percentile_composite_within_industry_l2_fallback_l1")
        self.assertEqual(neutralization["size_neutral_score_rule"], "percentile_composite_within_market_cap_quintile")
        self.assertEqual(neutralization["combined_score_rule"], "0_5_industry_neutral_percentile_plus_0_5_size_neutral_percentile")
        self.assertFalse(neutralization["crossed_industry_size_bucket_allowed"])
        self.assertEqual(neutralization["industry_basis"], "SW_L2_then_SW_L1_if_sample_lt_20")
        self.assertEqual(neutralization["industry_l2_min_count"], 20)
        self.assertEqual(neutralization["industry_l1_min_count"], 2)
        self.assertEqual(neutralization["size_bucket_rule"], "pit_market_cap_quintile_inside_top_500_per_as_of")
        self.assertEqual(neutralization["size_bucket_count"], 5)
        self.assertEqual(neutralization["expected_names_per_size_bucket"], 100)
        self.assertGreaterEqual(neutralization["minimum_size_bucket_count_for_primary_percentile"], 50)
        self.assertIn("do_not_cross_industry_and_size_buckets", neutralization["thin_bucket_policy"])
        self.assertEqual(neutralization["non_neutral_view_role"], "diagnostic_only_not_primary")
        self.assertEqual(neutralization["cap_weighted_view_role"], "diagnostic_only_not_primary")

    def test_primary_decision_cell_is_504d_csi300_single_cell_without_fdr_or_both_benchmark_gate(self) -> None:
        design = self._load_artifact()["frozen_design"]
        measurement = design["measurement_rule"]
        benchmark = design["benchmark_rule"]
        cell = design["decision_cell"]
        diagnostics = design["diagnostic_cells"]

        self.assertEqual(measurement["primary_horizon_trading_days"], 504)
        self.assertEqual(measurement["diagnostic_horizons_trading_days"], [252])
        self.assertEqual(measurement["entry_rule"], "next_trading_day_close_after_as_of")
        self.assertEqual(
            measurement["stock_return_basis"],
            "stock_total_return_adj_factor_next_trading_day_close_to_exit_close",
        )
        self.assertEqual(
            measurement["benchmark_return_basis"],
            "benchmark_total_return_index_next_trading_day_close_to_same_exit_close",
        )
        self.assertTrue(measurement["same_anchor_required"])
        self.assertEqual(measurement["round_trip_cost"], 0.0026)
        self.assertFalse(measurement["price_index_fallback_allowed"])
        self.assertEqual(benchmark["primary_benchmark"], "CSI300")
        self.assertEqual(benchmark["diagnostic_benchmark"], "CSI1000")
        self.assertFalse(benchmark["both_benchmark_pass_required"])
        self.assertEqual(cell["cell_id"], "primary_core_quality_composite_industry_size_neutral_504d_csi300")
        self.assertEqual(cell["signal"], "core_quality_composite_percentile_3factor")
        self.assertEqual(cell["view"], "industry_and_size_neutral")
        self.assertEqual(cell["horizon_trading_days"], 504)
        self.assertEqual(cell["benchmark"], "CSI300")
        self.assertEqual(cell["top_fraction"], 0.2)
        self.assertTrue(cell["mean_net_excess_must_be_positive"])
        self.assertEqual(cell["minimum_hac_t_stat"], 2.0)
        self.assertGreaterEqual(cell["minimum_monthly_cohorts"], 48)
        self.assertEqual(cell["minimum_allowed_monthly_excess_drawdown"], -0.15)
        self.assertEqual(cell["multiple_testing_adjustment_for_decision"], "not_applicable_single_primary_cell")
        self.assertTrue(diagnostics["report_csi1000"])
        self.assertTrue(diagnostics["report_252d"])
        self.assertTrue(diagnostics["report_single_factor_components"])
        self.assertTrue(diagnostics["report_earnings_stability"])
        self.assertFalse(diagnostics["diagnostics_can_define_alpha"])

    def test_anti_p_hacking_controls_block_quality_acceleration_and_rescue_slicing(self) -> None:
        controls = self._load_artifact()["frozen_design"]["anti_p_hacking_controls"]

        self.assertEqual(controls["test_budget_units"], 1)
        self.assertFalse(controls["parameter_sweep_allowed"])
        self.assertFalse(controls["universe_n_search_allowed"])
        self.assertFalse(controls["single_factor_winner_take_all_allowed"])
        self.assertFalse(controls["quality_acceleration_allowed_this_round"])
        self.assertFalse(controls["post_result_rescue_slicing_allowed"])
        self.assertTrue(controls["new_ledger_required_before_any_followup"])

    def test_pit_and_hygiene_controls_require_restatement_and_no_raw_leaks(self) -> None:
        controls = self._load_artifact()["frozen_design"]["pit_and_hygiene_controls"]

        self.assertEqual(
            controls["restatement_exclusion_list_ref"],
            "research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv",
        )
        self.assertTrue(controls["restatement_exclusion_required"])
        self.assertEqual(controls["expected_restatement_exclusion_group_count"], 1504)
        self.assertTrue(controls["pit_namechange_required"])
        self.assertFalse(controls["current_stock_basic_name_veto_allowed"])
        self.assertFalse(controls["tracked_summary_contains_raw_rows_allowed"])
        self.assertFalse(controls["tracked_summary_contains_endpoint_results_allowed"])
        self.assertFalse(controls["tracked_summary_contains_secret_allowed"])
        self.assertFalse(controls["tracked_summary_contains_request_url_allowed"])

    def test_ledger_registers_one_pending_singleton_test_without_execution_authorization(self) -> None:
        artifact = self._load_artifact()
        ledger = self._load_ledger()

        self.assertEqual(artifact["planned_test_budget"]["ledger_ref"], str(LEDGER_ARTIFACT_PATH).replace("\\", "/"))
        self.assertFalse(artifact["planned_test_budget"]["signal_search_run_authorized_now"])
        self.assertFalse(artifact["planned_test_budget"]["daily_basic_probe_or_pull_authorized_now"])
        self.assertEqual(ledger["ledger_status"], "active_planned_test_pending_review")
        self.assertEqual(ledger["lane_id"], "a_long_research")
        self.assertEqual(ledger["family_id"], "a_long_large_cap_pure_quality_v1")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(ledger["budget_policy"]["tests_available_without_new_review"], 0)
        self.assertEqual(ledger["test_spend_log"], [])
        self.assertEqual(len(ledger["planned_tests"]), 1)
        planned = ledger["planned_tests"][0]
        self.assertEqual(planned["test_id"], "a_long_large_cap_pure_quality_20260607")
        self.assertEqual(planned["planned_status"], "planned_not_reviewed")
        self.assertEqual(planned["approval_status"], "user_approved_pending_review")
        self.assertEqual(planned["expected_tests_spent"], 1)
        self.assertIn("new hypothesis", planned["review_boundary"][0])
        self.assertIn("daily_basic", planned["review_boundary"][1])
        self.assertIn("Diagnostics", planned["review_boundary"][3])

    def test_scope_creep_is_rejected_by_schema(self) -> None:
        payload = copy.deepcopy(self._load_artifact())
        payload["scope"]["daily_basic_pull_allowed_by_this_artifact"] = True
        payload["scope"]["signal_search_authorized_by_this_artifact"] = True
        payload["prior_result_boundary"]["old_result_reslice_allowed"] = True
        payload["data_dependency_gate"]["selected_market_cap_field_status"] = "pending_probe_not_selected"
        payload["frozen_design"]["universe_rule"]["reviewed_data_quality_exclusion_policy"]["backfill_next_main_board_by_circ_mv"] = False
        payload["frozen_design"]["signal_rule"]["zscore_composite_allowed"] = True
        payload["frozen_design"]["neutralization_rule"]["crossed_industry_size_bucket_allowed"] = True
        payload["frozen_design"]["benchmark_rule"]["both_benchmark_pass_required"] = True
        payload["prohibited_claims"]["validated_alpha"] = True

        errors = self._validate(payload)

        self.assertGreaterEqual(len(errors), 5)


if __name__ == "__main__":
    unittest.main()
