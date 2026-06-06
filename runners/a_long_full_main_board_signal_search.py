from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_long_full_main_board_data_integrity_audit as audit


PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_signal_search_preregistration_20260604.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_signal_search_program_test_budget_ledger_20260604.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "program_test_budget_ledger.schema.json"
MATERIALIZATION_SUMMARY_PATH = ROOT / "docs" / "a_long_full_main_board_materialization_execution_summary_20260605.json"
AUDIT_REPORT_PATH = ROOT / "research" / "results" / "a_long_full_main_board_data_integrity_audit_20260605" / "audit_report.json"
RESTATEMENT_EXCLUSION_LIST_PATH = (
    ROOT / "research" / "results" / "a_long_full_main_board_data_integrity_audit_20260605" / "restatement_ambiguous_exclusions.csv"
)
BENCHMARK_ACCESS_PROBE_SUMMARY_PATH = ROOT / "docs" / "a_long_total_return_benchmark_access_probe_summary_20260606.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/full_main_board_signal_search_20260605")
RAW_ROOT = ROOT / RAW_ROOT_REL
OUTPUT_DIR = ROOT / "research" / "results" / "a_long_signal_search_20260604"
SUMMARY_PATH = OUTPUT_DIR / "execution_summary.json"
SCHEMA_PATH = ROOT / "schemas" / "a_long_signal_search_execution_summary.schema.json"

START_DATE = "20180101"
END_DATE = "20251231"
EXPECTED_ACTIVE_COUNT = 3200
EXPECTED_DELISTED_COUNT = 187
EXPECTED_UNIVERSE_COUNT = 3387
EXPECTED_NO_INDUSTRY_EXCEPTION_COUNT = 191
EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT = 1504
EXPECTED_ENDPOINT_RESULTS_COUNT = 23718
SELECTION_STATUS_CALL_ID = "namechange_2018_2025"
SELECTION_STATUS_SOURCE = "tushare_namechange_pit_history"
ALLOWED_SIGNAL_FAMILIES = [
    "profitability_quality",
    "cash_conversion",
    "balance_sheet_strength",
    "earnings_stability",
]
F_ANN_DATE_REQUIRED_TABLES = {"income", "balancesheet", "cashflow"}
ANN_DATE_ONLY_TABLES = {"fina_indicator"}
HORIZONS = [252, 504]
BENCHMARKS = {
    "CSI300": "H00300.CSI",
    "CSI1000": "H00852.CSI",
}
PRIMARY_BENCHMARK = "CSI300"
SECONDARY_BENCHMARK = "CSI1000"
STOCK_RETURN_BASIS = "stock_total_return_adj_factor_next_trading_day_close_to_exit_close"
BENCHMARK_RETURN_BASIS = "benchmark_total_return_index_next_trading_day_close_to_same_exit_close"
BENCHMARK_ACCESS_STATUS = "total_return_close_available_close_to_close_amendment_selected"
MONTHLY_T_STAT_METHOD = "newey_west_hac_on_monthly_overlapping_cohorts"
HAC_LAG_RULE = "ceil_horizon_trading_days_div_21_capped_at_monthly_cohort_count_minus_1"
TRADING_DAYS_PER_MONTH = 21
EARNINGS_STABILITY_BASIS = "same_period_yoy_profit_dedt_growth_volatility"
MIN_EARNINGS_STABILITY_YOY_GROWTHS = 3
SUMMARY_ARTIFACT_ID = "a_long_signal_search_execution_summary_20260604"
FULL_PERIOD_SUFFIX = "2018_2025"
MIN_MONTHLY_COHORTS = 48
FDR_ALPHA = 0.05
TOP_FRACTION = 0.2
MIN_TOP_COUNT = 10
MAX_TOP_SYMBOL_SELECTION_SHARE = 0.2
MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE = 0.35
MIN_ALLOWED_MONTHLY_EXCESS_DRAWDOWN = -0.15

# Conservative round-trip cost: buy commission + sell commission + sell stamp tax
# + buy/sell slippage. This is intentionally not optimized by result.
COMMISSION_PER_SIDE = 0.0003
SELL_STAMP_TAX = 0.0010
SLIPPAGE_PER_SIDE = 0.0005
ROUND_TRIP_COST = (2 * COMMISSION_PER_SIDE) + SELL_STAMP_TAX + (2 * SLIPPAGE_PER_SIDE)


@dataclass(frozen=True)
class SignalContext:
    symbols: list[str]
    active_symbols: list[str]
    delisted_symbols: list[str]
    exception_symbols: set[str]
    as_ofs: list[str]
    trade_dates: list[str]
    list_date_by_symbol: dict[str, str]
    delist_date_by_symbol: dict[str, str | None]
    name_by_symbol: dict[str, str] = field(default_factory=dict)
    selection_status_by_symbol: dict[str, list[dict[str, str | None]]] = field(default_factory=dict)
    selection_status_source: str = SELECTION_STATUS_SOURCE


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the reviewed A-long full main-board signal search from already-materialized local raw data. "
            "This executes no provider call and writes a tracked no-secret summary only. "
            "It requires independent-review and post-review execute confirmations."
        )
    )
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument("--confirm-independent-review-pass", action="store_true")
    parser.add_argument("--confirm-post-review-execute", action="store_true")
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    write_json(tmp_path, payload)
    tmp_path.replace(path)


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for A-long schema-gated signal search; "
            "install project requirements before running this producer."
        ) from exc
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def normalize_yyyymmdd(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip().replace("-", "")
    if len(text) == 8 and text.isdigit():
        return text
    return None


def numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def call_id_for(table: str, symbol: str) -> str:
    return f"{table}_{symbol.replace('.', '_')}_{FULL_PERIOD_SUFFIX}"


def dividend_call_id(symbol: str) -> str:
    return f"dividend_{symbol.replace('.', '_')}"


def benchmark_call_id(benchmark_code: str) -> str:
    return f"index_daily_{benchmark_code.replace('.', '_')}_{FULL_PERIOD_SUFFIX}"


def require_execution_confirmations(*, confirm_independent_review_pass: bool, confirm_post_review_execute: bool) -> None:
    if not confirm_independent_review_pass:
        raise RuntimeError("signal search requires --confirm-independent-review-pass")
    if not confirm_post_review_execute:
        raise RuntimeError("signal search requires --confirm-post-review-execute")


def load_and_validate_preregistration(path: Path = PREREGISTRATION_PATH) -> dict[str, Any]:
    prereg = read_json(path)
    if prereg.get("schema_name") != "a_long_signal_search_preregistration":
        raise ValueError("signal-search preregistration schema_name mismatch")
    scope = prereg.get("scope") or {}
    for field in [
        "research_only",
        "manual_order_only",
    ]:
        if scope.get(field) is not True:
            raise ValueError(f"preregistration scope.{field} must be true")
    for field in [
        "signal_search_executed_by_this_artifact",
        "signal_search_authorized_by_this_artifact",
        "data_fetch_allowed_by_this_artifact",
        "provider_call_allowed_by_this_artifact",
        "production_use_allowed",
        "ship_gate_claim_allowed",
        "full_size_manual_use_allowed",
        "broker_or_order_automation_allowed",
    ]:
        if scope.get(field) is not False:
            raise ValueError(f"preregistration scope.{field} must be false")

    design = prereg.get("search_design") or {}
    if design.get("allowed_signal_families") != ALLOWED_SIGNAL_FAMILIES:
        raise ValueError("allowed signal families drifted")
    signal_policy = design.get("signal_family_measurement_policy") or {}
    if signal_policy.get("earnings_stability_basis") != EARNINGS_STABILITY_BASIS:
        raise ValueError("earnings_stability basis drifted")
    if signal_policy.get("mixed_ytd_quarter_sequence_allowed") is not False:
        raise ValueError("earnings_stability must not mix YTD 3/6/9/12-month cumulative profit rows")
    if signal_policy.get("minimum_same_period_yoy_growths") != MIN_EARNINGS_STABILITY_YOY_GROWTHS:
        raise ValueError("earnings_stability minimum YoY growth count drifted")
    if design.get("entry_exit_measurement_rule", {}).get("exit_horizons_trading_days") != HORIZONS:
        raise ValueError("exit horizons drifted")
    if design.get("benchmark_rule", {}).get("primary_benchmark") != "CSI300":
        raise ValueError("primary benchmark drifted")
    if design.get("benchmark_rule", {}).get("secondary_benchmark") != "CSI1000":
        raise ValueError("secondary benchmark drifted")
    measurement_rule = design.get("entry_exit_measurement_rule") or {}
    if measurement_rule.get("entry_rule") != "next_trading_day_close_after_as_of":
        raise ValueError("A-long entry rule must be next trading day close after the close-to-close amendment")
    if measurement_rule.get("stock_return_basis") != STOCK_RETURN_BASIS:
        raise ValueError("A-long stock return basis must be adj_factor total return after the close-to-close amendment")
    if measurement_rule.get("dividend_and_adj_factor_required") is not True:
        raise ValueError("close-to-close total-vs-total amendment must require adj_factor total return")
    benchmark_rule = design.get("benchmark_rule") or {}
    if benchmark_rule.get("benchmark_return_basis") != BENCHMARK_RETURN_BASIS:
        raise ValueError("A-long benchmark return basis must be total-return-index same-anchor close-to-close")
    if benchmark_rule.get("benchmark_access_probe_ref") != "docs/a_long_total_return_benchmark_access_probe_summary_20260606.json":
        raise ValueError("A-long benchmark access probe ref drifted")
    if benchmark_rule.get("benchmark_access_status") != BENCHMARK_ACCESS_STATUS:
        raise ValueError("A-long benchmark access status drifted from the reviewed close-to-close amendment")
    if benchmark_rule.get("price_index_benchmark_allowed") is not False:
        raise ValueError("price-index benchmark must remain forbidden after the close-to-close total-vs-total amendment")
    if benchmark_rule.get("price_index_fallback_allowed") is not False:
        raise ValueError("price-index fallback must remain forbidden")
    if benchmark_rule.get("derived_total_return_open_allowed") is not False:
        raise ValueError("derived total-return benchmark open must remain forbidden")

    industry = design.get("industry_policy") or {}
    if industry.get("exception_count") != EXPECTED_NO_INDUSTRY_EXCEPTION_COUNT:
        raise ValueError("no-industry exception count drifted")
    if industry.get("exception_retained_in_returns_and_risk") is not True:
        raise ValueError("no-industry exceptions must stay in returns and risk")
    if industry.get("exception_excluded_only_from_industry_denominators") is not True:
        raise ValueError("no-industry exceptions may only leave industry denominators")
    if industry.get("selection_time_st_or_delisting_name_veto_required") is not True:
        raise ValueError("selection-time ST / delisting-name veto must remain required")
    if industry.get("pit_selection_status_source_required") is not True:
        raise ValueError("selection-time veto must require a PIT name/status source")
    if industry.get("current_stock_basic_name_veto_allowed") is not False:
        raise ValueError("current stock_basic.name must not be used as a historical selection-time veto source")
    if industry.get("silent_industry_fill_allowed") is not False:
        raise ValueError("silent industry fill must remain forbidden")

    restatement = design.get("restatement_exclusion_policy") or {}
    if restatement.get("expected_exclusion_group_count") != EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT:
        raise ValueError("restatement exclusion count drifted")
    if restatement.get("runner_must_abort_if_exclusion_list_missing") is not True:
        raise ValueError("runner must abort when exclusion list is missing")
    if restatement.get("runner_must_abort_if_exclusion_not_applied") is not True:
        raise ValueError("runner must abort when exclusion list is not applied")
    if restatement.get("silent_use_of_ambiguous_groups_allowed") is not False:
        raise ValueError("silent use of ambiguous restatement groups must remain forbidden")
    if restatement.get("latest_only_fill_allowed") is not False:
        raise ValueError("latest-only fill must remain forbidden")
    if restatement.get("fina_indicator_pit_contract") != "ann_date_only_with_restatement_exclusion_no_latest_fill":
        raise ValueError("fina_indicator PIT contract drifted")

    testing = design.get("multiple_testing_policy") or {}
    if testing.get("parameter_sweep_allowed") is not False:
        raise ValueError("parameter sweep must remain forbidden")
    if testing.get("post_result_rescue_slicing_allowed") is not False:
        raise ValueError("post-result rescue slicing must remain forbidden")
    if testing.get("t_stat_method") != MONTHLY_T_STAT_METHOD:
        raise ValueError("monthly cohort t-stat method must be Newey-West HAC for overlapping long-horizon returns")
    if testing.get("hac_lag_rule") != HAC_LAG_RULE:
        raise ValueError("HAC lag rule drifted")
    if testing.get("monthly_cohort_count_is_not_independent_n") is not True:
        raise ValueError("monthly cohort count must not be treated as independent sample size")
    if testing.get("minimum_monthly_cohorts") < MIN_MONTHLY_COHORTS:
        raise ValueError("minimum monthly cohorts drifted")
    if testing.get("min_allowed_monthly_excess_drawdown") != MIN_ALLOWED_MONTHLY_EXCESS_DRAWDOWN:
        raise ValueError("monthly excess drawdown gate drifted")
    return prereg


def load_and_validate_ledger(path: Path = LEDGER_PATH) -> dict[str, Any]:
    ledger = read_json(path)
    if ledger.get("schema_name") != "program_test_budget_ledger":
        raise ValueError("program-test ledger schema_name mismatch")
    policy = ledger.get("budget_policy") or {}
    if policy.get("tests_spent_count") != 0:
        raise ValueError("A-long signal-search singleton test was already spent")
    if policy.get("next_test_requires_reviewed_preregistration") is not True:
        raise ValueError("ledger must require reviewed preregistration")
    if policy.get("next_test_requires_user_approval") is not True:
        raise ValueError("ledger must require user approval")
    planned = ledger.get("planned_tests") or []
    if len(planned) != 1 or planned[0].get("test_id") != "a_long_signal_search_preregistration_20260604":
        raise ValueError("ledger planned test mismatch")
    return ledger


def load_and_validate_audit_report(path: Path = AUDIT_REPORT_PATH) -> dict[str, Any]:
    report = read_json(path)
    if report.get("schema_name") != "a_long_full_main_board_data_integrity_audit_report":
        raise ValueError("audit report schema_name mismatch")
    decision = report.get("decision") or {}
    if decision.get("audit_status") != "passed_full_main_board_data_integrity_for_signal_search":
        raise ValueError("full main-board audit did not pass")
    if decision.get("hard_checks_pass") is not True:
        raise ValueError("full main-board audit hard checks did not pass")
    if decision.get("usable_start_year") != 2018:
        raise ValueError("usable start year drifted")
    if decision.get("signal_search_may_be_executed_after_review") is not True:
        raise ValueError("audit report does not permit the next reviewed signal-search gate")
    if decision.get("signal_search_authorized_by_this_report") is not False:
        raise ValueError("audit report must not authorize signal search by itself")
    if decision.get("alpha_found") is not False:
        raise ValueError("audit report must not claim alpha")
    boundary = report.get("full_main_board_boundary") or {}
    if boundary.get("active_symbol_count") != EXPECTED_ACTIVE_COUNT:
        raise ValueError("audit active count drifted")
    if boundary.get("delisted_symbol_count") != EXPECTED_DELISTED_COUNT:
        raise ValueError("audit delisted count drifted")
    if boundary.get("candidate_universe_count") != EXPECTED_UNIVERSE_COUNT:
        raise ValueError("audit universe count drifted")
    if boundary.get("reviewed_no_industry_exception_count") != EXPECTED_NO_INDUSTRY_EXCEPTION_COUNT:
        raise ValueError("audit no-industry exception count drifted")
    checks = {item.get("check_id"): item for item in report.get("checks", [])}
    status_check = checks.get("selection_time_status_source")
    if not status_check or status_check.get("status") != "pass_full_main_board":
        raise ValueError("full audit must pass PIT selection-time name/status source check")
    benchmark_check = checks.get("return_benchmark_measurement_basis") or {}
    metrics = benchmark_check.get("metrics") or {}
    if metrics.get("benchmark_return_basis") != BENCHMARK_RETURN_BASIS:
        raise ValueError("full audit benchmark check must match the H-code total-return close basis")
    return report


def load_and_validate_benchmark_route_amendment(path: Path = BENCHMARK_ACCESS_PROBE_SUMMARY_PATH) -> dict[str, Any]:
    summary = read_json(path)
    if summary.get("schema_name") != "a_long_total_return_benchmark_access_probe_summary":
        raise ValueError("A-long total-return benchmark access probe schema_name mismatch")
    decision = summary.get("decision") or {}
    if decision.get("price_index_fallback_allowed") is not False:
        raise ValueError("price-index benchmark fallback must remain forbidden")
    if decision.get("derived_total_return_open_allowed") is not False:
        raise ValueError("derived total-return benchmark open must remain forbidden")
    if decision.get("benchmark_access_status") != "blocked_total_return_same_anchor_open_unavailable":
        raise ValueError(
            "A-long close-to-close amendment must be grounded in the blocked total-return-open probe"
        )
    if decision.get("runner_benchmark_switch_allowed") is not False:
        raise ValueError("A-long probe summary must not authorize runner benchmark switch by itself")
    close_only_codes = {
        item.get("benchmark_label"): item.get("ts_code")
        for item in summary.get("direct_probes", [])
        if item.get("candidate_role") == "total_return_candidate"
        and item.get("close_only_total_return_candidate") is True
        and int(item.get("close_non_null_count") or 0) > 0
    }
    if close_only_codes.get("CSI300") != BENCHMARKS["CSI300"] or close_only_codes.get("CSI1000") != BENCHMARKS["CSI1000"]:
        raise ValueError("A-long close-to-close amendment requires probed total-return close data for CSI300 and CSI1000")
    return summary


def load_restatement_exclusions(path: Path = RESTATEMENT_EXCLUSION_LIST_PATH) -> set[tuple[str, str, str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"required restatement exclusion list missing: {display_path(path)}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"table_id", "symbol", "end_date", "ann_date", "required_signal_treatment"}
    if not rows or not required.issubset(rows[0].keys()):
        raise ValueError("restatement exclusion CSV missing required columns")
    exclusions = {
        (
            str(row["table_id"]),
            str(row["symbol"]),
            str(row["end_date"]),
            str(row["ann_date"]),
        )
        for row in rows
        if row.get("required_signal_treatment") == "exclude_this_table_symbol_period_ann_date_group"
    }
    if len(exclusions) != EXPECTED_RESTATEMENT_EXCLUSION_GROUP_COUNT:
        raise ValueError(f"restatement exclusion count mismatch: {len(exclusions)}")
    return exclusions


def validate_materialization_summary_and_manifest(raw_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], audit.PayloadStore]:
    summary = read_json(MATERIALIZATION_SUMMARY_PATH)
    audit.validate_materialization_summary(summary)
    execution = summary.get("execution") or {}
    if execution.get("endpoint_results_count") != EXPECTED_ENDPOINT_RESULTS_COUNT:
        raise ValueError("materialization endpoint count drifted")
    if execution.get("token_logged") is not False or execution.get("request_url_logged") is not False:
        raise ValueError("materialization summary must not log token or request URL")
    manifest = audit.load_endpoint_manifest(summary, raw_root)
    required_benchmark_call_ids = [benchmark_call_id(code) for code in BENCHMARKS.values()]
    missing_benchmark_call_ids = [call_id for call_id in required_benchmark_call_ids if call_id not in manifest]
    if missing_benchmark_call_ids:
        raise ValueError(
            "materialized raw panel lacks required total-return benchmark index_daily payloads: "
            + ", ".join(missing_benchmark_call_ids)
        )
    required_ids = required_benchmark_call_ids + [SELECTION_STATUS_CALL_ID]
    for call_id in required_ids:
        item = manifest.get(call_id)
        if item is None:
            raise ValueError(f"materialized raw panel lacks required PIT/status payload: {call_id}")
        if item.get("call_status") != "success" or int(item.get("row_count") or 0) <= 0:
            raise ValueError(f"required materialized payload is empty or not successful: {call_id}")
    store = audit.PayloadStore(raw_root=raw_root, manifest=manifest)
    return summary, manifest, store


def selection_status_history(store: audit.PayloadStore, symbols: set[str]) -> dict[str, list[dict[str, str | None]]]:
    history: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for row in store.records(SELECTION_STATUS_CALL_ID):
        symbol = str(row.get("ts_code") or "")
        if symbol not in symbols:
            continue
        start_date = normalize_yyyymmdd(row.get("start_date"))
        if start_date is None:
            continue
        history[symbol].append(
            {
                "name": str(row.get("name") or ""),
                "start_date": start_date,
                "end_date": normalize_yyyymmdd(row.get("end_date")),
            }
        )
    for events in history.values():
        events.sort(key=lambda item: (str(item.get("start_date") or ""), str(item.get("end_date") or "")))
    return dict(history)


def build_signal_context(store: audit.PayloadStore, repair: dict[str, Any]) -> SignalContext:
    audit_context = audit.build_context(store, repair)
    list_date_by_symbol: dict[str, str] = {}
    delist_date_by_symbol: dict[str, str | None] = {}
    name_by_symbol: dict[str, str] = {}
    for call_id in ["stock_basic_active_L", "stock_basic_delisted_D"]:
        for row in store.records(call_id):
            symbol = row.get("ts_code")
            if not symbol:
                continue
            text_symbol = str(symbol)
            if text_symbol not in audit_context.symbols:
                continue
            list_date_by_symbol[text_symbol] = normalize_yyyymmdd(row.get("list_date")) or "00000000"
            delist_date_by_symbol[text_symbol] = normalize_yyyymmdd(row.get("delist_date"))
            name_by_symbol[text_symbol] = str(row.get("name") or "")
    status_history = selection_status_history(store, set(audit_context.symbols))
    if not status_history:
        raise ValueError(
            "PIT selection-time name/status history is missing; current stock_basic.name cannot be used for historical veto"
        )
    trade_dates = sorted(
        {
            str(row["cal_date"])
            for row in store.records("trade_calendar_2018_2025")
            if str(row.get("is_open")) == "1" and START_DATE <= str(row.get("cal_date")) <= END_DATE
        }
    )
    if len(audit_context.active_symbols) != EXPECTED_ACTIVE_COUNT:
        raise ValueError("active symbol count drifted")
    if len(audit_context.delisted_symbols) != EXPECTED_DELISTED_COUNT:
        raise ValueError("delisted symbol count drifted")
    if len(audit_context.symbols) != EXPECTED_UNIVERSE_COUNT:
        raise ValueError("universe count drifted")
    if len(audit_context.exception_symbols) != EXPECTED_NO_INDUSTRY_EXCEPTION_COUNT:
        raise ValueError("no-industry exception symbol count drifted")
    return SignalContext(
        symbols=audit_context.symbols,
        active_symbols=audit_context.active_symbols,
        delisted_symbols=audit_context.delisted_symbols,
        exception_symbols=set(audit_context.exception_symbols),
        as_ofs=audit_context.as_ofs,
        trade_dates=trade_dates,
        list_date_by_symbol=list_date_by_symbol,
        delist_date_by_symbol=delist_date_by_symbol,
        name_by_symbol=name_by_symbol,
        selection_status_by_symbol=status_history,
    )


def row_exclusion_key(table_id: str, row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        table_id,
        str(row.get("ts_code") or row.get("symbol") or ""),
        str(normalize_yyyymmdd(row.get("end_date")) or ""),
        str(normalize_yyyymmdd(row.get("ann_date")) or ""),
    )


def select_latest_pit_row(
    rows: list[dict[str, Any]],
    *,
    table_id: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> dict[str, Any] | None:
    valid: list[dict[str, Any]] = []
    for row in rows:
        ann_date = normalize_yyyymmdd(row.get("ann_date"))
        end_date = normalize_yyyymmdd(row.get("end_date"))
        if ann_date is None or end_date is None or ann_date > as_of:
            continue
        f_ann_date = normalize_yyyymmdd(row.get("f_ann_date"))
        if table_id in F_ANN_DATE_REQUIRED_TABLES and f_ann_date is None:
            continue
        if table_id not in F_ANN_DATE_REQUIRED_TABLES | ANN_DATE_ONLY_TABLES:
            raise ValueError(f"unregistered PIT fundamental table: {table_id}")
        if f_ann_date is not None and f_ann_date > as_of:
            continue
        if row_exclusion_key(table_id, row) in restatement_exclusions:
            continue
        valid.append(row)
    if not valid:
        return None
    valid.sort(
        key=lambda row: (
            normalize_yyyymmdd(row.get("end_date")) or "",
            normalize_yyyymmdd(row.get("ann_date")) or "",
            normalize_yyyymmdd(row.get("f_ann_date")) or "",
        )
    )
    return valid[-1]


def select_recent_pit_rows(
    rows: list[dict[str, Any]],
    *,
    table_id: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
    limit: int,
) -> list[dict[str, Any]]:
    by_period: dict[str, dict[str, Any]] = {}
    for row in rows:
        selected = select_latest_pit_row([row], table_id=table_id, as_of=as_of, restatement_exclusions=restatement_exclusions)
        if selected is not None:
            end_date = normalize_yyyymmdd(selected.get("end_date")) or ""
            existing = by_period.get(end_date)
            if existing is None:
                by_period[end_date] = selected
            else:
                old_key = (normalize_yyyymmdd(existing.get("ann_date")) or "", normalize_yyyymmdd(existing.get("f_ann_date")) or "")
                new_key = (normalize_yyyymmdd(selected.get("ann_date")) or "", normalize_yyyymmdd(selected.get("f_ann_date")) or "")
                if new_key > old_key:
                    by_period[end_date] = selected
    return [by_period[key] for key in sorted(by_period.keys(), reverse=True)[:limit]]


def same_period_yoy_growths_from_ytd_profit(rows: list[dict[str, Any]], *, max_period_values: int = 5) -> list[float]:
    period_profit: dict[str, float] = {}
    for row in rows:
        end_date = normalize_yyyymmdd(row.get("end_date"))
        profit = numeric(row.get("profit_dedt"))
        if end_date and profit is not None:
            period_profit[end_date] = profit
    if not period_profit:
        return []

    latest_end_date = max(period_profit)
    period_suffix = latest_end_date[4:]
    by_year: dict[int, float] = {}
    for end_date, profit in period_profit.items():
        if end_date[4:] == period_suffix:
            by_year[int(end_date[:4])] = profit

    selected_years = sorted(by_year.keys(), reverse=True)[:max_period_values]
    selected_year_set = set(selected_years)
    growths: list[float] = []
    for year in selected_years:
        previous_year = year - 1
        if previous_year not in selected_year_set:
            continue
        previous_profit = by_year[previous_year]
        if previous_profit == 0:
            continue
        growths.append((by_year[year] - previous_profit) / abs(previous_profit))
    return growths


def compute_signal_values(
    store: audit.PayloadStore,
    symbol: str,
    as_of: str,
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> dict[str, float]:
    income_rows = store.records(call_id_for("income", symbol))
    balance_rows = store.records(call_id_for("balancesheet", symbol))
    cash_rows = store.records(call_id_for("cashflow", symbol))
    indicator_rows = store.records(call_id_for("fina_indicator", symbol))

    income_row = select_latest_pit_row(income_rows, table_id="income", as_of=as_of, restatement_exclusions=restatement_exclusions)
    balance_row = select_latest_pit_row(balance_rows, table_id="balancesheet", as_of=as_of, restatement_exclusions=restatement_exclusions)
    cash_row = select_latest_pit_row(cash_rows, table_id="cashflow", as_of=as_of, restatement_exclusions=restatement_exclusions)
    indicator_row = select_latest_pit_row(indicator_rows, table_id="fina_indicator", as_of=as_of, restatement_exclusions=restatement_exclusions)

    values: dict[str, float] = {}
    roe = numeric(indicator_row.get("roe")) if indicator_row else None
    if roe is not None:
        values["profitability_quality"] = roe

    cashflow = numeric(cash_row.get("n_cashflow_act")) if cash_row else None
    net_income = numeric(income_row.get("n_income_attr_p")) if income_row else None
    income_end_date = normalize_yyyymmdd(income_row.get("end_date")) if income_row else None
    cash_end_date = normalize_yyyymmdd(cash_row.get("end_date")) if cash_row else None
    if cashflow is not None and net_income not in (None, 0.0) and income_end_date == cash_end_date:
        values["cash_conversion"] = cashflow / abs(net_income)

    equity = numeric(balance_row.get("total_hldr_eqy_exc_min_int")) if balance_row else None
    assets = numeric(balance_row.get("total_assets")) if balance_row else None
    liabilities = numeric(balance_row.get("total_liab")) if balance_row else None
    if equity is not None and assets not in (None, 0.0) and liabilities is not None:
        values["balance_sheet_strength"] = (equity / assets) - (liabilities / assets)

    recent_profit_rows = select_recent_pit_rows(
        indicator_rows,
        table_id="fina_indicator",
        as_of=as_of,
        restatement_exclusions=restatement_exclusions,
        limit=32,
    )
    yoy_growths = same_period_yoy_growths_from_ytd_profit(recent_profit_rows)
    if len(yoy_growths) >= MIN_EARNINGS_STABILITY_YOY_GROWTHS:
        values["earnings_stability"] = -pstdev(yoy_growths)
    return values


def count_restatement_exclusion_keys_present(
    store: audit.PayloadStore,
    context: SignalContext,
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> int:
    seen: set[tuple[str, str, str, str]] = set()
    for symbol in context.symbols:
        for table_id in ["income", "balancesheet", "cashflow", "fina_indicator"]:
            for row in store.records(call_id_for(table_id, symbol)):
                key = row_exclusion_key(table_id, row)
                if key in restatement_exclusions:
                    seen.add(key)
    return len(seen)


def symbol_in_pit_scored_universe(context: SignalContext, symbol: str, as_of: str) -> bool:
    list_date = context.list_date_by_symbol.get(symbol, "00000000")
    delist_date = context.delist_date_by_symbol.get(symbol)
    if as_of < list_date:
        return False
    if delist_date is not None and as_of >= delist_date:
        return False
    return True


def selection_time_name_vetoed(name: str | None) -> bool:
    if not name:
        return False
    text = str(name).strip()
    upper = text.upper().replace("＊", "*")
    return (
        upper.startswith("*ST")
        or upper.startswith("ST")
        or upper.startswith("S*ST")
        or upper.startswith("SST")
        or text.startswith("退")
        or "退市" in text
    )


def selection_time_names_for_symbol(context: SignalContext, symbol: str, as_of: str) -> list[str]:
    names: list[str] = []
    for event in context.selection_status_by_symbol.get(symbol, []):
        start_date = event.get("start_date")
        end_date = event.get("end_date")
        if start_date and start_date <= as_of and (end_date is None or as_of <= end_date):
            names.append(str(event.get("name") or ""))
    return names


def symbol_vetoed_at_selection_time(context: SignalContext, symbol: str, as_of: str) -> bool:
    return any(selection_time_name_vetoed(name) for name in selection_time_names_for_symbol(context, symbol, as_of))


def load_industry_records(store: audit.PayloadStore) -> dict[str, list[dict[str, Any]]]:
    records_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in store.records("index_member_all_sw_membership"):
        symbol = row.get("ts_code")
        if symbol:
            records_by_symbol[str(symbol)].append(row)
    repair = read_json(audit.SW_REPAIR_SUMMARY_PATH)
    for item in (repair.get("active_sw_supplement") or {}).get("symbol_results", []):
        if item.get("supplement_success") is not True:
            continue
        raw_ref = item.get("raw_payload_ref")
        if not raw_ref:
            continue
        payload = read_json(audit.resolve_raw_ref(audit.SW_REPAIR_RAW_ROOT, str(raw_ref)))
        for row in payload.get("records", []):
            if isinstance(row, dict) and row.get("ts_code"):
                records_by_symbol[str(row["ts_code"])].append(row)
    return dict(records_by_symbol)


def industry_values(row: dict[str, Any]) -> tuple[str | None, str | None]:
    l2 = row.get("l2_code") or row.get("l2_name")
    l1 = row.get("l1_code") or row.get("l1_name")
    return str(l2) if l2 else None, str(l1) if l1 else None


def industry_for_symbol(records_by_symbol: dict[str, list[dict[str, Any]]], symbol: str, as_of: str) -> tuple[str | None, str | None, str]:
    candidates: list[dict[str, Any]] = []
    for row in records_by_symbol.get(symbol, []):
        in_date = normalize_yyyymmdd(row.get("in_date")) or "00000000"
        out_date = normalize_yyyymmdd(row.get("out_date")) or "99999999"
        if in_date <= as_of <= out_date:
            candidates.append(row)
    if not candidates:
        if records_by_symbol.get(symbol):
            return None, None, "no_interval_membership"
        return None, None, "missing"
    candidates.sort(key=lambda row: normalize_yyyymmdd(row.get("in_date")) or "")
    chosen = candidates[-1]
    l2, l1 = industry_values(chosen)
    return l2, l1, "asof_interval"


def industry_context_for_symbol(
    records_by_symbol: dict[str, list[dict[str, Any]]],
    context: SignalContext,
    symbol: str,
    as_of: str,
) -> tuple[str | None, str | None, str, bool]:
    l2, l1, industry_source = industry_for_symbol(records_by_symbol, symbol, as_of)
    has_membership_source = bool(records_by_symbol.get(symbol))
    industry_excluded = symbol in context.exception_symbols or industry_source == "no_interval_membership"
    if symbol in context.active_symbols and symbol not in context.exception_symbols and not has_membership_source:
        raise ValueError(f"active investable symbol has no industry membership source during signal search: {symbol}")
    if not industry_excluded and not (l2 or l1):
        raise ValueError(f"active investable symbol lacks industry during signal search: {symbol}")
    return l2, l1, industry_source, industry_excluded


def percentile_scores(items: list[dict[str, Any]], field: str, out_field: str) -> None:
    valid = [item for item in items if item.get(field) is not None]
    valid.sort(key=lambda item: item[field])
    count = len(valid)
    if count == 0:
        return
    if count == 1:
        valid[0][out_field] = 0.5
        return
    for index, item in enumerate(valid):
        item[out_field] = index / (count - 1)


def add_industry_neutral_scores(items: list[dict[str, Any]], family: str) -> None:
    by_l2: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_l1: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if item.get("industry_excluded"):
            continue
        if item.get("industry_l2"):
            by_l2[str(item["industry_l2"])].append(item)
        if item.get("industry_l1"):
            by_l1[str(item["industry_l1"])].append(item)

    neutral_scores: dict[str, float] = {}
    for _group, group_items in by_l2.items():
        if len(group_items) >= 20:
            percentile_scores(group_items, family, "_industry_percentile")
            for item in group_items:
                if "_industry_percentile" in item:
                    neutral_scores[item["symbol"]] = item["_industry_percentile"]
    for _group, group_items in by_l1.items():
        remaining = [item for item in group_items if item["symbol"] not in neutral_scores]
        if len(remaining) >= 2:
            percentile_scores(remaining, family, "_industry_percentile")
            for item in remaining:
                if "_industry_percentile" in item:
                    neutral_scores[item["symbol"]] = item["_industry_percentile"]
    for item in items:
        if item["symbol"] in neutral_scores:
            item[f"{family}__industry_neutral"] = neutral_scores[item["symbol"]]
        item.pop("_industry_percentile", None)


def stock_total_return_close_rows(store: audit.PayloadStore, symbol: str) -> dict[str, dict[str, float]]:
    daily_rows = store.records(call_id_for("daily", symbol))
    factor_rows = store.records(call_id_for("adj_factor", symbol))
    factor_by_date: dict[str, float] = {}
    for row in factor_rows:
        trade_date = normalize_yyyymmdd(row.get("trade_date"))
        factor = numeric(row.get("adj_factor"))
        if trade_date and factor is not None:
            factor_by_date[trade_date] = factor
    out: dict[str, dict[str, float]] = {}
    for row in daily_rows:
        trade_date = normalize_yyyymmdd(row.get("trade_date"))
        if not trade_date:
            continue
        close_price = numeric(row.get("close"))
        factor = factor_by_date.get(trade_date)
        if close_price is None or factor is None:
            continue
        out[trade_date] = {
            "close": close_price * factor,
        }
    return out


def index_total_return_close_rows(store: audit.PayloadStore, benchmark_code: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in store.records(benchmark_call_id(benchmark_code)):
        trade_date = normalize_yyyymmdd(row.get("trade_date"))
        close_price = numeric(row.get("close"))
        if trade_date and close_price is not None:
            out[trade_date] = {"close": close_price}
    return out


def compute_return(
    stock_prices: dict[str, dict[str, float]],
    index_prices: dict[str, dict[str, float]],
    trade_dates: list[str],
    as_of: str,
    horizon: int,
) -> tuple[float | None, float | None, str | None, str | None]:
    entry_candidates = [date for date in trade_dates if date > as_of]
    if not entry_candidates:
        return None, None, None, None
    entry_date = entry_candidates[0]
    try:
        entry_idx = trade_dates.index(entry_date)
    except ValueError:
        return None, None, None, None
    exit_idx = entry_idx + horizon
    if exit_idx >= len(trade_dates):
        return None, None, entry_date, None
    exit_date = trade_dates[exit_idx]
    if entry_date not in stock_prices:
        return None, None, entry_date, exit_date
    stock_exit_date = exit_date
    if stock_exit_date not in stock_prices:
        earlier = [date for date in stock_prices if entry_date < date <= exit_date]
        if not earlier:
            return None, None, entry_date, exit_date
        stock_exit_date = max(earlier)
    benchmark_exit_date = stock_exit_date
    if entry_date not in index_prices or benchmark_exit_date not in index_prices:
        return None, None, entry_date, benchmark_exit_date
    stock_entry = stock_prices[entry_date]["close"]
    stock_exit = stock_prices[stock_exit_date]["close"]
    bench_entry = index_prices[entry_date]["close"]
    bench_exit = index_prices[benchmark_exit_date]["close"]
    if min(stock_entry, stock_exit, bench_entry, bench_exit) <= 0:
        return None, None, entry_date, benchmark_exit_date
    stock_return = (stock_exit / stock_entry) - 1.0 - ROUND_TRIP_COST
    benchmark_return = (bench_exit / bench_entry) - 1.0
    return stock_return, benchmark_return, entry_date, benchmark_exit_date


def monthly_cohort_rows(
    *,
    store: audit.PayloadStore,
    context: SignalContext,
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    industry_records = load_industry_records(store)
    index_prices = {name: index_total_return_close_rows(store, code) for name, code in BENCHMARKS.items()}
    stock_price_cache: dict[str, dict[str, dict[str, float]]] = {}
    rows: list[dict[str, Any]] = []
    diagnostics = {
        "as_of_count": len(context.as_ofs),
        "symbol_count": len(context.symbols),
        "restatement_exclusion_group_count": len(restatement_exclusions),
        "industry_denominator_exclusion_symbol_count": len(context.exception_symbols),
        "scored_pit_universe_excluded_before_list_count": 0,
        "scored_pit_universe_excluded_after_delist_count": 0,
        "selection_time_name_vetoed_observation_count": 0,
        "selection_time_name_vetoed_symbol_count": 0,
        "industry_neutral_excluded_observation_count": 0,
        "industry_neutral_excluded_symbol_count": 0,
        "industry_neutral_excluded_observation_share": None,
        "industry_neutral_excluded_2018_2020_observation_count": 0,
        "industry_neutral_excluded_2018_2020_observation_share": None,
        "missing_signal_rows": 0,
        "missing_return_rows": 0,
    }
    industry_neutral_scored_observations = 0
    industry_neutral_scored_2018_2020_observations = 0
    industry_neutral_excluded_symbols: set[str] = set()
    selection_time_name_vetoed_symbols: set[str] = set()
    for as_of in context.as_ofs:
        scored: list[dict[str, Any]] = []
        for symbol in context.symbols:
            list_date = context.list_date_by_symbol.get(symbol, "00000000")
            delist_date = context.delist_date_by_symbol.get(symbol)
            if as_of < list_date:
                diagnostics["scored_pit_universe_excluded_before_list_count"] += 1
                continue
            if delist_date is not None and as_of >= delist_date:
                diagnostics["scored_pit_universe_excluded_after_delist_count"] += 1
                continue
            if symbol_vetoed_at_selection_time(context, symbol, as_of):
                diagnostics["selection_time_name_vetoed_observation_count"] += 1
                selection_time_name_vetoed_symbols.add(symbol)
                continue
            values = compute_signal_values(store, symbol, as_of, restatement_exclusions)
            if not values:
                diagnostics["missing_signal_rows"] += 1
                continue
            l2, l1, industry_source, industry_excluded = industry_context_for_symbol(industry_records, context, symbol, as_of)
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
            }
            item.update(values)
            scored.append(item)
        for family in ALLOWED_SIGNAL_FAMILIES:
            percentile_scores(scored, family, f"{family}__non_neutral")
            add_industry_neutral_scores(scored, family)
        for item in scored:
            symbol = item["symbol"]
            if symbol not in stock_price_cache:
                stock_price_cache[symbol] = stock_total_return_close_rows(store, symbol)
            for horizon in HORIZONS:
                stock_ret, _primary_bench_ret, entry_date, exit_date = compute_return(
                    stock_price_cache[symbol],
                    index_prices[PRIMARY_BENCHMARK],
                    context.trade_dates,
                    as_of,
                    horizon,
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
                    _stock, bench_ret, _entry, _exit = compute_return(
                        stock_price_cache[symbol],
                        prices,
                        context.trade_dates,
                        as_of,
                        horizon,
                    )
                    row[f"excess_{benchmark_name}"] = None if bench_ret is None else stock_ret - bench_ret
                rows.append(row)
    diagnostics["industry_neutral_excluded_symbol_count"] = len(industry_neutral_excluded_symbols)
    diagnostics["selection_time_name_vetoed_symbol_count"] = len(selection_time_name_vetoed_symbols)
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


def normal_two_sided_p_value(t_stat: float) -> float:
    return math.erfc(abs(t_stat) / math.sqrt(2.0))


def hac_lag_for_horizon(horizon: int, cohort_count: int) -> int:
    if cohort_count <= 1:
        return 0
    configured_lag = max(1, math.ceil(horizon / TRADING_DAYS_PER_MONTH))
    return min(configured_lag, cohort_count - 1)


def newey_west_hac_t_stat(values: list[float], *, horizon: int) -> tuple[float | None, float | None, int]:
    if not values:
        return None, None, 0
    if len(values) == 1:
        return 0.0, None, 0

    avg = mean(values)
    lag = hac_lag_for_horizon(horizon, len(values))
    residuals = [value - avg for value in values]
    gamma0 = sum(value * value for value in residuals) / len(values)
    long_run_variance = gamma0
    for offset in range(1, lag + 1):
        autocovariance = sum(residuals[index] * residuals[index - offset] for index in range(offset, len(values))) / len(values)
        weight = 1.0 - (offset / (lag + 1.0))
        long_run_variance += 2.0 * weight * autocovariance

    long_run_variance = max(long_run_variance, 0.0)
    standard_error = math.sqrt(long_run_variance / len(values)) if long_run_variance > 0 else 0.0
    t_stat = 0.0 if standard_error == 0 else avg / standard_error
    return t_stat, standard_error, lag


def add_bh_adjusted_p(results: list[dict[str, Any]]) -> None:
    tested = [item for item in results if item.get("p_value") is not None]
    tested.sort(key=lambda item: item["p_value"])
    m = len(tested)
    running = 1.0
    for rank, item in reversed(list(enumerate(tested, start=1))):
        adjusted = min(running, float(item["p_value"]) * m / rank)
        item["bh_adjusted_p_value"] = round(adjusted, 10)
        running = adjusted


def max_drawdown(values: list[float]) -> float:
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return worst


def summarize_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for family in ALLOWED_SIGNAL_FAMILIES:
        for view in ["non_neutral", "industry_neutral"]:
            score_field = f"{family}__{view}"
            for horizon in HORIZONS:
                for benchmark_name in BENCHMARKS:
                    excess_field = f"excess_{benchmark_name}"
                    cohort_returns: list[float] = []
                    selected_symbols: dict[str, int] = defaultdict(int)
                    yearly_positive_return_contribution: dict[str, float] = defaultdict(float)
                    as_ofs = sorted({row["as_of"] for row in rows if row.get("horizon") == horizon and row.get(score_field) is not None})
                    for as_of in as_ofs:
                        cohort = [
                            row for row in rows
                            if row.get("as_of") == as_of
                            and row.get("horizon") == horizon
                            and row.get(score_field) is not None
                            and row.get(excess_field) is not None
                        ]
                        if not cohort:
                            continue
                        cohort.sort(key=lambda row: row[score_field], reverse=True)
                        top_count = max(MIN_TOP_COUNT, int(len(cohort) * TOP_FRACTION))
                        selected = cohort[:top_count]
                        cohort_return = mean(float(row[excess_field]) for row in selected)
                        cohort_returns.append(cohort_return)
                        if cohort_return > 0:
                            yearly_positive_return_contribution[str(as_of)[:4]] += cohort_return
                        for row in selected:
                            selected_symbols[str(row["symbol"])] += 1
                    if len(cohort_returns) >= 2:
                        avg = mean(cohort_returns)
                        sd = pstdev(cohort_returns)
                        t_stat, _hac_standard_error, hac_lag_months = newey_west_hac_t_stat(cohort_returns, horizon=horizon)
                        p_value = normal_two_sided_p_value(t_stat)
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
                    drawdown = max_drawdown(cohort_returns) if cohort_returns else None
                    results.append(
                        {
                            "signal_family": family,
                            "view": view,
                            "horizon_trading_days": horizon,
                            "benchmark": benchmark_name,
                            "monthly_cohort_count": len(cohort_returns),
                            "mean_monthly_cohort_net_excess": None if avg is None else round(avg, 10),
                            "monthly_cohort_std": None if sd is None else round(sd, 10),
                            "monthly_clustered_t_stat": None if t_stat is None else round(t_stat, 10),
                            "monthly_t_stat_method": MONTHLY_T_STAT_METHOD,
                            "hac_lag_months": hac_lag_months,
                            "p_value": None if p_value is None else round(p_value, 10),
                            "bh_adjusted_p_value": None,
                            "positive_month_count": len([value for value in cohort_returns if value > 0]),
                            "worst_monthly_cohort_excess": round(min(cohort_returns), 10) if cohort_returns else None,
                            "best_monthly_cohort_excess": round(max(cohort_returns), 10) if cohort_returns else None,
                            "max_drawdown_on_monthly_excess": None if drawdown is None else round(drawdown, 10),
                            "top_symbol_selection_share": None if top_symbol_share is None else round(top_symbol_share, 10),
                            "max_single_year_positive_return_share": (
                                None if single_year_positive_return_share is None else round(single_year_positive_return_share, 10)
                            ),
                            "passes_minimum_monthly_cohorts": len(cohort_returns) >= MIN_MONTHLY_COHORTS,
                            "passes_name_concentration_guard": top_symbol_share is not None and top_symbol_share <= MAX_TOP_SYMBOL_SELECTION_SHARE,
                            "passes_single_year_concentration_guard": (
                                single_year_positive_return_share is not None
                                and single_year_positive_return_share <= MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE
                            ),
                            "passes_drawdown_guard": (
                                drawdown is not None
                                and drawdown >= MIN_ALLOWED_MONTHLY_EXCESS_DRAWDOWN
                            ),
                        }
                    )
    add_bh_adjusted_p(results)
    return results


def validate_pipeline_result_sanity(rows: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(
            "signal-search pipeline failure: no evaluated return rows; "
            "do not emit a no-alpha verdict or spend the singleton ledger"
        )
    expected_excess_fields = [f"excess_{benchmark_name}" for benchmark_name in BENCHMARKS]
    missing_fields = [field for field in expected_excess_fields if all(field not in row for row in rows)]
    if missing_fields:
        raise ValueError(
            "signal-search pipeline failure: evaluated return rows are missing benchmark excess fields: "
            + ", ".join(missing_fields)
        )
    total_cohorts = sum(int(item.get("monthly_cohort_count") or 0) for item in results)
    if total_cohorts == 0:
        raise ValueError(
            "signal-search pipeline failure: evaluated return rows produced zero monthly cohorts; "
            "do not emit a no-alpha verdict or spend the singleton ledger"
        )


def result_cell_passes_candidate_threshold(item: dict[str, Any]) -> bool:
    return (
        item.get("passes_minimum_monthly_cohorts") is True
        and (item.get("mean_monthly_cohort_net_excess") or 0) > 0
        and (item.get("monthly_clustered_t_stat") or 0) >= 2.0
        and item.get("bh_adjusted_p_value") is not None
        and item["bh_adjusted_p_value"] <= FDR_ALPHA
        and item.get("passes_name_concentration_guard") is True
        and item.get("passes_single_year_concentration_guard") is True
        and item.get("passes_drawdown_guard") is True
    )


def decision_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    cells_by_key = {
        (
            item.get("signal_family"),
            item.get("view"),
            item.get("horizon_trading_days"),
            item.get("benchmark"),
        ): item
        for item in results
    }
    candidates = [
        item for item in results
        if item.get("benchmark") == PRIMARY_BENCHMARK
        and result_cell_passes_candidate_threshold(item)
        and result_cell_passes_candidate_threshold(
            cells_by_key.get(
                (
                    item.get("signal_family"),
                    item.get("view"),
                    item.get("horizon_trading_days"),
                    SECONDARY_BENCHMARK,
                ),
                {},
            )
        )
    ]
    if candidates:
        plain = (
            "Signal search found a research-only alpha clue that clears both CSI300 and CSI1000 robustness gates. "
            "This is not enough for real-size use; it still needs forward validation."
        )
        verdict = "candidate_alpha_clue_research_only"
    else:
        plain = "Signal search found no usable alpha clue under the frozen rules."
        verdict = "no_alpha_found_under_frozen_rules"
    return {
        "research_verdict": verdict,
        "candidate_alpha_clue_count": len(candidates),
        "secondary_benchmark_required_for_candidate_alpha": True,
        "alpha_found_for_production": False,
        "ship_gate_evidence": False,
        "full_size_allowed": False,
        "size_exposure_caveat": (
            "Equal-weight top-quintile A-long cohorts can carry size / equal-weight exposure versus cap-weighted CSI300; "
            "candidate labels therefore require same-cell CSI1000 robustness and result review must inspect the CSI300-vs-CSI1000 gap."
        ),
        "plain_result": plain,
        "next_action": (
            "If this result is no-alpha, do not rescue it by changing thresholds. "
            "If it shows a research clue, the next step is forward-live validation, not full-size use."
        ),
    }


def build_summary(
    *,
    raw_root: Path,
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
    audit_report = load_and_validate_audit_report()
    load_and_validate_benchmark_route_amendment()
    restatement_exclusions = load_restatement_exclusions()
    materialization_summary, manifest, store = validate_materialization_summary_and_manifest(raw_root)
    repair = audit.validate_boundary_refs()
    context = build_signal_context(store, repair)
    restatement_keys_present = count_restatement_exclusion_keys_present(store, context, restatement_exclusions)
    if restatement_keys_present != len(restatement_exclusions):
        raise ValueError(
            "restatement exclusion list is not fully matched to the materialized raw panel: "
            f"found {restatement_keys_present}, expected {len(restatement_exclusions)}"
        )
    rows, diagnostics = monthly_cohort_rows(store=store, context=context, restatement_exclusions=restatement_exclusions)
    results = summarize_results(rows)
    validate_pipeline_result_sanity(rows, results)
    decision = decision_from_results(results)
    return {
        "schema_name": "a_long_signal_search_execution_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": SUMMARY_ARTIFACT_ID,
        "source_refs": [
            display_path(PREREGISTRATION_PATH),
            display_path(LEDGER_PATH),
            display_path(MATERIALIZATION_SUMMARY_PATH),
            display_path(AUDIT_REPORT_PATH),
            display_path(RESTATEMENT_EXCLUSION_LIST_PATH),
            display_path(BENCHMARK_ACCESS_PROBE_SUMMARY_PATH),
            "docs/a_long_scaled_delisted_no_industry_boundary_decision_20260605.json",
        ],
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_full_main_board_signal_search_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "provider_call_executed": False,
            "tushare_call_executed": False,
            "data_fetch_executed": False,
            "materialized_raw_read_only": True,
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
            "preregistration_validated": prereg.get("artifact_id") == "a_long_signal_search_preregistration_20260604",
            "ledger_unspent_before_run": ledger["budget_policy"]["tests_spent_count"] == 0,
            "full_main_board_audit_passed": audit_report["decision"]["audit_status"] == "passed_full_main_board_data_integrity_for_signal_search",
            "benchmark_route_amendment_validated": True,
            "restatement_exclusion_list_loaded": True,
            "restatement_exclusion_groups_expected": len(restatement_exclusions),
            "restatement_exclusion_groups_found_in_raw": restatement_keys_present,
            "restatement_exclusion_list_applied": restatement_keys_present == len(restatement_exclusions),
            "no_industry_boundary_consumed": len(context.exception_symbols) == EXPECTED_NO_INDUSTRY_EXCEPTION_COUNT,
            "no_network_calls_executed": True,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_endpoint_results": False,
            "tracked_summary_contains_secret": False,
            "tracked_summary_contains_request_url": False,
        },
        "full_main_board_boundary": {
            "board_scope": "main_board_only",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "active_symbol_count": len(context.active_symbols),
            "delisted_symbol_count": len(context.delisted_symbols),
            "candidate_universe_count": len(context.symbols),
            "reviewed_no_industry_exception_count": len(context.exception_symbols),
            "exception_symbols_retained_in_returns_and_risk": True,
            "exception_symbols_excluded_only_from_industry_denominators": True,
            "monthly_as_of_count": len(context.as_ofs),
        },
        "search_design": {
            "allowed_signal_families": list(ALLOWED_SIGNAL_FAMILIES),
            "horizons_trading_days": list(HORIZONS),
            "primary_benchmark": PRIMARY_BENCHMARK,
            "secondary_benchmark": SECONDARY_BENCHMARK,
            "stock_return_basis": STOCK_RETURN_BASIS,
            "benchmark_return_basis": BENCHMARK_RETURN_BASIS,
            "benchmark_access_probe_ref": "docs/a_long_total_return_benchmark_access_probe_summary_20260606.json",
            "benchmark_access_status": BENCHMARK_ACCESS_STATUS,
            "price_index_benchmark_allowed": False,
            "price_index_fallback_allowed": False,
            "derived_total_return_open_allowed": False,
            "views": ["non_neutral", "industry_neutral"],
            "top_fraction": TOP_FRACTION,
            "minimum_top_count_per_month": MIN_TOP_COUNT,
            "minimum_monthly_cohorts": MIN_MONTHLY_COHORTS,
            "monthly_t_stat_method": MONTHLY_T_STAT_METHOD,
            "hac_lag_rule": HAC_LAG_RULE,
            "monthly_cohort_count_is_not_independent_n": True,
            "earnings_stability_basis": EARNINGS_STABILITY_BASIS,
            "mixed_ytd_quarter_sequence_allowed": False,
            "minimum_earnings_stability_yoy_growths": MIN_EARNINGS_STABILITY_YOY_GROWTHS,
            "selection_time_status_source": SELECTION_STATUS_SOURCE,
            "current_stock_basic_name_veto_allowed": False,
            "multiple_testing_correction": "benjamini_hochberg_fdr",
            "round_trip_cost": ROUND_TRIP_COST,
            "same_anchor_close_to_close": True,
            "secondary_benchmark_required_for_candidate_alpha": True,
            "max_top_symbol_selection_share": MAX_TOP_SYMBOL_SELECTION_SHARE,
            "max_single_year_positive_return_share": MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
            "min_allowed_monthly_excess_drawdown": MIN_ALLOWED_MONTHLY_EXCESS_DRAWDOWN,
            "parameter_sweep_executed": False,
            "post_result_rescue_slicing_executed": False,
        },
        "execution_diagnostics": {
            **diagnostics,
            "endpoint_results_count": len(manifest),
            "evaluated_stock_return_rows": len(rows),
            "result_cell_count": len(results),
        },
        "result_cells": results,
        "decision": decision,
        "ledger_update_required_after_commit": {
            "ledger_ref": display_path(LEDGER_PATH),
            "spends_singleton_test": True,
            "test_id": "a_long_signal_search_preregistration_20260604",
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
            "A positive result would be a clue, not production proof, and cannot unlock full-size use.",
            "The unchanged ship gate still requires at least 12 months of forward-live evidence.",
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
            "test_id": "a_long_signal_search_preregistration_20260604",
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
                "No rerun, threshold change, family change, horizon change, benchmark change, or rescue slicing "
                "without a new reviewed preregistration and ledger update. Positive clues remain research-only "
                "until forward-live ship-gate evidence exists."
            ),
        }
    ]
    ledger["planned_tests"] = []
    ledger["next_required_actions"] = [
        "Do not rerun or rescue this A-long signal search without a new reviewed preregistration and ledger update.",
        "If the result is no-alpha, treat it as failed under the frozen rules.",
        "If the result is a research clue, route it to forward-live validation; do not treat it as production or ship-gate evidence.",
    ]
    validate_json(LEDGER_SCHEMA_PATH, ledger)
    write_json_atomic(ledger_path, ledger)
    return ledger


def write_summary_and_spend_ledger(*, summary_path: Path, summary: dict[str, Any], generated_at: str) -> None:
    if summary_path.exists():
        raise FileExistsError(f"refusing to overwrite existing signal-search summary: {display_path(summary_path)}")
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
        raw_root=args.raw_root,
        generated_at=generated_at,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    validate_json(SCHEMA_PATH, summary)
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
