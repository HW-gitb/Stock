from __future__ import annotations

import argparse
import csv
import json
import math
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

from runners import a_long_full_main_board_data_integrity_audit as audit


PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_signal_search_preregistration_20260604.json"
LEDGER_PATH = ROOT / "research" / "ledgers" / "a_long_signal_search_program_test_budget_ledger_20260604.json"
LEDGER_SCHEMA_PATH = ROOT / "schemas" / "program_test_budget_ledger.schema.json"
MATERIALIZATION_SUMMARY_PATH = ROOT / "docs" / "a_long_full_main_board_materialization_execution_summary_20260605.json"
AUDIT_REPORT_PATH = ROOT / "research" / "results" / "a_long_full_main_board_data_integrity_audit_20260605" / "audit_report.json"
RESTATEMENT_EXCLUSION_LIST_PATH = (
    ROOT / "research" / "results" / "a_long_full_main_board_data_integrity_audit_20260605" / "restatement_ambiguous_exclusions.csv"
)
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
ALLOWED_SIGNAL_FAMILIES = [
    "profitability_quality",
    "cash_conversion",
    "balance_sheet_strength",
    "earnings_stability",
]
HORIZONS = [252, 504]
BENCHMARKS = {
    "CSI300": "000300.SH",
    "CSI1000": "000852.SH",
}
PRIMARY_BENCHMARK = "CSI300"
SUMMARY_ARTIFACT_ID = "a_long_signal_search_execution_summary_20260604"
FULL_PERIOD_SUFFIX = "2018_2025"
MIN_MONTHLY_COHORTS = 48
FDR_ALPHA = 0.05
TOP_FRACTION = 0.2
MIN_TOP_COUNT = 10
MAX_TOP_SYMBOL_SELECTION_SHARE = 0.2
MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE = 0.35

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


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError:
        return
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
    if design.get("entry_exit_measurement_rule", {}).get("exit_horizons_trading_days") != HORIZONS:
        raise ValueError("exit horizons drifted")
    if design.get("benchmark_rule", {}).get("primary_benchmark") != "CSI300":
        raise ValueError("primary benchmark drifted")
    if design.get("benchmark_rule", {}).get("secondary_benchmark") != "CSI1000":
        raise ValueError("secondary benchmark drifted")

    industry = design.get("industry_policy") or {}
    if industry.get("exception_count") != EXPECTED_NO_INDUSTRY_EXCEPTION_COUNT:
        raise ValueError("no-industry exception count drifted")
    if industry.get("exception_retained_in_returns_and_risk") is not True:
        raise ValueError("no-industry exceptions must stay in returns and risk")
    if industry.get("exception_excluded_only_from_industry_denominators") is not True:
        raise ValueError("no-industry exceptions may only leave industry denominators")
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

    testing = design.get("multiple_testing_policy") or {}
    if testing.get("parameter_sweep_allowed") is not False:
        raise ValueError("parameter sweep must remain forbidden")
    if testing.get("post_result_rescue_slicing_allowed") is not False:
        raise ValueError("post-result rescue slicing must remain forbidden")
    if testing.get("minimum_monthly_cohorts") < MIN_MONTHLY_COHORTS:
        raise ValueError("minimum monthly cohorts drifted")
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
    return report


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
    if execution.get("endpoint_results_count") != 23717:
        raise ValueError("materialization endpoint count drifted")
    if execution.get("token_logged") is not False or execution.get("request_url_logged") is not False:
        raise ValueError("materialization summary must not log token or request URL")
    manifest = audit.load_endpoint_manifest(summary, raw_root)
    store = audit.PayloadStore(raw_root=raw_root, manifest=manifest)
    return summary, manifest, store


def build_signal_context(store: audit.PayloadStore, repair: dict[str, Any]) -> SignalContext:
    audit_context = audit.build_context(store, repair)
    list_date_by_symbol: dict[str, str] = {}
    delist_date_by_symbol: dict[str, str | None] = {}
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
    if cashflow is not None and net_income not in (None, 0.0):
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
        limit=4,
    )
    profits = [numeric(row.get("profit_dedt")) for row in recent_profit_rows]
    clean_profits = [value for value in profits if value is not None]
    if len(clean_profits) >= 3:
        avg_abs = abs(mean(clean_profits))
        if avg_abs > 0:
            values["earnings_stability"] = -(pstdev(clean_profits) / avg_abs)
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


def adjusted_price_rows(store: audit.PayloadStore, symbol: str) -> dict[str, dict[str, float]]:
    daily_rows = store.records(call_id_for("daily", symbol))
    adj_rows = store.records(call_id_for("adj_factor", symbol))
    adj_by_date = {normalize_yyyymmdd(row.get("trade_date")): numeric(row.get("adj_factor")) for row in adj_rows}
    out: dict[str, dict[str, float]] = {}
    for row in daily_rows:
        trade_date = normalize_yyyymmdd(row.get("trade_date"))
        if not trade_date:
            continue
        factor = adj_by_date.get(trade_date)
        open_price = numeric(row.get("open"))
        close_price = numeric(row.get("close"))
        if factor is None or open_price is None or close_price is None:
            continue
        out[trade_date] = {
            "open": open_price * factor,
            "close": close_price * factor,
        }
    return out


def index_price_rows(store: audit.PayloadStore, benchmark_code: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in store.records(benchmark_call_id(benchmark_code)):
        trade_date = normalize_yyyymmdd(row.get("trade_date"))
        open_price = numeric(row.get("open"))
        close_price = numeric(row.get("close"))
        if trade_date and open_price is not None and close_price is not None:
            out[trade_date] = {"open": open_price, "close": close_price}
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
    if entry_date not in index_prices or exit_date not in index_prices:
        return None, None, entry_date, exit_date
    stock_entry = stock_prices[entry_date]["open"]
    stock_exit = stock_prices[stock_exit_date]["close"]
    bench_entry = index_prices[entry_date]["open"]
    bench_exit = index_prices[exit_date]["close"]
    if min(stock_entry, stock_exit, bench_entry, bench_exit) <= 0:
        return None, None, entry_date, exit_date
    stock_return = (stock_exit / stock_entry) - 1.0 - ROUND_TRIP_COST
    benchmark_return = (bench_exit / bench_entry) - 1.0
    return stock_return, benchmark_return, entry_date, exit_date


def monthly_cohort_rows(
    *,
    store: audit.PayloadStore,
    context: SignalContext,
    restatement_exclusions: set[tuple[str, str, str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    industry_records = load_industry_records(store)
    index_prices = {name: index_price_rows(store, code) for name, code in BENCHMARKS.items()}
    stock_price_cache: dict[str, dict[str, dict[str, float]]] = {}
    rows: list[dict[str, Any]] = []
    diagnostics = {
        "as_of_count": len(context.as_ofs),
        "symbol_count": len(context.symbols),
        "restatement_exclusion_group_count": len(restatement_exclusions),
        "industry_denominator_exclusion_symbol_count": len(context.exception_symbols),
        "scored_pit_universe_excluded_before_list_count": 0,
        "scored_pit_universe_excluded_after_delist_count": 0,
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
                stock_price_cache[symbol] = adjusted_price_rows(store, symbol)
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
                        and row.get(f"excess_{PRIMARY_BENCHMARK}") is not None
                    ]
                    if not cohort:
                        continue
                    cohort.sort(key=lambda row: row[score_field], reverse=True)
                    top_count = max(MIN_TOP_COUNT, int(len(cohort) * TOP_FRACTION))
                    selected = cohort[:top_count]
                    cohort_return = mean(float(row[f"excess_{PRIMARY_BENCHMARK}"]) for row in selected)
                    cohort_returns.append(cohort_return)
                    if cohort_return > 0:
                        yearly_positive_return_contribution[str(as_of)[:4]] += cohort_return
                    for row in selected:
                        selected_symbols[str(row["symbol"])] += 1
                if len(cohort_returns) >= 2:
                    avg = mean(cohort_returns)
                    sd = pstdev(cohort_returns)
                    t_stat = 0.0 if sd == 0 else avg / (sd / math.sqrt(len(cohort_returns)))
                    p_value = normal_two_sided_p_value(t_stat)
                elif cohort_returns:
                    avg = cohort_returns[0]
                    sd = 0.0
                    t_stat = 0.0
                    p_value = None
                else:
                    avg = None
                    sd = None
                    t_stat = None
                    p_value = None
                total_selections = sum(selected_symbols.values())
                top_symbol_share = max(selected_symbols.values()) / total_selections if total_selections else None
                total_positive_return_contribution = sum(yearly_positive_return_contribution.values())
                single_year_positive_return_share = (
                    max(yearly_positive_return_contribution.values()) / total_positive_return_contribution
                    if total_positive_return_contribution > 0
                    else None
                )
                results.append(
                    {
                        "signal_family": family,
                        "view": view,
                        "horizon_trading_days": horizon,
                        "monthly_cohort_count": len(cohort_returns),
                        "mean_monthly_cohort_net_excess": None if avg is None else round(avg, 10),
                        "monthly_cohort_std": None if sd is None else round(sd, 10),
                        "monthly_clustered_t_stat": None if t_stat is None else round(t_stat, 10),
                        "p_value": None if p_value is None else round(p_value, 10),
                        "bh_adjusted_p_value": None,
                        "positive_month_count": len([value for value in cohort_returns if value > 0]),
                        "max_drawdown_on_monthly_excess": round(max_drawdown(cohort_returns), 10) if cohort_returns else None,
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
                    }
                )
    add_bh_adjusted_p(results)
    return results


def decision_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        item for item in results
        if item.get("passes_minimum_monthly_cohorts") is True
        and (item.get("mean_monthly_cohort_net_excess") or 0) > 0
        and (item.get("monthly_clustered_t_stat") or 0) >= 2.0
        and item.get("bh_adjusted_p_value") is not None
        and item["bh_adjusted_p_value"] <= FDR_ALPHA
        and item.get("passes_name_concentration_guard") is True
        and item.get("passes_single_year_concentration_guard") is True
    ]
    if candidates:
        plain = "Signal search found a research-only alpha clue. This is not enough for real-size use; it still needs forward validation."
        verdict = "candidate_alpha_clue_research_only"
    else:
        plain = "Signal search found no usable alpha clue under the frozen rules."
        verdict = "no_alpha_found_under_frozen_rules"
    return {
        "research_verdict": verdict,
        "candidate_alpha_clue_count": len(candidates),
        "alpha_found_for_production": False,
        "ship_gate_evidence": False,
        "full_size_allowed": False,
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
            "secondary_benchmark": "CSI1000",
            "views": ["non_neutral", "industry_neutral"],
            "top_fraction": TOP_FRACTION,
            "minimum_top_count_per_month": MIN_TOP_COUNT,
            "minimum_monthly_cohorts": MIN_MONTHLY_COHORTS,
            "multiple_testing_correction": "benjamini_hochberg_fdr",
            "round_trip_cost": ROUND_TRIP_COST,
            "same_anchor_open_to_close": True,
            "max_top_symbol_selection_share": MAX_TOP_SYMBOL_SELECTION_SHARE,
            "max_single_year_positive_return_share": MAX_SINGLE_YEAR_POSITIVE_RETURN_SHARE,
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
            "ledger_write_timing": "after_valid_summary_write",
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
    write_json(ledger_path, ledger)
    return ledger


def run(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = args.generated_at or iso_now()
    summary = build_summary(
        raw_root=args.raw_root,
        generated_at=generated_at,
        confirm_independent_review_pass=args.confirm_independent_review_pass,
        confirm_post_review_execute=args.confirm_post_review_execute,
    )
    validate_json(SCHEMA_PATH, summary)
    write_json(args.summary_path, summary)
    spend_ledger_after_success(
        ledger_path=LEDGER_PATH,
        summary=summary,
        result_ref=display_path(args.summary_path),
        generated_at=generated_at,
    )
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
