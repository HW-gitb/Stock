"""Pure, manual-only corporate-action disposition planning for US-short.

The caller injects one holding shape and one already manually confirmed, source-bound
corporate-action event.  The function returns a private planning ticket with exact
share/cash entitlements; it never reads or changes account state, talks to a broker,
places an order, calculates a return, or changes selection.  Applying the ticket is
always a separate human action after broker-confirmed terms are checked.
"""
from __future__ import annotations

from datetime import datetime
from fractions import Fraction
import re
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker


_EVENT_TYPES = frozenset({"stock_conversion", "cash_consideration", "stock_and_cash_consideration", "forced_exit"})
_SOURCE_CONFIRMATION = "manually_confirmed_source_bound"
_SHA256_HEX = frozenset("0123456789abcdef")
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class CorporateActionDispositionError(ValueError):
    """A corporate-action disposition ticket would be ambiguous or exceed the manual-only boundary."""


def _strict_date(value: Any) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise CorporateActionDispositionError("effective_date must be ASCII YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise CorporateActionDispositionError("effective_date must be a real date") from exc
    return value


def _ticker(value: Any, *, field: str) -> str:
    normalized = canonical_us_ticker(value)
    if normalized is None or value != normalized:
        raise CorporateActionDispositionError(f"{field} must be a canonical US ticker")
    return normalized


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CorporateActionDispositionError(f"{field} must be a positive integer")
    return value


def _nullable_positive_int(value: Any, *, field: str) -> int | None:
    return None if value is None else _positive_int(value, field=field)


def _sha256(value: Any) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _SHA256_HEX for char in value):
        raise CorporateActionDispositionError("source_evidence_ref_sha256 must be lowercase SHA-256 hex")
    return value


def _validate_position(position: Any) -> tuple[str, int]:
    if not isinstance(position, dict) or set(position) != {"ticker", "direction", "shares"}:
        raise CorporateActionDispositionError("position must contain exactly ticker/direction/shares")
    ticker = _ticker(position["ticker"], field="position.ticker")
    if position["direction"] != "long":
        raise CorporateActionDispositionError("manual disposition supports only the US-short long-only position contract")
    return ticker, _positive_int(position["shares"], field="position.shares")


def _validate_event(event: Any, *, position_ticker: str) -> dict[str, Any]:
    required = {
        "event_id", "event_type", "old_ticker", "effective_date", "source_evidence_ref_sha256",
        "source_confirmation", "successor_ticker", "stock_ratio_numerator", "stock_ratio_denominator",
        "cash_per_old_share_cents",
    }
    if not isinstance(event, dict) or set(event) != required:
        raise CorporateActionDispositionError("corporate-action event has an unexpected shape")
    event_id = event["event_id"]
    if type(event_id) is not str or _EVENT_ID_RE.fullmatch(event_id) is None:
        raise CorporateActionDispositionError("event_id must be a short normalized identifier")
    event_type = event["event_type"]
    if event_type not in _EVENT_TYPES:
        raise CorporateActionDispositionError("event_type is unsupported")
    old_ticker = _ticker(event["old_ticker"], field="event.old_ticker")
    if old_ticker != position_ticker:
        raise CorporateActionDispositionError("event.old_ticker must match the injected position")
    if event["source_confirmation"] != _SOURCE_CONFIRMATION:
        raise CorporateActionDispositionError("event requires manually confirmed source-bound semantics")
    successor = event["successor_ticker"]
    successor = None if successor is None else _ticker(successor, field="event.successor_ticker")
    numerator = _nullable_positive_int(event["stock_ratio_numerator"], field="event.stock_ratio_numerator")
    denominator = _nullable_positive_int(event["stock_ratio_denominator"], field="event.stock_ratio_denominator")
    cash_cents = _nullable_positive_int(event["cash_per_old_share_cents"], field="event.cash_per_old_share_cents")
    has_stock = event_type in {"stock_conversion", "stock_and_cash_consideration"}
    has_cash = event_type in {"cash_consideration", "stock_and_cash_consideration"}
    stock_fields = (successor, numerator, denominator)
    if has_stock:
        if any(value is None for value in stock_fields):
            raise CorporateActionDispositionError("stock event semantics require exactly successor ticker and ratio")
    elif any(value is not None for value in stock_fields):
        raise CorporateActionDispositionError("non-stock event cannot carry successor or stock ratio")
    if has_cash != (cash_cents is not None):
        raise CorporateActionDispositionError("cash event semantics require exactly cash_per_old_share_cents")
    if event_type == "forced_exit" and any(value is not None for value in (successor, numerator, denominator, cash_cents)):
        raise CorporateActionDispositionError("forced_exit cannot claim stock or cash consideration")
    return {
        "event_id": event_id,
        "event_type": event_type,
        "old_ticker": old_ticker,
        "effective_date": _strict_date(event["effective_date"]),
        "source_evidence_ref_sha256": _sha256(event["source_evidence_ref_sha256"]),
        "source_confirmation": _SOURCE_CONFIRMATION,
        "successor_ticker": successor,
        "stock_ratio_numerator": numerator,
        "stock_ratio_denominator": denominator,
        "cash_per_old_share_cents": cash_cents,
    }


def _manual_disposition(event: dict[str, Any], *, shares: int) -> dict[str, Any]:
    event_type = event["event_type"]
    entitlement = None
    cash_entitlement = None
    if event["stock_ratio_numerator"] is not None:
        ratio = Fraction(event["stock_ratio_numerator"], event["stock_ratio_denominator"])
        exact = shares * ratio
        entitlement = {"numerator": exact.numerator, "denominator": exact.denominator}
    if event["cash_per_old_share_cents"] is not None:
        cash_entitlement = shares * event["cash_per_old_share_cents"]
    if event_type == "stock_conversion":
        action, manual_exit = "manual_convert_shares", False
    elif event_type == "cash_consideration":
        action, manual_exit = "manual_record_cash_consideration", False
    elif event_type == "stock_and_cash_consideration":
        action, manual_exit = "manual_convert_and_record_cash", False
    else:
        action, manual_exit = "manual_exit_at_broker_confirmed_terms", True
    return {
        "action": action,
        "successor_ticker": event["successor_ticker"],
        "successor_share_entitlement": entitlement,
        "cash_entitlement_cents": cash_entitlement,
        "manual_exit_required": manual_exit,
        "manual_confirmation_to_apply_required": True,
    }


def build_manual_disposition(position: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Create a manual-only corporate-action ticket from injected, already-confirmed semantics."""
    ticker, shares = _validate_position(position)
    normalized_event = _validate_event(event, position_ticker=ticker)
    ticket = {
        "schema_name": "us_short_corporate_action_manual_disposition",
        "schema_version": "1.0.0",
        "position_binding": {"ticker": ticker, "shares": shares},
        "event_binding": {
            key: normalized_event[key]
            for key in (
                "event_id", "event_type", "old_ticker", "effective_date", "source_evidence_ref_sha256",
                "source_confirmation", "successor_ticker", "stock_ratio_numerator", "stock_ratio_denominator",
                "cash_per_old_share_cents",
            )
        },
        "manual_disposition": _manual_disposition(normalized_event, shares=shares),
        "boundary": {
            "account_state_read": False,
            "account_state_mutated": False,
            "broker_order_placed": False,
            "automatic_position_conversion_performed": False,
            "automatic_cash_booking_performed": False,
            "return_calculation_performed": False,
            "selection_or_ranking_changed": False,
            "ship_gate_evidence_claimed": False,
        },
    }
    validate_manual_disposition(ticket)
    return ticket


def validate_manual_disposition(ticket: Any) -> dict[str, Any]:
    """Reject a forged manual disposition before a caller can present it as a safe instruction."""
    if not isinstance(ticket, dict) or set(ticket) != {
        "schema_name", "schema_version", "position_binding", "event_binding", "manual_disposition", "boundary"
    }:
        raise CorporateActionDispositionError("manual disposition has an unexpected top-level shape")
    if ticket["schema_name"] != "us_short_corporate_action_manual_disposition" or ticket["schema_version"] != "1.0.0":
        raise CorporateActionDispositionError("manual disposition identity is invalid")
    position = ticket["position_binding"]
    if not isinstance(position, dict) or set(position) != {"ticker", "shares"}:
        raise CorporateActionDispositionError("manual disposition position binding is invalid")
    ticker = _ticker(position["ticker"], field="position_binding.ticker")
    shares = _positive_int(position["shares"], field="position_binding.shares")
    binding = ticket["event_binding"]
    if not isinstance(binding, dict) or set(binding) != {
        "event_id", "event_type", "old_ticker", "effective_date", "source_evidence_ref_sha256",
        "source_confirmation", "successor_ticker", "stock_ratio_numerator", "stock_ratio_denominator",
        "cash_per_old_share_cents",
    }:
        raise CorporateActionDispositionError("manual disposition event binding is invalid")
    normalized_binding = _validate_event(binding, position_ticker=ticker)
    manual = ticket["manual_disposition"]
    if not isinstance(manual, dict) or set(manual) != {
        "action", "successor_ticker", "successor_share_entitlement", "cash_entitlement_cents", "manual_exit_required", "manual_confirmation_to_apply_required"
    }:
        raise CorporateActionDispositionError("manual disposition instruction shape is invalid")
    expected = _manual_disposition(normalized_binding, shares=shares)
    if manual != expected:
        raise CorporateActionDispositionError("manual disposition instruction disagrees with bound event semantics")
    expected_boundary = {
        "account_state_read": False,
        "account_state_mutated": False,
        "broker_order_placed": False,
        "automatic_position_conversion_performed": False,
        "automatic_cash_booking_performed": False,
        "return_calculation_performed": False,
        "selection_or_ranking_changed": False,
        "ship_gate_evidence_claimed": False,
    }
    if ticket["boundary"] != expected_boundary:
        raise CorporateActionDispositionError("manual disposition boundary is invalid")
    return ticket
