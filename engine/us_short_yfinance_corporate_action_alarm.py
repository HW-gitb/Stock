"""Pure evaluator for a low-trust, one-ticker yfinance corporate-action smoke alarm."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any

from engine.us_short_security_identity import SecurityIdentityError, validate_security_identity


_OBSERVATION_KEYS = frozenset((
    "source_ticker", "returned_ticker", "expected_price_date", "observed_at", "fetch_status",
    "price_date", "close", "stock_splits", "dividends", "network_access_performed",
))
_FETCH_STATUSES = frozenset(("ok", "empty", "error"))


class YFinanceCorporateActionAlarmError(ValueError):
    """The low-trust observation is malformed or not bound to the supplied identity."""


def _identity(record: Any) -> dict[str, Any]:
    try:
        return validate_security_identity(record)
    except SecurityIdentityError as exc:
        raise YFinanceCorporateActionAlarmError("security identity is invalid") from exc


def _identity_digest(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _date(value: Any, *, field: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise YFinanceCorporateActionAlarmError(f"{field} must be YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise YFinanceCorporateActionAlarmError(f"{field} must be a real date") from exc
    return value


def _timestamp(value: Any) -> str:
    if type(value) is not str or "T" not in value:
        raise YFinanceCorporateActionAlarmError("observed_at must be an aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise YFinanceCorporateActionAlarmError("observed_at must be an aware ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise YFinanceCorporateActionAlarmError("observed_at must be timezone-aware")
    return value


def _number(value: Any, *, field: str, positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise YFinanceCorporateActionAlarmError(f"{field} must be numeric")
    try:
        finite = math.isfinite(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise YFinanceCorporateActionAlarmError(f"{field} must be finite") from exc
    if not finite or (positive and value <= 0) or (not positive and value < 0):
        raise YFinanceCorporateActionAlarmError(f"{field} is outside the allowed range")
    return float(value)


def evaluate_yfinance_daily_alarm(identity_record: Any, observation: Any) -> dict[str, Any]:
    """Classify one normalized daily action row without treating yfinance as semantics."""
    identity = _identity(identity_record)
    if not isinstance(observation, dict) or set(observation) != _OBSERVATION_KEYS:
        raise YFinanceCorporateActionAlarmError("observation must have the exact contract keys")
    if observation["source_ticker"] != identity["current_ticker"]:
        raise YFinanceCorporateActionAlarmError("source_ticker is not bound to the identity")
    expected = _date(observation["expected_price_date"], field="expected_price_date")
    observed_at = _timestamp(observation["observed_at"])
    status = observation["fetch_status"]
    if status not in _FETCH_STATUSES:
        raise YFinanceCorporateActionAlarmError("fetch_status is invalid")
    if type(observation["network_access_performed"]) is not bool:
        raise YFinanceCorporateActionAlarmError("network_access_performed must be boolean")

    reasons: list[str] = []
    if status != "ok":
        nullable = ("returned_ticker", "price_date", "close", "stock_splits", "dividends")
        if any(observation[key] is not None for key in nullable):
            raise YFinanceCorporateActionAlarmError("empty/error observations must not carry provider values")
        reasons.append("source_unavailable")
    else:
        returned = observation["returned_ticker"]
        if type(returned) is not str:
            raise YFinanceCorporateActionAlarmError("ok observation must carry returned_ticker")
        if returned != identity["current_ticker"]:
            reasons.append("returned_ticker_mismatch")
        price_date = _date(observation["price_date"], field="price_date")
        close = _number(observation["close"], field="close", positive=True)
        split = _number(observation["stock_splits"], field="stock_splits", positive=False)
        dividend = _number(observation["dividends"], field="dividends", positive=False)
        if price_date != expected:
            reasons.append("missing_expected_bar")
        if dividend > 0:
            reasons.append("dividend_reported")
        if split > 0:
            reasons.append("split_reported")
        _ = close

    ordered = [reason for reason in (
        "source_unavailable", "returned_ticker_mismatch", "missing_expected_bar",
        "dividend_reported", "split_reported",
    ) if reason in reasons]
    if not ordered:
        alarm_status = "clear"
    elif ordered == ["source_unavailable"]:
        alarm_status = "source_unavailable"
    else:
        alarm_status = "advisory_alarm"
    freeze = bool(ordered)
    return {
        "schema_name": "us_short_yfinance_corporate_action_alarm",
        "schema_version": "1.0.0",
        "security_binding": {
            "security_id": identity["security_id"],
            "current_ticker": identity["current_ticker"],
            "identity_ref_sha256": _identity_digest(identity),
        },
        "expected_price_date": expected,
        "observed_at": observed_at,
        "alarm_status": alarm_status,
        "alarm_reasons": ordered,
        "manual_review_required": freeze,
        "ticker_scoped_freeze_required": freeze,
        "failure_isolation": {
            "global_run_blocked": False,
            "unrelated_symbols_frozen": False,
        },
        "boundary": {
            "provider_call_performed": observation["network_access_performed"],
            "source_trust": "low_trust_advisory",
            "corporate_event_semantics_confirmed": False,
            "selection_use_allowed": False,
            "provider_health_gate_use_allowed": False,
            "paper_performance_confirmation_allowed": False,
            "account_state_read": False,
            "broker_order_placed": False,
            "ship_gate_evidence_claimed": False,
        },
    }
