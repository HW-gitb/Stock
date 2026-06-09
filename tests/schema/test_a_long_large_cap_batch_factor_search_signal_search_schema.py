"""Schema + internal-consistency tests for the A-long large-cap BATCH multi-factor signal-search
execution summary. The valid fixtures are derived from the runner's own result_specs / factor list so
the 48-cell matrix and 10 primary hypotheses cannot silently drift from the runner. Adversarial mutations
must be rejected either by the JSON Schema (design freeze) or by validate_summary_internal_consistency
(the count/relationship invariants draft-07 cannot express)."""
from __future__ import annotations

import unittest

import jsonschema

import runners.a_long_large_cap_batch_factor_search_signal_search as r


def _cell(spec: dict) -> dict:
    is_primary = (
        spec["view"] == r.PRIMARY_VIEW
        and spec["weighting"] == "equal_weight"
        and spec["horizon_trading_days"] == r.PRIMARY_HORIZON
        and spec["benchmark"] == r.PRIMARY_BENCHMARK
    )
    return {
        "cell_id": r.cell_id_for(spec),
        "signal_id": spec["signal_id"],
        "view": spec["view"],
        "weighting": spec["weighting"],
        "diagnostic_role": "primary_decision_cell" if is_primary else "diagnostic_only",
        "horizon_trading_days": spec["horizon_trading_days"],
        "benchmark": spec["benchmark"],
        "monthly_cohort_count": 60,
        "mean_monthly_cohort_net_excess": 0.01,
        "monthly_cohort_std": 0.1,
        "monthly_clustered_t_stat": 1.0,
        "monthly_t_stat_method": r.base.MONTHLY_T_STAT_METHOD,
        "hac_lag_months": 24,
        "p_value": 0.3,
        "minimum_monthly_top_count": 20,
        "positive_month_count": 35,
        "worst_monthly_cohort_excess": -0.2,
        "best_monthly_cohort_excess": 0.3,
        "diagnostic_max_drawdown_on_monthly_excess": -0.1,
        "top_symbol_selection_share": 0.05,
        "max_single_year_positive_return_share": 0.2,
        "passes_minimum_monthly_cohorts": True,
        "passes_minimum_top_count": True,
        "passes_name_concentration_guard": True,
        "passes_single_year_concentration_guard": True,
    }


def _factor(factor_id: str, *, clue: bool, tradeable: bool) -> dict:
    return {
        "factor_id": factor_id,
        "family": r.FACTOR_FAMILIES.get(factor_id, "composite"),
        "primary_cell_id": r.PRIMARY_CELL_IDS[factor_id],
        "monthly_cohort_count": 60,
        "mean_monthly_cohort_net_excess": 0.01,
        "monthly_clustered_t_stat": 1.0,
        "p_value": 0.3,
        "positive_month_count": 35,
        "top_symbol_selection_share": 0.05,
        "max_single_year_positive_return_share": 0.2,
        "passes_minimum_monthly_cohorts": True,
        "passes_minimum_top_count": True,
        "passes_name_concentration_guard": True,
        "passes_single_year_concentration_guard": True,
        "sub_period_first_half_mean_net_excess": 0.01,
        "sub_period_second_half_mean_net_excess": 0.01,
        "sub_period_both_halves_mean_excess_positive": True,
        "survives_fdr_q_research_clue": clue,
        "survives_fdr_q_strict": False,
        "passes_per_factor_robustness_gates": clue,
        "is_statistical_alpha_clue": clue,
        "relative_nav_max_drawdown": (-0.1 if tradeable else (-0.2 if clue else None)),
        "relative_nav_drawdown_gate_passed": tradeable,
        "is_tradeable_candidate": tradeable,
    }


def make_valid_summary(*, clues: tuple[str, ...] = (), tradeables: tuple[str, ...] = ()) -> dict:
    assert set(tradeables) <= set(clues)
    cells = [_cell(spec) for spec in r.result_specs()]
    factor_results = [_factor(f, clue=f in clues, tradeable=f in tradeables) for f in r.ALL_FACTORS]
    diag = {key: 0 for key in r._new_diagnostics()}
    diag["full_main_board_endpoint_results_count"] = 100
    diag["evaluated_stock_return_rows"] = 12345
    diag["result_cell_count"] = r.RESULT_CELL_COUNT
    is_dry = len(clues) == 0
    size_coverage_audit = {
        "minimum_size_bucket_count_for_primary": r.MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY,
        "size_coverage_gate_applies_to_cohort_forming_months_only": True,
        "gate_excludes_month_from_size_dependent_views": True,
        "by_factor": [
            {
                "factor_id": f,
                "observation_month_count": 90,
                "no_observation_month_count": 0,
                "no_observation_months": [],
                "incomplete_size_coverage_month_count": 0,
                "incomplete_size_coverage_months": [],
                "size_coverage_excluded_month_count": 0,
                "primary_cohort_month_count": 60,
            }
            for f in r.ALL_FACTORS
        ],
    }
    factor_input_coverage = {
        "by_factor": [
            {
                "factor_id": f,
                "available_count": 40000,
                "missing_input_count": 100,
                "non_positive_count": 50,
                "insufficient_ttm_count": 200,
                "insufficient_window_count": 300,
            }
            for f in r.BATCH_FACTORS
        ]
    }
    fdr_audit = {
        "m_total_hypotheses": r.M_TOTAL_HYPOTHESES,
        "q_research_clue_gate": r.Q_RESEARCH_CLUE_GATE,
        "q_strict_diagnostic": r.Q_STRICT_DIAGNOSTIC,
        "bh_threshold_p_at_q_research_clue": None if is_dry else 0.02,
        "bh_threshold_p_at_q_strict": None,
        "sorted_primary_p_values": [
            {
                "rank": i + 1,
                "factor_id": f,
                "primary_cell_id": r.PRIMARY_CELL_IDS[f],
                "p_value": 0.3,
                "bh_critical_value_at_q_research_clue": round(((i + 1) / r.M_TOTAL_HYPOTHESES) * r.Q_RESEARCH_CLUE_GATE, 10),
                "bh_critical_value_at_q_strict": round(((i + 1) / r.M_TOTAL_HYPOTHESES) * r.Q_STRICT_DIAGNOSTIC, 10),
                "survives_fdr_q_research_clue": f in clues,
                "survives_fdr_q_strict": False,
            }
            for i, f in enumerate(r.ALL_FACTORS)
        ],
    }
    return {
        "schema_name": "a_long_large_cap_batch_factor_search_signal_search_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-09T00:00:00+00:00",
        "artifact_id": r.SUMMARY_ARTIFACT_ID,
        "source_refs": [
            r.display_path(r.PREREGISTRATION_PATH),
            r.display_path(r.LEDGER_PATH),
            r.display_path(r.MARKET_CAP_AUDIT_REPORT_PATH),
            r.display_path(r.cap_audit.MATERIALIZATION_SUMMARY_PATH),
            r.display_path(r.cap_audit.DATA_QUALITY_EXCLUSION_DECISION_PATH),
            r.display_path(r.base.AUDIT_REPORT_PATH),
            r.display_path(r.base.RESTATEMENT_EXCLUSION_LIST_PATH),
            r.display_path(r.base.BENCHMARK_ACCESS_PROBE_SUMMARY_PATH),
        ],
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_large_cap_batch_factor_search_signal_search_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_call_executed": False,
            "tushare_call_executed": False,
            "data_fetch_executed": False,
            "local_raw_read_only": True,
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
            "preregistration_review_passed": True,
            "ledger_unspent_before_run": True,
            "market_cap_audit_passed": True,
            "full_main_board_audit_passed": True,
            "benchmark_route_amendment_validated": True,
            "restatement_exclusion_list_loaded": True,
            "restatement_exclusion_groups_expected": r.EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT,
            "restatement_exclusion_groups_found_in_raw": r.EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT,
            "restatement_exclusion_list_applied": True,
            "reviewed_data_quality_exclusion_applied": True,
            "reviewed_data_quality_exclusion_backfilled": True,
            "no_network_calls_executed": True,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_endpoint_results": False,
            "tracked_summary_contains_secret": False,
            "tracked_summary_contains_request_url": False,
        },
        "large_cap_universe_boundary": {
            "board_scope": "main_board_only",
            "selected_market_cap_field": r.SELECTED_MARKET_CAP_FIELD,
            "monthly_as_of_count": len(r.MONTHLY_AS_OF_DATES),
            "universe_size_n": r.UNIVERSE_SIZE_N,
            "size_bucket_count": 5,
            "minimum_size_bucket_count_for_primary_percentile": r.MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY,
            "reviewed_data_quality_exclusion_policy": r.cap_audit.DATA_QUALITY_EXCLUSION_BACKFILL_POLICY,
            "top500_symbols_written_to_tracked_summary": False,
            "market_cap_monthly_as_of_count": len(r.MONTHLY_AS_OF_DATES),
            "large_cap_target_universe_size": r.UNIVERSE_SIZE_N,
            "large_cap_signal_universe_observations": 48000,
            "documented_data_quality_exclusion_observation_count": 1,
            "backfilled_after_documented_exclusion_observation_count": 1,
            "outside_prior_audited_universe_after_backfill_observation_count": 0,
            "incomplete_large_cap_universe_month_count": 0,
            "minimum_size_bucket_count": r.UNIVERSE_SIZE_N // 5,
        },
        "search_design": {
            "factor_count": len(r.BATCH_FACTORS),
            "composite_count": 1,
            "total_primary_hypotheses": r.M_TOTAL_HYPOTHESES,
            "factor_ids": list(r.BATCH_FACTORS),
            "composite_id": r.COMPOSITE_ID,
            "primary_view": r.PRIMARY_VIEW,
            "primary_horizon_trading_days": r.PRIMARY_HORIZON,
            "diagnostic_horizons_trading_days": [r.DIAGNOSTIC_HORIZON],
            "primary_benchmark": r.PRIMARY_BENCHMARK,
            "diagnostic_benchmark": r.SECONDARY_BENCHMARK,
            "stock_return_basis": r.base.STOCK_RETURN_BASIS,
            "benchmark_return_basis": r.base.BENCHMARK_RETURN_BASIS,
            "round_trip_cost": r.base.ROUND_TRIP_COST,
            "top_fraction": r.TOP_FRACTION,
            "minimum_top_count_per_month": r.MIN_TOP_COUNT,
            "minimum_monthly_cohorts": r.MIN_MONTHLY_COHORTS,
            "monthly_t_stat_method": r.base.MONTHLY_T_STAT_METHOD,
            "hac_lag_rule": r.base.HAC_LAG_RULE,
            "decision_type": "batch_bh_fdr_over_primary_cells",
            "fdr_method": "benjamini_hochberg",
            "q_research_clue_gate": r.Q_RESEARCH_CLUE_GATE,
            "q_strict_diagnostic": r.Q_STRICT_DIAGNOSTIC,
            "minimum_allowed_relative_nav_drawdown": r.MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN,
            "max_top_symbol_selection_share": r.MAX_TOP_SYMBOL_SELECTION_SHARE,
            "max_single_year_positive_return_share": r.MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
            "sub_period_split_rule": "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves",
            "diagnostics_can_define_alpha": False,
            "drop_losing_factors_then_re_fdr_executed": False,
            "restatement_exclusion_required": True,
            "low_beta_trailing_days": r.LOW_BETA_TRAILING_DAYS,
            "low_max_trailing_days": r.LOW_MAX_TRAILING_DAYS,
            "momentum_formation_start_days_ago": r.MOMENTUM_FORMATION_START_DAYS_AGO,
            "momentum_formation_end_days_ago": r.MOMENTUM_FORMATION_END_DAYS_AGO,
        },
        "execution_diagnostics": diag,
        "result_cells": cells,
        "factor_results": factor_results,
        "size_coverage_audit": size_coverage_audit,
        "factor_input_coverage": factor_input_coverage,
        "fdr_audit": fdr_audit,
        "decision": {
            "research_verdict": r.DRY_VERDICT if is_dry else r.CLUE_VERDICT,
            "is_dry_batch": is_dry,
            "m_total_hypotheses": r.M_TOTAL_HYPOTHESES,
            "fdr_method": "benjamini_hochberg",
            "q_research_clue_gate": r.Q_RESEARCH_CLUE_GATE,
            "q_strict_diagnostic": r.Q_STRICT_DIAGNOSTIC,
            "bh_threshold_p_at_q_research_clue": None if is_dry else 0.02,
            "bh_threshold_p_at_q_strict": None,
            "statistical_alpha_clue_count": len(clues),
            "tradeable_candidate_count": len(tradeables),
            "surviving_clue_factor_ids": list(clues),
            "tradeable_candidate_factor_ids": list(tradeables),
            "diagnostics_can_rescue_primary_failure": False,
            "drop_losing_factors_then_re_fdr_executed": False,
            "multiple_testing_cannot_uncount_prior_spent_singletons": True,
            "alpha_found_for_production": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "plain_result": "synthetic fixture",
            "next_action": "synthetic fixture",
        },
        "ledger_update_required_after_commit": {
            "ledger_ref": r.display_path(r.LEDGER_PATH),
            "spends_singleton_test": True,
            "test_id": r.PLANNED_TEST_ID,
            "runner_writes_ledger": True,
            "ledger_write_timing": "pending_summary_then_ledger_then_final_summary",
            "ledger_status_after_runner": "active_no_new_test_authorized",
        },
        "prohibited_claims": {
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "batch_factor_proven": False,
            "fdr_uncounts_prior_singletons": False,
            "in_sample_clue_is_out_of_sample_proof": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "result_artifacts": [r.display_path(r.SUMMARY_PATH)],
        "limitations": ["synthetic fixture limitation"],
    }


def load_schema() -> dict:
    return r.read_json(r.SUMMARY_SCHEMA_PATH)


class BatchSummarySchemaValidTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = load_schema()

    def test_dry_summary_is_valid_and_internally_consistent(self) -> None:
        summary = make_valid_summary()
        jsonschema.validate(summary, self.schema)
        r.validate_summary_internal_consistency(summary)

    def test_clue_and_tradeable_summary_is_valid_and_consistent(self) -> None:
        summary = make_valid_summary(clues=("low_beta", "book_to_circ_mv"), tradeables=("low_beta",))
        jsonschema.validate(summary, self.schema)
        r.validate_summary_internal_consistency(summary)

    def test_runner_summary_schema_path_matches(self) -> None:
        self.assertTrue(r.SUMMARY_SCHEMA_PATH.exists())
        self.assertEqual(self.schema["properties"]["schema_name"]["const"], "a_long_large_cap_batch_factor_search_signal_search_execution_summary")
        self.assertEqual(len(self.schema["properties"]["result_cells"]["allOf"]), r.M_TOTAL_HYPOTHESES)
        self.assertEqual(self.schema["properties"]["result_cells"]["minItems"], r.RESULT_CELL_COUNT)


class BatchSummarySchemaAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = load_schema()

    def _assert_schema_rejects(self, summary: dict) -> None:
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(summary, self.schema)

    def _assert_consistency_rejects(self, summary: dict) -> None:
        with self.assertRaises(ValueError):
            r.validate_summary_internal_consistency(summary)

    def test_cell_metadata_inconsistent_with_cell_id_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        # Flip a primary cell's benchmark without changing its cell_id -> if/then pin must fire.
        for cell in summary["result_cells"]:
            if cell["cell_id"] == r.PRIMARY_CELL_IDS["book_to_circ_mv"]:
                cell["benchmark"] = "CSI1000"
                break
        self._assert_schema_rejects(summary)

    def test_primary_role_demoted_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        for cell in summary["result_cells"]:
            if cell["cell_id"] == r.PRIMARY_CELL_IDS["low_beta"]:
                cell["diagnostic_role"] = "diagnostic_only"
                break
        self._assert_schema_rejects(summary)

    def test_wrong_result_cell_count_const_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        summary["execution_diagnostics"]["result_cell_count"] = 47
        self._assert_schema_rejects(summary)

    def test_dropped_cell_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        summary["result_cells"] = summary["result_cells"][:-1]
        self._assert_schema_rejects(summary)

    def test_factor_family_drift_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        for item in summary["factor_results"]:
            if item["factor_id"] == "low_beta":
                item["family"] = "value"
                break
        self._assert_schema_rejects(summary)

    def test_q_threshold_drift_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        summary["decision"]["q_research_clue_gate"] = 0.2
        self._assert_schema_rejects(summary)

    def test_production_claim_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        summary["decision"]["alpha_found_for_production"] = True
        self._assert_schema_rejects(summary)

    def test_clue_flag_without_fdr_survival_rejected_by_consistency(self) -> None:
        summary = make_valid_summary()
        for item in summary["factor_results"]:
            if item["factor_id"] == "roa_ttm":
                item["is_statistical_alpha_clue"] = True  # but survives_fdr / gates remain False
                break
        # schema allows free booleans; the consistency guard must catch the contradiction.
        self._assert_consistency_rejects(summary)

    def test_tradeable_without_clue_rejected_by_consistency(self) -> None:
        summary = make_valid_summary()
        for item in summary["factor_results"]:
            if item["factor_id"] == "roa_ttm":
                item["is_tradeable_candidate"] = True
                item["relative_nav_drawdown_gate_passed"] = True
                break
        self._assert_consistency_rejects(summary)

    def test_clue_count_mismatch_rejected_by_consistency(self) -> None:
        summary = make_valid_summary(clues=("low_beta",), tradeables=())
        summary["decision"]["statistical_alpha_clue_count"] = 0
        self._assert_consistency_rejects(summary)

    def test_dry_verdict_with_clue_rejected_by_consistency(self) -> None:
        summary = make_valid_summary(clues=("low_beta",), tradeables=())
        summary["decision"]["research_verdict"] = r.DRY_VERDICT
        summary["decision"]["is_dry_batch"] = True
        self._assert_consistency_rejects(summary)

    def test_dropped_size_coverage_row_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        summary["size_coverage_audit"]["by_factor"] = summary["size_coverage_audit"]["by_factor"][:-1]
        self._assert_schema_rejects(summary)

    def test_size_coverage_count_mismatch_rejected_by_consistency(self) -> None:
        summary = make_valid_summary()
        row = summary["size_coverage_audit"]["by_factor"][0]
        row["incomplete_size_coverage_month_count"] = 3  # list stays empty -> mismatch
        self._assert_consistency_rejects(summary)

    def test_factor_input_coverage_missing_factor_rejected_by_schema(self) -> None:
        summary = make_valid_summary()
        summary["factor_input_coverage"]["by_factor"] = summary["factor_input_coverage"]["by_factor"][:-1]
        self._assert_schema_rejects(summary)

    def test_fdr_audit_survival_disagreement_rejected_by_consistency(self) -> None:
        summary = make_valid_summary(clues=("low_beta",), tradeables=())
        # factor_results says low_beta survives q0.10; flip the fdr_audit row to disagree.
        for row in summary["fdr_audit"]["sorted_primary_p_values"]:
            if row["factor_id"] == "low_beta":
                row["survives_fdr_q_research_clue"] = False
                break
        self._assert_consistency_rejects(summary)

    def test_fdr_audit_duplicate_rank_rejected_by_consistency(self) -> None:
        summary = make_valid_summary()
        summary["fdr_audit"]["sorted_primary_p_values"][1]["rank"] = 1
        self._assert_consistency_rejects(summary)

    def test_cell_id_metadata_mismatch_rejected_by_consistency(self) -> None:
        # Build a cell whose cell_id is internally inconsistent but is NOT one of the 48 frozen ids,
        # so the schema enum fires first; instead mutate metadata of a diagnostic cell in a way the
        # cell_id enum still accepts but cell_id_for disagrees -> consistency guard catches it.
        summary = make_valid_summary()
        # Pick a non-primary cell and corrupt its view while keeping a valid-enum cell_id.
        target = next(c for c in summary["result_cells"] if c["diagnostic_role"] == "diagnostic_only")
        # Force cell_id/metadata disagreement by overwriting cell_id with another frozen id.
        other = next(c["cell_id"] for c in summary["result_cells"] if c["cell_id"] != target["cell_id"])
        target["cell_id"] = other
        self._assert_consistency_rejects(summary)


if __name__ == "__main__":
    unittest.main()
