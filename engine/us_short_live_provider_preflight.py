"""Pure preflight helpers for live US-short provider entry points.

This module deliberately owns no I/O, provider calls, state writes, or caller
supplied "actual now" override.  Callers provide the requested anchor and a
frozen calendar; the actual ET wall clock is resolved internally.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from engine.us_short_canonical_asof import OutOfWindowError, resolve_canonical_asof
from engine.us_short_market_calendar import sessions_for_window


_ET = ZoneInfo("America/New_York")


def _now_et_wall_clock() -> datetime:
    """Return the actual current wall clock as a naive ET datetime."""

    return datetime.now(timezone.utc).astimezone(_ET).replace(tzinfo=None)


def _safe_datetime_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def _safe_aware_datetime_text(value: datetime) -> str:
    return value.replace(tzinfo=_ET).astimezone(timezone.utc).isoformat(timespec="seconds")


def _resolve_requested_canonical(
    now_et: datetime,
    calendar: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a canonical anchor and return only a safe failure category."""

    try:
        sessions = sessions_for_window(
            now_et.strftime("%Y%m%d"), calendar=calendar, back_days=15, fwd_days=15
        )
        return resolve_canonical_asof(now_et, sessions), None
    except OutOfWindowError:
        return None, "INTRADAY_DEAD_ZONE"
    except (TypeError, ValueError, KeyError):
        return None, "CANONICAL_WINDOW_UNAVAILABLE"


def _anchor_fields(canonical: Mapping[str, Any] | None) -> dict[str, Any]:
    if canonical is None:
        return {"decision_date": None, "price_basis_date": None, "run_date": None}
    return {
        "decision_date": canonical.get("decision_date"),
        "price_basis_date": canonical.get("price_basis_date"),
        "run_date": canonical.get("run_date"),
    }


def validate_provider_pace_seconds(value: Any) -> float:
    """Validate the shared provider pace contract and return a float value."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("provider_pace_seconds must be a finite number in [0, 60] and not bool")
    if not math.isfinite(value) or value < 0 or value > 60:
        raise ValueError("provider_pace_seconds must be a finite number in [0, 60] and not bool")
    return float(value)


def inspect_live_provider_clock(
    *,
    requested_now_et: datetime,
    calendar: Mapping[str, Any],
    requested_canonical: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare requested and actual canonical windows without doing any I/O."""

    requested, requested_failure = _resolve_requested_canonical(requested_now_et, calendar)
    actual_now_et = _now_et_wall_clock()
    actual, actual_failure = _resolve_requested_canonical(actual_now_et, calendar)

    requested_fields = _anchor_fields(requested)
    actual_fields = _anchor_fields(actual)
    requested_fields["now_et"] = _safe_datetime_text(requested_now_et)
    actual_fields["now_et"] = _safe_datetime_text(actual_now_et)

    if requested_failure:
        reason_code = "REQUESTED_CANONICAL_UNAVAILABLE"
    elif actual_failure:
        reason_code = actual_failure
    elif requested_canonical is not None and _anchor_fields(requested_canonical) != _anchor_fields(requested):
        reason_code = "REQUESTED_CONTEXT_MISMATCH"
    elif (
        requested_fields["decision_date"] == actual_fields["decision_date"]
        and requested_fields["price_basis_date"] == actual_fields["price_basis_date"]
    ):
        reason_code = "LIVE_CANONICAL_MATCH"
    else:
        reason_code = "LIVE_CANONICAL_MISMATCH"

    actual_window_state = actual.get("window_state") if actual is not None else actual_failure
    return {
        "compatible": reason_code == "LIVE_CANONICAL_MATCH",
        "reason_code": reason_code,
        "requested": requested_fields,
        "actual": actual_fields,
        "requested_window_state": requested.get("window_state") if requested is not None else requested_failure,
        "actual_window_state": actual_window_state,
        "actual_observed_at_et": _safe_datetime_text(actual_now_et),
        "actual_observed_at_utc": _safe_aware_datetime_text(actual_now_et),
    }
