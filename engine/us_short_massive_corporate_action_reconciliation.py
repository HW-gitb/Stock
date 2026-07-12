# -*- coding: utf-8 -*-
"""Build fail-closed, value-free Massive corporate-action event-to-price evidence.

This is the second, offline-only preparation cut for the section 12.1 corporate-action gate in
``docs/us_short_system_design.md``.  It accepts caller-injected *normalised* event and daily-price rows, binds
each split/dividend event to the prior and effective sessions in both adjusted and unadjusted price modes, and
returns only dates/statuses plus source digests.  It intentionally does not read raw payload files, call Massive,
evaluate an event-price relationship, calculate a return, or drive the paper-evaluation gate.  A complete pair of
price windows is therefore ``pending_price_reconciliation``, never a reconciliation success.

The future raw-payload adapter and the future semantic reconciliation rule need their own explicitly authorised
slices.  This module keeps the boundary visible: it can prepare evidence without guessing an ex-date or split-ratio
tolerance, and all downstream/provider/ship-gate permissions remain fixed false.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "us_short_massive_corporate_action_reconciliation_evidence.schema.json"
)
_VALIDATOR = None
_FAMILIES = ("splits", "dividends", "daily_adjusted", "daily_unadjusted")
_EVENT_FIELDS = frozenset({"event_id", "symbol", "event_type", "event_date", "source_family"})
_PRICE_FIELDS = frozenset({"symbol", "session_date", "adjustment_mode", "source_family", "close"})
_EVENT_FAMILY = {"split": "splits", "dividend": "dividends"}
_PRICE_FAMILY = {"adjusted": "daily_adjusted", "unadjusted": "daily_unadjusted"}
_HEX = frozenset("0123456789abcdef")


class MassiveCorporateActionReconciliationError(ValueError):
    """Raised when normalised corporate-action evidence cannot be safely bound."""


def _schema_validator():
    global _VALIDATOR
    if _VALIDATOR is not None:
        return _VALIDATOR
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - environment guard
        raise MassiveCorporateActionReconciliationError(
            "jsonschema is required to validate Massive corporate-action reconciliation evidence"
        ) from exc
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MassiveCorporateActionReconciliationError(
            "Massive corporate-action reconciliation evidence schema cannot be loaded"
        ) from exc
    Draft7Validator.check_schema(schema)
    _VALIDATOR = Draft7Validator(schema)
    return _VALIDATOR


def _validate_evidence_schema(evidence: dict[str, Any]) -> None:
    errors = sorted(_schema_validator().iter_errors(evidence), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise MassiveCorporateActionReconciliationError(
            f"generated Massive corporate-action evidence violates its schema at {path}: {first.message}"
        )


def _require_exact_keys(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise MassiveCorporateActionReconciliationError(f"{label} must be an object")
    keys = frozenset(value)
    if keys != expected:
        raise MassiveCorporateActionReconciliationError(
            f"{label} must have exactly {sorted(expected)}; got {sorted(keys)}"
        )
    return value


def _date8(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isdigit():
        raise MassiveCorporateActionReconciliationError(f"{label} must be YYYYMMDD")
    try:
        dt.datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise MassiveCorporateActionReconciliationError(f"{label} must be a real calendar date") from exc
    return value


def _iso_date(value: Any, label: str) -> dt.date:
    if type(value) is not str or len(value) != 10:
        raise MassiveCorporateActionReconciliationError(f"{label} must be YYYY-MM-DD")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise MassiveCorporateActionReconciliationError(f"{label} must be a real calendar date") from exc
    if parsed.isoformat() != value:
        raise MassiveCorporateActionReconciliationError(f"{label} must be canonical YYYY-MM-DD")
    return parsed


def _symbol(value: Any, label: str) -> str:
    if type(value) is not str or not value or len(value) > 10:
        raise MassiveCorporateActionReconciliationError(f"{label} must be a non-empty ticker-like string")
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for char in value):
        raise MassiveCorporateActionReconciliationError(f"{label} must be uppercase ticker-like text")
    return value


def _event_id(value: Any) -> str:
    if type(value) is not str or not value or len(value) > 128:
        raise MassiveCorporateActionReconciliationError("event_id must be a non-empty bounded string")
    if any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for char in value):
        raise MassiveCorporateActionReconciliationError("event_id contains unsafe characters")
    return value


def _positive_finite(value: Any, label: str) -> None:
    if isinstance(value, bool):
        raise MassiveCorporateActionReconciliationError(f"{label} must be a positive finite number")
    try:
        finite = math.isfinite(float(value))
        positive = float(value) > 0
    except (TypeError, ValueError, OverflowError) as exc:
        raise MassiveCorporateActionReconciliationError(f"{label} must be a positive finite number") from exc
    if not finite or not positive:
        raise MassiveCorporateActionReconciliationError(f"{label} must be a positive finite number")


def _validated_source_refs(source_ref_sha256: Any) -> dict[str, str]:
    if type(source_ref_sha256) is not dict or frozenset(source_ref_sha256) != frozenset(_FAMILIES):
        raise MassiveCorporateActionReconciliationError(
            "source_ref_sha256 must bind exactly splits/dividends/daily_adjusted/daily_unadjusted"
        )
    out: dict[str, str] = {}
    for family in _FAMILIES:
        digest = source_ref_sha256[family]
        if type(digest) is not str or len(digest) != 64 or any(char not in _HEX for char in digest):
            raise MassiveCorporateActionReconciliationError(f"source_ref_sha256.{family} must be lowercase sha256")
        out[family] = digest
    return out


def _validated_events(symbol: str, rows: Any) -> list[tuple[dict[str, str], dt.date]]:
    if type(rows) is not list:
        raise MassiveCorporateActionReconciliationError("normalized_event_rows must be a list")
    seen_ids: set[str] = set()
    out: list[tuple[dict[str, str], dt.date]] = []
    for index, row in enumerate(rows):
        row = _require_exact_keys(row, _EVENT_FIELDS, f"normalized_event_rows[{index}]")
        event_id = _event_id(row["event_id"])
        if event_id in seen_ids:
            raise MassiveCorporateActionReconciliationError(f"duplicate event_id {event_id!r}")
        seen_ids.add(event_id)
        if _symbol(row["symbol"], f"normalized_event_rows[{index}].symbol") != symbol:
            raise MassiveCorporateActionReconciliationError("normalised event symbol must match the requested symbol")
        event_type = row["event_type"]
        if event_type not in _EVENT_FAMILY:
            raise MassiveCorporateActionReconciliationError("event_type must be split or dividend")
        source_family = row["source_family"]
        if source_family != _EVENT_FAMILY[event_type]:
            raise MassiveCorporateActionReconciliationError(
                f"{event_type} events must be bound to {_EVENT_FAMILY[event_type]}"
            )
        event_date = _iso_date(row["event_date"], f"normalized_event_rows[{index}].event_date")
        out.append(
            (
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "event_date": event_date.isoformat(),
                    "source_family": source_family,
                },
                event_date,
            )
        )
    return sorted(out, key=lambda item: (item[1], item[0]["event_type"], item[0]["event_id"]))


def _validated_prices(symbol: str, rows: Any) -> dict[str, dict[dt.date, None]]:
    if type(rows) is not list:
        raise MassiveCorporateActionReconciliationError("normalized_price_rows must be a list")
    out: dict[str, dict[dt.date, None]] = {"adjusted": {}, "unadjusted": {}}
    for index, row in enumerate(rows):
        row = _require_exact_keys(row, _PRICE_FIELDS, f"normalized_price_rows[{index}]")
        if _symbol(row["symbol"], f"normalized_price_rows[{index}].symbol") != symbol:
            raise MassiveCorporateActionReconciliationError("normalised price symbol must match the requested symbol")
        mode = row["adjustment_mode"]
        if mode not in _PRICE_FAMILY:
            raise MassiveCorporateActionReconciliationError("adjustment_mode must be adjusted or unadjusted")
        if row["source_family"] != _PRICE_FAMILY[mode]:
            raise MassiveCorporateActionReconciliationError(
                f"{mode} price rows must be bound to {_PRICE_FAMILY[mode]}"
            )
        session_date = _iso_date(row["session_date"], f"normalized_price_rows[{index}].session_date")
        _positive_finite(row["close"], f"normalized_price_rows[{index}].close")
        if session_date in out[mode]:
            raise MassiveCorporateActionReconciliationError(
                f"duplicate {mode} price row for {session_date.isoformat()}"
            )
        out[mode][session_date] = None
    return out


def _window(prices: dict[dt.date, None], event_date: dt.date) -> dict[str, str | None]:
    prior_dates = [session_date for session_date in prices if session_date < event_date]
    prior = max(prior_dates).isoformat() if prior_dates else None
    event_session = event_date.isoformat() if event_date in prices else None
    if prior and event_session:
        status = "complete"
    elif prior:
        status = "missing_event_session"
    elif event_session:
        status = "missing_prior_session"
    else:
        status = "missing_prior_and_event_session"
    return {"prior_session": prior, "event_session": event_session, "window_status": status}


def build_event_price_reconciliation_evidence(
    *,
    decision_date: str,
    symbol: str,
    normalized_event_rows: list[dict[str, Any]],
    normalized_price_rows: list[dict[str, Any]],
    source_ref_sha256: dict[str, str],
) -> dict[str, Any]:
    """Bind normalised corporate-action events to two-mode price windows without assessing their economics.

    ``normalized_*`` rows are an explicit future adapter seam: this function never opens a raw file, makes a
    provider request, or writes an artifact.  The caller must have independently normalised source payloads and
    supplied the four source digests.  The output deliberately excludes prices and event values, so it is safe for a
    future gitignored evidence artifact but cannot be mistaken for a reconciliation result.
    """
    decision_date = _date8(decision_date, "decision_date")
    symbol = _symbol(symbol, "symbol")
    refs = _validated_source_refs(source_ref_sha256)
    events = _validated_events(symbol, normalized_event_rows)
    prices = _validated_prices(symbol, normalized_price_rows)

    windows: list[dict[str, Any]] = []
    split_count = 0
    dividend_count = 0
    complete_count = 0
    for event, event_date in events:
        adjusted = _window(prices["adjusted"], event_date)
        unadjusted = _window(prices["unadjusted"], event_date)
        complete = adjusted["window_status"] == "complete" and unadjusted["window_status"] == "complete"
        if event["event_type"] == "split":
            split_count += 1
        else:
            dividend_count += 1
        if complete:
            complete_count += 1
        windows.append(
            {
                **event,
                "adjusted": adjusted,
                "unadjusted": unadjusted,
                "assessment_status": "pending_price_reconciliation" if complete else "insufficient_price_window",
            }
        )

    evidence = {
        "schema_name": "us_short_massive_corporate_action_reconciliation_evidence",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "symbol": symbol,
        "source_binding": {
            "provider_id": "massive",
            "capture_packet_schema_name": "us_short_massive_corporate_action_validation_packet",
            "endpoint_families": list(_FAMILIES),
            "source_ref_sha256": refs,
        },
        "event_price_windows": windows,
        "coverage": {
            "split_event_count": split_count,
            "dividend_event_count": dividend_count,
            "complete_two_mode_window_count": complete_count,
            "insufficient_price_window_count": len(windows) - complete_count,
        },
        "boundary": {
            "provider_call_performed_during_derivation": False,
            "corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_evaluable_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }
    _validate_evidence_schema(evidence)
    return evidence
