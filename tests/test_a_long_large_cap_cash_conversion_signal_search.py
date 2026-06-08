from __future__ import annotations

import copy
import unittest
from unittest import mock

from runners import a_long_large_cap_cash_conversion_signal_search as runner


class ALongLargeCapCashConversionSignalSearchTest(unittest.TestCase):
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

    def test_current_review_gate_artifacts_validate_without_running_signal(self) -> None:
        prereg = runner.load_and_validate_preregistration()
        ledger = runner.load_and_validate_ledger()
        audit_report = runner.load_and_validate_market_cap_audit_report()

        self.assertEqual(prereg["artifact_id"], "a_long_large_cap_cash_conversion_20260607")
        self.assertEqual(
            prereg["scope"]["preregistration_review_status"],
            "passed_independent_review_ready_for_freeze",
        )
        self.assertEqual(ledger["family_id"], "a_long_large_cap_cash_conversion_v1")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(ledger["test_spend_log"], [])
        self.assertEqual(
            audit_report["decision"]["audit_status"],
            "passed_large_cap_market_cap_audit_for_signal_package",
        )

    def test_result_specs_lock_single_primary_and_32_cells(self) -> None:
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

        self.assertEqual(len(specs), 32)
        self.assertEqual(len(primary), 1)
        self.assertEqual(
            runner.PRIMARY_RESULT_CELL_ID,
            "cash_conversion_industry_size_neutral_equal_weight_504d_CSI300",
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
        self.assertEqual(len(cell_ids), 32)

    def test_size_neutral_scores_require_minimum_bucket_count(self) -> None:
        items = [
            {"symbol": "a", "size_bucket": "q1", "cash_conversion": 1.0},
            {"symbol": "b", "size_bucket": "q1", "cash_conversion": 2.0},
            {"symbol": "c", "size_bucket": "q2", "cash_conversion": 3.0},
        ]

        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 2):
            counts = runner.add_size_neutral_scores(items, "cash_conversion")

        self.assertEqual(counts, {"q1": 2, "q2": 1, "q3": 0, "q4": 0, "q5": 0})
        self.assertIn("cash_conversion__size_neutral", items[0])
        self.assertIn("cash_conversion__size_neutral", items[1])
        self.assertNotIn("cash_conversion__size_neutral", items[2])

    def test_marginal_industry_size_neutral_combines_half_and_half(self) -> None:
        complete = {
            "symbol": "000001.SZ",
            "cash_conversion__industry_neutral": 0.6,
            "cash_conversion__size_neutral": 0.5,
            "profitability_quality__industry_neutral": 0.9,
            "profitability_quality__size_neutral": 0.8,
        }
        missing = {
            "symbol": "000002.SZ",
            "cash_conversion__industry_neutral": 0.6,
        }

        coverage = runner.add_marginal_industry_size_neutral_scores([complete, missing])

        self.assertEqual(coverage["cash_conversion_industry_size_neutral_available_observation_count"], 1)
        self.assertAlmostEqual(complete["cash_conversion__industry_size_neutral"], 0.55)
        self.assertAlmostEqual(complete["profitability_quality__industry_size_neutral"], 0.85)
        self.assertNotIn("cash_conversion__industry_size_neutral", missing)

    def test_preregistration_validation_rejects_decision_gate_drift(self) -> None:
        prereg = copy.deepcopy(runner.read_json(runner.PREREGISTRATION_PATH))
        cell = prereg["frozen_design"]["decision_cell"]
        cell["top_fraction"] = 0.9
        cell["minimum_top_count_per_month"] = 99
        cell["statistical_alpha_clue_gates"]["minimum_hac_t_stat"] = 1.0

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

    def test_pipeline_sanity_rejects_thin_primary_size_neutral_coverage(self) -> None:
        primary = {
            "cell_id": runner.PRIMARY_RESULT_CELL_ID,
            "diagnostic_role": "primary_decision_cell",
            "monthly_cohort_count": 50,
        }
        diagnostics = {
            "primary_size_neutral_thin_month_count": 1,
            "primary_size_neutral_coverage_month_count": 50,
        }
        primary_series = {"cohort_returns": [0.01] * 50}

        with self.assertRaises(ValueError):
            runner.validate_pipeline_result_sanity([{"row": 1}], [primary], diagnostics, primary_series)

    def test_pipeline_sanity_rejects_short_primary_series(self) -> None:
        primary = {
            "cell_id": runner.PRIMARY_RESULT_CELL_ID,
            "diagnostic_role": "primary_decision_cell",
            "monthly_cohort_count": 1,
        }
        diagnostics = {
            "primary_size_neutral_thin_month_count": 0,
            "primary_size_neutral_coverage_month_count": 1,
        }
        primary_series = {"cohort_returns": [0.01]}

        with self.assertRaises(ValueError):
            runner.validate_pipeline_result_sanity([{"row": 1}], [primary], diagnostics, primary_series)

    def test_ledger_validation_rejects_schema_invalid_ledger(self) -> None:
        ledger = copy.deepcopy(runner.read_json(runner.LEDGER_PATH))
        ledger.pop("artifact_id", None)
        ledger["unexpected_extra_field"] = True

        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_nav_empty_basket_skips_tranche(self) -> None:
        # The only selected symbol has no close at the tranche entry date -> basket empty -> tranche skipped.
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

    def test_nav_tranche_without_full_horizon_window_is_skipped(self) -> None:
        # Entry has no scheduled exit within trade_dates -> tranche skipped.
        stock_price_cache = {"AAA": {"20200402": {"close": 100.0}}}
        csi300_prices = {"20200402": {"close": 100.0}}
        trade_dates = ["20200401", "20200402", "20200501"]
        with mock.patch.object(runner, "PRIMARY_HORIZON", 4), mock.patch.object(
            runner, "MONTHLY_AS_OF_DATES", ["20200401", "20200501"]
        ):
            result = runner.rolling_relative_nav_drawdown(
                primary_selections={"20200401": ["AAA"]},
                stock_price_cache=stock_price_cache,
                csi300_prices=csi300_prices,
                trade_dates=trade_dates,
            )
        self.assertEqual(result["tranche_count"], 0)
        self.assertIsNone(result["relative_nav_max_drawdown"])

    def test_nav_terminal_price_gap_carries_last_close(self) -> None:
        # AAA stops trading after 20200201 (delisting/suspension); later checkpoint carries the last close.
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
        # Two active checkpoints (20200201, 20200301); the second carries the last close, so relative NAV is flat.
        self.assertEqual(result["tranche_count"], 1)
        self.assertEqual(result["relative_nav_checkpoint_count"], 2)
        self.assertEqual(result["relative_nav_max_drawdown"], 0.0)


if __name__ == "__main__":
    unittest.main()
