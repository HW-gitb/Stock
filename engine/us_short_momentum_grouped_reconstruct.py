# -*- coding: utf-8 -*-
"""US-short full-universe: reconstruct per-ticker dated series from a grouped-daily window (pure).

Two shapes share ONE mechanical group-by-ticker walk (`_reconstruct_from_grouped`, single-source so the
ascending-axis / dedup / canonical-filter safety can never drift between them): the momentum
`{date,close,volume}` series (`reconstruct_series_from_grouped`, the §4.2 engine input) and the §4.3
overextension `{date,high,low,close,volume}` OHLCV series (`reconstruct_ohlcv_series_from_grouped`, cut 2b-iii,
which RETAINS high/low for ATR). Only the per-row point fields differ; the walk + fail-closed envelope are identical.

Design authority: docs/system_risk_register.md::R-USSHORT-BATCH5-FULL-UNIVERSE-MOMENTUM-PRODUCTION-MISSING.
The universe fetch already proved the cheap grouped-daily path — ONE Massive call per trading day returns
`{T,c,v}` for the WHOLE US market (runners/us_short_universe_fetch.py::_massive_grouped_for_date). To score
momentum for all ~2404 Pass1-eligible we need ~63+ sessions of that grouped data (LOOKBACK_3M=63), reshaped
into the per-ticker dated series the momentum engine consumes.

WHAT THIS IS: a MECHANICAL group-by-ticker. For each requested ticker (the Pass1-eligible set + the SPY/QQQ
benchmarks) it collects that ticker's (date, close, volume) across the ascending grouped sessions into
`{as_of, session, adjustment_mode, points:[{date, close, volume}]}` — exactly the shape
engine/us_short_momentum.py::_parse_dated_series accepts.

WHAT THIS IS NOT: NO PIT cut, NO return/percentile math, NO close/volume cleaning, NO scoring — the momentum
engine owns ALL of that (`_parse_dated_series` PIT-cuts future points + `_clean_series` rejects non-positive/
non-finite closes + enforces the MIN_HISTORY floor; a thin/bad series → empty features → honest disposition).
This module therefore MUST NOT reimplement any of it — it passes raw closes/volumes straight through so the
engine remains the single PIT authority (memory: per-engine copies must mirror the reference safety semantics;
here we reuse the reference instead of copying). A ticker missing from a session → that date is OMITTED (a
gap, never zero-filled); eligible tickers passed the ADV liquidity gate so they trade every session (no gaps),
while a thin non-eligible name simply yields too few points and the engine dispositions it. Pure/offline; no
provider/live/network; no A-share crossing.
"""
from __future__ import annotations

import re
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MomentumGroupedReconstructError(ValueError):
    """A grouped-daily window cannot be reshaped into per-ticker momentum series safely."""


def _require_nonempty_str(value: Any, *, field: str) -> str:
    if type(value) is not str or not value:
        raise MomentumGroupedReconstructError(f"{field} must be a non-empty string")
    return value


def _reconstruct_from_grouped(
    grouped_sessions: Any,
    *,
    tickers: Any,
    as_of: str,
    session: str,
    adjustment_mode: str,
    point_builder,
) -> dict[str, dict[str, Any]]:
    """Shared MECHANICAL group-by-ticker for both reconstruct shapes (single-source safety).

    Validates the clock + ticker set, walks the ascending grouped window (STRICTLY ascending + unique by date;
    dedup per session; filter to the wanted canonical set), and delegates the per-row point fields to
    `point_builder(row) -> dict | None` (None omits the point as a gap, never zero-filled). `date` is added by the
    walk. Raw values pass through unvalidated by design — the consuming engine (`_parse_dated_series` /
    `_parse_ohlcv_series`) is the single PIT/clean authority. A requested ticker in NO session is absent from the
    result (the producer dispositions it). A corrupt/duplicated session axis or a duplicate ticker within a
    session fails closed."""
    _require_nonempty_str(as_of, field="as_of")
    if not _DATE_RE.match(as_of):
        raise MomentumGroupedReconstructError("as_of must be YYYY-MM-DD")
    _require_nonempty_str(session, field="session")
    _require_nonempty_str(adjustment_mode, field="adjustment_mode")

    if type(tickers) not in (list, tuple, set, frozenset):
        raise MomentumGroupedReconstructError("tickers must be a list/tuple/set")
    wanted: set[str] = set()
    for raw in tickers:
        ct = canonical_us_ticker(raw)
        if ct is None:
            raise MomentumGroupedReconstructError("tickers must all be canonicalizable US tickers")
        wanted.add(ct)

    if type(grouped_sessions) is not list:
        raise MomentumGroupedReconstructError("grouped_sessions must be a list")

    points_by_ticker: dict[str, list[dict[str, Any]]] = {}
    prev_date: str | None = None
    for session_obj in grouped_sessions:
        if type(session_obj) is not dict:
            raise MomentumGroupedReconstructError("each grouped session must be a dict")
        date = session_obj.get("date")
        if type(date) is not str or not _DATE_RE.match(date):
            raise MomentumGroupedReconstructError("each grouped session date must be YYYY-MM-DD")
        if prev_date is not None and date <= prev_date:
            raise MomentumGroupedReconstructError("grouped session dates must be strictly ascending + unique")
        prev_date = date
        rows = session_obj.get("rows")
        if type(rows) is not list:
            raise MomentumGroupedReconstructError("each grouped session must carry a list of rows")
        seen_this_session: set[str] = set()
        for row in rows:
            if type(row) is not dict:
                raise MomentumGroupedReconstructError("each grouped row must be a dict")
            ct = canonical_us_ticker(row.get("ticker"))
            if ct is None or ct not in wanted:
                continue
            if ct in seen_this_session:
                raise MomentumGroupedReconstructError(f"duplicate ticker {ct} within grouped session {date}")
            seen_this_session.add(ct)
            fields = point_builder(row)
            if fields is None:
                continue   # a gap (missing a required field for this ticker on this date) → omit, never zero-fill
            points_by_ticker.setdefault(ct, []).append({"date": date, **fields})

    return {
        ticker: {
            "as_of": as_of,
            "session": session,
            "adjustment_mode": adjustment_mode,
            "points": points,
        }
        for ticker, points in points_by_ticker.items()
    }


def _momentum_point_fields(row: dict[str, Any]) -> dict[str, Any] | None:
    if "close" not in row or row["close"] is None:
        return None   # No close for this ticker on this date → a gap.
    fields: dict[str, Any] = {"close": row["close"]}
    if "volume" in row and row["volume"] is not None:
        fields["volume"] = row["volume"]
    return fields


def reconstruct_series_from_grouped(
    grouped_sessions: Any,
    *,
    tickers: Any,
    as_of: str,
    session: str,
    adjustment_mode: str,
) -> dict[str, dict[str, Any]]:
    """Reshape an ascending grouped-daily window into per-ticker `{date,close,volume?}` series for the momentum
    engine (§4.2). See `_reconstruct_from_grouped` for the shared walk / fail-closed envelope; raw close/volume
    pass through (the momentum engine is the single PIT/clean authority)."""
    return _reconstruct_from_grouped(
        grouped_sessions, tickers=tickers, as_of=as_of, session=session,
        adjustment_mode=adjustment_mode, point_builder=_momentum_point_fields)


def _ohlcv_point_fields(row: dict[str, Any]) -> dict[str, Any] | None:
    # Need high/low/close ALL present to form a valid §4.3 OHLCV bar (ATR needs high/low); any missing → a gap,
    # omit (never zero-fill). Raw values pass through — engine/us_short_overextension.py::_parse_ohlcv_series owns
    # finiteness / positivity / high>=low cleaning + the PIT cut.
    if row.get("close") is None or row.get("high") is None or row.get("low") is None:
        return None
    fields: dict[str, Any] = {"high": row["high"], "low": row["low"], "close": row["close"]}
    if "volume" in row and row["volume"] is not None:
        fields["volume"] = row["volume"]
    return fields


def reconstruct_ohlcv_series_from_grouped(
    grouped_sessions: Any,
    *,
    tickers: Any,
    as_of: str,
    session: str,
    adjustment_mode: str,
) -> dict[str, dict[str, Any]]:
    """Reshape an ascending grouped-daily window into per-ticker `{date,high,low,close,volume?}` OHLCV series for
    the §4.3 overextension producer (cut 2b-iii). Identical MECHANICAL group-by as the momentum reconstruct but
    RETAINS high/low (ATR needs them); raw values pass through (the overextension engine is the single PIT/clean
    authority). A row missing high/low/close on a date → that date is a gap (omitted)."""
    return _reconstruct_from_grouped(
        grouped_sessions, tickers=tickers, as_of=as_of, session=session,
        adjustment_mode=adjustment_mode, point_builder=_ohlcv_point_fields)
