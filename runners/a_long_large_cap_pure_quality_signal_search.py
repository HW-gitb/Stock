from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from runners import a_long_full_main_board_signal_search as base
from runners import a_long_large_cap_market_cap_audit as cap_audit


ROOT = Path(__file__).resolve().parents[1]

PACKET_PATH = ROOT / "docs" / "a_long_large_cap_pure_quality_signal_search_execution_packet_20260607.json"
PACKET_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_pure_quality_signal_search_execution_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_pure_quality_signal_search_execution_summary.schema.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_large_cap_pure_quality_20260607.json"
PREREGISTRATION_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_pure_quality_preregistration.schema.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "program_test_budget_ledger.schema.json"
MARKET_CAP_AUDIT_REPORT_PATH = (
    ROOT / "research" / "results" / "a_long_large_cap_market_cap_audit_20260607" / "audit_report.json"
)
OUTPUT_DIR = ROOT / "research" / "results" / "a_long_large_cap_pure_quality_20260607"
SUMMARY_PATH = OUTPUT_DIR / "execution_summary.json"

SUMMARY_ARTIFACT_ID = "a_long_large_cap_pure_quality_signal_search_execution_summary_20260607"
PACKET_ARTIFACT_ID = "a_long_large_cap_pure_quality_signal_search_execution_packet_20260607"
PLANNED_TEST_ID = "a_long_large_cap_pure_quality_20260607"
PRIMARY_SIGNAL_ID = "core_quality_composite_percentile_3factor"
COMPONENT_FACTORS = ["profitability_quality", "cash_conversion", "balance_sheet_strength"]
DIAGNOSTIC_FACTORS = COMPONENT_FACTORS + ["earnings_stability"]
COMPOSITE_VIEWS = ["industry_size_neutral", "non_neutral", "industry_neutral", "size_neutral"]
PRIMARY_VIEW = "industry_size_neutral"
PRIMARY_HORIZON = 504
DIAGNOSTIC_HORIZON = 252
HORIZONS = [DIAGNOSTIC_HORIZON, PRIMARY_HORIZON]
PRIMARY_BENCHMARK = "CSI300"
SECONDARY_BENCHMARK = "CSI1000"
BENCHMARKS = base.BENCHMARKS
TOP_FRACTION = 0.2
MIN_TOP_COUNT = 10
MIN_MONTHLY_COHORTS = 48
MAX_TOP_SYMBOL_SELECTION_SHARE = 0.2
MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE = 0.35
MIN_ALLOWED_MONTHLY_EXCESS_DRAWDOWN = -0.15
MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY = 50
UNIVERSE_SIZE_N = 500
MONTHLY_AS_OF_DATES = cap_audit.MONTHLY_AS_OF_DATES
SELECTED_MARKET_CAP_FIELD = "circ_mv"
EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT = base.EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT
SIZE_BUCKETS = [f"q{index}" for index in range(1, 6)]


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
            "Run the reviewed A-long large-cap pure-quality signal search from local raw data. "
            "This executes no provider call, but it spends the large-cap singleton ledger after a valid summary write."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=PACKET_PATH)
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
        raise RuntimeError("large-cap signal search requires --confirm-independent-review-pass")
    if not confirm_post_review_execute:
        raise RuntimeError("large-cap signal search requires --confirm-post-review-execute")


def load_and_validate_packet(path: Path = PACKET_PATH) -> dict[str, Any]:
    packet = read_json(path)
    validate_json(PACKET_SCHEMA_PATH, packet)
    if packet.get("schema_name") != "a_long_large_cap_pure_quality_signal_search_execution_packet":
        raise ValueError("large-cap signal-search packet schema_name mismatch")
    if packet.get("artifact_id") != PACKET_ARTIFACT_ID:
        raise ValueError("large-cap signal-search packet artifact_id mismatch")

    scope = packet.get("scope") or {}
    for field in [
        "research_only",
        "ready_for_later_execution_after_independent_review",
        "actual_signal_search_requires_post_review_execute_command",
        "local_raw_read_only",
        "large_cap_signal_search_allowed_after_gates",
        "manual_order_only",
    ]:
        if scope.get(field) is not True:
            raise ValueError(f"packet scope.{field} must be true")
    for field in [
        "provider_calls_executed_by_this_artifact",
        "tushare_calls_executed_by_this_artifact",
        "data_fetch_executed_by_this_artifact",
        "raw_payloads_read_by_this_artifact",
        "signal_search_executed_by_this_artifact",
        "alpha_backtest_executed_by_this_artifact",
        "datahub_allowed",
        "production_use_allowed",
        "ship_gate_claim_allowed",
        "full_size_manual_use_allowed",
        "broker_or_order_automation_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"packet scope.{field} must be false")

    boundary = packet.get("execution_boundary") or {}
    expected_boundary = {
        "preregistration_ref": "research/preregistrations/a_long_large_cap_pure_quality_20260607.json",
        "ledger_ref": "research/ledgers/a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json",
        "market_cap_audit_report_ref": "research/results/a_long_large_cap_market_cap_audit_20260607/audit_report.json",
        "market_cap_materialization_summary_ref": "docs/a_long_large_cap_market_cap_materialization_execution_summary_20260607.json",
        "market_cap_raw_root": "data/a_long/raw/tushare/large_cap_market_cap_materialization_20260607/",
        "full_main_board_raw_root": "data/a_long/raw/tushare/full_main_board_signal_search_20260605/",
        "full_main_board_audit_report_ref": "research/results/a_long_full_main_board_data_integrity_audit_20260605/audit_report.json",
        "restatement_exclusion_list_ref": "research/results/a_long_full_main_board_data_integrity_audit_20260605/restatement_ambiguous_exclusions.csv",
        "data_quality_exclusion_decision_ref": "docs/a_long_large_cap_data_quality_exclusion_decision_20260607.json",
    }
    for key, expected in expected_boundary.items():
        if boundary.get(key) != expected:
            raise ValueError(f"packet execution boundary mismatch: {key}")
    if boundary.get("monthly_as_of_dates") != MONTHLY_AS_OF_DATES:
        raise ValueError("packet monthly_as_of_dates drifted")
    if boundary.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("packet universe size drifted")
    if boundary.get("selected_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("packet market-cap field drifted")
    if boundary.get("reviewed_data_quality_exclusion_policy") != cap_audit.DATA_QUALITY_EXCLUSION_BACKFILL_POLICY:
        raise ValueError("packet data-quality exclusion policy drifted")

    signal = packet.get("signal_plan") or {}
    if signal.get("primary_signal_id") != PRIMARY_SIGNAL_ID:
        raise ValueError("packet primary signal drifted")
    if signal.get("component_factors") != COMPONENT_FACTORS:
        raise ValueError("packet component factors drifted")
    if signal.get("primary_view") != PRIMARY_VIEW:
        raise ValueError("packet primary view drifted")
    if signal.get("primary_horizon_trading_days") != PRIMARY_HORIZON:
        raise ValueError("packet primary horizon drifted")
    if signal.get("primary_benchmark") != PRIMARY_BENCHMARK:
        raise ValueError("packet primary benchmark drifted")
    if signal.get("secondary_benchmark_required_for_candidate_alpha") is not False:
        raise ValueError("large-cap primary decision must not require CSI1000 pass")
    if signal.get("multiple_testing_adjustment_for_decision") != "not_applicable_single_primary_cell":
        raise ValueError("large-cap primary decision must remain a single primary cell")

    for field, value in (packet.get("pre_execution_gates") or {}).items():
        if value is not True:
            raise ValueError(f"packet gate must stay true: {field}")
    for field, value in (packet.get("prohibited_claims") or {}).items():
        if value is not False:
            raise ValueError(f"packet prohibited claim must stay false: {field}")
    return packet


def load_and_validate_preregistration(path: Path = PREREGISTRATION_PATH) -> dict[str, Any]:
    prereg = read_json(path)
    validate_json(PREREGISTRATION_SCHEMA_PATH, prereg)
    if prereg.get("schema_name") != "a_long_large_cap_pure_quality_preregistration":
        raise ValueError("large-cap preregistration schema_name mismatch")
    scope = prereg.get("scope") or {}
    if scope.get("preregistration_review_status") != "passed_independent_review_ready_for_freeze":
        raise ValueError("large-cap preregistration is not review-passed")
    for field in [
        "research_only",
        "new_hypothesis_not_prior_reslice",
        "manual_order_only",
    ]:
        if scope.get(field) is not True:
            raise ValueError(f"large-cap preregistration scope.{field} must be true")
    for field in [
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
            raise ValueError(f"large-cap preregistration scope.{field} must be false")

    design = prereg.get("frozen_design") or {}
    universe = design.get("universe_rule") or {}
    if universe.get("board_scope") != "main_board_only":
        raise ValueError("large-cap board scope drifted")
    if universe.get("as_of_selection_rule") != "last_open_A_share_trading_day_of_each_calendar_month":
        raise ValueError("large-cap as-of selection rule drifted")
    if universe.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("large-cap universe size drifted")
    if universe.get("universe_size_n_search_allowed") is not False:
        raise ValueError("large-cap universe size search must remain forbidden")
    if universe.get("selection_basis") != "top_500_by_pit_market_cap_as_of_each_as_of_date":
        raise ValueError("large-cap universe selection basis drifted")
    if universe.get("market_cap_field_choice_status") != "circ_mv_reviewed_probe_passed_frozen_for_materialization":
        raise ValueError("large-cap market-cap field status drifted")
    if universe.get("include_later_delisted_names_at_pre_delisting_asofs") is not True:
        raise ValueError("large-cap PIT delisted-name inclusion drifted")
    if universe.get("pit_list_delist_required") is not True:
        raise ValueError("large-cap PIT list/delist requirement drifted")
    if universe.get("selection_time_namechange_veto_required") is not True:
        raise ValueError("large-cap PIT namechange veto requirement drifted")
    if universe.get("reviewed_data_quality_exclusion_boundary_ref") != cap_audit.DATA_QUALITY_EXCLUSION_DECISION_REF:
        raise ValueError("large-cap data-quality exclusion ref drifted")
    exclusion_policy = universe.get("reviewed_data_quality_exclusion_policy") or {}
    if exclusion_policy.get("excluded_symbols") != sorted(cap_audit.EXPECTED_REVIEWED_EXCLUSION_SYMBOLS):
        raise ValueError("large-cap data-quality exclusion symbol drifted")
    if exclusion_policy.get("affected_as_of_dates") != ["20191129"]:
        raise ValueError("large-cap data-quality exclusion date drifted")
    if exclusion_policy.get("max_excluded_symbols") != 1:
        raise ValueError("large-cap data-quality exclusion symbol cap drifted")
    if exclusion_policy.get("max_excluded_observations") != 1:
        raise ValueError("large-cap data-quality exclusion observation cap drifted")
    if exclusion_policy.get("drop_excluded_symbols_before_signal_scoring") is not True:
        raise ValueError("large-cap signal universe must drop reviewed exclusions")
    if exclusion_policy.get("backfill_next_main_board_by_circ_mv") is not True:
        raise ValueError("large-cap signal universe must backfill by circ_mv")
    if exclusion_policy.get("materialized_top500_rederivation_unchanged") is not True:
        raise ValueError("large-cap materialized top500 rederivation boundary drifted")
    if exclusion_policy.get("threshold_rescue_allowed") is not False:
        raise ValueError("large-cap threshold rescue must remain forbidden")
    if universe.get("st_star_bse_chinext_excluded") is not True:
        raise ValueError("large-cap board/status exclusion boundary drifted")

    signal = design.get("signal_rule") or {}
    if signal.get("primary_signal_id") != PRIMARY_SIGNAL_ID:
        raise ValueError("large-cap primary signal drifted")
    if signal.get("primary_signal_type") != "equal_weight_percentile_composite":
        raise ValueError("large-cap primary signal type drifted")
    if signal.get("component_factors") != COMPONENT_FACTORS:
        raise ValueError("large-cap component factors drifted")
    if signal.get("component_weighting") != "equal_weight_one_third_each":
        raise ValueError("large-cap component weighting drifted")
    if signal.get("percentile_rank_required") is not True:
        raise ValueError("large-cap percentile-rank requirement drifted")
    if signal.get("zscore_composite_allowed") is not False:
        raise ValueError("large-cap z-score composite must remain forbidden")
    if signal.get("single_factor_pass_can_define_alpha") is not False:
        raise ValueError("large-cap single-factor rescue must remain forbidden")
    if signal.get("earnings_stability_role") != "frozen_diagnostic_only_not_primary":
        raise ValueError("earnings_stability must remain diagnostic only")
    if signal.get("earnings_stability_can_rescue_primary_failure") is not False:
        raise ValueError("earnings_stability rescue must remain forbidden")
    policy = signal.get("factor_measurement_policy") or {}
    if policy.get("profitability_quality_basis") != base.PROFITABILITY_QUALITY_BASIS:
        raise ValueError("profitability quality basis drifted")
    if policy.get("profitability_quality_annualization_policy") != base.PROFITABILITY_QUALITY_ANNUALIZATION_POLICY:
        raise ValueError("profitability quality annualization policy drifted")
    if policy.get("raw_fina_indicator_roe_direct_cross_section_allowed") is not False:
        raise ValueError("raw fina_indicator ROE ranking must remain forbidden")
    if policy.get("cash_conversion_min_abs_net_income") != base.CASH_CONVERSION_MIN_ABS_NET_INCOME:
        raise ValueError("cash conversion denominator guard drifted")
    if policy.get("cash_conversion_small_denominator_guard_required") is not True:
        raise ValueError("cash conversion small-denominator guard drifted")
    if policy.get("earnings_stability_basis") != base.EARNINGS_STABILITY_BASIS:
        raise ValueError("earnings stability basis drifted")
    if policy.get("mixed_ytd_quarter_sequence_allowed") is not False:
        raise ValueError("mixed YTD quarter sequence must remain forbidden")

    neutral = design.get("neutralization_rule") or {}
    if neutral.get("primary_view") != "industry_and_size_neutral":
        raise ValueError("large-cap preregistered primary view drifted")
    if neutral.get("neutralization_method") != "marginal_double_neutralization":
        raise ValueError("large-cap neutralization method drifted")
    if neutral.get("primary_score_construction") != "equal_weight_average_of_marginal_industry_neutral_and_marginal_size_neutral_percentile_scores":
        raise ValueError("large-cap primary score construction drifted")
    if neutral.get("industry_neutral_score_rule") != "percentile_composite_within_industry_l2_fallback_l1":
        raise ValueError("large-cap industry-neutral score rule drifted")
    if neutral.get("size_neutral_score_rule") != "percentile_composite_within_market_cap_quintile":
        raise ValueError("large-cap size-neutral score rule drifted")
    if neutral.get("combined_score_rule") != "0_5_industry_neutral_percentile_plus_0_5_size_neutral_percentile":
        raise ValueError("large-cap combined score rule drifted")
    if neutral.get("crossed_industry_size_bucket_allowed") is not False:
        raise ValueError("crossed industry-size buckets must remain forbidden")
    if neutral.get("industry_basis") != "SW_L2_then_SW_L1_if_sample_lt_20":
        raise ValueError("large-cap industry basis drifted")
    if neutral.get("industry_l2_min_count") != 20:
        raise ValueError("large-cap industry L2 minimum drifted")
    if neutral.get("industry_l1_min_count") != 2:
        raise ValueError("large-cap industry L1 fallback minimum drifted")
    if neutral.get("size_bucket_rule") != "pit_market_cap_quintile_inside_top_500_per_as_of":
        raise ValueError("large-cap size bucket rule drifted")
    if neutral.get("size_bucket_count") != len(SIZE_BUCKETS):
        raise ValueError("large-cap size bucket count drifted")
    if neutral.get("expected_names_per_size_bucket") != UNIVERSE_SIZE_N // len(SIZE_BUCKETS):
        raise ValueError("large-cap expected size bucket count drifted")
    if neutral.get("minimum_size_bucket_count_for_primary_percentile") != MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY:
        raise ValueError("large-cap size bucket minimum drifted")
    if neutral.get("non_neutral_view_role") != "diagnostic_only_not_primary":
        raise ValueError("large-cap non-neutral diagnostic role drifted")
    if neutral.get("cap_weighted_view_role") != "diagnostic_only_not_primary":
        raise ValueError("large-cap cap-weighted diagnostic role drifted")

    measurement = design.get("measurement_rule") or {}
    if measurement.get("primary_horizon_trading_days") != PRIMARY_HORIZON:
        raise ValueError("large-cap primary horizon drifted")
    if measurement.get("diagnostic_horizons_trading_days") != [DIAGNOSTIC_HORIZON]:
        raise ValueError("large-cap diagnostic horizon drifted")
    if measurement.get("entry_rule") != "next_trading_day_close_after_as_of":
        raise ValueError("large-cap entry rule drifted")
    if measurement.get("round_trip_cost") != base.ROUND_TRIP_COST:
        raise ValueError("large-cap round-trip cost drifted")
    if measurement.get("stock_return_basis") != base.STOCK_RETURN_BASIS:
        raise ValueError("large-cap stock return basis drifted")
    if measurement.get("benchmark_return_basis") != base.BENCHMARK_RETURN_BASIS:
        raise ValueError("large-cap benchmark return basis drifted")
    if measurement.get("same_anchor_required") is not True:
        raise ValueError("large-cap same-anchor requirement drifted")
    if measurement.get("missing_scheduled_exit_policy") != base.MISSING_SCHEDULED_EXIT_POLICY:
        raise ValueError("large-cap missing scheduled exit policy drifted")
    if measurement.get("total_return_required") is not True:
        raise ValueError("large-cap total-return requirement drifted")
    if measurement.get("price_index_fallback_allowed") is not False:
        raise ValueError("large-cap price-index fallback must remain forbidden")

    benchmark = design.get("benchmark_rule") or {}
    if benchmark.get("primary_benchmark") != PRIMARY_BENCHMARK:
        raise ValueError("large-cap primary benchmark drifted")
    if benchmark.get("diagnostic_benchmark") != SECONDARY_BENCHMARK:
        raise ValueError("large-cap diagnostic benchmark drifted")
    if benchmark.get("both_benchmark_pass_required") is not False:
        raise ValueError("large-cap CSI1000 must remain diagnostic")
    if benchmark.get("benchmark_access_probe_ref") != display_path(base.BENCHMARK_ACCESS_PROBE_SUMMARY_PATH):
        raise ValueError("large-cap benchmark access probe ref drifted")
    if benchmark.get("benchmark_access_status") != base.BENCHMARK_ACCESS_STATUS:
        raise ValueError("large-cap benchmark access status drifted")
    if benchmark.get("derived_total_return_open_allowed") is not False:
        raise ValueError("derived total-return open must remain forbidden")

    cell = design.get("decision_cell") or {}
    if cell.get("cell_id") != "primary_core_quality_composite_industry_size_neutral_504d_csi300":
        raise ValueError("large-cap primary cell id drifted")
    if cell.get("signal") != PRIMARY_SIGNAL_ID:
        raise ValueError("large-cap primary cell signal drifted")
    if cell.get("view") != "industry_and_size_neutral":
        raise ValueError("large-cap primary cell view drifted")
    if cell.get("horizon_trading_days") != PRIMARY_HORIZON:
        raise ValueError("large-cap primary cell horizon drifted")
    if cell.get("benchmark") != PRIMARY_BENCHMARK:
        raise ValueError("large-cap primary cell benchmark drifted")
    if cell.get("top_fraction") != TOP_FRACTION:
        raise ValueError("large-cap top fraction drifted")
    if cell.get("minimum_top_count_per_month") != MIN_TOP_COUNT:
        raise ValueError("large-cap minimum top count drifted")
    if cell.get("mean_net_excess_must_be_positive") is not True:
        raise ValueError("large-cap mean excess positivity gate drifted")
    if cell.get("minimum_hac_t_stat") != 2.0:
        raise ValueError("large-cap HAC threshold drifted")
    if cell.get("minimum_monthly_cohorts") != MIN_MONTHLY_COHORTS:
        raise ValueError("large-cap minimum cohort count drifted")
    if cell.get("minimum_allowed_monthly_excess_drawdown") != MIN_ALLOWED_MONTHLY_EXCESS_DRAWDOWN:
        raise ValueError("large-cap drawdown threshold drifted")
    if cell.get("name_concentration_guard_max_share") != MAX_TOP_SYMBOL_SELECTION_SHARE:
        raise ValueError("large-cap name concentration guard drifted")
    if cell.get("single_year_positive_return_guard_max_share") != MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE:
        raise ValueError("large-cap single-year concentration guard drifted")
    if cell.get("multiple_testing_adjustment_for_decision") != "not_applicable_single_primary_cell":
        raise ValueError("large-cap multiple-testing decision policy drifted")

    diagnostics = design.get("diagnostic_cells") or {}
    for field in [
        "report_csi1000",
        "report_252d",
        "report_single_factor_components",
        "report_earnings_stability",
        "report_non_neutral",
    ]:
        if diagnostics.get(field) is not True:
            raise ValueError(f"large-cap diagnostic reporting gate drifted: {field}")
    if diagnostics.get("diagnostics_can_define_alpha") is not False:
        raise ValueError("large-cap diagnostics must not define alpha")

    anti = design.get("anti_p_hacking_controls") or {}
    if anti.get("test_budget_units") != 1:
        raise ValueError("large-cap test budget units drifted")
    for field in [
        "parameter_sweep_allowed",
        "universe_n_search_allowed",
        "single_factor_winner_take_all_allowed",
        "quality_acceleration_allowed_this_round",
        "post_result_rescue_slicing_allowed",
    ]:
        if anti.get(field) is not False:
            raise ValueError(f"large-cap anti-p-hacking control drifted: {field}")
    if anti.get("new_ledger_required_before_any_followup") is not True:
        raise ValueError("large-cap new-ledger follow-up rule drifted")

    hygiene = design.get("pit_and_hygiene_controls") or {}
    if hygiene.get("restatement_exclusion_list_ref") != display_path(base.RESTATEMENT_EXCLUSION_LIST_PATH):
        raise ValueError("large-cap restatement exclusion list ref drifted")
    if hygiene.get("restatement_exclusion_required") is not True:
        raise ValueError("large-cap restatement exclusion requirement drifted")
    if hygiene.get("expected_restatement_exclusion_group_count") != EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT:
        raise ValueError("large-cap restatement exclusion group count drifted")
    if hygiene.get("pit_namechange_required") is not True:
        raise ValueError("large-cap PIT namechange requirement drifted")
    if hygiene.get("current_stock_basic_name_veto_allowed") is not False:
        raise ValueError("current stock_basic name veto must remain forbidden")
    for field in [
        "tracked_summary_contains_raw_rows_allowed",
        "tracked_summary_contains_endpoint_results_allowed",
        "tracked_summary_contains_secret_allowed",
        "tracked_summary_contains_request_url_allowed",
    ]:
        if hygiene.get(field) is not False:
            raise ValueError(f"large-cap tracked summary hygiene drifted: {field}")
    return prereg


def load_and_validate_ledger(path: Path = LEDGER_PATH) -> dict[str, Any]:
    ledger = read_json(path)
    if ledger.get("schema_name") != "program_test_budget_ledger":
        raise ValueError("program-test ledger schema_name mismatch")
    if ledger.get("family_id") != "a_long_large_cap_pure_quality_v1":
        raise ValueError("large-cap ledger family drifted")
    policy = ledger.get("budget_policy") or {}
    if policy.get("tests_spent_count") != 0:
        raise ValueError("large-cap singleton signal-search test was already spent")
    if policy.get("tests_available_without_new_review") != 0:
        raise ValueError("large-cap ledger must not allow unreviewed tests")
    planned = ledger.get("planned_tests") or []
    if len(planned) != 1 or planned[0].get("test_id") != PLANNED_TEST_ID:
        raise ValueError("large-cap planned test mismatch")
    if planned[0].get("planned_status") != "planned_not_reviewed":
        raise ValueError("large-cap planned test status drifted")
    if ledger.get("test_spend_log") != []:
        raise ValueError("large-cap ledger spend log must be empty before execution")
    return ledger


def load_and_validate_market_cap_audit_report(path: Path = MARKET_CAP_AUDIT_REPORT_PATH) -> dict[str, Any]:
    report = read_json(path)
    validate_json(cap_audit.REPORT_SCHEMA_PATH, report)
    if report.get("schema_name") != "a_long_large_cap_market_cap_audit_report":
        raise ValueError("large-cap market-cap audit report schema_name mismatch")
    decision = report.get("decision") or {}
    if decision.get("audit_status") != "passed_large_cap_market_cap_audit_for_signal_package":
        raise ValueError("large-cap market-cap audit must pass before signal package execution")
    if decision.get("hard_checks_pass") is not True:
        raise ValueError("large-cap market-cap audit hard checks must pass")
    if decision.get("signal_search_authorized_by_this_report") is not False:
        raise ValueError("large-cap market-cap audit must not self-authorize signal search")
    if decision.get("alpha_found") is not False:
        raise ValueError("large-cap market-cap audit must not claim alpha")
    boundary = report.get("audit_boundary") or {}
    if boundary.get("monthly_as_of_dates") != MONTHLY_AS_OF_DATES:
        raise ValueError("large-cap market-cap audit as-of dates drifted")
    if boundary.get("selected_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("large-cap market-cap audit selected field drifted")
    if boundary.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("large-cap market-cap audit universe size drifted")
    checks = {item.get("check_id"): item for item in report.get("check_results", [])}
    bridge = checks.get("prior_full_main_board_universe_bridge") or {}
    metrics = bridge.get("metrics") or {}
    if metrics.get("total_unresolved_outside_prior_audited_universe_observations") != 0:
        raise ValueError("large-cap market-cap audit still has unresolved bridge gaps")
    if metrics.get("documented_data_quality_exclusion_observations") != 1:
        raise ValueError("large-cap market-cap audit documented exclusion count drifted")
    if metrics.get("signal_universe_backfill_observations") != 1:
        raise ValueError("large-cap market-cap audit backfill count drifted")
    return report


def load_full_main_board_sources(full_raw_root: Path) -> tuple[dict[str, Any], base.audit.PayloadStore, base.SignalContext, set[tuple[str, str, str, str]], int]:
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
        raise ValueError("large-cap materialization endpoint count drifted")
    for result, as_of in zip(endpoint_results, MONTHLY_AS_OF_DATES):
        if result.get("trade_date") != as_of:
            raise ValueError("large-cap materialization as-of order drifted")
        raw_path = cap_audit.resolve_raw_ref(market_cap_raw_root, result.get("raw_payload_ref"))
        payload = read_json(raw_path)
        if payload.get("call_status") != "success":
            raise ValueError(f"large-cap market-cap raw payload did not succeed: {result.get('call_id')}")
        records = [row for row in payload.get("records", []) if isinstance(row, dict)]
        ranked = cap_audit.ranked_main_board_by_market_cap(records)
        if len(ranked) < UNIVERSE_SIZE_N:
            raise ValueError(f"large-cap ranked universe is smaller than {UNIVERSE_SIZE_N}: {as_of}")
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
        raise ValueError("large-cap signal universe is incomplete after reviewed exclusion/backfill")
    if diagnostics["outside_prior_audited_universe_after_backfill_observation_count"]:
        raise ValueError("large-cap signal universe contains symbols outside prior audited full-main-board raw universe")
    if diagnostics["documented_data_quality_exclusion_observation_count"] != 1:
        raise ValueError("large-cap documented data-quality exclusion observation count drifted")
    if diagnostics["backfilled_after_documented_exclusion_observation_count"] != 1:
        raise ValueError("large-cap backfill observation count drifted")
    return universes, diagnostics


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


def primary_size_neutral_bucket_coverage(scored: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    counts = {bucket: 0 for bucket in SIZE_BUCKETS}
    score_field = f"{PRIMARY_SIGNAL_ID}__size_neutral"
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


def _mean_if_all_present(item: dict[str, Any], fields: list[str]) -> float | None:
    values: list[float] = []
    for field in fields:
        value = item.get(field)
        if value is None:
            return None
        values.append(float(value))
    return mean(values)


def add_composite_scores(items: list[dict[str, Any]]) -> dict[str, int]:
    coverage = {
        "primary_composite_available_observation_count": 0,
        "non_neutral_composite_available_observation_count": 0,
        "industry_neutral_composite_available_observation_count": 0,
        "size_neutral_composite_available_observation_count": 0,
        "single_factor_industry_size_neutral_available_observation_count": 0,
    }
    for item in items:
        for family in DIAGNOSTIC_FACTORS:
            industry_score = item.get(f"{family}__industry_neutral")
            size_score = item.get(f"{family}__size_neutral")
            if industry_score is not None and size_score is not None:
                item[f"{family}__industry_size_neutral"] = (float(industry_score) + float(size_score)) / 2.0
                if family in COMPONENT_FACTORS:
                    coverage["single_factor_industry_size_neutral_available_observation_count"] += 1

        for view in ["non_neutral", "industry_neutral", "size_neutral"]:
            score = _mean_if_all_present(item, [f"{family}__{view}" for family in COMPONENT_FACTORS])
            if score is not None:
                item[f"{PRIMARY_SIGNAL_ID}__{view}"] = score
                coverage[f"{view}_composite_available_observation_count"] += 1
        industry_score = item.get(f"{PRIMARY_SIGNAL_ID}__industry_neutral")
        size_score = item.get(f"{PRIMARY_SIGNAL_ID}__size_neutral")
        if industry_score is not None and size_score is not None:
            item[f"{PRIMARY_SIGNAL_ID}__industry_size_neutral"] = (float(industry_score) + float(size_score)) / 2.0
            coverage["primary_composite_available_observation_count"] += 1
    return coverage


def monthly_cohort_rows(
    *,
    store: base.audit.PayloadStore,
    context: base.SignalContext,
    large_cap_universes: dict[str, list[LargeCapMember]],
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
        "primary_size_neutral_bucket_coverage_by_month": [],
        "primary_composite_available_observation_count": 0,
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
            values = base.compute_signal_values(store, symbol, as_of, restatement_exclusions)
            if not any(factor in values for factor in COMPONENT_FACTORS):
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

        for family in DIAGNOSTIC_FACTORS:
            base.percentile_scores(scored, family, f"{family}__non_neutral")
            base.add_industry_neutral_scores(scored, family)
            valid_counts = add_size_neutral_scores(scored, family)
            diagnostics["size_neutral_thin_bucket_count"] += sum(
                1 for count in valid_counts.values() if count < MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY
            )
        coverage = add_composite_scores(scored)
        diagnostics["primary_composite_available_observation_count"] += coverage[
            "primary_composite_available_observation_count"
        ]
        primary_size_coverage = primary_size_neutral_bucket_coverage(scored, as_of)
        diagnostics["primary_size_neutral_bucket_coverage_by_month"].append(primary_size_coverage)
        diagnostics["primary_size_neutral_thin_month_count"] += (
            0 if primary_size_coverage["passes_minimum_bucket_count"] else 1
        )
        month_min_bucket_count = min(
            int(primary_size_coverage[f"{bucket}_count"]) for bucket in SIZE_BUCKETS
        )
        current_min = int(diagnostics["primary_size_neutral_min_bucket_observation_count"])
        if current_min == 0 or month_min_bucket_count < current_min:
            diagnostics["primary_size_neutral_min_bucket_observation_count"] = month_min_bucket_count

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
    return rows, diagnostics


def result_specs() -> list[dict[str, str | int]]:
    specs: list[dict[str, str | int]] = []
    for view in COMPOSITE_VIEWS:
        for horizon in HORIZONS:
            for benchmark in [PRIMARY_BENCHMARK, SECONDARY_BENCHMARK]:
                specs.append(
                    {
                        "signal_id": PRIMARY_SIGNAL_ID,
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
                    "signal_id": PRIMARY_SIGNAL_ID,
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


def weighted_mean(values: list[tuple[float, float]], *, weighting: str) -> float:
    if not values:
        raise ValueError("weighted_mean requires values")
    if weighting == "equal_weight":
        return mean(value for value, _weight in values)
    total_weight = sum(weight for _value, weight in values if weight > 0)
    if total_weight <= 0:
        return mean(value for value, _weight in values)
    return sum(value * weight for value, weight in values if weight > 0) / total_weight


def summarize_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    rows_by_horizon_as_of: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    as_ofs_by_horizon: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        horizon = row.get("horizon")
        as_of = row.get("as_of")
        if isinstance(horizon, int) and isinstance(as_of, str):
            rows_by_horizon_as_of[(horizon, as_of)].append(row)
            as_ofs_by_horizon[horizon].add(as_of)

    for spec in result_specs():
        signal_id = str(spec["signal_id"])
        view = str(spec["view"])
        weighting = str(spec["weighting"])
        horizon = int(spec["horizon_trading_days"])
        benchmark_name = str(spec["benchmark"])
        score_field = f"{signal_id}__{view}"
        excess_field = f"excess_{benchmark_name}"
        cohort_returns: list[float] = []
        selected_symbols: dict[str, int] = defaultdict(int)
        yearly_positive_return_contribution: dict[str, float] = defaultdict(float)
        monthly_top_counts: list[int] = []
        for as_of in sorted(as_ofs_by_horizon.get(horizon, set())):
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
            if cohort_return > 0:
                yearly_positive_return_contribution[str(as_of)[:4]] += cohort_return
            for row in selected:
                selected_symbols[str(row["symbol"])] += 1

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
        drawdown = base.max_drawdown(cohort_returns) if cohort_returns else None
        minimum_monthly_top_count = min(monthly_top_counts) if monthly_top_counts else 0
        is_primary = (
            signal_id == PRIMARY_SIGNAL_ID
            and view == PRIMARY_VIEW
            and weighting == "equal_weight"
            and horizon == PRIMARY_HORIZON
            and benchmark_name == PRIMARY_BENCHMARK
        )
        results.append(
            {
                "cell_id": (
                    f"{signal_id}_{view}_{weighting}_{horizon}d_{benchmark_name}"
                ),
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
                "max_drawdown_on_monthly_excess": None if drawdown is None else round(drawdown, 10),
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
                "passes_drawdown_guard": drawdown is not None and drawdown >= MIN_ALLOWED_MONTHLY_EXCESS_DRAWDOWN,
            }
        )
    return results


def primary_cell_passes(item: dict[str, Any]) -> bool:
    return (
        item.get("diagnostic_role") == "primary_decision_cell"
        and item.get("passes_minimum_monthly_cohorts") is True
        and item.get("passes_minimum_top_count") is True
        and (item.get("mean_monthly_cohort_net_excess") or 0) > 0
        and (item.get("monthly_clustered_t_stat") or 0) >= 2.0
        and item.get("passes_name_concentration_guard") is True
        and item.get("passes_single_year_concentration_guard") is True
        and item.get("passes_drawdown_guard") is True
    )


def decision_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    primary = next((item for item in results if item.get("diagnostic_role") == "primary_decision_cell"), None)
    if primary is None:
        raise ValueError("large-cap result set is missing the single primary decision cell")
    passed = primary_cell_passes(primary)
    if passed:
        verdict = "candidate_alpha_clue_research_only"
        plain = (
            "Large-cap pure-quality primary cell passed the frozen CSI300 504d gates. "
            "This is research-only and still cannot support production or full-size use."
        )
    else:
        verdict = "falsified_large_cap_pure_quality_under_frozen_rules"
        plain = "Large-cap pure-quality found no usable alpha under the frozen single-primary-cell rules."
    return {
        "research_verdict": verdict,
        "candidate_alpha_clue_count": 1 if passed else 0,
        "primary_cell_id": primary["cell_id"],
        "primary_cell_passed": passed,
        "secondary_benchmark_required_for_candidate_alpha": False,
        "diagnostics_can_rescue_primary_failure": False,
        "alpha_found_for_production": False,
        "ship_gate_evidence": False,
        "full_size_allowed": False,
        "plain_result": plain,
        "next_action": (
            "If the primary cell fails, do not rescue it with CSI1000, 252d, non-neutral, cap-weighted, "
            "single-factor, earnings-stability, threshold, horizon, benchmark, or universe changes without "
            "a new reviewed preregistration and ledger."
        ),
    }


def validate_pipeline_result_sanity(rows: list[dict[str, Any]], results: list[dict[str, Any]], diagnostics: dict[str, Any]) -> None:
    if not rows:
        raise ValueError(
            "large-cap signal-search pipeline failure: no evaluated return rows; do not emit a verdict or spend ledger"
        )
    primary_cells = [item for item in results if item.get("diagnostic_role") == "primary_decision_cell"]
    if len(primary_cells) != 1:
        raise ValueError("large-cap signal-search pipeline failure: result set must contain exactly one primary cell")
    primary = primary_cells[0]
    if primary.get("cell_id") != f"{PRIMARY_SIGNAL_ID}_{PRIMARY_VIEW}_equal_weight_{PRIMARY_HORIZON}d_{PRIMARY_BENCHMARK}":
        raise ValueError("large-cap signal-search pipeline failure: primary cell identity drifted")
    if int(primary.get("monthly_cohort_count") or 0) == 0:
        raise ValueError(
            "large-cap signal-search pipeline failure: primary cell has zero cohorts; do not emit a verdict or spend ledger"
        )
    if int(diagnostics.get("primary_size_neutral_thin_month_count") or 0) != 0:
        raise ValueError(
            "large-cap signal-search pipeline failure: primary size-neutral bucket coverage is thin; "
            "do not emit a verdict or spend ledger"
        )


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
    packet = load_and_validate_packet()
    prereg = load_and_validate_preregistration()
    ledger = load_and_validate_ledger()
    market_cap_audit_report = load_and_validate_market_cap_audit_report()
    full_audit_report, store, context, restatement_exclusions, endpoint_results_count = load_full_main_board_sources(full_raw_root)
    large_cap_universes, universe_diagnostics = load_large_cap_signal_universes(
        market_cap_raw_root=market_cap_raw_root,
        allowed_symbols=set(context.symbols),
    )
    rows, diagnostics = monthly_cohort_rows(
        store=store,
        context=context,
        large_cap_universes=large_cap_universes,
        restatement_exclusions=restatement_exclusions,
    )
    results = summarize_results(rows)
    validate_pipeline_result_sanity(rows, results, diagnostics)
    decision = decision_from_results(results)
    return {
        "schema_name": "a_long_large_cap_pure_quality_signal_search_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": SUMMARY_ARTIFACT_ID,
        "source_refs": [
            display_path(PACKET_PATH),
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
            "purpose": "a_long_large_cap_pure_quality_signal_search_execution",
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
            "packet_validated": packet.get("artifact_id") == PACKET_ARTIFACT_ID,
            "preregistration_validated": prereg.get("artifact_id") == "a_long_large_cap_pure_quality_20260607",
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
            "component_factors": list(COMPONENT_FACTORS),
            "diagnostic_factors": list(DIAGNOSTIC_FACTORS),
            "primary_view": PRIMARY_VIEW,
            "composite_views_reported": list(COMPOSITE_VIEWS),
            "cap_weighted_view_reported": True,
            "primary_horizon_trading_days": PRIMARY_HORIZON,
            "diagnostic_horizons_trading_days": [DIAGNOSTIC_HORIZON],
            "primary_benchmark": PRIMARY_BENCHMARK,
            "diagnostic_benchmark": SECONDARY_BENCHMARK,
            "secondary_benchmark_required_for_candidate_alpha": False,
            "stock_return_basis": base.STOCK_RETURN_BASIS,
            "benchmark_return_basis": base.BENCHMARK_RETURN_BASIS,
            "round_trip_cost": base.ROUND_TRIP_COST,
            "top_fraction": TOP_FRACTION,
            "minimum_top_count_per_month": MIN_TOP_COUNT,
            "minimum_monthly_cohorts": MIN_MONTHLY_COHORTS,
            "monthly_t_stat_method": base.MONTHLY_T_STAT_METHOD,
            "hac_lag_rule": base.HAC_LAG_RULE,
            "monthly_cohort_count_is_not_independent_n": True,
            "minimum_hac_t_stat": 2.0,
            "min_allowed_monthly_excess_drawdown": MIN_ALLOWED_MONTHLY_EXCESS_DRAWDOWN,
            "max_top_symbol_selection_share": MAX_TOP_SYMBOL_SELECTION_SHARE,
            "max_single_year_positive_return_share": MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
            "multiple_testing_adjustment_for_decision": "not_applicable_single_primary_cell",
            "diagnostics_can_define_alpha": False,
            "parameter_sweep_executed": False,
            "post_result_rescue_slicing_executed": False,
        },
        "execution_diagnostics": {
            **diagnostics,
            "full_main_board_endpoint_results_count": endpoint_results_count,
            "evaluated_stock_return_rows": len(rows),
            "result_cell_count": len(results),
        },
        "result_cells": results,
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
            "provider_selected": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "result_artifacts": [display_path(SUMMARY_PATH)],
        "limitations": [
            "This summary is research-only and reads already-materialized local raw data only.",
            "A positive result would be a research clue, not production proof, and cannot unlock full-size use.",
            "The unchanged project ship gate still requires at least 12 months of forward-live evidence.",
            "No provider call, DataHub work, broker access, automatic order execution, or production storage is authorized.",
        ],
    }


def ledger_status_for_decision(summary: dict[str, Any]) -> str:
    if summary["decision"]["research_verdict"] == "candidate_alpha_clue_research_only":
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
                f"candidate_alpha_clue_count={summary['decision']['candidate_alpha_clue_count']}; "
                "production_ready=false; ship_gate_evidence=false; full_size_allowed=false"
            ),
            "allowed_followup": (
                "No rerun, threshold change, family change, horizon change, benchmark change, universe change, "
                "diagnostic rescue, or result slicing without a new reviewed preregistration and ledger. "
                "Positive clues remain research-only until forward-live ship-gate evidence exists."
            ),
        }
    ]
    ledger["planned_tests"] = []
    ledger["next_required_actions"] = [
        "Do not rerun or rescue this large-cap pure-quality signal search without a new reviewed preregistration and ledger update.",
        "If the result is falsified, treat it as failed under the frozen single-primary-cell rules.",
        "If the result is a research clue, route it to forward-live validation; do not treat it as production or ship-gate evidence.",
    ]
    validate_json(LEDGER_SCHEMA_PATH, ledger)
    write_json_atomic(ledger_path, ledger)
    return ledger


def write_summary_and_spend_ledger(*, summary_path: Path, summary: dict[str, Any], generated_at: str) -> None:
    if summary_path.exists():
        raise FileExistsError(f"refusing to overwrite existing large-cap signal-search summary: {display_path(summary_path)}")
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
    write_summary_and_spend_ledger(summary_path=args.summary_path, summary=summary, generated_at=generated_at)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run(args)
    print(
        json.dumps(
            {
                "research_verdict": summary["decision"]["research_verdict"],
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
