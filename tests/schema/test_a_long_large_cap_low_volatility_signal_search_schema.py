from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


SUMMARY_SCHEMA_PATH = Path("schemas/a_long_large_cap_low_volatility_signal_search_execution_summary.schema.json")


class ALongLargeCapLowVolatilitySignalSearchSchemaTest(unittest.TestCase):
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
                    specs.append(("low_volatility", view, "equal_weight", horizon, benchmark))
        for horizon in [252, 504]:
            for benchmark in ["CSI300", "CSI1000"]:
                specs.append(("low_volatility", "industry_size_neutral", "cap_weighted", horizon, benchmark))
        for signal_id in ["idiosyncratic_volatility_vs_csi300_low", "downside_semideviation_low"]:
            for horizon in [252, 504]:
                for benchmark in ["CSI300", "CSI1000"]:
                    specs.append((signal_id, "industry_size_neutral", "equal_weight", horizon, benchmark))

        cells = []
        for signal_id, view, weighting, horizon, benchmark in specs:
            is_primary = (
                signal_id == "low_volatility"
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
                    "monthly_cohort_count": 60,
                    "mean_monthly_cohort_net_excess": 0.001,
                    "monthly_cohort_std": 0.01,
                    "monthly_clustered_t_stat": 0.7,
                    "monthly_t_stat_method": "newey_west_hac_on_monthly_overlapping_cohorts",
                    "hac_lag_months": 24 if horizon == 504 else 12,
                    "p_value": 0.48,
                    "minimum_monthly_top_count": 100,
                    "positive_month_count": 33,
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
            "schema_name": "a_long_large_cap_low_volatility_signal_search_execution_summary",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-08T00:00:00+00:00",
            "artifact_id": "a_long_large_cap_low_volatility_signal_search_execution_summary_20260608",
            "source_refs": [
                "research/preregistrations/a_long_large_cap_low_volatility_20260608.json",
                "research/ledgers/a_long_large_cap_low_volatility_program_test_budget_ledger_20260608.json",
                "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json",
                "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
                "docs/a_long_large_cap_data_quality_exclusion_decision_20260607.json",
                "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
                "docs/a_long_total_return_benchmark_access_probe_summary_20260606.json",
            ],
            "scope": {
                "phase": "7a_alpha_validation",
                "purpose": "a_long_large_cap_low_volatility_signal_search_execution",
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
                "restatement_exclusion_required": False,
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
                "primary_signal_id": "low_volatility_percentile",
                "primary_factor": "low_volatility",
                "primary_factor_definition": "negative_trailing_252_trading_day_realized_volatility_of_daily_adj_factor_total_returns_as_of_each_as_of_date",
                "volatility_estimator": "sample_standard_deviation_of_daily_simple_total_returns",
                "trailing_window_trading_days": 252,
                "realized_vol_min_valid_daily_returns": 120,
                "trailing_volatility_lookback_and_forward_horizon_are_distinct_axes": True,
                "idiosyncratic_or_total_vol_choice": "total_volatility_frozen_no_search",
                "diagnostic_factors": ["idiosyncratic_volatility_vs_csi300_low", "downside_semideviation_low"],
                "primary_view": "industry_size_neutral",
                "low_volatility_views_reported": ["industry_size_neutral", "non_neutral", "industry_neutral", "size_neutral"],
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
                "multiple_testing_adjustment_for_decision": "not_applicable_single_primary_cell",
                "restatement_exclusion_required": False,
                "restatement_exclusion_not_applicable_reason": "low_volatility is a price-only signal with no fundamental restatement dependency, so the fundamental restatement-ambiguity exclusion does not apply to signal scoring",
                "diagnostics_can_define_alpha": False,
                "parameter_sweep_executed": False,
                "trailing_window_search_executed": False,
                "idiosyncratic_vs_total_vol_search_executed": False,
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
                "size_neutral_thin_bucket_count": 30,
                "primary_size_neutral_thin_month_count": 0,
                "primary_size_neutral_min_bucket_observation_count": 50,
                "primary_size_neutral_coverage_month_count": 90,
                "primary_size_neutral_bucket_coverage_by_month": [
                    {
                        "as_of": "20200131",
                        "q1_count": 100,
                        "q2_count": 100,
                        "q3_count": 100,
                        "q4_count": 100,
                        "q5_count": 100,
                        "thin_bucket_count": 0,
                        "passes_minimum_bucket_count": True,
                    }
                    for _index in range(90)
                ],
                "primary_no_cohort_zero_score_month_count": 2,
                "primary_no_cohort_zero_score_months": ["20180131", "20180228"],
                "primary_incomplete_size_coverage_month_count": 4,
                "primary_incomplete_size_coverage_months": ["20180330", "20180427", "20180531", "20180629"],
                "primary_factor_available_observation_count": 44000,
                "trailing_window_trading_days": 252,
                "realized_vol_min_valid_daily_returns": 120,
                "trailing_window_valid_low_volatility_observation_count": 44000,
                "insufficient_trailing_window_observation_count": 4000,
                "trailing_window_coverage_by_month": [
                    {
                        "as_of": "20200131",
                        "pit_member_count": 500,
                        "low_volatility_valid_count": 500,
                        "insufficient_trailing_window_count": 0,
                    }
                    for _index in range(96)
                ],
                "trailing_window_startup_excluded_month_count": 6,
                "trailing_window_startup_excluded_months": [
                    "20180131",
                    "20180228",
                    "20180330",
                    "20180427",
                    "20180531",
                    "20180629",
                ],
                "return_exit_scheduled_count": 900,
                "return_exit_terminal_last_trade_count": 0,
                "return_exit_next_available_count": 0,
                "return_exit_missing_non_terminal_count": 0,
                "missing_signal_rows": 4000,
                "missing_return_rows": 0,
                "full_main_board_endpoint_results_count": 23718,
                "evaluated_stock_return_rows": 1000,
                "result_cell_count": 28,
            },
            "result_cells": self._cells(),
            "sub_period_robustness": {
                "split_rule": "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves",
                "valid_cohort_count": 60,
                "split_index": 30,
                "first_half": {"cohort_count": 30, "mean_net_excess": 0.001, "hac_t_stat": 0.5, "hac_lag_months": 24},
                "second_half": {"cohort_count": 30, "mean_net_excess": -0.001, "hac_t_stat": -0.4, "hac_lag_months": 24},
                "both_halves_mean_excess_positive": False,
            },
            "risk_gate_result": {
                "method": "rolling_overlapping_monthly_tranche_portfolio_nav",
                "benchmark_construction": "option_a_parallel_same_as_of_schedule_horizon_and_ramp_holding_csi300_total_return_instead_of_selected_basket",
                "cost_applied_to_benchmark_tranches": False,
                "tranche_count": 64,
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
                "research_verdict": "falsified_large_cap_low_volatility_under_frozen_rules",
                "is_statistical_alpha_clue": False,
                "is_tradeable_candidate": False,
                "statistical_alpha_clue_count": 0,
                "tradeable_candidate_count": 0,
                "primary_cell_id": "low_volatility_industry_size_neutral_equal_weight_504d_CSI300",
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
                "plain_result": "Large-cap low_volatility is falsified under the frozen single-primary-cell design.",
                "next_action": "Do not rescue diagnostics without a new reviewed preregistration and ledger.",
            },
            "ledger_update_required_after_commit": {
                "ledger_ref": "research/ledgers/a_long_large_cap_low_volatility_program_test_budget_ledger_20260608.json",
                "spends_singleton_test": True,
                "test_id": "a_long_large_cap_low_volatility_20260608",
                "runner_writes_ledger": True,
                "ledger_write_timing": "pending_summary_then_ledger_then_final_summary",
                "ledger_status_after_runner": "active_no_new_test_authorized",
            },
            "prohibited_claims": {
                "production_ready": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "low_volatility_proven": False,
                "in_sample_clue_is_out_of_sample_proof": False,
                "datahub_authorized": False,
                "broker_or_order_automation_authorized": False,
            },
            "result_artifacts": ["research/results/a_long_large_cap_low_volatility_20260608/execution_summary.json"],
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

    def test_summary_schema_rejects_restatement_required_true(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["execution_gates"]["restatement_exclusion_required"] = True
        invalid["search_design"]["restatement_exclusion_required"] = True

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 2)

    def test_summary_schema_rejects_summed_excess_drawdown_gate_and_benchmark_cost(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["risk_gate_result"]["cost_applied_to_benchmark_tranches"] = True
        invalid["risk_gate_result"]["method"] = "summed_overlapping_cohort_excess_drawdown"

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 2)

    def test_summary_schema_rejects_invalid_research_verdict(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["decision"]["research_verdict"] = "falsified_large_cap_cash_conversion_under_frozen_rules"

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
        # force a non-primary cell to claim the primary role
        for cell in invalid["result_cells"]:
            if cell["cell_id"] != "low_volatility_industry_size_neutral_equal_weight_504d_CSI300":
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

    def test_summary_schema_rejects_cell_id_metadata_mismatch(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        for cell in invalid["result_cells"]:
            if cell["cell_id"] == "low_volatility_non_neutral_equal_weight_252d_CSI300":
                cell["benchmark"] = "CSI1000"  # cell_id still encodes CSI300 -> contradiction
                break
        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)

    def test_summary_schema_rejects_decision_verdict_clue_contradiction(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        # research_verdict claims a clue while is_statistical_alpha_clue / counts / pass-flag stay falsified.
        invalid["decision"]["research_verdict"] = "statistical_alpha_clue_research_only"
        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 1)

    def test_summary_schema_accepts_clue_but_not_tradeable(self) -> None:
        payload = self._valid_summary()
        payload["sub_period_robustness"]["second_half"]["mean_net_excess"] = 0.002
        payload["sub_period_robustness"]["both_halves_mean_excess_positive"] = True
        payload["risk_gate_result"]["relative_nav_max_drawdown"] = -0.30
        payload["decision"].update(
            {
                "research_verdict": "statistical_alpha_clue_research_only",
                "is_statistical_alpha_clue": True,
                "is_tradeable_candidate": False,
                "statistical_alpha_clue_count": 1,
                "tradeable_candidate_count": 0,
                "primary_cell_passed_statistical_gates": True,
                "sub_period_both_halves_mean_excess_positive": True,
                "relative_nav_max_drawdown": -0.30,
                "relative_nav_drawdown_gate_passed": False,
            }
        )
        self.assertEqual(self._validate(SUMMARY_SCHEMA_PATH, payload), [])


if __name__ == "__main__":
    unittest.main()
