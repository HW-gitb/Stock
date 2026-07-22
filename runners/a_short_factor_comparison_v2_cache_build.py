"""Incrementally materialise the private A-short factor-comparison v2 cache.

This is the sole P0 provider seam for v2 and the shared cache seam for P5.
It reads only frozen private consumer captures, requests only selected symbols
and still-needed settlement windows, and writes an atomic, schema-valid cache.
v2 has a fixed first reservation; P5 overflow is deferred.  It never changes
M6.7 selection or treats a missing adjustment factor as observed evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_factor_comparison_v2 import (  # noqa: E402
    ComparisonV2Error,
    HORIZONS,
    _load_json,
    _private_root,
    _validate_source_receipt,
    validate_v2_weekly_record,
)
from engine.a_short_tushare_client import init_tushare_pro  # noqa: E402
from runners.materialize_execution_price_data_tushare import ts_call  # noqa: E402


DAILY_CACHE_NAME = "daily_cache.json"
DAILY_CACHE_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_daily_cache.schema.json"
DEFAULT_MAX_PROVIDER_CALLS = 91


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_existing_cache(root: Path) -> dict:
    path = root / DAILY_CACHE_NAME
    if not path.exists():
        return {
            "schema_name": "a_short_factor_comparison_v2_daily_cache",
            "schema_version": "1.0.0",
            "stocks": [],
            "limits": [],
            "meta": {
                "cache_kind": "a_short_factor_comparison_v2_incremental",
                "source": "tushare:daily+adj_factor+stk_limit",
            },
        }
    try:
        document = _load_json(path)
        schema = _load_json(DAILY_CACHE_SCHEMA_PATH)
        jsonschema.validate(document, schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ComparisonV2Error("v2 existing daily cache violates its frozen contract") from exc
    return document


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _string_date(value: object, label: str) -> str:
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ComparisonV2Error(f"v2 cache builder {label} is not YYYYMMDD") from exc
    return text


def _dedupe_rows(rows: list[dict], *, key_names: tuple[str, str], label: str) -> dict[tuple[str, str], dict]:
    result: dict[tuple[str, str], dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ComparisonV2Error(f"v2 {label} row is not an object")
        key = tuple(str(row.get(name) or "") for name in key_names)
        if not all(key):
            raise ComparisonV2Error(f"v2 {label} row has no stable key")
        existing = result.get(key)
        if existing is not None and existing != row:
            raise ComparisonV2Error(f"v2 {label} has conflicting duplicate key {key[0]} {key[1]}")
        result[key] = row
    return result


def _frozen_windows(root: Path, run_date: str) -> list[dict]:
    weeks = root / "weeks"
    if not weeks.exists():
        return []
    windows = []
    for week in sorted(path for path in weeks.iterdir() if path.is_dir() and path.name.isdigit()):
        capture_path = week / "capture.json"
        receipt_path = week / "source_receipt.json"
        if not capture_path.exists() or not receipt_path.exists():
            raise ComparisonV2Error(f"{week.name}: incomplete v2 capture cannot materialize a cache")
        capture, receipt = _load_json(capture_path), _load_json(receipt_path)
        validate_v2_weekly_record(capture)
        validate_v2_weekly_record(receipt)
        _validate_source_receipt(root, capture, receipt)
        if capture.get("record_type") != "capture":
            raise ComparisonV2Error(f"{week.name}: cache source is not a capture")
        outcome_path = week / "outcome.json"
        if outcome_path.exists():
            outcome = _load_json(outcome_path)
            validate_v2_weekly_record(outcome)
            questions = (outcome.get("payload") or {}).get("questions") or []
            if questions and all(row.get("status") in {"settled", "no_count"} for row in questions):
                continue
        identity = ((capture.get("payload") or {}).get("run_identity") or {})
        decision_date = _string_date(capture.get("decision_date"), "decision_date")
        price_data_through = _string_date(identity.get("price_data_through"), "price_data_through")
        if decision_date > run_date or price_data_through > run_date:
            continue
        symbols = sorted({
            str(code)
            for question in (capture.get("payload") or {}).get("questions") or []
            for arm in question.get("arms") or []
            for code in arm.get("selected_symbols") or []
            if str(code)
        })
        if symbols:
            windows.append({
                "decision_date": decision_date,
                "price_data_through": price_data_through,
                "symbols": symbols,
            })
    return windows


def _needed_dates_by_symbol(windows: list[dict], trading_dates: list[str], run_date: str) -> dict[str, set[str]]:
    date_pos = {day: index for index, day in enumerate(trading_dates)}
    needed: dict[str, set[str]] = {}
    for window in windows:
        start = window["price_data_through"]
        decision = window["decision_date"]
        if start not in date_pos or decision not in date_pos:
            raise ComparisonV2Error("v2 cache builder cannot prove captured price/decision dates from provider calendar")
        end_index = min(len(trading_dates) - 1, date_pos[decision] + max(HORIZONS))
        wanted = set(trading_dates[date_pos[start]:end_index + 1])
        wanted = {day for day in wanted if day <= run_date}
        for symbol in window["symbols"]:
            needed.setdefault(symbol, set()).update(wanted)
    return needed


def _frame_records(frame: pd.DataFrame, fields: tuple[str, ...], label: str) -> dict[tuple[str, str], dict]:
    if frame is None or frame.empty:
        return {}
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ComparisonV2Error(f"v2 Tushare {label} response misses {sorted(missing)}")
    records = []
    for raw in frame.loc[:, list(fields)].to_dict("records"):
        records.append({key: (str(value) if key in {"ts_code", "trade_date"} else value)
                        for key, value in raw.items()})
    return _dedupe_rows(records, key_names=("ts_code", "trade_date"), label=f"Tushare {label}")


def _optional_number(value: object) -> float | None:
    return float(value) if _finite(value) else None


def _single_attempt_trade_calendar(pro: Any, start_date: str, end_date: str) -> list[str]:
    frame = ts_call(pro.trade_cal, retries=1, exchange="SSE", start_date=start_date, end_date=end_date,
                    is_open="1", fields="cal_date")
    if frame is None or frame.empty or "cal_date" not in frame.columns:
        raise ComparisonV2Error("v2 Tushare trade_cal returned no usable open dates")
    return sorted(str(day) for day in frame["cal_date"].tolist())


def _single_attempt_symbol_frames(pro: Any, symbol: str, start_date: str, end_date: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = ts_call(pro.daily, retries=1, ts_code=symbol, start_date=start_date, end_date=end_date,
                    fields="ts_code,trade_date,open,close")
    adjustment = ts_call(pro.adj_factor, retries=1, ts_code=symbol, start_date=start_date, end_date=end_date,
                         fields="ts_code,trade_date,adj_factor")
    limits = ts_call(pro.stk_limit, retries=1, ts_code=symbol, start_date=start_date, end_date=end_date,
                     fields="ts_code,trade_date,up_limit")
    return (daily if daily is not None else pd.DataFrame(),
            adjustment if adjustment is not None else pd.DataFrame(),
            limits if limits is not None else pd.DataFrame())


def _provider_rows_for_symbol(*, symbol: str, wanted_dates: set[str], daily: pd.DataFrame,
                              adj: pd.DataFrame, limits: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    daily_by_key = _frame_records(daily, ("ts_code", "trade_date", "open", "close"), "daily")
    adj_by_key = _frame_records(adj, ("ts_code", "trade_date", "adj_factor"), "adj_factor")
    limit_by_key = _frame_records(limits, ("ts_code", "trade_date", "up_limit"), "stk_limit")
    stocks, limit_rows = [], []
    for trade_date in sorted(wanted_dates):
        raw = daily_by_key.get((symbol, trade_date))
        if raw is None:
            continue
        adjustment = adj_by_key.get((symbol, trade_date), {}).get("adj_factor")
        observed = _finite(adjustment) and float(adjustment) > 0.0
        stocks.append({
            "ts_code": symbol,
            "trade_date": trade_date,
            "open": _optional_number(raw.get("open")),
            "close": _optional_number(raw.get("close")),
            "adj_factor": float(adjustment) if observed else None,
            "adj_factor_observed": observed,
            "adj_factor_source": "provider_observed" if observed else "provider_missing",
            "corporate_action_verified": False,
        })
        limit_rows.append({
            "ts_code": symbol,
            "trade_date": trade_date,
            "up_limit": _optional_number(limit_by_key.get((symbol, trade_date), {}).get("up_limit")),
        })
    return stocks, limit_rows


def _p5_frozen_windows(industry_weight_root: str | Path | None, run_date: str) -> list[dict]:
    """Read P5's explicit consumer requests only; this builder never reads its ledger/outcomes."""
    if industry_weight_root is None:
        return []
    from engine.a_short_industry_weight_comparison import cache_consumer_windows
    return cache_consumer_windows(root=industry_weight_root, run_date=run_date)


def _missing_needed(needed: dict[str, set[str]], existing_stocks: dict[tuple[str, str], dict]) -> dict[str, set[str]]:
    return {symbol: dates for symbol, dates in needed.items()
            if any((symbol, day) not in existing_stocks for day in dates)}


def materialize_incremental_cache(*, root: str | Path, run_date: str, max_provider_calls: int = DEFAULT_MAX_PROVIDER_CALLS,
                                  pro: Any | None = None, industry_weight_root: str | Path | None = None) -> dict:
    """Materialize one truthful cache with v2-first/P5-deferred scheduling.

    Call accounting is still one shared calendar call plus three calls per fetched
    symbol.  Existing rows are loaded before the budget is calculated.  v2 is
    non-starvable; P5 symbols beyond the remaining capacity are deferred rather
    than turning an advisory evidence request into a v2/M6.7 failure.
    """
    private_root = _private_root(root)
    run_date = _string_date(run_date, "run_date")
    if run_date != _today():
        raise ComparisonV2Error("v2 cache builder requires the real local run_date")
    if not isinstance(max_provider_calls, int) or isinstance(max_provider_calls, bool) or max_provider_calls < 1:
        raise ComparisonV2Error("v2 cache builder max_provider_calls must be a positive integer")
    v2_windows = _frozen_windows(private_root, run_date)
    p5_windows = _p5_frozen_windows(industry_weight_root, run_date)
    if not v2_windows and not p5_windows:
        return {"status": ("no_frozen_v2_captures" if industry_weight_root is None else "no_frozen_consumer_captures"),
                "provider_calls": 0, "production_unchanged": True,
                "p5_deferred_due_to_budget": 0}
    existing = _load_existing_cache(private_root)
    existing_stocks = _dedupe_rows(existing["stocks"], key_names=("ts_code", "trade_date"), label="existing stocks")
    existing_limits = _dedupe_rows(existing["limits"], key_names=("ts_code", "trade_date"), label="existing limits")
    # With no existing row at all, every frozen v2 symbol necessarily needs a
    # three-call symbol batch.  Fail before even the calendar call if v2 alone
    # cannot fit; once a cache exists, the later date-level calculation is the
    # authority and may prove that most/all symbols are already current.
    if not existing_stocks:
        empty_cache_v2_symbols = {symbol for window in v2_windows for symbol in window["symbols"]}
        if 1 + 3 * len(empty_cache_v2_symbols) > max_provider_calls:
            raise ComparisonV2Error(
                "v2 cache builder provider-call budget exceeded after existing-cache check: "
                f"{1 + 3 * len(empty_cache_v2_symbols)}>{max_provider_calls}"
            )
    calendar_start = min(window["price_data_through"] for window in [*v2_windows, *p5_windows])
    if pro is None:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise ComparisonV2Error("TUSHARE_TOKEN is required to materialize the private v2 cache")
        pro = init_tushare_pro(token)
    trading_dates = _single_attempt_trade_calendar(pro, calendar_start, run_date)
    v2_needed = _needed_dates_by_symbol(v2_windows, trading_dates, run_date) if v2_windows else {}
    p5_needed = _needed_dates_by_symbol(p5_windows, trading_dates, run_date) if p5_windows else {}
    v2_missing = _missing_needed(v2_needed, existing_stocks)
    v2_calls = 1 + 3 * len(v2_missing)
    if v2_calls > max_provider_calls:
        raise ComparisonV2Error(
            f"v2 cache builder provider-call budget exceeded after existing-cache check: {v2_calls}>{max_provider_calls}"
        )
    remaining_symbols = (max_provider_calls - v2_calls) // 3
    selected_needed = {symbol: set(days) for symbol, days in v2_missing.items()}
    p5_deferred = []
    # P5 ordering: already/soonest maturity (older decision) then stable symbol.
    p5_symbol_dates: dict[str, set[str]] = {}
    p5_symbol_due: dict[str, str] = {}
    for window in p5_windows:
        for symbol in window["symbols"]:
            p5_symbol_dates.setdefault(symbol, set()).update(p5_needed.get(symbol, set()))
            p5_symbol_due[symbol] = min(p5_symbol_due.get(symbol, window["decision_date"]), window["decision_date"])
    for symbol in sorted(p5_symbol_dates, key=lambda code: (p5_symbol_due[code], code)):
        missing_dates = {day for day in p5_symbol_dates[symbol] if (symbol, day) not in existing_stocks}
        if not missing_dates:
            continue
        if symbol in selected_needed:
            selected_needed[symbol].update(missing_dates)
        elif remaining_symbols > 0:
            selected_needed[symbol] = set(missing_dates)
            remaining_symbols -= 1
        else:
            p5_deferred.append(symbol)
    if not selected_needed:
        return {"status": "cache_current", "provider_calls": 1, "production_unchanged": True,
                "p5_deferred_due_to_budget": len(p5_deferred)}
    new_stocks, new_limits = [], []
    for symbol in sorted(selected_needed):
        wanted_dates = selected_needed[symbol]
        daily, adj, limits = _single_attempt_symbol_frames(pro, symbol, min(wanted_dates), max(wanted_dates))
        stock_rows, limit_rows = _provider_rows_for_symbol(symbol=symbol, wanted_dates=wanted_dates,
                                                            daily=daily, adj=adj, limits=limits)
        new_stocks.extend(stock_rows)
        new_limits.extend(limit_rows)
    merged_stocks = _dedupe_rows([*existing_stocks.values(), *new_stocks], key_names=("ts_code", "trade_date"), label="merged stocks")
    merged_limits = _dedupe_rows([*existing_limits.values(), *new_limits], key_names=("ts_code", "trade_date"), label="merged limits")
    payload = {
        "schema_name": "a_short_factor_comparison_v2_daily_cache",
        "schema_version": "1.0.0",
        "stocks": [merged_stocks[key] for key in sorted(merged_stocks)],
        "limits": [merged_limits[key] for key in sorted(merged_limits)],
        "meta": {
            "cache_kind": "a_short_factor_comparison_v2_incremental",
            "source": "tushare:daily+adj_factor+stk_limit",
        },
    }
    try:
        jsonschema.validate(payload, _load_json(DAILY_CACHE_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise ComparisonV2Error("v2 cache builder produced an invalid private cache") from exc
    _atomic_write(private_root / DAILY_CACHE_NAME, payload)
    return {
        "status": "cache_updated",
        "provider_calls": 1 + 3 * len(selected_needed),
        "symbols_updated": sorted(selected_needed),
        "p5_deferred_due_to_budget": len(p5_deferred),
        "production_unchanged": True,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize only frozen private A-short factor-comparison v2 windows.")
    parser.add_argument("--root", required=True, help="gitignored state/a_short/factor_comparison_private/v2 root")
    parser.add_argument("--run-date", required=True, help="actual local run date YYYYMMDD")
    parser.add_argument("--max-provider-calls", type=int, default=DEFAULT_MAX_PROVIDER_CALLS)
    parser.add_argument("--industry-weight-root", default=None,
                        help="optional gitignored P5 state/a_short/industry_weight_comparison_private/v1 root")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = materialize_incremental_cache(root=args.root, run_date=args.run_date,
                                           max_provider_calls=args.max_provider_calls,
                                           industry_weight_root=args.industry_weight_root)
    print(f"[factor-comparison-v2-cache] {result['status']} (production unchanged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
