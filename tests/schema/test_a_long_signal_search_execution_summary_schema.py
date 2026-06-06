from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/a_long_signal_search_execution_summary.schema.json")
SUMMARY_PATH = Path("research/results/a_long_signal_search_20260604/execution_summary.json")


class ALongSignalSearchExecutionSummarySchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _validate(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        schema = self._load_schema()
        Draft7Validator.check_schema(schema)
        return list(Draft7Validator(schema).iter_errors(payload))

    def _valid_summary(self) -> dict:
        cells = []
        for family in ["profitability_quality", "cash_conversion", "balance_sheet_strength", "earnings_stability"]:
            for view in ["non_neutral", "industry_neutral"]:
                for horizon in [252, 504]:
                    cells.append(
                        {
                            "signal_family": family,
                            "view": view,
                            "horizon_trading_days": horizon,
                            "monthly_cohort_count": 50,
                            "mean_monthly_cohort_net_excess": 0.001,
                            "monthly_cohort_std": 0.01,
                            "monthly_clustered_t_stat": 0.7,
                            "p_value": 0.48,
                            "bh_adjusted_p_value": 0.8,
                            "positive_month_count": 27,
                            "max_drawdown_on_monthly_excess": -0.05,
                            "top_symbol_selection_share": 0.05,
                            "max_single_year_positive_return_share": 0.2,
                            "passes_minimum_monthly_cohorts": True,
                            "passes_name_concentration_guard": True,
                            "passes_single_year_concentration_guard": True,
                        }
                    )
        return {
            "schema_name": "a_long_signal_search_execution_summary",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-06T00:00:00+00:00",
            "artifact_id": "a_long_signal_search_execution_summary_20260604",
            "source_refs": [
                "research/preregistrations/a_long_signal_search_preregistration_20260604.json",
                "research/ledgers/a_long_signal_search_program_test_budget_ledger_20260604.json",
                "docs/a_long_full_main_board_materialization_execution_summary_20260605.json",
                "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
                "research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv",
                "docs/a_long_scaled_delisted_no_industry_boundary_decision_20260605.json",
            ],
            "scope": {
                "phase": "7a_alpha_validation",
                "purpose": "a_long_full_main_board_signal_search_execution",
                "lane_id": "a_long",
                "market": "A-share",
                "research_only": True,
                "provider_call_executed": False,
                "tushare_call_executed": False,
                "data_fetch_executed": False,
                "materialized_raw_read_only": True,
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
                "ledger_unspent_before_run": True,
                "full_main_board_audit_passed": True,
                "restatement_exclusion_list_loaded": True,
                "restatement_exclusion_groups_expected": 1504,
                "restatement_exclusion_groups_found_in_raw": 1504,
                "restatement_exclusion_list_applied": True,
                "no_industry_boundary_consumed": True,
                "no_network_calls_executed": True,
                "tracked_summary_contains_raw_rows": False,
                "tracked_summary_contains_endpoint_results": False,
                "tracked_summary_contains_secret": False,
                "tracked_summary_contains_request_url": False,
            },
            "full_main_board_boundary": {
                "board_scope": "main_board_only",
                "start_date": "20180101",
                "end_date": "20251231",
                "active_symbol_count": 3200,
                "delisted_symbol_count": 187,
                "candidate_universe_count": 3387,
                "reviewed_no_industry_exception_count": 191,
                "exception_symbols_retained_in_returns_and_risk": True,
                "exception_symbols_excluded_only_from_industry_denominators": True,
                "monthly_as_of_count": 96,
            },
            "search_design": {
                "allowed_signal_families": ["profitability_quality", "cash_conversion", "balance_sheet_strength", "earnings_stability"],
                "horizons_trading_days": [252, 504],
                "primary_benchmark": "CSI300",
                "secondary_benchmark": "CSI1000",
                "views": ["non_neutral", "industry_neutral"],
                "top_fraction": 0.2,
                "minimum_top_count_per_month": 10,
                "minimum_monthly_cohorts": 48,
                "multiple_testing_correction": "benjamini_hochberg_fdr",
                "round_trip_cost": 0.0026,
                "same_anchor_open_to_close": True,
                "max_top_symbol_selection_share": 0.2,
                "max_single_year_positive_return_share": 0.35,
                "parameter_sweep_executed": False,
                "post_result_rescue_slicing_executed": False,
            },
            "execution_diagnostics": {
                "as_of_count": 96,
                "symbol_count": 3387,
                "restatement_exclusion_group_count": 1504,
                "industry_denominator_exclusion_symbol_count": 191,
                "scored_pit_universe_excluded_before_list_count": 0,
                "scored_pit_universe_excluded_after_delist_count": 0,
                "missing_signal_rows": 0,
                "missing_return_rows": 0,
                "endpoint_results_count": 23717,
                "evaluated_stock_return_rows": 1,
                "result_cell_count": 16,
            },
            "result_cells": cells,
            "decision": {
                "research_verdict": "no_alpha_found_under_frozen_rules",
                "candidate_alpha_clue_count": 0,
                "alpha_found_for_production": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "plain_result": "Signal search found no usable alpha clue under the frozen rules.",
                "next_action": "Do not rescue by changing thresholds.",
            },
            "ledger_update_required_after_commit": {
                "ledger_ref": "research/ledgers/a_long_signal_search_program_test_budget_ledger_20260604.json",
                "spends_singleton_test": True,
                "test_id": "a_long_signal_search_preregistration_20260604",
                "runner_writes_ledger": True,
                "ledger_write_timing": "after_valid_summary_write",
                "ledger_status_after_runner": "active_no_new_test_authorized",
            },
            "prohibited_claims": {
                "production_ready": False,
                "ship_gate_evidence": False,
                "full_size_allowed": False,
                "provider_selected": False,
                "datahub_authorized": False,
                "broker_or_order_automation_authorized": False,
            },
            "result_artifacts": ["research/results/a_long_signal_search_20260604/execution_summary.json"],
            "limitations": ["research-only"],
        }

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertEqual(schema["properties"]["schema_name"]["const"], "a_long_signal_search_execution_summary")
        self.assertFalse(schema["additionalProperties"])

    def test_minimal_summary_validates(self) -> None:
        self.assertEqual(self._validate(self._valid_summary()), [])

    def test_generated_summary_validates_when_present(self) -> None:
        if not SUMMARY_PATH.exists():
            raise unittest.SkipTest("signal-search execution summary has not been generated yet")

        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self._validate(summary), [])
        text = SUMMARY_PATH.read_text(encoding="utf-8")
        self.assertNotIn('"records"', text)
        self.assertNotIn('"endpoint_results"', text)
        self.assertNotIn("TUSHARE_TOKEN", text)
        self.assertNotIn("http", text.lower())

    def test_scope_creep_is_rejected(self) -> None:
        invalid = copy.deepcopy(self._valid_summary())
        invalid["scope"]["provider_call_executed"] = True
        invalid["scope"]["production_use_allowed"] = True
        invalid["execution_gates"]["restatement_exclusion_list_applied"] = False
        invalid["execution_gates"]["tracked_summary_contains_raw_rows"] = True
        invalid["full_main_board_boundary"]["exception_symbols_retained_in_returns_and_risk"] = False
        invalid["search_design"]["parameter_sweep_executed"] = True
        invalid["decision"]["ship_gate_evidence"] = True
        invalid["prohibited_claims"]["full_size_allowed"] = True

        self.assertGreaterEqual(len(self._validate(invalid)), 8)


if __name__ == "__main__":
    unittest.main()
