from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_long_data_integrity_audit as base_audit
from engine.data.a_share_board_scope import assert_main_board_only


SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_broader_materialization_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/materialization_full_period_panel_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL
OUTPUT_DIR = ROOT / "research" / "results" / "a_long_materialized_full_period_data_integrity_audit_20260604"
REPORT_PATH = OUTPUT_DIR / "audit_report.json"
SCHEMA_PATH = ROOT / "schemas" / "a_long_materialized_full_period_data_integrity_audit_report.schema.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_data_integrity_audit_20260603.json"
DELISTED_INDUSTRY_EXCEPTION_SOURCE_PATH = (
    ROOT / "docs" / "a_long_000666_sw_membership_supplement_execution_summary_20260604.json"
)

START_DATE = "20180101"
END_DATE = "20251231"
ACTIVE_SYMBOLS = [
    "000001.SZ",
    "600519.SH",
    "600887.SH",
    "601318.SH",
    "600036.SH",
    "000651.SZ",
    "002415.SZ",
    "600276.SH",
]
DELISTED_SYMBOLS = ["000666.SZ"]
SYMBOLS = ACTIVE_SYMBOLS + DELISTED_SYMBOLS
BENCHMARKS = ["000300.SH", "000852.SH"]
FUNDAMENTAL_TABLES = ["income", "balancesheet", "cashflow", "fina_indicator"]
SAME_ANN_DATE_NON_NULL_PREFERENCE_FIELDS = {"profit_dedt"}
CHECK_IDS = [
    "fundamental_pit",
    "restatement_revision_asof",
    "survivorship_pit_universe",
    "return_benchmark_measurement_basis",
    "temporal_coverage_bias",
]
HARD_CHECK_IDS = set(CHECK_IDS) - {"temporal_coverage_bias"}
FULL_PERIOD_SUFFIX = "2018_2025"
TEMPORAL_COVERAGE_THRESHOLD_PCT = 80.0
DELISTED_INDUSTRY_MISSING_EXCEPTION_SYMBOLS = {"000666.SZ"}
MAX_DELISTED_INDUSTRY_MISSING_EXCEPTION_COUNT = 1
MAX_DELISTED_INDUSTRY_MISSING_EXCEPTION_RATE_PCT = 12.5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the already-materialized A-long 2018-2025 fixed raw panel. "
            "This reads local gitignored raw payloads only; it does not call providers, "
            "fetch data, search signals, calculate alpha, or authorize production use."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.set_defaults(materialization_summary=SUMMARY_PATH, raw_root=RAW_ROOT)
    return parser.parse_args(argv)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def json_default(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_json(schema_path: Path, payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required for schema-gated audit outputs; "
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
    return text if len(text) == 8 and text.isdigit() else None


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d")


def validate_materialization_summary(summary: dict[str, Any]) -> None:
    if summary.get("schema_name") != "a_long_tushare_broader_materialization_execution_summary":
        raise ValueError("materialization summary schema_name mismatch")
    decision = summary.get("decision") or {}
    if decision.get("materialization_status") != "passed_full_period_panel_materialization_shape":
        raise ValueError("full-period materialization summary must pass before raw audit")
    if decision.get("data_can_be_used_for_alpha_now") is not False:
        raise ValueError("materialization summary must not claim alpha readiness")

    execution = summary.get("execution") or {}
    if execution.get("endpoint_results_count") != 71:
        raise ValueError("materialization summary must contain the fixed 71-call panel")
    if execution.get("request_url_logged") is not False or execution.get("token_logged") is not False:
        raise ValueError("materialization summary must stay no-secret/no-url")

    boundary = summary.get("broader_materialization_boundary") or {}
    if boundary.get("materialization_id") != "a_long_tushare_full_period_panel_2018_2025":
        raise ValueError("full-period materialization id mismatch")
    if boundary.get("start_date") != START_DATE or boundary.get("end_date") != END_DATE:
        raise ValueError("full-period date boundary mismatch")
    assert_main_board_only(boundary.get("active_symbols") or [], context="A-long full-period audit summary active_symbols")
    assert_main_board_only(ACTIVE_SYMBOLS, context="A-long full-period audit runner active_symbols")
    if boundary.get("active_symbols") != ACTIVE_SYMBOLS or boundary.get("delisted_symbols") != DELISTED_SYMBOLS:
        raise ValueError("full-period symbols mismatch")
    if boundary.get("benchmark_indices") != BENCHMARKS:
        raise ValueError("full-period benchmark mismatch")
    if boundary.get("not_full_market") is not True or boundary.get("not_full_universe") is not True:
        raise ValueError("full-period audit must remain bounded, not full market/universe")

    rollup = summary.get("table_rollup") or []
    if len(rollup) != 11 or any(item.get("status") != "passed_full_period_panel_shape" for item in rollup):
        raise ValueError("all full-period table rollups must pass materialization shape")


def validate_raw_ref(raw_root: Path, raw_ref: str) -> Path:
    raw_path = Path(raw_ref)
    path = raw_path.resolve() if raw_path.is_absolute() else (ROOT / raw_path).resolve()
    approved = raw_root.resolve()
    try:
        path.relative_to(approved)
    except ValueError as exc:
        raise ValueError(f"raw payload ref escapes approved root: {raw_ref}") from exc
    if not path.exists():
        raise FileNotFoundError(f"raw payload missing: {raw_ref}")
    return path


def load_raw_payloads(summary: dict[str, Any], raw_root: Path) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for item in summary.get("endpoint_results", []):
        raw_ref = item.get("raw_payload_ref")
        if not raw_ref:
            raise ValueError(f"endpoint result lacks raw_payload_ref: {item.get('call_id')}")
        path = validate_raw_ref(raw_root, str(raw_ref))
        payload = read_json(path)
        if payload.get("call_status") != "success":
            raise ValueError(f"raw payload did not succeed: {raw_ref}")
        payloads[str(item["call_id"])] = payload
    return payloads


def records(payloads: dict[str, dict[str, Any]], call_id: str) -> list[dict[str, Any]]:
    value = payloads[call_id].get("records")
    if not isinstance(value, list):
        raise ValueError(f"raw payload records missing for {call_id}")
    return [row for row in value if isinstance(row, dict)]


def call_id_for(table: str, symbol: str) -> str:
    return f"{table}_{symbol.replace('.', '_')}_{FULL_PERIOD_SUFFIX}"


def dividend_call_id(symbol: str) -> str:
    return f"dividend_{symbol.replace('.', '_')}"


def index_call_id(benchmark: str) -> str:
    return f"index_daily_{benchmark.replace('.', '_')}_{FULL_PERIOD_SUFFIX}"


def monthly_last_open_days(payloads: dict[str, dict[str, Any]]) -> list[str]:
    days = sorted(
        {
            str(row["cal_date"])
            for row in records(payloads, "trade_calendar_2018_2025")
            if row.get("is_open") in {1, "1"}
        }
    )
    by_month: dict[str, str] = {}
    for day in days:
        by_month[day[:6]] = day
    return [by_month[month] for month in sorted(by_month)]


def check_record_columns(payloads: dict[str, dict[str, Any]], call_id: str, required: set[str]) -> tuple[bool, list[str]]:
    columns = set(str(column) for column in payloads[call_id].get("columns", []))
    missing = sorted(required - columns)
    return not missing, missing


def make_check(check_id: str, status: str, metrics: dict[str, Any], findings: list[str]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "hard_check": check_id in HARD_CHECK_IDS,
        "blocks_signal_search": True,
        "metrics": metrics,
        "findings": findings,
        "allowed_followup": (
            "If the fixed-panel audit passes, create a separate reviewed signal-search preregistration. "
            "Do not run signal search or claim alpha from this audit report."
        ),
    }


def check_fundamental_pit(payloads: dict[str, dict[str, Any]], as_ofs: list[str]) -> dict[str, Any]:
    missing_columns: list[str] = []
    rows_checked = 0
    valid_ann = 0
    missing_ann = 0
    future_ann_excluded = 0
    asof_selections = 0
    covered_symbols: set[str] = set()
    covered_tables: set[str] = set()

    for table in FUNDAMENTAL_TABLES:
        for symbol in SYMBOLS:
            cid = call_id_for(table, symbol)
            ok, missing = check_record_columns(payloads, cid, {"ts_code", "ann_date", "end_date"})
            if not ok:
                missing_columns.extend(f"{cid}:{field}" for field in missing)
                continue
            grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
            for row in records(payloads, cid):
                rows_checked += 1
                ann_date = normalize_yyyymmdd(row.get("ann_date"))
                end_date = normalize_yyyymmdd(row.get("end_date"))
                if ann_date is None or end_date is None:
                    missing_ann += 1
                    continue
                if ann_date > END_DATE:
                    future_ann_excluded += 1
                    continue
                valid_ann += 1
                covered_symbols.add(symbol)
                covered_tables.add(table)
                grouped[(symbol, end_date)].append(ann_date)
            for ann_dates in grouped.values():
                unique_dates = sorted(set(ann_dates))
                for as_of in as_ofs:
                    if any(date <= as_of for date in unique_dates):
                        asof_selections += 1

    missing_rate_pct = (missing_ann / rows_checked * 100.0) if rows_checked else 0.0
    if missing_columns:
        status = "blocked_missing_required_source"
    elif missing_rate_pct > 5.0:
        status = "fail_data_not_ready"
    else:
        status = "pass_fixed_panel"
    return make_check(
        "fundamental_pit",
        status,
        {
            "rows_checked": rows_checked,
            "valid_ann_date_rows": valid_ann,
            "missing_or_invalid_ann_date_rows": missing_ann,
            "missing_or_invalid_ann_date_exclusion_rate_pct": round(missing_rate_pct, 6),
            "future_ann_date_rows_after_panel_end": future_ann_excluded,
            "future_ann_date_rows_excluded_by_asof_gate": future_ann_excluded,
            "ann_date_asof_gating_feasible": not missing_columns and missing_rate_pct <= 5.0,
            "asof_selection_events_checked": asof_selections,
            "covered_symbol_count": len(covered_symbols),
            "covered_table_count": len(covered_tables),
            "missing_required_columns": missing_columns,
        },
        [
            "Raw full-period fundamentals include ann_date/end_date and can be selected only when ann_date <= as_of.",
            "Rows announced after the fixed panel end are excluded; they are not silent-filled or used early.",
        ],
    )


def row_signature(row: dict[str, Any]) -> str:
    cleaned = {key: value for key, value in row.items() if key not in {"request_url", "token"}}
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True, default=json_default)


def compact_value(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def differing_fields(rows: list[dict[str, Any]]) -> list[str]:
    keys = sorted({key for item in rows for key in item if key not in {"request_url", "token"}})
    out = []
    for key in keys:
        values = {
            json.dumps(compact_value(item.get(key)), ensure_ascii=False, sort_keys=True, default=json_default)
            for item in rows
        }
        if len(values) > 1:
            out.append(key)
    return out


def same_ann_duplicate_resolution(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    fields = differing_fields(rows)
    if not fields:
        return True, []
    if not set(fields).issubset(SAME_ANN_DATE_NON_NULL_PREFERENCE_FIELDS):
        return False, fields
    for field in fields:
        non_null_values = {
            json.dumps(compact_value(row.get(field)), ensure_ascii=False, sort_keys=True, default=json_default)
            for row in rows
            if compact_value(row.get(field)) is not None
        }
        if len(non_null_values) != 1:
            return False, fields
    return True, fields


def check_restatement_revision(payloads: dict[str, dict[str, Any]], as_ofs: list[str]) -> dict[str, Any]:
    groups_checked = 0
    multi_ann_groups = 0
    same_ann_conflicts = 0
    resolved_same_ann_duplicates = 0
    asof_selection_count = 0
    tables_with_f_ann_date: set[str] = set()
    conflict_examples: list[dict[str, Any]] = []
    resolution_examples: list[dict[str, Any]] = []

    for table in FUNDAMENTAL_TABLES:
        by_period: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for symbol in SYMBOLS:
            cid = call_id_for(table, symbol)
            if "f_ann_date" in payloads[cid].get("columns", []):
                tables_with_f_ann_date.add(table)
            for row in records(payloads, cid):
                ann_date = normalize_yyyymmdd(row.get("ann_date"))
                end_date = normalize_yyyymmdd(row.get("end_date"))
                if ann_date and ann_date <= END_DATE and end_date:
                    by_period[(symbol, end_date)].append(row)
        for rows in by_period.values():
            groups_checked += 1
            by_ann: dict[str, set[str]] = defaultdict(set)
            by_ann_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                ann_date = normalize_yyyymmdd(row.get("ann_date")) or ""
                by_ann[ann_date].add(row_signature(row))
                by_ann_rows[ann_date].append(row)
            for ann_date, signatures in by_ann.items():
                if len(signatures) <= 1:
                    continue
                sample_rows = by_ann_rows[ann_date]
                is_resolved, fields = same_ann_duplicate_resolution(sample_rows)
                if is_resolved:
                    resolved_same_ann_duplicates += 1
                    if fields and len(resolution_examples) < 10:
                        first = sample_rows[0]
                        resolution_examples.append(
                            {
                                "table": table,
                                "symbol": first.get("ts_code"),
                                "end_date": normalize_yyyymmdd(first.get("end_date")),
                                "ann_date": ann_date,
                                "row_count": len(sample_rows),
                                "resolution_rule": "prefer_single_non_null_value_when_only_allowed_fields_differ",
                                "resolved_fields": fields,
                            }
                        )
                    continue
                same_ann_conflicts += 1
                if len(conflict_examples) < 10:
                    first = sample_rows[0]
                    conflict_examples.append(
                        {
                            "table": table,
                            "symbol": first.get("ts_code"),
                            "end_date": normalize_yyyymmdd(first.get("end_date")),
                            "ann_date": ann_date,
                            "row_count": len(sample_rows),
                            "differing_fields": fields,
                        }
                    )
            ann_dates = sorted(date for date in by_ann if date)
            if len(ann_dates) > 1:
                multi_ann_groups += 1
            for as_of in as_ofs:
                if any(date <= as_of for date in ann_dates):
                    asof_selection_count += 1

    status = "pass_fixed_panel" if same_ann_conflicts == 0 else "fail_data_not_ready"
    return make_check(
        "restatement_revision_asof",
        status,
        {
            "period_groups_checked": groups_checked,
            "groups_with_multiple_ann_dates": multi_ann_groups,
            "same_ann_date_conflicting_duplicate_groups": same_ann_conflicts,
            "same_ann_date_conflict_examples": conflict_examples,
            "same_ann_date_duplicate_groups_resolved_by_non_null_preference": resolved_same_ann_duplicates,
            "same_ann_date_duplicate_resolution_examples": resolution_examples,
            "same_ann_date_duplicate_resolution_rule": (
                "If duplicated rows share ts_code/end_date/ann_date and differ only in allowed nullable fields "
                "with exactly one non-null value, the audit treats the duplicate as source-complementary and records "
                "a deterministic non-null preference. Any other same-ann-date difference remains a hard failure."
            ),
            "asof_latest_known_selection_events_checked": asof_selection_count,
            "tables_with_f_ann_date_column": sorted(tables_with_f_ann_date),
        },
        [
            "The audit checks period groups and would select latest-known ann_date <= as_of instead of later revised values.",
            "Few or zero restatement groups means no conflicting revision was observed in this fixed panel; it is not a universal provider guarantee.",
        ],
    )


def listing_rows(payloads: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for call_id in ["stock_basic_active_L", "stock_basic_delisted_D"]:
        for row in records(payloads, call_id):
            code = row.get("ts_code")
            if code in SYMBOLS:
                out[str(code)] = row
    return out


def membership_rows(payloads: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in SYMBOLS}
    for row in records(payloads, "index_member_all_sw_membership"):
        code = row.get("ts_code")
        if code in out:
            out[str(code)].append(row)
    return out


def validate_000666_no_industry_source_summary(path: Path = DELISTED_INDUSTRY_EXCEPTION_SOURCE_PATH) -> tuple[bool, str | None]:
    try:
        summary = read_json(path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return False, f"exception source unreadable: {exc.__class__.__name__}"

    if summary.get("schema_name") != "a_long_000666_sw_membership_supplement_execution_summary":
        return False, "exception source schema_name mismatch"
    if ((summary.get("scope") or {}).get("target_symbol")) != "000666.SZ":
        return False, "exception source target mismatch"

    execution = summary.get("execution") or {}
    if execution.get("actual_call_count") != 4 or execution.get("budget_exceeded") is not False:
        return False, "exception source did not complete the fixed 4-call no-budget-overrun probe"
    if execution.get("token_logged") is not False or execution.get("request_url_logged") is not False:
        return False, "exception source logged a token or request URL"

    decision = summary.get("decision") or {}
    if decision.get("supplement_status") != "no_candidate_sw_membership_source_found":
        return False, "exception source did not record no-candidate status"
    if decision.get("candidate_sw_membership_source_found") is not False:
        return False, "exception source did not reject candidate membership source"
    if decision.get("audit_rerun_authorized_by_this_summary") is not False:
        return False, "exception source must not authorize audit rerun"
    if decision.get("signal_search_authorized_by_this_summary") is not False:
        return False, "exception source must not authorize signal search"

    endpoint_results = {
        str(item.get("call_id")): item
        for item in summary.get("endpoint_results", [])
        if isinstance(item, dict)
    }
    stock_basic = endpoint_results.get("stock_basic_000666_delisted_context") or {}
    if stock_basic.get("call_status") != "success" or stock_basic.get("target_match_count") != 1:
        return False, "stock_basic did not confirm the delisted target row"
    value_flags = stock_basic.get("target_value_flags") or {}
    if value_flags.get("industry") is not False or value_flags.get("area") is not False:
        return False, "stock_basic still has a usable industry or area value"

    targeted = endpoint_results.get("index_member_all_000666_ts_code_filter") or {}
    if targeted.get("target_match_count") != 0 or targeted.get("row_count") != 0:
        return False, "targeted index_member_all probe found rows"

    crosscheck = endpoint_results.get("index_member_all_current_universe_crosscheck") or {}
    if crosscheck.get("call_status") != "success" or crosscheck.get("target_match_count") != 0:
        return False, "unfiltered index_member_all crosscheck found the target"

    return True, None


def check_survivorship(payloads: dict[str, dict[str, Any]], as_ofs: list[str]) -> dict[str, Any]:
    listings = listing_rows(payloads)
    missing_symbols = [symbol for symbol in SYMBOLS if symbol not in listings]
    active_status_failures = [
        symbol for symbol in ACTIVE_SYMBOLS if str(listings.get(symbol, {}).get("list_status")) != "L"
    ]
    delisted_status_failures = [
        symbol for symbol in DELISTED_SYMBOLS if str(listings.get(symbol, {}).get("list_status")) != "D"
    ]

    eligible_decisions = 0
    invalid_listing_date_rows = 0
    pre_list_exclusion_count = 0
    post_delist_exclusion_count = 0
    for as_of in as_ofs:
        for symbol, row in listings.items():
            list_date = normalize_yyyymmdd(row.get("list_date"))
            delist_date = normalize_yyyymmdd(row.get("delist_date"))
            if list_date is None:
                invalid_listing_date_rows += 1
                continue
            if as_of < list_date:
                pre_list_exclusion_count += 1
                continue
            if delist_date is not None and as_of >= delist_date:
                post_delist_exclusion_count += 1
                continue
            eligible_decisions += 1

    terminal_metrics: list[dict[str, Any]] = []
    terminal_failures: list[str] = []
    for symbol in DELISTED_SYMBOLS:
        row = listings.get(symbol, {})
        delist_date = normalize_yyyymmdd(row.get("delist_date"))
        terminal_daily = records(payloads, call_id_for("daily", symbol))
        terminal_adj = records(payloads, call_id_for("adj_factor", symbol))
        last_trade_date = max((normalize_yyyymmdd(item.get("trade_date")) for item in terminal_daily), default=None)
        last_adj_date = max((normalize_yyyymmdd(item.get("trade_date")) for item in terminal_adj), default=None)
        terminal_gap_days = None
        terminal_input_ok = False
        if delist_date and last_trade_date and last_adj_date:
            terminal_gap_days = (parse_date(delist_date) - parse_date(last_trade_date)).days
            terminal_input_ok = 0 <= terminal_gap_days <= 90 and last_adj_date >= last_trade_date
        if not terminal_input_ok:
            terminal_failures.append(symbol)
        terminal_metrics.append(
            {
                "symbol": symbol,
                "delist_date": delist_date,
                "last_trade_date": last_trade_date,
                "last_adj_factor_date": last_adj_date,
                "terminal_gap_days": terminal_gap_days,
                "terminal_return_input_available": terminal_input_ok,
            }
        )

    memberships = membership_rows(payloads)
    membership_missing = [symbol for symbol, rows in memberships.items() if not rows]
    exception_source_valid, exception_source_error = validate_000666_no_industry_source_summary()
    delisted_industry_missing_exceptions = [
        symbol
        for symbol in membership_missing
        if symbol in DELISTED_SYMBOLS
        and symbol in DELISTED_INDUSTRY_MISSING_EXCEPTION_SYMBOLS
        and exception_source_valid
    ]
    membership_missing_non_exception = [
        symbol for symbol in membership_missing if symbol not in delisted_industry_missing_exceptions
    ]
    exception_rate_pct = (
        len(delisted_industry_missing_exceptions) / len(SYMBOLS) * 100.0 if SYMBOLS else 0.0
    )
    exception_threshold_passed = (
        len(delisted_industry_missing_exceptions) <= MAX_DELISTED_INDUSTRY_MISSING_EXCEPTION_COUNT
        and exception_rate_pct <= MAX_DELISTED_INDUSTRY_MISSING_EXCEPTION_RATE_PCT
    )
    membership_has_dates = []
    for symbol, rows in memberships.items():
        ok = any(normalize_yyyymmdd(row.get("in_date")) and "l2_code" in row for row in rows)
        if ok:
            membership_has_dates.append(symbol)

    status = (
        "pass_fixed_panel"
        if not missing_symbols
        and not active_status_failures
        and not delisted_status_failures
        and invalid_listing_date_rows == 0
        and not terminal_failures
        and not membership_missing_non_exception
        and exception_threshold_passed
        else "fail_data_not_ready"
    )
    findings = [
        "The fixed active and delisted sample symbols are visible in stock_basic with list/delist dates.",
        "The delisted sample keeps terminal daily/adj_factor inputs near delisting instead of back-deleting the loss window.",
        "This is a bounded fixed-panel universe audit, not a full-market historical universe proof.",
    ]
    if delisted_industry_missing_exceptions:
        findings.append(
            "Reviewed no-source evidence allows the delisted missing-industry exception only for industry-neutralization denominators; returns and risk still keep the delisted symbol."
        )
    return make_check(
        "survivorship_pit_universe",
        status,
        {
            "fixed_symbols_found_in_stock_basic": sorted(listings),
            "missing_fixed_symbols": missing_symbols,
            "active_status_failures": active_status_failures,
            "delisted_status_failures": delisted_status_failures,
            "pit_membership_decisions_checked": eligible_decisions,
            "invalid_membership_decisions": invalid_listing_date_rows,
            "pre_list_exclusion_count": pre_list_exclusion_count,
            "post_delist_exclusion_count": post_delist_exclusion_count,
            "sw_membership_symbols_with_rows": sorted(membership_has_dates),
            "sw_membership_missing_symbols": membership_missing,
            "sw_membership_missing_non_exception_symbols": membership_missing_non_exception,
            "delisted_industry_missing_exception_symbols": delisted_industry_missing_exceptions,
            "delisted_industry_missing_exception_source_ref": display_path(DELISTED_INDUSTRY_EXCEPTION_SOURCE_PATH),
            "delisted_industry_missing_exception_source_valid": exception_source_valid,
            "delisted_industry_missing_exception_source_error": exception_source_error,
            "delisted_industry_missing_exception_count": len(delisted_industry_missing_exceptions),
            "delisted_industry_missing_exception_rate_pct": round(exception_rate_pct, 6),
            "delisted_industry_missing_exception_max_count": MAX_DELISTED_INDUSTRY_MISSING_EXCEPTION_COUNT,
            "delisted_industry_missing_exception_max_rate_pct": MAX_DELISTED_INDUSTRY_MISSING_EXCEPTION_RATE_PCT,
            "delisted_industry_missing_exception_threshold_passed": exception_threshold_passed,
            "industry_normalization_policy": {
                "silent_industry_fill_allowed": False,
                "drop_missing_industry_delisted_from_universe_allowed": False,
                "keep_delisted_symbol_in_returns_and_risk": True,
                "exclude_exception_symbols_from_industry_neutral_denominators": True,
                "exception_requires_reviewed_no_source_summary": True,
                "exception_applies_to_signal_score_only": True,
            },
            "industry_normalization_exclusion_symbols": delisted_industry_missing_exceptions,
            "delisted_symbols_kept_for_returns_and_risk": list(DELISTED_SYMBOLS),
            "delisted_terminal_return_inputs": terminal_metrics,
            "terminal_return_input_failed_symbols": terminal_failures,
        },
        findings,
    )


def valid_date_count(rows: list[dict[str, Any]], field: str) -> int:
    return sum(1 for row in rows if normalize_yyyymmdd(row.get(field)) is not None)


def check_return_benchmark(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    symbol_metrics = []
    failures: list[str] = []
    for symbol in SYMBOLS:
        daily = records(payloads, call_id_for("daily", symbol))
        adj = records(payloads, call_id_for("adj_factor", symbol))
        dividend_cid = dividend_call_id(symbol)
        dividend = records(payloads, dividend_cid)
        daily_dates = {normalize_yyyymmdd(row.get("trade_date")) for row in daily}
        adj_dates = {normalize_yyyymmdd(row.get("trade_date")) for row in adj}
        daily_dates.discard(None)
        adj_dates.discard(None)
        overlap_count = len(daily_dates & adj_dates)
        dividend_columns = set(payloads[dividend_cid].get("columns", []))
        has_dividend_source = {"ann_date", "ex_date"}.issubset(dividend_columns)
        valid_ex_date_count = valid_date_count(dividend, "ex_date")
        ok = bool(daily_dates) and bool(adj_dates) and overlap_count > 0 and has_dividend_source
        if not ok:
            failures.append(symbol)
        symbol_metrics.append(
            {
                "symbol": symbol,
                "daily_row_count": len(daily),
                "adj_factor_row_count": len(adj),
                "daily_adj_overlap_count": overlap_count,
                "dividend_row_count": len(dividend),
                "valid_dividend_ex_date_count": valid_ex_date_count,
                "return_input_shape_ok": ok,
            }
        )

    benchmark_metrics = []
    benchmark_failures: list[str] = []
    first_symbol_dates = {
        normalize_yyyymmdd(row.get("trade_date")) for row in records(payloads, call_id_for("daily", SYMBOLS[0]))
    }
    first_symbol_dates.discard(None)
    for benchmark in BENCHMARKS:
        cid = index_call_id(benchmark)
        rows = records(payloads, cid)
        columns = set(payloads[cid].get("columns", []))
        dates = {normalize_yyyymmdd(row.get("trade_date")) for row in rows}
        dates.discard(None)
        overlap = len(dates & first_symbol_dates)
        ok = {"trade_date", "open", "close"}.issubset(columns) and overlap > 0
        if not ok:
            benchmark_failures.append(benchmark)
        benchmark_metrics.append(
            {
                "benchmark": benchmark,
                "row_count": len(rows),
                "has_open_close": {"open", "close"}.issubset(columns),
                "overlap_with_stock_trade_dates": overlap,
            }
        )

    status = "pass_fixed_panel" if not failures and not benchmark_failures else "fail_data_not_ready"
    return make_check(
        "return_benchmark_measurement_basis",
        status,
        {
            "symbol_return_inputs": symbol_metrics,
            "benchmark_inputs": benchmark_metrics,
            "symbols_with_failed_return_input_shape": failures,
            "benchmarks_with_failed_anchor_input_shape": benchmark_failures,
            "stock_and_benchmark_anchor_policy": "future return calculation must use same entry/exit anchors; this audit checks open/close inputs only and does not calculate returns.",
            "silent_zero_fill_used": False,
        },
        [
            "Raw daily open/close, adj_factor, dividend-source, and benchmark open/close inputs exist for the fixed panel.",
            "No return, benchmark excess, signal, or alpha was calculated in this audit.",
        ],
    )


def eligible_symbols_for_year(payloads: dict[str, dict[str, Any]], year: int) -> list[str]:
    out = []
    year_start = f"{year}0101"
    year_end = f"{year}1231"
    for symbol, row in listing_rows(payloads).items():
        list_date = normalize_yyyymmdd(row.get("list_date"))
        delist_date = normalize_yyyymmdd(row.get("delist_date"))
        if list_date and list_date <= year_end and (delist_date is None or delist_date >= year_start):
            out.append(symbol)
    return sorted(out)


def coverage_by_year(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in range(2018, 2026):
        eligible = eligible_symbols_for_year(payloads, year)
        for table in FUNDAMENTAL_TABLES:
            covered = set()
            for symbol in eligible:
                for row in records(payloads, call_id_for(table, symbol)):
                    ann_date = normalize_yyyymmdd(row.get("ann_date"))
                    if ann_date and START_DATE <= ann_date <= END_DATE and ann_date.startswith(str(year)):
                        covered.add(symbol)
            pct = (len(covered) / len(eligible) * 100.0) if eligible else 0.0
            rows.append(
                {
                    "year": year,
                    "table_id": table,
                    "eligible_symbol_count": len(eligible),
                    "covered_symbol_count": len(covered),
                    "coverage_pct": round(pct, 6),
                    "status": "pass_fixed_panel" if pct >= TEMPORAL_COVERAGE_THRESHOLD_PCT else "below_threshold",
                }
            )
    return rows


def check_temporal_coverage(payloads: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = coverage_by_year(payloads)
    thin = [row for row in rows if row["status"] != "pass_fixed_panel"]
    usable_start_year = None
    for year in range(2018, 2026):
        candidate = [row for row in rows if row["year"] >= year]
        if candidate and all(row["status"] == "pass_fixed_panel" for row in candidate):
            usable_start_year = year
            break
    check = make_check(
        "temporal_coverage_bias",
        "coverage_characterized_fixed_panel",
        {
            "threshold_pct": TEMPORAL_COVERAGE_THRESHOLD_PCT,
            "usable_start_year": usable_start_year,
            "below_threshold_cell_count": len(thin),
            "below_threshold_cells": thin,
        },
        [
            "Coverage is characterized by year and required fundamental table for the fixed 2018-2025 panel.",
            "Low early coverage would narrow the usable signal-search window instead of being silently ignored.",
        ],
    )
    return check, rows


def self_test_payload(call_id: str, columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "call_status": "success",
        "columns": columns,
        "records": rows,
    }


def build_full_period_self_test_payloads() -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {
        "trade_calendar_2018_2025": self_test_payload(
            "trade_calendar_2018_2025",
            ["cal_date", "is_open"],
            [{"cal_date": f"{year}1231", "is_open": "1"} for year in range(2018, 2026)],
        ),
        "stock_basic_active_L": self_test_payload(
            "stock_basic_active_L",
            ["ts_code", "list_status", "list_date", "delist_date"],
            [
                {"ts_code": symbol, "list_status": "L", "list_date": "20000101", "delist_date": None}
                for symbol in ACTIVE_SYMBOLS
            ],
        ),
        "stock_basic_delisted_D": self_test_payload(
            "stock_basic_delisted_D",
            ["ts_code", "list_status", "list_date", "delist_date"],
            [{"ts_code": "000666.SZ", "list_status": "D", "list_date": "19961231", "delist_date": "20231026"}],
        ),
        "index_member_all_sw_membership": self_test_payload(
            "index_member_all_sw_membership",
            ["ts_code", "l2_code", "l2_name", "in_date", "out_date"],
            [
                {"ts_code": symbol, "l2_code": "801010", "l2_name": "Industry", "in_date": "20100101", "out_date": None}
                for symbol in SYMBOLS
            ],
        ),
    }
    for table in FUNDAMENTAL_TABLES:
        columns = ["ts_code", "ann_date", "end_date", "f_ann_date"]
        if table == "income":
            columns += ["revenue", "n_income_attr_p"]
        elif table == "balancesheet":
            columns += ["total_assets", "total_liab", "total_hldr_eqy_exc_min_int"]
        elif table == "cashflow":
            columns += ["n_cashflow_act"]
        else:
            columns += ["roe", "profit_dedt"]
        for symbol in SYMBOLS:
            rows = []
            for year in range(2018, 2026):
                row: dict[str, Any] = {
                    "ts_code": symbol,
                    "ann_date": f"{year}0430",
                    "f_ann_date": f"{year}0430",
                    "end_date": f"{year - 1}1231",
                }
                if table == "income":
                    row.update({"revenue": 1.0, "n_income_attr_p": 1.0})
                elif table == "balancesheet":
                    row.update({"total_assets": 1.0, "total_liab": 0.5, "total_hldr_eqy_exc_min_int": 0.5})
                elif table == "cashflow":
                    row.update({"n_cashflow_act": 1.0})
                else:
                    row.update({"roe": 1.0, "profit_dedt": 1.0})
                rows.append(row)
            payloads[call_id_for(table, symbol)] = self_test_payload(call_id_for(table, symbol), columns, rows)

    price_rows = [{"trade_date": f"{year}1231", "open": 10.0, "close": 10.5} for year in range(2018, 2026)]
    for symbol in SYMBOLS:
        symbol_price_rows = list(price_rows)
        if symbol in DELISTED_SYMBOLS:
            symbol_price_rows = [row for row in price_rows if str(row["trade_date"]) < "20231026"]
            symbol_price_rows.append({"trade_date": "20230831", "open": 8.0, "close": 8.5})
        payloads[call_id_for("daily", symbol)] = self_test_payload(
            call_id_for("daily", symbol),
            ["ts_code", "trade_date", "open", "close"],
            [{"ts_code": symbol, **row} for row in symbol_price_rows],
        )
        payloads[call_id_for("adj_factor", symbol)] = self_test_payload(
            call_id_for("adj_factor", symbol),
            ["ts_code", "trade_date", "adj_factor"],
            [{"ts_code": symbol, "trade_date": row["trade_date"], "adj_factor": 1.0} for row in symbol_price_rows],
        )
        payloads[dividend_call_id(symbol)] = self_test_payload(
            dividend_call_id(symbol),
            ["ts_code", "ann_date", "ex_date"],
            [{"ts_code": symbol, "ann_date": "20200430", "ex_date": "20200701"}],
        )
    payloads[call_id_for("adj_factor", "000666.SZ")]["records"].append(
        {"ts_code": "000666.SZ", "trade_date": "20231025", "adj_factor": 1.0}
    )
    for benchmark in BENCHMARKS:
        payloads[index_call_id(benchmark)] = self_test_payload(
            index_call_id(benchmark),
            ["ts_code", "trade_date", "open", "close"],
            [{"ts_code": benchmark, **row} for row in price_rows],
        )
    return payloads


def full_period_self_test_result(
    *,
    fixture_id: str,
    target_check_id: str,
    check_result: dict[str, Any],
    detected: bool,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "checker_origin": "materialized_full_period_runner",
        "target_check_id": target_check_id,
        "status": "pass" if detected else "fail",
        "detected_expected_violation": detected,
        "observed_check_status": check_result["status"],
        "metrics": metrics or check_result["metrics"],
    }


def run_materialized_runner_self_tests() -> list[dict[str, Any]]:
    base_payloads = build_full_period_self_test_payloads()
    as_ofs = monthly_last_open_days(base_payloads)
    tests: list[dict[str, Any]] = []

    payloads = copy.deepcopy(base_payloads)
    cid = call_id_for("income", "000001.SZ")
    payloads[cid]["columns"] = [column for column in payloads[cid]["columns"] if column != "ann_date"]
    check = check_fundamental_pit(payloads, as_ofs)
    tests.append(
        full_period_self_test_result(
            fixture_id="materialized_full_period_fundamental_missing_ann_date_column_blocks",
            target_check_id="fundamental_pit",
            check_result=check,
            detected=check["status"] == "blocked_missing_required_source"
            and f"{cid}:ann_date" in check["metrics"]["missing_required_columns"],
        )
    )

    payloads = copy.deepcopy(base_payloads)
    cid = call_id_for("income", "000001.SZ")
    payloads[cid]["records"].append(
        {
            "ts_code": "000001.SZ",
            "ann_date": "20200430",
            "f_ann_date": "20200430",
            "end_date": "20191231",
            "revenue": 999.0,
            "n_income_attr_p": 1.0,
        }
    )
    check = check_restatement_revision(payloads, as_ofs)
    tests.append(
        full_period_self_test_result(
            fixture_id="materialized_full_period_restatement_same_ann_date_conflict_fails",
            target_check_id="restatement_revision_asof",
            check_result=check,
            detected=check["status"] == "fail_data_not_ready"
            and check["metrics"]["same_ann_date_conflicting_duplicate_groups"] > 0,
        )
    )

    payloads = copy.deepcopy(base_payloads)
    payloads[call_id_for("daily", "000666.SZ")]["records"] = [
        {"ts_code": "000666.SZ", "trade_date": "20181231", "open": 8.0, "close": 8.5}
    ]
    check = check_survivorship(payloads, as_ofs)
    tests.append(
        full_period_self_test_result(
            fixture_id="materialized_full_period_survivorship_missing_terminal_return_fails",
            target_check_id="survivorship_pit_universe",
            check_result=check,
            detected=check["status"] == "fail_data_not_ready"
            and "000666.SZ" in check["metrics"]["terminal_return_input_failed_symbols"],
        )
    )

    payloads = copy.deepcopy(base_payloads)
    cid = index_call_id("000300.SH")
    payloads[cid]["columns"] = [column for column in payloads[cid]["columns"] if column != "open"]
    check = check_return_benchmark(payloads)
    tests.append(
        full_period_self_test_result(
            fixture_id="materialized_full_period_return_benchmark_missing_open_fails",
            target_check_id="return_benchmark_measurement_basis",
            check_result=check,
            detected=check["status"] == "fail_data_not_ready"
            and "000300.SH" in check["metrics"]["benchmarks_with_failed_anchor_input_shape"],
        )
    )

    payloads = copy.deepcopy(base_payloads)
    for symbol in SYMBOLS:
        cid = call_id_for("income", symbol)
        payloads[cid]["records"] = [row for row in payloads[cid]["records"] if not row["ann_date"].startswith("2018")]
    check, _rows = check_temporal_coverage(payloads)
    tests.append(
        full_period_self_test_result(
            fixture_id="materialized_full_period_temporal_coverage_below_threshold_detected",
            target_check_id="temporal_coverage_bias",
            check_result=check,
            detected=check["metrics"]["below_threshold_cell_count"] > 0,
        )
    )

    return tests


def run_required_self_tests(preregistration: dict[str, Any]) -> list[dict[str, Any]]:
    legacy_tests = []
    for item in base_audit.run_required_self_tests(preregistration):
        copied = dict(item)
        copied["checker_origin"] = "legacy_preregistration_base_audit"
        legacy_tests.append(copied)
    return legacy_tests + run_materialized_runner_self_tests()


def decision_from_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check["check_id"] for check in checks if check["hard_check"] and check["status"] == "fail_data_not_ready"]
    blocked = [check["check_id"] for check in checks if check["hard_check"] and check["status"] == "blocked_missing_required_source"]
    coverage = next(check for check in checks if check["check_id"] == "temporal_coverage_bias")
    usable_start_year = coverage["metrics"].get("usable_start_year")
    below_threshold_count = coverage["metrics"].get("below_threshold_cell_count", 0)

    if blocked:
        status = "blocked_missing_required_source"
        plain = "全周期固定 panel 审计没过：仍缺必须数据。不能找 alpha。"
        next_action = "先修缺失数据来源，再重新审计。"
        may_preregister = False
        hard_checks_pass = False
    elif failed:
        status = "fail_data_not_ready"
        survivorship = next(check for check in checks if check["check_id"] == "survivorship_pit_universe")
        membership_missing = survivorship["metrics"].get("sw_membership_missing_symbols", [])
        if failed == ["survivorship_pit_universe"] and membership_missing:
            plain = (
                "全周期固定 panel 只剩一个硬缺口：退市样本 "
                f"{', '.join(membership_missing)} 没有 SW 行业成员记录。不能找 alpha。"
            )
            next_action = "先补可审的退市股 SW 行业来源；补不到就必须继续阻塞 A-long 行业归一化信号搜索。"
        else:
            plain = "全周期固定 panel 审计发现硬错误。不能找 alpha。"
            next_action = "先修失败的字段或口径，再重新审计。"
        may_preregister = False
        hard_checks_pass = False
    elif usable_start_year is None:
        status = "fail_data_not_ready"
        plain = "全周期固定 panel 硬检查通过，但覆盖率无法给出可用起点。不能找 alpha。"
        next_action = "先修覆盖率来源或缩小窗口，再重新审计。"
        may_preregister = False
        hard_checks_pass = True
    elif below_threshold_count:
        status = "pass_hard_checks_with_limited_usable_window"
        plain = f"全周期固定 panel 硬检查通过，但只能从 {usable_start_year} 年开始考虑信号预注册。"
        next_action = "下一步可写单独的 A-long 信号搜索预注册，但窗口必须从审计给出的可用年份开始。"
        may_preregister = True
        hard_checks_pass = True
    else:
        status = "passed_fixed_panel_data_integrity_for_signal_preregistration"
        plain = "全周期固定 panel 数据审计通过。可以进入下一步：写信号搜索预注册。"
        next_action = "下一步是单独写 A-long 信号搜索预注册；还不能直接跑信号、声称 alpha 或实盘。"
        may_preregister = True
        hard_checks_pass = True

    return {
        "audit_status": status,
        "hard_checks_pass": hard_checks_pass,
        "usable_start_year": usable_start_year,
        "data_can_be_used_for_alpha_now": False,
        "signal_search_preregistration_may_be_created": may_preregister,
        "signal_search_authorized_by_this_report": False,
        "alpha_found": False,
        "plain_result": plain,
        "next_action": next_action,
    }


def build_report(*, summary_path: Path, raw_root: Path, output_dir: Path, generated_at: str) -> dict[str, Any]:
    summary = read_json(summary_path)
    validate_materialization_summary(summary)
    payloads = load_raw_payloads(summary, raw_root)
    as_ofs = monthly_last_open_days(payloads)
    preregistration = read_json(PREREGISTRATION_PATH)
    self_tests = run_required_self_tests(preregistration)

    checks = [
        check_fundamental_pit(payloads, as_ofs),
        check_restatement_revision(payloads, as_ofs),
        check_survivorship(payloads, as_ofs),
        check_return_benchmark(payloads),
    ]
    coverage_check, coverage_rows = check_temporal_coverage(payloads)
    checks.append(coverage_check)

    return {
        "schema_name": "a_long_materialized_full_period_data_integrity_audit_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_materialized_full_period_data_integrity_audit_report_20260604",
        "source_refs": [
            "docs/a_long_tushare_broader_materialization_execution_summary_20260604.json",
            "research/preregistrations/a_long_data_integrity_audit_20260603.json",
            "docs/system_risk_register.md",
        ],
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_materialized_full_period_data_integrity_audit",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "materialized_raw_read_only": True,
            "provider_call_executed": False,
            "data_fetch_executed": False,
            "raw_rows_in_tracked_report": False,
            "signal_search_executed": False,
            "alpha_backtest_executed": False,
            "production_use_allowed": False,
            "ship_gate_claim_allowed": False,
            "full_size_manual_use_allowed": False,
            "broker_or_order_automation_allowed": False,
            "manual_order_only": True,
        },
        "execution": {
            "materialization_summary_ref": "docs/a_long_tushare_broader_materialization_execution_summary_20260604.json",
            "raw_root": RAW_ROOT_REL.as_posix() + "/",
            "raw_payload_count": len(payloads),
            "network_calls_executed": 0,
            "provider_calls_executed": 0,
            "self_tests_required": len(self_tests),
            "self_tests_passed": len([item for item in self_tests if item["status"] == "pass"]),
            "tracked_report_contains_raw_records": False,
            "tracked_report_contains_secret": False,
            "tracked_report_contains_request_url": False,
        },
        "fixed_panel_boundary": {
            "panel_id": "a_long_tushare_full_period_panel_2018_2025",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "active_symbols": list(ACTIVE_SYMBOLS),
            "delisted_symbols": list(DELISTED_SYMBOLS),
            "benchmark_indices": list(BENCHMARKS),
            "monthly_as_of_count": len(as_ofs),
            "not_full_market": True,
            "not_full_universe": True,
        },
        "required_runner_self_tests": self_tests,
        "check_results": checks,
        "coverage_by_year": coverage_rows,
        "decision": decision_from_checks(checks),
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "signal_search_executed": False,
            "signal_search_authorized": False,
            "alpha_backtest_executed": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "provider_selected": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "result_artifacts": [
            display_path(output_dir / "audit_report.json"),
            display_path(output_dir / "check_summary.csv"),
            display_path(output_dir / "coverage_by_year.csv"),
        ],
        "limitations": [
            "This audit reads only the bounded nine-symbol 2018-2025 fixed panel, not the full A-share market or full A-long universe.",
            "A pass permits only the next reviewed signal-search preregistration step; it does not run signal search or prove alpha.",
            "No provider call, data fetch, return calculation, alpha backtest, DataHub, production use, ship-gate claim, full-size use, or broker/order automation is authorized.",
        ],
    }


def check_summary_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "check_id": item["check_id"],
            "status": item["status"],
            "hard_check": item["hard_check"],
            "blocks_signal_search": item["blocks_signal_search"],
            "finding_count": len(item["findings"]),
        }
        for item in report["check_results"]
    ]


def run(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = args.generated_at or iso_now()
    report = build_report(
        summary_path=args.materialization_summary,
        raw_root=args.raw_root,
        output_dir=args.output_dir,
        generated_at=generated_at,
    )
    validate_json(SCHEMA_PATH, report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "audit_report.json", report)
    write_csv(args.output_dir / "check_summary.csv", check_summary_rows(report))
    write_csv(args.output_dir / "coverage_by_year.csv", report["coverage_by_year"])
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(args)
    decision = report["decision"]
    print(
        json.dumps(
            {
                "audit_status": decision["audit_status"],
                "plain_result": decision["plain_result"],
                "next_action": decision["next_action"],
                "report_ref": display_path(args.output_dir / "audit_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
