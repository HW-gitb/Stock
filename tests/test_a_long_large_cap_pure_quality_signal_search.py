from __future__ import annotations

import unittest
from unittest import mock

from runners import a_long_large_cap_pure_quality_signal_search as runner


class ALongLargeCapPureQualitySignalSearchTest(unittest.TestCase):
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
        packet = runner.load_and_validate_packet()
        prereg = runner.load_and_validate_preregistration()
        ledger = runner.load_and_validate_ledger()
        audit_report = runner.load_and_validate_market_cap_audit_report()

        self.assertEqual(packet["artifact_id"], "a_long_large_cap_pure_quality_signal_search_execution_packet_20260607")
        self.assertEqual(prereg["artifact_id"], "a_long_large_cap_pure_quality_20260607")
        self.assertEqual(ledger["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(
            audit_report["decision"]["audit_status"],
            "passed_large_cap_market_cap_audit_for_signal_package",
        )

    def test_result_specs_lock_single_primary_and_36_cells(self) -> None:
        specs = runner.result_specs()
        primary = [
            spec for spec in specs
            if spec["signal_id"] == runner.PRIMARY_SIGNAL_ID
            and spec["view"] == runner.PRIMARY_VIEW
            and spec["weighting"] == "equal_weight"
            and spec["horizon_trading_days"] == runner.PRIMARY_HORIZON
            and spec["benchmark"] == runner.PRIMARY_BENCHMARK
        ]

        self.assertEqual(len(specs), 36)
        self.assertEqual(len(primary), 1)
        self.assertIn(
            {
                "signal_id": runner.PRIMARY_SIGNAL_ID,
                "view": runner.PRIMARY_VIEW,
                "weighting": "cap_weighted",
                "horizon_trading_days": runner.PRIMARY_HORIZON,
                "benchmark": runner.PRIMARY_BENCHMARK,
            },
            specs,
        )

    def test_size_neutral_scores_require_minimum_bucket_count(self) -> None:
        items = [
            {"symbol": "a", "size_bucket": "q1", "profitability_quality": 1.0},
            {"symbol": "b", "size_bucket": "q1", "profitability_quality": 2.0},
            {"symbol": "c", "size_bucket": "q2", "profitability_quality": 3.0},
        ]

        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 2):
            counts = runner.add_size_neutral_scores(items, "profitability_quality")

        self.assertEqual(counts, {"q1": 2, "q2": 1})
        self.assertIn("profitability_quality__size_neutral", items[0])
        self.assertIn("profitability_quality__size_neutral", items[1])
        self.assertNotIn("profitability_quality__size_neutral", items[2])

    def test_composite_score_requires_all_three_components_and_combines_marginal_scores(self) -> None:
        complete = {
            "symbol": "000001.SZ",
            "profitability_quality__industry_neutral": 0.9,
            "cash_conversion__industry_neutral": 0.6,
            "balance_sheet_strength__industry_neutral": 0.3,
            "profitability_quality__size_neutral": 0.8,
            "cash_conversion__size_neutral": 0.5,
            "balance_sheet_strength__size_neutral": 0.2,
            "profitability_quality__non_neutral": 1.0,
            "cash_conversion__non_neutral": 0.5,
            "balance_sheet_strength__non_neutral": 0.0,
        }
        missing = {
            "symbol": "000002.SZ",
            "profitability_quality__industry_neutral": 0.9,
            "cash_conversion__industry_neutral": 0.6,
            "profitability_quality__size_neutral": 0.8,
            "cash_conversion__size_neutral": 0.5,
        }

        coverage = runner.add_composite_scores([complete, missing])

        self.assertEqual(coverage["primary_composite_available_observation_count"], 1)
        self.assertAlmostEqual(complete["core_quality_composite_percentile_3factor__industry_neutral"], 0.6)
        self.assertAlmostEqual(complete["core_quality_composite_percentile_3factor__size_neutral"], 0.5)
        self.assertAlmostEqual(complete["core_quality_composite_percentile_3factor__industry_size_neutral"], 0.55)
        self.assertNotIn("core_quality_composite_percentile_3factor__industry_size_neutral", missing)

    def test_decision_uses_only_primary_cell_and_diagnostics_cannot_rescue_failure(self) -> None:
        primary_fail = {
            "cell_id": "core_quality_composite_percentile_3factor_industry_size_neutral_equal_weight_504d_CSI300",
            "diagnostic_role": "primary_decision_cell",
            "passes_minimum_monthly_cohorts": True,
            "passes_minimum_top_count": True,
            "mean_monthly_cohort_net_excess": -0.001,
            "monthly_clustered_t_stat": 5.0,
            "passes_name_concentration_guard": True,
            "passes_single_year_concentration_guard": True,
            "passes_drawdown_guard": True,
        }
        diagnostic_pass = {
            "cell_id": "earnings_stability_industry_size_neutral_equal_weight_504d_CSI1000",
            "diagnostic_role": "diagnostic_only",
            "passes_minimum_monthly_cohorts": True,
            "passes_minimum_top_count": True,
            "mean_monthly_cohort_net_excess": 0.05,
            "monthly_clustered_t_stat": 9.0,
            "passes_name_concentration_guard": True,
            "passes_single_year_concentration_guard": True,
            "passes_drawdown_guard": True,
        }

        decision = runner.decision_from_results([diagnostic_pass, primary_fail])

        self.assertEqual(decision["research_verdict"], "falsified_large_cap_pure_quality_under_frozen_rules")
        self.assertEqual(decision["candidate_alpha_clue_count"], 0)
        self.assertFalse(decision["diagnostics_can_rescue_primary_failure"])

    def test_primary_cell_can_pass_without_csi1000_confirmation(self) -> None:
        primary_pass = {
            "cell_id": "core_quality_composite_percentile_3factor_industry_size_neutral_equal_weight_504d_CSI300",
            "diagnostic_role": "primary_decision_cell",
            "passes_minimum_monthly_cohorts": True,
            "passes_minimum_top_count": True,
            "mean_monthly_cohort_net_excess": 0.01,
            "monthly_clustered_t_stat": 2.1,
            "passes_name_concentration_guard": True,
            "passes_single_year_concentration_guard": True,
            "passes_drawdown_guard": True,
        }

        decision = runner.decision_from_results([primary_pass])

        self.assertEqual(decision["research_verdict"], "candidate_alpha_clue_research_only")
        self.assertEqual(decision["candidate_alpha_clue_count"], 1)
        self.assertFalse(decision["secondary_benchmark_required_for_candidate_alpha"])


if __name__ == "__main__":
    unittest.main()
