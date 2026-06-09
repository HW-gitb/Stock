"""Unit + integration tests for the A-long large-cap BATCH multi-factor signal-search runner.

Covers the pure factor math (TTM rollover, daily returns, low-beta / low-max / momentum trailing
windows), the family-equal-weight composite blend, cohort formation, Benjamini-Hochberg FDR, the
two-tier per-factor decision (FDR survival + robustness gates -> clue; relative-NAV gate -> tradeable),
and integration checks that the runner's preregistration / ledger assertions match the real frozen
artifacts and that execution is double-confirmation gated."""
from __future__ import annotations

import types
import unittest
from unittest import mock

import jsonschema

import runners.a_long_large_cap_batch_factor_search_signal_search as r


class FactorMathTests(unittest.TestCase):
    def test_ttm_rollover_annual_is_passthrough(self) -> None:
        self.assertEqual(r.ttm_rollover({"20231231": 123.0}), 123.0)

    def test_ttm_rollover_interim_uses_prior_fy_and_prior_same_period(self) -> None:
        values = {"20230930": 30.0, "20221231": 80.0, "20220930": 20.0}
        self.assertAlmostEqual(r.ttm_rollover(values), 90.0)

    def test_ttm_rollover_missing_rollover_rows_returns_none(self) -> None:
        self.assertIsNone(r.ttm_rollover({"20230930": 30.0}))
        self.assertIsNone(r.ttm_rollover({}))

    def test_daily_return_series_skips_nonpositive_and_resets(self) -> None:
        rows = {
            "20200101": {"close": 100.0},
            "20200102": {"close": 110.0},
            "20200103": {"close": 0.0},
            "20200106": {"close": 120.0},
        }
        dates, rets = r.daily_return_series(rows)
        self.assertEqual(dates, ["20200102"])
        self.assertAlmostEqual(rets[0], 0.1)

    def test_low_max_score_is_negative_of_window_max(self) -> None:
        dates = ["20200102", "20200103", "20200106"]
        rets = [0.1, -0.05, 0.03]
        self.assertAlmostEqual(r.low_max_score(dates, rets, "20200106", 3), -0.1)

    def test_low_max_requires_full_window(self) -> None:
        dates = ["20200102", "20200103"]
        rets = [0.1, -0.05]
        self.assertIsNone(r.low_max_score(dates, rets, "20200103", 3))

    def test_low_max_respects_as_of_cutoff(self) -> None:
        dates = ["20200102", "20200103", "20200106"]
        rets = [0.01, 0.02, 0.99]
        # as_of excludes the 0.99 spike -> window is the first two -> -max(0.01,0.02)
        self.assertAlmostEqual(r.low_max_score(dates, rets, "20200103", 2), -0.02)

    def test_low_beta_score_is_negative_beta(self) -> None:
        # stock = 2x index exactly -> beta 2 -> score -2
        dates = ["d1", "d2", "d3", "d4"]
        stock = [0.02, -0.04, 0.06, -0.02]
        index_by_date = {"d1": 0.01, "d2": -0.02, "d3": 0.03, "d4": -0.01}
        self.assertAlmostEqual(r.low_beta_score(dates, stock, index_by_date, "d4", 4), -2.0, places=6)

    def test_low_beta_requires_full_window(self) -> None:
        dates = ["d1", "d2"]
        stock = [0.02, -0.04]
        index_by_date = {"d1": 0.01, "d2": -0.02}
        self.assertIsNone(r.low_beta_score(dates, stock, index_by_date, "d2", 4))

    def test_momentum_12_1_skips_recent_window(self) -> None:
        trade_dates = [f"d{i:02d}" for i in range(10)]
        # close grows; start_days_ago=4, end_days_ago=1 -> end=d08, start=d05
        prices = {f"d{i:02d}": {"close": 100.0 + i} for i in range(10)}
        as_of = "d09"
        score = r.momentum_12_1_score(prices, trade_dates, as_of, 4, 1)
        self.assertAlmostEqual(score, (108.0 / 105.0) - 1.0)

    def test_momentum_requires_enough_history(self) -> None:
        trade_dates = ["d0", "d1", "d2"]
        prices = {"d0": {"close": 100.0}, "d1": {"close": 101.0}, "d2": {"close": 102.0}}
        self.assertIsNone(r.momentum_12_1_score(prices, trade_dates, "d2", 5, 1))


class CompositeBlendTests(unittest.TestCase):
    def test_family_equal_weight_blend(self) -> None:
        item = {
            "book_to_circ_mv__industry_size_neutral": 0.8,
            "cash_flow_to_circ_mv__industry_size_neutral": 0.6,
            "low_beta__industry_size_neutral": 0.4,
        }
        available = r.add_composite_scores([item])
        self.assertEqual(available, 1)
        # value family mean = 0.7, low_risk family mean = 0.4 -> composite = mean(0.7, 0.4) = 0.55
        self.assertAlmostEqual(item[r.COMPOSITE_ID], 0.55)
        # the blend is written directly as the composite isn score (NOT re-neutralized)
        self.assertAlmostEqual(item[f"{r.COMPOSITE_ID}__industry_size_neutral"], 0.55)

    def test_no_scores_no_composite(self) -> None:
        item = {"symbol": "x"}
        available = r.add_composite_scores([item])
        self.assertEqual(available, 0)
        self.assertNotIn(r.COMPOSITE_ID, item)


class CohortFormationTests(unittest.TestCase):
    def test_thin_month_is_skipped_full_month_forms(self) -> None:
        score_field = "f__industry_size_neutral"
        rows_by = {}
        as_ofs = {504: set()}
        # thin month: 5 names (< MIN_TOP_COUNT) -> skipped
        rows_by[(504, "20200131")] = [
            {"symbol": f"thin{i}", score_field: 0.5, "excess_CSI300": 0.01, "market_cap": 1.0} for i in range(5)
        ]
        as_ofs[504].add("20200131")
        # full month: 50 names -> forms a cohort
        rows_by[(504, "20200229")] = [
            {"symbol": f"full{i}", score_field: i / 50.0, "excess_CSI300": 0.02, "market_cap": 1.0} for i in range(50)
        ]
        as_ofs[504].add("20200229")
        agg = r.cohort_excess_by_as_of(
            rows_by, as_ofs, score_field=score_field, excess_field="excess_CSI300", horizon=504, weighting="equal_weight"
        )
        self.assertEqual(agg["cohort_as_ofs"], ["20200229"])
        self.assertEqual(len(agg["cohort_returns"]), 1)
        self.assertAlmostEqual(agg["cohort_returns"][0], 0.02)

    def test_size_coverage_excluded_month_is_skipped(self) -> None:
        score_field = "f__industry_size_neutral"
        rows_by = {
            (504, "20200229"): [
                {"symbol": f"x{i}", score_field: i / 50.0, "excess_CSI300": 0.02, "market_cap": 1.0} for i in range(50)
            ]
        }
        as_ofs = {504: {"20200229"}}
        agg = r.cohort_excess_by_as_of(
            rows_by, as_ofs, score_field=score_field, excess_field="excess_CSI300", horizon=504,
            weighting="equal_weight", excluded_as_ofs={"20200229"},
        )
        self.assertEqual(agg["cohort_returns"], [])
        self.assertEqual(agg["cohort_as_ofs"], [])


class InputCoverageTests(unittest.TestCase):
    def test_no_circ_mv_marks_all_factors_missing_input(self) -> None:
        values, status = r.batch_factor_values(
            store=None, symbol="x", as_of="20200131", restatement_exclusions=set(),
            circ_mv=None, price_rows={}, index_ret_by_date={}, trade_dates=[],
        )
        self.assertEqual(values, {})
        self.assertEqual(status["no_circ_mv_observation_count"], 1)
        for factor in r.BATCH_FACTORS:
            self.assertEqual(status[r._input_key(factor, "missing_input")], 1)


class FdrAuditTests(unittest.TestCase):
    def test_sorted_table_ranks_and_survival(self) -> None:
        results = _all_primary_cells({"low_beta": {"p_value": 0.001}})
        # set every non-low_beta primary p to 0.9
        audit = r.build_fdr_audit(results)
        rows = audit["sorted_primary_p_values"]
        self.assertEqual(len(rows), r.M_TOTAL_HYPOTHESES)
        self.assertEqual([row["rank"] for row in rows], list(range(1, r.M_TOTAL_HYPOTHESES + 1)))
        # lowest p_value ranks first
        self.assertEqual(rows[0]["factor_id"], "low_beta")
        lb = next(row for row in rows if row["factor_id"] == "low_beta")
        self.assertTrue(lb["survives_fdr_q_research_clue"])
        self.assertAlmostEqual(audit["bh_threshold_p_at_q_research_clue"], 0.001)


class PipelineLeakGuardTests(unittest.TestCase):
    def test_excluded_month_in_primary_cohort_raises(self) -> None:
        rows = [{"horizon": 504, "as_of": "20200131"}]
        results = _all_result_cells_minimal()
        primary_series = {f: {"cohort_returns": [0.01, 0.02], "cohort_as_ofs": ["20200131", "20200229"]} for f in r.ALL_FACTORS}
        excluded = {f: set() for f in r.ALL_FACTORS}
        excluded["low_beta"] = {"20200131"}  # leaks into low_beta's primary cohort
        with self.assertRaises(ValueError):
            r.validate_pipeline_result_sanity(rows, results, primary_series, excluded)

    def test_clean_coverage_passes(self) -> None:
        rows = [{"horizon": 504, "as_of": "20200131"}]
        results = _all_result_cells_minimal()
        primary_series = {f: {"cohort_returns": [0.01, 0.02], "cohort_as_ofs": ["20200131", "20200229"]} for f in r.ALL_FACTORS}
        excluded = {f: {"20200331"} for f in r.ALL_FACTORS}  # excluded month not in any cohort
        r.validate_pipeline_result_sanity(rows, results, primary_series, excluded)


class BenjaminiHochbergTests(unittest.TestCase):
    def test_no_survivors_when_all_insignificant(self) -> None:
        pvals = {f"f{i}": 0.9 for i in range(10)}
        survivors, threshold = r.benjamini_hochberg(pvals, 0.1)
        self.assertEqual(survivors, set())
        self.assertIsNone(threshold)

    def test_none_pvalue_treated_as_one(self) -> None:
        pvals = {f"f{i}": None for i in range(10)}
        survivors, _ = r.benjamini_hochberg(pvals, 0.1)
        self.assertEqual(survivors, set())

    def test_two_survivors(self) -> None:
        pvals = {f"f{i}": 0.9 for i in range(10)}
        pvals["f0"] = 0.005  # <= (1/10)*0.1 = 0.01
        pvals["f1"] = 0.015  # <= (2/10)*0.1 = 0.02
        survivors, threshold = r.benjamini_hochberg(pvals, 0.1)
        self.assertEqual(survivors, {"f0", "f1"})
        self.assertAlmostEqual(threshold, 0.015)

    def test_step_up_includes_lower_pvalue_below_cutoff(self) -> None:
        # classic BH step-up: an intermediate p that fails its OWN rank is rescued because a
        # higher-rank p passes and lifts the cutoff above it. m=10, q=0.1.
        pvals = {f"f{i}": 0.9 for i in range(10)}
        pvals["f0"] = 0.001  # rank1: <= (1/10)*0.1 = 0.01  pass
        pvals["f1"] = 0.022  # rank2: <= (2/10)*0.1 = 0.02  FAILS at its own rank
        pvals["f2"] = 0.025  # rank3: <= (3/10)*0.1 = 0.03  pass -> k_max=3, cutoff 0.025 rescues f1
        survivors, threshold = r.benjamini_hochberg(pvals, 0.1)
        self.assertEqual(survivors, {"f0", "f1", "f2"})
        self.assertAlmostEqual(threshold, 0.025)


def _primary_cell(factor: str, *, p_value, mean=0.01, passes=True) -> dict:
    return {
        "cell_id": r.PRIMARY_CELL_IDS[factor],
        "signal_id": factor,
        "view": r.PRIMARY_VIEW,
        "weighting": "equal_weight",
        "diagnostic_role": "primary_decision_cell",
        "horizon_trading_days": r.PRIMARY_HORIZON,
        "benchmark": r.PRIMARY_BENCHMARK,
        "monthly_cohort_count": 60,
        "mean_monthly_cohort_net_excess": mean,
        "monthly_cohort_std": 0.1,
        "monthly_clustered_t_stat": 2.5,
        "monthly_t_stat_method": r.base.MONTHLY_T_STAT_METHOD,
        "hac_lag_months": 24,
        "p_value": p_value,
        "minimum_monthly_top_count": 20,
        "positive_month_count": 40,
        "worst_monthly_cohort_excess": -0.2,
        "best_monthly_cohort_excess": 0.3,
        "diagnostic_max_drawdown_on_monthly_excess": -0.1,
        "top_symbol_selection_share": 0.05,
        "max_single_year_positive_return_share": 0.2,
        "passes_minimum_monthly_cohorts": passes,
        "passes_minimum_top_count": passes,
        "passes_name_concentration_guard": passes,
        "passes_single_year_concentration_guard": passes,
    }


def _all_primary_cells(overrides: dict) -> list[dict]:
    cells = []
    for factor in r.ALL_FACTORS:
        spec = overrides.get(factor, {})
        cells.append(_primary_cell(factor, p_value=spec.get("p_value", 0.9), mean=spec.get("mean", 0.01), passes=spec.get("passes", True)))
    return cells


def _all_result_cells_minimal() -> list[dict]:
    """All 48 cells with just the fields validate_pipeline_result_sanity reads."""
    cells = []
    for spec in r.result_specs():
        is_primary = (
            spec["view"] == r.PRIMARY_VIEW and spec["weighting"] == "equal_weight"
            and spec["horizon_trading_days"] == r.PRIMARY_HORIZON and spec["benchmark"] == r.PRIMARY_BENCHMARK
        )
        cells.append(
            {
                "cell_id": r.cell_id_for(spec),
                "signal_id": spec["signal_id"],
                "diagnostic_role": "primary_decision_cell" if is_primary else "diagnostic_only",
            }
        )
    return cells


def _sub_period(both_positive: bool = True) -> dict:
    val = 0.01 if both_positive else -0.01
    return {
        "valid_cohort_count": 60,
        "split_index": 30,
        "first_half": {"cohort_count": 30, "mean_net_excess": 0.01, "hac_t_stat": 1.0, "hac_lag_months": 12},
        "second_half": {"cohort_count": 30, "mean_net_excess": val, "hac_t_stat": 1.0, "hac_lag_months": 12},
        "both_halves_mean_excess_positive": both_positive,
    }


class BatchDecisionTests(unittest.TestCase):
    def test_dry_when_no_factor_survives(self) -> None:
        results = _all_primary_cells({})
        sub = {f: _sub_period(True) for f in r.ALL_FACTORS}
        decision, factor_results = r.batch_decision(results, sub, {})
        self.assertTrue(decision["is_dry_batch"])
        self.assertEqual(decision["research_verdict"], r.DRY_VERDICT)
        self.assertEqual(decision["statistical_alpha_clue_count"], 0)
        self.assertEqual(len(factor_results), r.M_TOTAL_HYPOTHESES)

    def test_clue_and_tradeable(self) -> None:
        results = _all_primary_cells({"low_beta": {"p_value": 0.001}})
        sub = {f: _sub_period(True) for f in r.ALL_FACTORS}
        risk = {"low_beta": {"relative_nav_max_drawdown": -0.1}}
        decision, factor_results = r.batch_decision(results, sub, risk)
        self.assertFalse(decision["is_dry_batch"])
        self.assertEqual(decision["research_verdict"], r.CLUE_VERDICT)
        self.assertEqual(decision["surviving_clue_factor_ids"], ["low_beta"])
        self.assertEqual(decision["tradeable_candidate_factor_ids"], ["low_beta"])
        lb = next(item for item in factor_results if item["factor_id"] == "low_beta")
        self.assertTrue(lb["is_statistical_alpha_clue"])
        self.assertTrue(lb["is_tradeable_candidate"])

    def test_clue_not_tradeable_when_drawdown_too_deep(self) -> None:
        results = _all_primary_cells({"low_beta": {"p_value": 0.001}})
        sub = {f: _sub_period(True) for f in r.ALL_FACTORS}
        risk = {"low_beta": {"relative_nav_max_drawdown": -0.3}}
        decision, factor_results = r.batch_decision(results, sub, risk)
        self.assertEqual(decision["statistical_alpha_clue_count"], 1)
        self.assertEqual(decision["tradeable_candidate_count"], 0)
        lb = next(item for item in factor_results if item["factor_id"] == "low_beta")
        self.assertTrue(lb["is_statistical_alpha_clue"])
        self.assertFalse(lb["is_tradeable_candidate"])
        self.assertAlmostEqual(lb["relative_nav_max_drawdown"], -0.3)

    def test_fdr_survivor_failing_robustness_gates_is_not_a_clue(self) -> None:
        results = _all_primary_cells({"low_beta": {"p_value": 0.001, "passes": False}})
        sub = {f: _sub_period(True) for f in r.ALL_FACTORS}
        decision, _ = r.batch_decision(results, sub, {})
        self.assertTrue(decision["is_dry_batch"])
        self.assertEqual(decision["statistical_alpha_clue_count"], 0)

    def test_fdr_survivor_failing_sub_period_is_not_a_clue(self) -> None:
        results = _all_primary_cells({"low_beta": {"p_value": 0.001}})
        sub = {f: _sub_period(True) for f in r.ALL_FACTORS}
        sub["low_beta"] = _sub_period(False)
        decision, _ = r.batch_decision(results, sub, {})
        self.assertTrue(decision["is_dry_batch"])

    def test_missing_primary_cell_raises(self) -> None:
        results = _all_primary_cells({})[:-1]
        sub = {f: _sub_period(True) for f in r.ALL_FACTORS}
        with self.assertRaises(ValueError):
            r.batch_decision(results, sub, {})


class SubPeriodTests(unittest.TestCase):
    def test_both_halves_positive(self) -> None:
        series = {"cohort_returns": [0.01, 0.02, 0.03, 0.04], "cohort_as_ofs": ["a", "b", "c", "d"]}
        out = r.sub_period_robustness(series)
        self.assertTrue(out["both_halves_mean_excess_positive"])

    def test_one_half_negative(self) -> None:
        series = {"cohort_returns": [0.05, 0.05, -0.05, -0.05], "cohort_as_ofs": ["a", "b", "c", "d"]}
        out = r.sub_period_robustness(series)
        self.assertFalse(out["both_halves_mean_excess_positive"])

    def test_too_short(self) -> None:
        out = r.sub_period_robustness({"cohort_returns": [0.01], "cohort_as_ofs": ["a"]})
        self.assertFalse(out["both_halves_mean_excess_positive"])
        self.assertEqual(out["valid_cohort_count"], 1)


class PreregLedgerIntegrationTests(unittest.TestCase):
    """The runner's bespoke assertions must accept the REAL frozen, review-passed artifacts."""

    def test_real_preregistration_validates(self) -> None:
        prereg = r.load_and_validate_preregistration()
        self.assertEqual(prereg["artifact_id"], r.PREREGISTRATION_ARTIFACT_ID)

    def test_real_ledger_now_spent_post_execution(self) -> None:
        # The batch was executed 2026-06-09 (closeout 68ffc99): the singleton is spent and the
        # unspent-gate in load_and_validate_ledger correctly blocks any re-run of the real ledger.
        with self.assertRaises(ValueError):
            r.load_and_validate_ledger()
        raw = r.read_json(r.LEDGER_PATH)
        self.assertEqual(raw["family_id"], r.LEDGER_FAMILY_ID)
        self.assertEqual(raw["budget_policy"]["tests_spent_count"], 1)
        self.assertEqual(raw["ledger_status"], "active_no_new_test_authorized")
        self.assertEqual(raw["test_spend_log"][0]["status"], "spent_passed_research_continue_only")

    def test_real_market_cap_audit_report_validates(self) -> None:
        report = r.load_and_validate_market_cap_audit_report()
        self.assertTrue(report["decision"]["hard_checks_pass"])

    def test_spent_ledger_is_rejected(self) -> None:
        ledger = r.read_json(r.LEDGER_PATH)
        ledger["budget_policy"]["tests_spent_count"] = 1
        tmp = r.OUTPUT_DIR.parent / "_tmp_spent_batch_ledger.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        r.write_json_atomic(tmp, ledger)
        try:
            with self.assertRaises(ValueError):
                r.load_and_validate_ledger(tmp)
        finally:
            tmp.unlink(missing_ok=True)


class ExecutionGateTests(unittest.TestCase):
    def test_require_confirmations(self) -> None:
        with self.assertRaises(RuntimeError):
            r.require_execution_confirmations(confirm_independent_review_pass=False, confirm_post_review_execute=True)
        with self.assertRaises(RuntimeError):
            r.require_execution_confirmations(confirm_independent_review_pass=True, confirm_post_review_execute=False)
        # both true -> no raise
        r.require_execution_confirmations(confirm_independent_review_pass=True, confirm_post_review_execute=True)

    def test_build_summary_refuses_without_confirmations(self) -> None:
        with self.assertRaises(RuntimeError):
            r.build_summary(
                full_raw_root=r.base.RAW_ROOT,
                market_cap_raw_root=r.cap_audit.MARKET_CAP_RAW_ROOT,
                generated_at="2026-06-09T00:00:00+00:00",
                confirm_independent_review_pass=False,
                confirm_post_review_execute=False,
            )

    def test_parse_args_defaults_no_confirmations(self) -> None:
        args = r.parse_args([])
        self.assertFalse(args.confirm_independent_review_pass)
        self.assertFalse(args.confirm_post_review_execute)


class BuildSummaryStructureTests(unittest.TestCase):
    """Stub the heavy data loaders and assert the REAL build_summary output validates against the
    execution-summary schema (every key present, no extras, no missing) and passes the consistency
    guard. This is the integration guarantee that the runner's emitted structure cannot drift from the
    schema without a test failure, without needing the full multi-minute data pipeline."""

    def test_build_summary_output_matches_schema(self) -> None:
        diagnostics = r._new_diagnostics()
        rows = [{"horizon": 504, "as_of": "20200131"}, {"horizon": 252, "as_of": "20200131"}]
        universe_diag = {
            "market_cap_monthly_as_of_count": len(r.MONTHLY_AS_OF_DATES),
            "large_cap_target_universe_size": r.UNIVERSE_SIZE_N,
            "large_cap_signal_universe_observations": 48000,
            "documented_data_quality_exclusion_observation_count": 1,
            "backfilled_after_documented_exclusion_observation_count": 1,
            "outside_prior_audited_universe_after_backfill_observation_count": 0,
            "incomplete_large_cap_universe_month_count": 0,
            "minimum_size_bucket_count": r.UNIVERSE_SIZE_N // 5,
        }
        coverage = {
            "excluded_months_by_factor": {f: [] for f in r.ALL_FACTORS},
            "no_observation_months_by_factor": {f: [] for f in r.ALL_FACTORS},
            "incomplete_size_coverage_months_by_factor": {f: [] for f in r.ALL_FACTORS},
            "observation_month_count_by_factor": {f: 90 for f in r.ALL_FACTORS},
            "input_coverage_by_factor": {f: {o: 0 for o in r.INPUT_OUTCOMES} for f in r.BATCH_FACTORS},
        }
        context = types.SimpleNamespace(symbols=[], trade_dates=[], delist_date_by_symbol={}, list_date_by_symbol={})
        restatement_exclusions = set(range(r.EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT))
        with mock.patch.object(r, "load_and_validate_preregistration", return_value={"artifact_id": r.PREREGISTRATION_ARTIFACT_ID}), \
            mock.patch.object(r, "load_and_validate_ledger", return_value={"budget_policy": {"tests_spent_count": 0}}), \
            mock.patch.object(r, "load_and_validate_market_cap_audit_report", return_value={"decision": {"hard_checks_pass": True}}), \
            mock.patch.object(r, "load_full_main_board_sources", return_value=({"decision": {"hard_checks_pass": True}}, object(), context, restatement_exclusions, 100)), \
            mock.patch.object(r, "load_large_cap_signal_universes", return_value=({}, universe_diag)), \
            mock.patch.object(r, "monthly_cohort_rows", return_value=(rows, {}, diagnostics, coverage)), \
            mock.patch.object(r.base, "index_total_return_close_rows", return_value={}):
            summary = r.build_summary(
                full_raw_root=r.base.RAW_ROOT,
                market_cap_raw_root=r.cap_audit.MARKET_CAP_RAW_ROOT,
                generated_at="2026-06-09T00:00:00+00:00",
                confirm_independent_review_pass=True,
                confirm_post_review_execute=True,
            )
        schema = r.read_json(r.SUMMARY_SCHEMA_PATH)
        jsonschema.validate(summary, schema)
        r.validate_summary_internal_consistency(summary)
        # With empty cohorts every factor is non-significant -> dry batch.
        self.assertEqual(summary["decision"]["research_verdict"], r.DRY_VERDICT)
        self.assertEqual(len(summary["result_cells"]), r.RESULT_CELL_COUNT)
        self.assertEqual(len(summary["factor_results"]), r.M_TOTAL_HYPOTHESES)


class MatrixShapeTests(unittest.TestCase):
    def test_result_cell_matrix(self) -> None:
        self.assertEqual(r.RESULT_CELL_COUNT, 48)
        self.assertEqual(r.M_TOTAL_HYPOTHESES, 10)
        self.assertEqual(len(r.PRIMARY_CELL_IDS), 10)

    def test_primary_cells_are_isn_eq_504_csi300(self) -> None:
        specs = [s for s in r.result_specs() if r.cell_id_for(s) in r.PRIMARY_CELL_IDS.values()]
        self.assertEqual(len(specs), 10)
        for s in specs:
            self.assertEqual(s["view"], r.PRIMARY_VIEW)
            self.assertEqual(s["weighting"], "equal_weight")
            self.assertEqual(s["horizon_trading_days"], r.PRIMARY_HORIZON)
            self.assertEqual(s["benchmark"], r.PRIMARY_BENCHMARK)


if __name__ == "__main__":
    unittest.main()
