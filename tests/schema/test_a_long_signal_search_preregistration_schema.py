from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


SCHEMA_PATH = Path("schemas/a_long_signal_search_preregistration.schema.json")
ARTIFACT_PATH = Path("research/preregistrations/a_long_signal_search_preregistration_20260604.json")
LEDGER_SCHEMA_PATH = Path("schemas/program_test_budget_ledger.schema.json")
LEDGER_ARTIFACT_PATH = Path("research/ledgers/a_long_signal_search_program_test_budget_ledger_20260604.json")


class ALongSignalSearchPreregistrationSchemaTest(unittest.TestCase):
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

    def test_scope_blocks_signal_run_data_fetch_provider_datahub_and_ship_gate(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertTrue(scope["research_only"])
        self.assertTrue(scope["manual_order_only"])
        self.assertEqual(scope["lane_id"], "a_long")
        for field_name in [
            "signal_search_executed_by_this_artifact",
            "signal_search_authorized_by_this_artifact",
            "data_fetch_allowed_by_this_artifact",
            "provider_call_allowed_by_this_artifact",
            "full_market_or_full_universe_run_authorized_by_this_artifact",
            "datahub_allowed",
            "production_use_allowed",
            "ship_gate_claim_allowed",
            "full_size_manual_use_allowed",
            "broker_or_order_automation_allowed",
        ]:
            with self.subTest(field_name=field_name):
                self.assertFalse(scope[field_name])

    def test_data_gate_keeps_fixed_panel_as_route_proof_only(self) -> None:
        data_gate = self._load_artifact()["data_gate"]
        prohibited = self._load_artifact()["prohibited_claims"]

        self.assertEqual(data_gate["required_audit_status"], "passed_fixed_panel_data_integrity_for_signal_preregistration")
        self.assertTrue(data_gate["observed_hard_checks_pass"])
        self.assertEqual(data_gate["observed_self_tests_passed"], 11)
        self.assertEqual(data_gate["usable_start_year"], 2018)
        self.assertTrue(data_gate["fixed_panel_route_proof_only"])
        self.assertEqual(data_gate["fixed_panel_symbol_count"], 9)
        self.assertTrue(data_gate["fixed_panel_not_full_market"])
        self.assertTrue(data_gate["fixed_panel_not_full_universe"])
        self.assertFalse(data_gate["full_main_board_universe_ready"])
        self.assertFalse(data_gate["signal_runner_ready"])
        self.assertFalse(prohibited["fixed_panel_proves_alpha"])
        self.assertFalse(prohibited["full_universe_ready"])
        self.assertFalse(prohibited["signal_search_authorized"])

    def test_future_universe_requires_main_board_pit_and_delisting_returns(self) -> None:
        universe = self._load_artifact()["search_design"]["candidate_universe_rule"]

        self.assertEqual(universe["board_scope"], "main_board_only")
        self.assertTrue(universe["future_execution_must_not_use_fixed_9_symbol_panel_as_alpha_proof"])
        self.assertTrue(universe["future_execution_requires_reviewed_main_board_candidate_universe"])
        self.assertTrue(universe["pit_list_delist_required"])
        self.assertTrue(universe["delisting_return_required"])
        self.assertTrue(universe["st_star_bse_chinext_excluded"])

    def test_signal_families_are_frozen_and_unvalidated_valuation_is_blocked(self) -> None:
        design = self._load_artifact()["search_design"]

        self.assertEqual(
            set(design["allowed_signal_families"]),
            {"profitability_quality", "cash_conversion", "balance_sheet_strength", "earnings_stability"},
        )
        signal_policy = design["signal_family_measurement_policy"]
        self.assertEqual(signal_policy["earnings_stability_basis"], "same_period_yoy_profit_dedt_growth_volatility")
        self.assertFalse(signal_policy["mixed_ytd_quarter_sequence_allowed"])
        self.assertEqual(signal_policy["minimum_same_period_yoy_growths"], 3)
        self.assertIn("valuation_without_share_count_or_market_cap_lineage", design["blocked_signal_families"])
        self.assertFalse(design["multiple_testing_policy"]["parameter_sweep_allowed"])
        self.assertFalse(design["multiple_testing_policy"]["post_result_rescue_slicing_allowed"])
        self.assertEqual(design["multiple_testing_policy"]["t_stat_method"], "newey_west_hac_on_monthly_overlapping_cohorts")
        self.assertEqual(
            design["multiple_testing_policy"]["hac_lag_rule"],
            "ceil_horizon_trading_days_div_21_capped_at_monthly_cohort_count_minus_1",
        )
        self.assertTrue(design["multiple_testing_policy"]["monthly_cohort_count_is_not_independent_n"])
        self.assertGreaterEqual(design["multiple_testing_policy"]["minimum_monthly_cohorts"], 48)
        self.assertEqual(design["multiple_testing_policy"]["min_allowed_monthly_excess_drawdown"], -0.15)

    def test_measurement_basis_locks_same_anchor_close_to_close_total_vs_total_and_benchmarks(self) -> None:
        design = self._load_artifact()["search_design"]
        measurement = design["entry_exit_measurement_rule"]
        benchmark = design["benchmark_rule"]

        self.assertEqual(measurement["entry_rule"], "next_trading_day_close_after_as_of")
        self.assertEqual(measurement["exit_horizons_trading_days"], [252, 504])
        self.assertEqual(measurement["stock_return_basis"], "stock_total_return_adj_factor_next_trading_day_close_to_exit_close")
        self.assertTrue(measurement["same_anchor_required"])
        self.assertTrue(measurement["dividend_and_adj_factor_required"])
        self.assertEqual(benchmark["primary_benchmark"], "CSI300")
        self.assertEqual(benchmark["secondary_benchmark"], "CSI1000")
        self.assertEqual(benchmark["benchmark_return_basis"], "benchmark_total_return_index_next_trading_day_close_to_same_exit_close")
        self.assertEqual(benchmark["benchmark_access_status"], "total_return_close_available_close_to_close_amendment_selected")
        self.assertFalse(benchmark["price_index_benchmark_allowed"])
        self.assertFalse(benchmark["price_index_fallback_allowed"])
        self.assertFalse(benchmark["derived_total_return_open_allowed"])
        self.assertTrue(benchmark["same_anchor_required"])

    def test_industry_exception_retains_delisted_returns_and_blocks_silent_fill(self) -> None:
        industry = self._load_artifact()["search_design"]["industry_policy"]

        self.assertEqual(
            industry["reviewed_exception_boundary_ref"],
            "docs/a_long_scaled_delisted_no_industry_boundary_decision_20260605.json",
        )
        self.assertEqual(industry["exception_symbol_set_source"], "reviewed_191_name_boundary_from_sw_repair_summary")
        self.assertEqual(industry["exception_count"], 191)
        self.assertEqual(industry["exception_rate_pct"], 5.639209)
        self.assertLessEqual(industry["exception_rate_pct"], industry["max_exception_rate_pct"])
        self.assertTrue(industry["reviewed_delisted_missing_industry_exception_allowed"])
        self.assertTrue(industry["active_investable_missing_industry_hard_fail"])
        self.assertTrue(industry["active_delisting_shell_exception_allowed_only_by_boundary"])
        self.assertTrue(industry["exception_retained_in_returns_and_risk"])
        self.assertTrue(industry["exception_excluded_only_from_industry_denominators"])
        self.assertTrue(industry["terminal_delisting_return_required"])
        self.assertTrue(industry["selection_time_st_or_delisting_name_veto_required"])
        self.assertTrue(industry["pit_selection_status_source_required"])
        self.assertFalse(industry["current_stock_basic_name_veto_allowed"])
        self.assertFalse(industry["silent_industry_fill_allowed"])
        self.assertFalse(industry["manual_industry_fill_allowed"])

    def test_restatement_exclusion_list_is_mandatory_for_future_signal_inputs(self) -> None:
        policy = self._load_artifact()["search_design"]["restatement_exclusion_policy"]

        self.assertEqual(
            policy["full_main_board_audit_report_ref"],
            "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
        )
        self.assertEqual(
            policy["exclusion_list_ref"],
            "research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv",
        )
        self.assertTrue(policy["mandatory_exclusion_from_signal_inputs"])
        self.assertEqual(policy["expected_exclusion_group_count"], 1504)
        self.assertLessEqual(policy["observed_exclusion_rate_pct"], policy["max_registered_exclusion_rate_pct"])
        self.assertTrue(policy["runner_must_abort_if_exclusion_list_missing"])
        self.assertTrue(policy["runner_must_abort_if_exclusion_not_applied"])
        self.assertTrue(policy["excluded_groups_must_be_reported"])
        self.assertFalse(policy["silent_use_of_ambiguous_groups_allowed"])
        self.assertFalse(policy["latest_only_fill_allowed"])

    def test_scope_creep_is_rejected_by_schema(self) -> None:
        payload = copy.deepcopy(self._load_artifact())
        payload["scope"]["signal_search_authorized_by_this_artifact"] = True
        payload["prohibited_claims"]["validated_alpha"] = True
        payload["search_design"]["restatement_exclusion_policy"]["silent_use_of_ambiguous_groups_allowed"] = True
        payload["search_design"]["restatement_exclusion_policy"]["runner_must_abort_if_exclusion_not_applied"] = False

        errors = self._validate(payload)

        self.assertGreaterEqual(len(errors), 2)

    def test_ledger_registers_one_pending_test_without_authorizing_run(self) -> None:
        artifact = self._load_artifact()
        ledger = self._load_ledger()

        self.assertEqual(artifact["planned_test_budget"]["ledger_ref"], str(LEDGER_ARTIFACT_PATH).replace("\\", "/"))
        self.assertFalse(artifact["planned_test_budget"]["signal_search_run_authorized_now"])
        self.assertEqual(ledger["lane_id"], "a_long_research")
        self.assertEqual(ledger["ledger_status"], "active_planned_test_pending_review")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(ledger["budget_policy"]["tests_available_without_new_review"], 0)
        self.assertEqual(ledger["test_spend_log"], [])
        self.assertEqual(len(ledger["planned_tests"]), 1)
        planned = ledger["planned_tests"][0]
        self.assertEqual(planned["planned_status"], "planned_not_reviewed")
        self.assertEqual(planned["approval_status"], "pending_user_approval")
        self.assertIn("fixed 9-symbol panel is route proof only", planned["review_boundary"][0])


if __name__ == "__main__":
    unittest.main()
