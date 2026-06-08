from __future__ import annotations

import copy
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

    def test_review_gate_artifacts_and_spent_ledger_in_committed_state(self) -> None:
        # State-independent gate artifacts still validate.
        packet = runner.load_and_validate_packet()
        prereg = runner.load_and_validate_preregistration()
        audit_report = runner.load_and_validate_market_cap_audit_report()

        self.assertEqual(packet["artifact_id"], "a_long_large_cap_pure_quality_signal_search_execution_packet_20260607")
        self.assertEqual(prereg["artifact_id"], "a_long_large_cap_pure_quality_20260607")
        self.assertEqual(
            audit_report["decision"]["audit_status"],
            "passed_large_cap_market_cap_audit_for_signal_package",
        )
        # Post-execution committed state: the singleton ledger is schema-valid and spent, and the
        # unspent runtime gate now correctly refuses it (the spent singleton cannot be re-run).
        real_ledger = runner.read_json(runner.LEDGER_PATH)
        self.assertEqual(real_ledger["family_id"], "a_long_large_cap_pure_quality_v1")
        self.assertEqual(real_ledger["budget_policy"]["tests_spent_count"], 1)
        self.assertEqual(real_ledger["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(real_ledger["test_spend_log"][0]["status"], "spent_failed_outcome_threshold")
        with self.assertRaises(ValueError):
            runner.load_and_validate_ledger()

    def test_load_and_validate_ledger_accepts_unspent_fixture(self) -> None:
        # The runtime gate accepts an unspent singleton ledger. A synthetic unspent fixture keeps this
        # coverage stable in the committed post-execution (spent) state.
        unspent = copy.deepcopy(runner.read_json(runner.LEDGER_PATH))
        unspent["budget_policy"]["tests_spent_count"] = 0
        unspent["budget_policy"]["tests_available_without_new_review"] = 0
        unspent["test_spend_log"] = []
        unspent["planned_tests"] = [
            {"test_id": runner.PLANNED_TEST_ID, "planned_status": "planned_not_reviewed"}
        ]
        with mock.patch.object(runner, "read_json", return_value=unspent):
            validated = runner.load_and_validate_ledger()
        self.assertEqual(validated["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(validated["test_spend_log"], [])

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

        self.assertEqual(counts, {"q1": 2, "q2": 1, "q3": 0, "q4": 0, "q5": 0})
        self.assertIn("profitability_quality__size_neutral", items[0])
        self.assertIn("profitability_quality__size_neutral", items[1])
        self.assertNotIn("profitability_quality__size_neutral", items[2])

    def test_preregistration_validation_rejects_decision_gate_drift(self) -> None:
        prereg = copy.deepcopy(runner.read_json(runner.PREREGISTRATION_PATH))
        cell = prereg["frozen_design"]["decision_cell"]
        cell["top_fraction"] = 0.9
        cell["minimum_top_count_per_month"] = 99
        cell["mean_net_excess_must_be_positive"] = False
        cell["name_concentration_guard_max_share"] = 0.01
        cell["single_year_positive_return_guard_max_share"] = 0.01

        with mock.patch.object(runner, "read_json", return_value=prereg):
            with self.assertRaises(ValueError):
                runner.load_and_validate_preregistration()

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

    def test_primary_size_neutral_bucket_coverage_counts_all_five_buckets(self) -> None:
        scored = [
            {"size_bucket": "q1", "core_quality_composite_percentile_3factor__size_neutral": 0.7},
            {"size_bucket": "q3", "core_quality_composite_percentile_3factor__size_neutral": 0.4},
        ]

        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 1):
            coverage = runner.primary_size_neutral_bucket_coverage(scored, "20200131")

        self.assertEqual(coverage["q1_count"], 1)
        self.assertEqual(coverage["q2_count"], 0)
        self.assertEqual(coverage["q3_count"], 1)
        self.assertEqual(coverage["q4_count"], 0)
        self.assertEqual(coverage["q5_count"], 0)
        self.assertEqual(coverage["thin_bucket_count"], 3)
        self.assertFalse(coverage["passes_minimum_bucket_count"])

    def test_zero_primary_composite_month_is_not_a_size_coverage_violation(self) -> None:
        diagnostics = {
            "primary_size_neutral_thin_month_count": 0,
            "primary_size_neutral_min_bucket_observation_count": 0,
            "primary_size_neutral_coverage_month_count": 0,
            "primary_size_neutral_bucket_coverage_by_month": [],
            "primary_no_cohort_zero_composite_month_count": 0,
            "primary_no_cohort_zero_composite_months": [],
        }
        scored = [
            {"size_bucket": "q1", "core_quality_composite_percentile_3factor__size_neutral": 0.7},
            {"size_bucket": "q2", "core_quality_composite_percentile_3factor__size_neutral": 0.6},
        ]

        runner.update_primary_size_coverage_diagnostics(scored, "20180131", diagnostics)

        self.assertEqual(diagnostics["primary_no_cohort_zero_composite_month_count"], 1)
        self.assertEqual(diagnostics["primary_no_cohort_zero_composite_months"], ["20180131"])
        self.assertEqual(diagnostics["primary_size_neutral_thin_month_count"], 0)
        self.assertEqual(diagnostics["primary_size_neutral_coverage_month_count"], 0)
        self.assertEqual(diagnostics["primary_size_neutral_bucket_coverage_by_month"], [])

    def test_cohort_forming_month_with_thin_size_bucket_still_fails(self) -> None:
        diagnostics = {
            "primary_size_neutral_thin_month_count": 0,
            "primary_size_neutral_min_bucket_observation_count": 0,
            "primary_size_neutral_coverage_month_count": 0,
            "primary_size_neutral_bucket_coverage_by_month": [],
            "primary_no_cohort_zero_composite_month_count": 0,
            "primary_no_cohort_zero_composite_months": [],
        }
        scored = [
            {
                "size_bucket": "q1",
                "core_quality_composite_percentile_3factor__size_neutral": 0.7,
                "core_quality_composite_percentile_3factor__industry_size_neutral": 0.6,
            },
            {
                "size_bucket": "q3",
                "core_quality_composite_percentile_3factor__size_neutral": 0.4,
                "core_quality_composite_percentile_3factor__industry_size_neutral": 0.3,
            },
        ]

        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 1):
            runner.update_primary_size_coverage_diagnostics(scored, "20200131", diagnostics)

        self.assertEqual(diagnostics["primary_size_neutral_coverage_month_count"], 1)
        self.assertEqual(diagnostics["primary_size_neutral_thin_month_count"], 1)
        self.assertEqual(diagnostics["primary_size_neutral_min_bucket_observation_count"], 0)

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

    def test_pipeline_sanity_rejects_thin_primary_size_neutral_coverage(self) -> None:
        primary_pass = {
            "cell_id": "core_quality_composite_percentile_3factor_industry_size_neutral_equal_weight_504d_CSI300",
            "diagnostic_role": "primary_decision_cell",
            "monthly_cohort_count": 50,
        }
        diagnostics = {"primary_size_neutral_thin_month_count": 1}

        with self.assertRaises(ValueError):
            runner.validate_pipeline_result_sanity([{"row": 1}], [primary_pass], diagnostics)

    def test_pipeline_sanity_accepts_zero_composite_startup_months_excluded_from_gate(self) -> None:
        primary_pass = {
            "cell_id": "core_quality_composite_percentile_3factor_industry_size_neutral_equal_weight_504d_CSI300",
            "diagnostic_role": "primary_decision_cell",
            "monthly_cohort_count": 1,
        }
        diagnostics = {
            "primary_size_neutral_thin_month_count": 0,
            "primary_size_neutral_coverage_month_count": 1,
            "primary_no_cohort_zero_composite_month_count": 3,
            "primary_no_cohort_zero_composite_months": ["20180131", "20180228", "20180330"],
        }

        runner.validate_pipeline_result_sanity([{"row": 1}], [primary_pass], diagnostics)


if __name__ == "__main__":
    unittest.main()
