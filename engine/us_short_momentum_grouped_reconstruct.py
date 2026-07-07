# -*- coding: utf-8 -*-
"""US-short full-universe momentum: reconstruct per-ticker dated series from a grouped-daily window (pure).

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


def reconstruct_series_from_grouped(
    grouped_sessions: Any,
    *,
    tickers: Any,
    as_of: str,
    session: str,
    adjustment_mode: str,
) -> dict[str, dict[str, Any]]:
    """Reshape an ascending grouped-daily window into per-ticker dated series for the momentum engine.

    grouped_sessions: list of {"date": "YYYY-MM-DD", "rows": [{"ticker": str, "close": num, "volume": num?}]},
        STRICTLY ascending + unique by date (a corrupt/duplicated session axis fails closed).
    tickers: the requested identity set (Pass1-eligible + SPY/QQQ); canonicalized before matching.
    Returns {canonical_ticker: {"as_of", "session", "adjustment_mode", "points": [{"date","close","volume"?}]}}
        for every requested ticker that appears in >=1 session (a ticker in NO session is simply absent from
        the result → the producer dispositions it as absent_from_pool). Raw close/volume pass through unvalidated
        by design; the momentum engine is the single PIT/clean authority.
    """
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
            if "close" not in row or row["close"] is None:
                # No close for this ticker on this date → a gap; omit the point (never zero-fill).
                continue
            point: dict[str, Any] = {"date": date, "close": row["close"]}
            if "volume" in row and row["volume"] is not None:
                point["volume"] = row["volume"]
            points_by_ticker.setdefault(ct, []).append(point)

    return {
        ticker: {
            "as_of": as_of,
            "session": session,
            "adjustment_mode": adjustment_mode,
            "points": points,
        }
        for ticker, points in points_by_ticker.items()
    }
