from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


PACKET_SCHEMA_PATH = Path("schemas/a_long_large_cap_pure_quality_signal_search_execution_packet.schema.json")
PACKET_PATH = Path("docs/a_long_large_cap_pure_quality_signal_search_execution_packet_20260607.json")
SUMMARY_SCHEMA_PATH = Path("schemas/a_long_large_cap_pure_quality_signal_search_execution_summary.schema.json")


class ALongLargeCapPureQualitySignalSearchSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _validate(self, schema_path: Path, payload: dict) -> list:
        schema = self._load_json(schema_path)
        Draft7Validator.check_schema(schema)
        return list(Draft7Validator(schema).iter_errors(payload))

    def test_packet_schema_and_artifact_validate(self) -> None:
        schema = self._load_json(PACKET_SCHEMA_PATH)
        artifact = self._load_json(PACKET_PATH)

        Draft7Validator.check_schema(schema)
        self.assertEqual(list(Draft7Validator(schema).iter_errors(artifact)), [])

    def test_packet_rejects_scope_creep_and_primary_cell_drift(self) -> None:
        invalid = copy.deepcopy(self._load_json(PACKET_PATH))
        invalid["scope"]["provider_calls_executed_by_this_artifact"] = True
        invalid["scope"]["signal_search_executed_by_this_artifact"] = True
        invalid["scope"]["production_use_allowed"] = True
        invalid["execution_boundary"]["provider_call_required_for_future_execution"] = True
        invalid["signal_plan"]["secondary_benchmark_required_for_candidate_alpha"] = True
        invalid["signal_plan"]["multiple_testing_adjustment_for_decision"] = "benjamini_hochberg_fdr"
        invalid["prohibited_claims"]["a_long_alpha_found"] = True

        self.assertGreaterEqual(len(self._validate(PACKET_SCHEMA_PATH, invalid)), 7)

    def test_packet_locks_reviewed_boundaries(self) -> None:
        artifact = self._load_json(PACKET_PATH)

        self.assertEqual(
            artifact["execution_boundary"]["market_cap_audit_report_ref"],
            "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json",
        )
        self.assertEqual(artifact["execution_boundary"]["selected_market_cap_field"], "circ_mv")
        self.assertEqual(artifact["execution_boundary"]["universe_size_n"], 500)
        self.assertEqual(
            artifact["execution_boundary"]["reviewed_data_quality_exclusion_policy"],
            "drop_documented_exclusions_then_backfill_next_main_board_by_circ_mv",
        )
        self.assertFalse(artifact["execution_boundary"]["provider_call_required_for_future_execution"])
        self.assertTrue(artifact["execution_boundary"]["ledger_spend_required_if_signal_executes"])
        self.assertEqual(artifact["signal_plan"]["primary_benchmark"], "CSI300")
        self.assertEqual(artifact["signal_plan"]["diagnostic_benchmark"], "CSI1000")
        self.assertFalse(artifact["signal_plan"]["secondary_benchmark_required_for_candidate_alpha"])

    def _valid_summary(self) -> dict:
        cells = []
        signal_specs = []
        for view in ["industry_size_neutral", "non_neutral", "industry_neutral", "size_neutral"]:
            for horizon in [252, 504]:
                for benchmark in ["CSI300", "CSI1000"]:
                    signal_specs.append(("core_quality_composite_percentile_3factor", view, "equal_weight", horizon, benchmark))
        for horizon in [252, 504]:
            for benchmark in ["CSI300", "CSI1000"]:
                signal_specs.append(("core_quality_composite_percentile_3factor", "industry_size_neutral", "cap_weighted", horizon, benchmark))
        for signal_id in ["profitability_quality", "cash_conversion", "balance_sheet_strength", "earnings_stability"]:
            for horizon in [252, 504]:
                for benchmark in ["CSI300", "CSI1000"]:
                    signal_specs.append((signal_id, "industry_size_neutral", "equal_weight", horizon, benchmark))
        for signal_id, view, weighting, horizon, benchmark in signal_specs:
            is_primary = (
                signal_id == "core_quality_composite_percentile_3factor"
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
                    "max_drawdown_on_monthly_excess": -0.05,
                    "top_symbol_selection_share": 0.05,
                    "max_single_year_positive_return_share": 0.2,
                    "passes_minimum_monthly_cohorts": True,
                    "passes_minimum_top_count": True,
                    "passes_name_concentration_guard": True,
                    "passes_single_year_concentration_guard": True,
                    "passes_drawdown_guard": True
                }
            )
        return {
            "schema_name": "a_long_large_cap_pure_quality_signal_search_execution_summary",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-07T00:00:00+00:00",
            "artifact_id": "a_long_large_cap_pure_quality_signal_search_execution_summary_20260607",
            "source_refs": [
                "docs/a_long_large_cap_pure_quality_signal_search_execution_packet_20260607.json",
                "research/preregistrations/a_long_large_cap_pure_quality_20260607.json",
                "research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json",
                "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json",
                "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
                "docs/a_long_large_cap_data_quality_exclusion_decision_20260607.json",
                "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
                "research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv",
                "docs/a_long_total_return_benchmark_access_probe_summary_20260606.json"
            ],
            "scope": {
                "phase": "7a_alpha_validation",
                "purpose": "a_long_large_cap_pure_quality_signal_search_execution",
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
                "manual_order_only": True
            },
            "execution_gates": {
                "independent_review_confirmed": True,
                "post_review_execute_confirmed": True,
                "packet_validated": True,
                "preregistration_validated": True,
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
                "tracked_summary_contains_request_url": False
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
                "minimum_size_bucket_count": 100
            },
            "search_design": {
                "primary_signal_id": "core_quality_composite_percentile_3factor",
                "component_factors": ["profitability_quality", "cash_conversion", "balance_sheet_strength"],
                "diagnostic_factors": ["profitability_quality", "cash_conversion", "balance_sheet_strength", "earnings_stability"],
                "primary_view": "industry_size_neutral",
                "composite_views_reported": ["industry_size_neutral", "non_neutral", "industry_neutral", "size_neutral"],
                "cap_weighted_view_reported": True,
                "primary_horizon_trading_days": 504,
                "diagnostic_horizons_trading_days": [252],
                "primary_benchmark": "CSI300",
                "diagnostic_benchmark": "CSI1000",
                "secondary_benchmark_required_for_candidate_alpha": False,
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
                "min_allowed_monthly_excess_drawdown": -0.15,
                "max_top_symbol_selection_share": 0.2,
                "max_single_year_positive_return_share": 0.35,
                "multiple_testing_adjustment_for_decision": "not_applicable_single_primary_cell",
                "diagnostics_can_define_alpha": False,
                "parameter_sweep_executed": False,
                "post_result_rescue_slicing_executed": False
            },
            "execution_diagnostics": {
                "as_of_count": 96,
                "target_large_cap_universe_size": 500,
                "large_cap_universe_observations": 48000,
                "primary_composite_available_observation_count": 40000,
                "full_main_board_endpoint_results_count": 23718,
                "evaluated_stock_return_rows": 1000,
                "result_cell_count": 36
            },
            "result_cells": cells,
            "decision": {
                "research_verdict": "falsified_large_cap_pure_quality_under_frozen_rules",
                "candidate_alpha_clue_count": 0,
                "primary_cell_id": "core_quality_composite_percentile_3factor_industry_size_neutral_equal_weight_504d_CSI300",
                "primary_cell_passed": False,
                "secondary_benchmark_required_for_candidate_alpha": False,
                "diagnostics_can_rescue_primary_failure": False,
                "alpha_found_for_production": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "plain_result": "Large-cap pure-quality found no usable alpha under the frozen single-primary-cell rules.",
                "next_action": "Do not rescue diagnostics."
            },
            "ledger_update_required_after_commit": {
                "ledger_ref": "research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json",
                "spends_singleton_test": True,
                "test_id": "a_long_large_cap_pure_quality_20260607",
                "runner_writes_ledger": True,
                "ledger_write_timing": "pending_summary_then_ledger_then_final_summary",
                "ledger_status_after_runner": "active_no_new_test_authorized"
            },
            "prohibited_claims": {
                "production_ready": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "provider_selected": False,
                "datahub_authorized": False,
                "broker_or_order_automation_authorized": False
            },
            "result_artifacts": ["research/results/a_long_large_cap_pure_quality_20260607/execution_summary.json"],
            "limitations": ["research-only"]
        }

    def test_summary_schema_accepts_future_valid_shape(self) -> None:
        payload = self._valid_summary()

        self.assertEqual(self._validate(SUMMARY_SCHEMA_PATH, payload), [])

    def test_summary_schema_rejects_production_or_diagnostic_rescue_claims(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["scope"]["provider_call_executed"] = True
        invalid["scope"]["production_use_allowed"] = True
        invalid["execution_gates"]["tracked_summary_contains_endpoint_results"] = True
        invalid["decision"]["secondary_benchmark_required_for_candidate_alpha"] = True
        invalid["decision"]["diagnostics_can_rescue_primary_failure"] = True
        invalid["prohibited_claims"]["ship_gate_evidence"] = True

        self.assertGreaterEqual(len(self._validate(SUMMARY_SCHEMA_PATH, invalid)), 6)


if __name__ == "__main__":
    unittest.main()
