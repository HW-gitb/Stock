# -*- coding: utf-8 -*-
"""Pure US-short model-paper portfolio state transition.

This module settles one already-frozen weekly decision bundle against caller-
supplied regular-session OHLCV.  It never fetches data, reads a manual account,
talks to a broker, or grants ship-gate evidence.  The model-paper account is a
separate normalized-notional ledger.

Accounting is deliberately simple and auditable: entry cash pays notional and
the frozen full-round-trip cost prior; exit cash receives proceeds; realized
P&L records cost at entry plus price P&L at exit.  Consequently NAV is always
``cash + remaining shares * current mark`` and never adds realized P&L twice.
"""
from __future__ import annotations

import copy
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, FormatChecker

from engine.us_short_paper_fill import PaperFillError, simulate_fill


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
MONEY_QUANTUM = Decimal("0.000001")
INITIAL_BUCKET_CAPITAL = Decimal("100000.000000")

DECISION_SCHEMA = "us_short_model_paper_decision_bundle.schema.json"
STATE_SCHEMA = "us_short_model_paper_portfolio_state.schema.json"
SETTLEMENT_SCHEMA = "us_short_model_paper_settlement.schema.json"
NAV_SCHEMA = "us_short_model_paper_nav_snapshot.schema.json"

_VALIDATORS: dict[str, Draft7Validator] = {}

DECISION_BOUNDARY = {
    "paper_only": True,
    "provider_fetch": False,
    "automatic_broker_execution": False,
    "manual_account_read": False,
    "ship_gate_eligible": False,
}
STATE_BOUNDARY = {
    "paper_only": True,
    "manual_account_isolated": True,
    "automatic_broker_execution": False,
    "ship_gate_eligible": False,
}
NAV_BOUNDARY = {
    "paper_only": True,
    "diagnostic_when_degraded": True,
    "manual_account_isolated": True,
    "automatic_broker_execution": False,
    "ship_gate_eligible": False,
}

HOLDING_ACTIONS = {"减仓", "清仓-止损", "清仓-止盈", "清仓-事件", "持有"}
NO_TRADE_ACTIONS = {"观察", "否决/避开"}
CLEAR_ACTIONS = {"清仓-止损", "清仓-止盈", "清仓-事件"}


class ModelPaperPortfolioError(ValueError):
    """Raised when a model-paper artifact or transition fails closed."""


def _validator(schema_name: str) -> Draft7Validator:
    if schema_name not in _VALIDATORS:
        schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        _VALIDATORS[schema_name] = Draft7Validator(schema, format_checker=FormatChecker())
    return _VALIDATORS[schema_name]


def _schema_validate(value: Any, schema_name: str, label: str) -> None:
    errors = sorted(_validator(schema_name).iter_errors(value), key=lambda item: list(item.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise ModelPaperPortfolioError(f"{label} schema violation at {path}: {first.message}")


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ModelPaperPortfolioError(f"artifact is not canonical JSON: {exc}") from exc


def artifact_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _date8(value: str, label: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise ModelPaperPortfolioError(f"{label} must be a real YYYYMMDD date") from exc


def _finite_positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ModelPaperPortfolioError(f"{label} must be a finite positive number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ModelPaperPortfolioError(f"{label} must be a finite positive number")
    return float(value)


def _finite_nonnegative(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ModelPaperPortfolioError(f"{label} must be a finite nonnegative number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ModelPaperPortfolioError(f"{label} must be a finite nonnegative number")
    return float(value)


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ModelPaperPortfolioError(f"{label} is not a decimal") from exc
    if not result.is_finite():
        raise ModelPaperPortfolioError(f"{label} must be finite")
    return result


def _money(value: Any) -> str:
    try:
        result = _decimal(value, "money").quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise ModelPaperPortfolioError("money is outside the supported decimal range") from exc
    if result == 0:
        result = abs(result)
    return format(result, ".6f")


def _price_decimal(value: Any, label: str) -> Decimal:
    result = _money_decimal(_money(value), label, nonnegative=True)
    if result <= 0:
        raise ModelPaperPortfolioError(f"{label} must be positive")
    return result


def _money_decimal(value: str, label: str, *, nonnegative: bool = False) -> Decimal:
    result = _decimal(value, label)
    if _money(result) != value:
        raise ModelPaperPortfolioError(f"{label} is not a canonical six-decimal string")
    if nonnegative and result < 0:
        raise ModelPaperPortfolioError(f"{label} must be nonnegative")
    return result


def _validate_position(position: dict, state_as_of: str) -> None:
    for key in ("entry_decision_date", "entry_session_date", "mark_as_of"):
        _date8(position[key], f"position.{key}")
    if position["mark_as_of"] != state_as_of:
        raise ModelPaperPortfolioError("each open position mark_as_of must equal state.as_of")
    fill = _money_decimal(position["fill_price"], "position.fill_price", nonnegative=True)
    stop = _money_decimal(position["stop_clear_price"], "position.stop_clear_price", nonnegative=True)
    tp1 = _money_decimal(position["take_profit_reduce_price"], "position.take_profit_reduce_price", nonnegative=True)
    tp2 = _money_decimal(position["take_profit_exit_price"], "position.take_profit_exit_price", nonnegative=True)
    _money_decimal(position["mark_price"], "position.mark_price", nonnegative=True)
    if not (Decimal("0") < stop < fill < tp1 < tp2):
        raise ModelPaperPortfolioError("position levels must satisfy 0 < stop < fill < tp1 < tp2")
    frozen = position["trade_state"] == "manual_review_frozen"
    if frozen != (position["freeze_reason"] is not None):
        raise ModelPaperPortfolioError("position freeze_reason must match trade_state")


def validate_decision_bundle(bundle: dict) -> None:
    _schema_validate(bundle, DECISION_SCHEMA, "decision_bundle")
    decision_dt = _date8(bundle["decision_date"], "decision_date")
    basis_dt = _date8(bundle["price_basis_date"], "price_basis_date")
    if decision_dt <= basis_dt:
        raise ModelPaperPortfolioError("decision_date must be after price_basis_date")
    if bundle["source_binding"]["source_as_of"] != bundle["decision_date"]:
        raise ModelPaperPortfolioError("decision source_binding.source_as_of must equal decision_date")
    for key, value in bundle["cost_prior"].items():
        _finite_nonnegative(value, f"cost_prior.{key}")
    tickers = [row["ticker"] for row in bundle["orders"]]
    if tickers != sorted(tickers) or len(set(tickers)) != len(tickers):
        raise ModelPaperPortfolioError("decision orders must have unique tickers in sorted order")
    for row in bundle["orders"]:
        has_order_spread = ("round_trip_spread_fraction" in row or "spread_source" in row)
        if has_order_spread:
            if "round_trip_spread_fraction" not in row or "spread_source" not in row:
                raise ModelPaperPortfolioError("order spread prior must carry fraction and source together")
            _finite_nonnegative(row["round_trip_spread_fraction"], f"{row['ticker']}.round_trip_spread_fraction")
            if not isinstance(row["spread_source"], str) or not row["spread_source"].strip():
                raise ModelPaperPortfolioError(f"{row['ticker']}.spread_source is invalid")
        action = row["final_action"]
        if action == "加仓":
            raise ModelPaperPortfolioError("add action is not implemented; fail closed")
        price_keys = (
            "valid_entry_low",
            "valid_entry_high",
            "limit_order_price",
            "breakout_entry_price",
            "stop_clear_price",
            "take_profit_reduce_price",
            "take_profit_exit_price",
            "event_clear_reference_price",
        )
        for key in price_keys:
            if row[key] is not None:
                _finite_positive(row[key], f"{row['ticker']}.{key}")
        if action == "建仓":
            if row["recommended_action_shares"] is None:
                raise ModelPaperPortfolioError("build action requires recommended_action_shares")
            if row["order_type"] is None or row["order_expiry"] != "first_regular_session_only":
                raise ModelPaperPortfolioError("build action requires a frozen entry order and expiry")
            required = ["valid_entry_low", "valid_entry_high", "stop_clear_price", "take_profit_reduce_price", "take_profit_exit_price"]
            if any(row[key] is None for key in required):
                raise ModelPaperPortfolioError("build action is missing entry/passive price geometry")
            entry_key = "limit_order_price" if row["order_type"] == "pullback_limit" else "breakout_entry_price"
            if row[entry_key] is None:
                raise ModelPaperPortfolioError(f"build action requires {entry_key}")
        else:
            entry_only = ("order_type", "order_expiry", "valid_entry_low", "valid_entry_high", "limit_order_price", "breakout_entry_price")
            if any(row[key] is not None for key in entry_only):
                raise ModelPaperPortfolioError("non-build action cannot carry entry-order fields")
        if action in HOLDING_ACTIONS:
            if any(row[key] is None for key in ("stop_clear_price", "take_profit_reduce_price", "take_profit_exit_price")):
                raise ModelPaperPortfolioError("holding action requires stop/take-profit levels")
            stop = float(row["stop_clear_price"])
            tp1 = float(row["take_profit_reduce_price"])
            tp2 = float(row["take_profit_exit_price"])
            if not stop < tp1 < tp2:
                raise ModelPaperPortfolioError("holding action levels must satisfy stop < tp1 < tp2")
        needs_shares = action == "建仓" or action == "减仓" or action in CLEAR_ACTIONS
        if needs_shares != (row["recommended_action_shares"] is not None):
            raise ModelPaperPortfolioError(f"{action} share-count semantics are invalid")


def validate_portfolio_state(state: dict) -> None:
    _schema_validate(state, STATE_SCHEMA, "portfolio_state")
    _date8(state["as_of"], "state.as_of")
    if state["last_settled_decision_date"] is not None:
        if _date8(state["last_settled_decision_date"], "last_settled_decision_date") > _date8(state["as_of"], "state.as_of"):
            raise ModelPaperPortfolioError("last_settled_decision_date cannot exceed state.as_of")
    initial = _money_decimal(state["initial_bucket_capital"], "initial_bucket_capital", nonnegative=True)
    if initial != INITIAL_BUCKET_CAPITAL:
        raise ModelPaperPortfolioError("v1 normalized-notional initial bucket must equal 100000.000000")
    _money_decimal(state["cash"], "cash", nonnegative=True)
    _money_decimal(state["cumulative_realized_pnl"], "cumulative_realized_pnl")
    _money_decimal(state["cumulative_cost_paid"], "cumulative_cost_paid", nonnegative=True)
    tickers = [position["ticker"] for position in state["positions"]]
    if tickers != sorted(tickers) or len(tickers) != len(set(tickers)):
        raise ModelPaperPortfolioError("positions must have unique tickers in sorted order")
    for position in state["positions"]:
        _validate_position(position, state["as_of"])


def validate_nav_snapshot(nav: dict) -> None:
    _schema_validate(nav, NAV_SCHEMA, "nav_snapshot")
    _date8(nav["as_of"], "nav.as_of")
    cash = _money_decimal(nav["cash"], "nav.cash", nonnegative=True)
    market = _money_decimal(nav["market_value"], "nav.market_value", nonnegative=True)
    nav_value = _money_decimal(nav["nav"], "nav.nav", nonnegative=True)
    realized = _money_decimal(nav["cumulative_realized_pnl"], "nav.cumulative_realized_pnl")
    unrealized = _money_decimal(nav["unrealized_pnl"], "nav.unrealized_pnl")
    total = _money_decimal(nav["total_pnl"], "nav.total_pnl")
    _money_decimal(nav["cumulative_cost_paid"], "nav.cumulative_cost_paid", nonnegative=True)
    if _money(cash + market) != nav["nav"]:
        raise ModelPaperPortfolioError("NAV accounting identity failed: nav must equal cash + market_value")
    if _money(realized + unrealized) != nav["total_pnl"]:
        raise ModelPaperPortfolioError("NAV accounting identity failed: total_pnl must equal realized + unrealized")
    if nav["paper_evaluable"] != (nav["performance_status"] == "evaluable"):
        raise ModelPaperPortfolioError("paper_evaluable must match performance_status")
    if nav["paper_evaluable"] and (nav["degradation_reasons"] or nav["evaluation_source_sha256"] is None):
        raise ModelPaperPortfolioError("evaluable NAV requires a source digest and no degradation reasons")
    if not nav["paper_evaluable"] and not nav["degradation_reasons"]:
        raise ModelPaperPortfolioError("diagnostic NAV requires at least one degradation reason")


def validate_settlement(settlement: dict) -> None:
    _schema_validate(settlement, SETTLEMENT_SCHEMA, "settlement")
    decision_dt = _date8(settlement["decision_date"], "settlement.decision_date")
    maturity_dt = _date8(settlement["maturity_as_of"], "settlement.maturity_as_of")
    if maturity_dt < decision_dt:
        raise ModelPaperPortfolioError("settlement maturity cannot precede decision_date")
    tickers = [item["ticker"] for item in settlement["order_outcomes"]]
    if tickers != sorted(tickers) or len(tickers) != len(set(tickers)):
        raise ModelPaperPortfolioError("settlement outcomes must have unique sorted tickers")
    for outcome in settlement["order_outcomes"]:
        status = outcome["status"]
        transactions = outcome["transactions"]
        if status in {"not_filled", "held", "held_action_unfilled", "no_trade", "manual_review_frozen"} and transactions:
            raise ModelPaperPortfolioError(f"{status} outcome cannot carry transactions")
        if status == "opened" and (not transactions or transactions[0]["kind"] != "entry" or any(tx["kind"] == "exit" for tx in transactions)):
            raise ModelPaperPortfolioError("opened outcome requires entry without full exit")
        if status == "partially_reduced" and not any(tx["kind"] == "partial_exit" for tx in transactions):
            raise ModelPaperPortfolioError("partially_reduced outcome requires a partial_exit")
        if status == "closed" and (not transactions or transactions[-1]["kind"] != "exit"):
            raise ModelPaperPortfolioError("closed outcome requires a final exit transaction")
        for transaction in outcome["transactions"]:
            tx_dt = _date8(transaction["session_date"], "transaction.session_date")
            if not decision_dt <= tx_dt <= maturity_dt:
                raise ModelPaperPortfolioError("transaction date falls outside settlement window")
            _money_decimal(transaction["price"], "transaction.price", nonnegative=True)
            _money_decimal(transaction["cash_delta"], "transaction.cash_delta")
            _money_decimal(transaction["realized_pnl_delta"], "transaction.realized_pnl_delta")
            _money_decimal(transaction["cost_paid_delta"], "transaction.cost_paid_delta", nonnegative=True)


def seed_portfolio_state(as_of: str, initial_bucket_capital: str = "100000.000000") -> dict:
    _date8(as_of, "as_of")
    if _money_decimal(initial_bucket_capital, "initial_bucket_capital", nonnegative=True) != INITIAL_BUCKET_CAPITAL:
        raise ModelPaperPortfolioError("v1 only supports normalized-notional 100000.000000")
    state = {
        "schema_name": "us_short_model_paper_portfolio_state",
        "schema_version": "1.0.0",
        "capital_kind": "normalized_notional",
        "base_currency": "USD",
        "initial_bucket_capital": initial_bucket_capital,
        "as_of": as_of,
        "last_settled_decision_date": None,
        "cash": initial_bucket_capital,
        "cumulative_realized_pnl": "0.000000",
        "cumulative_cost_paid": "0.000000",
        "positions": [],
        "boundary": copy.deepcopy(STATE_BOUNDARY),
    }
    validate_portfolio_state(state)
    return state


def _validate_evaluation(evaluation: dict) -> None:
    expected = {"paper_evaluable", "status", "degradation_reasons", "source_sha256"}
    if not isinstance(evaluation, dict) or set(evaluation) != expected:
        raise ModelPaperPortfolioError("paper_evaluation must be closed-world")
    if not isinstance(evaluation["paper_evaluable"], bool):
        raise ModelPaperPortfolioError("paper_evaluation.paper_evaluable must be boolean")
    expected_status = "evaluable" if evaluation["paper_evaluable"] else "not_evaluable"
    if evaluation["status"] != expected_status:
        raise ModelPaperPortfolioError("paper_evaluation status contradicts paper_evaluable")
    reasons = evaluation["degradation_reasons"]
    if not isinstance(reasons, list) or any(not isinstance(item, str) or not item for item in reasons) or len(reasons) != len(set(reasons)):
        raise ModelPaperPortfolioError("paper_evaluation degradation_reasons must be unique nonempty strings")
    source = evaluation["source_sha256"]
    if evaluation["paper_evaluable"]:
        if reasons or not isinstance(source, str) or len(source) != 64 or any(ch not in "0123456789abcdef" for ch in source):
            raise ModelPaperPortfolioError("evaluable paper_evaluation requires source digest and no reasons")
    elif not reasons:
        raise ModelPaperPortfolioError("not_evaluable paper_evaluation requires degradation reasons")
    elif source is not None and (not isinstance(source, str) or len(source) != 64 or any(ch not in "0123456789abcdef" for ch in source)):
        raise ModelPaperPortfolioError("paper_evaluation source_sha256 is malformed")


def build_nav_snapshot(state: dict, paper_evaluation: dict) -> dict:
    validate_portfolio_state(state)
    _validate_evaluation(paper_evaluation)
    cash = _money_decimal(state["cash"], "cash", nonnegative=True)
    initial = _money_decimal(state["initial_bucket_capital"], "initial", nonnegative=True)
    realized = _money_decimal(state["cumulative_realized_pnl"], "realized")
    market = Decimal("0")
    unrealized = Decimal("0")
    for position in state["positions"]:
        shares = Decimal(position["shares"])
        mark = _money_decimal(position["mark_price"], "mark", nonnegative=True)
        fill = _money_decimal(position["fill_price"], "fill", nonnegative=True)
        market += shares * mark
        unrealized += shares * (mark - fill)
    nav_value = cash + market
    total = nav_value - initial
    if _money(realized + unrealized) != _money(total):
        raise ModelPaperPortfolioError("state accounting identity failed before NAV emission")
    evaluable = paper_evaluation["paper_evaluable"]
    nav = {
        "schema_name": "us_short_model_paper_nav_snapshot",
        "schema_version": "1.0.0",
        "as_of": state["as_of"],
        "state_sha256": artifact_sha256(state),
        "cash": _money(cash),
        "market_value": _money(market),
        "nav": _money(nav_value),
        "cumulative_realized_pnl": _money(realized),
        "unrealized_pnl": _money(unrealized),
        "total_pnl": _money(total),
        "cumulative_cost_paid": state["cumulative_cost_paid"],
        "performance_status": "evaluable" if evaluable else "diagnostic_data_degraded",
        "paper_evaluable": evaluable,
        "degradation_reasons": sorted(paper_evaluation["degradation_reasons"]),
        "evaluation_source_sha256": paper_evaluation["source_sha256"],
        "boundary": copy.deepcopy(NAV_BOUNDARY),
    }
    validate_nav_snapshot(nav)
    return nav


def _validate_price_packet(packet: dict, decision_date: str, maturity_as_of: str, required_tickers: set[str]) -> dict[str, list[dict]]:
    expected = {"as_of", "session_scope", "adjustment_mode", "observed_at", "source_sha256", "paper_evaluation", "bars_by_ticker"}
    if not isinstance(packet, dict) or set(packet) != expected:
        raise ModelPaperPortfolioError("price_packet must be closed-world")
    _date8(packet["as_of"], "price_packet.as_of")
    if packet["as_of"] != maturity_as_of:
        raise ModelPaperPortfolioError("price_packet.as_of must equal maturity_as_of")
    if packet["session_scope"] != "RTH":
        raise ModelPaperPortfolioError("only regular-session RTH price packets are supported")
    if not isinstance(packet["adjustment_mode"], str) or not packet["adjustment_mode"]:
        raise ModelPaperPortfolioError("price_packet.adjustment_mode is required")
    try:
        datetime.fromisoformat(packet["observed_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ModelPaperPortfolioError("price_packet.observed_at must be ISO-8601") from exc
    source = packet["source_sha256"]
    if not isinstance(source, str) or len(source) != 64 or any(ch not in "0123456789abcdef" for ch in source):
        raise ModelPaperPortfolioError("price_packet.source_sha256 is malformed")
    _validate_evaluation(packet["paper_evaluation"])
    bars_by_ticker = packet["bars_by_ticker"]
    if not isinstance(bars_by_ticker, dict) or set(bars_by_ticker) != required_tickers:
        raise ModelPaperPortfolioError("price_packet tickers must exactly match holdings plus build orders")
    decision_dt = _date8(decision_date, "decision_date")
    maturity_dt = _date8(maturity_as_of, "maturity_as_of")
    for ticker in sorted(required_tickers):
        bars = bars_by_ticker[ticker]
        if not isinstance(bars, list) or not bars:
            raise ModelPaperPortfolioError(f"{ticker} requires at least one RTH bar")
        dates: list[str] = []
        for bar in bars:
            if not isinstance(bar, dict) or set(bar) != {"date", "open", "high", "low", "close"}:
                raise ModelPaperPortfolioError(f"{ticker} bar must be closed-world OHLC")
            bar_dt = _date8(bar["date"], f"{ticker}.bar.date")
            if bar_dt < decision_dt:
                raise ModelPaperPortfolioError("bar date precedes decision_date")
            if bar_dt > maturity_dt:
                raise ModelPaperPortfolioError("bar date exceeds maturity_as_of")
            values = {key: _finite_positive(bar[key], f"{ticker}.{bar['date']}.{key}") for key in ("open", "high", "low", "close")}
            if not (values["low"] <= values["open"] <= values["high"] and values["low"] <= values["close"] <= values["high"]):
                raise ModelPaperPortfolioError(f"{ticker} bar has inconsistent OHLC geometry")
            dates.append(bar["date"])
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ModelPaperPortfolioError(f"{ticker} bars must have unique increasing dates")
        if dates[0] != decision_date:
            raise ModelPaperPortfolioError(f"{ticker} first bar must equal decision_date")
    return bars_by_ticker


def _transaction(kind: str, date: str, shares: int, price: Decimal, cash_delta: Decimal, realized_delta: Decimal, cost_delta: Decimal, reason: str) -> dict:
    return {
        "kind": kind,
        "session_date": date,
        "shares": shares,
        "price": _money(price),
        "cash_delta": _money(cash_delta),
        "realized_pnl_delta": _money(realized_delta),
        "cost_paid_delta": _money(cost_delta),
        "reason": reason,
    }


def _stop_fill(bar: dict, stop: Decimal) -> tuple[Decimal, str] | None:
    open_price = _price_decimal(bar["open"], "bar.open")
    low = _decimal(bar["low"], "bar.low")
    if open_price <= stop:
        return open_price, "gap_stop"
    if low <= stop:
        return stop, "intraday_stop"
    return None


def _target_fill(bar: dict, target: Decimal) -> Decimal | None:
    open_price = _decimal(bar["open"], "bar.open")
    high = _decimal(bar["high"], "bar.high")
    if open_price >= target or high >= target:
        return target
    return None


def settle_decision_bundle(prior_state: dict, decision_bundle: dict, price_packet: dict, maturity_as_of: str) -> tuple[dict, dict, dict]:
    """Settle one frozen decision and return ``(settlement, state, nav)``.

    All returned values are schema-valid, deterministic dictionaries.  No file
    is read or written by this pure transition.
    """
    validate_portfolio_state(prior_state)
    validate_decision_bundle(decision_bundle)
    _date8(maturity_as_of, "maturity_as_of")
    if artifact_sha256(prior_state) != decision_bundle["prior_state_sha256"]:
        raise ModelPaperPortfolioError("decision prior_state_sha256 does not bind the supplied state")
    if prior_state["as_of"] != decision_bundle["price_basis_date"]:
        raise ModelPaperPortfolioError("decision price_basis_date must equal prior state as_of")
    if _date8(maturity_as_of, "maturity_as_of") < _date8(decision_bundle["decision_date"], "decision_date"):
        raise ModelPaperPortfolioError("maturity_as_of cannot precede decision_date")

    positions = {item["ticker"]: copy.deepcopy(item) for item in prior_state["positions"]}
    orders = {item["ticker"]: item for item in decision_bundle["orders"]}
    missing_holdings = sorted(set(positions) - set(orders))
    if missing_holdings:
        raise ModelPaperPortfolioError(f"missing decision row for holding(s): {missing_holdings}")
    for ticker in positions:
        if orders[ticker]["final_action"] not in HOLDING_ACTIONS | NO_TRADE_ACTIONS:
            raise ModelPaperPortfolioError(f"existing holding {ticker} has non-holding action")
    for ticker, row in orders.items():
        if ticker not in positions and row["final_action"] in HOLDING_ACTIONS:
            raise ModelPaperPortfolioError(f"holding action for absent position {ticker}")
        if ticker in positions and row["final_action"] == "建仓":
            raise ModelPaperPortfolioError(f"build action collides with existing position {ticker}")

    build_tickers = {ticker for ticker, row in orders.items() if row["final_action"] == "建仓"}
    required_tickers = set(positions) | build_tickers
    bars_by_ticker = _validate_price_packet(price_packet, decision_bundle["decision_date"], maturity_as_of, required_tickers)

    cash = _money_decimal(prior_state["cash"], "cash", nonnegative=True)
    realized = _money_decimal(prior_state["cumulative_realized_pnl"], "realized")
    cumulative_cost = _money_decimal(prior_state["cumulative_cost_paid"], "cost", nonnegative=True)
    decision_digest = artifact_sha256(decision_bundle)
    outcomes: list[dict] = []

    def apply_exit(position: dict, shares: int, price: Decimal, date: str, reason: str, kind: str) -> dict:
        nonlocal cash, realized
        fill = _money_decimal(position["fill_price"], "fill", nonnegative=True)
        proceeds = Decimal(shares) * price
        pnl_delta = Decimal(shares) * (price - fill)
        cash += proceeds
        realized += pnl_delta
        return _transaction(kind, date, shares, price, proceeds, pnl_delta, Decimal("0"), reason)

    for ticker in sorted(orders):
        row = orders[ticker]
        action = row["final_action"]
        txs: list[dict] = []
        if action in NO_TRADE_ACTIONS and ticker not in positions:
            outcomes.append({"ticker": ticker, "final_action": action, "status": "no_trade", "transactions": txs})
            continue

        if action == "建仓":
            bars = bars_by_ticker[ticker]
            try:
                fill_result = simulate_fill(row, bars[0])
            except PaperFillError as exc:
                raise ModelPaperPortfolioError(f"{ticker} entry fill rejected: {exc}") from exc
            if fill_result["status"] == "not_filled":
                outcomes.append({"ticker": ticker, "final_action": action, "status": "not_filled", "transactions": txs})
                continue
            shares = row["recommended_action_shares"]
            fill = _price_decimal(fill_result["fill_price"], "fill_price")
            notional = Decimal(shares) * fill
            costs = decision_bundle["cost_prior"]
            spread_fraction = (_decimal(row["round_trip_spread_fraction"], "round_trip_spread_fraction")
                               if "round_trip_spread_fraction" in row
                               else _decimal(costs["spread_cost"], "spread_cost"))
            cost_fraction = (_decimal(costs["commission_fee"], "commission_fee") + spread_fraction
                             + _decimal(costs["slippage_bps"], "slippage_bps") / Decimal("10000"))
            cost_paid = (notional * cost_fraction).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
            cash_out = notional + cost_paid
            if cash < cash_out:
                raise ModelPaperPortfolioError(f"insufficient model-paper cash for {ticker} build")
            cash -= cash_out
            realized -= cost_paid
            cumulative_cost += cost_paid
            txs.append(_transaction("entry", bars[0]["date"], shares, fill, -cash_out, -cost_paid, cost_paid, "entry_fill"))
            position = {
                "ticker": ticker,
                "entry_decision_date": decision_bundle["decision_date"],
                "entry_session_date": bars[0]["date"],
                "shares": shares,
                "fill_price": _money(fill),
                "stop_clear_price": _money(row["stop_clear_price"]),
                "take_profit_reduce_price": _money(row["take_profit_reduce_price"]),
                "take_profit_exit_price": _money(row["take_profit_exit_price"]),
                "tp1_completed": False,
                "trade_state": "active",
                "freeze_reason": None,
                "mark_price": _money(bars[0]["close"]),
                "mark_as_of": bars[0]["date"],
                "source_decision_sha256": decision_digest,
                "last_action_decision_sha256": decision_digest,
            }
            if fill_result["status"] in {"filled_stopped", "filled_tp_exit"}:
                exit_price = _price_decimal(fill_result["exit_price"], "same_day_exit")
                reason = "same_day_stop" if fill_result["status"] == "filled_stopped" else "same_day_take_profit"
                txs.append(apply_exit(position, shares, exit_price, bars[0]["date"], reason, "exit"))
                status = "closed"
            else:
                status = "opened"
                stop = _money_decimal(position["stop_clear_price"], "stop", nonnegative=True)
                tp2 = _money_decimal(position["take_profit_exit_price"], "tp2", nonnegative=True)
                for bar in bars[1:]:
                    stopped = _stop_fill(bar, stop)
                    if stopped is not None:
                        exit_price, reason = stopped
                        txs.append(apply_exit(position, shares, exit_price, bar["date"], reason, "exit"))
                        status = "closed"
                        break
                    target = _target_fill(bar, tp2)
                    if target is not None:
                        txs.append(apply_exit(position, shares, target, bar["date"], "take_profit_exit", "exit"))
                        status = "closed"
                        break
                if status != "closed":
                    positions[ticker] = position
            outcomes.append({"ticker": ticker, "final_action": action, "status": status, "transactions": txs})
            continue

        position = positions[ticker]
        shares_before = position["shares"]
        if action == "减仓" and not (0 < row["recommended_action_shares"] < shares_before):
            raise ModelPaperPortfolioError("reduce shares must be positive and less than remaining shares")
        if action in CLEAR_ACTIONS and row["recommended_action_shares"] != shares_before:
            raise ModelPaperPortfolioError("clear action shares must exactly equal remaining shares")
        if action in HOLDING_ACTIONS:
            position["stop_clear_price"] = _money(row["stop_clear_price"])
            position["take_profit_reduce_price"] = _money(row["take_profit_reduce_price"])
            position["take_profit_exit_price"] = _money(row["take_profit_exit_price"])
        position["last_action_decision_sha256"] = decision_digest
        fill = _money_decimal(position["fill_price"], "fill", nonnegative=True)
        stop = _money_decimal(position["stop_clear_price"], "stop", nonnegative=True)
        tp1 = _money_decimal(position["take_profit_reduce_price"], "tp1", nonnegative=True)
        tp2 = _money_decimal(position["take_profit_exit_price"], "tp2", nonnegative=True)
        if not (stop < fill < tp1 < tp2):
            raise ModelPaperPortfolioError("holding action cannot invert stop/entry/take-profit geometry")
        bars = bars_by_ticker[ticker]

        if action == "清仓-事件" and row["event_source_ref_sha256"] is not None:
            event_price = _price_decimal(bars[0]["open"], "event open")
            txs.append(apply_exit(position, position["shares"], event_price, bars[0]["date"], "event_clear_next_open", "exit"))
            del positions[ticker]
            outcomes.append({"ticker": ticker, "final_action": action, "status": "closed", "transactions": txs})
            continue

        event_frozen = action == "清仓-事件" and row["event_source_ref_sha256"] is None
        if event_frozen:
            position["trade_state"] = "manual_review_frozen"
            position["freeze_reason"] = "event_source_unbound"

        status = "manual_review_frozen" if event_frozen else ("held_action_unfilled" if action in {"减仓", "清仓-止损", "清仓-止盈"} else "held")
        manage_action = "持有" if event_frozen or action in NO_TRADE_ACTIONS else action
        for bar in bars:
            stopped = _stop_fill(bar, stop)
            if stopped is not None:
                exit_price, reason = stopped
                txs.append(apply_exit(position, position["shares"], exit_price, bar["date"], reason, "exit"))
                del positions[ticker]
                status = "closed"
                break
            if manage_action != "清仓-止损":
                target = _target_fill(bar, tp2)
                if target is not None:
                    txs.append(apply_exit(position, position["shares"], target, bar["date"], "take_profit_exit", "exit"))
                    del positions[ticker]
                    status = "closed"
                    break
            if manage_action == "减仓" and not position["tp1_completed"]:
                target = _target_fill(bar, tp1)
                if target is not None:
                    reduce_shares = row["recommended_action_shares"]
                    txs.append(apply_exit(position, reduce_shares, target, bar["date"], "take_profit_reduce", "partial_exit"))
                    position["shares"] -= reduce_shares
                    position["tp1_completed"] = True
                    status = "partially_reduced"
        outcomes.append({"ticker": ticker, "final_action": action, "status": status, "transactions": txs})

    for ticker, position in positions.items():
        bars = bars_by_ticker[ticker]
        if bars[-1]["date"] != maturity_as_of:
            raise ModelPaperPortfolioError(f"remaining position {ticker} lacks an exact maturity mark")
        position["mark_price"] = _money(bars[-1]["close"])
        position["mark_as_of"] = maturity_as_of

    state = {
        "schema_name": "us_short_model_paper_portfolio_state",
        "schema_version": "1.0.0",
        "capital_kind": "normalized_notional",
        "base_currency": "USD",
        "initial_bucket_capital": prior_state["initial_bucket_capital"],
        "as_of": maturity_as_of,
        "last_settled_decision_date": decision_bundle["decision_date"],
        "cash": _money(cash),
        "cumulative_realized_pnl": _money(realized),
        "cumulative_cost_paid": _money(cumulative_cost),
        "positions": [positions[ticker] for ticker in sorted(positions)],
        "boundary": copy.deepcopy(STATE_BOUNDARY),
    }
    validate_portfolio_state(state)
    nav = build_nav_snapshot(state, price_packet["paper_evaluation"])
    settlement = {
        "schema_name": "us_short_model_paper_settlement",
        "schema_version": "1.0.0",
        "decision_date": decision_bundle["decision_date"],
        "maturity_as_of": maturity_as_of,
        "prior_state_sha256": decision_bundle["prior_state_sha256"],
        "decision_bundle_sha256": decision_digest,
        "price_packet_sha256": artifact_sha256(price_packet),
        "order_outcomes": outcomes,
        "post_state_sha256": artifact_sha256(state),
        "nav_snapshot_sha256": artifact_sha256(nav),
        "boundary": copy.deepcopy(DECISION_BOUNDARY),
    }
    validate_settlement(settlement)
    return settlement, state, nav


__all__ = [
    "ModelPaperPortfolioError",
    "artifact_sha256",
    "build_nav_snapshot",
    "canonical_json_bytes",
    "seed_portfolio_state",
    "settle_decision_bundle",
    "validate_decision_bundle",
    "validate_nav_snapshot",
    "validate_portfolio_state",
    "validate_settlement",
]
