"""Pure, fail-closed northbound market-gate lookback calculations.

Queue row 22b.  The weekly production gate already has one canonical
predicate in :mod:`engine.a_short_northbound`; this module only applies that
predicate to historical, provider-shaped rows for a comparison artifact.

The benchmark ``index_daily`` dates are the historical trading-session
calendar.  A northbound five-session request is built from that calendar, not
from whatever northbound rows happened to survive the provider response.  A
missing northbound row therefore cannot silently move the five-session window
backward.  The CSI300 window uses the exact live EGS trade-date span (65
sessions in the current production configuration); the shared 20-session
value is only the live minimum-length guard.  Both series pass through the
shared 22a exact reconciliation layer.

This module is pure: it does not call a provider, read credentials, change a
production flag, or write a file.  Callers fetch and store raw payloads; this
module returns counts and per-week verdicts without raw rows or numeric input
values.
"""

from __future__ import annotations

from datetime import datetime
import math
import numbers
import re
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Iterable

from engine.a_short_market_history import canonical_dates, reconcile_dated_series
from engine.a_short_csi300_window import CSI300_LIVE_WINDOW_SESSIONS
from engine.a_short_northbound import (
    classify_northbound_status,
    should_block_new_entries,
)


LOOKBACK_SCHEMA_NAME = "a_short_northbound_market_silence_lookback_summary"
LOOKBACK_SCHEMA_VERSION = "2.0.0"
NORTHBOUND_FLOW_WINDOW_SESSIONS = 5
# Tushare moneyflow_hsgt.north_money is in 万元.  The live producer converts
# it once at the provider boundary; the historical comparison must use the
# same CNY input semantics before calling the shared live predicate.
TUSHARE_NORTH_MONEY_UNIT_YUAN = 10_000
_DATE8 = re.compile(r"^[0-9]{8}$")


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, numbers.Real)
        and math.isfinite(float(value))
    )


def _canonical_date(value: Any) -> str | None:
    try:
        date = canonical_dates([value])
    except (TypeError, ValueError):
        return None
    return date[0] if date and _DATE8.fullmatch(date[0]) else None


def _records(payload: Any) -> list[Mapping[str, Any]] | None:
    """Convert a provider frame explicitly; reject generators and objects."""
    if payload is None or isinstance(payload, (str, bytes)):
        return None
    to_dict = getattr(payload, "to_dict", None)
    if callable(to_dict):
        try:
            payload = to_dict(orient="records")
        except (TypeError, ValueError):
            return None
    if not isinstance(payload, (list, tuple)):
        return None
    if any(not isinstance(row, Mapping) for row in payload):
        return None
    return list(payload)


def _normalise_rows(
    payload: Any,
    *,
    value_key: str,
    expected_ts_code: str | None = None,
) -> list[dict[str, Any]] | None:
    """Return canonical rows or ``None`` when the source shape is unusable."""
    rows = _records(payload)
    if rows is None:
        return None
    normalised: list[dict[str, Any]] = []
    for row in rows:
        trade_date = _canonical_date(row.get("trade_date"))
        if trade_date is None:
            return None
        if expected_ts_code is not None:
            ts_code = row.get("ts_code")
            if ts_code is not None and str(ts_code).strip().upper() != expected_ts_code:
                return None
        normalised.append(
            {
                "trade_date": trade_date,
                value_key: _provider_number(row.get(value_key)),
            }
        )
    return normalised


def _provider_number(value: Any) -> Any:
    """Normalise a provider's finite decimal string before 22a reconciliation."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        parsed = float(text)
    except ValueError:
        return value
    return parsed


def _iso_week_key(trade_date: str) -> tuple[int, int]:
    parsed = datetime.strptime(trade_date, "%Y%m%d")
    iso = parsed.isocalendar()
    return int(iso.year), int(iso.week)


def three_year_lookback_start(as_of: str) -> str:
    """Return the inclusive calendar-date start of the three-year window."""
    canonical = _canonical_date(as_of)
    if canonical is None:
        raise ValueError("as_of must be a canonical calendar date")
    parsed = datetime.strptime(canonical, "%Y%m%d")
    try:
        start = parsed.replace(year=parsed.year - 3)
    except ValueError:  # 29 February in a leap year
        start = parsed.replace(year=parsed.year - 3, day=28)
    return start.strftime("%Y%m%d")


def _week_endpoints(index_rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Return one latest observed CSI300 session per ISO week, oldest first."""
    latest_by_week: dict[tuple[int, int], str] = {}
    for row in index_rows:
        trade_date = str(row["trade_date"])
        key = _iso_week_key(trade_date)
        if trade_date > latest_by_week.get(key, ""):
            latest_by_week[key] = trade_date
    return tuple(sorted(latest_by_week.values()))


def _calendar_window(
    index_rows: Sequence[Mapping[str, Any]],
    *,
    week_end: str,
    size: int,
) -> tuple[str, ...] | None:
    dates = sorted(
        {
            str(row["trade_date"])
            for row in index_rows
            if str(row["trade_date"]) <= week_end
        },
        reverse=True,
    )
    if len(dates) < size:
        return None
    return tuple(dates[:size])


def _unavailable_reason(
    *,
    csi_dates: Sequence[str] | None,
    flow_dates: Sequence[str] | None,
    truncated_dates: set[str],
) -> str:
    if csi_dates is None:
        return "warm_up"
    if flow_dates and any(date in truncated_dates for date in flow_dates):
        return "fetch_truncated"
    return "source_gap"


def _reconcile_window(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    requested_dates: Iterable[str] | None,
    value_key: str,
) -> dict[str, Any]:
    if requested_dates is None or rows is None:
        return {
            "series": None,
            "requested_count": 0 if requested_dates is None else len(tuple(requested_dates)),
            "observed_count": 0,
            "coverage_complete": False,
        }
    requested = tuple(requested_dates)
    selected = [row for row in rows if row.get("trade_date") in set(requested)]
    return reconcile_dated_series(
        selected,
        requested_dates=requested,
        value_key=value_key,
    )


def _lookback_predicate(flow_yuan: Any, status: str, csi300_return: Any) -> bool:
    """Small named seam used by the injection negative control."""
    return should_block_new_entries(flow_yuan, status, csi300_return)


def _week_verdict(
    *,
    week_end: str,
    index_rows: Sequence[Mapping[str, Any]],
    northbound_rows: Sequence[Mapping[str, Any]] | None,
    predicate: Callable[[Any, str, Any], bool] | None = None,
    northbound_fetch_truncated_dates: set[str] | None = None,
) -> dict[str, Any]:
    """Evaluate one week and assert the result agrees with the live predicate."""
    predicate = _lookback_predicate if predicate is None else predicate
    northbound_fetch_truncated_dates = northbound_fetch_truncated_dates or set()
    csi_dates = _calendar_window(
        index_rows,
        week_end=week_end,
        size=CSI300_LIVE_WINDOW_SESSIONS,
    )
    flow_dates = None if csi_dates is None else csi_dates[:NORTHBOUND_FLOW_WINDOW_SESSIONS]
    csi = _reconcile_window(index_rows, requested_dates=csi_dates, value_key="close")
    flow = _reconcile_window(
        northbound_rows,
        requested_dates=flow_dates,
        value_key="north_money",
    )

    csi_complete = csi["coverage_complete"] is True
    flow_complete = flow["coverage_complete"] is True
    if not csi_complete or not flow_complete:
        # Missing facts deliberately flow through the same live predicate as
        # production; the result is recorded as unavailable and never enters
        # the eligible denominator.
        canonical = should_block_new_entries(None, "unknown", None)
        observed = predicate(None, "unknown", None)
        if observed != canonical:
            raise AssertionError("northbound lookback predicate diverges on unavailable facts")
        return {
            "week_end": week_end,
            "northbound_coverage": "complete" if flow_complete else "unavailable",
            "csi300_coverage": "complete" if csi_complete else "unavailable",
            "verdict": "unavailable",
            "unavailable_reason": _unavailable_reason(
                csi_dates=csi_dates,
                flow_dates=flow_dates,
                truncated_dates=northbound_fetch_truncated_dates,
            ),
            "predicate_consistent": True,
        }

    flow_values = [value for _, value in flow["series"]]
    csi_values = [value for _, value in csi["series"]]
    if (
        any(not _finite_number(value) for value in flow_values)
        or any(not _finite_number(value) or float(value) <= 0 for value in csi_values)
    ):
        canonical = should_block_new_entries(None, "unknown", None)
        observed = predicate(None, "unknown", None)
        if observed != canonical:
            raise AssertionError("northbound lookback predicate diverges on invalid facts")
        return {
            "week_end": week_end,
            "northbound_coverage": "unavailable",
            "csi300_coverage": "unavailable",
            "verdict": "unavailable",
            "unavailable_reason": _unavailable_reason(
                csi_dates=csi_dates,
                flow_dates=flow_dates,
                truncated_dates=northbound_fetch_truncated_dates,
            ),
            "predicate_consistent": True,
        }

    flow_yuan = sum(float(value) for value in flow_values) * TUSHARE_NORTH_MONEY_UNIT_YUAN
    status = classify_northbound_status(flow_yuan)
    csi300_return = (float(csi_values[0]) / float(csi_values[-1]) - 1.0) * 100.0
    observed = predicate(flow_yuan, status, csi300_return)
    canonical = should_block_new_entries(flow_yuan, status, csi300_return)
    if observed != canonical:
        raise AssertionError("northbound lookback predicate diverges from live predicate")
    return {
        "week_end": week_end,
        "northbound_coverage": "complete",
        "csi300_coverage": "complete",
        "verdict": "triggered" if observed else "eligible_not_triggered",
        "unavailable_reason": None,
        "predicate_consistent": True,
    }


def build_lookback_summary(
    northbound_payload: Any,
    csi300_payload: Any,
    *,
    as_of: str,
    source_artifact_count: int = 2,
    predicate: Callable[[Any, str, Any], bool] | None = None,
    northbound_fetch_truncated_dates: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build the counts-only comparison artifact from two fetched payloads."""
    canonical_as_of = _canonical_date(as_of)
    if canonical_as_of is None:
        raise ValueError("as_of must be a canonical calendar date")
    predicate = _lookback_predicate if predicate is None else predicate
    truncated_dates = {
        canonical
        for value in (northbound_fetch_truncated_dates or ())
        if (canonical := _canonical_date(value)) is not None
    }

    northbound_rows = _normalise_rows(northbound_payload, value_key="north_money")
    index_rows = _normalise_rows(
        csi300_payload,
        value_key="close",
        expected_ts_code="000300.SH",
    )
    if index_rows is None:
        index_rows = []
    northbound_rows = northbound_rows if northbound_rows is not None else None

    lookback_start = three_year_lookback_start(canonical_as_of)
    index_rows = [
        row for row in index_rows
        if lookback_start <= row["trade_date"] <= canonical_as_of
    ]
    if northbound_rows is not None:
        northbound_rows = [
            row for row in northbound_rows
            if lookback_start <= row["trade_date"] <= canonical_as_of
        ]
    weeks = _week_endpoints(index_rows)
    verdicts = [
        _week_verdict(
            week_end=week_end,
            index_rows=index_rows,
            northbound_rows=northbound_rows,
            predicate=predicate,
            northbound_fetch_truncated_dates=truncated_dates,
        )
        for week_end in weeks
    ]
    eligible = sum(item["verdict"] != "unavailable" for item in verdicts)
    unavailable = sum(item["verdict"] == "unavailable" for item in verdicts)
    triggered = sum(item["verdict"] == "triggered" for item in verdicts)

    not_verified: list[str] = []
    if index_rows == []:
        not_verified.append("index_daily CSI300 source is unavailable or has an invalid shape")
    if northbound_rows is None:
        not_verified.append("moneyflow_hsgt northbound source is unavailable or has an invalid shape")
    if unavailable:
        unavailable_breakdown = {
            "warm_up": sum(item.get("unavailable_reason") == "warm_up" for item in verdicts),
            "fetch_truncated": sum(item.get("unavailable_reason") == "fetch_truncated" for item in verdicts),
            "source_gap": sum(item.get("unavailable_reason") == "source_gap" for item in verdicts),
        }
        not_verified.append(
            f"{unavailable} of {len(verdicts)} weekly windows are unavailable after exact coverage reconciliation "
            f"(warm_up={unavailable_breakdown['warm_up']}, "
            f"fetch_truncated={unavailable_breakdown['fetch_truncated']}, "
            f"source_gap={unavailable_breakdown['source_gap']})"
        )
    else:
        unavailable_breakdown = {"warm_up": 0, "fetch_truncated": 0, "source_gap": 0}
    if not verdicts:
        not_verified.append("no historical weekly endpoints were observed")
    if eligible == 0 and verdicts:
        not_verified.append("no eligible weekly window is available for trigger-frequency interpretation")

    if not verdicts or eligible == 0:
        status = "NOT_VERIFIED"
        trigger_count: int | None = None
    elif unavailable:
        status = "PARTIAL"
        trigger_count = triggered
    else:
        status = "COMPLETE"
        trigger_count = triggered

    return {
        "schema_name": LOOKBACK_SCHEMA_NAME,
        "schema_version": LOOKBACK_SCHEMA_VERSION,
        "as_of": canonical_as_of,
        "lookback_basis": "provider_historical_week_endpoints",
        "lookback_start": lookback_start,
        "lookback_week_count": len(verdicts),
        "weeks_considered": [item["week_end"] for item in verdicts],
        "source_artifact_count": max(0, int(source_artifact_count)),
        "structured_fact_week_count": eligible,
        "eligible_week_count": eligible,
        "trigger_count": trigger_count,
        "unavailable_week_count": unavailable,
        "weeks": verdicts,
        "status": status,
        "comparison_only": True,
        "production_effect_enabled": False,
        "source_binding": {
            "northbound": "tushare:moneyflow_hsgt.north_money",
            "northbound_unit": "CNY_after_provider_wan_times_10000",
            "northbound_window_sessions": NORTHBOUND_FLOW_WINDOW_SESSIONS,
            "csi300": "tushare:index_daily.000300.SH.close",
            "csi300_window_sessions": CSI300_LIVE_WINDOW_SESSIONS,
            "predicate": "engine.a_short_northbound.should_block_new_entries",
            "calendar_basis": "index_daily.000300.SH.trade_date",
        },
        "unavailable_breakdown": unavailable_breakdown,
        "northbound_fetch": {
            "row_cap": None,
            "segment_max_sessions": None,
            "segment_count": 0,
            "requested_session_count": 0,
            "observed_session_count": 0,
            "truncated_segment_count": 0,
            "truncated": False,
            "status": "not_supplied",
        },
        "not_verified": not_verified,
    }
