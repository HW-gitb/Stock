from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator


SCHEMA_PATH = Path("schemas/a_long_large_cap_low_volatility_preregistration.schema.json")
ARTIFACT_PATH = Path("research/preregistrations/a_long_large_cap_low_volatility_20260608.json")
LEDGER_SCHEMA_PATH = Path("schemas/program_test_budget_ledger.schema.json")
LEDGER_ARTIFACT_PATH = Path(
    "research/ledgers/a_long_large_cap_low_volatility_program_test_budget_ledger_20260608.json"
)


class ALongLargeCapLowVolatilityPreregistrationSchemaTest(unittest.TestCase):
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

    def test_scope_is_research_only_review_passed_and_blocks_data_fetch_and_run(self) -> None:
        scope = self._load_artifact()["scope"]

        self.assertTrue(scope["research_only"])
        self.assertTrue(scope["manual_order_only"])
        self.assertTrue(scope["externally_motivated_not_prior_rescue"])
        self.assertTrue(scope["new_hypothesis_not_prior_reslice"])
        self.assertTrue(scope["reuses_reviewed_materialized_market_cap_universe"])
        self.assertTrue(scope["reuses_reviewed_full_main_board_daily_close_series"])
        # After Codex independent-review PASS, the committed design records the review-passed state.
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
        # After Codex PASS, the committed design records the review-passed state, which equals the gate.
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

    def test_provenance_is_externally_motivated_not_in_sample_diagnostic(self) -> None:
        prov = self._load_artifact()["hypothesis_provenance"]

        self.assertTrue(prov["externally_literature_motivated"])
        self.assertFalse(prov["derived_from_in_sample_diagnostic_of_prior_run"])
        self.assertTrue(prov["targets_prior_drawdown_failure_mode"])
        self.assertEqual(
            prov["evidence_status"],
            "external_literature_plus_failure_mode_motivated_in_sample_period_test_not_out_of_sample_proof",
        )
        self.assertTrue(prov["in_sample_period_not_forward"])
        self.assertTrue(prov["requires_forward_live_for_validation"])
        self.assertTrue(prov["program_level_selection_after_three_prior_spent_singletons_acknowledged"])
        self.assertTrue(prov["no_trailing_window_search"])
        self.assertTrue(prov["no_idiosyncratic_vs_total_vol_search"])
        self.assertFalse(prov["old_result_reslice_allowed"])
        self.assertFalse(prov["prior_clue_or_diagnostic_relabel_as_pass_allowed"])

    def test_prior_clue_cannot_be_rescued(self) -> None:
        boundary = self._load_artifact()["prior_result_boundary"]

        self.assertEqual(
            boundary["prior_result_ref"],
            "research/results/a_long_large_cap_cash_conversion_20260607/execution_summary.json",
        )
        self.assertEqual(boundary["prior_research_verdict"], "statistical_alpha_clue_research_only")
        self.assertEqual(boundary["prior_statistical_alpha_clue_count"], 1)
        self.assertEqual(boundary["prior_tradeable_candidate_count"], 0)
        self.assertFalse(boundary["is_rescue_of_prior_clue"])
        self.assertFalse(boundary["old_result_reslice_allowed"])
        self.assertFalse(boundary["old_single_factor_diagnostic_rescue_allowed"])
        self.assertFalse(boundary["threshold_relaxation_allowed"])
        self.assertFalse(boundary["benchmark_rescue_allowed"])
        self.assertFalse(boundary["horizon_rescue_allowed"])

    def test_data_reuse_requires_no_new_fetch_including_daily_series(self) -> None:
        reuse = self._load_artifact()["data_reuse"]

        self.assertTrue(reuse["no_new_provider_call_required"])
        self.assertTrue(reuse["no_new_daily_basic_pull_required"])
        self.assertTrue(reuse["no_new_daily_bar_pull_required"])
        self.assertEqual(
            reuse["daily_close_series_source"],
            "full_main_board_raw_root_daily_call_close_times_adj_factor",
        )
        self.assertEqual(
            reuse["full_main_board_audit_report_ref"],
            "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
        )
        self.assertEqual(reuse["selected_market_cap_field"], "circ_mv")
        self.assertEqual(reuse["monthly_as_of_count"], 96)

    def test_primary_signal_is_single_factor_low_volatility_frozen_window(self) -> None:
        signal = self._load_artifact()["frozen_design"]["signal_rule"]

        self.assertEqual(signal["primary_signal_id"], "low_volatility_percentile")
        self.assertEqual(signal["primary_signal_type"], "single_factor_percentile")
        self.assertEqual(signal["primary_factor"], "low_volatility")
        self.assertEqual(
            signal["primary_factor_definition"],
            "negative_trailing_252_trading_day_realized_volatility_of_daily_adj_factor_total_returns_as_of_each_as_of_date",
        )
        self.assertEqual(signal["trailing_window_trading_days"], 252)
        self.assertEqual(signal["realized_vol_min_valid_daily_returns"], 120)
        self.assertTrue(signal["low_volatility_is_high_score_direction"])
        self.assertEqual(signal["idiosyncratic_or_total_vol_choice"], "total_volatility_frozen_no_search")
        self.assertFalse(signal["trailing_window_search_allowed"])
        self.assertFalse(signal["idiosyncratic_or_total_vol_search_allowed"])
        self.assertFalse(signal["factor_definition_change_allowed"])
        self.assertTrue(signal["percentile_rank_required"])
        self.assertFalse(signal["multi_factor_composite_allowed"])
        self.assertTrue(signal["insufficient_trailing_window_months_excluded_from_cohorts"])
        self.assertEqual(
            set(signal["diagnostic_factors"]),
            {"idiosyncratic_volatility_vs_csi300_low", "downside_semideviation_low"},
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

        self.assertEqual(cell["cell_id"], "primary_low_volatility_industry_size_neutral_504d_csi300")
        self.assertEqual(cell["signal"], "low_volatility_percentile")
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
        self.assertTrue(measurement["trailing_volatility_lookback_and_forward_horizon_are_distinct_axes"])
        self.assertEqual(benchmark["primary_benchmark"], "CSI300")
        self.assertFalse(benchmark["both_benchmark_pass_required"])

    def test_risk_gate_is_relative_nav_drawdown_frozen_at_same_minus_15_bar(self) -> None:
        risk = self._load_artifact()["frozen_design"]["risk_gate"]

        self.assertEqual(risk["method"], "rolling_overlapping_monthly_tranche_portfolio_nav")
        self.assertEqual(risk["primary_risk_metric"], "max_drawdown_of_relative_nav")
        self.assertEqual(risk["relative_nav_formula"], "strategy_nav_divided_by_benchmark_nav")
        self.assertEqual(
            risk["benchmark_construction"],
            "option_a_parallel_same_as_of_schedule_horizon_and_ramp_holding_csi300_total_return_instead_of_selected_basket",
        )
        self.assertFalse(risk["cost_applied_to_benchmark_tranches"])
        self.assertEqual(risk["minimum_allowed_relative_nav_drawdown"], -0.15)
        self.assertTrue(risk["threshold_frozen_before_run"])
        self.assertEqual(risk["absolute_strategy_nav_drawdown_role"], "diagnostic_only")
        self.assertFalse(risk["summed_overlapping_cohort_excess_drawdown_as_gate_allowed"])
        self.assertTrue(risk["risk_gate_affects_tradeable_label_only_not_alpha_clue"])

    def test_pit_hygiene_drops_fundamental_restatement_exclusion_for_price_only_signal(self) -> None:
        pit = self._load_artifact()["frozen_design"]["pit_and_hygiene_controls"]

        self.assertFalse(pit["restatement_exclusion_required"])
        self.assertIn("price_only", pit["restatement_exclusion_not_applicable_reason"])
        self.assertTrue(pit["pit_namechange_required"])
        self.assertFalse(pit["current_stock_basic_name_veto_allowed"])
        self.assertTrue(pit["trailing_window_uses_only_pre_as_of_daily_returns"])
        self.assertTrue(pit["no_look_ahead_in_trailing_window_required"])

    def test_anti_p_hacking_blocks_window_and_estimator_search(self) -> None:
        controls = self._load_artifact()["frozen_design"]["anti_p_hacking_controls"]

        self.assertEqual(controls["test_budget_units"], 1)
        self.assertFalse(controls["parameter_sweep_allowed"])
        self.assertFalse(controls["factor_definition_search_allowed"])
        self.assertFalse(controls["trailing_window_search_allowed"])
        self.assertFalse(controls["idiosyncratic_vs_total_vol_search_allowed"])
        self.assertFalse(controls["multi_factor_composite_search_allowed"])
        self.assertFalse(controls["post_result_rescue_slicing_allowed"])
        self.assertTrue(controls["risk_gate_threshold_frozen_before_run"])
        self.assertTrue(controls["new_ledger_required_before_any_followup"])

    def test_ledger_registers_spent_singleton_after_execution(self) -> None:
        # Post-execution committed state: the frozen preregistration's run / fetch gates stay off, and
        # the singleton ledger is now spent exactly once (the low_volatility signal search executed and
        # was falsified). This replaces the pre-execution unspent assertion now that the ledger is spent.
        artifact = self._load_artifact()
        ledger = self._load_ledger()

        self.assertEqual(
            artifact["planned_test_budget"]["ledger_ref"], str(LEDGER_ARTIFACT_PATH).replace("\\", "/")
        )
        self.assertFalse(artifact["planned_test_budget"]["signal_search_run_authorized_now"])
        self.assertFalse(artifact["planned_test_budget"]["new_data_fetch_authorized_now"])
        self.assertEqual(ledger["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(ledger["lane_id"], "a_long_research")
        self.assertEqual(ledger["family_id"], "a_long_large_cap_low_volatility_v1")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 1)
        self.assertEqual(ledger["budget_policy"]["tests_available_without_new_review"], 0)
        self.assertEqual(ledger["planned_tests"], [])
        self.assertEqual(len(ledger["test_spend_log"]), 1)
        spend = ledger["test_spend_log"][0]
        self.assertEqual(spend["test_id"], "a_long_large_cap_low_volatility_20260608")
        self.assertEqual(spend["status"], "spent_failed_outcome_threshold")
        self.assertEqual(spend["tests_spent"], 1)

    def test_frozen_decision_thresholds_are_exact_consts(self) -> None:
        base = self._load_artifact()
        mutations = [
            ("signal_window", "trailing_window_trading_days", 504),
            ("signal_window", "trailing_window_trading_days", 126),
            ("neutralization", "minimum_size_bucket_count_for_primary_percentile", 10),
            ("top_count", "minimum_top_count_per_month", 5),
            ("cohorts", "minimum_monthly_cohorts", 24),
        ]
        for target, field, value in mutations:
            payload = copy.deepcopy(base)
            if target == "signal_window":
                payload["frozen_design"]["signal_rule"][field] = value
            elif target == "neutralization":
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
        payload["hypothesis_provenance"]["old_result_reslice_allowed"] = True
        payload["hypothesis_provenance"]["derived_from_in_sample_diagnostic_of_prior_run"] = True
        payload["frozen_design"]["signal_rule"]["multi_factor_composite_allowed"] = True
        payload["frozen_design"]["signal_rule"]["trailing_window_search_allowed"] = True
        payload["frozen_design"]["neutralization_rule"]["crossed_industry_size_bucket_allowed"] = True
        payload["frozen_design"]["risk_gate"]["summed_overlapping_cohort_excess_drawdown_as_gate_allowed"] = True
        payload["prohibited_claims"]["validated_alpha"] = True

        errors = self._validate(payload)

        self.assertGreaterEqual(len(errors), 5)


if __name__ == "__main__":
    unittest.main()
