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


SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_batch_factor_search_signal_search_execution_summary.schema.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_large_cap_batch_factor_search_20260609.json"
PREREGISTRATION_SCHEMA_PATH = ROOT / "schemas" / "a_long_large_cap_batch_factor_search_preregistration.schema.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_large_cap_batch_factor_search_program_test_budget_ledger_20260609.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "program_test_budget_ledger.schema.json"
MARKET_CAP_AUDIT_REPORT_PATH = (
    ROOT / "research" / "results" / "a_long_large_cap_market_cap_audit_20260607" / "audit_report.json"
)
OUTPUT_DIR = ROOT / "research" / "results" / "a_long_large_cap_batch_factor_search_20260609"
SUMMARY_PATH = OUTPUT_DIR / "execution_summary.json"

SUMMARY_ARTIFACT_ID = "a_long_large_cap_batch_factor_search_signal_search_execution_summary_20260609"
PLANNED_TEST_ID = "a_long_large_cap_batch_factor_search_20260609"
PREREGISTRATION_ARTIFACT_ID = "a_long_large_cap_batch_factor_search_20260609"
LEDGER_FAMILY_ID = "a_long_large_cap_batch_factor_search_v1"

# The nine frozen primary factors (all *_to_circ_mv denominators / score directions per the prereg) plus
# the frozen family-equal-weight composite. The composite is the 10th primary hypothesis under BH-FDR.
COMPOSITE_ID = "family_balanced_composite"
FACTOR_FAMILIES: dict[str, str] = {
    "book_to_circ_mv": "value",
    "cash_flow_to_circ_mv": "value",
    "sales_to_circ_mv": "value",
    "low_accruals": "earnings_quality",
    "low_asset_growth": "investment",
    "roa_ttm": "profitability",
    "low_beta": "low_risk",
    "low_max": "low_risk",
    "momentum_12_1": "momentum",
}
BATCH_FACTORS = list(FACTOR_FAMILIES.keys())
ALL_FACTORS = BATCH_FACTORS + [COMPOSITE_ID]
PRIMARY_HYPOTHESES = list(ALL_FACTORS)
M_TOTAL_HYPOTHESES = len(PRIMARY_HYPOTHESES)

PRIMARY_VIEW = "industry_size_neutral"
DIAGNOSTIC_VIEWS = ["non_neutral", "industry_neutral", "size_neutral"]
PRIMARY_HORIZON = 504
DIAGNOSTIC_HORIZON = 252
HORIZONS = [DIAGNOSTIC_HORIZON, PRIMARY_HORIZON]
PRIMARY_BENCHMARK = "CSI300"
SECONDARY_BENCHMARK = "CSI1000"
BENCHMARKS = base.BENCHMARKS

# Frozen trailing windows for the price-based factors (no search).
LOW_BETA_TRAILING_DAYS = 252
LOW_MAX_TRAILING_DAYS = 21
MOMENTUM_FORMATION_START_DAYS_AGO = 252
MOMENTUM_FORMATION_END_DAYS_AGO = 21
TTM_ROLLOVER_PERIOD_LIMIT = 12

TOP_FRACTION = 0.2
MIN_TOP_COUNT = 10
MIN_MONTHLY_COHORTS = 48
MAX_TOP_SYMBOL_SELECTION_SHARE = 0.2
MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE = 0.35
MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN = -0.15
MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY = 50
UNIVERSE_SIZE_N = 500
MONTHLY_AS_OF_DATES = cap_audit.MONTHLY_AS_OF_DATES
SELECTED_MARKET_CAP_FIELD = "circ_mv"
EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT = base.EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT
SIZE_BUCKETS = [f"q{index}" for index in range(1, 6)]

# Benjamini-Hochberg false-discovery-rate thresholds (frozen before the run).
Q_RESEARCH_CLUE_GATE = 0.1
Q_STRICT_DIAGNOSTIC = 0.05

DRY_VERDICT = "batch_dry_no_factor_survives_fdr_under_frozen_rules"
CLUE_VERDICT = "batch_statistical_alpha_clue_research_only"


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
            "Run the reviewed A-long large-cap BATCH multi-factor signal search from local raw data. It scores "
            "nine frozen factors (book/cash_flow/sales_to_circ_mv, low_accruals, low_asset_growth, roa_ttm, "
            "low_beta, low_max, momentum_12_1) plus a frozen family-equal-weight composite on the reviewed "
            "top-500 circ_mv universe + full-main-board PIT fundamentals (no provider call), decides across "
            "factors with Benjamini-Hochberg FDR over the ten primary cells, and spends the batch singleton "
            "ledger once after a valid summary write."
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
        raise RuntimeError("batch signal search requires --confirm-independent-review-pass")
    if not confirm_post_review_execute:
        raise RuntimeError("batch signal search requires --confirm-post-review-execute")


def load_and_validate_preregistration(path: Path = PREREGISTRATION_PATH) -> dict[str, Any]:
    prereg = read_json(path)
    validate_json(PREREGISTRATION_SCHEMA_PATH, prereg)
    if prereg.get("schema_name") != "a_long_large_cap_batch_factor_search_preregistration":
        raise ValueError("batch preregistration schema_name mismatch")
    if prereg.get("artifact_id") != PREREGISTRATION_ARTIFACT_ID:
        raise ValueError("batch preregistration artifact_id mismatch")
    scope = prereg.get("scope") or {}
    if scope.get("preregistration_review_status") != "passed_independent_review_ready_for_freeze":
        raise ValueError("batch preregistration is not review-passed")
    for field in ["research_only", "is_batch_multiple_testing_design", "manual_order_only"]:
        if scope.get(field) is not True:
            raise ValueError(f"batch preregistration scope.{field} must be true")
    for field in [
        "signal_search_authorized_by_this_artifact",
        "data_fetch_allowed_by_this_artifact",
        "provider_call_allowed_by_this_artifact",
        "production_use_allowed",
        "ship_gate_claim_allowed",
        "full_size_manual_use_allowed",
        "broker_or_order_automation_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"batch preregistration scope.{field} must be false")

    design = prereg.get("frozen_design") or {}
    if design.get("design_id") != LEDGER_FAMILY_ID:
        raise ValueError("batch design id drifted")
    bfr = design.get("batch_factor_rule") or {}
    if bfr.get("factor_count") != len(BATCH_FACTORS):
        raise ValueError("batch factor count drifted")
    if bfr.get("total_primary_hypotheses") != M_TOTAL_HYPOTHESES:
        raise ValueError("batch total primary hypotheses drifted")
    prereg_factor_ids = [factor.get("factor_id") for factor in bfr.get("factors") or []]
    if prereg_factor_ids != BATCH_FACTORS:
        raise ValueError("batch factor list drifted from the runner-frozen factor order")
    for factor in bfr.get("factors") or []:
        fid = factor.get("factor_id")
        if FACTOR_FAMILIES.get(fid) != factor.get("family"):
            raise ValueError(f"batch factor family drifted: {fid}")
        if factor.get("high_value_is_high_score") is not True:
            raise ValueError(f"batch factor score direction drifted: {fid}")
    composite = bfr.get("composite") or {}
    if composite.get("composite_id") != COMPOSITE_ID:
        raise ValueError("batch composite id drifted")
    if composite.get("counted_as_additional_primary_hypothesis") is not True:
        raise ValueError("batch composite must be counted as an additional primary hypothesis")
    if composite.get("weight_search_allowed") is not False:
        raise ValueError("batch composite weight search must remain forbidden")

    decision = design.get("decision_rule") or {}
    if decision.get("decision_type") != "batch_bh_fdr_over_primary_cells":
        raise ValueError("batch decision type drifted")
    if decision.get("fdr_method") != "benjamini_hochberg":
        raise ValueError("batch fdr method drifted")
    if decision.get("m_total_hypotheses") != M_TOTAL_HYPOTHESES:
        raise ValueError("batch m_total_hypotheses drifted")
    if decision.get("q_research_clue_gate") != Q_RESEARCH_CLUE_GATE:
        raise ValueError("batch q_research_clue_gate drifted")
    if decision.get("q_strict_diagnostic_reported") != Q_STRICT_DIAGNOSTIC:
        raise ValueError("batch q_strict_diagnostic drifted")
    if decision.get("q_search_allowed") is not False:
        raise ValueError("batch q search must remain forbidden")
    pc = decision.get("primary_cell_per_factor") or {}
    if pc.get("view") != "industry_and_size_neutral":
        raise ValueError("batch primary cell view drifted")
    if pc.get("weighting") != "equal_weight":
        raise ValueError("batch primary cell weighting drifted")
    if pc.get("horizon_trading_days") != PRIMARY_HORIZON:
        raise ValueError("batch primary cell horizon drifted")
    if pc.get("benchmark") != PRIMARY_BENCHMARK:
        raise ValueError("batch primary cell benchmark drifted")
    if pc.get("top_fraction") != TOP_FRACTION:
        raise ValueError("batch primary cell top fraction drifted")
    if pc.get("minimum_top_count_per_month") != MIN_TOP_COUNT:
        raise ValueError("batch primary cell minimum top count drifted")
    gates = decision.get("per_factor_statistical_alpha_clue_gates") or {}
    if gates.get("minimum_monthly_cohorts") != MIN_MONTHLY_COHORTS:
        raise ValueError("batch minimum monthly cohorts drifted")
    if gates.get("name_concentration_guard_max_share") != MAX_TOP_SYMBOL_SELECTION_SHARE:
        raise ValueError("batch name concentration guard drifted")
    if gates.get("single_year_positive_return_guard_max_share") != MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE:
        raise ValueError("batch single-year concentration guard drifted")
    if gates.get("sub_period_both_halves_mean_excess_positive_required") is not True:
        raise ValueError("batch sub-period both-halves gate drifted")
    tradeable = decision.get("tradeable_candidate_gates") or {}
    if tradeable.get("minimum_allowed_relative_nav_drawdown") != MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN:
        raise ValueError("batch tradeable relative-NAV drawdown threshold drifted")

    measurement = design.get("measurement_rule") or {}
    if measurement.get("primary_horizon_trading_days") != PRIMARY_HORIZON:
        raise ValueError("batch primary horizon drifted")
    if measurement.get("round_trip_cost") != base.ROUND_TRIP_COST:
        raise ValueError("batch round-trip cost drifted")
    if measurement.get("stock_return_basis") != base.STOCK_RETURN_BASIS:
        raise ValueError("batch stock return basis drifted")
    if measurement.get("benchmark_return_basis") != base.BENCHMARK_RETURN_BASIS:
        raise ValueError("batch benchmark return basis drifted")
    if measurement.get("total_return_required") is not True:
        raise ValueError("batch total-return requirement drifted")

    universe = design.get("universe_rule") or {}
    if universe.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("batch universe size drifted")
    if universe.get("reviewed_data_quality_exclusion_boundary_ref") != cap_audit.DATA_QUALITY_EXCLUSION_DECISION_REF:
        raise ValueError("batch data-quality exclusion ref drifted")

    hygiene = design.get("pit_and_hygiene_controls") or {}
    if hygiene.get("restatement_exclusion_list_ref") != display_path(base.RESTATEMENT_EXCLUSION_LIST_PATH):
        raise ValueError("batch restatement exclusion list ref drifted")
    if hygiene.get("expected_restatement_exclusion_group_count") != EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT:
        raise ValueError("batch restatement exclusion group count drifted")
    if hygiene.get("restatement_exclusion_required") is not True:
        raise ValueError("batch restatement exclusion requirement drifted")

    stopping = design.get("stopping_rule") or {}
    if stopping.get("this_is_the_last_structured_batch_candidate_generation_round") is not True:
        raise ValueError("batch stopping-rule flag drifted")

    anti = design.get("anti_p_hacking_controls") or {}
    if anti.get("test_budget_units") != 1:
        raise ValueError("batch test budget units drifted")
    for field in [
        "factor_definition_search_allowed",
        "factor_count_search_allowed",
        "trailing_window_search_allowed",
        "q_threshold_search_allowed",
        "composite_weight_search_allowed",
        "drop_losing_factors_then_re_fdr_allowed",
    ]:
        if anti.get(field) is not False:
            raise ValueError(f"batch anti-p-hacking control drifted: {field}")

    planned = prereg.get("planned_test_budget") or {}
    if planned.get("test_budget_units") != 1:
        raise ValueError("batch planned test budget drifted")
    if planned.get("required_preregistration_review_status_for_execution") != "passed_independent_review_ready_for_freeze":
        raise ValueError("batch required execution review status drifted")
    return prereg


def load_and_validate_ledger(path: Path = LEDGER_PATH) -> dict[str, Any]:
    ledger = read_json(path)
    validate_json(LEDGER_SCHEMA_PATH, ledger)
    if ledger.get("schema_name") != "program_test_budget_ledger":
        raise ValueError("program-test ledger schema_name mismatch")
    if ledger.get("family_id") != LEDGER_FAMILY_ID:
        raise ValueError("batch ledger family drifted")
    if ledger.get("ledger_status") != "active_planned_test_pending_review":
        raise ValueError("batch ledger is not in the active pre-execution state")
    policy = ledger.get("budget_policy") or {}
    if policy.get("tests_spent_count") != 0:
        raise ValueError("batch singleton signal-search test was already spent")
    if policy.get("tests_available_without_new_review") != 0:
        raise ValueError("batch ledger must not allow unreviewed tests")
    if policy.get("next_test_requires_reviewed_preregistration") is not True:
        raise ValueError("batch ledger must require reviewed preregistration")
    if policy.get("next_test_requires_user_approval") is not True:
        raise ValueError("batch ledger must require user approval")
    planned = ledger.get("planned_tests") or []
    if len(planned) != 1 or planned[0].get("test_id") != PLANNED_TEST_ID:
        raise ValueError("batch planned test mismatch")
    if planned[0].get("planned_status") != "planned_not_reviewed":
        raise ValueError("batch planned test status drifted")
    if planned[0].get("planned_preregistration_ref") != display_path(PREREGISTRATION_PATH):
        raise ValueError("batch ledger planned preregistration ref drifted")
    if planned[0].get("planned_result_ref") != display_path(SUMMARY_PATH):
        raise ValueError("batch ledger planned result ref drifted")
    if planned[0].get("expected_tests_spent") != 1:
        raise ValueError("batch ledger expected_tests_spent must be exactly 1")
    if planned[0].get("approval_status") != "user_approved_pending_review":
        raise ValueError("batch ledger planned test approval status drifted")
    if ledger.get("test_spend_log") != []:
        raise ValueError("batch ledger spend log must be empty before execution")
    return ledger


def load_and_validate_market_cap_audit_report(path: Path = MARKET_CAP_AUDIT_REPORT_PATH) -> dict[str, Any]:
    report = read_json(path)
    validate_json(cap_audit.REPORT_SCHEMA_PATH, report)
    if report.get("schema_name") != "a_long_large_cap_market_cap_audit_report":
        raise ValueError("batch market-cap audit report schema_name mismatch")
    decision = report.get("decision") or {}
    if decision.get("audit_status") != "passed_large_cap_market_cap_audit_for_signal_package":
        raise ValueError("batch market-cap audit must pass before execution")
    if decision.get("hard_checks_pass") is not True:
        raise ValueError("batch market-cap audit hard checks must pass")
    if decision.get("signal_search_authorized_by_this_report") is not False:
        raise ValueError("batch market-cap audit must not self-authorize signal search")
    boundary = report.get("audit_boundary") or {}
    if boundary.get("monthly_as_of_dates") != MONTHLY_AS_OF_DATES:
        raise ValueError("batch market-cap audit as-of dates drifted")
    if boundary.get("selected_market_cap_field") != SELECTED_MARKET_CAP_FIELD:
        raise ValueError("batch market-cap audit selected field drifted")
    if boundary.get("universe_size_n") != UNIVERSE_SIZE_N:
        raise ValueError("batch market-cap audit universe size drifted")
    return report


def load_full_main_board_sources(
    full_raw_root: Path,
) -> tuple[dict[str, Any], base.audit.PayloadStore, base.SignalContext, set[tuple[str, str, str, str]], int]:
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
        raise ValueError("batch materialization endpoint count drifted")
    for result, as_of in zip(endpoint_results, MONTHLY_AS_OF_DATES):
        if result.get("trade_date") != as_of:
            raise ValueError("batch materialization as-of order drifted")
        raw_path = cap_audit.resolve_raw_ref(market_cap_raw_root, result.get("raw_payload_ref"))
        payload = read_json(raw_path)
        if payload.get("call_status") != "success":
            raise ValueError(f"batch market-cap raw payload did not succeed: {result.get('call_id')}")
        records = [row for row in payload.get("records", []) if isinstance(row, dict)]
        ranked = cap_audit.ranked_main_board_by_market_cap(records)
        if len(ranked) < UNIVERSE_SIZE_N:
            raise ValueError(f"batch ranked universe is smaller than {UNIVERSE_SIZE_N}: {as_of}")
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
        raise ValueError("batch signal universe is incomplete after reviewed exclusion/backfill")
    if diagnostics["outside_prior_audited_universe_after_backfill_observation_count"]:
        raise ValueError("batch signal universe contains symbols outside prior audited full-main-board raw universe")
    if diagnostics["documented_data_quality_exclusion_observation_count"] != 1:
        raise ValueError("batch documented data-quality exclusion observation count drifted")
    if diagnostics["backfilled_after_documented_exclusion_observation_count"] != 1:
        raise ValueError("batch backfill observation count drifted")
    return universes, diagnostics


# --- fundamental factor inputs (PIT) ------------------------------------------------------------

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


def average_total_assets(
    store: base.audit.PayloadStore,
    symbol: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> tuple[float | None, float | None]:
    """Returns (latest_total_assets, average_of_two_most_recent_total_assets)."""
    rows = store.records(base.call_id_for("balancesheet", symbol))
    recent = base.select_recent_pit_rows(
        rows,
        table_id="balancesheet",
        as_of=as_of,
        restatement_exclusions=restatement_exclusions,
        limit=TTM_ROLLOVER_PERIOD_LIMIT,
    )
    by_period: dict[str, float] = {}
    for row in recent:
        end_date = base.normalize_yyyymmdd(row.get("end_date"))
        value = base.numeric(row.get("total_assets"))
        if end_date and value is not None:
            by_period[end_date] = value
    if not by_period:
        return None, None
    ordered = [by_period[key] for key in sorted(by_period.keys(), reverse=True)]
    latest = ordered[0]
    avg = mean(ordered[:2]) if len(ordered) >= 2 else latest
    return latest, avg


def year_over_year_total_assets_growth(
    store: base.audit.PayloadStore,
    symbol: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> float | None:
    rows = store.records(base.call_id_for("balancesheet", symbol))
    recent = base.select_recent_pit_rows(
        rows,
        table_id="balancesheet",
        as_of=as_of,
        restatement_exclusions=restatement_exclusions,
        limit=TTM_ROLLOVER_PERIOD_LIMIT,
    )
    by_period: dict[str, float] = {}
    for row in recent:
        end_date = base.normalize_yyyymmdd(row.get("end_date"))
        value = base.numeric(row.get("total_assets"))
        if end_date and value is not None and value != 0:
            by_period[end_date] = value
    if not by_period:
        return None
    latest_end = max(by_period)
    suffix = latest_end[4:]
    year = int(latest_end[:4])
    prior = by_period.get(f"{year - 1}{suffix}")
    if prior is None or prior == 0:
        return None
    return (by_period[latest_end] / prior) - 1.0


# --- price factor inputs (PIT trailing windows) -------------------------------------------------

def daily_return_series(price_rows: dict[str, dict[str, float]]) -> tuple[list[str], list[float]]:
    """Adjusted-close daily simple returns, ascending by date."""
    dates = sorted(price_rows)
    rets_dates: list[str] = []
    rets: list[float] = []
    prev: float | None = None
    for date in dates:
        close = price_rows[date].get("close")
        if close is None or close <= 0:
            prev = None
            continue
        if prev is not None and prev > 0:
            rets_dates.append(date)
            rets.append((close / prev) - 1.0)
        prev = close
    return rets_dates, rets


def low_beta_score(
    stock_ret_dates: list[str],
    stock_rets: list[float],
    index_ret_by_date: dict[str, float],
    as_of: str,
    window: int,
) -> float | None:
    pairs: list[tuple[float, float]] = []
    for date, sret in zip(stock_ret_dates, stock_rets):
        if date > as_of:
            continue
        iret = index_ret_by_date.get(date)
        if iret is not None:
            pairs.append((sret, iret))
    if len(pairs) < window:
        return None
    window_pairs = pairs[-window:]
    idx_vals = [iret for _sret, iret in window_pairs]
    idx_mean = mean(idx_vals)
    idx_var = sum((iret - idx_mean) ** 2 for iret in idx_vals)
    if idx_var <= 0:
        return None
    stock_mean = mean(sret for sret, _iret in window_pairs)
    cov = sum((sret - stock_mean) * (iret - idx_mean) for sret, iret in window_pairs)
    beta = cov / idx_var
    return -beta


def low_max_score(stock_ret_dates: list[str], stock_rets: list[float], as_of: str, window: int) -> float | None:
    window_rets = [ret for date, ret in zip(stock_ret_dates, stock_rets) if date <= as_of][-window:]
    if len(window_rets) < window:
        return None
    return -max(window_rets)


def momentum_12_1_score(
    price_rows: dict[str, dict[str, float]],
    trade_dates: list[str],
    as_of: str,
    start_days_ago: int,
    end_days_ago: int,
) -> float | None:
    pit_dates = [date for date in trade_dates if date <= as_of]
    if len(pit_dates) <= start_days_ago:
        return None
    end_date = pit_dates[-1 - end_days_ago]
    start_date = pit_dates[-1 - start_days_ago]
    start_close = price_rows.get(start_date, {}).get("close")
    end_close = price_rows.get(end_date, {}).get("close")
    if start_close is None or end_close is None or start_close <= 0 or end_close <= 0:
        return None
    return (end_close / start_close) - 1.0


# Per-factor raw-input outcome buckets reported in factor_input_coverage (R-BATCH-RUNNER-DIAGNOSTIC-AUDIT).
INPUT_OUTCOMES = ["available", "missing_input", "non_positive", "insufficient_ttm", "insufficient_window"]


def _input_key(factor: str, outcome: str) -> str:
    return f"input::{factor}::{outcome}"


def batch_factor_values(
    *,
    store: base.audit.PayloadStore,
    symbol: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
    circ_mv: float | None,
    price_rows: dict[str, dict[str, float]],
    index_ret_by_date: dict[str, float],
    trade_dates: list[str],
) -> tuple[dict[str, float], dict[str, int]]:
    """Compute all nine frozen factors for one name as of one date. Cross-sectional percentiles are used
    downstream so circ_mv unit scale is rank-invariant. Returns (values, status) where status carries a
    per-factor raw-input outcome counter (available / missing_input / non_positive / insufficient_ttm /
    insufficient_window) used to build the factor_input_coverage audit section."""
    values: dict[str, float] = {}
    status: dict[str, int] = defaultdict(int)

    def record(factor: str, outcome: str) -> None:
        status[_input_key(factor, outcome)] += 1

    if circ_mv is None or circ_mv <= 0:
        status["no_circ_mv_observation_count"] += 1
        for factor in BATCH_FACTORS:
            record(factor, "missing_input")
        return values, status

    book_equity = latest_pit_stock_value(store, symbol, as_of, restatement_exclusions, "balancesheet", "total_hldr_eqy_exc_min_int")
    if book_equity is None:
        record("book_to_circ_mv", "missing_input")
    elif book_equity <= 0:
        record("book_to_circ_mv", "non_positive")
    else:
        values["book_to_circ_mv"] = book_equity / circ_mv
        record("book_to_circ_mv", "available")

    ttm_cfo = ttm_rollover(pit_period_values(store, symbol, as_of, restatement_exclusions, "cashflow", "n_cashflow_act"))
    if ttm_cfo is None:
        record("cash_flow_to_circ_mv", "insufficient_ttm")
    else:
        values["cash_flow_to_circ_mv"] = ttm_cfo / circ_mv
        record("cash_flow_to_circ_mv", "available")

    ttm_revenue = ttm_rollover(pit_period_values(store, symbol, as_of, restatement_exclusions, "income", "revenue"))
    if ttm_revenue is None:
        record("sales_to_circ_mv", "insufficient_ttm")
    elif ttm_revenue <= 0:
        record("sales_to_circ_mv", "non_positive")
    else:
        values["sales_to_circ_mv"] = ttm_revenue / circ_mv
        record("sales_to_circ_mv", "available")

    ttm_ni = ttm_rollover(pit_period_values(store, symbol, as_of, restatement_exclusions, "income", "n_income_attr_p"))
    _latest_assets, avg_assets = average_total_assets(store, symbol, as_of, restatement_exclusions)
    if avg_assets is None or avg_assets <= 0:
        record("low_accruals", "missing_input")
        record("roa_ttm", "missing_input")
    else:
        if ttm_ni is not None and ttm_cfo is not None:
            values["low_accruals"] = -((ttm_ni - ttm_cfo) / avg_assets)
            record("low_accruals", "available")
        else:
            record("low_accruals", "insufficient_ttm")
        if ttm_ni is not None:
            values["roa_ttm"] = ttm_ni / avg_assets
            record("roa_ttm", "available")
        else:
            record("roa_ttm", "insufficient_ttm")

    asset_growth = year_over_year_total_assets_growth(store, symbol, as_of, restatement_exclusions)
    if asset_growth is None:
        record("low_asset_growth", "missing_input")
    else:
        values["low_asset_growth"] = -asset_growth
        record("low_asset_growth", "available")

    stock_ret_dates, stock_rets = daily_return_series(price_rows)
    beta = low_beta_score(stock_ret_dates, stock_rets, index_ret_by_date, as_of, LOW_BETA_TRAILING_DAYS)
    if beta is None:
        record("low_beta", "insufficient_window")
    else:
        values["low_beta"] = beta
        record("low_beta", "available")
    mx = low_max_score(stock_ret_dates, stock_rets, as_of, LOW_MAX_TRAILING_DAYS)
    if mx is None:
        record("low_max", "insufficient_window")
    else:
        values["low_max"] = mx
        record("low_max", "available")
    mom = momentum_12_1_score(
        price_rows, trade_dates, as_of, MOMENTUM_FORMATION_START_DAYS_AGO, MOMENTUM_FORMATION_END_DAYS_AGO
    )
    if mom is None:
        record("momentum_12_1", "insufficient_window")
    else:
        values["momentum_12_1"] = mom
        record("momentum_12_1", "available")

    return values, status


# --- neutralization scoring (identical machinery for every factor) ------------------------------

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


def add_marginal_industry_size_neutral_scores(items: list[dict[str, Any]], factors: list[str]) -> dict[str, int]:
    coverage = {f"{family}_industry_size_neutral_available_observation_count": 0 for family in factors}
    for item in items:
        for family in factors:
            industry_score = item.get(f"{family}__industry_neutral")
            size_score = item.get(f"{family}__size_neutral")
            if industry_score is not None and size_score is not None:
                item[f"{family}__industry_size_neutral"] = (float(industry_score) + float(size_score)) / 2.0
                coverage[f"{family}_industry_size_neutral_available_observation_count"] += 1
    return coverage


def add_composite_scores(items: list[dict[str, Any]]) -> int:
    """The composite primary score IS the family-equal-weight blend of each name's per-factor
    industry_size_neutral percentile scores (per the frozen prereg construction): for each family
    present, average that family's factors' already-neutral isn percentiles, then average across
    families. The blend is therefore already industry-and-size-neutral and is NOT re-neutralized;
    it is written directly to both COMPOSITE_ID (the raw value, used for size-coverage counting) and
    COMPOSITE_ID__industry_size_neutral (the score field the composite primary/diagnostic cells read).
    Only names with at least one family scored receive a composite score."""
    family_to_factors: dict[str, list[str]] = defaultdict(list)
    for factor, family in FACTOR_FAMILIES.items():
        family_to_factors[family].append(factor)
    available = 0
    for item in items:
        family_means: list[float] = []
        for family, factors in family_to_factors.items():
            scores = [
                float(item[f"{factor}__industry_size_neutral"])
                for factor in factors
                if item.get(f"{factor}__industry_size_neutral") is not None
            ]
            if scores:
                family_means.append(mean(scores))
        if family_means:
            blend = mean(family_means)
            item[COMPOSITE_ID] = blend
            item[f"{COMPOSITE_ID}__industry_size_neutral"] = blend
            available += 1
    return available


# --- cohort formation -------------------------------------------------------------------------

def _new_diagnostics() -> dict[str, Any]:
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
        "no_circ_mv_observation_count": 0,
        "return_exit_scheduled_count": 0,
        "return_exit_terminal_last_trade_count": 0,
        "return_exit_next_available_count": 0,
        "return_exit_missing_non_terminal_count": 0,
        "missing_signal_rows": 0,
        "missing_return_rows": 0,
    }
    for factor in ALL_FACTORS:
        diagnostics[f"{factor}_industry_size_neutral_available_observation_count"] = 0
    return diagnostics


def monthly_cohort_rows(
    *,
    store: base.audit.PayloadStore,
    context: base.SignalContext,
    large_cap_universes: dict[str, list[LargeCapMember]],
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, float]]], dict[str, Any], dict[str, Any]]:
    industry_records = base.load_industry_records(store)
    index_prices = {name: base.index_total_return_close_rows(store, code) for name, code in BENCHMARKS.items()}
    csi300_ret_dates, csi300_rets = daily_return_series(index_prices[PRIMARY_BENCHMARK])
    index_ret_by_date = dict(zip(csi300_ret_dates, csi300_rets))
    stock_price_cache: dict[str, dict[str, dict[str, float]]] = {}
    rows: list[dict[str, Any]] = []
    diagnostics = _new_diagnostics()
    industry_neutral_excluded_symbols: set[str] = set()
    selection_time_name_vetoed_symbols: set[str] = set()
    # Per-factor size-coverage tracking (R-BATCH-RUNNER-SIZE-COVERAGE) + raw-input outcome accumulation
    # (R-BATCH-RUNNER-DIAGNOSTIC-AUDIT).
    no_observation_months: dict[str, list[str]] = defaultdict(list)
    incomplete_size_coverage_months: dict[str, list[str]] = defaultdict(list)
    observation_month_count: dict[str, int] = defaultdict(int)
    input_status: dict[str, int] = defaultdict(int)

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
            if symbol not in stock_price_cache:
                stock_price_cache[symbol] = base.stock_total_return_close_rows(store, symbol)
            values, status = batch_factor_values(
                store=store,
                symbol=symbol,
                as_of=as_of,
                restatement_exclusions=restatement_exclusions,
                circ_mv=member.market_cap,
                price_rows=stock_price_cache[symbol],
                index_ret_by_date=index_ret_by_date,
                trade_dates=context.trade_dates,
            )
            for key, count in status.items():
                if key.startswith("input::"):
                    input_status[key] += count
                else:
                    diagnostics[key] = diagnostics.get(key, 0) + count
            if not any(factor in values for factor in BATCH_FACTORS):
                diagnostics["missing_signal_rows"] += 1
                continue
            l2, l1, industry_source, industry_excluded = base.industry_context_for_symbol(
                industry_records, context, symbol, as_of
            )
            if industry_excluded:
                diagnostics["industry_neutral_excluded_observation_count"] += 1
                industry_neutral_excluded_symbols.add(symbol)
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

        for family in BATCH_FACTORS:
            base.percentile_scores(scored, family, f"{family}__non_neutral")
            base.add_industry_neutral_scores(scored, family)
            add_size_neutral_scores(scored, family)
        add_marginal_industry_size_neutral_scores(scored, BATCH_FACTORS)
        # The composite primary score IS the family-equal-weight blend of already-neutral percentiles
        # (set directly by add_composite_scores); it is NOT re-neutralized.
        add_composite_scores(scored)

        for factor in ALL_FACTORS:
            diagnostics[f"{factor}_industry_size_neutral_available_observation_count"] += sum(
                1 for item in scored if item.get(f"{factor}__industry_size_neutral") is not None
            )
            # Per-factor / per-as_of market-cap-quintile coverage of the RAW factor observations. A month
            # whose actual observations are absent in any quintile (or empty) cannot form a clean
            # size-neutral primary cohort and is excluded from this factor's size-dependent cohorts.
            bucket_counts = {bucket: 0 for bucket in SIZE_BUCKETS}
            for item in scored:
                if item.get(factor) is None:
                    continue
                bucket = item.get("size_bucket")
                if bucket in bucket_counts:
                    bucket_counts[str(bucket)] += 1
            total = sum(bucket_counts.values())
            if total == 0:
                no_observation_months[factor].append(as_of)
            else:
                observation_month_count[factor] += 1
                if min(bucket_counts.values()) < MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY:
                    incomplete_size_coverage_months[factor].append(as_of)

        for item in scored:
            symbol = item["symbol"]
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
                row.update({"horizon": horizon, "entry_date": entry_date, "exit_date": exit_date, "stock_return_net": stock_ret})
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

    excluded_months_by_factor = {
        factor: sorted(set(no_observation_months[factor]) | set(incomplete_size_coverage_months[factor]))
        for factor in ALL_FACTORS
    }
    input_coverage_by_factor = {
        factor: {outcome: input_status.get(_input_key(factor, outcome), 0) for outcome in INPUT_OUTCOMES}
        for factor in BATCH_FACTORS
    }
    coverage = {
        "excluded_months_by_factor": excluded_months_by_factor,
        "no_observation_months_by_factor": {factor: sorted(no_observation_months[factor]) for factor in ALL_FACTORS},
        "incomplete_size_coverage_months_by_factor": {
            factor: sorted(incomplete_size_coverage_months[factor]) for factor in ALL_FACTORS
        },
        "observation_month_count_by_factor": {factor: observation_month_count[factor] for factor in ALL_FACTORS},
        "input_coverage_by_factor": input_coverage_by_factor,
    }
    return rows, stock_price_cache, diagnostics, coverage


# --- result cells -----------------------------------------------------------------------------

def result_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for factor in BATCH_FACTORS:
        specs.append({"signal_id": factor, "view": PRIMARY_VIEW, "weighting": "equal_weight", "horizon_trading_days": PRIMARY_HORIZON, "benchmark": PRIMARY_BENCHMARK})
        specs.append({"signal_id": factor, "view": PRIMARY_VIEW, "weighting": "equal_weight", "horizon_trading_days": DIAGNOSTIC_HORIZON, "benchmark": PRIMARY_BENCHMARK})
        specs.append({"signal_id": factor, "view": PRIMARY_VIEW, "weighting": "equal_weight", "horizon_trading_days": PRIMARY_HORIZON, "benchmark": SECONDARY_BENCHMARK})
        specs.append({"signal_id": factor, "view": "non_neutral", "weighting": "equal_weight", "horizon_trading_days": PRIMARY_HORIZON, "benchmark": PRIMARY_BENCHMARK})
        specs.append({"signal_id": factor, "view": PRIMARY_VIEW, "weighting": "cap_weighted", "horizon_trading_days": PRIMARY_HORIZON, "benchmark": PRIMARY_BENCHMARK})
    for horizon, benchmark in [(PRIMARY_HORIZON, PRIMARY_BENCHMARK), (DIAGNOSTIC_HORIZON, PRIMARY_BENCHMARK), (PRIMARY_HORIZON, SECONDARY_BENCHMARK)]:
        specs.append({"signal_id": COMPOSITE_ID, "view": PRIMARY_VIEW, "weighting": "equal_weight", "horizon_trading_days": horizon, "benchmark": benchmark})
    return specs


def cell_id_for(spec: dict[str, Any]) -> str:
    return f"{spec['signal_id']}_{spec['view']}_{spec['weighting']}_{spec['horizon_trading_days']}d_{spec['benchmark']}"


def primary_cell_id_for(factor: str) -> str:
    return cell_id_for(
        {"signal_id": factor, "view": PRIMARY_VIEW, "weighting": "equal_weight", "horizon_trading_days": PRIMARY_HORIZON, "benchmark": PRIMARY_BENCHMARK}
    )


PRIMARY_CELL_IDS = {factor: primary_cell_id_for(factor) for factor in ALL_FACTORS}
RESULT_CELL_COUNT = len(result_specs())


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
        # Form a top-fraction cohort only when at least MIN_TOP_COUNT names are scored that month for
        # this factor/view (early/thin months otherwise add noise). Names are only scored when their
        # market-cap quintile had >= 50 members, so scored names already come from healthy buckets.
        if len(cohort) < MIN_TOP_COUNT:
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
    excluded_months_by_factor: dict[str, set[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, list[str]]]]:
    excluded_months_by_factor = {k: set(v) for k, v in (excluded_months_by_factor or {}).items()}
    results: list[dict[str, Any]] = []
    rows_by_horizon_as_of: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    as_ofs_by_horizon: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        horizon = row.get("horizon")
        as_of = row.get("as_of")
        if isinstance(horizon, int) and isinstance(as_of, str):
            rows_by_horizon_as_of[(horizon, as_of)].append(row)
            as_ofs_by_horizon[horizon].add(as_of)

    primary_series_by_factor: dict[str, dict[str, Any]] = {}
    primary_selections_by_factor: dict[str, dict[str, list[str]]] = {}

    for spec in result_specs():
        signal_id = str(spec["signal_id"])
        view = str(spec["view"])
        weighting = str(spec["weighting"])
        horizon = int(spec["horizon_trading_days"])
        benchmark_name = str(spec["benchmark"])
        score_field = f"{signal_id}__{view}"
        excess_field = f"excess_{benchmark_name}"
        # The size-coverage gate excludes a factor's thin/absent-quintile months from its size-dependent
        # views (industry_size_neutral, size_neutral). The non_neutral view does not use size buckets.
        view_excluded = (
            excluded_months_by_factor.get(signal_id, set())
            if view in ("industry_size_neutral", "size_neutral")
            else frozenset()
        )
        agg = cohort_excess_by_as_of(
            rows_by_horizon_as_of, as_ofs_by_horizon,
            score_field=score_field, excess_field=excess_field, horizon=horizon, weighting=weighting,
            excluded_as_ofs=view_excluded,
        )
        cohort_returns = agg["cohort_returns"]
        selected_symbols = agg["selected_symbols"]
        yearly = agg["yearly_positive_return_contribution"]
        monthly_top_counts = agg["monthly_top_counts"]

        if len(cohort_returns) >= 2:
            avg = mean(cohort_returns)
            sd = pstdev(cohort_returns)
            t_stat, _se, hac_lag = base.newey_west_hac_t_stat(cohort_returns, horizon=horizon)
            p_value = base.normal_two_sided_p_value(t_stat)
        elif cohort_returns:
            avg, sd, t_stat, hac_lag, p_value = cohort_returns[0], 0.0, 0.0, 0, None
        else:
            avg = sd = t_stat = p_value = None
            hac_lag = 0

        total_selections = sum(selected_symbols.values())
        top_symbol_share = max(selected_symbols.values()) / total_selections if total_selections else None
        total_positive = sum(yearly.values())
        single_year_share = max(yearly.values()) / total_positive if total_positive > 0 else None
        diag_drawdown = base.max_drawdown(cohort_returns) if cohort_returns else None
        min_top_count = min(monthly_top_counts) if monthly_top_counts else 0
        is_primary = (
            view == PRIMARY_VIEW and weighting == "equal_weight"
            and horizon == PRIMARY_HORIZON and benchmark_name == PRIMARY_BENCHMARK
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
                "hac_lag_months": hac_lag,
                "p_value": None if p_value is None else round(p_value, 10),
                "minimum_monthly_top_count": min_top_count,
                "positive_month_count": len([value for value in cohort_returns if value > 0]),
                "worst_monthly_cohort_excess": round(min(cohort_returns), 10) if cohort_returns else None,
                "best_monthly_cohort_excess": round(max(cohort_returns), 10) if cohort_returns else None,
                "diagnostic_max_drawdown_on_monthly_excess": None if diag_drawdown is None else round(diag_drawdown, 10),
                "top_symbol_selection_share": None if top_symbol_share is None else round(top_symbol_share, 10),
                "max_single_year_positive_return_share": None if single_year_share is None else round(single_year_share, 10),
                "passes_minimum_monthly_cohorts": len(cohort_returns) >= MIN_MONTHLY_COHORTS,
                "passes_minimum_top_count": min_top_count >= MIN_TOP_COUNT,
                "passes_name_concentration_guard": top_symbol_share is not None and top_symbol_share <= MAX_TOP_SYMBOL_SELECTION_SHARE,
                "passes_single_year_concentration_guard": single_year_share is not None and single_year_share <= MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
            }
        )
        if is_primary:
            primary_series_by_factor[signal_id] = {"cohort_returns": cohort_returns, "cohort_as_ofs": agg["cohort_as_ofs"]}
            primary_selections_by_factor[signal_id] = agg["selections_by_as_of"]

    return results, primary_series_by_factor, primary_selections_by_factor


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
    return {"cohort_count": len(values), "mean_net_excess": round(avg, 10), "hac_t_stat": None if t_stat is None else round(t_stat, 10), "hac_lag_months": lag}


def sub_period_robustness(primary_series: dict[str, Any] | None) -> dict[str, Any]:
    returns = (primary_series or {}).get("cohort_returns") or []
    if len(returns) < 2:
        return {
            "valid_cohort_count": len(returns), "split_index": 0,
            "first_half": half_hac_stats([], horizon=PRIMARY_HORIZON),
            "second_half": half_hac_stats([], horizon=PRIMARY_HORIZON),
            "both_halves_mean_excess_positive": False,
        }
    split_index = len(returns) // 2
    first_stats = half_hac_stats(returns[:split_index], horizon=PRIMARY_HORIZON)
    second_stats = half_hac_stats(returns[split_index:], horizon=PRIMARY_HORIZON)
    both_positive = (
        first_stats["mean_net_excess"] is not None and second_stats["mean_net_excess"] is not None
        and first_stats["mean_net_excess"] > 0 and second_stats["mean_net_excess"] > 0
    )
    return {
        "valid_cohort_count": len(returns), "split_index": split_index,
        "first_half": first_stats, "second_half": second_stats,
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
            tranches.append({"entry_date": entry_date, "scheduled_exit": scheduled_exit, "entry_csi": entry_csi, "basket": basket})

    strategy_nav: list[float] = []
    relative_nav: list[float] = []
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
        if benchmark_level > 0:
            relative_nav.append(strategy_level / benchmark_level)
    return {
        "tranche_count": len(tranches),
        "relative_nav_checkpoint_count": len(relative_nav),
        "relative_nav_max_drawdown": None if not relative_nav else round(max_drawdown_on_levels(relative_nav), 10),
        "absolute_strategy_nav_max_drawdown": None if not strategy_nav else round(max_drawdown_on_levels(strategy_nav), 10),
    }


# --- batch decision (Benjamini-Hochberg FDR over the ten primary cells) ------------------------

def benjamini_hochberg(pvalues_by_factor: dict[str, float | None], q: float) -> tuple[set[str], float | None]:
    full = [(factor, 1.0 if pvalues_by_factor.get(factor) is None else float(pvalues_by_factor[factor])) for factor in pvalues_by_factor]
    m = len(full)
    if m == 0:
        return set(), None
    ordered = sorted(full, key=lambda item: item[1])
    k_max = 0
    for k, (_factor, p_value) in enumerate(ordered, start=1):
        if p_value <= (k / m) * q:
            k_max = k
    if k_max == 0:
        return set(), None
    cutoff = ordered[k_max - 1][1]
    survivors = {factor for factor, p_value in full if p_value <= cutoff}
    return survivors, cutoff


def per_factor_gates_pass(cell: dict[str, Any], sub_period: dict[str, Any]) -> bool:
    return (
        cell.get("passes_minimum_monthly_cohorts") is True
        and cell.get("passes_minimum_top_count") is True
        and (cell.get("mean_monthly_cohort_net_excess") or 0) > 0
        and cell.get("passes_name_concentration_guard") is True
        and cell.get("passes_single_year_concentration_guard") is True
        and sub_period.get("both_halves_mean_excess_positive") is True
    )


def batch_decision(
    results: list[dict[str, Any]],
    sub_period_by_factor: dict[str, dict[str, Any]],
    risk_gate_by_factor: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    primary_by_factor: dict[str, dict[str, Any]] = {}
    for cell in results:
        if cell.get("diagnostic_role") == "primary_decision_cell":
            primary_by_factor[str(cell["signal_id"])] = cell
    if set(primary_by_factor) != set(PRIMARY_HYPOTHESES):
        raise ValueError("batch result set is missing one or more primary cells")

    pvalues = {factor: primary_by_factor[factor].get("p_value") for factor in PRIMARY_HYPOTHESES}
    survivors_q010, threshold_q010 = benjamini_hochberg(pvalues, Q_RESEARCH_CLUE_GATE)
    survivors_q005, threshold_q005 = benjamini_hochberg(pvalues, Q_STRICT_DIAGNOSTIC)

    factor_results: list[dict[str, Any]] = []
    clue_factor_ids: list[str] = []
    tradeable_factor_ids: list[str] = []
    for factor in PRIMARY_HYPOTHESES:
        cell = primary_by_factor[factor]
        sub_period = sub_period_by_factor.get(factor) or sub_period_robustness(None)
        gates_pass = per_factor_gates_pass(cell, sub_period)
        is_clue = factor in survivors_q010 and gates_pass
        risk = risk_gate_by_factor.get(factor) or {}
        relative_drawdown = risk.get("relative_nav_max_drawdown")
        drawdown_gate_passed = is_clue and relative_drawdown is not None and relative_drawdown >= MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN
        is_tradeable = bool(is_clue and drawdown_gate_passed)
        if is_clue:
            clue_factor_ids.append(factor)
        if is_tradeable:
            tradeable_factor_ids.append(factor)
        factor_results.append(
            {
                "factor_id": factor,
                "family": FACTOR_FAMILIES.get(factor, "composite"),
                "primary_cell_id": cell["cell_id"],
                "monthly_cohort_count": cell["monthly_cohort_count"],
                "mean_monthly_cohort_net_excess": cell["mean_monthly_cohort_net_excess"],
                "monthly_clustered_t_stat": cell["monthly_clustered_t_stat"],
                "p_value": cell["p_value"],
                "positive_month_count": cell["positive_month_count"],
                "top_symbol_selection_share": cell["top_symbol_selection_share"],
                "max_single_year_positive_return_share": cell["max_single_year_positive_return_share"],
                "passes_minimum_monthly_cohorts": cell["passes_minimum_monthly_cohorts"],
                "passes_minimum_top_count": cell["passes_minimum_top_count"],
                "passes_name_concentration_guard": cell["passes_name_concentration_guard"],
                "passes_single_year_concentration_guard": cell["passes_single_year_concentration_guard"],
                "sub_period_first_half_mean_net_excess": sub_period["first_half"]["mean_net_excess"],
                "sub_period_second_half_mean_net_excess": sub_period["second_half"]["mean_net_excess"],
                "sub_period_both_halves_mean_excess_positive": sub_period["both_halves_mean_excess_positive"],
                "survives_fdr_q_research_clue": factor in survivors_q010,
                "survives_fdr_q_strict": factor in survivors_q005,
                "passes_per_factor_robustness_gates": gates_pass,
                "is_statistical_alpha_clue": is_clue,
                "relative_nav_max_drawdown": relative_drawdown if is_clue else None,
                "relative_nav_drawdown_gate_passed": drawdown_gate_passed,
                "is_tradeable_candidate": is_tradeable,
            }
        )

    is_dry = not clue_factor_ids
    verdict = DRY_VERDICT if is_dry else CLUE_VERDICT
    if is_dry:
        plain = (
            "No factor in the frozen batch survived Benjamini-Hochberg FDR at q=0.10 with the per-factor "
            "robustness gates, so the batch is dry under the frozen rules. Per the stopping rule, downgrade "
            "A-share large-cap long in-sample alpha to forward-live / a different market-or-data path; do not "
            "rescue with new factor definitions."
        )
    else:
        plain = (
            f"{len(clue_factor_ids)} factor(s) survived BH-FDR at q=0.10 with the robustness gates "
            f"({', '.join(clue_factor_ids)}); {len(tradeable_factor_ids)} also passed the -15% relative-NAV "
            "tradeable gate. These are research-only clues and route to forward-live validation, not production / "
            "ship-gate / full-size; FDR cannot uncount the five prior spent singletons."
        )
    decision = {
        "research_verdict": verdict,
        "is_dry_batch": is_dry,
        "m_total_hypotheses": M_TOTAL_HYPOTHESES,
        "fdr_method": "benjamini_hochberg",
        "q_research_clue_gate": Q_RESEARCH_CLUE_GATE,
        "q_strict_diagnostic": Q_STRICT_DIAGNOSTIC,
        "bh_threshold_p_at_q_research_clue": None if threshold_q010 is None else round(threshold_q010, 10),
        "bh_threshold_p_at_q_strict": None if threshold_q005 is None else round(threshold_q005, 10),
        "statistical_alpha_clue_count": len(clue_factor_ids),
        "tradeable_candidate_count": len(tradeable_factor_ids),
        "surviving_clue_factor_ids": clue_factor_ids,
        "tradeable_candidate_factor_ids": tradeable_factor_ids,
        "diagnostics_can_rescue_primary_failure": False,
        "drop_losing_factors_then_re_fdr_executed": False,
        "multiple_testing_cannot_uncount_prior_spent_singletons": True,
        "alpha_found_for_production": False,
        "ship_gate_evidence": False,
        "full_size_allowed": False,
        "plain_result": plain,
        "next_action": (
            "If dry, follow the stopping rule (downgrade / forward-live / pivot), do not rescue with new "
            "definitions, thresholds, windows, q, or composite weights, and do not drop losing factors and re-run "
            "FDR. Any surviving clue is research-only until forward-live ship-gate evidence exists, and needs a new "
            "reviewed preregistration and ledger for any follow-up."
        ),
    }
    return decision, factor_results


def validate_pipeline_result_sanity(
    rows: list[dict[str, Any]],
    results: list[dict[str, Any]],
    primary_series_by_factor: dict[str, dict[str, Any]],
    excluded_months_by_factor: dict[str, set[str]] | None = None,
) -> None:
    if not rows:
        raise ValueError("batch signal-search pipeline failure: no evaluated return rows; do not emit a verdict or spend ledger")
    if len(results) != RESULT_CELL_COUNT:
        raise ValueError(f"batch signal-search pipeline failure: expected {RESULT_CELL_COUNT} result cells, got {len(results)}")
    primary_cells = [item for item in results if item.get("diagnostic_role") == "primary_decision_cell"]
    primary_signal_ids = {str(cell["signal_id"]) for cell in primary_cells}
    if primary_signal_ids != set(PRIMARY_HYPOTHESES):
        raise ValueError("batch signal-search pipeline failure: primary cells do not cover exactly the ten hypotheses")
    for cell in primary_cells:
        if cell["cell_id"] != PRIMARY_CELL_IDS[str(cell["signal_id"])]:
            raise ValueError("batch signal-search pipeline failure: a primary cell id drifted")
    if set(primary_series_by_factor) != set(PRIMARY_HYPOTHESES):
        raise ValueError("batch signal-search pipeline failure: primary series do not cover the ten hypotheses")
    # No size-coverage-excluded month may leak into any factor's primary (industry_size_neutral) cohort.
    excluded_months_by_factor = excluded_months_by_factor or {}
    for factor in PRIMARY_HYPOTHESES:
        excluded = set(excluded_months_by_factor.get(factor, set()))
        cohort_months = set((primary_series_by_factor.get(factor) or {}).get("cohort_as_ofs") or [])
        if excluded & cohort_months:
            raise ValueError(
                f"batch signal-search pipeline failure: a size-coverage-excluded month leaked into the "
                f"primary cohort for {factor}"
            )


def validate_summary_internal_consistency(summary: dict[str, Any]) -> None:
    cells = summary.get("result_cells") or []
    if len(cells) != RESULT_CELL_COUNT:
        raise ValueError("batch summary result_cell_count mismatch")
    primary_cells = [cell for cell in cells if cell.get("diagnostic_role") == "primary_decision_cell"]
    if {str(cell["signal_id"]) for cell in primary_cells} != set(PRIMARY_HYPOTHESES):
        raise ValueError("batch summary primary cells must cover exactly the ten hypotheses")
    for cell in cells:
        expected = cell_id_for(
            {"signal_id": cell.get("signal_id"), "view": cell.get("view"), "weighting": cell.get("weighting"),
             "horizon_trading_days": cell.get("horizon_trading_days"), "benchmark": cell.get("benchmark")}
        )
        if cell.get("cell_id") != expected:
            raise ValueError(f"batch summary cell_id/metadata mismatch: {cell.get('cell_id')} vs {expected}")

    factor_results = summary.get("factor_results") or []
    if {str(item["factor_id"]) for item in factor_results} != set(PRIMARY_HYPOTHESES):
        raise ValueError("batch summary factor_results must cover exactly the ten hypotheses")
    clue_ids = []
    tradeable_ids = []
    for item in factor_results:
        clue = bool(item.get("is_statistical_alpha_clue"))
        tradeable = bool(item.get("is_tradeable_candidate"))
        if clue is not (bool(item.get("survives_fdr_q_research_clue")) and bool(item.get("passes_per_factor_robustness_gates"))):
            raise ValueError(f"batch summary clue flag inconsistent for {item.get('factor_id')}")
        if tradeable is not (clue and bool(item.get("relative_nav_drawdown_gate_passed"))):
            raise ValueError(f"batch summary tradeable flag inconsistent for {item.get('factor_id')}")
        if clue:
            clue_ids.append(str(item["factor_id"]))
        if tradeable:
            tradeable_ids.append(str(item["factor_id"]))

    decision = summary.get("decision") or {}
    if decision.get("statistical_alpha_clue_count") != len(clue_ids):
        raise ValueError("batch summary statistical_alpha_clue_count mismatch")
    if decision.get("tradeable_candidate_count") != len(tradeable_ids):
        raise ValueError("batch summary tradeable_candidate_count mismatch")
    if sorted(decision.get("surviving_clue_factor_ids") or []) != sorted(clue_ids):
        raise ValueError("batch summary surviving_clue_factor_ids mismatch")
    if sorted(decision.get("tradeable_candidate_factor_ids") or []) != sorted(tradeable_ids):
        raise ValueError("batch summary tradeable_candidate_factor_ids mismatch")
    if decision.get("is_dry_batch") is not (len(clue_ids) == 0):
        raise ValueError("batch summary is_dry_batch contradicts the clue count")
    expected_verdict = DRY_VERDICT if not clue_ids else CLUE_VERDICT
    if decision.get("research_verdict") != expected_verdict:
        raise ValueError("batch summary research_verdict contradicts the clue count")
    diagnostics = summary.get("execution_diagnostics") or {}
    if diagnostics.get("result_cell_count") != len(cells):
        raise ValueError("batch summary execution_diagnostics.result_cell_count mismatch")

    # Size-coverage audit covers all ten hypotheses; each count matches its list length.
    coverage_rows = (summary.get("size_coverage_audit") or {}).get("by_factor") or []
    if {str(row["factor_id"]) for row in coverage_rows} != set(PRIMARY_HYPOTHESES):
        raise ValueError("batch summary size_coverage_audit must cover exactly the ten hypotheses")
    for row in coverage_rows:
        if row.get("no_observation_month_count") != len(row.get("no_observation_months") or []):
            raise ValueError(f"batch summary no_observation_month_count mismatch for {row.get('factor_id')}")
        if row.get("incomplete_size_coverage_month_count") != len(row.get("incomplete_size_coverage_months") or []):
            raise ValueError(f"batch summary incomplete_size_coverage_month_count mismatch for {row.get('factor_id')}")

    # Factor-input coverage covers exactly the nine raw factors (composite has no raw inputs).
    input_rows = (summary.get("factor_input_coverage") or {}).get("by_factor") or []
    if {str(row["factor_id"]) for row in input_rows} != set(BATCH_FACTORS):
        raise ValueError("batch summary factor_input_coverage must cover exactly the nine raw factors")

    # FDR audit table covers all ten hypotheses with unique ranks 1..m and agrees with factor_results.
    fdr_rows = (summary.get("fdr_audit") or {}).get("sorted_primary_p_values") or []
    if {str(row["factor_id"]) for row in fdr_rows} != set(PRIMARY_HYPOTHESES):
        raise ValueError("batch summary fdr_audit must cover exactly the ten hypotheses")
    if sorted(row["rank"] for row in fdr_rows) != list(range(1, len(PRIMARY_HYPOTHESES) + 1)):
        raise ValueError("batch summary fdr_audit ranks must be a permutation of 1..m")
    fdr_by_factor = {str(row["factor_id"]): row for row in fdr_rows}
    for item in factor_results:
        audit_row = fdr_by_factor[str(item["factor_id"])]
        if bool(audit_row.get("survives_fdr_q_research_clue")) is not bool(item.get("survives_fdr_q_research_clue")):
            raise ValueError(f"batch summary fdr_audit q0.10 survival disagrees with factor_results for {item.get('factor_id')}")
        if bool(audit_row.get("survives_fdr_q_strict")) is not bool(item.get("survives_fdr_q_strict")):
            raise ValueError(f"batch summary fdr_audit q0.05 survival disagrees with factor_results for {item.get('factor_id')}")


def build_fdr_audit(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Sorted Benjamini-Hochberg primary p-value / rank table (R-BATCH-RUNNER-DIAGNOSTIC-AUDIT)."""
    primary_by_factor = {str(c["signal_id"]): c for c in results if c.get("diagnostic_role") == "primary_decision_cell"}
    pvalues = {factor: primary_by_factor[factor].get("p_value") for factor in PRIMARY_HYPOTHESES}
    survivors_q010, threshold_q010 = benjamini_hochberg(pvalues, Q_RESEARCH_CLUE_GATE)
    survivors_q005, threshold_q005 = benjamini_hochberg(pvalues, Q_STRICT_DIAGNOSTIC)
    m = M_TOTAL_HYPOTHESES
    ordered = sorted(PRIMARY_HYPOTHESES, key=lambda f: (1.0 if pvalues[f] is None else float(pvalues[f]), f))
    table = []
    for rank, factor in enumerate(ordered, start=1):
        p_value = pvalues[factor]
        table.append(
            {
                "rank": rank,
                "factor_id": factor,
                "primary_cell_id": PRIMARY_CELL_IDS[factor],
                "p_value": None if p_value is None else round(float(p_value), 10),
                "bh_critical_value_at_q_research_clue": round((rank / m) * Q_RESEARCH_CLUE_GATE, 10),
                "bh_critical_value_at_q_strict": round((rank / m) * Q_STRICT_DIAGNOSTIC, 10),
                "survives_fdr_q_research_clue": factor in survivors_q010,
                "survives_fdr_q_strict": factor in survivors_q005,
            }
        )
    return {
        "m_total_hypotheses": m,
        "q_research_clue_gate": Q_RESEARCH_CLUE_GATE,
        "q_strict_diagnostic": Q_STRICT_DIAGNOSTIC,
        "bh_threshold_p_at_q_research_clue": None if threshold_q010 is None else round(threshold_q010, 10),
        "bh_threshold_p_at_q_strict": None if threshold_q005 is None else round(threshold_q005, 10),
        "sorted_primary_p_values": table,
    }


def build_size_coverage_audit(coverage: dict[str, Any], primary_series_by_factor: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Per-factor market-cap-quintile coverage audit (R-BATCH-RUNNER-SIZE-COVERAGE)."""
    by_factor = []
    for factor in ALL_FACTORS:
        no_obs = coverage["no_observation_months_by_factor"][factor]
        incomplete = coverage["incomplete_size_coverage_months_by_factor"][factor]
        excluded = coverage["excluded_months_by_factor"][factor]
        primary_months = (primary_series_by_factor.get(factor) or {}).get("cohort_as_ofs") or []
        by_factor.append(
            {
                "factor_id": factor,
                "observation_month_count": coverage["observation_month_count_by_factor"][factor],
                "no_observation_month_count": len(no_obs),
                "no_observation_months": list(no_obs),
                "incomplete_size_coverage_month_count": len(incomplete),
                "incomplete_size_coverage_months": list(incomplete),
                "size_coverage_excluded_month_count": len(excluded),
                "primary_cohort_month_count": len(primary_months),
            }
        )
    return {
        "minimum_size_bucket_count_for_primary": MIN_SIZE_BUCKET_COUNT_FOR_PRIMARY,
        "size_coverage_gate_applies_to_cohort_forming_months_only": True,
        "gate_excludes_month_from_size_dependent_views": True,
        "by_factor": by_factor,
    }


def build_factor_input_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    """Per-factor raw-input availability / exclusion counters (R-BATCH-RUNNER-DIAGNOSTIC-AUDIT)."""
    by_factor = []
    for factor in BATCH_FACTORS:
        counts = coverage["input_coverage_by_factor"][factor]
        by_factor.append(
            {
                "factor_id": factor,
                "available_count": counts["available"],
                "missing_input_count": counts["missing_input"],
                "non_positive_count": counts["non_positive"],
                "insufficient_ttm_count": counts["insufficient_ttm"],
                "insufficient_window_count": counts["insufficient_window"],
            }
        )
    return {"by_factor": by_factor}


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
    full_audit_report, store, context, restatement_exclusions, endpoint_results_count = load_full_main_board_sources(full_raw_root)
    large_cap_universes, universe_diagnostics = load_large_cap_signal_universes(
        market_cap_raw_root=market_cap_raw_root, allowed_symbols=set(context.symbols)
    )
    rows, stock_price_cache, diagnostics, coverage = monthly_cohort_rows(
        store=store, context=context, large_cap_universes=large_cap_universes, restatement_exclusions=restatement_exclusions
    )
    excluded_months_by_factor = {factor: set(months) for factor, months in coverage["excluded_months_by_factor"].items()}
    results, primary_series_by_factor, primary_selections_by_factor = summarize_results(rows, excluded_months_by_factor)
    validate_pipeline_result_sanity(rows, results, primary_series_by_factor, excluded_months_by_factor)
    sub_period_by_factor = {factor: sub_period_robustness(primary_series_by_factor.get(factor)) for factor in PRIMARY_HYPOTHESES}

    csi300_prices = base.index_total_return_close_rows(store, BENCHMARKS[PRIMARY_BENCHMARK])
    # Risk gate is computed only for factors that pass FDR + per-factor gates, but we need the clue set
    # first; do a provisional FDR pass to know which factors need the (expensive) NAV computation.
    primary_by_factor = {str(c["signal_id"]): c for c in results if c.get("diagnostic_role") == "primary_decision_cell"}
    provisional_survivors, _threshold = benjamini_hochberg(
        {f: primary_by_factor[f].get("p_value") for f in PRIMARY_HYPOTHESES}, Q_RESEARCH_CLUE_GATE
    )
    risk_gate_by_factor: dict[str, dict[str, Any]] = {}
    for factor in PRIMARY_HYPOTHESES:
        if factor in provisional_survivors and per_factor_gates_pass(primary_by_factor[factor], sub_period_by_factor[factor]):
            risk_gate_by_factor[factor] = rolling_relative_nav_drawdown(
                primary_selections=primary_selections_by_factor.get(factor) or {},
                stock_price_cache=stock_price_cache,
                csi300_prices=csi300_prices,
                trade_dates=context.trade_dates,
            )
    decision, factor_results = batch_decision(results, sub_period_by_factor, risk_gate_by_factor)
    fdr_audit = build_fdr_audit(results)
    size_coverage_audit = build_size_coverage_audit(coverage, primary_series_by_factor)
    factor_input_coverage = build_factor_input_coverage(coverage)

    return {
        "schema_name": "a_long_large_cap_batch_factor_search_signal_search_execution_summary",
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
            "reviewed_data_quality_exclusion_applied": universe_diagnostics["documented_data_quality_exclusion_observation_count"] == 1,
            "reviewed_data_quality_exclusion_backfilled": universe_diagnostics["backfilled_after_documented_exclusion_observation_count"] == 1,
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
            "factor_count": len(BATCH_FACTORS),
            "composite_count": 1,
            "total_primary_hypotheses": M_TOTAL_HYPOTHESES,
            "factor_ids": list(BATCH_FACTORS),
            "composite_id": COMPOSITE_ID,
            "primary_view": PRIMARY_VIEW,
            "primary_horizon_trading_days": PRIMARY_HORIZON,
            "diagnostic_horizons_trading_days": [DIAGNOSTIC_HORIZON],
            "primary_benchmark": PRIMARY_BENCHMARK,
            "diagnostic_benchmark": SECONDARY_BENCHMARK,
            "stock_return_basis": base.STOCK_RETURN_BASIS,
            "benchmark_return_basis": base.BENCHMARK_RETURN_BASIS,
            "round_trip_cost": base.ROUND_TRIP_COST,
            "top_fraction": TOP_FRACTION,
            "minimum_top_count_per_month": MIN_TOP_COUNT,
            "minimum_monthly_cohorts": MIN_MONTHLY_COHORTS,
            "monthly_t_stat_method": base.MONTHLY_T_STAT_METHOD,
            "hac_lag_rule": base.HAC_LAG_RULE,
            "decision_type": "batch_bh_fdr_over_primary_cells",
            "fdr_method": "benjamini_hochberg",
            "q_research_clue_gate": Q_RESEARCH_CLUE_GATE,
            "q_strict_diagnostic": Q_STRICT_DIAGNOSTIC,
            "minimum_allowed_relative_nav_drawdown": MIN_ALLOWED_RELATIVE_NAV_DRAWDOWN,
            "max_top_symbol_selection_share": MAX_TOP_SYMBOL_SELECTION_SHARE,
            "max_single_year_positive_return_share": MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
            "sub_period_split_rule": "median_split_of_valid_504d_entry_cohorts_into_two_equal_halves",
            "diagnostics_can_define_alpha": False,
            "drop_losing_factors_then_re_fdr_executed": False,
            "restatement_exclusion_required": True,
            "low_beta_trailing_days": LOW_BETA_TRAILING_DAYS,
            "low_max_trailing_days": LOW_MAX_TRAILING_DAYS,
            "momentum_formation_start_days_ago": MOMENTUM_FORMATION_START_DAYS_AGO,
            "momentum_formation_end_days_ago": MOMENTUM_FORMATION_END_DAYS_AGO,
        },
        "execution_diagnostics": {
            **diagnostics,
            "full_main_board_endpoint_results_count": endpoint_results_count,
            "evaluated_stock_return_rows": len(rows),
            "result_cell_count": len(results),
        },
        "result_cells": results,
        "factor_results": factor_results,
        "size_coverage_audit": size_coverage_audit,
        "factor_input_coverage": factor_input_coverage,
        "fdr_audit": fdr_audit,
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
            "batch_factor_proven": False,
            "fdr_uncounts_prior_singletons": False,
            "in_sample_clue_is_out_of_sample_proof": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "result_artifacts": [display_path(SUMMARY_PATH)],
        "limitations": [
            "This summary is research-only and reads already-materialized local raw data only.",
            "BH-FDR controls within-batch multiple testing but cannot uncount the five prior spent singletons; a survivor is the program-level (5+k)-th test.",
            "All denominators are circ_mv (free-float); factor ids use the *_to_circ_mv / free-float convention and are not canonical book-to-market / EV ratios.",
            "roa_ttm is a profitability proxy, not Novy-Marx gross or FF5 operating profitability (those fields are not materialized); it overlaps the falsified ROE-quality line.",
            "low_beta / low_max are low-risk-family factors correlated with the falsified low_volatility line; momentum_12_1 is expected weak in China large-cap.",
            "Statistical power is limited: 504d holds over 2018-2025 give few non-overlapping windows, so each factor's HAC t rests on a short effective sample and FDR at m=10 sets a high bar.",
            "If the batch is dry, the stopping rule applies: downgrade A-share large-cap in-sample alpha to forward-live / pivot, do not rescue with new factor definitions.",
            "A surviving clue is research-only until the unchanged project ship gate (>= 12 months forward-live) is satisfied; no production / DataHub / broker / order automation is authorized.",
        ],
    }


def ledger_status_for_decision(summary: dict[str, Any]) -> str:
    if summary["decision"]["is_dry_batch"]:
        return "spent_failed_outcome_threshold"
    return "spent_passed_research_continue_only"


def spend_ledger_after_success(*, ledger_path: Path, summary: dict[str, Any], result_ref: str, generated_at: str) -> dict[str, Any]:
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
                "No rerun, factor-definition / factor-count / trailing-window / q / composite-weight change, no "
                "dropping losing factors then re-running FDR, no horizon / benchmark / universe change, and no "
                "diagnostic rescue without a new reviewed preregistration and ledger. A dry batch triggers the "
                "stopping rule; any clue is research-only until forward-live ship-gate evidence exists."
            ),
        }
    ]
    ledger["planned_tests"] = []
    ledger["next_required_actions"] = [
        "Do not rerun or rescue this batch signal search without a new reviewed preregistration and ledger update.",
        "If the batch is dry, follow the stopping rule (downgrade A-share large-cap in-sample alpha to forward-live / pivot), not definition rescue.",
        "If any factor is a clue, route it to forward-live validation; do not treat it as production or ship-gate evidence.",
    ]
    validate_json(LEDGER_SCHEMA_PATH, ledger)
    write_json_atomic(ledger_path, ledger)
    return ledger


def write_summary_and_spend_ledger(*, summary_path: Path, summary: dict[str, Any], generated_at: str) -> None:
    if summary_path.exists():
        raise FileExistsError(f"refusing to overwrite existing batch signal-search summary: {display_path(summary_path)}")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path = summary_path.with_name(summary_path.name + ".pending")
    write_json_atomic(pending_path, summary)
    try:
        spend_ledger_after_success(ledger_path=LEDGER_PATH, summary=summary, result_ref=display_path(summary_path), generated_at=generated_at)
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
                "is_dry_batch": summary["decision"]["is_dry_batch"],
                "statistical_alpha_clue_count": summary["decision"]["statistical_alpha_clue_count"],
                "tradeable_candidate_count": summary["decision"]["tradeable_candidate_count"],
                "surviving_clue_factor_ids": summary["decision"]["surviving_clue_factor_ids"],
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

