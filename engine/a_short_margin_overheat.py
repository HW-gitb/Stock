"""Market-level financing-balance (融资余额) overheat facts for A-short row 19.

Queue row 19 (#16).  ``A-EGS/egs_main.py`` carried a placeholder line for this
for a long time while the neighbouring momentum judgement was really computed.
This module supplies the missing quantity: where today's whole-market financing
balance sits inside its own rolling three-year distribution.

Settled caliber (queue row 19, user adjudication 2026-08-04 refined by the row
21 probe; an implementer may not reinterpret it):

* the balance is ``rzye`` -- the financing leg only.  ``rzrqye`` bundles the
  securities-lending side, which is about 1% of the A-share total and only
  dilutes the "long leverage" meaning the gate is about;
* all three exchanges (``SSE`` / ``SZSE`` / ``BSE``) are summed.  BSE is ~0.3%
  and changes no verdict, but one stated caliber is worth more than 0.3%;
* the window is a rolling three years, and a single missing session inside it
  fails closed through the row 22a reconciliation rather than producing a
  percentile from a partial window;
* the unit is CNY.  The row 21 probe left the unit deliberately unresolved
  because northbound had already cost one 万元-vs-元 trap; Tushare publishes
  ``pro.margin`` balances in yuan and the consumer contract records that.

This module is pure and offline: no request, no credential, no file.  Callers
fetch and hand the provider rows in.

The percentile threshold and the cash factor are deliberately ``None``.  Row 19
publishes the percentile and a trigger-frequency evidence artifact first; the
number that decides real money is a user adjudication, not an implementer's
invention.  Until both are set, the consumer records the percentile and changes
no allocation -- and that is a second, independent gate from
``MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
import numbers
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from engine.a_short_market_history import (
    canonical_dates,
    percentile_rank,
    reconcile_dated_series,
)


#: Tushare ``pro.margin`` publishes one row per exchange per session.
MARGIN_OVERHEAT_EXCHANGES = ("SSE", "SZSE", "BSE")
MARGIN_EXCHANGE_FIELD = "exchange_id"
MARGIN_BALANCE_FIELD = "rzye"
MARGIN_BALANCE_UNIT = "CNY"
MARGIN_OVERHEAT_WINDOW_YEARS = 3
#: Three calendar years hold roughly 730 A-share sessions.  A calendar that
#: comes back far shorter than this is truncated, not a short market history,
#: and a percentile from it would silently describe the wrong window.
MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS = 600
#: One ``pro.margin`` response is capped by the vendor.  A response at or above
#: the cap is treated as truncated until proven otherwise -- the same lesson the
#: row 22b fetch and the limit-up index probe both had to learn the hard way.
MARGIN_PROVIDER_ROW_CAP = 2000
#: 300 sessions * 3 exchanges = 900 rows, comfortably inside that cap.
MARGIN_FETCH_SEGMENT_MAX_SESSIONS = 300
#: The market margin balance is published one session late: a 2026-08-05 fetch
#: returned every exchange through 2026-08-04 and nothing for 2026-08-05.  The
#: window therefore ends at the newest fully published session, and a longer
#: silence than this is a source outage rather than the normal lag.  This is the
#: market-level ``pro.margin`` surface, deliberately not tied to the per-stock
#: ``margin_detail`` lag constant: two endpoints, two publication schedules.
MARGIN_OVERHEAT_MAX_PUBLICATION_LAG_SESSIONS = 1

#: The overheat quantity is a RATIO, not a level (user adjudication 2026-08-06,
#: grounded in the B0 probe): the raw three-exchange balance drifted +84.1% over
#: six years, so "above its own 90th percentile" was almost always true and the
#: gate would have been a permanent haircut.  Dividing by the Shanghai
#: Composite's free-float market value (`index_dailybasic.float_mv`, CNY, the
#: B0-recommended denominator: six-year drift falls to +6.8%) yields a
#: stationary quantity a percentile threshold can actually discriminate on.
MARGIN_RATIO_DENOMINATOR_INDEX = "000001.SH"
MARGIN_RATIO_DENOMINATOR_FIELD = "float_mv"
#: Exchange set is DATE-EFFECTIVE (user adjudication 2026-08-06, option (a)):
#: BSE joins the required set from its first session with published margin data
#: (observed from the fetched rows), preserving the earlier "all three
#: exchanges" caliber without failing every pre-BSE historical window.  A
#: window that reaches into this date with no BSE rows at all is a truncated
#: fetch, not an old market, and fails closed.
BSE_MARGIN_EXPECTED_BY = "20260101"

#: Governance placeholders.  Row 19 does not invent either number.
MARGIN_OVERHEAT_PERCENTILE_THRESHOLD: float | None = None
MARGIN_OVERHEAT_CASH_FACTOR: float | None = None
#: Row 19 records only; flipping this is a separate user adjudication taken
#: together with the two numbers above.
MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED = False

#: Candidate thresholds published for that adjudication.
MARGIN_OVERHEAT_CANDIDATE_PERCENTILES = (0.80, 0.85, 0.90, 0.95)
#: Evidence history: scoring the last three years of weeks at the live gate's
#: own caliber (a FULL rolling three-year window per week) needs twice the
#: window of history.
MARGIN_OVERHEAT_EVIDENCE_HISTORY_YEARS = 6


def _finite_number(value: Any) -> bool:
    """Accept numpy scalars too; see ``a_short_market_history._is_finite_number``."""
    return (
        not isinstance(value, bool)
        and isinstance(value, numbers.Real)
        and math.isfinite(float(value))
    )


def _provider_number(value: Any) -> Any:
    """Normalise a finite decimal string before reconciliation."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return float(text)
    except ValueError:
        return value


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


def window_start(as_of: str, years: int = MARGIN_OVERHEAT_WINDOW_YEARS) -> str:
    """Return the inclusive calendar start of the rolling window."""
    canonical = canonical_dates([as_of])
    if not canonical:
        raise ValueError("as_of must be a canonical calendar date")
    parsed = datetime.strptime(canonical[0], "%Y%m%d")
    try:
        start = parsed.replace(year=parsed.year - int(years))
    except ValueError:  # 29 February
        start = parsed.replace(year=parsed.year - int(years), day=28)
    return start.strftime("%Y%m%d")


def fetch_segments(
    session_dates: Iterable[Any],
    *,
    max_sessions: int | None = None,
) -> list[tuple[str, ...]]:
    """Split a session list into vendor-cap-safe request windows, newest first.

    ``max_sessions`` resolves at call time so the module constant stays the one
    place to change it; a default argument would freeze it at import.
    """
    if max_sessions is None:
        max_sessions = MARGIN_FETCH_SEGMENT_MAX_SESSIONS
    if max_sessions <= 0:
        raise ValueError("max_sessions must be positive")
    dates = canonical_dates(session_dates)
    return [
        dates[offset:offset + max_sessions]
        for offset in range(0, len(dates), max_sessions)
    ]


def _bse_effective_from(records: list[Mapping[str, Any]]) -> str | None:
    """First session with a finite BSE margin row, from the response itself.

    The date is discovered, not invented: no reliable public constant states
    when BSE margin publication began, and pinning a wrong date would either
    fail every honest historical window or excuse a truncated one.  The
    anti-gaming checks live in the caller: BSE coverage must be exact from
    this date onward, and a window reaching `BSE_MARGIN_EXPECTED_BY` with no
    BSE at all is treated as truncated rather than as an old market.
    """
    dates = [
        canonical
        for row in records
        if str(row.get(MARGIN_EXCHANGE_FIELD, "")).strip().upper() == "BSE"
        and _finite_number(_provider_number(row.get(MARGIN_BALANCE_FIELD)))
        and (canonical := _canonical_date(row.get("trade_date"))) is not None
    ]
    return min(dates) if dates else None


def _canonical_date(value: Any) -> str | None:
    try:
        dates = canonical_dates([value])
    except (TypeError, ValueError):
        return None
    return dates[0] if dates else None


def required_exchanges(trade_date: str, bse_effective_from: str | None) -> tuple[str, ...]:
    """The date-effective required exchange set (adjudicated option (a))."""
    if bse_effective_from is not None and trade_date >= bse_effective_from:
        return MARGIN_OVERHEAT_EXCHANGES
    return ("SSE", "SZSE")


def market_margin_totals(
    rows: Any,
    *,
    requested_dates: Iterable[Any],
) -> dict[str, Any]:
    """Sum ``rzye`` across the required exchanges, per session, or fail closed.

    Every exchange is reconciled separately through the row 22a layer over the
    sessions where it is required, so a missing session on a required exchange
    cannot be summed into a smaller market total that still looks complete.
    The required set is date-effective: BSE joins from its first published
    session; a window reaching ``BSE_MARGIN_EXPECTED_BY`` with no BSE rows at
    all fails closed as a truncated fetch.
    """
    requested = canonical_dates(requested_dates)
    result: dict[str, Any] = {
        "totals": None,
        "requested_count": len(requested),
        "observed_count": 0,
        "coverage_complete": False,
        "exchange_coverage": {exchange: 0 for exchange in MARGIN_OVERHEAT_EXCHANGES},
        "bse_effective_from": None,
    }
    if not requested:
        return result
    records = _records(rows)
    if records is None:
        return result

    bse_from = _bse_effective_from(records)
    result["bse_effective_from"] = bse_from
    if bse_from is None and requested[0] >= BSE_MARGIN_EXPECTED_BY:
        return result

    by_exchange: dict[str, list[dict[str, Any]]] = {
        exchange: [] for exchange in MARGIN_OVERHEAT_EXCHANGES
    }
    for row in records:
        exchange = str(row.get(MARGIN_EXCHANGE_FIELD, "")).strip().upper()
        if exchange not in by_exchange:
            continue
        by_exchange[exchange].append(
            {
                "trade_date": row.get("trade_date"),
                MARGIN_BALANCE_FIELD: _provider_number(row.get(MARGIN_BALANCE_FIELD)),
            }
        )

    series_by_exchange: dict[str, dict[str, float]] = {}
    for exchange, exchange_rows in by_exchange.items():
        exchange_requested = tuple(
            date for date in requested
            if exchange in required_exchanges(date, bse_from)
        )
        if not exchange_requested:
            series_by_exchange[exchange] = {}
            continue
        requested_set = set(exchange_requested)
        reconciled = reconcile_dated_series(
            # The fetch may legitimately cover more than the published window
            # (the denominator index publishes same-day while margin lags one
            # session), so rows outside the requested set are irrelevant, not
            # gaps; within the window, missing/duplicate/non-finite still fail.
            [
                row for row in exchange_rows
                if (canonical := _canonical_date(row.get("trade_date"))) is not None
                and canonical in requested_set
            ],
            requested_dates=exchange_requested,
            value_key=MARGIN_BALANCE_FIELD,
        )
        result["exchange_coverage"][exchange] = int(reconciled["observed_count"])
        if not reconciled["coverage_complete"]:
            return result
        series_by_exchange[exchange] = {
            date: value for date, value in reconciled["series"]
        }

    totals = {
        date: sum(
            series_by_exchange[exchange][date]
            for exchange in required_exchanges(date, bse_from)
        )
        for date in requested
    }
    if any(not _finite_number(value) for value in totals.values()):
        return result
    result["totals"] = totals
    result["observed_count"] = len(totals)
    result["coverage_complete"] = True
    return result


def margin_ratio_series(
    margin_rows: Any,
    denominator_rows: Any,
    *,
    requested_dates: Iterable[Any],
) -> dict[str, Any]:
    """Per-session overheat ratio, or fail closed with the failing leg named.

    ratio_t = required-exchange ``rzye`` total / Shanghai Composite ``float_mv``
    (both CNY, both exactly reconciled over the same sessions).
    """
    requested = canonical_dates(requested_dates)
    totals = market_margin_totals(margin_rows, requested_dates=requested)
    result: dict[str, Any] = {
        "ratios": None,
        "numerator": totals,
        "denominator_coverage_complete": False,
        "requested_count": len(requested),
        "coverage_complete": False,
    }
    if not totals["coverage_complete"]:
        return result
    records = _records(denominator_rows)
    if records is None:
        return result
    requested_set = set(requested)
    denominator = reconcile_dated_series(
        [
            {
                "trade_date": canonical,
                MARGIN_RATIO_DENOMINATOR_FIELD: _provider_number(
                    row.get(MARGIN_RATIO_DENOMINATOR_FIELD)
                ),
            }
            for row in records
            if (canonical := _canonical_date(row.get("trade_date"))) is not None
            and canonical in requested_set
        ],
        requested_dates=requested,
        value_key=MARGIN_RATIO_DENOMINATOR_FIELD,
    )
    result["denominator_coverage_complete"] = bool(denominator["coverage_complete"])
    if not denominator["coverage_complete"]:
        return result
    float_mv = dict(denominator["series"])
    if any(value <= 0 for value in float_mv.values()):
        return result
    result["ratios"] = {
        date: totals["totals"][date] / float_mv[date] for date in requested
    }
    result["float_mv"] = float_mv
    result["coverage_complete"] = True
    return result


def resolve_published_window(
    rows: Any,
    *,
    calendar_dates: Iterable[Any],
    max_lag_sessions: int | None = None,
) -> tuple[str, ...]:
    """Trim the requested window back to the newest fully published session.

    The calendar knows that today is a trading day; the vendor does not publish
    today's market margin balance until the next session.  Requiring the window
    to reach the decision date would make every run fail closed, so the window
    ends at the newest session that carries all three exchanges -- but only if
    that session is within the normal publication lag.  A longer silence returns
    an empty window, because then the gap is an outage and the percentile would
    silently describe a stale market.
    """
    if max_lag_sessions is None:
        max_lag_sessions = MARGIN_OVERHEAT_MAX_PUBLICATION_LAG_SESSIONS
    calendar = canonical_dates(calendar_dates)
    if not calendar:
        return ()
    records = _records(rows)
    if records is None:
        return ()
    published: dict[str, set[str]] = {}
    for row in records:
        exchange = str(row.get(MARGIN_EXCHANGE_FIELD, "")).strip().upper()
        if exchange not in MARGIN_OVERHEAT_EXCHANGES:
            continue
        if not _finite_number(_provider_number(row.get(MARGIN_BALANCE_FIELD))):
            continue
        trade_date = canonical_dates([row.get("trade_date")]) if row.get("trade_date") is not None else ()
        if trade_date:
            published.setdefault(trade_date[0], set()).add(exchange)
    bse_from = _bse_effective_from(records)
    for lag, trade_date in enumerate(calendar):
        if published.get(trade_date) == set(required_exchanges(trade_date, bse_from)):
            if lag > int(max_lag_sessions):
                return ()
            return calendar[lag:]
    return ()


def should_reduce_new_exposure(
    percentile: Any,
    threshold: Any = None,
) -> bool:
    """Fail-closed overheat predicate: both facts must be present and finite.

    ``threshold`` defaults to the governance constant, which is ``None`` until
    the user adjudicates it -- so today this predicate is always ``False`` and
    the caller records the percentile without touching any allocation.
    """
    if threshold is None:
        threshold = MARGIN_OVERHEAT_PERCENTILE_THRESHOLD
    return (
        _finite_number(percentile)
        and _finite_number(threshold)
        and float(percentile) >= float(threshold)
    )


def margin_overheat_facts(
    rows: Any,
    denominator_rows: Any = None,
    *,
    requested_dates: Iterable[Any],
    production_effect_enabled: bool | None = None,
) -> dict[str, Any]:
    """Reduce one margin+denominator response pair to the row-19 leaves.

    The percentile is taken over the RATIO series (balance / Shanghai Composite
    float market value), never over the raw balance: the level drifted +84% in
    six years and its percentile was almost always high (user adjudication
    2026-08-06).  Both legs reconcile exactly or nothing is published.
    """
    if production_effect_enabled is None:
        production_effect_enabled = MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED
    requested = canonical_dates(requested_dates)
    facts: dict[str, Any] = {
        "percentile": None,
        "ratio": None,
        "balance_yuan": None,
        "denominator_float_mv_yuan": None,
        "window_start": requested[-1] if requested else None,
        "window_end": requested[0] if requested else None,
        "requested_session_count": len(requested),
        "observed_session_count": 0,
        "coverage_complete": False,
        "production_effect_enabled": bool(production_effect_enabled),
    }
    if len(requested) < MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS:
        # A short calendar is a truncated fetch far more often than it is a
        # genuinely short market history; either way it is not a three-year
        # window and must not be published as one.
        return facts
    series = margin_ratio_series(rows, denominator_rows, requested_dates=requested)
    facts["observed_session_count"] = int(series["numerator"]["observed_count"])
    if not series["coverage_complete"]:
        return facts
    ratios = series["ratios"]
    current_ratio = ratios[requested[0]]
    percentile = percentile_rank(ratios.values(), current_ratio)
    if percentile is None:
        return facts
    facts.update(
        {
            "percentile": float(percentile),
            "ratio": float(current_ratio),
            "balance_yuan": float(series["numerator"]["totals"][requested[0]]),
            "denominator_float_mv_yuan": float(series["float_mv"][requested[0]]),
            "coverage_complete": True,
        }
    )
    return facts


def _iso_week_key(trade_date: str) -> tuple[int, int]:
    iso = datetime.strptime(trade_date, "%Y%m%d").isocalendar()
    return int(iso.year), int(iso.week)


def _week_endpoints(dates: Sequence[str]) -> tuple[str, ...]:
    """Return the latest observed session per ISO week, oldest first."""
    latest: dict[tuple[int, int], str] = {}
    for trade_date in dates:
        key = _iso_week_key(trade_date)
        if trade_date > latest.get(key, ""):
            latest[key] = trade_date
    return tuple(sorted(latest.values()))


def _week_monday(trade_date: str) -> datetime:
    parsed = datetime.strptime(trade_date, "%Y%m%d")
    return parsed - timedelta(days=parsed.isocalendar().weekday - 1)


def _longest_calendar_consecutive(week_ends: Sequence[str], flags: Sequence[bool]) -> int:
    """Longest run of triggering weeks that are adjacent on the ISO calendar.

    Counting runs over the evaluable list alone silently bridged calendar weeks
    with no trading sessions (a Spring Festival week), so a published "longest
    consecutive 53 weeks" really spanned 54 calendar weeks (review Optional
    O-5).  A missing calendar week now breaks the run.
    """
    longest = current = 0
    previous_monday: datetime | None = None
    for week_end, flag in zip(week_ends, flags):
        monday = _week_monday(week_end)
        if flag:
            adjacent = previous_monday is not None and (monday - previous_monday).days == 7
            current = current + 1 if (current and adjacent) else 1
            longest = max(longest, current)
        else:
            current = 0
        previous_monday = monday
    return longest


def _rolling_window_start(week_end: str, years: int = MARGIN_OVERHEAT_WINDOW_YEARS) -> str:
    parsed = datetime.strptime(week_end, "%Y%m%d")
    try:
        start = parsed.replace(year=parsed.year - int(years))
    except ValueError:  # 29 February
        start = parsed.replace(year=parsed.year - int(years), day=28)
    return start.strftime("%Y%m%d")


def threshold_trigger_evidence(
    totals: Mapping[str, Any],
    *,
    candidate_percentiles: Iterable[float] = MARGIN_OVERHEAT_CANDIDATE_PERCENTILES,
    min_trailing_sessions: int = MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS,
) -> dict[str, Any]:
    """Score each historical week against each candidate percentile threshold.

    Each week is scored at the LIVE gate's own caliber: its window is exactly
    the rolling three calendar years ending at that week, and a week whose
    window holds fewer sessions than the live 600-session floor is reported as
    unavailable warm-up rather than scored against a window the gate would
    never use.  The earlier expanding-window basis is retired: with six years
    of history (adjudicated 2026-08-06) the last three years of weeks all
    carry full live-caliber windows, so the published frequency is what the
    gate itself would have done.
    """
    dates = sorted(str(date) for date in totals)
    if any(not _finite_number(totals[date]) for date in dates):
        raise ValueError("threshold evidence requires a fully finite series")
    weeks = _week_endpoints(dates)
    thresholds = [float(value) for value in candidate_percentiles]
    if any(not 0.0 < value <= 1.0 for value in thresholds):
        raise ValueError("candidate percentiles must lie in (0,1]")

    week_rows: list[dict[str, Any]] = []
    for week_end in weeks:
        window_start = _rolling_window_start(week_end)
        trailing = [totals[date] for date in dates if window_start <= date <= week_end]
        if len(trailing) < int(min_trailing_sessions):
            week_rows.append(
                {
                    "week_end": week_end,
                    "trailing_session_count": len(trailing),
                    "percentile": None,
                    "verdict": "unavailable",
                    "unavailable_reason": "warm_up",
                }
            )
            continue
        percentile = percentile_rank(trailing, totals[week_end])
        if percentile is None:
            week_rows.append(
                {
                    "week_end": week_end,
                    "trailing_session_count": len(trailing),
                    "percentile": None,
                    "verdict": "unavailable",
                    "unavailable_reason": "source_gap",
                }
            )
            continue
        week_rows.append(
            {
                "week_end": week_end,
                "trailing_session_count": len(trailing),
                "percentile": float(percentile),
                "verdict": "evaluable",
                "unavailable_reason": None,
            }
        )

    evaluable = [row for row in week_rows if row["verdict"] == "evaluable"]
    by_threshold = []
    for threshold in thresholds:
        flags = [
            should_reduce_new_exposure(row["percentile"], threshold)
            for row in evaluable
        ]
        by_year: dict[str, int] = {}
        for row, flag in zip(evaluable, flags):
            if flag:
                # ISO year, matching the ISO-week grouping the endpoints come
                # from; the natural year misfiled a 12-31 that belongs to the
                # next ISO year (review Optional O-5).
                year = str(_iso_week_key(row["week_end"])[0])
                by_year[year] = by_year.get(year, 0) + 1
        by_threshold.append(
            {
                "percentile_threshold": threshold,
                "trigger_week_count": sum(flags),
                "longest_consecutive_trigger_weeks": _longest_calendar_consecutive(
                    [row["week_end"] for row in evaluable], flags
                ),
                "trigger_weeks_by_year": dict(sorted(by_year.items())),
            }
        )

    return {
        "basis": (
            f"live_caliber_rolling_{MARGIN_OVERHEAT_WINDOW_YEARS}y_"
            f"min_{int(min_trailing_sessions)}_sessions"
        ),
        "week_count": len(week_rows),
        "evaluable_week_count": len(evaluable),
        "unavailable_week_count": len(week_rows) - len(evaluable),
        "unavailable_breakdown": {
            "warm_up": sum(
                row.get("unavailable_reason") == "warm_up" for row in week_rows
            ),
            "source_gap": sum(
                row.get("unavailable_reason") == "source_gap" for row in week_rows
            ),
        },
        "by_threshold": by_threshold,
        "weeks": week_rows,
    }
