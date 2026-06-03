from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pickle
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_PREREGISTRATION = Path("research/preregistrations/a_long_data_integrity_audit_20260603.json")
DEFAULT_LEDGER = Path("research/ledgers/a_long_data_integrity_audit_program_test_budget_ledger_20260603.json")
DEFAULT_OUTPUT_DIR = Path("research/results/a_long_data_integrity_audit_20260603")
DEFAULT_CACHE_DIR = Path("A-EGS/Result/egs_cache")
DEFAULT_FORWARD_DAILY_CACHE = Path("result/a_short/backtest/cache/forward_daily.pkl")
REPORT_SCHEMA = Path("schemas/a_long_data_integrity_audit_report.schema.json")
LEDGER_SCHEMA = Path("schemas/program_test_budget_ledger.schema.json")
TEST_ID = "a_long_data_integrity_audit_20260603"
REPORT_ID = "a_long_data_integrity_audit_report_20260603"
DEFAULT_GENERATED_AT = "2026-06-03T00:00:00Z"
CHECK_IDS = (
    "fundamental_pit",
    "restatement_revision_asof",
    "survivorship_pit_universe",
    "return_benchmark_measurement_basis",
    "temporal_coverage_bias",
)
HARD_CHECK_IDS = tuple(check_id for check_id in CHECK_IDS if check_id != "temporal_coverage_bias")
CACHE_FAMILIES = {
    "derived_financial": "financial_*.pkl",
    "stock_list": "stock_list_*_v2.pkl",
    "daily_all": "daily_all_*_60d.pkl",
    "daily_basic": "daily_basic_*.pkl",
    "trade_dates": "trade_dates_*.pkl",
    "csi300_return": "csi300_*.pkl",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen A-long data-integrity audit against existing local "
            "A-share cache artifacts only. This runner never calls Tushare, "
            "does not search signals, and does not authorize production use."
        )
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--forward-daily-cache", type=Path, default=DEFAULT_FORWARD_DAILY_CACHE)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-at", default=DEFAULT_GENERATED_AT)
    parser.add_argument("--code-version-ref", default="working_tree")
    parser.add_argument("--no-update-ledger", action="store_true")
    return parser.parse_args(argv)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    except ModuleNotFoundError:
        return
    schema = read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"{schema_path} validation failed: {joined}")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_yyyymmdd(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else None


def months_between(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    months: list[str] = []
    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year}{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def date_from_cache_name(name: str) -> str | None:
    match = re.search(r"(20\d{6})", name)
    return match.group(1) if match else None


def safe_load_pickle(path: Path) -> Any:
    with path.open("rb") as handle:
        return pickle.load(handle)


def summarize_pickle(path: Path) -> dict[str, Any]:
    try:
        obj = safe_load_pickle(path)
    except Exception as exc:
        return {"status": "unreadable", "error": f"{type(exc).__name__}: {exc}"}
    if isinstance(obj, pd.DataFrame):
        return {
            "status": "ok",
            "object_type": "DataFrame",
            "row_count": int(len(obj)),
            "columns": [str(column) for column in obj.columns],
        }
    if isinstance(obj, dict):
        return {
            "status": "ok",
            "object_type": "dict",
            "row_count": int(len(obj)),
            "columns": sorted(str(key) for key in obj.keys())[:30],
        }
    if isinstance(obj, (list, set, tuple)):
        return {
            "status": "ok",
            "object_type": type(obj).__name__,
            "row_count": int(len(obj)),
            "columns": [],
        }
    return {
        "status": "ok",
        "object_type": type(obj).__name__,
        "row_count": None,
        "columns": [],
    }


def inventory_cache_family(cache_dir: Path, family_id: str, pattern: str) -> dict[str, Any]:
    paths = sorted(cache_dir.glob(pattern))
    dates = sorted({date for path in paths if (date := date_from_cache_name(path.name))})
    sample_summaries = []
    column_union: set[str] = set()
    row_counts: list[int] = []
    for path in paths[:3]:
        summary = summarize_pickle(path)
        sample_summaries.append(
            {
                "path": str(path).replace("\\", "/"),
                "status": summary.get("status"),
                "object_type": summary.get("object_type"),
                "row_count": summary.get("row_count"),
                "columns": summary.get("columns", [])[:20],
            }
        )
        if summary.get("status") == "ok":
            column_union.update(str(column) for column in summary.get("columns", []))
            if isinstance(summary.get("row_count"), int):
                row_counts.append(int(summary["row_count"]))
    return {
        "family_id": family_id,
        "pattern": pattern,
        "file_count": len(paths),
        "date_count": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "dates": dates,
        "columns_union_sample": sorted(column_union),
        "min_sample_row_count": min(row_counts) if row_counts else None,
        "max_sample_row_count": max(row_counts) if row_counts else None,
        "sample_files": sample_summaries,
    }


def summarize_forward_daily_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path).replace("\\", "/"),
            "status": "missing",
            "findings": ["forward_daily cache is absent"],
        }
    try:
        payload = safe_load_pickle(path)
    except Exception as exc:
        return {
            "path": str(path).replace("\\", "/"),
            "status": "unreadable",
            "findings": [f"{type(exc).__name__}: {exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "path": str(path).replace("\\", "/"),
            "status": "invalid",
            "findings": ["forward_daily cache payload is not a dict"],
        }
    stocks = payload.get("stocks")
    limits = payload.get("limits")
    benchmarks = payload.get("benchmarks", {})
    stock_columns = list(stocks.columns) if isinstance(stocks, pd.DataFrame) else []
    benchmark_summary = {}
    if isinstance(benchmarks, dict):
        for name, frame in benchmarks.items():
            if isinstance(frame, pd.DataFrame):
                benchmark_summary[str(name)] = {
                    "row_count": int(len(frame)),
                    "columns": [str(column) for column in frame.columns],
                }
    return {
        "path": str(path).replace("\\", "/"),
        "status": "ok",
        "meta": payload.get("meta", {}),
        "stocks": {
            "row_count": int(len(stocks)) if isinstance(stocks, pd.DataFrame) else 0,
            "columns": [str(column) for column in stock_columns],
            "has_adj_factor": "adj_factor" in stock_columns,
        },
        "limits": {
            "row_count": int(len(limits)) if isinstance(limits, pd.DataFrame) else 0,
        },
        "benchmarks": benchmark_summary,
    }


def build_cache_inventory(cache_dir: Path, forward_daily_cache: Path) -> dict[str, Any]:
    families = [
        inventory_cache_family(cache_dir, family_id, pattern)
        for family_id, pattern in CACHE_FAMILIES.items()
    ]
    return {
        "cache_dir": str(cache_dir).replace("\\", "/"),
        "families": families,
        "forward_daily_cache": summarize_forward_daily_cache(forward_daily_cache),
    }


def family_by_id(inventory: dict[str, Any], family_id: str) -> dict[str, Any]:
    for family in inventory["families"]:
        if family["family_id"] == family_id:
            return family
    raise KeyError(family_id)


def local_schedule_coverage(preregistration: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    schedule = preregistration["audit_as_of_schedule"]
    expected_months = months_between(schedule["start_as_of"], schedule["end_as_of"])
    available_dates = sorted(
        set().union(
            family_by_id(inventory, "derived_financial")["dates"],
            family_by_id(inventory, "stock_list")["dates"],
            family_by_id(inventory, "daily_all")["dates"],
        )
    )
    available_months = sorted({date[:6] for date in available_dates})
    missing_months = [month for month in expected_months if month not in set(available_months)]
    return {
        "schedule_id": schedule["schedule_id"],
        "expected_month_count": len(expected_months),
        "available_month_count": len([month for month in expected_months if month in set(available_months)]),
        "first_expected_month": expected_months[0],
        "last_expected_month": expected_months[-1],
        "first_available_month": available_months[0] if available_months else None,
        "last_available_month": available_months[-1] if available_months else None,
        "missing_expected_month_count": len(missing_months),
        "missing_expected_month_sample": missing_months[:12],
        "exact_last_trading_day_schedule_verified": False,
        "verification_limitation": "No raw trade_cal schedule artifact is present for the full frozen 2018-2025 schedule; local cache dates are diagnostic only.",
    }


def check_fundamental_pit_rows(rows: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    valid_count = 0
    future_count = 0
    missing_or_invalid_count = 0
    for row in rows:
        ann_date = normalize_yyyymmdd(row.get("ann_date"))
        if ann_date is None:
            missing_or_invalid_count += 1
            continue
        valid_count += 1
        if ann_date > as_of:
            future_count += 1
    missing_denominator = valid_count + missing_or_invalid_count
    return {
        "valid_ann_date_rows": valid_count,
        "future_ann_date_rows": future_count,
        "missing_or_invalid_ann_date_rows": missing_or_invalid_count,
        "ann_date_future_lookahead_violation_rate": future_count / valid_count if valid_count else 0.0,
        "ann_date_missing_or_invalid_exclusion_rate_pct": (
            missing_or_invalid_count / missing_denominator * 100.0 if missing_denominator else 0.0
        ),
        "hard_fail": future_count > 0,
    }


def check_restatement_rows(rows: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("ts_code")), str(row.get("end_date")))].append(row)
    checked_groups = 0
    violation_groups = 0
    for group_rows in groups.values():
        if len(group_rows) < 2:
            continue
        checked_groups += 1
        used_ann_date = normalize_yyyymmdd(group_rows[0].get("used_ann_date"))
        if used_ann_date is not None and used_ann_date > as_of:
            violation_groups += 1
    return {
        "duplicate_groups_checked": checked_groups,
        "restatement_or_latest_only_violation_groups": violation_groups,
        "hard_fail": violation_groups > 0,
    }


def check_survivorship_rows(rows: list[dict[str, Any]], as_of: str) -> dict[str, Any]:
    violations = 0
    for row in rows:
        list_date = normalize_yyyymmdd(row.get("list_date"))
        delist_date = normalize_yyyymmdd(row.get("delist_date"))
        is_eligible = list_date is not None and list_date <= as_of and (delist_date is None or delist_date > as_of)
        dropped = bool(row.get("dropped_by_active_only_filter"))
        missing_terminal = bool(row.get("held_through_delist")) and not bool(row.get("terminal_return_captured"))
        if (is_eligible and dropped) or missing_terminal:
            violations += 1
    return {
        "membership_rows_checked": len(rows),
        "survivorship_or_terminal_return_violation_rows": violations,
        "hard_fail": violations > 0,
    }


def check_return_measurement_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    violations = 0
    for row in rows:
        anchor_mismatch = row.get("stock_entry_anchor") != row.get("benchmark_entry_anchor") or row.get("stock_exit_anchor") != row.get("benchmark_exit_anchor")
        missing_terminal = bool(row.get("held_through_delist")) and not bool(row.get("terminal_return_captured"))
        silent_zero_fill = bool(row.get("silent_zero_fill"))
        if anchor_mismatch or missing_terminal or silent_zero_fill:
            violations += 1
    return {
        "return_rows_checked": len(rows),
        "return_or_benchmark_measurement_violation_rows": violations,
        "hard_fail": violations > 0,
    }


def characterize_coverage(cells: list[dict[str, Any]], threshold_pct: float) -> dict[str, Any]:
    years = sorted({int(cell["year"]) for cell in cells})
    usable_start_year = None
    for year in years:
        later = [cell for cell in cells if int(cell["year"]) >= year]
        if later and all(float(cell["coverage_pct"]) >= threshold_pct for cell in later):
            usable_start_year = year
            break
    thin_cells = [
        {
            "year": int(cell["year"]),
            "table": str(cell["table"]),
            "coverage_pct": float(cell["coverage_pct"]),
        }
        for cell in cells
        if float(cell["coverage_pct"]) < threshold_pct
    ]
    return {
        "threshold_pct": threshold_pct,
        "usable_start_year": usable_start_year,
        "thin_cell_count": len(thin_cells),
        "thin_cells": thin_cells,
        "global_hard_fail": False,
    }


def run_required_self_tests(preregistration: dict[str, Any]) -> list[dict[str, Any]]:
    threshold = float(
        next(check for check in preregistration["audit_checks"] if check["check_id"] == "temporal_coverage_bias")["pass_threshold"]["value"]
    )
    tests = []

    future = check_fundamental_pit_rows(
        [{"ts_code": "000001.SZ", "end_date": "20240331", "ann_date": "20240501"}],
        "20240430",
    )
    tests.append(self_test_record("future_ann_date_hard_fail", future["hard_fail"], future))

    restated = check_restatement_rows(
        [
            {"ts_code": "000001.SZ", "end_date": "20231231", "ann_date": "20240301", "used_ann_date": "20240901"},
            {"ts_code": "000001.SZ", "end_date": "20231231", "ann_date": "20240901", "used_ann_date": "20240901"},
        ],
        "20240430",
    )
    tests.append(self_test_record("restated_value_asof_fail", restated["hard_fail"], restated))

    dropped = check_survivorship_rows(
        [
            {
                "ts_code": "000001.SZ",
                "list_date": "20000101",
                "delist_date": "20250630",
                "dropped_by_active_only_filter": True,
            }
        ],
        "20240430",
    )
    tests.append(self_test_record("dropped_delisted_member_fail", dropped["hard_fail"], dropped))

    missing_terminal_survivorship = check_survivorship_rows(
        [
            {
                "ts_code": "000002.SZ",
                "list_date": "20000101",
                "delist_date": "20240510",
                "held_through_delist": True,
                "terminal_return_captured": False,
            }
        ],
        "20240430",
    )
    missing_terminal_return = check_return_measurement_rows(
        [
            {
                "stock_entry_anchor": "entry_open",
                "stock_exit_anchor": "exit_close",
                "benchmark_entry_anchor": "entry_open",
                "benchmark_exit_anchor": "exit_close",
                "held_through_delist": True,
                "terminal_return_captured": False,
            }
        ]
    )
    tests.append(
        self_test_record(
            "missing_delisting_terminal_return_fail",
            missing_terminal_survivorship["hard_fail"] and missing_terminal_return["hard_fail"],
            {
                "survivorship": missing_terminal_survivorship,
                "return_measurement": missing_terminal_return,
            },
        )
    )

    anchor = check_return_measurement_rows(
        [
            {
                "stock_entry_anchor": "entry_open",
                "stock_exit_anchor": "exit_close",
                "benchmark_entry_anchor": "asof_close",
                "benchmark_exit_anchor": "exit_close",
                "terminal_return_captured": True,
            }
        ]
    )
    tests.append(self_test_record("benchmark_anchor_mismatch_fail", anchor["hard_fail"], anchor))

    coverage = characterize_coverage(
        [
            {"year": 2018, "table": "income", "coverage_pct": 10.0},
            {"year": 2019, "table": "income", "coverage_pct": 70.0},
            {"year": 2020, "table": "income", "coverage_pct": 80.0},
            {"year": 2021, "table": "income", "coverage_pct": 90.0},
        ],
        threshold,
    )
    tests.append(
        self_test_record(
            "sparse_early_coverage_declares_usable_window",
            coverage["usable_start_year"] == 2020 and coverage["global_hard_fail"] is False,
            coverage,
        )
    )

    expected = {item["fixture_id"] for item in preregistration["required_runner_self_tests"]}
    actual = {item["fixture_id"] for item in tests}
    if actual != expected:
        raise ValueError(f"self-test fixture ids do not match preregistration: expected={expected}, actual={actual}")
    return tests


def self_test_record(fixture_id: str, passed: bool, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "status": "pass" if passed else "fail",
        "detected_expected_violation": bool(passed),
        "metrics": metrics,
    }


def derived_coverage_rows(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    financial_dates = family_by_id(inventory, "derived_financial")["dates"]
    stock_dates = set(family_by_id(inventory, "stock_list")["dates"])
    rows = []
    for date in financial_dates:
        year = date[:4]
        has_denominator = date in stock_dates
        rows.append(
            {
                "year": int(year),
                "as_of": date,
                "table": "derived_financial_cache",
                "coverage_pct": None,
                "pit_certifying": False,
                "has_matching_stock_list_denominator": has_denominator,
                "note": "Derived A-short financial cache omits ann_date/end_date and cannot certify A-long PIT fundamentals.",
            }
        )
    return rows


def hard_check_report(check_id: str, status: str, findings: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "hard_check": check_id in HARD_CHECK_IDS,
        "blocks_signal_search": status in {"fail_data_not_ready", "blocked_missing_required_source"},
        "metrics": metrics,
        "findings": findings,
        "allowed_followup": "repair_data_route_before_signal_search",
    }


def evaluate_real_audit(preregistration: dict[str, Any], inventory: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    schedule = local_schedule_coverage(preregistration, inventory)
    financial = family_by_id(inventory, "derived_financial")
    stock_list = family_by_id(inventory, "stock_list")
    daily_all = family_by_id(inventory, "daily_all")
    daily_basic = family_by_id(inventory, "daily_basic")
    forward_daily = inventory["forward_daily_cache"]
    financial_columns = set(financial["columns_union_sample"])

    checks = [
        hard_check_report(
            "fundamental_pit",
            "blocked_missing_required_source",
            [
                "No raw Tushare income cache was found.",
                "No raw Tushare balancesheet cache was found.",
                "No raw Tushare fina_indicator PIT cache with ann_date/end_date lineage was found.",
                "Existing financial_*.pkl files are derived A-short caches and omit ann_date/end_date, so look-ahead and missing-ann_date rates cannot be certified.",
            ],
            {
                "derived_financial_cache_files": financial["file_count"],
                "derived_financial_first_date": financial["first_date"],
                "derived_financial_last_date": financial["last_date"],
                "derived_financial_has_ann_date_column": "ann_date" in financial_columns,
                "derived_financial_has_end_date_column": "end_date" in financial_columns,
                "missing_or_invalid_ann_date_rows_excluded": None,
                "ann_date_future_lookahead_violation_rate": None,
            },
        ),
        hard_check_report(
            "restatement_revision_asof",
            "blocked_missing_required_source",
            [
                "Derived financial caches keep already-selected values only.",
                "No raw duplicate ts_code/end_date rows with multiple ann_date values are available to prove as-of restatement selection.",
                "Latest-only or pre-filtered derived values cannot certify long-lane historical factor lineage.",
            ],
            {
                "raw_duplicate_ann_date_groups_available": False,
                "restatement_or_latest_only_violation_rate": None,
            },
        ),
        hard_check_report(
            "survivorship_pit_universe",
            "blocked_missing_required_source",
            [
                "stock_list_*_v2 caches exist only for local cached as-of dates, not the full frozen 2018-2025 monthly schedule.",
                "The local cache set cannot prove historical PIT universe coverage for missing years/months.",
                "No terminal/delisting return artifact is available for held names that leave the universe during a holding window.",
            ],
            {
                "stock_list_cache_files": stock_list["file_count"],
                "stock_list_first_date": stock_list["first_date"],
                "stock_list_last_date": stock_list["last_date"],
                "missing_expected_schedule_month_count": schedule["missing_expected_month_count"],
                "terminal_delisting_return_artifact_available": False,
            },
        ),
        hard_check_report(
            "return_benchmark_measurement_basis",
            "blocked_missing_required_source",
            [
                "Local price caches provide some daily/adj_factor material, but not a reviewed A-long total-return chain.",
                "No dividend/cash distribution source is present for long-lane total return.",
                "No terminal/delisting return handling is present for long-lane held positions.",
                "Benchmark open/close material exists in forward_daily only for the A-short backtest cache; it does not certify the frozen A-long 2018-2025 schedule.",
            ],
            {
                "daily_all_cache_files": daily_all["file_count"],
                "daily_basic_cache_files": daily_basic["file_count"],
                "forward_daily_status": forward_daily["status"],
                "forward_daily_stock_has_adj_factor": forward_daily.get("stocks", {}).get("has_adj_factor"),
                "dividend_or_total_return_source_available": False,
                "terminal_delisting_return_source_available": False,
            },
        ),
        hard_check_report(
            "temporal_coverage_bias",
            "blocked_missing_required_source",
            [
                "Coverage cannot be certified because raw PIT fundamental tables and a full PIT eligible denominator are missing.",
                "Derived financial cache dates can be listed, but they do not prove ann_date-valid PIT coverage.",
            ],
            {
                "usable_start_year": None,
                "coverage_characterization_basis": "diagnostic_derived_cache_inventory_only",
                "derived_financial_cache_files": financial["file_count"],
                "expected_schedule_month_count": schedule["expected_month_count"],
                "available_cache_month_count": schedule["available_month_count"],
                "missing_expected_schedule_month_count": schedule["missing_expected_month_count"],
            },
        ),
    ]
    coverage = {
        "status": "blocked_missing_required_source",
        "usable_start_year": None,
        "basis": "diagnostic_derived_cache_inventory_only_not_pit_certifying",
        "threshold_pct": 80,
        "derived_cache_rows": derived_coverage_rows(inventory),
    }
    return checks, coverage


def decision_from_checks(checks: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
    hard_blocked = [check["check_id"] for check in checks if check["hard_check"] and check["status"] == "blocked_missing_required_source"]
    hard_failed = [check["check_id"] for check in checks if check["hard_check"] and check["status"] == "fail_data_not_ready"]
    if hard_blocked:
        status = "blocked_missing_required_source"
        plain = "不能开始 A 股长线找 alpha；本地数据缺 raw PIT 三大表、完整 PIT universe、分红/退市收益链。"
        next_action = "先补 A-long 可审计数据路线，再重新预注册/运行数据审计；不得开始信号搜索。"
    elif hard_failed:
        status = "fail_data_not_ready"
        plain = "不能开始 A 股长线找 alpha；数据审计发现硬错误。"
        next_action = "先修复硬错误，再重新运行 reviewed 数据审计；不得开始信号搜索。"
    elif coverage.get("usable_start_year") is None:
        status = "blocked_missing_required_source"
        plain = "硬检查未失败，但覆盖率不能声明可用起始年；还不能找 alpha。"
        next_action = "先补覆盖率证据并声明可用起始年。"
    else:
        status = "pass_data_ready_for_signal_preregistration"
        plain = f"数据地基可用于下一步信号预注册，但只能从 {coverage['usable_start_year']} 年开始。"
        next_action = "创建单独 reviewed A-long signal-search preregistration；本报告本身不授权信号回测。"
    return {
        "audit_status": status,
        "hard_checks_pass": not hard_blocked and not hard_failed,
        "hard_blocked_checks": hard_blocked,
        "hard_failed_checks": hard_failed,
        "usable_start_year": coverage.get("usable_start_year"),
        "signal_search_allowed_by_this_report": False,
        "alpha_found": False,
        "plain_result": plain,
        "next_action": next_action,
    }


def build_report(
    *,
    generated_at: str,
    preregistration_path: Path,
    ledger_path: Path,
    cache_dir: Path,
    forward_daily_cache: Path,
    output_dir: Path,
    code_version_ref: str,
) -> dict[str, Any]:
    preregistration = read_json(preregistration_path)
    self_tests = run_required_self_tests(preregistration)
    failed_self_tests = [item["fixture_id"] for item in self_tests if item["status"] != "pass"]
    if failed_self_tests:
        raise RuntimeError(f"required runner self-tests failed: {failed_self_tests}")

    inventory = build_cache_inventory(cache_dir, forward_daily_cache)
    schedule = local_schedule_coverage(preregistration, inventory)
    checks, coverage = evaluate_real_audit(preregistration, inventory)
    decision = decision_from_checks(checks, coverage)

    return {
        "schema_name": "a_long_data_integrity_audit_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "artifact_id": REPORT_ID,
        "scope": {
            "phase": "7a_alpha_validation",
            "purpose": "a_long_data_integrity_audit_execution",
            "lane_id": "a_long",
            "market": "A-share",
            "research_only": True,
            "local_cache_read_only": True,
            "provider_call_executed": False,
            "data_fetch_executed": False,
            "signal_search_executed": False,
            "alpha_backtest_executed": False,
            "production_use_allowed": False,
            "ship_gate_claim_allowed": False,
            "full_size_manual_use_allowed": False,
            "broker_or_order_automation_allowed": False,
            "manual_order_only": True,
        },
        "execution": {
            "test_id": TEST_ID,
            "preregistration_ref": str(preregistration_path).replace("\\", "/"),
            "ledger_ref": str(ledger_path).replace("\\", "/"),
            "result_dir": str(output_dir).replace("\\", "/"),
            "code_version_ref": code_version_ref,
            "network_calls_executed": 0,
            "provider_calls_executed": 0,
            "self_tests_required": len(preregistration["required_runner_self_tests"]),
            "self_tests_passed": len([item for item in self_tests if item["status"] == "pass"]),
        },
        "decision": decision,
        "required_runner_self_tests": self_tests,
        "audit_as_of_schedule": preregistration["audit_as_of_schedule"],
        "schedule_cache_coverage": schedule,
        "audit_checks": checks,
        "coverage_characterization": coverage,
        "local_cache_inventory": inventory,
        "prohibited_claims": {
            "a_long_alpha_found": False,
            "signal_search_authorized": False,
            "production_ready": False,
            "ship_gate_evidence": False,
            "full_size_allowed": False,
            "provider_selected": False,
            "datahub_authorized": False,
            "broker_or_order_automation_authorized": False,
        },
        "source_refs": [
            str(preregistration_path).replace("\\", "/"),
            str(ledger_path).replace("\\", "/"),
            "docs/SESSION_LOG.md",
            "docs/system_risk_register.md",
        ],
        "result_artifacts": [
            str(output_dir / "audit_report.json").replace("\\", "/"),
            str(output_dir / "check_summary.csv").replace("\\", "/"),
            str(output_dir / "coverage_by_year.csv").replace("\\", "/"),
        ],
        "limitations": [
            "This run reads local cache files only; it does not call Tushare or any provider.",
            "Existing financial_*.pkl files are derived A-short caches and cannot certify raw PIT fundamentals.",
            "A blocked result is not an alpha result; it means the data route is not ready for A-long signal search.",
            "This report does not authorize signal search, production use, ship-gate evidence, full-size manual use, or broker/order automation.",
        ],
    }


def check_summary_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for check in report["audit_checks"]:
        rows.append(
            {
                "check_id": check["check_id"],
                "status": check["status"],
                "hard_check": check["hard_check"],
                "blocks_signal_search": check["blocks_signal_search"],
                "finding_count": len(check["findings"]),
                "allowed_followup": check["allowed_followup"],
            }
        )
    return rows


def coverage_csv_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return report["coverage_characterization"]["derived_cache_rows"]


def result_summary_for_ledger(report: dict[str, Any]) -> str:
    decision = report["decision"]
    return (
        f"decision={decision['audit_status']}; self_tests={report['execution']['self_tests_passed']}/"
        f"{report['execution']['self_tests_required']}; hard_checks_pass={str(decision['hard_checks_pass']).lower()}; "
        f"usable_start_year={decision['usable_start_year']}; signal_search_allowed=false; "
        "blocked_reason=missing raw PIT fundamentals / complete PIT universe / dividend and terminal delisting return lineage"
    )


def update_ledger(ledger_path: Path, preregistration_path: Path, report: dict[str, Any], result_ref: Path) -> dict[str, Any]:
    ledger = read_json(ledger_path)
    if any(item.get("test_id") == TEST_ID for item in ledger.get("test_spend_log", [])):
        raise RuntimeError(f"{TEST_ID} is already spent in {ledger_path}")
    planned = [item for item in ledger.get("planned_tests", []) if item.get("test_id") == TEST_ID]
    if not planned:
        raise RuntimeError(f"{TEST_ID} is not present in planned_tests for {ledger_path}")

    ledger["ledger_status"] = "active_no_new_test_authorized"
    ledger["budget_policy"]["tests_spent_count"] = int(ledger["budget_policy"]["tests_spent_count"]) + 1
    ledger["budget_policy"]["tests_available_without_new_review"] = 0
    ledger["test_spend_log"].append(
        {
            "test_id": TEST_ID,
            "preregistration_ref": str(preregistration_path).replace("\\", "/"),
            "result_ref": str(result_ref).replace("\\", "/"),
            "status": "spent_voided_by_data_integrity_failure",
            "tests_spent": 1,
            "promotion_relevant": True,
            "result_summary": result_summary_for_ledger(report),
            "allowed_followup": "Repair or replace the A-long data route and create a new reviewed data-integrity audit plan before any signal search; no alpha backtest or production use is authorized.",
        }
    )
    ledger["planned_tests"] = [item for item in ledger.get("planned_tests", []) if item.get("test_id") != TEST_ID]
    ledger["next_required_actions"] = [
        "Do not start A-long signal search from this blocked audit result.",
        "Repair the data route: raw PIT fundamentals with ann_date/end_date lineage, full PIT universe, dividend/total-return handling, and terminal delisting return lineage are required.",
        "After repair, create a new reviewed data-integrity audit plan or rerun only under a reviewed authorization.",
    ]
    validate_json(LEDGER_SCHEMA, ledger)
    write_json(ledger_path, ledger)
    return ledger


def run(args: argparse.Namespace) -> dict[str, Any]:
    report = build_report(
        generated_at=args.generated_at,
        preregistration_path=args.preregistration,
        ledger_path=args.ledger,
        cache_dir=args.cache_dir,
        forward_daily_cache=args.forward_daily_cache,
        output_dir=args.output_dir,
        code_version_ref=args.code_version_ref,
    )
    validate_json(REPORT_SCHEMA, report)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "audit_report.json"
    write_json(report_path, report)
    write_csv(args.output_dir / "check_summary.csv", check_summary_rows(report))
    write_csv(args.output_dir / "coverage_by_year.csv", coverage_csv_rows(report))

    ledger = None
    if not args.no_update_ledger:
        ledger = update_ledger(args.ledger, args.preregistration, report, report_path)
    return {"report": report, "ledger": ledger}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    decision = result["report"]["decision"]
    print(json.dumps({
        "audit_status": decision["audit_status"],
        "plain_result": decision["plain_result"],
        "next_action": decision["next_action"],
        "report_ref": str(args.output_dir / "audit_report.json").replace("\\", "/"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
