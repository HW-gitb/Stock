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


SUMMARY_PATH = ROOT / "docs" / "a_long_tushare_incremental_materialization_execution_summary_20260604.json"
RAW_ROOT_REL = Path("data/a_long/raw/tushare/materialization_thin_slice_20260604")
RAW_ROOT = ROOT / RAW_ROOT_REL
OUTPUT_DIR = ROOT / "research" / "results" / "a_long_materialized_thin_slice_data_integrity_audit_20260604"
REPORT_PATH = OUTPUT_DIR / "audit_report.json"
SCHEMA_PATH = ROOT / "schemas" / "a_long_materialized_thin_slice_data_integrity_audit_report.schema.json"
PREREGISTRATION_PATH = ROOT / "research" / "preregistrations" / "a_long_data_integrity_audit_20260603.json"

START_DATE = "20220101"
END_DATE = "20231231"
SYMBOLS = ["000001.SZ", "600519.SH", "000666.SZ"]
DELISTED_SYMBOL = "000666.SZ"
BENCHMARKS = ["000300.SH", "000852.SH"]
FUNDAMENTAL_TABLES = ["income", "balancesheet", "cashflow", "fina_indicator"]
CHECK_IDS = [
    "fundamental_pit",
    "restatement_revision_asof",
    "survivorship_pit_universe",
    "return_benchmark_measurement_basis",
    "temporal_coverage_bias",
]
HARD_CHECK_IDS = set(CHECK_IDS) - {"temporal_coverage_bias"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the already-materialized A-long 2022-2023 raw thin slice. "
            "This reads local gitignored raw payloads only; it does not call providers, "
            "rerun full materialization, search signals, or calculate alpha."
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
    if summary.get("schema_name") != "a_long_tushare_incremental_materialization_execution_summary":
        raise ValueError("materialization summary schema_name mismatch")
    decision = summary.get("decision") or {}
    if decision.get("materialization_status") != "passed_thin_slice_materialization_shape":
        raise ValueError("materialization summary must pass before raw audit")
    execution = summary.get("execution") or {}
    if execution.get("new_network_call_count", 0) + execution.get("reused_raw_payload_count", 0) != 29:
        raise ValueError("materialization summary must contain the fixed 29-call thin slice")
    if execution.get("request_url_logged") is not False or execution.get("token_logged") is not False:
        raise ValueError("materialization summary must stay no-secret/no-url")
    boundary = summary.get("thin_slice_boundary") or {}
    if boundary.get("start_date") != START_DATE or boundary.get("end_date") != END_DATE:
        raise ValueError("thin-slice date boundary mismatch")
    if boundary.get("active_symbols") != SYMBOLS[:2] or boundary.get("delisted_symbols") != [DELISTED_SYMBOL]:
        raise ValueError("thin-slice symbols mismatch")
    if boundary.get("benchmark_indices") != BENCHMARKS:
        raise ValueError("thin-slice benchmark mismatch")


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
    return f"{table}_{symbol.replace('.', '_')}_2022_2023"


def monthly_last_open_days(payloads: dict[str, dict[str, Any]]) -> list[str]:
    days = sorted({str(row["cal_date"]) for row in records(payloads, "trade_calendar_2022_2023") if row.get("is_open") in {1, "1"}})
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
            "Use this thin-slice result only to justify a reviewed broader materialization/audit step; "
            "do not start signal search from it."
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
                valid_ann += 1
                covered_symbols.add(symbol)
                covered_tables.add(table)
                grouped[(symbol, end_date)].append(ann_date)
                if ann_date > END_DATE:
                    future_ann_excluded += 1
            for ann_dates in grouped.values():
                unique_dates = sorted(set(ann_dates))
                for as_of in as_ofs:
                    eligible_dates = [date for date in unique_dates if date <= as_of]
                    if eligible_dates:
                        asof_selections += 1

    missing_rate_pct = (missing_ann / rows_checked * 100.0) if rows_checked else 0.0
    if missing_columns:
        status = "blocked_missing_required_source"
    elif missing_rate_pct > 5.0:
        status = "fail_data_not_ready"
    else:
        status = "pass_thin_slice"
    return make_check(
        "fundamental_pit",
        status,
        {
            "rows_checked": rows_checked,
            "valid_ann_date_rows": valid_ann,
            "missing_or_invalid_ann_date_rows": missing_ann,
            "missing_or_invalid_ann_date_exclusion_rate_pct": round(missing_rate_pct, 6),
            "future_ann_date_rows_after_slice_end": future_ann_excluded,
            "future_ann_date_rows_excluded_by_asof_gate": future_ann_excluded,
            "ann_date_asof_gating_feasible": not missing_columns and missing_rate_pct <= 5.0,
            "asof_selection_events_checked": asof_selections,
            "covered_symbol_count": len(covered_symbols),
            "covered_table_count": len(covered_tables),
            "missing_required_columns": missing_columns,
        },
        [
            "Raw thin-slice fundamentals include ann_date/end_date and this runner selects only rows with ann_date <= each fixed as_of.",
            "This proves ann_date-gating feasibility for this audit; future signal backtests must enforce the same gate before alpha claims.",
        ],
    )


def row_signature(row: dict[str, Any]) -> str:
    cleaned = {key: value for key, value in row.items() if key not in {"request_url", "token"}}
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True, default=json_default)


def check_restatement_revision(payloads: dict[str, dict[str, Any]], as_ofs: list[str]) -> dict[str, Any]:
    groups_checked = 0
    multi_ann_groups = 0
    same_ann_conflicts = 0
    asof_selection_count = 0

    for table in FUNDAMENTAL_TABLES:
        by_period: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for symbol in SYMBOLS:
            for row in records(payloads, call_id_for(table, symbol)):
                ann_date = normalize_yyyymmdd(row.get("ann_date"))
                end_date = normalize_yyyymmdd(row.get("end_date"))
                if ann_date and end_date:
                    by_period[(symbol, end_date)].append(row)
        for rows in by_period.values():
            groups_checked += 1
            by_ann: dict[str, set[str]] = defaultdict(set)
            for row in rows:
                by_ann[normalize_yyyymmdd(row.get("ann_date")) or ""].add(row_signature(row))
            same_ann_conflicts += sum(1 for signatures in by_ann.values() if len(signatures) > 1)
            ann_dates = sorted(date for date in by_ann if date)
            if len(ann_dates) > 1:
                multi_ann_groups += 1
            for as_of in as_ofs:
                if any(date <= as_of for date in ann_dates):
                    asof_selection_count += 1

    status = "pass_thin_slice" if same_ann_conflicts == 0 else "fail_data_not_ready"
    return make_check(
        "restatement_revision_asof",
        status,
        {
            "period_groups_checked": groups_checked,
            "groups_with_multiple_ann_dates": multi_ann_groups,
            "same_ann_date_conflicting_duplicate_groups": same_ann_conflicts,
            "asof_latest_known_selection_events_checked": asof_selection_count,
        },
        [
            "The runner selected latest-known ann_date <= as_of from raw period groups and found no conflicting same-ann_date duplicates.",
            "A thin slice with few/no restatement groups is not full restatement proof.",
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


def check_survivorship(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    listings = listing_rows(payloads)
    missing_symbols = [symbol for symbol in SYMBOLS if symbol not in listings]
    active_status_ok = all(str(listings.get(symbol, {}).get("list_status")) == "L" for symbol in SYMBOLS[:2])
    delisted_row = listings.get(DELISTED_SYMBOL, {})
    delisted_status_ok = str(delisted_row.get("list_status")) == "D"
    delist_date = normalize_yyyymmdd(delisted_row.get("delist_date"))
    terminal_daily = records(payloads, call_id_for("daily", DELISTED_SYMBOL))
    terminal_adj = records(payloads, call_id_for("adj_factor", DELISTED_SYMBOL))
    last_trade_date = max((normalize_yyyymmdd(row.get("trade_date")) for row in terminal_daily), default=None)
    last_adj_date = max((normalize_yyyymmdd(row.get("trade_date")) for row in terminal_adj), default=None)
    terminal_gap_days = None
    terminal_input_ok = False
    if delist_date and last_trade_date and last_adj_date:
        terminal_gap_days = (parse_date(delist_date) - parse_date(last_trade_date)).days
        terminal_input_ok = 0 <= terminal_gap_days <= 90 and last_adj_date >= last_trade_date

    status = (
        "pass_thin_slice"
        if not missing_symbols and active_status_ok and delisted_status_ok and terminal_input_ok
        else "fail_data_not_ready"
    )
    return make_check(
        "survivorship_pit_universe",
        status,
        {
            "fixed_symbols_found_in_stock_basic": sorted(listings),
            "missing_fixed_symbols": missing_symbols,
            "active_symbols_status_ok": active_status_ok,
            "delisted_symbol_status_ok": delisted_status_ok,
            "delisted_symbol": DELISTED_SYMBOL,
            "delist_date": delist_date,
            "last_trade_date": last_trade_date,
            "last_adj_factor_date": last_adj_date,
            "terminal_gap_days": terminal_gap_days,
            "terminal_return_input_available": terminal_input_ok,
        },
        [
            "The fixed active and delisted sample symbols are visible in raw stock_basic rows.",
            "The delisted sample has terminal daily and adj_factor inputs close enough to delisting for later return measurement.",
            "This is not a full PIT universe proof.",
        ],
    )


def valid_date_count(rows: list[dict[str, Any]], field: str) -> int:
    return sum(1 for row in rows if normalize_yyyymmdd(row.get(field)) is not None)


def check_return_benchmark(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    symbol_metrics = []
    failures: list[str] = []
    for symbol in SYMBOLS:
        daily = records(payloads, call_id_for("daily", symbol))
        adj = records(payloads, call_id_for("adj_factor", symbol))
        dividend = records(payloads, f"dividend_{symbol.replace('.', '_')}")
        daily_dates = {normalize_yyyymmdd(row.get("trade_date")) for row in daily}
        adj_dates = {normalize_yyyymmdd(row.get("trade_date")) for row in adj}
        daily_dates.discard(None)
        adj_dates.discard(None)
        overlap_count = len(daily_dates & adj_dates)
        has_dividend_source = len(dividend) > 0 and "ann_date" in payloads[f"dividend_{symbol.replace('.', '_')}"].get("columns", [])
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
        cid = f"index_daily_{benchmark.replace('.', '_')}_2022_2023"
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

    status = "pass_thin_slice" if not failures and not benchmark_failures else "fail_data_not_ready"
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
            "Raw daily open/close, adj_factor, dividend-source, and benchmark open/close inputs exist for the thin slice.",
            "No return or benchmark excess was calculated in this audit.",
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
    for year in [2022, 2023]:
        eligible = eligible_symbols_for_year(payloads, year)
        for table in FUNDAMENTAL_TABLES:
            covered = set()
            for symbol in eligible:
                for row in records(payloads, call_id_for(table, symbol)):
                    ann_date = normalize_yyyymmdd(row.get("ann_date"))
                    if ann_date and ann_date.startswith(str(year)):
                        covered.add(symbol)
            pct = (len(covered) / len(eligible) * 100.0) if eligible else 0.0
            rows.append(
                {
                    "year": year,
                    "table_id": table,
                    "eligible_symbol_count": len(eligible),
                    "covered_symbol_count": len(covered),
                    "coverage_pct": round(pct, 6),
                    "status": "pass_thin_slice" if pct >= 80.0 else "thin_slice_below_threshold",
                }
            )
    return rows


def check_temporal_coverage(payloads: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = coverage_by_year(payloads)
    thin = [row for row in rows if row["status"] != "pass_thin_slice"]
    usable_start_year = None
    for year in [2022, 2023]:
        if all(row["status"] == "pass_thin_slice" for row in rows if row["year"] >= year):
            usable_start_year = year
            break
    check = make_check(
        "temporal_coverage_bias",
        "coverage_characterized_thin_slice",
        {
            "threshold_pct": 80,
            "thin_slice_usable_start_year": usable_start_year,
            "below_threshold_cell_count": len(thin),
            "below_threshold_cells": thin,
        },
        [
            "Coverage is characterized only for the 2022-2023 three-symbol thin slice.",
            "A full signal-search window still requires full-period PIT coverage characterization.",
        ],
    )
    return check, rows


def self_test_payload(
    call_id: str,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "call_status": "success",
        "columns": columns,
        "records": rows,
    }


def build_materialized_self_test_payloads() -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {
        "trade_calendar_2022_2023": self_test_payload(
            "trade_calendar_2022_2023",
            ["cal_date", "is_open"],
            [
                {"cal_date": "20220131", "is_open": "1"},
                {"cal_date": "20221230", "is_open": "1"},
                {"cal_date": "20230131", "is_open": "1"},
                {"cal_date": "20231229", "is_open": "1"},
            ],
        ),
        "stock_basic_active_L": self_test_payload(
            "stock_basic_active_L",
            ["ts_code", "list_status", "list_date", "delist_date"],
            [
                {"ts_code": "000001.SZ", "list_status": "L", "list_date": "19910403", "delist_date": None},
                {"ts_code": "600519.SH", "list_status": "L", "list_date": "20010827", "delist_date": None},
            ],
        ),
        "stock_basic_delisted_D": self_test_payload(
            "stock_basic_delisted_D",
            ["ts_code", "list_status", "list_date", "delist_date"],
            [{"ts_code": DELISTED_SYMBOL, "list_status": "D", "list_date": "19961231", "delist_date": "20230920"}],
        ),
    }

    for table in FUNDAMENTAL_TABLES:
        columns = ["ts_code", "ann_date", "end_date"]
        if table == "income":
            columns += ["revenue", "n_income_attr_p"]
        elif table == "balancesheet":
            columns += ["total_assets", "total_liab", "total_hldr_eqy_exc_min_int"]
        elif table == "cashflow":
            columns += ["n_cashflow_act"]
        else:
            columns += ["roe", "profit_dedt"]
        for symbol in SYMBOLS:
            rows: list[dict[str, Any]] = []
            for ann_date, end_date in [("20220430", "20211231"), ("20230430", "20221231")]:
                row: dict[str, Any] = {"ts_code": symbol, "ann_date": ann_date, "end_date": end_date}
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

    price_rows = [
        {"trade_date": "20220131", "open": 10.0, "close": 10.5},
        {"trade_date": "20221230", "open": 11.0, "close": 11.5},
        {"trade_date": "20230131", "open": 12.0, "close": 12.5},
        {"trade_date": "20230831", "open": 8.0, "close": 8.5},
    ]
    for symbol in SYMBOLS:
        payloads[call_id_for("daily", symbol)] = self_test_payload(
            call_id_for("daily", symbol),
            ["ts_code", "trade_date", "open", "close"],
            [{"ts_code": symbol, **row} for row in price_rows],
        )
        payloads[call_id_for("adj_factor", symbol)] = self_test_payload(
            call_id_for("adj_factor", symbol),
            ["ts_code", "trade_date", "adj_factor"],
            [{"ts_code": symbol, "trade_date": row["trade_date"], "adj_factor": 1.0} for row in price_rows],
        )
        payloads[f"dividend_{symbol.replace('.', '_')}"] = self_test_payload(
            f"dividend_{symbol.replace('.', '_')}",
            ["ts_code", "ann_date", "ex_date"],
            [{"ts_code": symbol, "ann_date": "20220430", "ex_date": "20220701"}],
        )

    for benchmark in BENCHMARKS:
        payloads[f"index_daily_{benchmark.replace('.', '_')}_2022_2023"] = self_test_payload(
            f"index_daily_{benchmark.replace('.', '_')}_2022_2023",
            ["ts_code", "trade_date", "open", "close"],
            [{"ts_code": benchmark, **row} for row in price_rows],
        )
    return payloads


def materialized_self_test_result(
    *,
    fixture_id: str,
    target_check_id: str,
    check_result: dict[str, Any],
    detected: bool,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "checker_origin": "materialized_thin_slice_runner",
        "target_check_id": target_check_id,
        "status": "pass" if detected else "fail",
        "detected_expected_violation": detected,
        "observed_check_status": check_result["status"],
        "metrics": metrics or check_result["metrics"],
    }


def run_materialized_runner_self_tests() -> list[dict[str, Any]]:
    base_payloads = build_materialized_self_test_payloads()
    as_ofs = monthly_last_open_days(base_payloads)
    tests: list[dict[str, Any]] = []

    payloads = copy.deepcopy(base_payloads)
    cid = call_id_for("income", "000001.SZ")
    payloads[cid]["columns"] = [column for column in payloads[cid]["columns"] if column != "ann_date"]
    check = check_fundamental_pit(payloads, as_ofs)
    tests.append(
        materialized_self_test_result(
            fixture_id="materialized_fundamental_missing_ann_date_column_blocks",
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
            "ann_date": "20220430",
            "end_date": "20211231",
            "revenue": 999.0,
            "n_income_attr_p": 1.0,
        }
    )
    check = check_restatement_revision(payloads, as_ofs)
    tests.append(
        materialized_self_test_result(
            fixture_id="materialized_restatement_same_ann_date_conflict_fails",
            target_check_id="restatement_revision_asof",
            check_result=check,
            detected=check["status"] == "fail_data_not_ready"
            and check["metrics"]["same_ann_date_conflicting_duplicate_groups"] > 0,
        )
    )

    payloads = copy.deepcopy(base_payloads)
    payloads[call_id_for("daily", DELISTED_SYMBOL)]["records"] = [
        {"ts_code": DELISTED_SYMBOL, "trade_date": "20220131", "open": 8.0, "close": 8.5}
    ]
    check = check_survivorship(payloads)
    tests.append(
        materialized_self_test_result(
            fixture_id="materialized_survivorship_missing_terminal_return_fails",
            target_check_id="survivorship_pit_universe",
            check_result=check,
            detected=check["status"] == "fail_data_not_ready"
            and check["metrics"]["terminal_return_input_available"] is False,
        )
    )

    payloads = copy.deepcopy(base_payloads)
    cid = "index_daily_000300_SH_2022_2023"
    payloads[cid]["columns"] = [column for column in payloads[cid]["columns"] if column != "open"]
    check = check_return_benchmark(payloads)
    tests.append(
        materialized_self_test_result(
            fixture_id="materialized_return_benchmark_missing_open_fails",
            target_check_id="return_benchmark_measurement_basis",
            check_result=check,
            detected=check["status"] == "fail_data_not_ready"
            and "000300.SH" in check["metrics"]["benchmarks_with_failed_anchor_input_shape"],
        )
    )

    payloads = copy.deepcopy(base_payloads)
    for symbol in SYMBOLS:
        cid = call_id_for("income", symbol)
        payloads[cid]["records"] = [row for row in payloads[cid]["records"] if row["ann_date"] != "20220430"]
    check, _rows = check_temporal_coverage(payloads)
    tests.append(
        materialized_self_test_result(
            fixture_id="materialized_temporal_coverage_below_threshold_detected",
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
    materialized_tests = run_materialized_runner_self_tests()
    return legacy_tests + materialized_tests


def decision_from_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check["check_id"] for check in checks if check["status"] == "fail_data_not_ready"]
    blocked = [check["check_id"] for check in checks if check["status"] == "blocked_missing_required_source"]
    if blocked:
        status = "blocked_missing_required_source"
        plain = "小切片审计没过：仍缺必须的数据来源。不能找 alpha。"
        next_action = "先修数据来源，再重新审计；不要全量放大或找信号。"
    elif failed:
        status = "fail_data_not_ready"
        plain = "小切片审计发现硬错误。不能找 alpha。"
        next_action = "先修失败的字段/逻辑，再重新审计；不要全量放大或找信号。"
    else:
        status = "passed_thin_slice_data_integrity_not_alpha_ready"
        plain = "小切片数据审计通过，但还不能找 alpha。"
        next_action = "下一步是另起 reviewed full-period/incremental materialization packet，再做完整数据审计。"
    return {
        "audit_status": status,
        "thin_slice_checks_pass": not failed and not blocked,
        "data_can_be_used_for_alpha_now": False,
        "full_materialization_authorized_by_this_report": False,
        "signal_search_authorized_by_this_report": False,
        "alpha_found": False,
        "plain_result": plain,
        "next_action": next_action,
    }


def build_report(
    *,
    summary_path: Path,
    raw_root: Path,
    output_dir: Path,
    generated_at: str,
) -> dict[str, Any]:
    summary = read_json(summary_path)
    validate_materialization_summary(summary)
    payloads = load_raw_payloads(summary, raw_root)
    as_ofs = monthly_last_open_days(payloads)
    preregistration = read_json(PREREGISTRATION_PATH)
    self_tests = run_required_self_tests(preregistration)

    checks = [
        check_fundamental_pit(payloads, as_ofs),
        check_restatement_revision(payloads, as_ofs),
        check_survivorship(payloads),
        check_return_benchmark(payloads),
    ]
    coverage_check, coverage_rows = check_temporal_coverage(payloads)
    checks.append(coverage_check)

    return {
        "schema_name": "a_long_materialized_thin_slice_data_integrity_audit_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": "a_long_materialized_thin_slice_data_integrity_audit_report_20260604",
        "source_refs": [
            "docs/a_long_tushare_incremental_materialization_execution_summary_20260604.json",
            "research/preregistrations/a_long_data_integrity_audit_20260603.json",
            "docs/system_risk_register.md",
        ],
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_materialized_thin_slice_data_integrity_audit",
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
            "materialization_summary_ref": "docs/a_long_tushare_incremental_materialization_execution_summary_20260604.json",
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
        "thin_slice_boundary": {
            "slice_id": "a_long_tushare_thin_slice_2022_2023",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "symbols": list(SYMBOLS),
            "benchmark_indices": list(BENCHMARKS),
            "not_full_market": True,
            "not_full_2018_2025": True,
        },
        "required_runner_self_tests": self_tests,
        "check_results": checks,
        "coverage_by_year": coverage_rows,
        "decision": decision_from_checks(checks),
        "prohibited_claims": {
            "a_long_data_ready": False,
            "a_long_alpha_found": False,
            "signal_search_authorized": False,
            "full_materialization_done": False,
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
            "This audit reads only the 2022-2023 three-symbol materialized raw thin slice.",
            "A pass proves thin-slice PIT/survivorship/return-input mechanics only; it does not prove full-universe or full-period data integrity.",
            "No provider call, data fetch, return calculation, signal search, alpha backtest, DataHub, production use, ship-gate claim, full-size use, or broker/order automation is authorized.",
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
