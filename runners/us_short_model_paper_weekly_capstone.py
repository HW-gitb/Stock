#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline model-paper stage for the US-short weekly capstone.

The normal weekly capstone owns provider access.  This module is deliberately
the later local-only stage: it consumes an already-arrived OHLCV packet and an
independent paper-plan factory, then delegates the ordered state transition to
``engine.us_short_model_paper_weekly``.  It has no network client, no manual
account path, and no official action-table input.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from engine.us_short_model_paper_portfolio import artifact_sha256
from engine.us_short_model_paper_store import ModelPaperStoreError, load_current_nav, load_current_state, load_pending_decision
from engine.us_short_model_paper_weekly import (
    ModelPaperWeeklyError,
    planned_holding_target_union,
    prepare_paper_account_adapter,
    run_paper_weekly_transition,
)
from runners.us_short_account_state_from_manual_tables import validate_account_state


class ModelPaperWeeklyCapstoneError(RuntimeError):
    """The local model-paper capstone stage rejected its source or transition."""


def _date8(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ModelPaperWeeklyCapstoneError(f"{label} must be YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ModelPaperWeeklyCapstoneError(f"{label} must be a real YYYYMMDD date") from exc
    return value


def _iso_to_date8(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 10:
        raise ModelPaperWeeklyCapstoneError(f"{label} must be YYYY-MM-DD")
    return _date8(value.replace("-", ""), label)


def _finite_positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelPaperWeeklyCapstoneError(f"{label} must be finite and positive")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")) or result <= 0:
        raise ModelPaperWeeklyCapstoneError(f"{label} must be finite and positive")
    return result


def price_packet_from_arrived_ohlcv(
    *,
    ohlcv_packet: dict,
    pending_decision: dict | None,
    decision_date: str,
    price_basis_date: str,
) -> dict:
    """Convert only the pending decision's arrived RTH bars to the portfolio engine packet.

    It never broadens missing holding coverage with candidate bars: the output ticker set is exactly the
    pending bundle's order set.  Corporate-action semantics deliberately stay not-evaluable until a later
    reviewed evidence path supplies all three confirmations.
    """
    decision_date = _date8(decision_date, "decision_date")
    price_basis_date = _date8(price_basis_date, "price_basis_date")
    if not isinstance(ohlcv_packet, dict):
        raise ModelPaperWeeklyCapstoneError("OHLCV packet must be an object")
    contract = ohlcv_packet.get("series_contract")
    provenance = ohlcv_packet.get("provenance")
    by_ticker = ohlcv_packet.get("series_by_ticker")
    clock = ohlcv_packet.get("decision_clock")
    if not isinstance(contract, dict) or not isinstance(provenance, dict) or not isinstance(by_ticker, dict) \
            or not isinstance(clock, dict):
        raise ModelPaperWeeklyCapstoneError("OHLCV packet is missing its contract/provenance/series")
    if clock.get("expected_decision_date") != decision_date:
        raise ModelPaperWeeklyCapstoneError("OHLCV packet decision clock does not equal this capstone decision date")
    if _iso_to_date8(contract.get("as_of"), "OHLCV series_contract.as_of") != price_basis_date:
        raise ModelPaperWeeklyCapstoneError("OHLCV packet price basis does not equal this capstone price basis")
    if contract.get("session") != "RTH":
        raise ModelPaperWeeklyCapstoneError("model-paper maturity requires an RTH OHLCV packet")
    observed_at = provenance.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at:
        raise ModelPaperWeeklyCapstoneError("OHLCV provenance observed_at is required")

    required = [] if pending_decision is None else [row["ticker"] for row in pending_decision["orders"]]
    bars_by_ticker: dict[str, list[dict]] = {}
    entry_date = None if pending_decision is None else pending_decision["decision_date"]
    for ticker in required:
        series = by_ticker.get(ticker)
        if not isinstance(series, dict) or not isinstance(series.get("points"), list):
            raise ModelPaperWeeklyCapstoneError(f"paper holding {ticker} lacks source-bound OHLCV coverage")
        if _iso_to_date8(series.get("as_of"), f"{ticker}.as_of") != price_basis_date \
                or series.get("session") != contract["session"] \
                or series.get("adjustment_mode") != contract.get("adjustment_mode"):
            raise ModelPaperWeeklyCapstoneError(f"paper holding {ticker} OHLCV clock/contract mismatch")
        bars = []
        prior = None
        for point in series["points"]:
            if not isinstance(point, dict):
                raise ModelPaperWeeklyCapstoneError(f"paper holding {ticker} has a malformed OHLCV point")
            date = _iso_to_date8(point.get("date"), f"{ticker}.date")
            if prior is not None and date <= prior:
                raise ModelPaperWeeklyCapstoneError(f"paper holding {ticker} OHLCV dates are unordered")
            prior = date
            if date < entry_date or date > price_basis_date:
                continue
            values = {name: _finite_positive(point.get(name), f"{ticker}.{name}")
                      for name in ("open", "high", "low", "close")}
            if not (values["low"] <= values["open"] <= values["high"]
                    and values["low"] <= values["close"] <= values["high"]):
                raise ModelPaperWeeklyCapstoneError(f"paper holding {ticker} OHLCV geometry is invalid")
            bars.append({"date": date, **values})
        bars_by_ticker[ticker] = bars
    return {
        "as_of": price_basis_date,
        "session_scope": "RTH",
        "adjustment_mode": contract.get("adjustment_mode"),
        "observed_at": observed_at,
        "source_sha256": artifact_sha256(ohlcv_packet),
        "paper_evaluation": {
            "paper_evaluable": False,
            "status": "not_evaluable",
            "degradation_reasons": ["corporate_action_unconfirmed"],
            "source_sha256": None,
        },
        "bars_by_ticker": bars_by_ticker,
    }


def forecast_holding_target_union(*, store_root: str, manual_holding_tickers: list[str] | tuple[str, ...]) -> dict:
    """Produce the preflight-only manual∪paper target forecast; it performs no provider call."""
    try:
        state = load_current_state(store_root)
    except ModelPaperStoreError as exc:
        raise ModelPaperWeeklyCapstoneError(f"cannot load paper state for target forecast: {exc}") from exc
    try:
        targets = planned_holding_target_union(
            manual_holding_tickers=manual_holding_tickers, paper_state=state)
    except ModelPaperWeeklyError as exc:
        raise ModelPaperWeeklyCapstoneError(str(exc)) from exc
    return {
        "manual_paper_holding_target_union": targets,
        "target_count": len(targets),
        "provider_calls_performed": False,
        "forecast_only": True,
    }


def account_state_from_paper_adapter(adapter: dict) -> dict:
    """Project a validated paper adapter onto the existing capstone account seam.

    This is intentionally a one-way projection: no manual account fields are
    accepted, and the normalized $100k paper bucket remains isolated from any
    real account.
    """
    if not isinstance(adapter, dict):
        raise ModelPaperWeeklyCapstoneError("paper adapter must be an object")
    try:
        cash = float(Decimal(str(adapter["us_short_available_cash"])))
        positions = [
            {
                "ticker": row["ticker"], "direction": "long", "shares": row["shares"],
                "avg_cost_usd": row["avg_cost_usd"], "entry_date": row["entry_date"],
                "current_stop": row["current_stop"],
            }
            for row in adapter["positions"]
        ]
        account = {
            "schema_name": "us_short_account_state",
            "schema_version": "1.0.0",
            "as_of": adapter["decision_date"],
            "us_market_equity": adapter["us_market_equity"],
            "us_short_bucket_capital": adapter["us_short_bucket_capital"],
            "us_short_available_cash": cash,
            "positions": positions,
            "holding_action_reconciliation": {
                "schema_name": "us_short_holding_action_reconciliation", "schema_version": "1.0.0",
                "as_of": adapter["decision_date"],
                "positions": [
                    {
                        "ticker": row["ticker"], "entry_date": row["entry_date"],
                        "remaining_shares": row["shares"], "tp1_completed": row["tp1_completed"],
                        "tp1_completed_at": None,
                        "source_reconciliation_ref": f"model_paper_adapter:{adapter['source_state_sha256']}",
                    }
                    for row in adapter["positions"]
                ],
            },
            "symbol_cooldown_reconciliation": {
                "schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
                "as_of": adapter["decision_date"], "events": [],
            },
            "manual_order_only": True,
            "broker_connection_allowed": False,
        }
        validate_account_state(account, account["as_of"])
    except Exception as exc:  # noqa: BLE001 - preserve one local paper boundary
        raise ModelPaperWeeklyCapstoneError("paper adapter cannot form a valid capstone account") from exc
    return account


def prepare_offline_model_paper_adapter(
    *,
    store_root: str,
    decision_date: str,
    price_basis_date: str,
    arrived_ohlcv_packet: dict,
) -> dict:
    """Preview mature-old-week state and derive the current paper account, without store writes."""
    try:
        pending = load_pending_decision(store_root)
    except ModelPaperStoreError as exc:
        if "not initialized" not in str(exc):
            raise ModelPaperWeeklyCapstoneError(f"cannot load paper pending decision: {exc}") from exc
        pending = None
    price_packet = price_packet_from_arrived_ohlcv(
        ohlcv_packet=arrived_ohlcv_packet, pending_decision=pending,
        decision_date=decision_date, price_basis_date=price_basis_date,
    )
    try:
        preview = prepare_paper_account_adapter(
            store_root=store_root, decision_date=decision_date,
            price_basis_date=price_basis_date, price_packet=price_packet,
        )
    except ModelPaperWeeklyError as exc:
        raise ModelPaperWeeklyCapstoneError(str(exc)) from exc
    account = account_state_from_paper_adapter(preview["adapter"])
    return {
        **preview,
        "account_state": account,
        "frozen_holding_tickers": [row["ticker"] for row in account["positions"]],
        "execution_mode": "offline_local_adapter_preview",
        "provider_calls_performed": False,
    }


def _machine_order(row: dict) -> dict:
    if not isinstance(row, dict) or not isinstance(row.get("ticker"), str) or not isinstance(row.get("final_action"), str):
        raise ModelPaperWeeklyCapstoneError("machine record row lacks ticker/final_action")
    price = row.get("price")
    fields = price.get("action_fields") if isinstance(price, dict) else {}
    if not isinstance(fields, dict):
        raise ModelPaperWeeklyCapstoneError(f"{row['ticker']}: machine price action_fields is invalid")
    action = row["final_action"]
    proposal = row.get("action_proposal")
    sizing = row.get("sizing")
    shares = proposal.get("recommended_action_shares") if isinstance(proposal, dict) else None
    if action == "建仓" and shares is None and isinstance(sizing, dict):
        shares = sizing.get("desired_model_shares")
    entry_keys = ("order_type", "order_expiry", "valid_entry_low", "valid_entry_high", "limit_order_price", "breakout_entry_price")
    entry = {key: fields.get(key) if action == "建仓" else None for key in entry_keys}
    event_ref = None
    if action == "清仓-事件":
        event = row.get("forward_event")
        evidence = event.get("evidence_ref") if isinstance(event, dict) else None
        if not isinstance(evidence, dict):
            raise ModelPaperWeeklyCapstoneError(f"{row['ticker']}: event clear lacks source-bound evidence")
        event_ref = artifact_sha256(evidence)
    return {
        "ticker": row["ticker"], "final_action": action, "recommended_action_shares": shares,
        **entry,
        "stop_clear_price": fields.get("stop_clear_price"),
        "take_profit_reduce_price": fields.get("take_profit_reduce_price"),
        "take_profit_exit_price": fields.get("take_profit_exit_price"),
        "event_clear_reference_price": fields.get("event_clear_reference_price"),
        "event_source_ref_sha256": event_ref,
    }


def paper_plan_factory_from_machine_record(machine_record_path: Path | str):
    """Bind a paper plan to the exact generated machine record, never a manual action table."""
    path = Path(machine_record_path)
    try:
        raw = path.read_bytes()
        record = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ModelPaperWeeklyCapstoneError("machine record is unreadable") from exc
    if not isinstance(record, dict) or not isinstance(record.get("as_of"), str) or not isinstance(record.get("rows"), list):
        raise ModelPaperWeeklyCapstoneError("machine record must contain as_of and rows")
    orders = [_machine_order(row) for row in record["rows"]]
    if len({row["ticker"] for row in orders}) != len(orders):
        raise ModelPaperWeeklyCapstoneError("machine record has duplicate paper-order tickers")
    orders.sort(key=lambda row: row["ticker"])
    source_sha256 = hashlib.sha256(raw).hexdigest()

    def factory(adapter: dict) -> dict:
        held = {row["ticker"] for row in adapter.get("positions", []) if isinstance(row, dict)}
        ordered = {row["ticker"] for row in orders}
        if not held <= ordered:
            raise ModelPaperWeeklyCapstoneError("machine record omits a matured paper holding")
        return {
            "source_receipt_sha256": source_sha256,
            "source_as_of": record["as_of"],
            "paper_account_adapter_sha256": artifact_sha256(adapter),
            "cost_prior": {"commission_fee": 0.001, "slippage_bps": 0.0, "spread_cost": 0.0},
            "orders": copy.deepcopy(orders),
        }
    return factory


def fixed_weekly_portfolio_metrics(*, store_root: str) -> dict:
    """Return the seven fixed paper-account report fields from the head-bound state."""
    try:
        state = load_current_state(store_root)
        nav = load_current_nav(store_root)
    except ModelPaperStoreError as exc:
        raise ModelPaperWeeklyCapstoneError(f"cannot load committed paper metrics: {exc}") from exc
    try:
        weeks = sum(1 for child in (Path(store_root) / "weeks").iterdir() if (child / "decision_bundle.json").is_file())
    except OSError as exc:
        raise ModelPaperWeeklyCapstoneError("cannot count paper weeks") from exc
    initial = Decimal(state["initial_bucket_capital"])
    current_nav = Decimal(nav["nav"])
    pnl = current_nav - initial
    return {
        "initial_capital": str(initial),
        "current_cash": nav["cash"],
        "holdings_market_value": nav["market_value"],
        "current_nav": nav["nav"],
        "cumulative_pnl": f"{pnl:.6f}",
        "cumulative_return_pct": f"{(pnl / initial * Decimal('100')):.6f}",
        "consecutive_weeks": weeks,
        "paper_evaluable": nav["paper_evaluable"],
        "performance_status": nav["performance_status"],
    }


def append_fixed_weekly_portfolio_section(report_path: Path | str, metrics: dict) -> None:
    """Append/replace the fixed seven-field diagnostic paper section in a private weekly report."""
    path = Path(report_path)
    try:
        report = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModelPaperWeeklyCapstoneError("weekly report is unreadable for paper metrics") from exc
    marker = "\n## model_paper_portfolio\n"
    report = report.split(marker, 1)[0].rstrip()
    lines = [marker.rstrip()]
    for key in ("initial_capital", "current_cash", "holdings_market_value", "current_nav", "cumulative_pnl", "cumulative_return_pct", "consecutive_weeks"):
        lines.append(f"- {key}: {metrics[key]}")
    lines.append(f"- paper_evaluable: {metrics['paper_evaluable']} ({metrics['performance_status']})")
    temporary = path.with_name(f".{path.name}.model-paper.tmp")
    temporary.write_text(report + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_offline_model_paper_capstone(
    *,
    run_account_mode: str,
    store_root: str,
    decision_date: str,
    price_basis_date: str,
    created_at: str,
    arrived_ohlcv_packet: dict,
    paper_plan_factory,
) -> dict:
    """Run the paper-only/dual local stage after a capstone has already obtained its source artifacts.

    In ``dual`` mode the caller runs the existing manual branch separately; this function still receives neither
    its account state nor its action table, making the paper branch physically independent.  All source and
    order data is caller-supplied local fixture/artifact data; no provider code is imported or called here.
    """
    try:
        pending = load_pending_decision(store_root)
    except ModelPaperStoreError as exc:
        if "not initialized" not in str(exc):
            raise ModelPaperWeeklyCapstoneError(f"cannot load paper pending decision: {exc}") from exc
        pending = None
    price_packet = price_packet_from_arrived_ohlcv(
        ohlcv_packet=arrived_ohlcv_packet, pending_decision=pending, decision_date=decision_date,
        price_basis_date=price_basis_date)
    try:
        summary = run_paper_weekly_transition(
            run_account_mode=run_account_mode,
            store_root=store_root,
            decision_date=decision_date,
            price_basis_date=price_basis_date,
            created_at=created_at,
            price_packet=price_packet,
            plan_factory=paper_plan_factory,
        )
    except ModelPaperWeeklyError as exc:
        raise ModelPaperWeeklyCapstoneError(str(exc)) from exc
    return {**summary, "execution_mode": "offline_local_capstone", "provider_calls_performed": False}


__all__ = [
    "ModelPaperWeeklyCapstoneError",
    "account_state_from_paper_adapter",
    "append_fixed_weekly_portfolio_section",
    "fixed_weekly_portfolio_metrics",
    "forecast_holding_target_union",
    "paper_plan_factory_from_machine_record",
    "price_packet_from_arrived_ohlcv",
    "prepare_offline_model_paper_adapter",
    "run_offline_model_paper_capstone",
]
