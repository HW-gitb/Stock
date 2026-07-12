# -*- coding: utf-8 -*-
"""Build fail-closed, value-free Massive corporate-action event-to-price evidence.

This module contains the second and third, offline-only preparation cuts for the section 12.1 corporate-action gate in
``docs/us_short_system_design.md``.  It accepts caller-injected *normalised* event and daily-price rows, binds
each split/dividend event to the prior and effective sessions in both adjusted and unadjusted price modes, and
returns only dates/statuses plus source digests.  It intentionally does not read raw payload files, call Massive,
evaluate an event-price relationship, calculate a return, or drive the paper-evaluation gate.  A complete pair of
price windows is therefore ``pending_price_reconciliation``, never a reconciliation success.

The third cut can assess a caller-injected split factor only under a zero-tolerance rule: a factor mismatch is
``split_factor_mismatch_or_rounding_unresolved``, not a rounded pass.  Dividend adjustment semantics remain
unresolved because this module has no approved dividend-adjustment contract.  The future raw-payload adapter needs
its own explicitly authorised slice.  All downstream/provider/ship-gate permissions remain fixed false.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "us_short_massive_corporate_action_reconciliation_evidence.schema.json"
)
_VALIDATOR = None
_ASSESSMENT_VALIDATOR = None
_FAMILIES = ("splits", "dividends", "daily_adjusted", "daily_unadjusted")
_EVENT_FIELDS = frozenset({"event_id", "symbol", "event_type", "event_date", "source_family"})
_PRICE_FIELDS = frozenset({"symbol", "session_date", "adjustment_mode", "source_family", "close"})
_EVENT_FAMILY = {"split": "splits", "dividend": "dividends"}
_PRICE_FAMILY = {"adjusted": "daily_adjusted", "unadjusted": "daily_unadjusted"}
_MEASUREMENT_FAMILIES = ("splits", "daily_adjusted", "daily_unadjusted")
_SPLIT_FACTOR_FIELDS = frozenset(
    {
        "event_id",
        "split_from",
        "split_to",
        "adjusted_prior_close",
        "adjusted_event_close",
        "unadjusted_prior_close",
        "unadjusted_event_close",
    }
)
_HEX = frozenset("0123456789abcdef")
_ASSESSMENT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "us_short_massive_corporate_action_assessment.schema.json"
)


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


def _assessment_schema_validator():
    global _ASSESSMENT_VALIDATOR
    if _ASSESSMENT_VALIDATOR is not None:
        return _ASSESSMENT_VALIDATOR
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - environment guard
        raise MassiveCorporateActionReconciliationError(
            "jsonschema is required to validate Massive corporate-action assessment"
        ) from exc
    try:
        schema = json.loads(_ASSESSMENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MassiveCorporateActionReconciliationError(
            "Massive corporate-action assessment schema cannot be loaded"
        ) from exc
    Draft7Validator.check_schema(schema)
    _ASSESSMENT_VALIDATOR = Draft7Validator(schema)
    return _ASSESSMENT_VALIDATOR


def _validate_assessment_schema(assessment: dict[str, Any]) -> None:
    errors = sorted(_assessment_schema_validator().iter_errors(assessment), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise MassiveCorporateActionReconciliationError(
            f"generated Massive corporate-action assessment violates its schema at {path}: {first.message}"
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


def _positive_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise MassiveCorporateActionReconciliationError(f"{label} must be a positive finite number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MassiveCorporateActionReconciliationError(f"{label} must be a positive finite number") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise MassiveCorporateActionReconciliationError(f"{label} must be a positive finite number")
    return parsed


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


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated_evidence_for_assessment(evidence: Any) -> list[dict[str, Any]]:
    if type(evidence) is not dict:
        raise MassiveCorporateActionReconciliationError("event_price_evidence must be an object")
    _validate_evidence_schema(evidence)
    windows = evidence["event_price_windows"]
    seen_ids: set[str] = set()
    split_count = 0
    dividend_count = 0
    complete_count = 0
    insufficient_count = 0
    for window in windows:
        event_id = window["event_id"]
        if event_id in seen_ids:
            raise MassiveCorporateActionReconciliationError(f"duplicate evidence event_id {event_id!r}")
        seen_ids.add(event_id)
        if window["event_type"] == "split":
            split_count += 1
        else:
            dividend_count += 1
        if window["assessment_status"] == "pending_price_reconciliation":
            complete_count += 1
        else:
            insufficient_count += 1
    expected_coverage = {
        "split_event_count": split_count,
        "dividend_event_count": dividend_count,
        "complete_two_mode_window_count": complete_count,
        "insufficient_price_window_count": insufficient_count,
    }
    if evidence["coverage"] != expected_coverage:
        raise MassiveCorporateActionReconciliationError("event-price evidence coverage does not match its windows")
    return windows


def _validated_measurement_refs(evidence: dict[str, Any], source_refs: Any) -> None:
    if type(source_refs) is not dict or frozenset(source_refs) != frozenset(_MEASUREMENT_FAMILIES):
        raise MassiveCorporateActionReconciliationError(
            "measurement_source_ref_sha256 must bind exactly splits/daily_adjusted/daily_unadjusted"
        )
    bound_refs = evidence["source_binding"]["source_ref_sha256"]
    for family in _MEASUREMENT_FAMILIES:
        digest = source_refs[family]
        if type(digest) is not str or len(digest) != 64 or any(char not in _HEX for char in digest):
            raise MassiveCorporateActionReconciliationError(
                f"measurement_source_ref_sha256.{family} must be lowercase sha256"
            )
        if digest != bound_refs[family]:
            raise MassiveCorporateActionReconciliationError(
                f"measurement source digest does not match event-price evidence for {family}"
            )


def _validated_split_factors(windows: list[dict[str, Any]], rows: Any) -> dict[str, dict[str, Decimal]]:
    if type(rows) is not list:
        raise MassiveCorporateActionReconciliationError("split_factor_rows must be a list")
    expected_ids = {
        window["event_id"]
        for window in windows
        if window["event_type"] == "split" and window["assessment_status"] == "pending_price_reconciliation"
    }
    out: dict[str, dict[str, Decimal]] = {}
    for index, row in enumerate(rows):
        row = _require_exact_keys(row, _SPLIT_FACTOR_FIELDS, f"split_factor_rows[{index}]")
        event_id = _event_id(row["event_id"])
        if event_id not in expected_ids:
            raise MassiveCorporateActionReconciliationError(
                "split factor rows may bind only complete split evidence windows"
            )
        if event_id in out:
            raise MassiveCorporateActionReconciliationError(f"duplicate split factor row for {event_id!r}")
        values = {
            name: _positive_decimal(row[name], f"split_factor_rows[{index}].{name}")
            for name in _SPLIT_FACTOR_FIELDS
            if name != "event_id"
        }
        if values["split_from"] == values["split_to"]:
            raise MassiveCorporateActionReconciliationError("split factor must change the share ratio")
        out[event_id] = values
    if frozenset(out) != frozenset(expected_ids):
        raise MassiveCorporateActionReconciliationError("complete split windows require exactly one factor measurement")
    return out


def _split_factor_status(values: dict[str, Decimal]) -> str:
    """Return exact-match or unresolved.  No rounding/tolerance is silently accepted in Cut 3."""
    expected_factor_change = Fraction(values["split_from"]) / Fraction(values["split_to"])
    prior_adjustment_factor = Fraction(values["unadjusted_prior_close"]) / Fraction(values["adjusted_prior_close"])
    event_adjustment_factor = Fraction(values["unadjusted_event_close"]) / Fraction(values["adjusted_event_close"])
    observed_factor_change = event_adjustment_factor / prior_adjustment_factor
    if observed_factor_change == expected_factor_change:
        return "split_factor_exact_match"
    return "split_factor_mismatch_or_rounding_unresolved"


def assess_split_factor_reconciliation(
    *,
    event_price_evidence: dict[str, Any],
    split_factor_rows: list[dict[str, Any]],
    measurement_source_ref_sha256: dict[str, str],
) -> dict[str, Any]:
    """Assess only complete split windows; do not infer dividend semantics or authorise the paper gate.

    The caller supplies in-memory normalized split ratios and price measurements.  Their three source digests must
    exactly match the prior event-price evidence.  This function has no raw adapter, no provider call, and no write
    path.  The comparison is intentionally zero-tolerance: a tiny rounding difference remains unresolved until a
    later, separately authorised source-semantics rule says otherwise.
    """
    windows = _validated_evidence_for_assessment(event_price_evidence)
    _validated_measurement_refs(event_price_evidence, measurement_source_ref_sha256)
    factors = _validated_split_factors(windows, split_factor_rows)

    assessments: list[dict[str, str]] = []
    split_exact_count = 0
    split_unresolved_count = 0
    dividend_unresolved_count = 0
    insufficient_count = 0
    for window in windows:
        event_id = window["event_id"]
        event_type = window["event_type"]
        if window["assessment_status"] == "insufficient_price_window":
            status = "insufficient_price_window"
            insufficient_count += 1
        elif event_type == "dividend":
            status = "dividend_adjustment_semantics_unresolved"
            dividend_unresolved_count += 1
        else:
            status = _split_factor_status(factors[event_id])
            if status == "split_factor_exact_match":
                split_exact_count += 1
            else:
                split_unresolved_count += 1
        assessments.append({"event_id": event_id, "event_type": event_type, "status": status})

    assessment = {
        "schema_name": "us_short_massive_corporate_action_assessment",
        "schema_version": "1.0.0",
        "evidence_binding": {
            "evidence_schema_name": event_price_evidence["schema_name"],
            "decision_date": event_price_evidence["decision_date"],
            "symbol": event_price_evidence["symbol"],
            "source_binding_sha256": _sha256_json(event_price_evidence["source_binding"]),
            "event_price_windows_sha256": _sha256_json(windows),
        },
        "event_assessments": assessments,
        "coverage": {
            "split_exact_match_count": split_exact_count,
            "split_mismatch_or_rounding_unresolved_count": split_unresolved_count,
            "dividend_semantics_unresolved_count": dividend_unresolved_count,
            "insufficient_price_window_count": insufficient_count,
        },
        "boundary": {
            "split_factor_assessment_performed": True,
            "provider_call_performed_during_derivation": False,
            "raw_payload_adapter_performed": False,
            "full_corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_evaluable_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }
    _validate_assessment_schema(assessment)
    return assessment
