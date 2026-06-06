from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


SCHEMA_PATH = Path("schemas/a_long_full_main_board_signal_search_execution_packet.schema.json")
ARTIFACT_PATH = Path("docs/a_long_full_main_board_signal_search_execution_packet_20260605.json")
BOUNDARY_PATH = Path("docs/a_long_scaled_delisted_no_industry_boundary_decision_20260605.json")
REPAIR_SUMMARY_PATH = Path("docs/a_long_main_board_sw_coverage_repair_execution_summary_20260604.json")


class ALongFullMainBoardSignalSearchExecutionPacketSchemaTest(unittest.TestCase):
    def _load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_schema(self) -> dict:
        return self._load_json(SCHEMA_PATH)

    def _load_artifact(self) -> dict:
        return self._load_json(ARTIFACT_PATH)

    def _validate(self, payload: dict) -> list:
        schema = self._load_schema()
        Draft7Validator.check_schema(schema)
        return list(Draft7Validator(schema).iter_errors(payload))

    def test_schema_and_artifact_validate_when_jsonschema_available(self) -> None:
        schema = self._load_schema()
        artifact = self._load_artifact()

        Draft7Validator.check_schema(schema)
        self.assertEqual(list(Draft7Validator(schema).iter_errors(artifact)), [])

    def test_artifact_does_not_execute_but_allows_future_reviewed_run(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertTrue(scope["research_only"])
        self.assertFalse(scope["provider_calls_executed_by_this_artifact"])
        self.assertFalse(scope["tushare_calls_executed_by_this_artifact"])
        self.assertFalse(scope["data_fetch_executed_by_this_artifact"])
        self.assertFalse(scope["raw_payloads_read_by_this_artifact"])
        self.assertFalse(scope["signal_search_executed_by_this_artifact"])
        self.assertTrue(scope["ready_for_later_execution_after_independent_review"])
        self.assertTrue(scope["actual_tushare_calls_require_post_review_execute_command"])
        self.assertTrue(scope["full_main_board_data_pull_allowed_after_gates"])
        self.assertTrue(scope["full_main_board_signal_search_allowed_after_gates"])
        self.assertFalse(scope["full_market_or_cross_board_pull_allowed"])
        self.assertFalse(scope["production_use_allowed"])
        self.assertFalse(scope["ship_gate_claim_allowed"])
        self.assertFalse(scope["full_size_manual_use_allowed"])

    def test_boundary_matches_approved_scaled_decision_and_repair_summary(self) -> None:
        artifact = self._load_artifact()
        boundary = self._load_json(BOUNDARY_PATH)["reviewed_boundary"]
        repair = self._load_json(REPAIR_SUMMARY_PATH)
        execution_boundary = artifact["execution_boundary"]

        self.assertTrue(artifact["boundary_approval"]["claude_review_pass_recorded"])
        self.assertTrue(artifact["boundary_approval"]["user_approval_recorded"])
        self.assertEqual(execution_boundary["main_board_active_count_from_preflight"], boundary["main_board_active_count"])
        self.assertEqual(
            execution_boundary["main_board_delisted_2018_2025_count_from_preflight"],
            boundary["main_board_delisted_2018_2025_count"],
        )
        self.assertEqual(
            execution_boundary["reviewed_no_industry_exception_count"],
            boundary["scaled_no_industry_boundary_count_if_approved"],
        )
        self.assertEqual(
            execution_boundary["active_delisting_shell_symbols"],
            repair["active_delisting_shell_boundary"]["detected_symbols"],
        )
        self.assertFalse(execution_boundary["manual_industry_fill_allowed"])
        self.assertFalse(execution_boundary["drop_boundary_names_from_returns_or_risk_allowed"])
        self.assertTrue(execution_boundary["industry_denominator_exclusion_only"])

    def test_run_plan_requires_audit_before_signal_and_spends_ledger(self) -> None:
        plan = self._load_artifact()["audit_and_signal_plan"]

        self.assertTrue(plan["full_data_integrity_audit_required_before_signal_search"])
        self.assertTrue(plan["abort_signal_search_if_audit_fails"])
        self.assertEqual(plan["preregistration_ref"], "research/preregistrations/a_long_signal_search_preregistration_20260604.json")
        self.assertEqual(plan["ledger_ref"], "research/ledgers/a_long_signal_search_program_test_budget_ledger_20260604.json")
        self.assertEqual(
            set(plan["allowed_signal_families"]),
            {"profitability_quality", "cash_conversion", "balance_sheet_strength", "earnings_stability"},
        )
        self.assertEqual(plan["exit_horizons_trading_days"], [252, 504])
        self.assertEqual(plan["primary_benchmark"], "CSI300")
        self.assertEqual(plan["secondary_benchmark"], "CSI1000")
        self.assertEqual(
            plan["benchmark_return_basis"],
            "benchmark_total_return_index_next_trading_day_close_to_same_exit_close",
        )
        self.assertEqual(
            plan["benchmark_access_probe_ref"],
            "docs/a_long_total_return_benchmark_access_probe_summary_20260606.json",
        )
        self.assertEqual(plan["benchmark_access_status"], "total_return_close_available_close_to_close_amendment_selected")
        self.assertEqual(
            plan["required_total_return_benchmark_call_ids"],
            ["index_daily_H00300_CSI_2018_2025", "index_daily_H00852_CSI_2018_2025"],
        )
        self.assertEqual(plan["required_selection_time_status_call_id"], "namechange_2018_2025")
        self.assertFalse(plan["price_index_benchmark_allowed"])
        self.assertFalse(plan["price_index_fallback_allowed"])
        self.assertFalse(plan["derived_total_return_open_allowed"])
        self.assertTrue(plan["total_return_with_adj_factor_and_dividend_lineage_required"])
        self.assertTrue(plan["same_anchor_required"])
        self.assertEqual(plan["t_stat_method"], "newey_west_hac_on_monthly_overlapping_cohorts")
        self.assertEqual(
            plan["hac_lag_rule"],
            "ceil_horizon_trading_days_div_21_capped_at_monthly_cohort_count_minus_1",
        )
        self.assertTrue(plan["monthly_cohort_count_is_not_independent_n"])
        self.assertEqual(plan["earnings_stability_basis"], "same_period_yoy_profit_dedt_growth_volatility")
        self.assertFalse(plan["mixed_ytd_quarter_sequence_allowed"])
        self.assertEqual(plan["minimum_earnings_stability_yoy_growths"], 3)
        self.assertEqual(plan["min_allowed_monthly_excess_drawdown"], -0.15)
        self.assertFalse(plan["parameter_sweep_allowed"])
        self.assertFalse(plan["post_result_rescue_slicing_allowed"])
        self.assertTrue(plan["ledger_spend_required_if_signal_executes"])

    def test_data_pull_budget_and_storage_are_locked(self) -> None:
        artifact = self._load_artifact()
        pull = artifact["data_pull_plan"]
        storage = artifact["storage_and_output_boundary"]

        self.assertEqual(pull["estimated_symbol_count"], 3387)
        self.assertEqual(pull["planned_total_endpoint_calls"], 23718)
        self.assertIn("security_name_change", pull["tables"])
        self.assertEqual(pull["benchmark_total_return_index_codes"], ["H00300.CSI", "H00852.CSI"])
        self.assertFalse(pull["benchmark_price_index_codes_allowed"])
        self.assertEqual(pull["benchmark_total_return_required_fields"], ["ts_code", "trade_date", "close"])
        self.assertLessEqual(pull["planned_total_endpoint_calls"], pull["max_total_endpoint_calls"])
        self.assertEqual(pull["retry_count_allowed"], 0)
        self.assertTrue(pull["checkpoint_resume_required"])
        self.assertGreaterEqual(pull["minimum_seconds_between_network_calls"], 1.0)
        self.assertTrue(storage["raw_output_root_must_be_gitignored"])
        self.assertFalse(storage["raw_retention_authorizes_production_storage"])

    def test_scope_creep_is_rejected_by_schema(self) -> None:
        invalid = copy.deepcopy(self._load_artifact())
        invalid["scope"]["provider_calls_executed_by_this_artifact"] = True
        invalid["scope"]["production_use_allowed"] = True
        invalid["scope"]["ship_gate_claim_allowed"] = True
        invalid["execution_boundary"]["manual_industry_fill_allowed"] = True
        invalid["execution_boundary"]["drop_boundary_names_from_returns_or_risk_allowed"] = True
        invalid["data_pull_plan"]["retry_count_allowed"] = 1
        invalid["audit_and_signal_plan"]["parameter_sweep_allowed"] = True
        invalid["prohibited_claims"]["a_long_alpha_found"] = True

        self.assertGreaterEqual(len(self._validate(invalid)), 8)


if __name__ == "__main__":
    unittest.main()
