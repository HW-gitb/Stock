# -*- coding: utf-8 -*-
"""US-short static frozen NYSE/NASDAQ market calendar + session-builder — batch4 slice 4b.

Design authority: docs/us_short_system_design.md §2.1 / §3.5 / §18.2 batch4 (D2: a static frozen
NYSE calendar artifact + a thin session-builder, offline / auditable / deterministic — NOT a
rule generator, NOT a provider). This module ONLY builds the `sessions` list that
engine/us_short_canonical_asof.py::resolve_canonical_asof consumes; it does not resolve dates,
select stocks, fetch data, or touch a provider.

The calendar DATA (holidays / early-closes) lives in a frozen preset
(presets/us_short_market_calendar_*.json), is rules-derived OFFLINE, and is gated on authoritative
cross-check (`data_provenance.verification_status`) before any live/forward use (batch5,
SR-PROVIDER-001). The builder LOGIC here is pure and fully unit-tested against injected fixture
calendars. No A-share crossing.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

REGULAR_OPEN = "09:30"
REGULAR_CLOSE = "16:00"
HALF_DAY_CLOSE = "13:00"   # NYSE/NASDAQ early-close is ALWAYS 13:00 ET (§3.5 contract); pinned, not arbitrary.
_VERIFICATION_STATUSES = ("pending_authoritative_cross_check", "authoritative_verified")
_REQUIRED_KEYS = {
    "calendar", "timezone", "start_date", "end_date",
    "regular_open", "regular_close", "holidays", "half_days", "data_provenance",
}


class MarketCalendarError(Exception):
    """A frozen market-calendar artifact is malformed / internally inconsistent (fail-closed)."""


def _real_yyyymmdd(s):
    """'YYYYMMDD' (8 ASCII digits AND a real calendar date) -> the validated string."""
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        raise MarketCalendarError(f"日期须为 8 位 ASCII YYYYMMDD: {s!r}")
    try:
        datetime.strptime(s, "%Y%m%d")
    except ValueError:
        raise MarketCalendarError(f"非真实日历日: {s!r}")
    return s


def _is_weekday(d):
    """True iff a validated YYYYMMDD falls Mon-Fri (the builder only emits weekday sessions)."""
    return datetime.strptime(d, "%Y%m%d").weekday() < 5


def validate_market_calendar(cal):
    """Fail-closed structural + cross-field validation of a loaded calendar dict.

    Runtime gate (does NOT rely on the JSON schema, which a separate schema-conformance test pins
    and which is unavailable at runtime where jsonschema may be absent): an EXACT top-level key set
    (closed-world — required keys present AND no unknown fields, mirroring schema
    additionalProperties:false), real-date holidays /
    early-closes, start<=end, every holiday/early-close inside [start_date, end_date] AND on a WEEKDAY
    (a weekend holiday/half-day row is a builder no-op — observed closures must be encoded on the
    OBSERVED weekday, e.g. Sat Jul-4 → Fri Jul-3), no date is
    BOTH a holiday and an early-close (an observed full close is not also a half-day), each
    early-close pinned to EXACTLY 13:00 (§3.5 NYSE/NASDAQ contract — not an arbitrary early time;
    rejects 09:30 open==close, 15:59, 14:00, …), and a well-formed `data_provenance` (object with
    EXACTLY source/verification_status/note, non-empty source+note, allowed verification_status —
    so the `pending_authoritative_cross_check` honesty gate cannot be laundered away by a
    `trust_me` / missing / non-object provenance). Returns the dict on success; raises
    MarketCalendarError otherwise.
    """
    if not isinstance(cal, dict):
        raise MarketCalendarError("calendar 须为 dict")
    missing = _REQUIRED_KEYS - set(cal)
    if missing:
        raise MarketCalendarError(f"calendar 缺字段: {sorted(missing)}")
    extra = set(cal) - _REQUIRED_KEYS
    if extra:
        raise MarketCalendarError(
            f"calendar 含未知顶层字段（closed-world，对齐 schema additionalProperties:false；builder 静默忽略未知字段）: {sorted(extra)}")
    if cal["calendar"] != "NYSE_NASDAQ" or cal["timezone"] != "America/New_York":
        raise MarketCalendarError("calendar/timezone 非 NYSE_NASDAQ / America/New_York")
    if cal["regular_open"] != REGULAR_OPEN or cal["regular_close"] != REGULAR_CLOSE:
        raise MarketCalendarError("regular_open/close 须为 09:30 / 16:00")
    start = _real_yyyymmdd(cal["start_date"])
    end = _real_yyyymmdd(cal["end_date"])
    if not (start <= end):
        raise MarketCalendarError(f"start_date 须 <= end_date: {start}..{end}")

    holidays = cal["holidays"]
    if not isinstance(holidays, list):
        raise MarketCalendarError("holidays 须为 list")
    hset = set()
    for h in holidays:
        d = _real_yyyymmdd(h)
        if not _is_weekday(d):
            raise MarketCalendarError(
                f"holiday 落在周末（非交易日、builder 静默忽略；观察日须编码为 OBSERVED 交易日，如 Sat Jul-4 → Fri Jul-3）: {d}")
        if not (start <= d <= end):
            raise MarketCalendarError(f"holiday 越出日历范围: {d}")
        if d in hset:
            raise MarketCalendarError(f"重复 holiday: {d}")
        hset.add(d)

    half_days = cal["half_days"]
    if not isinstance(half_days, dict):
        raise MarketCalendarError("half_days 须为 dict")
    for d_raw, close_raw in half_days.items():
        d = _real_yyyymmdd(d_raw)
        if not _is_weekday(d):
            raise MarketCalendarError(f"early-close 落在周末（非交易日、builder 静默忽略）: {d}")
        if close_raw != HALF_DAY_CLOSE:
            raise MarketCalendarError(
                f"early-close 须恰为 {HALF_DAY_CLOSE}（NYSE/NASDAQ 半日市固定 13:00 ET，§3.5 契约；"
                f"如需其它收盘须先改 owner 设计契约 + README，再放宽此门）: {d}={close_raw!r}")
        if not (start <= d <= end):
            raise MarketCalendarError(f"early-close 越出日历范围: {d}")
        if d in hset:
            raise MarketCalendarError(f"日期既是 holiday 又是 early-close（观察日全休不应再设半日市）: {d}")

    prov = cal["data_provenance"]
    if not isinstance(prov, dict):
        raise MarketCalendarError("data_provenance 须为 object")
    if set(prov) != {"source", "verification_status", "note"}:
        raise MarketCalendarError(f"data_provenance 键须恰为 source/verification_status/note: {sorted(prov)}")
    if not (isinstance(prov["source"], str) and prov["source"].strip()):
        raise MarketCalendarError("data_provenance.source 须为非空字符串")
    if prov["verification_status"] not in _VERIFICATION_STATUSES:
        raise MarketCalendarError(
            f"data_provenance.verification_status 非法（须 ∈ {_VERIFICATION_STATUSES}）: {prov.get('verification_status')!r}")
    if not (isinstance(prov["note"], str) and prov["note"].strip()):
        raise MarketCalendarError("data_provenance.note 须为非空字符串")
    return cal


def load_market_calendar(path):
    """Load + fail-closed-validate a frozen market-calendar artifact (offline; no network)."""
    with open(Path(path), encoding="utf-8") as f:
        cal = json.load(f)
    return validate_market_calendar(cal)


def build_sessions(start_date, end_date, *, calendar):
    """Frozen calendar + [start_date, end_date] window -> sessions list for resolve_canonical_asof.

    Emits one {"date","open","close"} per WEEKDAY (Mon-Fri) in the inclusive window that is NOT a
    holiday; `close` is the early-close time for an early-close date else the regular close. The
    window MUST lie inside the calendar's frozen [start_date, end_date] (else ValueError — the
    resolver must never receive sessions outside the verified frozen range). Deterministic, pure.
    """
    cal = validate_market_calendar(calendar)
    s = _real_yyyymmdd(start_date)
    e = _real_yyyymmdd(end_date)
    if not (s <= e):
        raise ValueError(f"窗口 start 须 <= end: {s}..{e}")
    if not (cal["start_date"] <= s and e <= cal["end_date"]):
        raise ValueError(
            f"窗口 [{s},{e}] 超出冻结日历范围 [{cal['start_date']},{cal['end_date']}]"
            f"（请扩表并重新权威核对，勿用范围外推断）")
    holidays = set(cal["holidays"])
    half_days = cal["half_days"]
    out = []
    d = datetime.strptime(s, "%Y%m%d").date()
    end = datetime.strptime(e, "%Y%m%d").date()
    while d <= end:
        ds = d.strftime("%Y%m%d")
        if d.weekday() < 5 and ds not in holidays:  # 0-4 = Mon-Fri
            out.append({"date": ds, "open": REGULAR_OPEN, "close": half_days.get(ds, REGULAR_CLOSE)})
        d += timedelta(days=1)
    return out


def sessions_for_window(center_date, *, calendar, back_days=15, fwd_days=15):
    """Convenience: sessions spanning [center-back_days, center+fwd_days] (calendar days), clamped
    to the frozen calendar range. ±15 calendar days covers weekends + a holiday on either side, so
    the resolver always sees a settled (price-basis) and an upcoming (decision) session. The
    Beijing->ET conversion that produces a real `center_date` lives in the thin runner (slice 4d)."""
    c = datetime.strptime(_real_yyyymmdd(center_date), "%Y%m%d").date()
    cal = validate_market_calendar(calendar)
    lo = max((c - timedelta(days=back_days)).strftime("%Y%m%d"), cal["start_date"])
    hi = min((c + timedelta(days=fwd_days)).strftime("%Y%m%d"), cal["end_date"])
    return build_sessions(lo, hi, calendar=cal)
