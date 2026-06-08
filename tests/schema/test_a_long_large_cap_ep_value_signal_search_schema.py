from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


SUMMARY_SCHEMA_PATH = Path("schemas/a_long_large_cap_ep_value_signal_search_execution_summary.schema.json")

PRIMARY_CELL_ID = "ep_value_industry_size_neutral_equal_weight_504d_CSI300"


class ALongLargeCapEpValueSignalSearchSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate(self, schema_path: Path, payload: dict) -> list:
        schema = self._load_json(schema_path)
        Draft7Validator.check_schema(schema)
        return list(Draft7Validator(schema).iter_errors(payload))

    def _cells(self) -> list:
        specs = []
        for view in ["industry_size_neutral", "non_neutral", "industry_neutral", "size_neutral"]:
            for horizon in [252, 504]:
                for benchmark in ["CSI300", "CSI1000"]:
                    specs.append(("ep_value", view, "equal_weight", horizon, benchmark))
        for horizon in [252, 504]:
            for benchmark in ["CSI300", "CSI1000"]:
                specs.append(("ep_value", "industry_size_neutral", "cap_weighted", horizon, benchmark))
        for signal_id in ["book_to_market", "cash_flow_to_price"]:
            for horizon in [252, 504]:
                for benchmark in ["CSI300", "CSI1000"]:
                    specs.append((signal_id, "industry_size_neutral", "equal_weight", horizon, benchmark))

        cells = []
        for signal_id, view, weighting, horizon, benchmark in specs:
            is_primary = (
                signal_id == "ep_value"
                and view == "industry_size_neutral"
                and weighting == "equal_weight"
                and horizon == 504
                and benchmark == "CSI300"
            )
            cells.append(
                {
                    "cell_id": f"{signal_id}_{view}_{weighting}_{horizon}d_{benchmark}",
                    "signal_id": signal_id,
                    "view": view,
                    "weighting": weighting,
                    "diagnostic_role": "primary_decision_cell" if is_primary else "diagnostic_only",
                    "horizon_trading_days": horizon,
                    "benchmark": benchmark,
                    "monthly_cohort_count": 50,
                    "mean_monthly_cohort_net_excess": 0.001,
                    "monthly_cohort_std": 0.01,
                    "monthly_clustered_t_stat": 0.7,
                    "monthly_t_stat_method": "newey_west_hac_on_monthly_overlapping_cohorts",
                    "hac_lag_months": 24 if horizon == 504 else 12,
                    "p_value": 0.48,
                    "minimum_monthly_top_count": 10,
                    "positive_month_count": 28,
                    "worst_monthly_cohort_excess": -0.02,
                    "best_monthly_cohort_excess": 0.03,
                    "diagnostic_max_drawdown_on_monthly_excess": -0.05,
                    "top_symbol_selection_share": 0.05,
                    "max_single_year_positive_return_share": 0.2,
                    "passes_minimum_monthly_cohorts": True,
                    "passes_minimum_top_count": True,
                    "passes_name_concentration_guard": True,
                    "passes_single_year_concentration_guard": True,
                }
            )
        return cells

    def _valid_summary(self) -> dict:
        return {
            "schema_name": "a_long_large_cap_ep_value_signal_search_execution_summary",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-08T00:00:00+00:00",
            "artifact_id": "a_long_large_cap_ep_value_signal_search_execution_summary_20260608",
            "source_refs": [
                "research/preregistrations/a_long_large_cap_ep_value_20260608.json",
                "research/ledgers/a_long_large_cap_ep_value_program_test_budget_ledger_20260608.json",
                "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json",
                "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
                "docs/a_long_large_cap_data_quality_exclusion_decision_20260607.json",
                "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
                "research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv",
                "docs/a_long_total_return_benchmark_access_probe_summary_20260606.json",
            ],
            "scope": {
                "phase": "7a_alpha_validation",
                "purpose": "a_long_large_cap_ep_value_signal_search_execution",
                "lane_id": "a_long",
                "market": "A-share",
                "research_only": True,
                "provider_call_executed": False,
                "tushare_call_executed": False,
                "data_fetch_executed": False,
                "local_raw_read_only": True,
                "signal_search_executed": True,
                "alpha_backtest_executed": True,
                "production_use_allowed": False,
                "ship_gate_claim_allowed": False,
                "full_size_manual_use_allowed": False,
                "broker_or_order_automation_allowed": False,
                "manual_order_only": True,
            },
            "execution_gates": {
                "independent_review_confirmed": True,
                "post_review_execute_confirmed": True,
                "preregistration_validated": True,
                "preregistration_review_passed": True,
                "ledger_unspent_before_run": True,
                "market_cap_audit_passed": True,
                "full_main_board_audit_passed": True,
                "benchmark_route_amendment_validated": True,
                "restatement_exclusion_list_loaded": True,
                "restatement_exclusion_groups_expected": 1504,
                "restatement_exclusion_groups_found_in_raw": 1504,
                "restatement_exclusion_list_applied": True,
                "reviewed_data_quality_exclusion_applied": True,
                "reviewed_data_quality_exclusion_backfilled": True,
                "no_network_calls_executed": True,
                "tracked_summary_contains_raw_rows": False,
                "tracked_summary_contains_endpoint_results": False,
                "tracked_summary_contains_secret": False,
                "tracked_summary_contains_request_url": False,
            },
            "large_cap_universe_boundary": {
                "board_scope": "main_board_only",
                "selected_market_cap_field": "circ_mv",
                "monthly_as_of_count": 96,
                "universe_size_n": 500,
                "size_bucket_count": 5,
                "minimum_size_bucket_count_for_primary_percentile": 50,
                "reviewed_data_quality_exclusion_policy": "drop_documented_exclusions_then_backfill_next_main_board_by_circ_mv",
                "top500_symbols_written_to_tracked_summary": False,
                "market_cap_monthly_as_of_count": 96,
                "large_cap_target_universe_size": 500,
                "large_cap_signal_universe_observations": 48000,
                "documented_data_quality_exclusion_observation_count": 1,
                "backfilled_after_documented_exclusion_observation_count": 1,
                "outside_prior_audited_universe_after_backfill_observation_count": 0,
                "incomplete_large_cap_universe_month_count": 0,
                "minimum_size_bucket_count": 100,
            },
            "search_design": {
                "primary_signal_id": "ep_value_percentile",
                "primary_factor": "ep_value",
                "primary_factor_definition": "trailing_twelve_month_net_income_attr_parent_div_pit_circ_mv_as_of_each_as_of_date",
                "earnings_basis": "trailing_twelve_month_net_income_attr_parent_from_pit_income_ytd_rollover",
                "ttm_rollover_rule": "latest_pit_ytd_plus_prior_fiscal_year_annual_minus_prior_year_same_period_ytd_all_pit_and_restatement_excluded",
                "denominator_field": "pit_circ_mv_at_as_of",
                "non_positive_ttm_earnings_excluded_from_scoring": True,
                "diagnostic_factors": ["book_to_market", "cash_flow_to_price"],
                "primary_view": "industry_size_neutral",
                "ep_value_views_reported": ["industry_size_neutral", "non_neutral", "industry_neutral", "size_neutral"],
                "cap_weighted_view_reported": True,
                "primary_horizon_trading_days": 504,
                "diagnostic_horizons_trading_days": [252],
                "primary_benchmark": "CSI300",
                "diagnostic_benchmark": "CSI1000",
                "secondary_benchmark_required_for_alpha_clue": False,
                "stock_return_basis": "stock_total_return_adj_factor_next_trading_day_close_to_exit_close",
                "benchmark_return_basis": "benchmark_total_return_index_next_trading_day_close_to_same_exit_close",
                "round_trip_cost": 0.0026,
                "top_fraction": 0.2,
                "minimum_top_count_per_month": 10,
                "minimum_monthly_cohorts": 48,
                "monthly_t_stat_method": "newey_west_hac_on_monthly_overlapping_cohorts",
                "hac_lag_rule": "ceil_horizon_trading_days_div_21_capped_at_monthly_cohort_count_minus_1",
                "monthly_cohort_count_is_not_independent_n": True,
                "minimum_hac_t_stat": 2.0,
                "decision_is_two_tier": True,
                "minimum_allowed_relative_nav_drawdown": -0.15,
                "max_top_symbol_selection_share": 0.2,
                "max_single_year_positive_return_share": 0.35,
                "sub_period_split_rule": "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves",
                "multiple_testing_adjustment_for_decision": "not_applicable_single_primary_cell_but_fifth_program_level_test_caveated_in_provenance",
                "restatement_exclusion_required": True,
                "diagnostics_can_define_alpha": False,
                "parameter_sweep_executed": False,
                "earnings_basis_search_executed": False,
                "denominator_field_search_executed": False,
                "post_result_rescue_slicing_executed": False,
            },
            "execution_diagnostics": {
                "as_of_count": 96,
                "target_large_cap_universe_size": 500,
                "large_cap_universe_observations": 48000,
                "scored_pit_universe_excluded_before_list_count": 0,
                "scored_pit_universe_excluded_after_delist_count": 0,
                "selection_time_name_vetoed_observation_count": 0,
                "selection_time_name_vetoed_symbol_count": 0,
                "industry_neutral_excluded_observation_count": 0,
                "industry_neutral_excluded_symbol_count": 0,
                "industry_neutral_excluded_observation_share": 0.0,
                "industry_neutral_excluded_2018_2020_observation_count": 0,
                "industry_neutral_excluded_2018_2020_observation_share": 0.0,
                "size_neutral_thin_bucket_count": 0,
                "primary_size_neutral_thin_month_count": 0,
                "primary_size_neutral_min_bucket_observation_count": 50,
                "primary_size_neutral_coverage_month_count": 93,
                "primary_size_neutral_bucket_coverage_by_month": [
                    {
                        "as_of": "20200131",
                        "q1_count": 50,
                        "q2_count": 50,
                        "q3_count": 50,
                        "q4_count": 50,
                        "q5_count": 50,
                        "thin_bucket_count": 0,
                        "passes_minimum_bucket_count": True,
                    }
                    for _index in range(93)
                ],
                "primary_no_cohort_zero_score_month_count": 2,
                "primary_no_cohort_zero_score_months": ["20180131", "20180228"],
                "primary_incomplete_size_coverage_month_count": 1,
                "primary_incomplete_size_coverage_months": ["20180330"],
                "primary_factor_available_observation_count": 40000,
                "ep_non_positive_earnings_excluded_observation_count": 1200,
                "ep_insufficient_ttm_coverage_observation_count": 800,
                "return_exit_scheduled_count": 900,
                "return_exit_terminal_last_trade_count": 0,
                "return_exit_next_available_count": 0,
                "return_exit_missing_non_terminal_count": 0,
                "missing_signal_rows": 0,
                "missing_return_rows": 0,
                "full_main_board_endpoint_results_count": 23718,
                "evaluated_stock_return_rows": 1000,
                "result_cell_count": 28,
            },
            "result_cells": self._cells(),
            "sub_period_robustness": {
                "split_rule": "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves",
                "valid_cohort_count": 50,
                "split_index": 25,
                "first_half": {"cohort_count": 25, "mean_net_excess": 0.001, "hac_t_stat": 0.5, "hac_lag_months": 24},
                "second_half": {"cohort_count": 25, "mean_net_excess": -0.001, "hac_t_stat": -0.4, "hac_lag_months": 24},
                "both_halves_mean_excess_positive": False,
            },
            "risk_gate_result": {
                "method": "rolling_overlapping_monthly_tranche_portfolio_nav",
                "benchmark_construction": "option_a_parallel_same_as_of_schedule_horizon_and_ramp_holding_csi300_total_return_instead_of_selected_basket",
                "cost_applied_to_benchmark_tranches": False,
                "tranche_count": 70,
                "relative_nav_checkpoint_count": 70,
                "relative_nav_max_drawdown": -0.22,
                "absolute_strategy_nav_max_drawdown": -0.31,
                "minimum_allowed_relative_nav_drawdown": -0.15,
                "relative_nav_by_checkpoint": [
                    {"as_of": "20200131", "active_tranche_count": 12, "relative_nav": 1.01},
                    {"as_of": "20200229", "active_tranche_count": 13, "relative_nav": 0.98},
                ],
            },
            "decision": {
                "research_verdict": "falsified_large_cap_ep_value_under_frozen_rules",
                "is_statistical_alpha_clue": False,
                "is_tradeable_candidate": False,
                "statistical_alpha_clue_count": 0,
                "tradeable_candidate_count": 0,
                "primary_cell_id": PRIMARY_CELL_ID,
                "primary_cell_passed_statistical_gates": False,
                "sub_period_both_halves_mean_excess_positive": False,
                "relative_nav_max_drawdown": -0.22,
                "relative_nav_drawdown_gate_passed": False,
                "risk_gate_affects_tradeable_label_only_not_alpha_clue": True,
                "secondary_benchmark_required_for_alpha_clue": False,
                "diagnostics_can_rescue_primary_failure": False,
                "alpha_found_for_production": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "plain_result": "Large-cap ep_value is falsified under the frozen single-primary-cell design.",
                "next_action": "Do not rescue diagnostics without a new reviewed preregistration and ledger.",
            },
            "ledger_update_required_after_commit": {
                "ledger_ref": "research/ledgers/a_long_large_cap_ep_value_program_test_budget_ledger_20260608.json",
                "spends_singleton_test": True,
                "test_id": "a_long_large_cap_ep_value_20260608",
                "runner_writes_ledger": True,
                "ledger_write_timing": "pending_summary_then_ledger_then_final_summary",
                "ledger_status_after_runner": "active_no_new_test_authorized",
            },
            "prohibited_claims": {
                "production_ready": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "ep_value_proven": False,
                "in_sample_clue_is_out_of_sample_proof": False,
                "datahub_authorized": False,
                "broker_or_order_automation_authorized": False,
            },
            "result_artifacts": ["research/results/a_long_large_cap_ep_value_20260608/execution_summary.json"],
            "limitations": ["research-only"],
        }

    def test_summary_schema_accepts_valid_shape(self) -> None:
        payload = self._valid_summary()

        self.assertEqual(len(payload["result_cells"]), 28)
        self.assertEqual(self._validate(SUMMARY_SCHEMA_PATH, payload), [])

    def test_summary_schema_accepts_two_tier_clue_and_tradeable(self) -> None:
        payload = self._valid_summary()
        payload["sub_period_robustness"]["second_half"]["mean_net_excess"] = 0.002
        payload["sub_period_robustness"]["both_halves_mean_excess_positive"] = True
        payload["risk_gate_result"]["relative_nav_max_drawdown"] = -0.05
        payload["decision"].update(
            {
                "research_verdict": "statistical_alpha_clue_research_only",
                "is_statistical_alpha_clue": True,
                "is_tradeable_candidate": True,
                "statistical_alpha_clue_count": 1,
                "tradeable_candidate_count": 1,
                "primary_cell_passed_statistical_gates": True,
                "sub_period_both_halves_mean_excess_positive": True,
                "relative_nav_max_drawdown": -0.05,
                "relative_nav_drawdown_gate_passed": True,
            }
        )
        self.assertEqual(self._validate(SUMMARY_SCHEMA_PATH, payload), [])

    def test_summary_schema_rejects_production_or_rescue_claims(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["scope"]["provider_call_executed"] = True
        invalid["scope"]["production_use_allowed"] = True
        invalid["execution_gates"]["tracked_summary_contains_endpoint_results"] = True
        invalid["decision"]["diagnostics_can_rescue_primary_failure"] = True
        invalid["decision"]["risk_gate_affects_tradeable_label_only_not_alpha_clue"] = False
        invalid["prohibited_claims"]["ship_gate_evidence"] = True

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 6)

    def test_summary_schema_rejects_earnings_basis_or_denominator_search(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["search_design"]["earnings_basis_search_executed"] = True
        invalid["search_design"]["denominator_field_search_executed"] = True

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 2)

    def test_summary_schema_rejects_summed_excess_drawdown_gate_and_benchmark_cost(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["risk_gate_result"]["cost_applied_to_benchmark_tranches"] = True
        invalid["risk_gate_result"]["method"] = "summed_overlapping_cohort_excess_drawdown"

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 2)

    def test_summary_schema_rejects_invalid_research_verdict(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["decision"]["research_verdict"] = "candidate_alpha_clue_research_only"

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)

    def test_summary_schema_rejects_raw_injected_execution_diagnostics(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["execution_diagnostics"]["raw_rows"] = [{"ts_code": "000001.SZ"}]

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)

    def test_summary_schema_rejects_wrong_cell_count(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["result_cells"] = invalid["result_cells"][:27]

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)

    def test_summary_schema_rejects_duplicate_primary_role(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        for cell in invalid["result_cells"]:
            if cell["cell_id"] != PRIMARY_CELL_ID:
                cell["diagnostic_role"] = "primary_decision_cell"
                break

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)

    def test_summary_schema_rejects_thin_primary_size_bucket_coverage(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["execution_diagnostics"]["primary_size_neutral_thin_month_count"] = 1
        invalid["execution_diagnostics"]["primary_size_neutral_min_bucket_observation_count"] = 49
        invalid["execution_diagnostics"]["primary_size_neutral_bucket_coverage_by_month"][0]["q2_count"] = 49
        invalid["execution_diagnostics"]["primary_size_neutral_bucket_coverage_by_month"][0]["thin_bucket_count"] = 1
        invalid["execution_diagnostics"]["primary_size_neutral_bucket_coverage_by_month"][0][
            "passes_minimum_bucket_count"
        ] = False

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 4)

    def test_summary_schema_rejects_non_primary_cell_id_metadata_mismatch(self) -> None:
        # A non-primary result cell keeps its expected cell_id but carries wrong view / horizon /
        # benchmark; the per-cell_id if/then pin must reject it on the schema alone.
        invalid = copy.deepcopy(self._valid_summary())
        for cell in invalid["result_cells"]:
            if cell["cell_id"] == "ep_value_non_neutral_equal_weight_252d_CSI300":
                cell["view"] = "industry_size_neutral"
                cell["horizon_trading_days"] = 504
                cell["benchmark"] = "CSI1000"
                break

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)

    def test_summary_schema_rejects_falsified_verdict_with_clue_true(self) -> None:
        # research_verdict falsified while is_statistical_alpha_clue true (and clue count / primary-pass
        # set) must be rejected by the schema's decision invariants.
        invalid = copy.deepcopy(self._valid_summary())
        invalid["decision"].update(
            {
                "research_verdict": "falsified_large_cap_ep_value_under_frozen_rules",
                "is_statistical_alpha_clue": True,
                "statistical_alpha_clue_count": 1,
                "primary_cell_passed_statistical_gates": True,
            }
        )

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)

    def test_summary_schema_rejects_tradeable_without_clue_and_gate(self) -> None:
        # is_tradeable_candidate true while the clue and drawdown gates are false must be rejected by
        # the schema's decision invariants.
        invalid = copy.deepcopy(self._valid_summary())
        invalid["decision"].update(
            {
                "is_tradeable_candidate": True,
                "tradeable_candidate_count": 1,
                "is_statistical_alpha_clue": False,
                "relative_nav_drawdown_gate_passed": False,
            }
        )

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)


if __name__ == "__main__":
    unittest.main()
