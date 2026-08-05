"""Canonical CSI300 window semantics shared by live EGS and lookbacks.

The live EGS passes a 65-session trade-date list to ``get_csi300_return``.
The ``20`` check in that function is only the minimum-length guard for its
calendar-day fallback; it is not the live window size.  Keep both facts here
so historical comparison code cannot silently invent a different window.
"""

from __future__ import annotations

import re
from typing import Any


CSI300_MIN_TRADE_DATE_SESSIONS = 20
CSI300_LIVE_WINDOW_SESSIONS = 65
CSI300_FALLBACK_CALENDAR_DAYS = 35
_DATE8 = re.compile(r"^[0-9]{8}$")


def csi300_window_spec(
    trade_dates: Any,
    *,
    fallback_start_date: str,
) -> dict[str, Any]:
    """Return the exact live request/metadata window for ``trade_dates``.

    The production path uses the complete supplied session span once the
    minimum guard is met.  Short input uses the existing 35-calendar-day
    fallback.  Invalid input is returned as an empty spec for metadata
    callers; the live caller still preserves its existing indexing behavior.
    """
    dates = tuple(str(value).strip() for value in (trade_dates or ()))
    if not dates or any(not _DATE8.fullmatch(value) for value in dates):
        return {
            "start_date": None,
            "end_date": None,
            "length": None,
            "length_unit": None,
        }
    if len(dates) >= CSI300_MIN_TRADE_DATE_SESSIONS:
        return {
            "start_date": dates[-1],
            "end_date": dates[0],
            "length": len(dates),
            "length_unit": "trading_sessions",
        }
    return {
        "start_date": str(fallback_start_date),
        "end_date": dates[0],
        "length": CSI300_FALLBACK_CALENDAR_DAYS,
        "length_unit": "calendar_days",
    }
