"""Single source of truth for A-share business time."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


A_SHARE_MARKET_TZ = ZoneInfo("Asia/Shanghai")


def a_share_market_now(now: datetime | None = None) -> datetime:
    """Return a timezone-aware instant in the Shanghai market timezone."""
    if now is None:
        return datetime.now(A_SHARE_MARKET_TZ)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("A-share market clock requires a timezone-aware datetime")
    return now.astimezone(A_SHARE_MARKET_TZ)


def a_share_market_wall_time(now: datetime | None = None) -> datetime:
    """Return Shanghai wall time for legacy pure functions that compare clock times."""
    return a_share_market_now(now).replace(tzinfo=None)


def a_share_market_date(now: datetime | None = None) -> str:
    """Return the Shanghai market date in canonical YYYYMMDD form."""
    return a_share_market_now(now).strftime("%Y%m%d")
