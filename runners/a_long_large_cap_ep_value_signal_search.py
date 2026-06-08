from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_long_full_main_board_signal_search as base
from runners import a_long_large_cap_market_cap_audit as cap_audit


SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_ep_value_signal_search_execution_summary.schema.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_large_cap_ep_value_20260608.json"
PREREGISTRATION_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_ep_value_preregistration.schema.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_large_cap_ep_value_program_test_budget_ledger_20260608.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "program_test_budget_ledger.schema.json"
MARKET_CAP_AUDIT_REPORT_PATH = (
    ROOT / "research" / "results" / "a_long_large_cap_market_cap_audit_20260607" / "audit_report.json"
)
OUTPUT_DIR = ROOT / "research" / "results" / "a_long_large_cap_ep_value_20260608"
SUMMARY_PATH = OUTPUT_DIR / "execution_summary.json"

SUMMARY_ARTIFACT_ID = "a_long_large_cap_ep_value_signal_search_execution_summary_20260608"
PLANNED_TEST_ID = "a_long_large_cap_ep_value_20260608"
PREREGISTRATION_ARTIFACT_ID = "a_long_large_cap_ep_value_20260608"
LEDGER_FAMILY_ID = "a_long_large_cap_ep_value_v1"

# The single primary factor under test (fundamental value) plus the frozen diagnostic-only factors.
PRIMARY_SIGNAL_ID = "ep_value_percentile"
PRIMARY_FACTOR = "ep_value"
DIAGNOSTIC_FACTORS = ["book_to_market", "cash_flow_to_price"]
ALL_FACTORS = [PRIMARY_FACTOR] + DIAGNOSTIC_FACTORS
PRIMARY_VIEW = "industry_size_neutral"
EP_VALUE_VIEWS = ["industry_size_neutral", "non_neutral", "industry_neutral", "size_neutral"]
PRIMARY_HORIZON = 504
DIAGNOSTIC_HORIZON = 252
HORIZONS = [DIAGNOSTIC_HORIZON, PRIMARY_HORIZON]
PRIMARY_BENCHMARK = "CSI300"
SECONDARY_BENCHMARK = "CSI1000"
BENCHMARKS = base.BENCHMARKS

# Frozen EP construction. EP = trailing-twelve-month net income attributable to parent / PIT circ_mv.
# Only the cross-sectional percentile is used, so the circ_mv unit scale (and the net-income vs
# circ_mv unit mismatch) is immaterial to the ranking. Non-positive TTM earnings are excluded.
PRIMARY_FACTOR_DEFINITION = "trailing_twelve_month_net_income_attr_parent_div_pit_circ_mv_as_of_each_as_of_date"
EARNINGS_BASIS = "trailing_twelve_month_net_income_attr_parent_from_pit_income_ytd_rollover"
TTM_ROLLOVER_RULE = "latest_pit_ytd_plus_prior_fiscal_year_annual_minus_prior_year_same_period_ytd_all_pit_and_restatement_excluded"
DENOMINATOR_FIELD = "pit_circ_mv_at_as_of"
TTM_ROLLOVER_PERIOD_LIMIT = 12

TOP_FRACTION = 0.2
MIN_TOP_COUNT = 10
MIN_MONTHLY_COHORTS = 48
MAX_TOP_SYMBOL_SELECTION_SHARE = 0.2
MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE = 0.35
MIN_HAC_T_STAT = 2.0
MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN = -0.15
MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY = 50
UNIVERSE_SIZE_N = 500
MONTHLY_AS_OF_DATES = cap_audit.MONTHLY_AS_OF_DATES
SELECTED_MARKET_CAP_FIELD = "circ_mv"
EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT = base.EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT
SIZE_BUCKETS = [f"q{index}" for index in range(1, 6)]

PRIMARY_CELL_ID = "primary_ep_value_industry_size_neutral_504d_csi300"
FALSIFIED_VERDICT = "falsified_large_cap_ep_value_under_frozen_rules"
STATISTICAL_ALPHA_CLUE_VERDICT = "statistical_alpha_clue_research_only"


@dataclass(frozen=True)
class LargeCapMember:
    symbol: str
    market_cap: float
    raw_rank: int
    size_bucket: str
    backfilled_after_documented_exclusion: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reviewed A-long large-cap ep_value single-factor signal search from local raw data. "
            "ep_value is trailing-twelve-month net income attributable to parent over PIT circ_mv (the China "
            "value factor); it reads the already-materialized full-main-board PIT income fundamentals + the "
            "reviewed restatement exclusion list + the top-500 circ_mv universe, executes no provider call, and "
            "spends the ep_value singleton ledger after a valid summary write."
        )
    )
    parser.add_argument("--full-raw-root", type=Path, default=base.RAW_ROOT)
    parser.add_argument("--market-cap-raw-root", type=Path, default=cap_audit.MARKET_CAP_RAW_ROOT)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--confirm-independent-review-pass", action="store_true")
    parser.add_argument("--confirm-post-review-execute", action="store_true")
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Any) -> None:
    base.write_json_atomic(path, payload)


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    base.validate_json(schema_path, payload)


def display_path(path: Path) -> str:
    return base.display_path(path)


def require_execution_confirmations(*, confirm_independent_review_pass: bool, confirm_post_review_execute: bool) -> None:
    if not confirm_independent_review_pass:
        raise RuntimeError("ep_value signal search requires --confirm-independent-review-pass")
    if not confirm_post_review_execute:
        raise RuntimeError("ep_value signal search requires --confirm-post-review-execute")


def load_and_validate_preregistration(path: Path = PREREGISTRATION_PATH) -> dict[str, Any]:
    prereg = read_json(path)
    validate_json(PREREGISTRATION_SCHEMA_PATH, prereg)
    if prereg.get("schema_name") != "a_long_large_cap_ep_value_preregistration":
        raise ValueError("ep_value preregistration schema_name mismatch")
    if prereg.get("artifact_id") != PREREGISTRATION_ARTIFACT_ID:
        raise ValueError("ep_value preregistration artifact_id mismatch")

    scope = prereg.get("scope") or {}
    if scope.get("preregistration_review_status") != "passed_independent_review_ready_for_freeze":
        raise ValueError("ep_value preregistration is not review-passed")
    for field in [
        "research_only",
        "externally_motivated_not_prior_rescue",
        "new_hypothesis_not_prior_reslice",
        "reuses_reviewed_materialized_market_cap_universe",
        "reuses_reviewed_full_main_board_fundamentals",
        "manual_order_only",
    ]:
        if scope.get(field) is not True:
            raise ValueError(f"ep_value preregistration scope.{field} must be true")
    for field in [
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
        if scope.get(field) is not False:
            raise ValueError(f"ep_value preregistration scope.{field} must be false")

    provenance = prereg.get("hypothesis_provenance") or {}
    if provenance.get("externally_literature_motivated") is not True:
        raise ValueError("ep_value provenance must remain externally literature motivated")
    if provenance.get("derived_from_in_sample_diagnostic_of_prior_run") is not False:
        raise ValueError("ep_value must not be an in-sample diagnostic of a prior run")
    if provenance.get("not_covered_by_prior_full_main_board_signal_families") is not True:
        raise ValueError("ep_value not-covered-by-prior-families flag drifted")
    if provenance.get("no_factor_definition_search") is not True:
        raise ValueError("ep_value factor-definition search must remain forbidden")
    if provenance.get("no_earnings_basis_search") is not True:
        raise ValueError("ep_value earnings-basis search must remain forbidden")
    if provenance.get("no_denominator_field_search") is not True:
        raise ValueError("ep_value denominator-field search must remain forbidden")

    data_reuse = prereg.get("data_reuse") or {}
    if data_reuse.get("no_new_provider_call_required") is not True:
        raise ValueError("ep_value data reuse no-provider-call flag drifted")
    if data_reuse.get("ep_numerator_source") != "full_main_board_raw_root_pit_income_n_income_attr_p_ytd_rows":
        raise ValueError("ep_value numerator source drifted")
    if data_reuse.get("ep_denominator_source") != "reviewed_materialized_pit_circ_mv_at_as_of":
        raise ValueError("ep_value denominator source drifted")
    if data_reuse.get("selected_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("ep_value data reuse market-cap field drifted")
    if data_reuse.get("monthly_as_of_count") != len(MONTHLY_AS_OF_DATES):
        raise ValueError("ep_value data reuse as-of count drifted")

    design = prereg.get("frozen_design") or {}
    if design.get("design_id") != LEDGER_FAMILY_ID:
        raise ValueError("ep_value design id drifted")

    universe = design.get("universe_rule") or {}
    if universe.get("board_scope") != "main_board_only":
        raise ValueError("ep_value board scope drifted")
    if universe.get("as_of_selection_rule") != "last_open_A_share_trading_day_of_each_calendar_month":
        raise ValueError("ep_value as-of selection rule drifted")
    if universe.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("ep_value universe size drifted")
    if universe.get("universe_size_n_search_allowed") is not False:
        raise ValueError("ep_value universe size search must remain forbidden")
    if universe.get("selection_basis") != "top_500_by_pit_market_cap_as_of_each_as_of_date":
        raise ValueError("ep_value universe selection basis drifted")
    if universe.get("include_later_delisted_names_at_pre_delisting_asofs") is not True:
        raise ValueError("ep_value PIT delisted-name inclusion drifted")
    if universe.get("pit_list_delist_required") is not True:
        raise ValueError("ep_value PIT list/delist requirement drifted")
    if universe.get("selection_time_namechange_veto_required") is not True:
        raise ValueError("ep_value PIT namechange veto requirement drifted")
    if universe.get("reviewed_data_quality_exclusion_boundary_ref") != cap_audit.DATA_QUALITY_EXCLUSION_DECISION_REF:
        raise ValueError("ep_value data-quality exclusion ref drifted")
    exclusion_policy = universe.get("reviewed_data_quality_exclusion_policy") or {}
    if exclusion_policy.get("excluded_symbols") != sorted(cap_audit.EXPECTED_REVIEWED_EXCLUSION_SYMBOLS):
        raise ValueError("ep_value data-quality exclusion symbol drifted")
    if exclusion_policy.get("affected_as_of_dates") != ["20191129"]:
        raise ValueError("ep_value data-quality exclusion date drifted")
    if exclusion_policy.get("drop_excluded_symbols_before_signal_scoring") is not True:
        raise ValueError("ep_value signal universe must drop reviewed exclusions")
    if exclusion_policy.get("backfill_next_main_board_by_circ_mv") is not True:
        raise ValueError("ep_value signal universe must backfill by circ_mv")
    if exclusion_policy.get("materialized_top500_rederivation_unchanged") is not True:
        raise ValueError("ep_value materialized top500 rederivation boundary drifted")
    if exclusion_policy.get("threshold_rescue_allowed") is not False:
        raise ValueError("ep_value threshold rescue must remain forbidden")
    if universe.get("st_star_bse_chinext_excluded") is not True:
        raise ValueError("ep_value board/status exclusion boundary drifted")

    signal = design.get("signal_rule") or {}
    if signal.get("primary_signal_id") != PRIMARY_SIGNAL_ID:
        raise ValueError("ep_value primary signal drifted")
    if signal.get("primary_signal_type") != "single_factor_percentile":
        raise ValueError("ep_value primary signal type drifted")
    if signal.get("primary_factor") != PRIMARY_FACTOR:
        raise ValueError("ep_value primary factor drifted")
    if signal.get("primary_factor_definition") != PRIMARY_FACTOR_DEFINITION:
        raise ValueError("ep_value primary factor definition drifted")
    if signal.get("earnings_basis") != EARNINGS_BASIS:
        raise ValueError("ep_value earnings basis drifted")
    if signal.get("ttm_rollover_rule") != TTM_ROLLOVER_RULE:
        raise ValueError("ep_value TTM rollover rule drifted")
    if signal.get("earnings_basis_search_allowed") is not False:
        raise ValueError("ep_value earnings-basis search must remain forbidden")
    if signal.get("denominator_field") != DENOMINATOR_FIELD:
        raise ValueError("ep_value denominator field drifted")
    if signal.get("denominator_field_search_allowed") is not False:
        raise ValueError("ep_value denominator-field search must remain forbidden")
    if signal.get("non_positive_ttm_earnings_excluded_from_scoring") is not True:
        raise ValueError("ep_value non-positive-earnings exclusion drifted")
    if signal.get("high_ep_is_high_score_direction") is not True:
        raise ValueError("ep_value high-score direction drifted")
    if signal.get("factor_definition_change_allowed") is not False:
        raise ValueError("ep_value factor-definition-change must remain forbidden")
    if signal.get("percentile_rank_required") is not True:
        raise ValueError("ep_value percentile-rank requirement drifted")
    if signal.get("zscore_allowed") is not False:
        raise ValueError("ep_value z-score must remain forbidden")
    if signal.get("multi_factor_composite_allowed") is not False:
        raise ValueError("ep_value multi-factor composite must remain forbidden")
    if signal.get("single_factor_winner_take_all_from_prior_result_allowed") is not False:
        raise ValueError("ep_value winner-take-all must remain forbidden")
    if signal.get("insufficient_ttm_earnings_months_excluded_from_cohorts") is not True:
        raise ValueError("ep_value startup TTM-coverage exclusion drifted")
    if signal.get("diagnostic_factors") != DIAGNOSTIC_FACTORS:
        raise ValueError("ep_value diagnostic factors drifted")
    if signal.get("diagnostic_factor_can_rescue_primary_failure") is not False:
        raise ValueError("ep_value diagnostic rescue must remain forbidden")

    neutral = design.get("neutralization_rule") or {}
    if neutral.get("primary_view") != "industry_and_size_neutral":
        raise ValueError("ep_value preregistered primary view drifted")
    if neutral.get("neutralization_method") != "marginal_double_neutralization":
        raise ValueError("ep_value neutralization method drifted")
    if neutral.get("primary_score_construction") != "equal_weight_average_of_marginal_industry_neutral_and_marginal_size_neutral_percentile_scores":
        raise ValueError("ep_value primary score construction drifted")
    if neutral.get("industry_neutral_score_rule") != "percentile_within_industry_l2_fallback_l1":
        raise ValueError("ep_value industry-neutral score rule drifted")
    if neutral.get("size_neutral_score_rule") != "percentile_within_market_cap_quintile":
        raise ValueError("ep_value size-neutral score rule drifted")
    if neutral.get("combined_score_rule") != "0_5_industry_neutral_percentile_plus_0_5_size_neutral_percentile":
        raise ValueError("ep_value combined score rule drifted")
    if neutral.get("crossed_industry_size_bucket_allowed") is not False:
        raise ValueError("ep_value crossed industry-size buckets must remain forbidden")
    if neutral.get("industry_basis") != "SW_L2_then_SW_L1_if_sample_lt_20":
        raise ValueError("ep_value industry basis drifted")
    if neutral.get("industry_l2_min_count") != 20:
        raise ValueError("ep_value industry L2 minimum drifted")
    if neutral.get("industry_l1_min_count") != 2:
        raise ValueError("ep_value industry L1 fallback minimum drifted")
    if neutral.get("size_bucket_rule") != "pit_market_cap_quintile_inside_top_500_per_as_of":
        raise ValueError("ep_value size bucket rule drifted")
    if neutral.get("size_bucket_count") != len(SIZE_BUCKETS):
        raise ValueError("ep_value size bucket count drifted")
    if neutral.get("expected_names_per_size_bucket") != UNIVERSE_SIZE_N // len(SIZE_BUCKETS):
        raise ValueError("ep_value expected size bucket count drifted")
    if neutral.get("minimum_size_bucket_count_for_primary_percentile") != MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY:
        raise ValueError("ep_value size bucket minimum drifted")
    if neutral.get("non_neutral_view_role") != "diagnostic_only_not_primary":
        raise ValueError("ep_value non-neutral diagnostic role drifted")
    if neutral.get("cap_weighted_view_role") != "diagnostic_only_not_primary":
        raise ValueError("ep_value cap-weighted diagnostic role drifted")

    measurement = design.get("measurement_rule") or {}
    if measurement.get("primary_horizon_trading_days") != PRIMARY_HORIZON:
        raise ValueError("ep_value primary horizon drifted")
    if measurement.get("diagnostic_horizons_trading_days") != [DIAGNOSTIC_HORIZON]:
        raise ValueError("ep_value diagnostic horizon drifted")
    if measurement.get("entry_rule") != "next_trading_day_close_after_as_of":
        raise ValueError("ep_value entry rule drifted")
    if measurement.get("round_trip_cost") != base.ROUND_TRIP_COST:
        raise ValueError("ep_value round-trip cost drifted")
    if measurement.get("stock_return_basis") != base.STOCK_RETURN_BASIS:
        raise ValueError("ep_value stock return basis drifted")
    if measurement.get("benchmark_return_basis") != base.BENCHMARK_RETURN_BASIS:
        raise ValueError("ep_value benchmark return basis drifted")
    if measurement.get("same_anchor_required") is not True:
        raise ValueError("ep_value same-anchor requirement drifted")
    if measurement.get("missing_scheduled_exit_policy") != base.MISSING_SCHEDULED_EXIT_POLICY:
        raise ValueError("ep_value missing scheduled exit policy drifted")
    if measurement.get("total_return_required") is not True:
        raise ValueError("ep_value total-return requirement drifted")
    if measurement.get("price_index_fallback_allowed") is not False:
        raise ValueError("ep_value price-index fallback must remain forbidden")

    benchmark = design.get("benchmark_rule") or {}
    if benchmark.get("primary_benchmark") != PRIMARY_BENCHMARK:
        raise ValueError("ep_value primary benchmark drifted")
    if benchmark.get("diagnostic_benchmark") != SECONDARY_BENCHMARK:
        raise ValueError("ep_value diagnostic benchmark drifted")
    if benchmark.get("both_benchmark_pass_required") is not False:
        raise ValueError("ep_value CSI1000 must remain diagnostic")
    if benchmark.get("benchmark_access_probe_ref") != display_path(base.BENCHMARK_ACCESS_PROBE_SUMMARY_PATH):
        raise ValueError("ep_value benchmark access probe ref drifted")
    if benchmark.get("benchmark_access_status") != base.BENCHMARK_ACCESS_STATUS:
        raise ValueError("ep_value benchmark access status drifted")
    if benchmark.get("derived_total_return_open_allowed") is not False:
        raise ValueError("ep_value derived total-return open must remain forbidden")

    cell = design.get("decision_cell") or {}
    if cell.get("cell_id") != PRIMARY_CELL_ID:
        raise ValueError("ep_value primary cell id drifted")
    if cell.get("signal") != PRIMARY_SIGNAL_ID:
        raise ValueError("ep_value primary cell signal drifted")
    if cell.get("view") != "industry_and_size_neutral":
        raise ValueError("ep_value primary cell view drifted")
    if cell.get("horizon_trading_days") != PRIMARY_HORIZON:
        raise ValueError("ep_value primary cell horizon drifted")
    if cell.get("benchmark") != PRIMARY_BENCHMARK:
        raise ValueError("ep_value primary cell benchmark drifted")
    if cell.get("top_fraction") != TOP_FRACTION:
        raise ValueError("ep_value top fraction drifted")
    if cell.get("minimum_top_count_per_month") != MIN_TOP_COUNT:
        raise ValueError("ep_value minimum top count drifted")
    if cell.get("decision_is_two_tier") is not True:
        raise ValueError("ep_value two-tier decision drifted")
    clue_gates = cell.get("statistical_alpha_clue_gates") or {}
    if clue_gates.get("mean_net_excess_must_be_positive") is not True:
        raise ValueError("ep_value mean excess positivity gate drifted")
    if clue_gates.get("minimum_hac_t_stat") != MIN_HAC_T_STAT:
        raise ValueError("ep_value HAC threshold drifted")
    if clue_gates.get("minimum_monthly_cohorts") != MIN_MONTHLY_COHORTS:
        raise ValueError("ep_value minimum cohort count drifted")
    if clue_gates.get("name_concentration_guard_max_share") != MAX_TOP_SYMBOL_SELECTION_SHARE:
        raise ValueError("ep_value name concentration guard drifted")
    if clue_gates.get("single_year_positive_return_guard_max_share") != MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE:
        raise ValueError("ep_value single-year concentration guard drifted")
    if clue_gates.get("sub_period_both_halves_mean_excess_positive_required") is not True:
        raise ValueError("ep_value sub-period both-halves gate drifted")
    tradeable_gates = cell.get("tradeable_candidate_gates") or {}
    if tradeable_gates.get("risk_gate_metric") != "rolling_overlapping_portfolio_relative_nav_max_drawdown_vs_csi300":
        raise ValueError("ep_value tradeable risk-gate metric drifted")
    if tradeable_gates.get("minimum_allowed_relative_nav_drawdown") != MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN:
        raise ValueError("ep_value relative-NAV drawdown threshold drifted")
    if tradeable_gates.get("absolute_nav_drawdown_is_diagnostic_only") is not True:
        raise ValueError("ep_value absolute-NAV drawdown diagnostic role drifted")
    if tradeable_gates.get("risk_gate_affects_tradeable_label_only_not_alpha_clue") is not True:
        raise ValueError("ep_value risk-gate scope (tradeable label only) drifted")

    sub_period = design.get("sub_period_robustness") or {}
    if sub_period.get("split_rule") != "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves":
        raise ValueError("ep_value sub-period split rule drifted")
    if sub_period.get("natural_calendar_year_split_allowed") is not False:
        raise ValueError("ep_value calendar-year split must remain forbidden")
    if sub_period.get("requires_both_halves_mean_excess_positive") is not True:
        raise ValueError("ep_value sub-period both-halves requirement drifted")
    if sub_period.get("report_each_half_hac_t_stat") is not True:
        raise ValueError("ep_value sub-period per-half HAC reporting drifted")

    risk_gate = design.get("risk_gate") or {}
    if risk_gate.get("method") != "rolling_overlapping_monthly_tranche_portfolio_nav":
        raise ValueError("ep_value risk-gate method drifted")
    if risk_gate.get("benchmark_construction") != "option_a_parallel_same_as_of_schedule_horizon_and_ramp_holding_csi300_total_return_instead_of_selected_basket":
        raise ValueError("ep_value risk-gate benchmark construction drifted")
    if risk_gate.get("cost_applied_to_benchmark_tranches") is not False:
        raise ValueError("ep_value risk-gate benchmark cost flag drifted")
    if risk_gate.get("relative_nav_formula") != "strategy_nav_divided_by_benchmark_nav":
        raise ValueError("ep_value relative-NAV formula drifted")
    if risk_gate.get("primary_risk_metric") != "max_drawdown_of_relative_nav":
        raise ValueError("ep_value primary risk metric drifted")
    if risk_gate.get("minimum_allowed_relative_nav_drawdown") != MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN:
        raise ValueError("ep_value risk-gate drawdown threshold drifted")
    if risk_gate.get("threshold_frozen_before_run") is not True:
        raise ValueError("ep_value risk-gate frozen-threshold flag drifted")
    if risk_gate.get("summed_overlapping_cohort_excess_drawdown_as_gate_allowed") is not False:
        raise ValueError("ep_value summed-excess drawdown gate must remain forbidden")
    if risk_gate.get("risk_gate_affects_tradeable_label_only_not_alpha_clue") is not True:
        raise ValueError("ep_value risk-gate scope (tradeable label only) drifted")

    diagnostics = design.get("diagnostic_cells") or {}
    for field in [
        "report_csi1000",
        "report_252d",
        "report_single_factor_diagnostics",
        "report_non_neutral",
        "report_cap_weighted",
        "report_absolute_nav_drawdown",
        "report_each_sub_period_half",
        "report_ep_vs_book_to_market_comparison",
    ]:
        if diagnostics.get(field) is not True:
            raise ValueError(f"ep_value diagnostic reporting gate drifted: {field}")
    if diagnostics.get("diagnostics_can_define_alpha") is not False:
        raise ValueError("ep_value diagnostics must not define alpha")

    anti = design.get("anti_p_hacking_controls") or {}
    if anti.get("test_budget_units") != 1:
        raise ValueError("ep_value test budget units drifted")
    for field in [
        "parameter_sweep_allowed",
        "universe_n_search_allowed",
        "factor_definition_search_allowed",
        "earnings_basis_search_allowed",
        "denominator_field_search_allowed",
        "multi_factor_composite_search_allowed",
        "post_result_rescue_slicing_allowed",
    ]:
        if anti.get(field) is not False:
            raise ValueError(f"ep_value anti-p-hacking control drifted: {field}")
    if anti.get("risk_gate_threshold_frozen_before_run") is not True:
        raise ValueError("ep_value frozen-risk-gate control drifted")
    if anti.get("new_ledger_required_before_any_followup") is not True:
        raise ValueError("ep_value new-ledger follow-up rule drifted")

    hygiene = design.get("pit_and_hygiene_controls") or {}
    if hygiene.get("restatement_exclusion_list_ref") != display_path(base.RESTATEMENT_EXCLUSION_LIST_PATH):
        raise ValueError("ep_value restatement exclusion list ref drifted")
    if hygiene.get("restatement_exclusion_required") is not True:
        raise ValueError("ep_value restatement exclusion requirement drifted")
    if hygiene.get("expected_restatement_exclusion_group_count") != EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT:
        raise ValueError("ep_value restatement exclusion group count drifted")
    if hygiene.get("pit_earnings_uses_only_ann_date_leq_as_of") is not True:
        raise ValueError("ep_value PIT-earnings requirement drifted")
    if hygiene.get("non_positive_ttm_earnings_excluded_from_scoring") is not True:
        raise ValueError("ep_value non-positive-earnings hygiene flag drifted")
    if hygiene.get("pit_namechange_required") is not True:
        raise ValueError("ep_value PIT namechange requirement drifted")
    if hygiene.get("current_stock_basic_name_veto_allowed") is not False:
        raise ValueError("ep_value current stock_basic name veto must remain forbidden")
    for field in [
        "tracked_summary_contains_raw_rows_allowed",
        "tracked_summary_contains_endpoint_results_allowed",
        "tracked_summary_contains_secret_allowed",
        "tracked_summary_contains_request_url_allowed",
    ]:
        if hygiene.get(field) is not False:
            raise ValueError(f"ep_value tracked summary hygiene drifted: {field}")

    planned = prereg.get("planned_test_budget") or {}
    if planned.get("test_budget_units") != 1:
        raise ValueError("ep_value planned test budget drifted")
    if planned.get("required_preregistration_review_status_for_execution") != "passed_independent_review_ready_for_freeze":
        raise ValueError("ep_value required execution review status drifted")
    return prereg


def load_and_validate_ledger(path: Path = LEDGER_PATH) -> dict[str, Any]:
    ledger = read_json(path)
    # Schema-validate the executable ledger before any bespoke field check or spend.
    validate_json(LEDGER_SCHEMA_PATH, ledger)
    if ledger.get("schema_name") != "program_test_budget_ledger":
        raise ValueError("program-test ledger schema_name mismatch")
    if ledger.get("family_id") != LEDGER_FAMILY_ID:
        raise ValueError("ep_value ledger family drifted")
    if ledger.get("ledger_status") != "active_planned_test_pending_review":
        raise ValueError("ep_value ledger is not in the active pre-execution state")
    policy = ledger.get("budget_policy") or {}
    if policy.get("tests_spent_count") != 0:
        raise ValueError("ep_value singleton signal-search test was already spent")
    if policy.get("tests_available_without_new_review") != 0:
        raise ValueError("ep_value ledger must not allow unreviewed tests")
    if policy.get("next_test_requires_reviewed_preregistration") is not True:
        raise ValueError("ep_value ledger must require reviewed preregistration")
    if policy.get("next_test_requires_user_approval") is not True:
        raise ValueError("ep_value ledger must require user approval")
    planned = ledger.get("planned_tests") or []
    if len(planned) != 1 or planned[0].get("test_id") != PLANNED_TEST_ID:
        raise ValueError("ep_value planned test mismatch")
    if planned[0].get("planned_status") != "planned_not_reviewed":
        raise ValueError("ep_value planned test status drifted")
    # Prove this exact singleton maps to this preregistration and this result, spends exactly one
    # test, and is the user-approved planned test.
    if planned[0].get("planned_preregistration_ref") != display_path(PREREGISTRATION_PATH):
        raise ValueError("ep_value ledger planned preregistration ref drifted")
    if planned[0].get("planned_result_ref") != display_path(SUMMARY_PATH):
        raise ValueError("ep_value ledger planned result ref drifted")
    if planned[0].get("expected_tests_spent") != 1:
        raise ValueError("ep_value ledger expected_tests_spent must be exactly 1")
    if planned[0].get("approval_status") != "user_approved_pending_review":
        raise ValueError("ep_value ledger planned test approval status drifted")
    if ledger.get("test_spend_log") != []:
        raise ValueError("ep_value ledger spend log must be empty before execution")
    return ledger


def load_and_validate_market_cap_audit_report(path: Path = MARKET_CAP_AUDIT_REPORT_PATH) -> dict[str, Any]:
    report = read_json(path)
    validate_json(cap_audit.REPORT_SCHEMA_PATH, report)
    if report.get("schema_name") != "a_long_large_cap_market_cap_audit_report":
        raise ValueError("ep_value market-cap audit report schema_name mismatch")
    decision = report.get("decision") or {}
    if decision.get("audit_status") != "passed_large_cap_market_cap_audit_for_signal_package":
        raise ValueError("ep_value market-cap audit must pass before execution")
    if decision.get("hard_checks_pass") is not True:
        raise ValueError("ep_value market-cap audit hard checks must pass")
    if decision.get("signal_search_authorized_by_this_report") is not False:
        raise ValueError("ep_value market-cap audit must not self-authorize signal search")
    if decision.get("alpha_found") is not False:
        raise ValueError("ep_value market-cap audit must not claim alpha")
    boundary = report.get("audit_boundary") or {}
    if boundary.get("monthly_as_of_dates") != MONTHLY_AS_OF_DATES:
        raise ValueError("ep_value market-cap audit as-of dates drifted")
    if boundary.get("selected_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("ep_value market-cap audit selected field drifted")
    if boundary.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("ep_value market-cap audit universe size drifted")
    checks = {item.get("check_id"): item for item in report.get("check_results", [])}
    bridge = checks.get("prior_full_main_board_universe_bridge") or {}
    metrics = bridge.get("metrics") or {}
    if metrics.get("total_unresolved_outside_prior_audited_universe_observations") != 0:
        raise ValueError("ep_value market-cap audit still has unresolved bridge gaps")
    if metrics.get("documented_data_quality_exclusion_observations") != 1:
        raise ValueError("ep_value market-cap audit documented exclusion count drifted")
    if metrics.get("signal_universe_backfill_observations") != 1:
        raise ValueError("ep_value market-cap audit backfill count drifted")
    return report


def load_full_main_board_sources(
    full_raw_root: Path,
) -> tuple[dict[str, Any], base.audit.PayloadStore, base.SignalContext, set[tuple[str, str, str, str]], int]:
    # ep_value is a fundamental signal: it reads PIT income (and balancesheet / cashflow for diagnostics)
    # and DOES apply the reviewed restatement-ambiguity exclusion list, like cash_conversion.
    full_audit_report = base.load_and_validate_audit_report()
    base.load_and_validate_benchmark_route_amendment()
    restatement_exclusions = base.load_restatement_exclusions()
    _summary, manifest, store = base.validate_materialization_summary_and_manifest(full_raw_root)
    repair = base.audit.validate_boundary_refs()
    context = base.build_signal_context(store, repair)
    restatement_keys_present = base.count_restatement_exclusion_keys_present(store, context, restatement_exclusions)
    if restatement_keys_present != len(restatement_exclusions):
        raise ValueError(
            "restatement exclusion list is not fully matched to the materialized raw panel: "
            f"found {restatement_keys_present}, expected {len(restatement_exclusions)}"
        )
    return full_audit_report, store, context, restatement_exclusions, len(manifest)


def load_large_cap_signal_universes(
    *,
    market_cap_raw_root: Path,
    allowed_symbols: set[str],
) -> tuple[dict[str, list[LargeCapMember]], dict[str, Any]]:
    materialization_summary = read_json(cap_audit.MATERIALIZATION_SUMMARY_PATH)
    cap_audit.validate_materialization_summary(materialization_summary)
    decision = cap_audit.load_and_validate_data_quality_exclusion_decision()
    reviewed_exclusions = cap_audit.reviewed_exclusions_by_as_of(decision)

    universes: dict[str, list[LargeCapMember]] = {}
    diagnostics = {
        "market_cap_monthly_as_of_count": len(MONTHLY_AS_OF_DATES),
        "large_cap_target_universe_size": UNIVERSE_SIZE_N,
        "large_cap_signal_universe_observations": 0,
        "documented_data_quality_exclusion_observation_count": 0,
        "backfilled_after_documented_exclusion_observation_count": 0,
        "outside_prior_audited_universe_after_backfill_observation_count": 0,
        "incomplete_large_cap_universe_month_count": 0,
        "minimum_size_bucket_count": UNIVERSE_SIZE_N // 5,
    }

    endpoint_results = materialization_summary.get("endpoint_results") or []
    if len(endpoint_results) != len(MONTHLY_AS_OF_DATES):
        raise ValueError("ep_value materialization endpoint count drifted")
    for result, as_of in zip(endpoint_results, MONTHLY_AS_OF_DATES):
        if result.get("trade_date") != as_of:
            raise ValueError("ep_value materialization as-of order drifted")
        raw_path = cap_audit.resolve_raw_ref(market_cap_raw_root, result.get("raw_payload_ref"))
        payload = read_json(raw_path)
        if payload.get("call_status") != "success":
            raise ValueError(f"ep_value market-cap raw payload did not succeed: {result.get('call_id')}")
        records = [row for row in payload.get("records", []) if isinstance(row, dict)]
        ranked = cap_audit.ranked_main_board_by_market_cap(records)
        if len(ranked) < UNIVERSE_SIZE_N:
            raise ValueError(f"ep_value ranked universe is smaller than {UNIVERSE_SIZE_N}: {as_of}")
        raw_rank = {symbol: index + 1 for index, (symbol, _value) in enumerate(ranked)}
        selected = cap_audit.signal_universe_after_exclusion_backfill(
            ranked,
            as_of=as_of,
            reviewed_exclusions=reviewed_exclusions,
        )
        if len(selected) != UNIVERSE_SIZE_N:
            diagnostics["incomplete_large_cap_universe_month_count"] += 1
        members: list[LargeCapMember] = []
        for index, (symbol, market_cap) in enumerate(selected[:UNIVERSE_SIZE_N]):
            if symbol not in allowed_symbols:
                diagnostics["outside_prior_audited_universe_after_backfill_observation_count"] += 1
            bucket = f"q{(index // 100) + 1}"
            members.append(
                LargeCapMember(
                    symbol=symbol,
                    market_cap=market_cap,
                    raw_rank=raw_rank[symbol],
                    size_bucket=bucket,
                    backfilled_after_documented_exclusion=raw_rank[symbol] > UNIVERSE_SIZE_N,
                )
            )
        diagnostics["large_cap_signal_universe_observations"] += len(members)
        diagnostics["documented_data_quality_exclusion_observation_count"] += len(reviewed_exclusions.get(as_of, set()))
        diagnostics["backfilled_after_documented_exclusion_observation_count"] += sum(
            member.backfilled_after_documented_exclusion for member in members
        )
        universes[as_of] = members

    if diagnostics["incomplete_large_cap_universe_month_count"]:
        raise ValueError("ep_value signal universe is incomplete after reviewed exclusion/backfill")
    if diagnostics["outside_prior_audited_universe_after_backfill_observation_count"]:
        raise ValueError("ep_value signal universe contains symbols outside prior audited full-main-board raw universe")
    if diagnostics["documented_data_quality_exclusion_observation_count"] != 1:
        raise ValueError("ep_value documented data-quality exclusion observation count drifted")
    if diagnostics["backfilled_after_documented_exclusion_observation_count"] != 1:
        raise ValueError("ep_value backfill observation count drifted")
    return universes, diagnostics


def pit_period_values(
    store: base.audit.PayloadStore,
    symbol: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
    table_id: str,
    field: str,
) -> dict[str, float]:
    rows = store.records(base.call_id_for(table_id, symbol))
    recent = base.select_recent_pit_rows(
        rows,
        table_id=table_id,
        as_of=as_of,
        restatement_exclusions=restatement_exclusions,
        limit=TTM_ROLLOVER_PERIOD_LIMIT,
    )
    out: dict[str, float] = {}
    for row in recent:
        end_date = base.normalize_yyyymmdd(row.get("end_date"))
        value = base.numeric(row.get(field))
        if end_date and value is not None:
            out[end_date] = value
    return out


def ttm_rollover(period_values: dict[str, float]) -> float | None:
    """Trailing-twelve-month value from PIT YTD rows: latest YTD + prior fiscal-year annual
    - prior-year same-period YTD. If the latest period is annual (1231) the YTD is already TTM.
    Returns None when the rollover rows are not all present."""
    if not period_values:
        return None
    latest_end = max(period_values)
    suffix = latest_end[4:]
    year = int(latest_end[:4])
    latest = period_values[latest_end]
    if suffix == "1231":
        return latest
    prior_fiscal_year_annual = period_values.get(f"{year - 1}1231")
    prior_year_same_period = period_values.get(f"{year - 1}{suffix}")
    if prior_fiscal_year_annual is None or prior_year_same_period is None:
        return None
    return latest + prior_fiscal_year_annual - prior_year_same_period


def latest_pit_stock_value(
    store: base.audit.PayloadStore,
    symbol: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
    table_id: str,
    field: str,
) -> float | None:
    row = base.select_latest_pit_row(
        store.records(base.call_id_for(table_id, symbol)),
        table_id=table_id,
        as_of=as_of,
        restatement_exclusions=restatement_exclusions,
    )
    return base.numeric(row.get(field)) if row else None


def ep_signal_values(
    *,
    store: base.audit.PayloadStore,
    symbol: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
    circ_mv: float | None,
) -> tuple[dict[str, float], str]:
    """Compute the frozen ep_value primary factor and the two diagnostic factors from PIT fundamentals
    over the reused circ_mv denominator. Only the cross-sectional percentile of each factor is used, so
    the constant circ_mv unit scale does not affect the ranking. Returns (values, ep_status) where
    ep_status is scored / non_positive_earnings / insufficient_ttm / no_circ_mv."""
    values: dict[str, float] = {}
    if circ_mv is None or circ_mv <= 0:
        return values, "no_circ_mv"

    ttm_net_income = ttm_rollover(
        pit_period_values(store, symbol, as_of, restatement_exclusions, "income", "n_income_attr_p")
    )
    if ttm_net_income is None:
        ep_status = "insufficient_ttm"
    elif ttm_net_income <= 0:
        ep_status = "non_positive_earnings"
    else:
        ep_status = "scored"
        values[PRIMARY_FACTOR] = ttm_net_income / circ_mv

    book_equity = latest_pit_stock_value(
        store, symbol, as_of, restatement_exclusions, "balancesheet", "total_hldr_eqy_exc_min_int"
    )
    if book_equity is not None and book_equity > 0:
        values["book_to_market"] = book_equity / circ_mv

    ttm_cash_flow = ttm_rollover(
        pit_period_values(store, symbol, as_of, restatement_exclusions, "cashflow", "n_cashflow_act")
    )
    if ttm_cash_flow is not None:
        values["cash_flow_to_price"] = ttm_cash_flow / circ_mv

    return values, ep_status


def add_size_neutral_scores(items: list[dict[str, Any]], family: str) -> dict[str, int]:
    valid_count_by_bucket: dict[str, int] = {bucket: 0 for bucket in SIZE_BUCKETS}
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if item.get(family) is None:
            continue
        bucket = item.get("size_bucket")
        if bucket:
            by_bucket[str(bucket)].append(item)
    for bucket in SIZE_BUCKETS:
        bucket_items = by_bucket.get(bucket, [])
        valid_count_by_bucket[bucket] = len(bucket_items)
        if len(bucket_items) < MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY:
            continue
        base.percentile_scores(bucket_items, family, "_size_percentile")
        for item in bucket_items:
            if "_size_percentile" in item:
                item[f"{family}__size_neutral"] = item["_size_percentile"]
            item.pop("_size_percentile", None)
    return valid_count_by_bucket


def add_marginal_industry_size_neutral_scores(items: list[dict[str, Any]]) -> dict[str, int]:
    coverage = {f"{family}_industry_size_neutral_available_observation_count": 0 for family in ALL_FACTORS}
    for item in items:
        for family in ALL_FACTORS:
            industry_score = item.get(f"{family}__industry_neutral")
            size_score = item.get(f"{family}__size_neutral")
            if industry_score is not None and size_score is not None:
                item[f"{family}__industry_size_neutral"] = (float(industry_score) + float(size_score)) / 2.0
                coverage[f"{family}_industry_size_neutral_available_observation_count"] += 1
    return coverage


def primary_size_neutral_bucket_coverage(scored: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    counts = {bucket: 0 for bucket in SIZE_BUCKETS}
    score_field = f"{PRIMARY_FACTOR}__size_neutral"
    for item in scored:
        if item.get(score_field) is None:
            continue
        bucket = item.get("size_bucket")
        if bucket in counts:
            counts[str(bucket)] += 1
    thin_bucket_count = sum(1 for count in counts.values() if count < MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY)
    return {
        "as_of": as_of,
        "q1_count": counts["q1"],
        "q2_count": counts["q2"],
        "q3_count": counts["q3"],
        "q4_count": counts["q4"],
        "q5_count": counts["q5"],
        "thin_bucket_count": thin_bucket_count,
        "passes_minimum_bucket_count": thin_bucket_count == 0,
    }


def primary_observation_count(scored: list[dict[str, Any]]) -> int:
    score_field = f"{PRIMARY_FACTOR}__{PRIMARY_VIEW}"
    return sum(1 for item in scored if item.get(score_field) is not None)


def primary_factor_actual_bucket_counts(scored: list[dict[str, Any]]) -> dict[str, int]:
    """Actual primary-factor-non-null observations per market-cap quintile (before the
    minimum-count scoring skip)."""
    counts = {bucket: 0 for bucket in SIZE_BUCKETS}
    for item in scored:
        if item.get(PRIMARY_FACTOR) is None:
            continue
        bucket = item.get("size_bucket")
        if bucket in counts:
            counts[str(bucket)] += 1
    return counts


def update_primary_size_coverage_diagnostics(
    scored: list[dict[str, Any]],
    as_of: str,
    diagnostics: dict[str, Any],
) -> None:
    if primary_observation_count(scored) == 0:
        diagnostics["primary_no_cohort_zero_score_month_count"] += 1
        diagnostics["primary_no_cohort_zero_score_months"].append(as_of)
        return

    # A startup month where some market-cap quintile has fewer than the minimum EP observations (early
    # panel months before a full TTM rollover window has accrued for most names) cannot form an
    # across-quintile size-neutral score, so it is excluded from cohort formation. This is PIT EP
    # availability, not a threshold relaxation.
    actual_bucket_counts = primary_factor_actual_bucket_counts(scored)
    if min(actual_bucket_counts.values()) < MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY:
        diagnostics["primary_incomplete_size_coverage_month_count"] += 1
        diagnostics["primary_incomplete_size_coverage_months"].append(as_of)
        return

    primary_size_coverage = primary_size_neutral_bucket_coverage(scored, as_of)
    diagnostics["primary_size_neutral_bucket_coverage_by_month"].append(primary_size_coverage)
    diagnostics["primary_size_neutral_coverage_month_count"] += 1
    diagnostics["primary_size_neutral_thin_month_count"] += (
        0 if primary_size_coverage["passes_minimum_bucket_count"] else 1
    )
    month_min_bucket_count = min(
        int(primary_size_coverage[f"{bucket}_count"]) for bucket in SIZE_BUCKETS
    )
    current_min = int(diagnostics["primary_size_neutral_min_bucket_observation_count"])
    if current_min == 0 or month_min_bucket_count < current_min:
        diagnostics["primary_size_neutral_min_bucket_observation_count"] = month_min_bucket_count


def monthly_cohort_rows(
    *,
    store: base.audit.PayloadStore,
    context: base.SignalContext,
    large_cap_universes: dict[str, list[LargeCapMember]],
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    industry_records = base.load_industry_records(store)
    index_prices = {name: base.index_total_return_close_rows(store, code) for name, code in BENCHMARKS.items()}
    stock_price_cache: dict[str, dict[str, dict[str, float]]] = {}
    rows: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {
        "as_of_count": len(MONTHLY_AS_OF_DATES),
        "target_large_cap_universe_size": UNIVERSE_SIZE_N,
        "large_cap_universe_observations": 0,
        "scored_pit_universe_excluded_before_list_count": 0,
        "scored_pit_universe_excluded_after_delist_count": 0,
        "selection_time_name_vetoed_observation_count": 0,
        "selection_time_name_vetoed_symbol_count": 0,
        "industry_neutral_excluded_observation_count": 0,
        "industry_neutral_excluded_symbol_count": 0,
        "industry_neutral_excluded_observation_share": None,
        "industry_neutral_excluded_2018_2020_observation_count": 0,
        "industry_neutral_excluded_2018_2020_observation_share": None,
        "size_neutral_thin_bucket_count": 0,
        "primary_size_neutral_thin_month_count": 0,
        "primary_size_neutral_min_bucket_observation_count": 0,
        "primary_size_neutral_coverage_month_count": 0,
        "primary_size_neutral_bucket_coverage_by_month": [],
        "primary_no_cohort_zero_score_month_count": 0,
        "primary_no_cohort_zero_score_months": [],
        "primary_incomplete_size_coverage_month_count": 0,
        "primary_incomplete_size_coverage_months": [],
        "primary_factor_available_observation_count": 0,
        "ep_non_positive_earnings_excluded_observation_count": 0,
        "ep_insufficient_ttm_coverage_observation_count": 0,
        "return_exit_scheduled_count": 0,
        "return_exit_terminal_last_trade_count": 0,
        "return_exit_next_available_count": 0,
        "return_exit_missing_non_terminal_count": 0,
        "missing_signal_rows": 0,
        "missing_return_rows": 0,
    }
    industry_neutral_scored_observations = 0
    industry_neutral_scored_2018_2020_observations = 0
    industry_neutral_excluded_symbols: set[str] = set()
    selection_time_name_vetoed_symbols: set[str] = set()

    for as_of in MONTHLY_AS_OF_DATES:
        scored: list[dict[str, Any]] = []
        members = large_cap_universes.get(as_of) or []
        diagnostics["large_cap_universe_observations"] += len(members)
        for member in members:
            symbol = member.symbol
            list_date = context.list_date_by_symbol.get(symbol, "00000000")
            delist_date = context.delist_date_by_symbol.get(symbol)
            if as_of < list_date:
                diagnostics["scored_pit_universe_excluded_before_list_count"] += 1
                continue
            if delist_date is not None and as_of >= delist_date:
                diagnostics["scored_pit_universe_excluded_after_delist_count"] += 1
                continue
            if base.symbol_vetoed_at_selection_time(context, symbol, as_of):
                diagnostics["selection_time_name_vetoed_observation_count"] += 1
                selection_time_name_vetoed_symbols.add(symbol)
                continue
            values, ep_status = ep_signal_values(
                store=store,
                symbol=symbol,
                as_of=as_of,
                restatement_exclusions=restatement_exclusions,
                circ_mv=member.market_cap,
            )
            if ep_status == "non_positive_earnings":
                diagnostics["ep_non_positive_earnings_excluded_observation_count"] += 1
            elif ep_status == "insufficient_ttm":
                diagnostics["ep_insufficient_ttm_coverage_observation_count"] += 1
            if not any(factor in values for factor in ALL_FACTORS):
                diagnostics["missing_signal_rows"] += 1
                continue
            l2, l1, industry_source, industry_excluded = base.industry_context_for_symbol(
                industry_records,
                context,
                symbol,
                as_of,
            )
            industry_neutral_scored_observations += 1
            in_early_window = "2018" <= str(as_of)[:4] <= "2020"
            if in_early_window:
                industry_neutral_scored_2018_2020_observations += 1
            if industry_excluded:
                diagnostics["industry_neutral_excluded_observation_count"] += 1
                industry_neutral_excluded_symbols.add(symbol)
                if in_early_window:
                    diagnostics["industry_neutral_excluded_2018_2020_observation_count"] += 1
            item: dict[str, Any] = {
                "symbol": symbol,
                "as_of": as_of,
                "industry_l2": l2,
                "industry_l1": l1,
                "industry_source": industry_source,
                "industry_excluded": industry_excluded,
                "size_bucket": member.size_bucket,
                "market_cap": member.market_cap,
                "raw_market_cap_rank": member.raw_rank,
                "backfilled_after_documented_exclusion": member.backfilled_after_documented_exclusion,
            }
            item.update(values)
            scored.append(item)

        for family in ALL_FACTORS:
            base.percentile_scores(scored, family, f"{family}__non_neutral")
            base.add_industry_neutral_scores(scored, family)
            valid_counts = add_size_neutral_scores(scored, family)
            diagnostics["size_neutral_thin_bucket_count"] += sum(
                1 for count in valid_counts.values() if count < MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY
            )
        coverage = add_marginal_industry_size_neutral_scores(scored)
        diagnostics["primary_factor_available_observation_count"] += coverage[
            f"{PRIMARY_FACTOR}_industry_size_neutral_available_observation_count"
        ]
        update_primary_size_coverage_diagnostics(scored, as_of, diagnostics)

        for item in scored:
            symbol = item["symbol"]
            if symbol not in stock_price_cache:
                stock_price_cache[symbol] = base.stock_total_return_close_rows(store, symbol)
            for horizon in HORIZONS:
                _entry, _scheduled_exit, _resolved_exit, exit_policy = base.resolve_return_dates(
                    stock_price_cache[symbol],
                    context.trade_dates,
                    as_of,
                    horizon,
                    delist_date=context.delist_date_by_symbol.get(symbol),
                )
                if exit_policy == "scheduled_exit":
                    diagnostics["return_exit_scheduled_count"] += 1
                elif exit_policy == "terminal_last_trade_before_delist":
                    diagnostics["return_exit_terminal_last_trade_count"] += 1
                elif exit_policy == "next_available_after_missing_scheduled_exit":
                    diagnostics["return_exit_next_available_count"] += 1
                elif exit_policy == "missing_non_terminal_exit_price":
                    diagnostics["return_exit_missing_non_terminal_count"] += 1
                stock_ret, _primary_bench_ret, entry_date, exit_date = base.compute_return(
                    stock_price_cache[symbol],
                    index_prices[PRIMARY_BENCHMARK],
                    context.trade_dates,
                    as_of,
                    horizon,
                    delist_date=context.delist_date_by_symbol.get(symbol),
                )
                if stock_ret is None:
                    diagnostics["missing_return_rows"] += 1
                    continue
                row = dict(item)
                row.update(
                    {
                        "horizon": horizon,
                        "entry_date": entry_date,
                        "exit_date": exit_date,
                        "stock_return_net": stock_ret,
                    }
                )
                for benchmark_name, prices in index_prices.items():
                    _stock, bench_ret, _entry, _exit = base.compute_return(
                        stock_price_cache[symbol],
                        prices,
                        context.trade_dates,
                        as_of,
                        horizon,
                        delist_date=context.delist_date_by_symbol.get(symbol),
                    )
                    row[f"excess_{benchmark_name}"] = None if bench_ret is None else stock_ret - bench_ret
                rows.append(row)

    diagnostics["selection_time_name_vetoed_symbol_count"] = len(selection_time_name_vetoed_symbols)
    diagnostics["industry_neutral_excluded_symbol_count"] = len(industry_neutral_excluded_symbols)
    if industry_neutral_scored_observations:
        diagnostics["industry_neutral_excluded_observation_share"] = round(
            diagnostics["industry_neutral_excluded_observation_count"] / industry_neutral_scored_observations,
            10,
        )
    if industry_neutral_scored_2018_2020_observations:
        diagnostics["industry_neutral_excluded_2018_2020_observation_share"] = round(
            diagnostics["industry_neutral_excluded_2018_2020_observation_count"]
            / industry_neutral_scored_2018_2020_observations,
            10,
        )
    return rows, stock_price_cache, diagnostics


def result_specs() -> list[dict[str, str | int]]:
    specs: list[dict[str, str | int]] = []
    for view in EP_VALUE_VIEWS:
        for horizon in HORIZONS:
            for benchmark in [PRIMARY_BENCHMARK, SECONDARY_BENCHMARK]:
                specs.append(
                    {
                        "signal_id": PRIMARY_FACTOR,
                        "view": view,
                        "weighting": "equal_weight",
                        "horizon_trading_days": horizon,
                        "benchmark": benchmark,
                    }
                )
    for horizon in HORIZONS:
        for benchmark in [PRIMARY_BENCHMARK, SECONDARY_BENCHMARK]:
            specs.append(
                {
                    "signal_id": PRIMARY_FACTOR,
                    "view": PRIMARY_VIEW,
                    "weighting": "cap_weighted",
                    "horizon_trading_days": horizon,
                    "benchmark": benchmark,
                }
            )
    for factor in DIAGNOSTIC_FACTORS:
        for horizon in HORIZONS:
            for benchmark in [PRIMARY_BENCHMARK, SECONDARY_BENCHMARK]:
                specs.append(
                    {
                        "signal_id": factor,
                        "view": PRIMARY_VIEW,
                        "weighting": "equal_weight",
                        "horizon_trading_days": horizon,
                        "benchmark": benchmark,
                    }
                )
    return specs


def cell_id_for(spec: dict[str, Any]) -> str:
    return (
        f"{spec['signal_id']}_{spec['view']}_{spec['weighting']}"
        f"_{spec['horizon_trading_days']}d_{spec['benchmark']}"
    )


PRIMARY_RESULT_CELL_ID = cell_id_for(
    {
        "signal_id": PRIMARY_FACTOR,
        "view": PRIMARY_VIEW,
        "weighting": "equal_weight",
        "horizon_trading_days": PRIMARY_HORIZON,
        "benchmark": PRIMARY_BENCHMARK,
    }
)


def weighted_mean(values: list[tuple[float, float]], *, weighting: str) -> float:
    if not values:
        raise ValueError("weighted_mean requires values")
    if weighting == "equal_weight":
        return mean(value for value, _weight in values)
    total_weight = sum(weight for _value, weight in values if weight > 0)
    if total_weight <= 0:
        return mean(value for value, _weight in values)
    return sum(value * weight for value, weight in values if weight > 0) / total_weight


def cohort_excess_by_as_of(
    rows_by_horizon_as_of: dict[tuple[int, str], list[dict[str, Any]]],
    as_ofs_by_horizon: dict[int, set[str]],
    *,
    score_field: str,
    excess_field: str,
    horizon: int,
    weighting: str,
    excluded_as_ofs: set[str] = frozenset(),
) -> dict[str, Any]:
    cohort_returns: list[float] = []
    cohort_as_ofs: list[str] = []
    selected_symbols: dict[str, int] = defaultdict(int)
    yearly_positive_return_contribution: dict[str, float] = defaultdict(float)
    monthly_top_counts: list[int] = []
    selections_by_as_of: dict[str, list[str]] = {}
    for as_of in sorted(as_ofs_by_horizon.get(horizon, set())):
        if as_of in excluded_as_ofs:
            continue
        cohort = [
            row
            for row in rows_by_horizon_as_of.get((horizon, as_of), [])
            if row.get(score_field) is not None and row.get(excess_field) is not None
        ]
        if not cohort:
            continue
        cohort.sort(key=lambda row: row[score_field], reverse=True)
        target_top_count = max(MIN_TOP_COUNT, int(len(cohort) * TOP_FRACTION))
        selected = cohort[:target_top_count]
        monthly_top_counts.append(len(selected))
        cohort_return = weighted_mean(
            [(float(row[excess_field]), float(row.get("market_cap") or 0.0)) for row in selected],
            weighting=weighting,
        )
        cohort_returns.append(cohort_return)
        cohort_as_ofs.append(as_of)
        selections_by_as_of[as_of] = [str(row["symbol"]) for row in selected]
        if cohort_return > 0:
            yearly_positive_return_contribution[str(as_of)[:4]] += cohort_return
        for row in selected:
            selected_symbols[str(row["symbol"])] += 1
    return {
        "cohort_returns": cohort_returns,
        "cohort_as_ofs": cohort_as_ofs,
        "selected_symbols": selected_symbols,
        "yearly_positive_return_contribution": yearly_positive_return_contribution,
        "monthly_top_counts": monthly_top_counts,
        "selections_by_as_of": selections_by_as_of,
    }


def summarize_results(
    rows: list[dict[str, Any]],
    incomplete_size_coverage_months: set[str] = frozenset(),
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, list[str]]]:
    incomplete_size_coverage_months = set(incomplete_size_coverage_months)
    results: list[dict[str, Any]] = []
    rows_by_horizon_as_of: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    as_ofs_by_horizon: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        horizon = row.get("horizon")
        as_of = row.get("as_of")
        if isinstance(horizon, int) and isinstance(as_of, str):
            rows_by_horizon_as_of[(horizon, as_of)].append(row)
            as_ofs_by_horizon[horizon].add(as_of)

    primary_series: dict[str, Any] | None = None
    primary_selections: dict[str, list[str]] = {}

    for spec in result_specs():
        signal_id = str(spec["signal_id"])
        view = str(spec["view"])
        weighting = str(spec["weighting"])
        horizon = int(spec["horizon_trading_days"])
        benchmark_name = str(spec["benchmark"])
        score_field = f"{signal_id}__{view}"
        excess_field = f"excess_{benchmark_name}"
        view_excluded_as_ofs = (
            incomplete_size_coverage_months
            if view in ("industry_size_neutral", "size_neutral")
            else frozenset()
        )
        agg = cohort_excess_by_as_of(
            rows_by_horizon_as_of,
            as_ofs_by_horizon,
            score_field=score_field,
            excess_field=excess_field,
            horizon=horizon,
            weighting=weighting,
            excluded_as_ofs=view_excluded_as_ofs,
        )
        cohort_returns = agg["cohort_returns"]
        selected_symbols = agg["selected_symbols"]
        yearly_positive_return_contribution = agg["yearly_positive_return_contribution"]
        monthly_top_counts = agg["monthly_top_counts"]

        if len(cohort_returns) >= 2:
            avg = mean(cohort_returns)
            sd = pstdev(cohort_returns)
            t_stat, _hac_standard_error, hac_lag_months = base.newey_west_hac_t_stat(cohort_returns, horizon=horizon)
            p_value = base.normal_two_sided_p_value(t_stat)
        elif cohort_returns:
            avg = cohort_returns[0]
            sd = 0.0
            t_stat = 0.0
            hac_lag_months = 0
            p_value = None
        else:
            avg = None
            sd = None
            t_stat = None
            hac_lag_months = 0
            p_value = None

        total_selections = sum(selected_symbols.values())
        top_symbol_share = max(selected_symbols.values()) / total_selections if total_selections else None
        total_positive_return_contribution = sum(yearly_positive_return_contribution.values())
        single_year_positive_return_share = (
            max(yearly_positive_return_contribution.values()) / total_positive_return_contribution
            if total_positive_return_contribution > 0
            else None
        )
        diagnostic_excess_drawdown = base.max_drawdown(cohort_returns) if cohort_returns else None
        minimum_monthly_top_count = min(monthly_top_counts) if monthly_top_counts else 0
        is_primary = (
            signal_id == PRIMARY_FACTOR
            and view == PRIMARY_VIEW
            and weighting == "equal_weight"
            and horizon == PRIMARY_HORIZON
            and benchmark_name == PRIMARY_BENCHMARK
        )
        results.append(
            {
                "cell_id": cell_id_for(spec),
                "signal_id": signal_id,
                "view": view,
                "weighting": weighting,
                "diagnostic_role": "primary_decision_cell" if is_primary else "diagnostic_only",
                "horizon_trading_days": horizon,
                "benchmark": benchmark_name,
                "monthly_cohort_count": len(cohort_returns),
                "mean_monthly_cohort_net_excess": None if avg is None else round(avg, 10),
                "monthly_cohort_std": None if sd is None else round(sd, 10),
                "monthly_clustered_t_stat": None if t_stat is None else round(t_stat, 10),
                "monthly_t_stat_method": base.MONTHLY_T_STAT_METHOD,
                "hac_lag_months": hac_lag_months,
                "p_value": None if p_value is None else round(p_value, 10),
                "minimum_monthly_top_count": minimum_monthly_top_count,
                "positive_month_count": len([value for value in cohort_returns if value > 0]),
                "worst_monthly_cohort_excess": round(min(cohort_returns), 10) if cohort_returns else None,
                "best_monthly_cohort_excess": round(max(cohort_returns), 10) if cohort_returns else None,
                "diagnostic_max_drawdown_on_monthly_excess": (
                    None if diagnostic_excess_drawdown is None else round(diagnostic_excess_drawdown, 10)
                ),
                "top_symbol_selection_share": None if top_symbol_share is None else round(top_symbol_share, 10),
                "max_single_year_positive_return_share": (
                    None if single_year_positive_return_share is None else round(single_year_positive_return_share, 10)
                ),
                "passes_minimum_monthly_cohorts": len(cohort_returns) >= MIN_MONTHLY_COHORTS,
                "passes_minimum_top_count": minimum_monthly_top_count >= MIN_TOP_COUNT,
                "passes_name_concentration_guard": top_symbol_share is not None
                and top_symbol_share <= MAX_TOP_SYMBOL_SELECTION_SHARE,
                "passes_single_year_concentration_guard": single_year_positive_return_share is not None
                and single_year_positive_return_share <= MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
            }
        )
        if is_primary:
            primary_series = {
                "cohort_returns": cohort_returns,
                "cohort_as_ofs": agg["cohort_as_ofs"],
            }
            primary_selections = agg["selections_by_as_of"]

    return results, primary_series, primary_selections


def max_drawdown_on_levels(levels: list[float]) -> float | None:
    if not levels:
        return None
    peak: float | None = None
    worst = 0.0
    for value in levels:
        if peak is None or value > peak:
            peak = value
        if peak and peak > 0:
            drawdown = (value / peak) - 1.0
            if drawdown < worst:
                worst = drawdown
    return worst


def half_hac_stats(values: list[float], *, horizon: int) -> dict[str, Any]:
    if not values:
        return {"cohort_count": 0, "mean_net_excess": None, "hac_t_stat": None, "hac_lag_months": 0}
    avg = mean(values)
    if len(values) >= 2:
        t_stat, _se, lag = base.newey_west_hac_t_stat(values, horizon=horizon)
    else:
        t_stat, lag = 0.0, 0
    return {
        "cohort_count": len(values),
        "mean_net_excess": round(avg, 10),
        "hac_t_stat": None if t_stat is None else round(t_stat, 10),
        "hac_lag_months": lag,
    }


def sub_period_robustness(primary_series: dict[str, Any] | None) -> dict[str, Any]:
    if primary_series is None or len(primary_series["cohort_returns"]) < 2:
        return {
            "split_rule": "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves",
            "valid_cohort_count": 0 if primary_series is None else len(primary_series["cohort_returns"]),
            "split_index": 0,
            "first_half": half_hac_stats([], horizon=PRIMARY_HORIZON),
            "second_half": half_hac_stats([], horizon=PRIMARY_HORIZON),
            "both_halves_mean_excess_positive": False,
        }
    returns = primary_series["cohort_returns"]
    split_index = len(returns) // 2
    first = returns[:split_index]
    second = returns[split_index:]
    first_stats = half_hac_stats(first, horizon=PRIMARY_HORIZON)
    second_stats = half_hac_stats(second, horizon=PRIMARY_HORIZON)
    both_positive = (
        first_stats["mean_net_excess"] is not None
        and second_stats["mean_net_excess"] is not None
        and first_stats["mean_net_excess"] > 0
        and second_stats["mean_net_excess"] > 0
    )
    return {
        "split_rule": "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves",
        "valid_cohort_count": len(returns),
        "split_index": split_index,
        "first_half": first_stats,
        "second_half": second_stats,
        "both_halves_mean_excess_positive": both_positive,
    }


def _close_lookup(prices: dict[str, dict[str, float]]):
    dates = sorted(prices)
    closes = [prices[date]["close"] for date in dates]

    def lookup(date: str) -> float | None:
        index = bisect.bisect_right(dates, date) - 1
        if index < 0:
            return None
        return closes[index]

    return lookup


def entry_and_scheduled_exit(as_of: str, trade_dates: list[str]) -> tuple[str | None, str | None]:
    entry_candidates = [date for date in trade_dates if date > as_of]
    if not entry_candidates:
        return None, None
    entry_date = entry_candidates[0]
    entry_idx = trade_dates.index(entry_date)
    exit_idx = entry_idx + PRIMARY_HORIZON
    if exit_idx >= len(trade_dates):
        return entry_date, None
    return entry_date, trade_dates[exit_idx]


def rolling_relative_nav_drawdown(
    *,
    primary_selections: dict[str, list[str]],
    stock_price_cache: dict[str, dict[str, dict[str, float]]],
    csi300_prices: dict[str, dict[str, float]],
    trade_dates: list[str],
) -> dict[str, Any]:
    checkpoints = sorted(MONTHLY_AS_OF_DATES)
    csi_lookup = _close_lookup(csi300_prices)
    symbol_lookup: dict[str, Any] = {}
    tranches: list[dict[str, Any]] = []
    for as_of in sorted(primary_selections):
        symbols = primary_selections.get(as_of) or []
        if not symbols:
            continue
        entry_date, scheduled_exit = entry_and_scheduled_exit(as_of, trade_dates)
        if entry_date is None or scheduled_exit is None:
            continue
        entry_csi = csi_lookup(entry_date)
        if entry_csi is None or entry_csi <= 0:
            continue
        basket: list[tuple[str, float]] = []
        for symbol in symbols:
            prices = stock_price_cache.get(symbol) or {}
            entry_close = prices.get(entry_date, {}).get("close")
            if entry_close is None or entry_close <= 0:
                continue
            if symbol not in symbol_lookup:
                symbol_lookup[symbol] = _close_lookup(prices)
            basket.append((symbol, entry_close))
        if basket:
            tranches.append(
                {
                    "entry_date": entry_date,
                    "scheduled_exit": scheduled_exit,
                    "entry_csi": entry_csi,
                    "basket": basket,
                }
            )

    strategy_nav: list[float] = []
    benchmark_nav: list[float] = []
    relative_nav: list[float] = []
    relative_nav_by_checkpoint: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        strategy_values: list[float] = []
        benchmark_values: list[float] = []
        for tranche in tranches:
            if not (tranche["entry_date"] <= checkpoint <= tranche["scheduled_exit"]):
                continue
            checkpoint_csi = csi_lookup(checkpoint)
            if checkpoint_csi is None or checkpoint_csi <= 0:
                continue
            multiples: list[float] = []
            for symbol, entry_close in tranche["basket"]:
                checkpoint_close = symbol_lookup[symbol](checkpoint)
                if checkpoint_close is None or checkpoint_close <= 0:
                    continue
                multiples.append(checkpoint_close / entry_close)
            if not multiples:
                continue
            strategy_values.append(mean(multiples) - base.ROUND_TRIP_COST)
            benchmark_values.append(checkpoint_csi / tranche["entry_csi"])
        if not strategy_values or not benchmark_values:
            continue
        strategy_level = mean(strategy_values)
        benchmark_level = mean(benchmark_values)
        strategy_nav.append(strategy_level)
        benchmark_nav.append(benchmark_level)
        if benchmark_level > 0:
            relative_level = strategy_level / benchmark_level
            relative_nav.append(relative_level)
            relative_nav_by_checkpoint.append(
                {
                    "as_of": checkpoint,
                    "active_tranche_count": len(strategy_values),
                    "relative_nav": round(relative_level, 10),
                }
            )

    return {
        "method": "rolling_overlapping_monthly_tranche_portfolio_nav",
        "benchmark_construction": "option_a_parallel_same_as_of_schedule_horizon_and_ramp_holding_csi300_total_return_instead_of_selected_basket",
        "cost_applied_to_benchmark_tranches": False,
        "tranche_count": len(tranches),
        "relative_nav_checkpoint_count": len(relative_nav),
        "relative_nav_max_drawdown": (
            None if not relative_nav else round(max_drawdown_on_levels(relative_nav), 10)
        ),
        "absolute_strategy_nav_max_drawdown": (
            None if not strategy_nav else round(max_drawdown_on_levels(strategy_nav), 10)
        ),
        "minimum_allowed_relative_nav_drawdown": MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN,
        "relative_nav_by_checkpoint": relative_nav_by_checkpoint,
    }


def primary_cell_passes_statistical_gates(primary: dict[str, Any], sub_period: dict[str, Any]) -> bool:
    return (
        primary.get("passes_minimum_monthly_cohorts") is True
        and primary.get("passes_minimum_top_count") is True
        and (primary.get("mean_monthly_cohort_net_excess") or 0) > 0
        and (primary.get("monthly_clustered_t_stat") or 0) >= MIN_HAC_T_STAT
        and primary.get("passes_name_concentration_guard") is True
        and primary.get("passes_single_year_concentration_guard") is True
        and sub_period.get("both_halves_mean_excess_positive") is True
    )


def decision_from_results(
    results: list[dict[str, Any]],
    sub_period: dict[str, Any],
    risk_gate_result: dict[str, Any],
) -> dict[str, Any]:
    primary = next((item for item in results if item.get("diagnostic_role") == "primary_decision_cell"), None)
    if primary is None:
        raise ValueError("ep_value result set is missing the single primary decision cell")
    statistical_clue = primary_cell_passes_statistical_gates(primary, sub_period)
    relative_drawdown = risk_gate_result.get("relative_nav_max_drawdown")
    relative_drawdown_gate_passed = (
        relative_drawdown is not None and relative_drawdown >= MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN
    )
    tradeable_candidate = statistical_clue and relative_drawdown_gate_passed

    if statistical_clue and tradeable_candidate:
        verdict = STATISTICAL_ALPHA_CLUE_VERDICT
        plain = (
            "Large-cap ep_value passed the frozen CSI300 504d statistical-alpha-clue gates and the "
            "rolling relative-NAV drawdown gate, so it is a research-only statistical alpha clue and a research-only "
            "tradeable candidate. It still cannot support production, ship-gate evidence, or full-size use."
        )
    elif statistical_clue:
        verdict = STATISTICAL_ALPHA_CLUE_VERDICT
        plain = (
            "Large-cap ep_value passed the frozen statistical-alpha-clue gates but failed the rolling "
            "relative-NAV drawdown gate, so it is a research-only statistical alpha clue but NOT a tradeable candidate."
        )
    else:
        verdict = FALSIFIED_VERDICT
        plain = (
            "Large-cap ep_value failed at least one frozen statistical-alpha-clue gate, so it is falsified "
            "under this frozen single-primary-cell design."
        )

    return {
        "research_verdict": verdict,
        "is_statistical_alpha_clue": statistical_clue,
        "is_tradeable_candidate": tradeable_candidate,
        "statistical_alpha_clue_count": 1 if statistical_clue else 0,
        "tradeable_candidate_count": 1 if tradeable_candidate else 0,
        "primary_cell_id": primary["cell_id"],
        "primary_cell_passed_statistical_gates": statistical_clue,
        "sub_period_both_halves_mean_excess_positive": sub_period.get("both_halves_mean_excess_positive") is True,
        "relative_nav_max_drawdown": relative_drawdown,
        "relative_nav_drawdown_gate_passed": relative_drawdown_gate_passed,
        "risk_gate_affects_tradeable_label_only_not_alpha_clue": True,
        "secondary_benchmark_required_for_alpha_clue": False,
        "diagnostics_can_rescue_primary_failure": False,
        "alpha_found_for_production": False,
        "ship_gate_evidence": False,
        "full_size_allowed": False,
        "plain_result": plain,
        "next_action": (
            "If the primary cell fails, do not rescue it with CSI1000, 252d, non-neutral, cap-weighted, diagnostic "
            "factors, an alternative earnings basis, an alternative denominator, threshold, horizon, benchmark, or "
            "universe changes without a new reviewed preregistration and ledger. A passing clue or tradeable candidate "
            "is research-only until forward-live ship-gate evidence exists."
        ),
    }


def validate_pipeline_result_sanity(
    rows: list[dict[str, Any]],
    results: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    primary_series: dict[str, Any] | None,
) -> None:
    if not rows:
        raise ValueError(
            "ep_value signal-search pipeline failure: no evaluated return rows; do not emit a verdict or spend ledger"
        )
    primary_cells = [item for item in results if item.get("diagnostic_role") == "primary_decision_cell"]
    if len(primary_cells) != 1:
        raise ValueError("ep_value signal-search pipeline failure: result set must contain exactly one primary cell")
    primary = primary_cells[0]
    if primary.get("cell_id") != PRIMARY_RESULT_CELL_ID:
        raise ValueError("ep_value signal-search pipeline failure: primary cell identity drifted")
    if int(primary.get("monthly_cohort_count") or 0) == 0:
        raise ValueError(
            "ep_value signal-search pipeline failure: primary cell has zero cohorts; do not emit a verdict or spend ledger"
        )
    if primary_series is None or len(primary_series.get("cohort_returns") or []) < 2:
        raise ValueError(
            "ep_value signal-search pipeline failure: primary cohort series is too short for a sub-period split"
        )
    if int(diagnostics.get("primary_size_neutral_thin_month_count") or 0) != 0:
        raise ValueError(
            "ep_value signal-search pipeline failure: primary size-neutral bucket coverage is thin; "
            "do not emit a verdict or spend ledger"
        )
    coverage_month_count = int(diagnostics.get("primary_size_neutral_coverage_month_count") or 0)
    if coverage_month_count < int(primary.get("monthly_cohort_count") or 0):
        raise ValueError(
            "ep_value signal-search pipeline failure: primary size-neutral coverage month count "
            "is below the primary cohort count"
        )
    startup_excluded_months = set(diagnostics.get("primary_no_cohort_zero_score_months") or []) | set(
        diagnostics.get("primary_incomplete_size_coverage_months") or []
    )
    primary_cohort_as_ofs = set((primary_series or {}).get("cohort_as_ofs") or [])
    if startup_excluded_months & primary_cohort_as_ofs:
        raise ValueError(
            "ep_value signal-search pipeline failure: a startup (zero-score / incomplete-coverage) month "
            "leaked into the primary decision cohort"
        )


def validate_summary_internal_consistency(summary: dict[str, Any]) -> None:
    """Producer-side guard that the tracked summary is internally consistent before it is written.
    The summary schema pins cell identity and decision flag/verdict consistency; the count==list-length
    invariants that JSON Schema draft-07 cannot express are enforced here."""
    cells = summary.get("result_cells") or []
    primary_cells = [cell for cell in cells if cell.get("diagnostic_role") == "primary_decision_cell"]
    if len(primary_cells) != 1 or primary_cells[0].get("cell_id") != PRIMARY_RESULT_CELL_ID:
        raise ValueError("ep_value summary must contain exactly one primary cell with the frozen primary cell id")
    for cell in cells:
        expected_cell_id = cell_id_for(
            {
                "signal_id": cell.get("signal_id"),
                "view": cell.get("view"),
                "weighting": cell.get("weighting"),
                "horizon_trading_days": cell.get("horizon_trading_days"),
                "benchmark": cell.get("benchmark"),
            }
        )
        if cell.get("cell_id") != expected_cell_id:
            raise ValueError(
                f"ep_value summary cell_id/metadata mismatch: {cell.get('cell_id')} vs {expected_cell_id}"
            )

    decision = summary.get("decision") or {}
    clue = decision.get("is_statistical_alpha_clue")
    tradeable = decision.get("is_tradeable_candidate")
    if (decision.get("research_verdict") == STATISTICAL_ALPHA_CLUE_VERDICT) is not bool(clue):
        raise ValueError("ep_value summary research_verdict contradicts is_statistical_alpha_clue")
    if decision.get("primary_cell_passed_statistical_gates") is not bool(clue):
        raise ValueError("ep_value summary primary_cell_passed_statistical_gates contradicts is_statistical_alpha_clue")
    if decision.get("statistical_alpha_clue_count") != (1 if clue else 0):
        raise ValueError("ep_value summary statistical_alpha_clue_count contradicts is_statistical_alpha_clue")
    if decision.get("tradeable_candidate_count") != (1 if tradeable else 0):
        raise ValueError("ep_value summary tradeable_candidate_count contradicts is_tradeable_candidate")
    if bool(tradeable) is not (bool(clue) and bool(decision.get("relative_nav_drawdown_gate_passed"))):
        raise ValueError(
            "ep_value summary is_tradeable_candidate must equal (is_statistical_alpha_clue and relative_nav_drawdown_gate_passed)"
        )

    diagnostics = summary.get("execution_diagnostics") or {}
    for count_field, list_field in [
        ("primary_no_cohort_zero_score_month_count", "primary_no_cohort_zero_score_months"),
        ("primary_incomplete_size_coverage_month_count", "primary_incomplete_size_coverage_months"),
    ]:
        if diagnostics.get(count_field) != len(diagnostics.get(list_field) or []):
            raise ValueError(f"ep_value summary {count_field} does not match len({list_field})")
    if diagnostics.get("result_cell_count") != len(cells):
        raise ValueError("ep_value summary result_cell_count does not match the number of result cells")


def build_summary(
    *,
    full_raw_root: Path,
    market_cap_raw_root: Path,
    generated_at: str,
    confirm_independent_review_pass: bool,
    confirm_post_review_execute: bool,
) -> dict[str, Any]:
    require_execution_confirmations(
        confirm_independent_review_pass=confirm_independent_review_pass,
        confirm_post_review_execute=confirm_post_review_execute,
    )
    prereg = load_and_validate_preregistration()
    ledger = load_and_validate_ledger()
    market_cap_audit_report = load_and_validate_market_cap_audit_report()
    full_audit_report, store, context, restatement_exclusions, endpoint_results_count = load_full_main_board_sources(
        full_raw_root
    )
    large_cap_universes, universe_diagnostics = load_large_cap_signal_universes(
        market_cap_raw_root=market_cap_raw_root,
        allowed_symbols=set(context.symbols),
    )
    rows, stock_price_cache, diagnostics = monthly_cohort_rows(
        store=store,
        context=context,
        large_cap_universes=large_cap_universes,
        restatement_exclusions=restatement_exclusions,
    )
    results, primary_series, primary_selections = summarize_results(
        rows, set(diagnostics["primary_incomplete_size_coverage_months"])
    )
    validate_pipeline_result_sanity(rows, results, diagnostics, primary_series)
    sub_period = sub_period_robustness(primary_series)
    csi300_prices = base.index_total_return_close_rows(store, BENCHMARKS[PRIMARY_BENCHMARK])
    risk_gate_result = rolling_relative_nav_drawdown(
        primary_selections=primary_selections,
        stock_price_cache=stock_price_cache,
        csi300_prices=csi300_prices,
        trade_dates=context.trade_dates,
    )
    decision = decision_from_results(results, sub_period, risk_gate_result)
    return {
        "schema_name": "a_long_large_cap_ep_value_signal_search_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": SUMMARY_ARTIFACT_ID,
        "source_refs": [
            display_path(PREREGISTRATION_PATH),
            display_path(LEDGER_PATH),
            display_path(MARKET_CAP_AUDIT_REPORT_PATH),
            display_path(cap_audit.MATERIALIZATION_SUMMARY_PATH),
            display_path(cap_audit.DATA_QUALITY_EXCLUSION_DECISION_PATH),
            display_path(base.AUDIT_REPORT_PATH),
            display_path(base.RESTATEMENT_EXCLUSION_LIST_PATH),
            display_path(base.BENCHMARK_ACCESS_PROBE_SUMMARY_PATH),
        ],
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_large_cap_ep_value_signal_search_execution",
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
            "independent_review_confirmed": confirm_independent_review_pass,
            "post_review_execute_confirmed": confirm_post_review_execute,
            "preregistration_validated": prereg.get("artifact_id") == PREREGISTRATION_ARTIFACT_ID,
            "preregistration_review_passed": True,
            "ledger_unspent_before_run": ledger["budget_policy"]["tests_spent_count"] == 0,
            "market_cap_audit_passed": market_cap_audit_report["decision"]["hard_checks_pass"] is True,
            "full_main_board_audit_passed": full_audit_report["decision"]["hard_checks_pass"] is True,
            "benchmark_route_amendment_validated": True,
            "restatement_exclusion_list_loaded": True,
            "restatement_exclusion_groups_expected": EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT,
            "restatement_exclusion_groups_found_in_raw": len(restatement_exclusions),
            "restatement_exclusion_list_applied": len(restatement_exclusions) == EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT,
            "reviewed_data_quality_exclusion_applied": universe_diagnostics[
                "documented_data_quality_exclusion_observation_count"
            ]
            == 1,
            "reviewed_data_quality_exclusion_backfilled": universe_diagnostics[
                "backfilled_after_documented_exclusion_observation_count"
            ]
            == 1,
            "no_network_calls_executed": True,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_endpoint_results": False,
            "tracked_summary_contains_secret": False,
            "tracked_summary_contains_request_url": False,
        },
        "large_cap_universe_boundary": {
            "board_scope": "main_board_only",
            "selected_market_cap_field": SELECTED_MARKET_CAP_FIELD,
            "monthly_as_of_count": len(MONTHLY_AS_OF_DATES),
            "universe_size_n": UNIVERSE_SIZE_N,
            "size_bucket_count": 5,
            "minimum_size_bucket_count_for_primary_percentile": MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY,
            "reviewed_data_quality_exclusion_policy": cap_audit.DATA_QUALITY_EXCLUSION_BACKFILL_POLICY,
            "top500_symbols_written_to_tracked_summary": False,
            **universe_diagnostics,
        },
        "search_design": {
            "primary_signal_id": PRIMARY_SIGNAL_ID,
            "primary_factor": PRIMARY_FACTOR,
            "primary_factor_definition": PRIMARY_FACTOR_DEFINITION,
            "earnings_basis": EARNINGS_BASIS,
            "ttm_rollover_rule": TTM_ROLLOVER_RULE,
            "denominator_field": DENOMINATOR_FIELD,
            "non_positive_ttm_earnings_excluded_from_scoring": True,
            "diagnostic_factors": list(DIAGNOSTIC_FACTORS),
            "primary_view": PRIMARY_VIEW,
            "ep_value_views_reported": list(EP_VALUE_VIEWS),
            "cap_weighted_view_reported": True,
            "primary_horizon_trading_days": PRIMARY_HORIZON,
            "diagnostic_horizons_trading_days": [DIAGNOSTIC_HORIZON],
            "primary_benchmark": PRIMARY_BENCHMARK,
            "diagnostic_benchmark": SECONDARY_BENCHMARK,
            "secondary_benchmark_required_for_alpha_clue": False,
            "stock_return_basis": base.STOCK_RETURN_BASIS,
            "benchmark_return_basis": base.BENCHMARK_RETURN_BASIS,
            "round_trip_cost": base.ROUND_TRIP_COST,
            "top_fraction": TOP_FRACTION,
            "minimum_top_count_per_month": MIN_TOP_COUNT,
            "minimum_monthly_cohorts": MIN_MONTHLY_COHORTS,
            "monthly_t_stat_method": base.MONTHLY_T_STAT_METHOD,
            "hac_lag_rule": base.HAC_LAG_RULE,
            "monthly_cohort_count_is_not_independent_n": True,
            "minimum_hac_t_stat": MIN_HAC_T_STAT,
            "decision_is_two_tier": True,
            "minimum_allowed_relative_nav_drawdown": MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN,
            "max_top_symbol_selection_share": MAX_TOP_SYMBOL_SELECTION_SHARE,
            "max_single_year_positive_return_share": MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
            "sub_period_split_rule": "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves",
            "multiple_testing_adjustment_for_decision": "not_applicable_single_primary_cell_but_fifth_program_level_test_caveated_in_provenance",
            "restatement_exclusion_required": True,
            "diagnostics_can_define_alpha": False,
            "parameter_sweep_executed": False,
            "earnings_basis_search_executed": False,
            "denominator_field_search_executed": False,
            "post_result_rescue_slicing_executed": False,
        },
        "execution_diagnostics": {
            **diagnostics,
            "full_main_board_endpoint_results_count": endpoint_results_count,
            "evaluated_stock_return_rows": len(rows),
            "result_cell_count": len(results),
        },
        "result_cells": results,
        "sub_period_robustness": sub_period,
        "risk_gate_result": risk_gate_result,
        "decision": decision,
        "ledger_update_required_after_commit": {
            "ledger_ref": display_path(LEDGER_PATH),
            "spends_singleton_test": True,
            "test_id": PLANNED_TEST_ID,
            "runner_writes_ledger": True,
            "ledger_write_timing": "pending_summary_then_ledger_then_final_summary",
            "ledger_status_after_runner": "active_no_new_test_authorized",
        },
        "prohibited_claims": {
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "ep_value_proven": False,
            "in_sample_clue_is_out_of_sample_proof": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "result_artifacts": [display_path(SUMMARY_PATH)],
        "limitations": [
            "This summary is research-only and reads already-materialized local raw data only.",
            "ep_value is externally literature-motivated and a distinct value-factor family, but it is the fifth program-level large-cap factor tested, so accumulating multiple testing means even a passing in-sample result is weak; the vs-CSI300 evidence is single-sample.",
            "EP uses circulating market cap (circ_mv) as the denominator; on names with large restricted-share blocks this is an earnings-to-free-float yield. Only the cross-sectional percentile is used, so the unit scale does not affect the ranking.",
            "Names with non-positive trailing-twelve-month earnings are excluded from EP scoring; the EP percentile is over profitable large-caps only.",
            "Statistical power is limited: 504d holds over 2018-2025 give only a few non-overlapping windows, so the HAC t-stat rests on a short effective sample.",
            "The relative-NAV drawdown gate only governs the tradeable-candidate label, not the statistical-alpha-clue verdict.",
            "The unchanged project ship gate still requires at least 12 months of forward-live evidence.",
            "No provider call, DataHub work, broker access, automatic order execution, or production storage is authorized.",
        ],
    }


def ledger_status_for_decision(summary: dict[str, Any]) -> str:
    if summary["decision"]["research_verdict"] == STATISTICAL_ALPHA_CLUE_VERDICT:
        return "spent_passed_research_continue_only"
    return "spent_failed_outcome_threshold"


def spend_ledger_after_success(
    *,
    ledger_path: Path,
    summary: dict[str, Any],
    result_ref: str,
    generated_at: str,
) -> dict[str, Any]:
    ledger = load_and_validate_ledger(ledger_path)
    ledger["generated_at"] = generated_at
    ledger["ledger_status"] = "active_no_new_test_authorized"
    ledger["budget_policy"]["tests_spent_count"] = 1
    ledger["budget_policy"]["tests_available_without_new_review"] = 0
    ledger["test_spend_log"] = [
        {
            "test_id": PLANNED_TEST_ID,
            "preregistration_ref": display_path(PREREGISTRATION_PATH),
            "result_ref": result_ref,
            "status": ledger_status_for_decision(summary),
            "tests_spent": 1,
            "promotion_relevant": True,
            "result_summary": (
                f"research_verdict={summary['decision']['research_verdict']}; "
                f"statistical_alpha_clue_count={summary['decision']['statistical_alpha_clue_count']}; "
                f"tradeable_candidate_count={summary['decision']['tradeable_candidate_count']}; "
                "production_ready=false; ship_gate_evidence=false; full_size_allowed=false"
            ),
            "allowed_followup": (
                "No rerun, factor-definition change, earnings-basis change, denominator change, horizon change, "
                "benchmark change, universe change, diagnostic rescue, or result slicing without a new reviewed "
                "preregistration and ledger. Positive clues remain research-only until forward-live ship-gate evidence exists."
            ),
        }
    ]
    ledger["planned_tests"] = []
    ledger["next_required_actions"] = [
        "Do not rerun or rescue this large-cap ep_value signal search without a new reviewed preregistration and ledger update.",
        "If the result is falsified, treat it as failed under the frozen single-primary-cell rules.",
        "If the result is a research clue or tradeable candidate, route it to forward-live validation; do not treat it as production or ship-gate evidence.",
    ]
    validate_json(LEDGER_SCHEMA_PATH, ledger)
    write_json_atomic(ledger_path, ledger)
    return ledger


def write_summary_and_spend_ledger(*, summary_path: Path, summary: dict[str, Any], generated_at: str) -> None:
    if summary_path.exists():
        raise FileExistsError(
            f"refusing to overwrite existing ep_value signal-search summary: {display_path(summary_path)}"
        )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path = summary_path.with_name(summary_path.name + ".pending")
    write_json_atomic(pending_path, summary)
    try:
        spend_ledger_after_success(
            ledger_path=LEDGER_PATH,
            summary=summary,
            result_ref=display_path(summary_path),
            generated_at=generated_at,
        )
    except Exception:
        pending_path.unlink(missing_ok=True)
        raise
    pending_path.replace(summary_path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = args.generated_at or iso_now()
    summary = build_summary(
        full_raw_root=args.full_raw_root,
        market_cap_raw_root=args.market_cap_raw_root,
        generated_at=generated_at,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    validate_json(SUMMARY_SCHEMA_PATH, summary)
    validate_summary_internal_consistency(summary)
    write_summary_and_spend_ledger(summary_path=args.summary_path, summary=summary, generated_at=generated_at)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(
        json.dumps(
            {
                "research_verdict": summary["decision"]["research_verdict"],
                "is_statistical_alpha_clue": summary["decision"]["is_statistical_alpha_clue"],
                "is_tradeable_candidate": summary["decision"]["is_tradeable_candidate"],
                "plain_result": summary["decision"]["plain_result"],
                "summary_ref": display_path(args.summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
