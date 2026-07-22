"""Shared P2/P3 managed-exit simulator.

This module is deliberately input-only: it never fetches prices and never
changes an M6.7 decision.  P2's shadow ledger and the future P3 validator must
call this one evaluator so their T1/trailing semantics cannot drift apart.
"""
from __future__ import annotations

import math
from typing import Any

from runners.a_short_phase5_engine import atr14, tick_up


CONTRACT_VERSION = "1.1.0"
HORIZON_TRADING_DAYS = 20
ROUND_TRIP_COST_FRACTION = 0.0016
ATR_PERIOD = 14
ATR_HISTORY_ROWS = ATR_PERIOD + 1


class ManagedExitError(ValueError):
    """A frozen plan or execution-price input cannot prove a valid outcome."""


def net_excess_after_round_trip_cost_pct(gross_excess_pct: object) -> float:
    """Return strategy net excess over a passive benchmark in percentage points.

    ``gross_excess_pct`` is the strategy gross return minus the benchmark
    return.  The benchmark is not charged the strategy's trading cost.
    """
    if isinstance(gross_excess_pct, bool):
        raise ManagedExitError("non_finite_return")
    try:
        gross_excess = float(gross_excess_pct)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ManagedExitError("non_finite_return") from exc
    if not math.isfinite(gross_excess):
        raise ManagedExitError("non_finite_return")
    return gross_excess - ROUND_TRIP_COST_FRACTION * 100.0


def _finite_price(value: object) -> float:
    if isinstance(value, bool):
        raise ManagedExitError("non_finite_price")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ManagedExitError("non_finite_price") from exc
    if not math.isfinite(number) or number <= 0:
        raise ManagedExitError("non_finite_price")
    return number


def _finite_nonnegative(value: object) -> float:
    if isinstance(value, bool):
        raise ManagedExitError("invalid_volume")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ManagedExitError("invalid_volume") from exc
    if not math.isfinite(number) or number < 0:
        raise ManagedExitError("invalid_volume")
    return number


def _date(value: object) -> str:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        raise ManagedExitError("invalid_trade_date")
    return text


def _same_price(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-8, max(abs(left), abs(right)) * 1e-8)


def _normalise_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ManagedExitError("execution_prices_unavailable")
    normalized: list[dict[str, Any]] = []
    previous_date = ""
    for source in rows:
        if not isinstance(source, dict):
            raise ManagedExitError("invalid_execution_row")
        trade_date = _date(source.get("trade_date"))
        if trade_date <= previous_date:
            raise ManagedExitError("execution_dates_not_strictly_increasing")
        previous_date = trade_date
        row = {
            "trade_date": trade_date,
            "open": _finite_price(source.get("open")),
            "high": _finite_price(source.get("high")),
            "low": _finite_price(source.get("low")),
            "close": _finite_price(source.get("close")),
            "volume": _finite_nonnegative(source.get("volume")),
            "suspended": bool(source.get("suspended", False)),
        }
        if row["low"] > row["high"]:
            raise ManagedExitError("invalid_execution_ohlc")
        for key in ("up_limit", "down_limit", "raw_close", "adj_factor"):
            if source.get(key) is not None:
                row[key] = _finite_price(source.get(key))
            else:
                row[key] = None
        normalized.append(row)
    return normalized


def _plan_window_rows(plan: dict[str, Any], execution_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain only rows needed to evaluate one frozen H20 plan.

    A shared cache accumulates prior plans.  Its older corporate-action gaps
    must not invalidate this plan, while the reference bar, 15 completed rows
    for ATR14, and every row through H20 remain fail-closed inputs.
    """
    if not isinstance(plan, dict):
        raise ManagedExitError("invalid_frozen_plan")
    decision_date = _date(plan.get("decision_date"))
    if not isinstance(execution_rows, list) or not execution_rows:
        raise ManagedExitError("execution_prices_unavailable")
    dated_rows: list[tuple[dict[str, Any], str]] = []
    previous_date = ""
    for source in execution_rows:
        if not isinstance(source, dict):
            raise ManagedExitError("invalid_execution_row")
        trade_date = _date(source.get("trade_date"))
        if trade_date <= previous_date:
            raise ManagedExitError("execution_dates_not_strictly_increasing")
        previous_date = trade_date
        dated_rows.append((source, trade_date))

    first_horizon_index = next((index for index, (_row, trade_date) in enumerate(dated_rows)
                                if trade_date > decision_date), None)
    if first_horizon_index is None:
        return [row for row, _trade_date in dated_rows]
    last_horizon_index = min(len(dated_rows) - 1, first_horizon_index + HORIZON_TRADING_DAYS - 1)
    selected = set(range(max(0, first_horizon_index - ATR_HISTORY_ROWS), last_horizon_index + 1))
    if plan.get("price_basis") == "qfq":
        reference_date = _date(plan.get("reference_trade_date"))
        reference_index = next((index for index, (_row, trade_date) in enumerate(dated_rows)
                                if trade_date == reference_date), None)
        if reference_index is not None:
            selected.add(reference_index)
    return [row for index, (row, _trade_date) in enumerate(dated_rows) if index in selected]


def _is_one_price_limit(row: dict[str, Any], limit_key: str) -> bool:
    limit = row.get(limit_key)
    return limit is not None and _same_price(row["high"], row["low"]) and _same_price(row["close"], limit)


def _buyable(row: dict[str, Any]) -> bool:
    return not row["suspended"] and row["volume"] > 0 and not _is_one_price_limit(row, "up_limit")


def _sellable(row: dict[str, Any]) -> bool:
    # An upper-limit session is sellable; a lower-limit one-price session is not.
    return not row["suspended"] and row["volume"] > 0 and not _is_one_price_limit(row, "down_limit")


def _convert_plan(plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ManagedExitError("invalid_frozen_plan")
    decision_date = _date(plan.get("decision_date"))
    basis = str(plan.get("price_basis") or "")
    multiplier = _finite_price(plan.get("atr_multiplier"))
    if basis == "execution_raw_x_adj":
        ratio = 1.0
    elif basis == "qfq":
        reference_date = _date(plan.get("reference_trade_date"))
        reference_close = _finite_price(plan.get("reference_close"))
        reference = next((row for row in rows if row["trade_date"] == reference_date), None)
        if reference is None or reference.get("raw_close") is None or reference.get("adj_factor") is None:
            raise ManagedExitError("price_basis_mismatch")
        execution_close = reference["raw_close"] * reference["adj_factor"]
        if not math.isfinite(execution_close) or execution_close <= 0 or not _same_price(execution_close, reference["close"]):
            raise ManagedExitError("price_basis_mismatch")
        ratio = execution_close / reference_close
        if not math.isfinite(ratio) or ratio <= 0:
            raise ManagedExitError("price_basis_mismatch")
    else:
        raise ManagedExitError("price_basis_mismatch")

    levels: dict[str, float | None] = {}
    for key in ("entry_low", "entry_high", "stop", "t1", "t2"):
        value = plan.get(key)
        if value is None and key in {"t1", "t2"}:
            levels[key] = None
            continue
        levels[key] = _finite_price(value) * ratio
    if levels["stop"] >= levels["entry_high"]:
        raise ManagedExitError("invalid_frozen_plan")
    if levels["t1"] is not None and levels["t1"] <= levels["entry_high"]:
        raise ManagedExitError("invalid_frozen_plan")
    if levels["t2"] is not None and levels["t1"] is not None and levels["t2"] <= levels["t1"]:
        raise ManagedExitError("invalid_frozen_plan")
    return {
        "decision_date": decision_date,
        "price_basis": basis,
        "conversion_ratio": ratio,
        "atr_multiplier": multiplier,
        **levels,
    }


def _stop_fill(row: dict[str, Any], stop: float) -> float:
    return row["open"] if row["open"] <= stop else stop


def _t1_fill(row: dict[str, Any], t1: float) -> float:
    return row["open"] if row["open"] >= t1 else t1


def _result_no_count(reason: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "no_count",
        "reason": reason,
        "events": [],
    }


def _diagnostic_snapshot(*, horizon: list[dict[str, Any]], entry_horizon_index: int,
                         entry_price: float, fills: list[dict[str, Any]], days: int) -> dict[str, Any]:
    """Mark a fixed decision-date horizon without changing the H20 result.

    H5/H10 are diagnostic only.  A position exited before the diagnostic date
    remains cash at 0%; a still-open remainder is marked at that date's close.
    """
    cutoff = horizon[days - 1]
    if entry_horizon_index >= days:
        return {"status": "no_count", "reason": "entry_not_filled_by_horizon",
                "trade_date": cutoff["trade_date"]}
    realized = [fill for fill in fills
                if fill["kind"] != "h20_mark" and fill["trade_date"] <= cutoff["trade_date"]]
    realized_weight = sum(fill["weight"] for fill in realized)
    remaining_weight = max(0.0, 1.0 - realized_weight)
    gross_return = sum(fill["weight"] * (fill["price"] / entry_price - 1.0) for fill in realized)
    gross_return += remaining_weight * (cutoff["close"] / entry_price - 1.0)
    return {
        "status": "settled" if remaining_weight == 0 else "mark_to_market",
        "reason": None,
        "trade_date": cutoff["trade_date"],
        "unrealized": remaining_weight > 0,
        "gross_return_pct": round(gross_return * 100.0, 8),
        "net_return_pct": round((gross_return - ROUND_TRIP_COST_FRACTION) * 100.0, 8),
    }


def evaluate_managed_exit(plan: dict[str, Any], execution_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate one frozen P2/P3 plan on pre-existing execution-basis OHLCV.

    A result is either a settled H20 return or ``no_count``.  It never guesses
    a missing adjustment factor, fillability state, or price basis.
    """
    try:
        rows = _normalise_rows(_plan_window_rows(plan, execution_rows))
        frozen = _convert_plan(plan, rows)
        horizon_indices = [
            index
            for index, row in enumerate(rows)
            if row["trade_date"] > frozen["decision_date"]
        ][:HORIZON_TRADING_DAYS]
        horizon = [rows[index] for index in horizon_indices]
        if len(horizon) < HORIZON_TRADING_DAYS:
            return _result_no_count("h20_not_available")
        entry_horizon_index = next((idx for idx, row in enumerate(horizon) if _buyable(row)), None)
        if entry_horizon_index is None:
            return _result_no_count("entry_unfillable")
        entry_index = horizon_indices[entry_horizon_index]
        entry_row = rows[entry_index]
        entry_price = entry_row["open"]
        remaining_weight = 1.0
        t1_done = frozen["t1"] is None
        trailing = frozen["stop"]
        fills: list[dict[str, Any]] = []

        # Entry day itself cannot be sold under A-share T+1.  The horizon is
        # anchored to decision T+1, so a late first fill never extends H20.
        for horizon_index in range(entry_horizon_index + 1, len(horizon)):
            index = horizon_indices[horizon_index]
            row = rows[index]
            # ATR is a completed, prior-day value.  It must retain the
            # historical execution rows before the decision date rather than
            # waiting fourteen post-decision sessions to become available.
            prior_rows = rows[:index]
            atr = atr14(prior_rows, n=ATR_PERIOD)
            post_entry_high = max(item["high"] for item in rows[entry_index:index])
            if atr is not None and atr > 0:
                candidate = tick_up(post_entry_high - atr * frozen["atr_multiplier"])
                if candidate is not None:
                    trailing = max(trailing, candidate)
            if not _sellable(row):
                continue
            # Conservative priority: a stop/trailing breach consumes all
            # remaining shares before a same-day T1 touch can be credited.
            if row["low"] <= trailing:
                fills.append({"kind": "stop_or_trailing", "trade_date": row["trade_date"],
                              "price": _stop_fill(row, trailing), "weight": remaining_weight})
                remaining_weight = 0.0
                break
            if not t1_done and frozen["t1"] is not None and row["high"] >= frozen["t1"]:
                fills.append({"kind": "t1", "trade_date": row["trade_date"],
                              "price": _t1_fill(row, frozen["t1"]), "weight": 0.5})
                remaining_weight -= 0.5
                t1_done = True

        h20 = horizon[-1]
        unrealized_at_h20 = remaining_weight > 0
        if remaining_weight > 0:
            fills.append({"kind": "h20_mark", "trade_date": h20["trade_date"],
                          "price": h20["close"], "weight": remaining_weight})
        gross_return = sum(fill["weight"] * (fill["price"] / entry_price - 1.0) for fill in fills)
        net_return = gross_return - ROUND_TRIP_COST_FRACTION
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "settled",
            "reason": None,
            "decision_date": frozen["decision_date"],
            "entry_date": entry_row["trade_date"],
            "entry_price": entry_price,
            "h20_date": h20["trade_date"],
            "trailing_at_h20": trailing,
            "unrealized_at_h20": unrealized_at_h20,
            "gross_return_pct": round(gross_return * 100.0, 8),
            "net_return_pct": round(net_return * 100.0, 8),
            "round_trip_cost_pct": ROUND_TRIP_COST_FRACTION * 100.0,
            "price_basis": "execution_raw_x_adj",
            "conversion_ratio": frozen["conversion_ratio"],
            "diagnostics": {
                "h5": _diagnostic_snapshot(horizon=horizon, entry_horizon_index=entry_horizon_index,
                                            entry_price=entry_price, fills=fills, days=5),
                "h10": _diagnostic_snapshot(horizon=horizon, entry_horizon_index=entry_horizon_index,
                                             entry_price=entry_price, fills=fills, days=10),
                "h20": _diagnostic_snapshot(horizon=horizon, entry_horizon_index=entry_horizon_index,
                                             entry_price=entry_price, fills=fills, days=20),
            },
            "events": fills,
        }
    except ManagedExitError as exc:
        return _result_no_count(str(exc))
