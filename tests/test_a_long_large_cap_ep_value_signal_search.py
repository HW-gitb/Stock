from __future__ import annotations

import copy
import unittest
from unittest import mock

from runners import a_long_full_main_board_signal_search as base
from runners import a_long_large_cap_ep_value_signal_search as runner


def _pit_row(end_date: str, field: str, value: float) -> dict:
    # ann_date == f_ann_date == end_date keeps every row point-in-time visible for as-ofs after the
    # period end; the income/balancesheet/cashflow tables require f_ann_date, which this supplies.
    return {"end_date": end_date, "ann_date": end_date, "f_ann_date": end_date, field: value}


class _FakeStore:
    def __init__(self, rows_by_call: dict[str, list[dict]]) -> None:
        self._rows = rows_by_call

    def records(self, call_id: str) -> list[dict]:
        return self._rows.get(call_id, [])


class ALongLargeCapEpValueSignalSearchTest(unittest.TestCase):
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
        prereg = runner.load_and_validate_preregistration()
        audit_report = runner.load_and_validate_market_cap_audit_report()
        self.assertEqual(prereg["artifact_id"], "a_long_large_cap_ep_value_20260608")
        self.assertEqual(
            prereg["scope"]["preregistration_review_status"],
            "passed_independent_review_ready_for_freeze",
        )
        self.assertEqual(
            audit_report["decision"]["audit_status"],
            "passed_large_cap_market_cap_audit_for_signal_package",
        )
        # Post-execution committed state: the singleton ledger is schema-valid and spent, and the
        # unspent runtime gate now correctly refuses it (the spent singleton cannot be re-run).
        real_ledger = runner.read_json(runner.LEDGER_PATH)
        runner.validate_json(runner.LEDGER_SCHEMA_PATH, real_ledger)
        self.assertEqual(real_ledger["family_id"], "a_long_large_cap_ep_value_v1")
        self.assertEqual(real_ledger["budget_policy"]["tests_spent_count"], 1)
        self.assertEqual(real_ledger["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(real_ledger["test_spend_log"][0]["status"], "spent_failed_outcome_threshold")
        with self.assertRaises(ValueError):
            runner.load_and_validate_ledger()

    def _unspent_ledger_fixture(self) -> dict:
        # The real singleton ledger is spent post-execution (planned_tests emptied); this synthetic
        # unspent fixture keeps the hardened-gate acceptance / drift coverage stable.
        unspent = copy.deepcopy(runner.read_json(runner.LEDGER_PATH))
        unspent["ledger_status"] = "active_planned_test_pending_review"
        unspent["budget_policy"]["tests_spent_count"] = 0
        unspent["budget_policy"]["tests_available_without_new_review"] = 0
        unspent["test_spend_log"] = []
        unspent["planned_tests"] = [
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
        return unspent

    def test_load_and_validate_ledger_accepts_unspent_fixture(self) -> None:
        with mock.patch.object(runner, "read_json", return_value=self._unspent_ledger_fixture()):
            validated = runner.load_and_validate_ledger()
        self.assertEqual(validated["budget_policy"]["tests_spent_count"], 0)
        self.assertEqual(validated["test_spend_log"], [])

    def test_ledger_validation_rejects_schema_invalid_ledger(self) -> None:
        ledger = copy.deepcopy(runner.read_json(runner.LEDGER_PATH))
        ledger.pop("artifact_id", None)
        ledger["unexpected_extra_field"] = True
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_ledger_validation_rejects_already_spent_singleton(self) -> None:
        ledger = self._unspent_ledger_fixture()
        ledger["budget_policy"]["tests_spent_count"] = 1
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

    def test_ledger_validation_rejects_drifted_result_ref(self) -> None:
        ledger = self._unspent_ledger_fixture()
        ledger["planned_tests"][0]["planned_result_ref"] = "research/results/somewhere_else/execution_summary.json"
        with mock.patch.object(runner, "read_json", return_value=ledger):
            with self.assertRaises(ValueError):
                runner.load_and_validate_ledger()

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
            "ep_value_industry_size_neutral_equal_weight_504d_CSI300",
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
        # The two diagnostic factors are reported only as the industry_size_neutral equal-weight view.
        for factor in runner.DIAGNOSTIC_FACTORS:
            self.assertIn(f"{factor}_industry_size_neutral_equal_weight_504d_CSI300", cell_ids)

    def test_ttm_rollover_annual_period_passes_through(self) -> None:
        values = {"20191231": 50.0, "20201231": 80.0}
        self.assertEqual(runner.ttm_rollover(values), 80.0)

    def test_ttm_rollover_interim_period_uses_prior_fy_minus_prior_same_period(self) -> None:
        values = {
            "20200331": 10.0,
            "20200630": 25.0,
            "20200930": 40.0,
            "20201231": 60.0,
            "20210331": 12.0,
        }
        # TTM at 2021Q1 = latest_ytd(12) + prior_FY_annual(60) - prior_year_same_period_ytd(10) = 62.
        self.assertAlmostEqual(runner.ttm_rollover(values), 62.0)

    def test_ttm_rollover_missing_rollover_rows_returns_none(self) -> None:
        self.assertIsNone(runner.ttm_rollover({}))
        # Interim latest with no prior-fiscal-year annual nor prior-year same period.
        self.assertIsNone(runner.ttm_rollover({"20210331": 12.0}))
        # Has prior FY annual but missing prior-year same-period YTD.
        self.assertIsNone(runner.ttm_rollover({"20201231": 60.0, "20210331": 12.0}))

    def _scored_store(self) -> _FakeStore:
        income = [
            _pit_row("20200331", "n_income_attr_p", 10.0),
            _pit_row("20201231", "n_income_attr_p", 60.0),
            _pit_row("20210331", "n_income_attr_p", 12.0),
        ]
        cashflow = [
            _pit_row("20200331", "n_cashflow_act", 5.0),
            _pit_row("20201231", "n_cashflow_act", 30.0),
            _pit_row("20210331", "n_cashflow_act", 6.0),
        ]
        balance = [_pit_row("20210331", "total_hldr_eqy_exc_min_int", 200.0)]
        return _FakeStore(
            {
                base.call_id_for("income", "T"): income,
                base.call_id_for("cashflow", "T"): cashflow,
                base.call_id_for("balancesheet", "T"): balance,
            }
        )

    def test_ep_signal_values_scored_emits_all_three_factors(self) -> None:
        values, status = runner.ep_signal_values(
            store=self._scored_store(),
            symbol="T",
            as_of="20210601",
            restatement_exclusions=set(),
            circ_mv=100.0,
        )
        self.assertEqual(status, "scored")
        # ep_value = TTM net income (12 + 60 - 10 = 62) / circ_mv(100).
        self.assertAlmostEqual(values["ep_value"], 0.62)
        # book_to_market = 200 / 100.
        self.assertAlmostEqual(values["book_to_market"], 2.0)
        # cash_flow_to_price = TTM CFO (6 + 30 - 5 = 31) / 100.
        self.assertAlmostEqual(values["cash_flow_to_price"], 0.31)

    def test_ep_signal_values_non_positive_earnings_excludes_primary_keeps_diagnostics(self) -> None:
        income = [
            _pit_row("20200331", "n_income_attr_p", 10.0),
            _pit_row("20201231", "n_income_attr_p", 5.0),
            _pit_row("20210331", "n_income_attr_p", -40.0),
        ]
        store = _FakeStore(
            {
                base.call_id_for("income", "T"): income,
                base.call_id_for("cashflow", "T"): [_pit_row("20210331", "n_cashflow_act", 9.0),
                                                    _pit_row("20201231", "n_cashflow_act", 30.0),
                                                    _pit_row("20200331", "n_cashflow_act", 4.0)],
                base.call_id_for("balancesheet", "T"): [_pit_row("20210331", "total_hldr_eqy_exc_min_int", 50.0)],
            }
        )
        values, status = runner.ep_signal_values(
            store=store, symbol="T", as_of="20210601", restatement_exclusions=set(), circ_mv=100.0
        )
        # TTM net income = -40 + 5 - 10 = -45 <= 0 -> non_positive_earnings, ep_value omitted.
        self.assertEqual(status, "non_positive_earnings")
        self.assertNotIn("ep_value", values)
        self.assertIn("book_to_market", values)
        self.assertIn("cash_flow_to_price", values)

    def test_ep_signal_values_insufficient_ttm_history(self) -> None:
        store = _FakeStore(
            {
                base.call_id_for("income", "T"): [_pit_row("20210331", "n_income_attr_p", 12.0)],
                base.call_id_for("cashflow", "T"): [],
                base.call_id_for("balancesheet", "T"): [_pit_row("20210331", "total_hldr_eqy_exc_min_int", 200.0)],
            }
        )
        values, status = runner.ep_signal_values(
            store=store, symbol="T", as_of="20210601", restatement_exclusions=set(), circ_mv=100.0
        )
        self.assertEqual(status, "insufficient_ttm")
        self.assertNotIn("ep_value", values)
        self.assertIn("book_to_market", values)

    def test_ep_signal_values_no_circ_mv_returns_empty(self) -> None:
        values, status = runner.ep_signal_values(
            store=self._scored_store(),
            symbol="T",
            as_of="20210601",
            restatement_exclusions=set(),
            circ_mv=0.0,
        )
        self.assertEqual(status, "no_circ_mv")
        self.assertEqual(values, {})

    def test_size_neutral_scores_require_minimum_bucket_count(self) -> None:
        items = [
            {"symbol": "a", "size_bucket": "q1", "ep_value": 1.0},
            {"symbol": "b", "size_bucket": "q1", "ep_value": 2.0},
            {"symbol": "c", "size_bucket": "q2", "ep_value": 3.0},
        ]
        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 2):
            counts = runner.add_size_neutral_scores(items, "ep_value")
        self.assertEqual(counts, {"q1": 2, "q2": 1, "q3": 0, "q4": 0, "q5": 0})
        self.assertIn("ep_value__size_neutral", items[0])
        self.assertIn("ep_value__size_neutral", items[1])
        self.assertNotIn("ep_value__size_neutral", items[2])

    def test_marginal_industry_size_neutral_combines_half_and_half(self) -> None:
        complete = {
            "symbol": "000001.SZ",
            "ep_value__industry_neutral": 0.6,
            "ep_value__size_neutral": 0.5,
            "book_to_market__industry_neutral": 0.9,
            "book_to_market__size_neutral": 0.8,
        }
        missing = {
            "symbol": "000002.SZ",
            "ep_value__industry_neutral": 0.6,
        }
        coverage = runner.add_marginal_industry_size_neutral_scores([complete, missing])
        self.assertEqual(coverage["ep_value_industry_size_neutral_available_observation_count"], 1)
        self.assertAlmostEqual(complete["ep_value__industry_size_neutral"], 0.55)
        self.assertAlmostEqual(complete["book_to_market__industry_size_neutral"], 0.85)
        self.assertNotIn("ep_value__industry_size_neutral", missing)

    def test_preregistration_validation_rejects_decision_gate_drift(self) -> None:
        prereg = copy.deepcopy(runner.read_json(runner.PREREGISTRATION_PATH))
        cell = prereg["frozen_design"]["decision_cell"]
        cell["top_fraction"] = 0.9
        cell["minimum_top_count_per_month"] = 99
        cell["statistical_alpha_clue_gates"]["minimum_hac_t_stat"] = 1.0
        with mock.patch.object(runner, "read_json", return_value=prereg):
            with self.assertRaises(ValueError):
                runner.load_and_validate_preregistration()

    def test_preregistration_validation_rejects_earnings_basis_search(self) -> None:
        prereg = copy.deepcopy(runner.read_json(runner.PREREGISTRATION_PATH))
        prereg["frozen_design"]["signal_rule"]["earnings_basis_search_allowed"] = True
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
            "primary_no_cohort_zero_score_months": [],
            "primary_incomplete_size_coverage_months": [],
        }
        primary_series = {"cohort_returns": [0.01] * 50, "cohort_as_ofs": ["x"] * 50}
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
            "primary_no_cohort_zero_score_months": [],
            "primary_incomplete_size_coverage_months": [],
        }
        primary_series = {"cohort_returns": [0.01], "cohort_as_ofs": ["x"]}
        with self.assertRaises(ValueError):
            runner.validate_pipeline_result_sanity([{"row": 1}], [primary], diagnostics, primary_series)

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
        diagnostics = self._coverage_diagnostics()
        scored = [
            {"size_bucket": "q1", "ep_value": 1.0, "ep_value__industry_size_neutral": 0.6}
            for _ in range(2)
        ]
        for bucket in ["q2", "q3", "q4", "q5"]:
            scored.append({"size_bucket": bucket, "ep_value": 1.0})
        with mock.patch.object(runner, "MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY", 2):
            runner.update_primary_size_coverage_diagnostics(scored, "20180330", diagnostics)
        self.assertEqual(diagnostics["primary_incomplete_size_coverage_month_count"], 1)
        self.assertEqual(diagnostics["primary_incomplete_size_coverage_months"], ["20180330"])
        self.assertEqual(diagnostics["primary_size_neutral_thin_month_count"], 0)
        self.assertEqual(diagnostics["primary_size_neutral_coverage_month_count"], 0)

    def test_incomplete_month_excluded_from_primary_cohort_but_kept_for_non_size_views(self) -> None:
        def row(as_of: str, symbol: str, score: float, excess: float) -> dict:
            return {
                "as_of": as_of,
                "symbol": symbol,
                "horizon": runner.PRIMARY_HORIZON,
                "market_cap": 1.0,
                "ep_value__industry_size_neutral": score,
                "ep_value__non_neutral": score,
                f"excess_{runner.PRIMARY_BENCHMARK}": excess,
            }

        rows = []
        for i in range(15):
            rows.append(row("20180330", f"INC{i}", 0.10 * i, 0.02))  # incomplete startup-ramp month
            rows.append(row("20200131", f"OK{i}", 0.10 * i, 0.01))  # normal month

        results, primary_series, primary_selections = runner.summarize_results(rows, {"20180330"})

        self.assertNotIn("20180330", primary_series["cohort_as_ofs"])
        self.assertIn("20200131", primary_series["cohort_as_ofs"])
        self.assertNotIn("20180330", primary_selections)
        non_neutral = next(
            cell
            for cell in results
            if cell["cell_id"] == "ep_value_non_neutral_equal_weight_504d_CSI300"
        )
        self.assertEqual(non_neutral["monthly_cohort_count"], 2)

    def _consistent_summary(self) -> dict:
        primary = {
            "cell_id": "ep_value_industry_size_neutral_equal_weight_504d_CSI300",
            "signal_id": "ep_value",
            "view": "industry_size_neutral",
            "weighting": "equal_weight",
            "horizon_trading_days": 504,
            "benchmark": "CSI300",
            "diagnostic_role": "primary_decision_cell",
        }
        diag = {
            "cell_id": "book_to_market_industry_size_neutral_equal_weight_252d_CSI1000",
            "signal_id": "book_to_market",
            "view": "industry_size_neutral",
            "weighting": "equal_weight",
            "horizon_trading_days": 252,
            "benchmark": "CSI1000",
            "diagnostic_role": "diagnostic_only",
        }
        return {
            "result_cells": [primary, diag],
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
                "primary_no_cohort_zero_score_month_count": 0,
                "primary_no_cohort_zero_score_months": [],
                "primary_incomplete_size_coverage_month_count": 0,
                "primary_incomplete_size_coverage_months": [],
                "result_cell_count": 2,
            },
        }

    def test_summary_consistency_accepts_consistent_summary(self) -> None:
        runner.validate_summary_internal_consistency(self._consistent_summary())

    def test_summary_consistency_rejects_cell_id_metadata_mismatch(self) -> None:
        summary = self._consistent_summary()
        summary["result_cells"][1]["benchmark"] = "CSI300"  # cell_id still says CSI1000
        with self.assertRaises(ValueError):
            runner.validate_summary_internal_consistency(summary)

    def test_summary_consistency_rejects_verdict_clue_contradiction(self) -> None:
        summary = self._consistent_summary()
        summary["decision"]["is_statistical_alpha_clue"] = True  # verdict still falsified
        with self.assertRaises(ValueError):
            runner.validate_summary_internal_consistency(summary)

    def test_summary_consistency_rejects_tradeable_without_clue(self) -> None:
        summary = self._consistent_summary()
        summary["decision"]["is_tradeable_candidate"] = True
        summary["decision"]["tradeable_candidate_count"] = 1
        with self.assertRaises(ValueError):
            runner.validate_summary_internal_consistency(summary)

    def test_summary_consistency_rejects_count_list_length_mismatch(self) -> None:
        summary = self._consistent_summary()
        summary["execution_diagnostics"]["primary_no_cohort_zero_score_month_count"] = 1
        with self.assertRaises(ValueError):
            runner.validate_summary_internal_consistency(summary)


if __name__ == "__main__":
    unittest.main()
