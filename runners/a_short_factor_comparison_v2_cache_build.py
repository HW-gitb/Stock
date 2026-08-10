"""Incrementally materialise the single private A-short daily cache.

This is the sole P0 provider seam for v2 and the shared cache seam for P5/P2/P3.
It reads only frozen private consumer captures, requests only selected symbols
and still-needed settlement windows, and writes one atomic, schema-valid raw-price
surface plus its deterministic execution projection.  v2 has a fixed first
reservation; P5 is next, and P2/P3 overflow is deferred after both.  It never
changes M6.7 selection or treats a missing adjustment factor as observed evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta
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
    is_current_governed_capture,
    validate_v2_weekly_record,
)
from engine.a_short_observability import safe_exception_summary  # noqa: E402
from engine.a_short_tushare_client import init_tushare_pro  # noqa: E402
from engine.data.a_share_board_scope import is_a_share_main_board  # noqa: E402
from runners.materialize_execution_price_data_tushare import ts_call  # noqa: E402


DAILY_CACHE_NAME = "daily_cache.json"
DAILY_CACHE_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_daily_cache.schema.json"
CACHE_BUILD_OUTCOME_SCHEMA_PATH = ROOT / "schemas" / "a_short_shared_cache_build_outcome.schema.json"
CACHE_BUILD_OUTCOME_SCHEMA_NAME = "a_short_shared_cache_build_outcome"
CACHE_BUILD_OUTCOME_SCHEMA_VERSION = "1.1.0"
DAILY_CACHE_SCHEMA_VERSION = "1.2.0"
CACHE_BUILD_STATUSES = (
    "no_frozen_v2_captures",
    "no_frozen_consumer_captures",
    "cache_current",
    "deferred_due_to_budget",
    "cache_updated",
    "cache_updated_with_deferrals",
    "failed",
)
DEFAULT_MAX_PROVIDER_CALLS = 91
EXECUTION_PRE_HISTORY_DAYS = 20
EXECUTION_HORIZON_DAYS = 20
CONSUMER_PRIORITY = {
    "v2_factor_comparison": 0,
    "p5_industry_weight": 1,
    "p2_target_policy": 2,
    "p3_final_action_validation": 2,
    "official_operation_evidence": 3,
    "p4_overlay_adjudication": 4,
}


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _cache_build_outcome_payload(*, result: dict, run_date: str) -> dict:
    """Project an internal builder result into the launcher-only receipt contract."""
    status = result.get("status")
    if status not in CACHE_BUILD_STATUSES:
        raise ComparisonV2Error("shared cache builder returned an unknown outcome status")
    provider_calls = result.get("provider_calls", 0)
    if not isinstance(provider_calls, int) or isinstance(provider_calls, bool) or provider_calls < 0:
        raise ComparisonV2Error("shared cache builder outcome provider_calls is invalid")
    raw_deferred = result.get("deferred_symbols_by_consumer") or {}
    if not isinstance(raw_deferred, dict):
        raise ComparisonV2Error("shared cache builder outcome deferred counts are invalid")
    deferred: dict[str, int] = {}
    for consumer, count in raw_deferred.items():
        if not isinstance(consumer, str) or not consumer or \
                not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ComparisonV2Error("shared cache builder outcome deferred counts are invalid")
        deferred[consumer] = count
    deferred_total = sum(deferred.values())
    if status == "failed":
        error_code = str(result.get("error_code") or "")
        error_detail = str(result.get("error_detail") or "")
        if not error_code or not error_code.replace("_", "").isalnum() or len(error_code) > 128:
            raise ComparisonV2Error("failed cache outcome error_code is invalid")
        if not error_detail or "\n" in error_detail or "\r" in error_detail or len(error_detail) > 512:
            raise ComparisonV2Error("failed cache outcome error_detail is invalid")
        payload = {
            "schema_name": CACHE_BUILD_OUTCOME_SCHEMA_NAME,
            "schema_version": CACHE_BUILD_OUTCOME_SCHEMA_VERSION,
            "run_date": _string_date(run_date, "outcome run_date"),
            "status": status,
            "provider_calls": provider_calls,
            "deferred_symbols_by_consumer": dict(sorted(deferred.items())),
            "production_unchanged": True,
            "error_code": error_code,
            "error_detail": error_detail,
        }
        try:
            jsonschema.validate(payload, _load_json(CACHE_BUILD_OUTCOME_SCHEMA_PATH))
        except jsonschema.ValidationError as exc:
            raise ComparisonV2Error("shared cache builder failed outcome violates its contract") from exc
        return payload
    if status.startswith("no_frozen_") and (provider_calls != 0 or deferred_total != 0):
        raise ComparisonV2Error("no-frozen cache outcome must have zero provider calls and deferrals")
    if not status.startswith("no_frozen_") and provider_calls < 1:
        raise ComparisonV2Error("cache outcome with frozen work must record a provider call")
    if status in {"cache_current", "cache_updated"} and deferred_total != 0:
        raise ComparisonV2Error("current/updated cache outcome cannot carry deferred counts")
    if status in {"deferred_due_to_budget", "cache_updated_with_deferrals"} and deferred_total <= 0:
        raise ComparisonV2Error("degraded cache outcome must carry a positive deferred count")
    payload = {
        "schema_name": CACHE_BUILD_OUTCOME_SCHEMA_NAME,
        "schema_version": CACHE_BUILD_OUTCOME_SCHEMA_VERSION,
        "run_date": _string_date(run_date, "outcome run_date"),
        "status": status,
        "provider_calls": provider_calls,
        "deferred_symbols_by_consumer": dict(sorted(deferred.items())),
        "production_unchanged": True,
    }
    try:
        jsonschema.validate(payload, _load_json(CACHE_BUILD_OUTCOME_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise ComparisonV2Error("shared cache builder outcome violates its contract") from exc
    return payload


def write_cache_build_outcome_receipt(*, path: str | Path, run_date: str, result: dict) -> dict:
    """Atomically write the de-identified builder result consumed by the launcher."""
    payload = _cache_build_outcome_payload(result=result, run_date=run_date)
    _atomic_write(Path(path), payload)
    return payload


def _empty_cache() -> dict:
    return {
        "schema_name": "a_short_factor_comparison_v2_daily_cache",
        "schema_version": DAILY_CACHE_SCHEMA_VERSION,
        "stocks": [],
        "limits": [],
        "benchmarks": [],
        "rows": [],
        "meta": {
            "cache_kind": "a_short_shared_incremental",
            "source": "tushare:daily+adj_factor+stk_limit+index_daily",
        },
    }


def _load_existing_cache(root: Path) -> dict:
    path = root / DAILY_CACHE_NAME
    if not path.exists():
        return _empty_cache()
    try:
        document = _load_json(path)
        schema = _load_json(DAILY_CACHE_SCHEMA_PATH)
        jsonschema.validate(document, schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ComparisonV2Error("v2 existing daily cache violates its frozen contract") from exc
    return _upgrade_cache_document(document)


def _upgrade_cache_document(document: dict) -> dict:
    """Derive the current cache shape in memory; never rewrite legacy bytes."""
    upgraded = {
        "schema_name": "a_short_factor_comparison_v2_daily_cache",
        "schema_version": DAILY_CACHE_SCHEMA_VERSION,
        "stocks": [], "limits": [], "benchmarks": [], "rows": [],
        "meta": dict(document.get("meta") or {}),
    }
    meta = upgraded["meta"]
    meta.setdefault("cache_kind", "a_short_shared_incremental")
    meta.setdefault("source", "tushare:daily+adj_factor+stk_limit")
    meta.setdefault("writer", "runners/a_short_factor_comparison_v2_cache_build.py")
    meta.setdefault("last_run_date", _today())
    meta.setdefault("consumers", [])
    meta.setdefault("provider_call_ceiling", DEFAULT_MAX_PROVIDER_CALLS)
    meta.setdefault("deferred_due_to_budget", {})
    raw_fields = ("open", "high", "low", "close", "vol")
    for raw in document.get("stocks") or []:
        row = dict(raw)
        # Legacy 1.0 rows did not carry the execution-only raw fields.  Keep
        # the old bytes untouched, but make the in-memory upgrade explicit
        # and pending rather than letting the 1.2 closed-world schema reject
        # the row before the provider seam can enrich it.
        for field in ("high", "low", "vol"):
            row.setdefault(field, None)
        raw_observed = row.get("raw_provider_observed")
        if not isinstance(raw_observed, bool):
            raw_observed = any(_finite(row.get(field)) for field in raw_fields)
        row["raw_provider_observed"] = raw_observed
        if "suspended" not in row or (not raw_observed and not any(_finite(row.get(field)) for field in raw_fields)):
            volume = _optional_number(row.get("vol"))
            row["suspended"] = bool(volume <= 0.0) if raw_observed and volume is not None else None
        adj_observed = row.get("adj_factor_observed")
        if not isinstance(adj_observed, bool):
            adj_observed = _finite(row.get("adj_factor")) and float(row.get("adj_factor")) > 0.0
        row["adj_factor_observed"] = bool(adj_observed)
        if adj_observed:
            row["adj_factor_source"] = "provider_observed"
        else:
            row["adj_factor_source"] = "provider_missing"
            row["adj_factor"] = None
        row.setdefault("corporate_action_verified", False)
        upgraded["stocks"].append(row)
    for raw in document.get("limits") or []:
        row = dict(raw)
        observed = row.get("provider_observed")
        if not isinstance(observed, bool):
            observed = any(_finite(row.get(field)) for field in ("up_limit", "down_limit"))
        row["provider_observed"] = observed
        row.setdefault("down_limit", None)
        upgraded["limits"].append(row)
    for raw in document.get("benchmarks") or []:
        row = dict(raw)
        observed = row.get("provider_observed")
        row["provider_observed"] = observed if isinstance(observed, bool) else any(
            _finite(row.get(field)) for field in ("open", "close")
        )
        upgraded["benchmarks"].append(row)
    stocks = _dedupe_rows(upgraded["stocks"], key_names=("ts_code", "trade_date"), label="upgraded stocks")
    limits = _dedupe_rows(upgraded["limits"], key_names=("ts_code", "trade_date"), label="upgraded limits")
    upgraded["stocks"] = [stocks[key] for key in sorted(stocks)]
    upgraded["limits"] = [limits[key] for key in sorted(limits)]
    benchmarks = _dedupe_rows(upgraded["benchmarks"], key_names=("ts_code", "trade_date"), label="upgraded benchmarks")
    upgraded["benchmarks"] = [benchmarks[key] for key in sorted(benchmarks)]
    upgraded["rows"] = _execution_projection(stocks, limits)
    try:
        jsonschema.validate(upgraded, _load_json(DAILY_CACHE_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise ComparisonV2Error("v2 upgraded daily cache violates its frozen contract") from exc
    return upgraded


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
        if not is_current_governed_capture(capture):
            # Old epoch evidence remains on disk for diagnosis but must not
            # consume fresh cache/provider budget or enter this admission's clock.
            continue
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
                "consumer": "v2_factor_comparison",
                "decision_date": decision_date,
                "price_data_through": price_data_through,
                "window_mode": "captured_start",
                "horizon_days": max(HORIZONS),
                "symbols": symbols,
            })
    return windows


def _normalize_captured_windows(requests: list[dict], *, consumer: str, label: str) -> list[dict]:
    """Accept captured-start and managed-exit frozen requests at the provider seam."""
    windows = []
    for request in requests:
        if not isinstance(request, dict):
            raise ComparisonV2Error(f"{label} cache request is malformed")
        request_consumer = str(request.get("consumer") or consumer)
        if request_consumer != consumer:
            raise ComparisonV2Error(f"{label} cache request has the wrong consumer")
        symbols = request.get("symbols") or []
        if not isinstance(symbols, list) or not all(str(symbol) for symbol in symbols):
            raise ComparisonV2Error(f"{label} cache request has no valid symbols")
        mode = str(request.get("window_mode") or "captured_start")
        if mode not in {"captured_start", "managed_exit"}:
            raise ComparisonV2Error(f"{label} cache request has an invalid window_mode")
        window = {
            "consumer": consumer,
            "decision_date": _string_date(request.get("decision_date"), f"{label} decision_date"),
            "price_data_through": _string_date(request.get("price_data_through"), f"{label} price_data_through"),
            "window_mode": mode,
            "horizon_days": int(request.get("horizon_days") or max(HORIZONS)),
            "symbols": [str(symbol) for symbol in symbols],
        }
        if mode == "managed_exit":
            pre_history_days = request.get("pre_history_days")
            if not isinstance(pre_history_days, int) or isinstance(pre_history_days, bool) or pre_history_days < 0:
                raise ComparisonV2Error(f"{label} cache request has an invalid pre_history_days")
            window["pre_history_days"] = pre_history_days
        windows.append(window)
    return windows


def _load_consumer_ledger(path: str | Path | None, schema_name: str, label: str) -> dict | None:
    if path is None:
        return None
    source = Path(path)
    if not source.is_file():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComparisonV2Error(f"{label} private ledger is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_name") != schema_name or \
            not isinstance(payload.get("epochs"), list):
        raise ComparisonV2Error(f"{label} private ledger contract is invalid")
    return payload


def _p2_active_records(payload: dict) -> list[dict]:
    try:
        from runners.a_short_target_policy_comparison_runner import _active_epoch, _validate_ledger
        _validate_ledger(payload)
        target_epoch = _active_epoch(payload, create=False, track="target_exit")
        breakout_epoch = _active_epoch(payload, create=False, track="breakout_entry")
    except Exception as exc:
        raise ComparisonV2Error("P2 target-policy private ledger contract is invalid") from exc
    target_records = list((target_epoch or {}).get("records", []))
    breakout_records = list((breakout_epoch or {}).get("records", []))
    # Keep component evidence separate: a target epoch reset must not relay an
    # older breakout record (or the reverse) into a fresh cache request.
    return [*target_records, *breakout_records]


def _p3_active_records(payload: dict) -> list[dict]:
    try:
        from runners.a_short_final_action_validation_runner import _active_epoch, _validate_ledger
        _validate_ledger(payload)
        epoch = _active_epoch(payload, create=False)
    except Exception as exc:
        raise ComparisonV2Error("P3 final-action private ledger contract is invalid") from exc
    return list(epoch["records"]) if epoch is not None else []


def _p2_windows(path: str | Path | None, run_date: str) -> list[dict]:
    payload = _load_consumer_ledger(
        path, "a_short_target_policy_comparison_ledger", "P2 target-policy"
    )
    if payload is None:
        return []
    windows: list[dict] = []
    for record in _p2_active_records(payload):
        if record.get("forward_eligible") is not True:
            continue
        decision_date = _string_date(record.get("decision_date"), "P2 decision_date")
        if decision_date > run_date:
            continue
        symbols: set[str] = set()
        for entry in record.get("target_entries") or []:
            if not isinstance(entry, dict) or entry.get("changed") is not True or \
                    (entry.get("outcomes") or {}).get("status") == "settled":
                continue
            if isinstance(entry.get("baseline"), dict) and isinstance(entry.get("challenger"), dict) and \
                    str(entry.get("ts_code") or ""):
                symbols.add(str(entry["ts_code"]))
        for entry in record.get("breakout_entries") or []:
            if not isinstance(entry, dict) or entry.get("changed") is not True or \
                    (entry.get("outcomes") or {}).get("status") == "settled":
                continue
            if isinstance(entry.get("entry_plan"), dict) and str(entry.get("ts_code") or ""):
                symbols.add(str(entry["ts_code"]))
        if symbols:
            windows.append({
                "consumer": "p2_target_policy",
                "decision_date": decision_date,
                "window_mode": "managed_exit",
                "pre_history_days": EXECUTION_PRE_HISTORY_DAYS,
                "horizon_days": EXECUTION_HORIZON_DAYS,
                "symbols": sorted(symbols),
            })
    return windows


def _p3_windows(path: str | Path | None, run_date: str) -> list[dict]:
    payload = _load_consumer_ledger(
        path, "a_short_final_action_validation_private_ledger", "P3 final-action"
    )
    if payload is None:
        return []
    windows: list[dict] = []
    for record in _p3_active_records(payload):
        if record.get("forward_eligible") is not True or \
                (record.get("full_edge_result") or {}).get("status") == "settled":
            continue
        decision_date = _string_date(record.get("decision_date"), "P3 decision_date")
        if decision_date > run_date:
            continue
        plans = record.get("managed_plans") or {}
        selected = record.get("selected_codes") or []
        if not isinstance(plans, dict) or not isinstance(selected, list):
            raise ComparisonV2Error("P3 final-action private ledger record is invalid")
        symbols = sorted({str(code) for code in selected
                          if str(code) and isinstance(plans.get(str(code)), dict)})
        if symbols:
            windows.append({
                "consumer": "p3_final_action_validation",
                "decision_date": decision_date,
                "window_mode": "managed_exit",
                "pre_history_days": EXECUTION_PRE_HISTORY_DAYS,
                "horizon_days": EXECUTION_HORIZON_DAYS,
                "symbols": symbols,
            })
    return windows


def _official_operation_windows(root: str | Path | None, run_date: str) -> list[dict]:
    """Read frozen formal-operation requests; this provider seam does not settle them."""
    if root is None:
        return []
    try:
        from runners.a_short_official_operation_evidence import cache_consumer_windows
        requests = cache_consumer_windows(root=root, run_date=run_date)
    except Exception as exc:
        raise ComparisonV2Error("official operation evidence private capture is invalid") from exc
    return _normalize_captured_windows(requests, consumer="official_operation_evidence",
                                       label="official operation evidence")


def _p4_windows(root: str | Path | None, run_date: str) -> list[dict]:
    """P4a is deliberately last: it cannot starve formal/P0/P5/P2/P3 consumers."""
    if root is None:
        return []
    try:
        from engine.a_short_overlay_adjudication import cache_consumer_windows
        requests = cache_consumer_windows(root=root, run_date=run_date)
    except Exception as exc:
        raise ComparisonV2Error("P4a overlay-adjudication private capture is invalid") from exc
    return _normalize_captured_windows(requests, consumer="p4_overlay_adjudication", label="P4a overlay adjudication")


def _calendar_start_hint(windows: list[dict]) -> str:
    hints: list[str] = []
    for window in windows:
        if window.get("window_mode") == "captured_start":
            hints.append(str(window["price_data_through"]))
            continue
        decision = datetime.strptime(str(window["decision_date"]), "%Y%m%d")
        hints.append((decision - timedelta(days=60)).strftime("%Y%m%d"))
        if window.get("price_data_through"):
            hints.append(str(window["price_data_through"]))
    return min(hints)


def _needed_dates_by_symbol(
    windows: list[dict], trading_dates: list[str], run_date: str,
) -> tuple[dict[str, set[str]], dict[str, tuple[int, str, str]], dict[str, set[str]]]:
    date_pos = {day: index for index, day in enumerate(trading_dates)}
    needed: dict[str, set[str]] = {}
    order: dict[str, tuple[int, str, str]] = {}
    consumers: dict[str, set[str]] = {}
    for window in windows:
        decision = window["decision_date"]
        if decision not in date_pos:
            raise ComparisonV2Error("shared cache builder cannot prove a decision date from provider calendar")
        if window.get("window_mode") == "captured_start":
            start = window["price_data_through"]
            if start not in date_pos:
                raise ComparisonV2Error("shared cache builder cannot prove a captured price date")
            start_index = date_pos[start]
        else:
            start_index = max(0, date_pos[decision] - int(window.get("pre_history_days") or 0))
            reference_date = window.get("price_data_through")
            if reference_date is not None:
                if reference_date not in date_pos:
                    raise ComparisonV2Error("shared cache builder cannot prove a managed-exit price reference date")
                start_index = min(start_index, date_pos[reference_date])
        end_index = min(len(trading_dates) - 1, date_pos[decision] + int(window["horizon_days"]))
        wanted = set(trading_dates[start_index:end_index + 1])
        wanted = {day for day in wanted if day <= run_date}
        consumer = str(window["consumer"])
        priority = CONSUMER_PRIORITY[consumer]
        for symbol in window["symbols"]:
            needed.setdefault(symbol, set()).update(wanted)
            order[symbol] = min(order.get(symbol, (priority, decision, symbol)),
                                (priority, decision, symbol))
            consumers.setdefault(symbol, set()).add(consumer)
    return needed, order, consumers


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


def _frame_records_with_optional_fields(
    frame: pd.DataFrame, required: tuple[str, ...], optional: tuple[str, ...], label: str,
) -> dict[tuple[str, str], dict]:
    fields = (*required, *(field for field in optional if field in frame.columns)) if frame is not None else required
    return _frame_records(frame, fields, label)


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
                    fields="ts_code,trade_date,open,high,low,close,vol")
    adjustment = ts_call(pro.adj_factor, retries=1, ts_code=symbol, start_date=start_date, end_date=end_date,
                         fields="ts_code,trade_date,adj_factor")
    limits = ts_call(pro.stk_limit, retries=1, ts_code=symbol, start_date=start_date, end_date=end_date,
                     fields="ts_code,trade_date,up_limit,down_limit")
    return (daily if daily is not None else pd.DataFrame(),
            adjustment if adjustment is not None else pd.DataFrame(),
            limits if limits is not None else pd.DataFrame())


def _single_attempt_benchmark_frame(pro: Any, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """One provider-observed index range; P4a never invents or adjusts a benchmark."""
    frame = ts_call(pro.index_daily, retries=1, ts_code=symbol, start_date=start_date, end_date=end_date,
                    fields="ts_code,trade_date,open,close")
    return frame if frame is not None else pd.DataFrame()


def _provider_benchmark_rows(*, symbol: str, wanted_dates: set[str], frame: pd.DataFrame) -> list[dict]:
    rows = _frame_records(frame, ("ts_code", "trade_date", "open", "close"), "index_daily")
    return [{"ts_code": symbol, "trade_date": day,
             "open": _optional_number(rows.get((symbol, day), {}).get("open")),
             "close": _optional_number(rows.get((symbol, day), {}).get("close")),
             "provider_observed": (symbol, day) in rows}
            for day in sorted(wanted_dates)]


def _provider_rows_for_symbol(*, symbol: str, wanted_dates: set[str], daily: pd.DataFrame,
                              adj: pd.DataFrame, limits: pd.DataFrame,
                              require_execution_fields: bool) -> tuple[list[dict], list[dict]]:
    daily_by_key = (_frame_records(
        daily, ("ts_code", "trade_date", "open", "high", "low", "close", "vol"), "daily"
    ) if require_execution_fields else _frame_records_with_optional_fields(
        daily, ("ts_code", "trade_date", "open", "close"), ("high", "low", "vol"), "daily"
    ))
    adj_by_key = _frame_records(adj, ("ts_code", "trade_date", "adj_factor"), "adj_factor")
    limit_by_key = (_frame_records(
        limits, ("ts_code", "trade_date", "up_limit", "down_limit"), "stk_limit"
    ) if require_execution_fields else _frame_records_with_optional_fields(
        limits, ("ts_code", "trade_date", "up_limit"), ("down_limit",), "stk_limit"
    ))
    stocks, limit_rows = [], []
    for trade_date in sorted(wanted_dates):
        raw = daily_by_key.get((symbol, trade_date))
        adjustment = adj_by_key.get((symbol, trade_date), {}).get("adj_factor")
        observed = _finite(adjustment) and float(adjustment) > 0.0
        volume = _optional_number(raw.get("vol")) if raw is not None else None
        raw_provider_observed = raw is not None
        suspended = bool(volume <= 0.0) if raw_provider_observed and volume is not None else None
        limit = limit_by_key.get((symbol, trade_date), {})
        stocks.append({
            "ts_code": symbol,
            "trade_date": trade_date,
            "open": _optional_number(raw.get("open")) if raw is not None else None,
            "high": _optional_number(raw.get("high")) if raw is not None else None,
            "low": _optional_number(raw.get("low")) if raw is not None else None,
            "close": _optional_number(raw.get("close")) if raw is not None else None,
            "vol": volume,
            "suspended": suspended,
            "raw_provider_observed": raw_provider_observed,
            "adj_factor": float(adjustment) if observed else None,
            "adj_factor_observed": observed,
            "adj_factor_source": "provider_observed" if observed else "provider_missing",
            "corporate_action_verified": False,
        })
        limit_rows.append({
            "ts_code": symbol,
            "trade_date": trade_date,
            "up_limit": _optional_number(limit.get("up_limit")),
            "down_limit": _optional_number(limit.get("down_limit")),
            "provider_observed": (symbol, trade_date) in limit_by_key,
        })
    return stocks, limit_rows


def _p5_frozen_windows(industry_weight_root: str | Path | None, run_date: str) -> list[dict]:
    """Read P5's explicit consumer requests only; this builder never reads its ledger/outcomes."""
    if industry_weight_root is None:
        return []
    from engine.a_short_industry_weight_comparison import cache_consumer_windows
    return _normalize_captured_windows(
        cache_consumer_windows(root=industry_weight_root, run_date=run_date),
        consumer="p5_industry_weight", label="P5",
    )


def _normalise_merge_row(label: str, raw: dict) -> dict:
    row = dict(raw)
    if label == "stocks":
        for field in ("high", "low", "vol", "suspended"):
            row.setdefault(field, None)
        if not isinstance(row.get("raw_provider_observed"), bool):
            row["raw_provider_observed"] = any(_finite(row.get(field)) for field in ("open", "high", "low", "close", "vol"))
        if not row["raw_provider_observed"]:
            row["suspended"] = None
        elif row.get("suspended") is None and _finite(row.get("vol")):
            row["suspended"] = bool(float(row["vol"]) <= 0.0)
        row.setdefault("adj_factor", None)
        adj_observed = row.get("adj_factor_observed")
        if not isinstance(adj_observed, bool):
            adj_observed = _finite(row.get("adj_factor")) and float(row.get("adj_factor")) > 0.0
        row["adj_factor_observed"] = bool(adj_observed)
        if adj_observed:
            row["adj_factor_source"] = "provider_observed"
        else:
            row["adj_factor"] = None
            row["adj_factor_source"] = "provider_missing"
        row.setdefault("corporate_action_verified", False)
    elif label == "limits":
        row.setdefault("down_limit", None)
        if not isinstance(row.get("provider_observed"), bool):
            row["provider_observed"] = any(_finite(row.get(field)) for field in ("up_limit", "down_limit"))
    elif label == "benchmarks":
        if not isinstance(row.get("provider_observed"), bool):
            row["provider_observed"] = any(_finite(row.get(field)) for field in ("open", "close"))
    return row


def _validate_cache_row_state(label: str, row: dict) -> None:
    if label == "stocks":
        raw_observed = row.get("raw_provider_observed")
        if not isinstance(raw_observed, bool):
            raise ComparisonV2Error("invalid_cache_row_state")
        raw_fields = ("open", "high", "low", "close", "vol")
        if not raw_observed and any(_finite(row.get(field)) for field in raw_fields):
            raise ComparisonV2Error("invalid_cache_row_state")
        if raw_observed and not any(_finite(row.get(field)) for field in raw_fields):
            raise ComparisonV2Error("invalid_cache_row_state")
        if row.get("suspended") is not None and not isinstance(row.get("suspended"), bool):
            raise ComparisonV2Error("invalid_cache_row_state")
        if not raw_observed and row.get("suspended") is not None:
            raise ComparisonV2Error("invalid_cache_row_state")
        adj_observed = row.get("adj_factor_observed")
        source = row.get("adj_factor_source")
        factor = row.get("adj_factor")
        if adj_observed is True and (not _finite(factor) or float(factor) <= 0.0 or source != "provider_observed"):
            raise ComparisonV2Error("invalid_cache_row_state")
        if adj_observed is not True and (factor is not None or source not in {"provider_missing", "provider_empty"}):
            raise ComparisonV2Error("invalid_cache_row_state")
        if row.get("corporate_action_verified") is not None and not isinstance(row.get("corporate_action_verified"), bool):
            raise ComparisonV2Error("invalid_cache_row_state")
        return
    if label in {"limits", "benchmarks"}:
        observed = row.get("provider_observed")
        if not isinstance(observed, bool):
            raise ComparisonV2Error("invalid_cache_row_state")
        fields = ("up_limit", "down_limit") if label == "limits" else ("open", "close")
        if not observed and any(_finite(row.get(field)) for field in fields):
            raise ComparisonV2Error("invalid_cache_row_state")
        if observed and not any(_finite(row.get(field)) for field in fields):
            raise ComparisonV2Error("invalid_cache_row_state")


def _merge_values(previous: dict, incoming: dict, fields: tuple[str, ...], label: str, key: tuple[str, str]) -> None:
    for field in fields:
        old_value, new_value = previous.get(field), incoming.get(field)
        if old_value is not None and new_value is not None and old_value != new_value:
            raise ComparisonV2Error(f"shared {label} has conflicting_duplicate_key {key[0]} {key[1]}")


def _row_family_complete(label: str, row: dict) -> bool:
    if label == "stocks":
        return row.get("raw_provider_observed") is True and _row_has_fields(
            row, {"open", "high", "low", "close", "vol", "suspended"}
        )
    if label == "limits":
        return row.get("provider_observed") is True and _row_has_fields(
            row, {"up_limit", "down_limit"}
        )
    if label == "benchmarks":
        return row.get("provider_observed") is True and _row_has_fields(
            row, {"open", "close"}
        )
    raise ComparisonV2Error(f"unsupported shared cache label {label}")


def _merge_partial_rows(existing: dict[tuple[str, str], dict], new_rows: list[dict], *, label: str) -> dict[tuple[str, str], dict]:
    merged = {key: _normalise_merge_row(label, value) for key, value in existing.items()}
    for value in merged.values():
        _validate_cache_row_state(label, value)
    incoming = {
        key: _normalise_merge_row(label, value)
        for key, value in _dedupe_rows(new_rows, key_names=("ts_code", "trade_date"), label=f"new {label}").items()
    }
    fields = {
        "stocks": ("open", "high", "low", "close", "vol", "suspended", "adj_factor", "adj_factor_observed", "adj_factor_source", "corporate_action_verified"),
        "limits": ("up_limit", "down_limit", "provider_observed"),
        "benchmarks": ("open", "close", "provider_observed"),
    }[label]
    raw_fields = ("open", "high", "low", "close", "vol", "suspended")
    for key, row in incoming.items():
        _validate_cache_row_state(label, row)
        previous = merged.get(key)
        if previous is None:
            merged[key] = row
            continue
        upgraded = dict(previous)
        if label == "stocks":
            if not (_row_family_complete(label, previous) and not _row_family_complete(label, row)):
                _merge_values(previous, row, raw_fields, label, key)
                for field in raw_fields:
                    if upgraded.get(field) is None and row.get(field) is not None:
                        upgraded[field] = row[field]
                upgraded["raw_provider_observed"] = previous["raw_provider_observed"] or row["raw_provider_observed"]
            previous_adj_complete = previous.get("adj_factor_observed") is True
            incoming_adj_complete = row.get("adj_factor_observed") is True
            if not (previous_adj_complete and not incoming_adj_complete):
                _merge_values(previous, row, ("adj_factor",), label, key)
                if previous.get("adj_factor") is None and row.get("adj_factor") is not None:
                    for field in ("adj_factor", "adj_factor_observed", "adj_factor_source"):
                        upgraded[field] = row[field]
                elif previous_adj_complete and incoming_adj_complete and (
                    previous.get("adj_factor_observed") != row.get("adj_factor_observed") or
                    previous.get("adj_factor_source") != row.get("adj_factor_source")
                ):
                    raise ComparisonV2Error(f"shared {label} has conflicting_duplicate_key {key[0]} {key[1]}")
            # Verification is monotonic metadata: a later confirmed flag may
            # upgrade an unverified row, but a weaker observation cannot
            # downgrade an already verified row.
            upgraded["corporate_action_verified"] = bool(
                previous.get("corporate_action_verified") or row.get("corporate_action_verified")
            )
        else:
            value_fields = fields[:-1]
            if not (_row_family_complete(label, previous) and not _row_family_complete(label, row)):
                _merge_values(previous, row, value_fields, label, key)
                for field in value_fields:
                    if upgraded.get(field) is None and row.get(field) is not None:
                        upgraded[field] = row[field]
                upgraded["provider_observed"] = previous["provider_observed"] or row["provider_observed"]
        _validate_cache_row_state(label, upgraded)
        merged[key] = upgraded
    return merged


def _row_has_fields(row: dict | None, fields: set[str]) -> bool:
    if not isinstance(row, dict) or not fields.issubset(row):
        return False
    return all(row.get(field) is not None for field in fields)


def _confirmed_empty(label: str, row: dict | None) -> bool:
    # Shared daily-cache empty rows are deliberately retryable.  The V1
    # contract only permits stable empty results for endpoints whose business
    # contract explicitly says that an empty response is a complete result;
    # raw prices, limits, and benchmark endpoints do not have that contract.
    return False


def _raw_fetch_required(row: dict | None, fields: set[str]) -> bool:
    return not _confirmed_empty("stocks", row) and not (
        isinstance(row, dict) and row.get("raw_provider_observed") is True and _row_has_fields(row, fields)
    )


def _adj_fetch_required(row: dict | None) -> bool:
    if not isinstance(row, dict):
        return True
    return not (row.get("adj_factor_observed") is True and _finite(row.get("adj_factor")) and
                float(row["adj_factor"]) > 0.0 and row.get("adj_factor_source") == "provider_observed")


def _limit_fetch_required(row: dict | None, fields: set[str]) -> bool:
    return not _confirmed_empty("limits", row) and not (
        isinstance(row, dict) and row.get("provider_observed") is True and _row_has_fields(row, fields)
    )


def _benchmark_fetch_required(row: dict | None) -> bool:
    return not _confirmed_empty("benchmarks", row) and not (
        isinstance(row, dict) and row.get("provider_observed") is True and
        _row_has_fields(row, {"open", "close"})
    )


def _missing_symbols(
    *, needed: dict[str, set[str]], consumers: dict[str, set[str]],
    stocks: dict[tuple[str, str], dict], limits: dict[tuple[str, str], dict],
) -> set[str]:
    missing: set[str] = set()
    for symbol, dates in needed.items():
        execution_required = bool(consumers.get(symbol, set()) & {
            "p2_target_policy", "p3_final_action_validation", "official_operation_evidence", "p4_overlay_adjudication",
        })
        stock_fields = {"open", "close", "adj_factor", "adj_factor_observed", "adj_factor_source"}
        limit_fields = {"up_limit"}
        if execution_required:
            stock_fields.update({"high", "low", "vol", "suspended"})
            limit_fields.add("down_limit")
        if any(_raw_fetch_required(stocks.get((symbol, day)), {"open", "close"} | (
                    {"high", "low", "vol", "suspended"} if execution_required else set()
                )) or _adj_fetch_required(stocks.get((symbol, day))) or
               _limit_fetch_required(limits.get((symbol, day)), limit_fields) for day in dates):
            missing.add(symbol)
    return missing


def _adjusted(value: object, adjustment: object) -> float | None:
    if not (_finite(value) and _finite(adjustment)) or float(value) <= 0.0 or float(adjustment) <= 0.0:
        return None
    result = float(value) * float(adjustment)
    return result if math.isfinite(result) and result > 0.0 else None


def _execution_projection(
    stocks: dict[tuple[str, str], dict], limits: dict[tuple[str, str], dict],
) -> list[dict]:
    rows: list[dict] = []
    previous_adjustment: dict[str, float] = {}
    for key in sorted(stocks):
        stock = stocks[key]
        limit = limits.get(key) or {}
        adjustment = stock.get("adj_factor") if stock.get("adj_factor_observed") is True else None
        adjustment_value = float(adjustment) if _finite(adjustment) and float(adjustment) > 0.0 else None
        prior = previous_adjustment.get(key[0])
        unverified_action = prior is not None and adjustment_value is not None and \
            not math.isclose(prior, adjustment_value, rel_tol=1e-12, abs_tol=1e-12) and \
            stock.get("corporate_action_verified") is not True
        if adjustment_value is not None:
            previous_adjustment[key[0]] = adjustment_value
        execution_adjustment = None if unverified_action else adjustment
        volume = _optional_number(stock.get("vol"))
        rows.append({
            "ts_code": key[0],
            "trade_date": key[1],
            "open": _adjusted(stock.get("open"), execution_adjustment),
            "high": _adjusted(stock.get("high"), execution_adjustment),
            "low": _adjusted(stock.get("low"), execution_adjustment),
            "close": _adjusted(stock.get("close"), execution_adjustment),
            "volume": volume,
            "suspended": stock.get("suspended"),
            "up_limit": _adjusted(limit.get("up_limit"), execution_adjustment),
            "down_limit": _adjusted(limit.get("down_limit"), execution_adjustment),
            "raw_close": _optional_number(stock.get("close")),
            "adj_factor": _optional_number(execution_adjustment),
            "corporate_action_verified": bool(stock.get("corporate_action_verified", False)),
        })
    return rows


def materialize_incremental_cache(
    *, root: str | Path, run_date: str, max_provider_calls: int = DEFAULT_MAX_PROVIDER_CALLS,
    pro: Any | None = None, industry_weight_root: str | Path | None = None,
    target_policy_root: str | Path | None = None,
    final_action_validation_root: str | Path | None = None,
    official_operation_evidence_root: str | Path | None = None,
    overlay_adjudication_root: str | Path | None = None,
) -> dict:
    """Fetch frozen v2/P5/P2/P3/official windows into one atomic private cache."""
    private_root = _private_root(root)
    run_date = _string_date(run_date, "run_date")
    if run_date != _today():
        raise ComparisonV2Error("shared cache builder requires the real local run_date")
    if not isinstance(max_provider_calls, int) or isinstance(max_provider_calls, bool) or max_provider_calls < 1:
        raise ComparisonV2Error("shared cache builder max_provider_calls must be a positive integer")
    v2_windows = _normalize_captured_windows(
        _frozen_windows(private_root, run_date), consumer="v2_factor_comparison", label="v2"
    )
    p5_windows = _p5_frozen_windows(industry_weight_root, run_date)
    p2_windows = _p2_windows(target_policy_root, run_date)
    p3_windows = _p3_windows(final_action_validation_root, run_date)
    official_windows = _official_operation_windows(official_operation_evidence_root, run_date)
    p4_windows = _p4_windows(overlay_adjudication_root, run_date)
    windows = [*v2_windows, *p5_windows, *p2_windows, *p3_windows, *official_windows, *p4_windows]
    if not windows:
        return {"status": ("no_frozen_v2_captures" if industry_weight_root is None and
                           target_policy_root is None and final_action_validation_root is None and
                           official_operation_evidence_root is None and overlay_adjudication_root is None
                           else "no_frozen_consumer_captures"), "provider_calls": 0,
                "p5_deferred_due_to_budget": 0, "production_unchanged": True}
    requested_symbols = {symbol for window in windows for symbol in window["symbols"]}
    if any(not is_a_share_main_board(symbol) for symbol in requested_symbols):
        raise ComparisonV2Error("shared cache request contains a non-main-board or malformed symbol")
    existing = _load_existing_cache(private_root)
    existing_stocks = _dedupe_rows(existing["stocks"], key_names=("ts_code", "trade_date"), label="existing stocks")
    existing_limits = _dedupe_rows(existing["limits"], key_names=("ts_code", "trade_date"), label="existing limits")
    existing_benchmarks = _dedupe_rows(existing.get("benchmarks") or [], key_names=("ts_code", "trade_date"), label="existing benchmarks")
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
    if pro is None:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise ComparisonV2Error("TUSHARE_TOKEN is required to materialize the private shared cache")
        pro = init_tushare_pro(token)
    trading_dates = _single_attempt_trade_calendar(pro, _calendar_start_hint(windows), run_date)
    consumer_names = sorted({str(window["consumer"]) for window in windows})
    needed, _all_order, _all_consumers = _needed_dates_by_symbol(windows, trading_dates, run_date)
    windows_by_consumer = {
        "v2_factor_comparison": v2_windows,
        "p5_industry_weight": p5_windows,
        "p2_target_policy": p2_windows,
        "p3_final_action_validation": p3_windows,
        "official_operation_evidence": official_windows,
        "p4_overlay_adjudication": p4_windows,
    }
    missing_by_consumer: dict[str, set[str]] = {}
    missing_order: dict[str, tuple[int, str, str]] = {}
    for consumer, consumer_windows in windows_by_consumer.items():
        if not consumer_windows:
            missing_by_consumer[consumer] = set()
            continue
        consumer_needed, consumer_order, consumer_map = _needed_dates_by_symbol(
            consumer_windows, trading_dates, run_date
        )
        consumer_missing = _missing_symbols(
            needed=consumer_needed, consumers=consumer_map, stocks=existing_stocks, limits=existing_limits,
        )
        missing_by_consumer[consumer] = consumer_missing
        for symbol in consumer_missing:
            missing_order[symbol] = min(missing_order.get(symbol, consumer_order[symbol]), consumer_order[symbol])
    v2_missing = missing_by_consumer["v2_factor_comparison"]
    v2_calls = 1 + 3 * len(v2_missing)
    if v2_calls > max_provider_calls:
        raise ComparisonV2Error(
            f"v2 cache builder provider-call budget exceeded after existing-cache check: {v2_calls}>{max_provider_calls}"
        )
    missing_symbols = set(missing_order)
    p4_symbols = {symbol for window in p4_windows for symbol in window["symbols"]}
    p4_needed_dates = set().union(*(needed.get(symbol, set()) for symbol in p4_symbols)) if p4_symbols else set()
    if not missing_symbols and not p4_windows:
        return {"status": "cache_current", "provider_calls": 1, "consumers": consumer_names,
                "p5_deferred_due_to_budget": 0,
                "production_unchanged": True}
    symbol_capacity = max(0, (max_provider_calls - 1) // 3)
    scheduled = sorted(v2_missing, key=lambda symbol: missing_order[symbol])
    remaining_capacity = symbol_capacity - len(scheduled)
    scheduled.extend(sorted(missing_symbols - set(scheduled), key=lambda symbol: missing_order[symbol])[:remaining_capacity])
    deferred = sorted(missing_symbols - set(scheduled), key=lambda symbol: missing_order[symbol])
    deferred_by_consumer = {
        consumer: sum(symbol in missing_by_consumer[consumer] for symbol in deferred)
        for consumer in consumer_names
    }
    if not scheduled and not p4_symbols:
        return {
            "status": "deferred_due_to_budget", "provider_calls": 1,
            "consumers": consumer_names,
            "deferred_symbols_by_consumer": deferred_by_consumer,
            "p5_deferred_due_to_budget": deferred_by_consumer.get("p5_industry_weight", 0),
            "production_unchanged": True,
        }
    new_stocks, new_limits = [], []
    for symbol in scheduled:
        wanted_dates = needed[symbol]
        daily, adj, limits = _single_attempt_symbol_frames(pro, symbol, min(wanted_dates), max(wanted_dates))
        stock_rows, limit_rows = _provider_rows_for_symbol(symbol=symbol, wanted_dates=wanted_dates,
                                                            daily=daily, adj=adj, limits=limits,
                                                            require_execution_fields=any(
                                                                symbol in missing_by_consumer[consumer]
                                                                for consumer in ("p2_target_policy", "p3_final_action_validation",
                                                                                 "official_operation_evidence", "p4_overlay_adjudication")
                                                            ))
        new_stocks.extend(stock_rows)
        new_limits.extend(limit_rows)
    # Benchmarks are requested only if P4's already-low-priority stock work fitted.
    # They are two existing-writer calls, inside the unchanged 91-call ceiling;
    # otherwise P4 simply remains deferred/no-count and no older consumer loses a slot.
    p4_stock_deferred = bool(p4_symbols & set(deferred))
    benchmark_codes = ("000852.SH", "000300.SH")
    benchmark_missing = [code for code in benchmark_codes if any(
        _benchmark_fetch_required(existing_benchmarks.get((code, day)))
        for day in p4_needed_dates
    )]
    benchmark_calls = 0
    new_benchmarks: list[dict] = []
    if p4_symbols and not p4_stock_deferred and benchmark_missing:
        available_calls = max_provider_calls - (1 + 3 * len(scheduled))
        if available_calls >= len(benchmark_missing):
            for code in benchmark_missing:
                frame = _single_attempt_benchmark_frame(pro, code, min(p4_needed_dates), max(p4_needed_dates))
                new_benchmarks.extend(_provider_benchmark_rows(symbol=code, wanted_dates=p4_needed_dates, frame=frame))
            benchmark_calls = len(benchmark_missing)
        else:
            deferred_by_consumer["p4_overlay_adjudication"] = deferred_by_consumer.get("p4_overlay_adjudication", 0) + len(p4_symbols)
    merged_stocks = _merge_partial_rows(existing_stocks, new_stocks, label="stocks")
    merged_limits = _merge_partial_rows(existing_limits, new_limits, label="limits")
    merged_benchmarks = _merge_partial_rows(existing_benchmarks, new_benchmarks, label="benchmarks")
    payload = {
        "schema_name": "a_short_factor_comparison_v2_daily_cache",
        "schema_version": DAILY_CACHE_SCHEMA_VERSION,
        "stocks": [merged_stocks[key] for key in sorted(merged_stocks)],
        "limits": [merged_limits[key] for key in sorted(merged_limits)],
        "benchmarks": [merged_benchmarks[key] for key in sorted(merged_benchmarks)],
        "rows": _execution_projection(merged_stocks, merged_limits),
        "meta": {
            "cache_kind": "a_short_shared_incremental",
            "source": "tushare:daily+adj_factor+stk_limit",
            "writer": "runners/a_short_factor_comparison_v2_cache_build.py",
            "last_run_date": run_date,
            "consumers": consumer_names,
            "provider_call_ceiling": max_provider_calls,
            "deferred_due_to_budget": deferred_by_consumer,
        },
    }
    try:
        jsonschema.validate(payload, _load_json(DAILY_CACHE_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise ComparisonV2Error("shared cache builder produced an invalid private cache") from exc
    _atomic_write(private_root / DAILY_CACHE_NAME, payload)
    return {
        "status": "cache_updated_with_deferrals" if any(payload["meta"]["deferred_due_to_budget"].values()) else "cache_updated",
        "provider_calls": 1 + 3 * len(scheduled) + benchmark_calls,
        "symbols_updated": scheduled,
        "consumers": consumer_names,
        "deferred_symbols_by_consumer": payload["meta"]["deferred_due_to_budget"],
        "p5_deferred_due_to_budget": payload["meta"]["deferred_due_to_budget"].get("p5_industry_weight", 0),
        "production_unchanged": True,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize frozen private A-short v2/P5/P2/P3/official windows into one cache.")
    parser.add_argument("--root", required=True, help="gitignored state/a_short/factor_comparison_private/v2 root")
    parser.add_argument("--run-date", required=True, help="actual local run date YYYYMMDD")
    parser.add_argument("--outcome-json", required=True,
                        help="launcher-only atomic status receipt path")
    parser.add_argument("--max-provider-calls", type=int, default=DEFAULT_MAX_PROVIDER_CALLS)
    parser.add_argument("--industry-weight-root", default=None,
                        help="optional gitignored P5 state/a_short/industry_weight_comparison_private/v1 root")
    parser.add_argument("--target-policy-root", help="existing gitignored P2 private ledger")
    parser.add_argument("--final-action-validation-root", help="existing gitignored P3 private ledger")
    parser.add_argument("--official-operation-evidence-root",
                        help="gitignored formal-operation capture root; consumes no provider outside this writer")
    parser.add_argument("--overlay-adjudication-root",
                        help="gitignored P4a state/a_short/overlay_adjudication_private/v1 root; lowest-priority consumer")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = materialize_incremental_cache(root=args.root, run_date=args.run_date,
                                               max_provider_calls=args.max_provider_calls,
                                               industry_weight_root=args.industry_weight_root,
                                               target_policy_root=args.target_policy_root,
                                               final_action_validation_root=args.final_action_validation_root,
                                               official_operation_evidence_root=args.official_operation_evidence_root,
                                               overlay_adjudication_root=args.overlay_adjudication_root)
        write_cache_build_outcome_receipt(path=args.outcome_json, run_date=args.run_date, result=result)
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 - the receipt is the bounded failure surface
        failure = {
            "status": "failed",
            "provider_calls": 0,
            "deferred_symbols_by_consumer": {},
            "error_code": "cache_build_failed",
            "error_detail": f"build: {safe_exception_summary(exc, limit=480)}"[:512],
            "production_unchanged": True,
        }
        try:
            write_cache_build_outcome_receipt(path=args.outcome_json, run_date=args.run_date, result=failure)
        except Exception:
            # The launcher invalidates the old receipt before invocation.  If a
            # new failure receipt cannot be written, it must observe that
            # absence and retain ``cache_outcome_missing``/process_failed.
            pass
        print("[a-short-shared-daily-cache] failed (production unchanged)", file=sys.stderr)
        return 1
    print(f"[a-short-shared-daily-cache] {result['status']} (production unchanged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
