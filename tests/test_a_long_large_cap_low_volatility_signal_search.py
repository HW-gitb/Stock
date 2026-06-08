from __future__ import annotations

import copy
import math
import statistics
import unittest
from unittest import mock

from runners import a_long_large_cap_low_volatility_signal_search as runner


class ALongLargeCapLowVolatilitySignalSearchTest(unittest.TestCase):
    def test_execution_requires_both_confirmations(self) -> None:
        with self.assertRaises(RuntimeError):
            runner.require_execution_confirmations(
                confirm_independent_review_pass=False,
                confirm_post_review_execute=True,
            )
        with self.assertRaises(RuntimeError):
            runner.require_execution_confirmations(
                confirm_independent_review_pass=True,
                confirm_post_review_execute=False,
            )

    def _unspent_ledger_fixture(self) -> dict:
        # Synthetic unspent singleton (deep-copied from the real ledger, spend reversed, planned test
        # rebuilt) so the acceptance path and the per-field guards stay testable in the committed
        # post-execution (spent) state.
        ledger = copy.deepcopy(runner.read_json(runner.LEDGER_PATH))
        ledger["ledger_status"] = "active_planned_test_pending_review"
        ledger["budget_policy"]["tests_spent_count"] = 0
        ledger["budget_policy"]["tests_available_without_new_review"] = 0
        ledger["test_spend_log"] = []
        ledger["planned_tests"] = [
            {
                "test_id": runner.PLANNED_TEST_ID,
                "planned_status": "planned_not_reviewed",
                "created_at": "2026-06-08T00:00:00+00:00",
                "planned_preregistration_ref": runner.display_path(runner.PREREGISTRATION_PATH),
                "planned_result_ref": runner.display_path(runner.SUMMARY_PATH),
                "promotion_relevant": True,
                "expected_tests_spent": 1,
                "approval_status": "user_approved_pending_review",
                "design_summary": "Synthetic unspent fixture for the load_and_validate_ledger acceptance path.",
                "review_boundary": ["Synthetic fixture; not a real planned test."],
            }
        ]
        return ledger

    def _mutated_ledger(self, mutate) -> dict:
        ledger = self._unspent_ledger_fixture()
        mutate(ledger)
        return ledger

    def test_review_gate_artifacts_and_spent_ledger_in_committed_state(self) -> None:
        # Post-execution committed state: prereg + market-cap audit still validate; the real singleton
        # ledger is schema-valid and SPENT, and the runtime gate now correctly REFUSES it (the spent
        # singleton cannot be re-run).
        prereg = runner.load_and_validate_preregistration()
        audit_report = runner.load_and_validate_market_cap_audit_report()
        self.assertEqual(prereg["artifact_id"], "a_long_large_cap_low_volatility_20260608")
        self.assertEqual(
            prereg["scope"]["preregistration_review_status"],
            "passed_independent_review_ready_for_freeze",
        )
        self.assertEqual(
            audit_report["decision"]["audit_status"],
            "passed_large_cap_market_cap_audit_for_signal_package",
        )
        real_ledger = runner.read_json(runner.LEDGER_PATH)
        runner.validate_json(runner.LEDGER_SCHEMA_PATH, real_ledger)
        self.assertEqual(real_ledger["family_id"], "a_long_large_cap_low_volatility_v1")
        self.assertEqual(real_ledger["budget_policy"]["tests_spent_count"], 1)
        self.assertEqual(real_ledger["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(real_ledger["test_spend_log"][0]["status"], "spent_failed_outcome_threshold")
        with self.assertRaises(ValueError):
            runner.load_and_validate_ledger()

    def test_load_and_validate_ledger_accepts_unspent_fixture(self) -> None:
        fixture = self._unspent_ledger_fixture()
        with mock.patch.object(runner, "read_json", return_value=fixture):
            validated = runner.load_and_validate_ledger()
        self.assertEqual(validated["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(validated["test_spend_log"], [])

    def test_load_and_validate_ledger_rejects_spent_count(self) -> None:
        ledger = self._mutated_ledger(lambda l: l["budget_policy"].__setitem__("tests_spent_count", 1))
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_ledger_validation_rejects_schema_invalid_ledger(self) -> None:
        ledger = copy.deepcopy(runner.read_json(runner.LEDGER_PATH))
        ledger.pop("artifact_id", None)
        ledger["unexpected_extra_field"] = True

        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_ledger_rejects_non_active_status(self) -> None:
        ledger = self._mutated_ledger(lambda l: l.__setitem__("ledger_status", "closed_superseded"))
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_ledger_rejects_expected_tests_spent_not_one(self) -> None:
        ledger = self._mutated_ledger(
            lambda l: l["planned_tests"][0].__setitem__("expected_tests_spent", 2)
        )
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_ledger_rejects_wrong_planned_preregistration_ref(self) -> None:
        ledger = self._mutated_ledger(
            lambda l: l["planned_tests"][0].__setitem__(
                "planned_preregistration_ref", "research/preregistrations/some_other_prereg.json"
            )
        )
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_ledger_rejects_wrong_planned_result_ref(self) -> None:
        ledger = self._mutated_ledger(
            lambda l: l["planned_tests"][0].__setitem__(
                "planned_result_ref", "research/results/some_other_result/execution_summary.json"
            )
        )
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_ledger_rejects_wrong_approval_status(self) -> None:
        ledger = self._mutated_ledger(
            lambda l: l["planned_tests"][0].__setitem__("approval_status", "not_yet_user_approved")
        )
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def _consistent_summary(self) -> dict:
        def cell(signal: str, view: str, weighting: str, horizon: int, benchmark: str, primary: bool = False) -> dict:
            spec = {
                "signal_id": signal,
                "view": view,
                "weighting": weighting,
                "horizon_trading_days": horizon,
                "benchmark": benchmark,
            }
            return {
                "cell_id": runner.cell_id_for(spec),
                "signal_id": signal,
                "view": view,
                "weighting": weighting,
                "diagnostic_role": "primary_decision_cell" if primary else "diagnostic_only",
                "horizon_trading_days": horizon,
                "benchmark": benchmark,
            }

        return {
            "result_cells": [
                cell("low_volatility", "industry_size_neutral", "equal_weight", 504, "CSI300", primary=True),
                cell("low_volatility", "non_neutral", "equal_weight", 252, "CSI1000"),
            ],
            "decision": {
                "research_verdict": runner.FALSIFIED_VERDICT,
                "is_statistical_alpha_clue": False,
                "is_tradeable_candidate": False,
                "statistical_alpha_clue_count": 0,
                "tradeable_candidate_count": 0,
                "primary_cell_passed_statistical_gates": False,
                "relative_nav_drawdown_gate_passed": False,
            },
            "execution_diagnostics": {
                "primary_no_cohort_zero_score_month_count": 1,
                "primary_no_cohort_zero_score_months": ["20180131"],
                "primary_incomplete_size_coverage_month_count": 1,
                "primary_incomplete_size_coverage_months": ["20180330"],
                "trailing_window_startup_excluded_month_count": 2,
                "trailing_window_startup_excluded_months": ["20180131", "20180330"],
                "result_cell_count": 2,
            },
        }

    def test_summary_internal_consistency_accepts_consistent_payload(self) -> None:
        self.assertIsNone(runner.validate_summary_internal_consistency(self._consistent_summary()))

    def test_summary_internal_consistency_rejects_cell_id_metadata_mismatch(self) -> None:
        summary = self._consistent_summary()
        summary["result_cells"][1]["benchmark"] = "CSI300"  # cell_id still says CSI1000
        with self.assertRaises(ValueError):
            runner.validate_summary_internal_consistency(summary)

    def test_summary_internal_consistency_rejects_verdict_clue_mismatch(self) -> None:
        summary = self._consistent_summary()
        summary["decision"]["research_verdict"] = runner.STATISTICAL_ALPHA_CLUE_VERDICT  # but is_clue stays False
        with self.assertRaises(ValueError):
            runner.validate_summary_internal_consistency(summary)

    def test_summary_internal_consistency_rejects_count_list_mismatch(self) -> None:
        summary = self._consistent_summary()
        summary["execution_diagnostics"]["primary_no_cohort_zero_score_month_count"] = 2  # list has 1
        with self.assertRaises(ValueError):
            runner.validate_summary_internal_consistency(summary)

    def test_summary_internal_consistency_rejects_startup_union_mismatch(self) -> None:
        summary = self._consistent_summary()
        # Same count (2) but the list is not the sorted union of the zero-score + incomplete months.
        summary["execution_diagnostics"]["trailing_window_startup_excluded_months"] = ["20180131", "20180427"]
        with self.assertRaises(ValueError):
            runner.validate_summary_internal_consistency(summary)

    def test_result_specs_lock_single_primary_and_28_cells(self) -> None:
        specs = runner.result_specs()
        primary = [
            spec
            for spec in specs
            if spec["signal_id"] == runner.PRIMARY_FACTOR
            and spec["view"] == runner.PRIMARY_VIEW
            and spec["weighting"] == "equal_weight"
            and spec["horizon_trading_days"] == runner.PRIMARY_HORIZON
            and spec["benchmark"] == runner.PRIMARY_BENCHMARK
        ]

        self.assertEqual(len(specs), 28)
        self.assertEqual(len(primary), 1)
        self.assertEqual(
            runner.PRIMARY_RESULT_CELL_ID,
            "low_volatility_industry_size_neutral_equal_weight_504d_CSI300",
        )
        self.assertIn(
            {
                "signal_id": runner.PRIMARY_FACTOR,
                "view": runner.PRIMARY_VIEW,
                "weighting": "cap_weighted",
                "horizon_trading_days": runner.PRIMARY_HORIZON,
                "benchmark": runner.PRIMARY_BENCHMARK,
            },
            specs,
        )
        cell_ids = {runner.cell_id_for(spec) for spec in specs}
        self.assertEqual(len(cell_ids), 28)
        # The two diagnostic factors are reported only at the primary view, equal-weight.
        for factor in runner.DIAGNOSTIC_FACTORS:
            factor_specs = [spec for spec in specs if spec["signal_id"] == factor]
            self.assertEqual(len(factor_specs), 4)
            self.assertTrue(all(spec["view"] == runner.PRIMARY_VIEW for spec in factor_specs))
            self.assertTrue(all(spec["weighting"] == "equal_weight" for spec in factor_specs))

    def test_trailing_window_dates_by_as_of_takes_last_window_leq_as_of(self) -> None:
        trade_dates = ["20200101", "20200102", "20200103", "20200104", "20200110", "20200120"]
        with mock.patch.object(runner, "MONTHLY_AS_OF_DATES", ["20200103", "20200110"]), mock.patch.object(
            runner, "TRAILING_WINDOW_TRADING_DAYS", 3
        ):
            windows = runner.trailing_window_dates_by_as_of(trade_dates)
        # Only trading days <= as_of, capped to the last 3, and the as_of close itself is included.
        self.assertEqual(windows["20200103"], ["20200101", "20200102", "20200103"])
        self.assertEqual(windows["20200110"], ["20200103", "20200104", "20200110"])

    def test_realized_volatility_signals_skips_when_below_min_returns(self) -> None:
        # Only one valid daily return is far below the 120-return guard -> no factor is emitted.
        values = runner.realized_volatility_signals(
            window_dates=["d1", "d2"],
            stock_close_by_date={"d1": 100.0, "d2": 110.0},
            benchmark_close_by_date={"d1": 100.0, "d2": 101.0},
        )
        self.assertEqual(values, {})

    def test_realized_volatility_signals_emits_negative_total_and_diagnostics(self) -> None:
        window_dates = ["d1", "d2", "d3", "d4"]
        stock = {"d1": 100.0, "d2": 110.0, "d3": 99.0, "d4": 108.9}
        benchmark = {"d1": 100.0, "d2": 101.0, "d3": 100.0, "d4": 101.0}
        with mock.patch.object(runner, "MIN_VALID_DAILY_RETURNS", 2):
            values = runner.realized_volatility_signals(
                window_dates=window_dates,
                stock_close_by_date=stock,
                benchmark_close_by_date=benchmark,
            )
        expected_low_vol = -statistics.stdev([0.1, -0.1, 0.1])
        self.assertAlmostEqual(values["low_volatility"], expected_low_vol)
        self.assertLess(values["low_volatility"], 0.0)
        self.assertIn("downside_semideviation_low", values)
        self.assertLessEqual(values["downside_semideviation_low"], 0.0)
        self.assertIn("idiosyncratic_volatility_vs_csi300_low", values)
        self.assertLessEqual(values["idiosyncratic_volatility_vs_csi300_low"], 0.0)

    def test_realized_volatility_skips_idiosyncratic_when_market_returns_missing(self) -> None:
        # Stock has enough returns but the benchmark series is absent over the window, so only the
        # stock-only factors (low_volatility, downside) are emitted; the idiosyncratic factor is not.
        window_dates = ["d1", "d2", "d3"]
        stock = {"d1": 100.0, "d2": 110.0, "d3": 99.0}
        with mock.patch.object(runner, "MIN_VALID_DAILY_RETURNS", 2):
            values = runner.realized_volatility_signals(
                window_dates=window_dates,
                stock_close_by_date=stock,
                benchmark_close_by_date={},
            )
        self.assertIn("low_volatility", values)
        self.assertIn("downside_semideviation_low", values)
        self.assertNotIn("idiosyncratic_volatility_vs_csi300_low", values)

    def test_realized_volatility_breaks_pair_across_suspension_gap(self) -> None:
        # The stock has no close on d3 (suspended); only the adjacent pairs d1->d2 and d3->d4 with both
        # closes present count, so a suspended day breaks the pair rather than spanning the gap.
        window_dates = ["d1", "d2", "d3", "d4", "d5"]
        stock = {"d1": 100.0, "d2": 101.0, "d4": 102.0, "d5": 103.0}
        with mock.patch.object(runner, "MIN_VALID_DAILY_RETURNS", 2):
            values = runner.realized_volatility_signals(
                window_dates=window_dates,
                stock_close_by_date=stock,
                benchmark_close_by_date={date: 100.0 for date in window_dates},
            )
        # Valid adjacent returns: d1->d2 and d4->d5 (d2->d3, d3->d4 broken by the missing d3 close).
        expected = -statistics.stdev([101.0 / 100.0 - 1.0, 103.0 / 102.0 - 1.0])
        self.assertAlmostEqual(values["low_volatility"], expected)

    def test_downside_semideviation_uses_only_negative_returns(self) -> None:
        returns = [0.1, -0.2, 0.3, -0.1]
        expected = math.sqrt((0.04 + 0.01) / 3)
        self.assertAlmostEqual(runner.downside_semideviation(returns), expected)
        self.assertEqual(runner.downside_semideviation([0.1]), 0.0)
        self.assertEqual(runner.downside_semideviation([0.1, 0.2]), 0.0)

    def test_idiosyncratic_volatility_zero_market_variance_returns_none(self) -> None:
        self.assertIsNone(runner.idiosyncratic_volatility([0.1, 0.2, 0.3], [0.01, 0.01, 0.01]))

    def test_idiosyncratic_volatility_perfect_linear_has_zero_residual(self) -> None:
        market = [0.01, -0.02, 0.03, -0.01]
        stock = [2.0 * value for value in market]
        self.assertAlmostEqual(runner.idiosyncratic_volatility(stock, market), 0.0, places=9)

    def test_size_neutral_scores_require_minimum_bucket_count(self) -> None:
        items = [
            {"symbol": "a", "size_bucket": "q1", "low_volatility": 1.0},
            {"symbol": "b", "size_bucket": "q1", "low_volatility": 2.0},
            {"symbol": "c", "size_bucket": "q2", "low_volatility": 3.0},
        ]

        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 2):
            counts = runner.add_size_neutral_scores(items, "low_volatility")

        self.assertEqual(counts, {"q1": 2, "q2": 1, "q3": 0, "q4": 0, "q5": 0})
        self.assertIn("low_volatility__size_neutral", items[0])
        self.assertIn("low_volatility__size_neutral", items[1])
        self.assertNotIn("low_volatility__size_neutral", items[2])

    def test_marginal_industry_size_neutral_combines_half_and_half(self) -> None:
        complete = {
            "symbol": "000001.SZ",
            "low_volatility__industry_neutral": 0.6,
            "low_volatility__size_neutral": 0.5,
            "downside_semideviation_low__industry_neutral": 0.9,
            "downside_semideviation_low__size_neutral": 0.8,
        }
        missing = {
            "symbol": "000002.SZ",
            "low_volatility__industry_neutral": 0.6,
        }

        coverage = runner.add_marginal_industry_size_neutral_scores([complete, missing])

        self.assertEqual(coverage["low_volatility_industry_size_neutral_available_observation_count"], 1)
        self.assertAlmostEqual(complete["low_volatility__industry_size_neutral"], 0.55)
        self.assertAlmostEqual(complete["downside_semideviation_low__industry_size_neutral"], 0.85)
        self.assertNotIn("low_volatility__industry_size_neutral", missing)

    def test_preregistration_validation_rejects_decision_gate_drift(self) -> None:
        prereg = copy.deepcopy(runner.read_json(runner.PREREGISTRATION_PATH))
        cell = prereg["frozen_design"]["decision_cell"]
        cell["top_fraction"] = 0.9
        cell["minimum_top_count_per_month"] = 99
        cell["statistical_alpha_clue_gates"]["minimum_hac_t_stat"] = 1.0

        with mock.patch.object(runner, "read_json", return_value=prereg):
            with self.assertRaises(ValueError):
                runner.load_and_validate_preregistration()

    def test_preregistration_validation_rejects_trailing_window_search(self) -> None:
        prereg = copy.deepcopy(runner.read_json(runner.PREREGISTRATION_PATH))
        prereg["frozen_design"]["signal_rule"]["trailing_window_search_allowed"] = True

        with mock.patch.object(runner, "read_json", return_value=prereg):
            with self.assertRaises(ValueError):
                runner.load_and_validate_preregistration()

    def test_preregistration_validation_rejects_summed_excess_drawdown_gate(self) -> None:
        prereg = copy.deepcopy(runner.read_json(runner.PREREGISTRATION_PATH))
        prereg["frozen_design"]["risk_gate"]["summed_overlapping_cohort_excess_drawdown_as_gate_allowed"] = True

        with mock.patch.object(runner, "read_json", return_value=prereg):
            with self.assertRaises(ValueError):
                runner.load_and_validate_preregistration()

    def test_max_drawdown_on_levels(self) -> None:
        self.assertIsNone(runner.max_drawdown_on_levels([]))
        self.assertEqual(runner.max_drawdown_on_levels([1.0, 1.1, 1.2]), 0.0)
        worst = runner.max_drawdown_on_levels([1.0, 1.2, 0.9, 1.05])
        self.assertAlmostEqual(worst, (0.9 / 1.2) - 1.0)

    def test_sub_period_robustness_median_split_requires_both_halves_positive(self) -> None:
        positive = runner.sub_period_robustness(
            {"cohort_returns": [0.02, 0.01, 0.03, 0.04], "cohort_as_ofs": ["a", "b", "c", "d"]}
        )
        self.assertEqual(positive["split_index"], 2)
        self.assertEqual(positive["first_half"]["cohort_count"], 2)
        self.assertEqual(positive["second_half"]["cohort_count"], 2)
        self.assertTrue(positive["both_halves_mean_excess_positive"])

        mixed = runner.sub_period_robustness(
            {"cohort_returns": [0.05, 0.05, -0.04, -0.03], "cohort_as_ofs": ["a", "b", "c", "d"]}
        )
        self.assertFalse(mixed["both_halves_mean_excess_positive"])

    def test_rolling_relative_nav_drawdown_builds_levels_and_relative_drawdown(self) -> None:
        stock_price_cache = {
            "AAA": {
                "20200102": {"close": 100.0},
                "20200201": {"close": 110.0},
                "20200301": {"close": 105.0},
            }
        }
        csi300_prices = {
            "20200102": {"close": 100.0},
            "20200201": {"close": 100.0},
            "20200301": {"close": 100.0},
        }
        trade_dates = [
            "20200101",
            "20200102",
            "20200201",
            "20200202",
            "20200301",
            "20200302",
            "20200401",
        ]
        with mock.patch.object(runner, "PRIMARY_HORIZON", 4), mock.patch.object(
            runner, "MONTHLY_AS_OF_DATES", ["20200101", "20200201", "20200301", "20200401"]
        ):
            result = runner.rolling_relative_nav_drawdown(
                primary_selections={"20200101": ["AAA"]},
                stock_price_cache=stock_price_cache,
                csi300_prices=csi300_prices,
                trade_dates=trade_dates,
            )

        self.assertEqual(result["tranche_count"], 1)
        self.assertEqual(result["relative_nav_checkpoint_count"], 2)
        self.assertFalse(result["cost_applied_to_benchmark_tranches"])
        self.assertIsNotNone(result["relative_nav_max_drawdown"])
        self.assertLess(result["relative_nav_max_drawdown"], 0.0)
        self.assertGreater(result["relative_nav_max_drawdown"], -0.15)

    def _primary_pass_cell(self) -> dict:
        return {
            "cell_id": runner.PRIMARY_RESULT_CELL_ID,
            "diagnostic_role": "primary_decision_cell",
            "passes_minimum_monthly_cohorts": True,
            "passes_minimum_top_count": True,
            "mean_monthly_cohort_net_excess": 0.01,
            "monthly_clustered_t_stat": 2.5,
            "passes_name_concentration_guard": True,
            "passes_single_year_concentration_guard": True,
        }

    def test_decision_falsified_when_tier1_fails(self) -> None:
        primary = self._primary_pass_cell()
        primary["monthly_clustered_t_stat"] = 1.0
        decision = runner.decision_from_results(
            [primary],
            {"both_halves_mean_excess_positive": True},
            {"relative_nav_max_drawdown": -0.05},
        )
        self.assertEqual(decision["research_verdict"], runner.FALSIFIED_VERDICT)
        self.assertFalse(decision["is_statistical_alpha_clue"])
        self.assertFalse(decision["is_tradeable_candidate"])
        self.assertEqual(decision["statistical_alpha_clue_count"], 0)

    def test_decision_falsified_when_sub_period_half_negative(self) -> None:
        decision = runner.decision_from_results(
            [self._primary_pass_cell()],
            {"both_halves_mean_excess_positive": False},
            {"relative_nav_max_drawdown": -0.05},
        )
        self.assertEqual(decision["research_verdict"], runner.FALSIFIED_VERDICT)
        self.assertFalse(decision["is_statistical_alpha_clue"])

    def test_decision_clue_but_not_tradeable_when_nav_drawdown_fails(self) -> None:
        decision = runner.decision_from_results(
            [self._primary_pass_cell()],
            {"both_halves_mean_excess_positive": True},
            {"relative_nav_max_drawdown": -0.30},
        )
        self.assertEqual(decision["research_verdict"], runner.STATISTICAL_ALPHA_CLUE_VERDICT)
        self.assertTrue(decision["is_statistical_alpha_clue"])
        self.assertFalse(decision["is_tradeable_candidate"])
        self.assertEqual(decision["statistical_alpha_clue_count"], 1)
        self.assertEqual(decision["tradeable_candidate_count"], 0)
        self.assertFalse(decision["relative_nav_drawdown_gate_passed"])

    def test_decision_clue_and_tradeable_when_both_tiers_pass(self) -> None:
        decision = runner.decision_from_results(
            [self._primary_pass_cell()],
            {"both_halves_mean_excess_positive": True},
            {"relative_nav_max_drawdown": -0.05},
        )
        self.assertEqual(decision["research_verdict"], runner.STATISTICAL_ALPHA_CLUE_VERDICT)
        self.assertTrue(decision["is_statistical_alpha_clue"])
        self.assertTrue(decision["is_tradeable_candidate"])
        self.assertEqual(decision["tradeable_candidate_count"], 1)
        self.assertFalse(decision["diagnostics_can_rescue_primary_failure"])
        self.assertFalse(decision["full_size_allowed"])

    def _sanity_diagnostics(self, **overrides) -> dict:
        diagnostics = {
            "primary_size_neutral_thin_month_count": 0,
            "primary_size_neutral_coverage_month_count": 50,
            "primary_no_cohort_zero_score_months": [],
            "primary_incomplete_size_coverage_months": [],
        }
        diagnostics.update(overrides)
        return diagnostics

    def test_pipeline_sanity_rejects_thin_primary_size_neutral_coverage(self) -> None:
        primary = {
            "cell_id": runner.PRIMARY_RESULT_CELL_ID,
            "diagnostic_role": "primary_decision_cell",
            "monthly_cohort_count": 50,
        }
        diagnostics = self._sanity_diagnostics(primary_size_neutral_thin_month_count=1)
        primary_series = {"cohort_returns": [0.01] * 50, "cohort_as_ofs": [f"2020{i:04d}" for i in range(50)]}

        with self.assertRaises(ValueError):
            runner.validate_pipeline_result_sanity([{"row": 1}], [primary], diagnostics, primary_series)

    def test_pipeline_sanity_rejects_short_primary_series(self) -> None:
        primary = {
            "cell_id": runner.PRIMARY_RESULT_CELL_ID,
            "diagnostic_role": "primary_decision_cell",
            "monthly_cohort_count": 1,
        }
        diagnostics = self._sanity_diagnostics(primary_size_neutral_coverage_month_count=1)
        primary_series = {"cohort_returns": [0.01], "cohort_as_ofs": ["20200101"]}

        with self.assertRaises(ValueError):
            runner.validate_pipeline_result_sanity([{"row": 1}], [primary], diagnostics, primary_series)

    def test_pipeline_sanity_rejects_startup_month_leak_into_primary_cohort(self) -> None:
        primary = {
            "cell_id": runner.PRIMARY_RESULT_CELL_ID,
            "diagnostic_role": "primary_decision_cell",
            "monthly_cohort_count": 50,
        }
        diagnostics = self._sanity_diagnostics(
            primary_incomplete_size_coverage_months=["20180330"],
        )
        primary_series = {
            "cohort_returns": [0.01] * 50,
            "cohort_as_ofs": ["20180330"] + [f"2020{i:04d}" for i in range(49)],
        }

        with self.assertRaises(ValueError):
            runner.validate_pipeline_result_sanity([{"row": 1}], [primary], diagnostics, primary_series)

    def test_nav_empty_basket_skips_tranche(self) -> None:
        stock_price_cache = {"AAA": {"20200301": {"close": 100.0}}}
        csi300_prices = {"20200102": {"close": 100.0}, "20200201": {"close": 100.0}}
        trade_dates = ["20200101", "20200102", "20200201", "20200202", "20200301", "20200302", "20200401"]
        with mock.patch.object(runner, "PRIMARY_HORIZON", 4), mock.patch.object(
            runner, "MONTHLY_AS_OF_DATES", ["20200101", "20200201", "20200301", "20200401"]
        ):
            result = runner.rolling_relative_nav_drawdown(
                primary_selections={"20200101": ["AAA"]},
                stock_price_cache=stock_price_cache,
                csi300_prices=csi300_prices,
                trade_dates=trade_dates,
            )
        self.assertEqual(result["tranche_count"], 0)
        self.assertEqual(result["relative_nav_checkpoint_count"], 0)
        self.assertIsNone(result["relative_nav_max_drawdown"])

    def test_nav_terminal_price_gap_carries_last_close(self) -> None:
        stock_price_cache = {"AAA": {"20200102": {"close": 100.0}, "20200201": {"close": 110.0}}}
        csi300_prices = {
            "20200102": {"close": 100.0},
            "20200201": {"close": 100.0},
            "20200301": {"close": 100.0},
        }
        trade_dates = ["20200101", "20200102", "20200201", "20200202", "20200301", "20200302", "20200401"]
        with mock.patch.object(runner, "PRIMARY_HORIZON", 4), mock.patch.object(
            runner, "MONTHLY_AS_OF_DATES", ["20200101", "20200201", "20200301", "20200401"]
        ):
            result = runner.rolling_relative_nav_drawdown(
                primary_selections={"20200101": ["AAA"]},
                stock_price_cache=stock_price_cache,
                csi300_prices=csi300_prices,
                trade_dates=trade_dates,
            )
        self.assertEqual(result["tranche_count"], 1)
        self.assertEqual(result["relative_nav_checkpoint_count"], 2)
        self.assertEqual(result["relative_nav_max_drawdown"], 0.0)

    def _coverage_diagnostics(self) -> dict:
        return {
            "primary_size_neutral_thin_month_count": 0,
            "primary_size_neutral_min_bucket_observation_count": 0,
            "primary_size_neutral_coverage_month_count": 0,
            "primary_size_neutral_bucket_coverage_by_month": [],
            "primary_no_cohort_zero_score_month_count": 0,
            "primary_no_cohort_zero_score_months": [],
            "primary_incomplete_size_coverage_month_count": 0,
            "primary_incomplete_size_coverage_months": [],
        }

    def test_incomplete_size_coverage_month_is_excluded_not_thin(self) -> None:
        # Trailing-window startup ramp: q1 populated >= min, q2-q5 populated but below min (non-empty) ->
        # the across-quintile size-neutral cannot be formed -> excluded as incomplete, NOT thin.
        diagnostics = self._coverage_diagnostics()
        scored = [
            {"size_bucket": "q1", "low_volatility": 1.0, "low_volatility__industry_size_neutral": 0.6}
            for _ in range(2)
        ]
        for bucket in ["q2", "q3", "q4", "q5"]:
            scored.append({"size_bucket": bucket, "low_volatility": 1.0})  # 1 each, below min -> not scored
        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 2):
            runner.update_primary_size_coverage_diagnostics(scored, "20180330", diagnostics)
        self.assertEqual(diagnostics["primary_incomplete_size_coverage_month_count"], 1)
        self.assertEqual(diagnostics["primary_incomplete_size_coverage_months"], ["20180330"])
        self.assertEqual(diagnostics["primary_size_neutral_thin_month_count"], 0)
        self.assertEqual(diagnostics["primary_size_neutral_coverage_month_count"], 0)

    def test_full_size_coverage_month_is_counted(self) -> None:
        diagnostics = self._coverage_diagnostics()
        scored = []
        for bucket in runner.SIZE_BUCKETS:
            for _ in range(2):
                scored.append(
                    {
                        "size_bucket": bucket,
                        "low_volatility": 1.0,
                        "low_volatility__size_neutral": 0.5,
                        "low_volatility__industry_size_neutral": 0.5,
                    }
                )
        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 2):
            runner.update_primary_size_coverage_diagnostics(scored, "20200115", diagnostics)
        self.assertEqual(diagnostics["primary_incomplete_size_coverage_month_count"], 0)
        self.assertEqual(diagnostics["primary_size_neutral_coverage_month_count"], 1)
        self.assertEqual(diagnostics["primary_size_neutral_thin_month_count"], 0)

    def test_incomplete_month_excluded_from_primary_cohort_but_kept_for_non_size_views(self) -> None:
        def row(as_of: str, symbol: str, score: float, excess: float) -> dict:
            return {
                "as_of": as_of,
                "symbol": symbol,
                "horizon": runner.PRIMARY_HORIZON,
                "market_cap": 1.0,
                "low_volatility__industry_size_neutral": score,
                "low_volatility__non_neutral": score,
                f"excess_{runner.PRIMARY_BENCHMARK}": excess,
            }

        rows = []
        for i in range(15):
            rows.append(row("20180330", f"INC{i}", 0.10 * i, 0.02))  # incomplete startup-ramp month
            rows.append(row("20200131", f"OK{i}", 0.10 * i, 0.01))  # normal month

        results, primary_series, primary_selections = runner.summarize_results(rows, {"20180330"})

        # The incomplete month must NOT be consumed by the primary (industry_size_neutral) cohort.
        self.assertNotIn("20180330", primary_series["cohort_as_ofs"])
        self.assertIn("20200131", primary_series["cohort_as_ofs"])
        self.assertNotIn("20180330", primary_selections)
        # But a non-size diagnostic cell still consumes it (both as-ofs).
        non_neutral = next(
            cell
            for cell in results
            if cell["cell_id"] == "low_volatility_non_neutral_equal_weight_504d_CSI300"
        )
        self.assertEqual(non_neutral["monthly_cohort_count"], 2)


if __name__ == "__main__":
    unittest.main()
