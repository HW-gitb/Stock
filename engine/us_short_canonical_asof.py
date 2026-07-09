# -*- coding: utf-8 -*-
"""US-short weekend-pipeline canonical decision-day (decision_date) resolver — batch4 slice 4a.

Design authority: docs/us_short_system_design.md §2.1 (canonical 决策日两边窗口 / 盘中死区 /
价格基准 / 幂等 / live-historical) + §3.5 (NYSE/NASDAQ 市场日历 / timezone). This module ONLY
implements; it does NOT restate those semantics (single semantic authority = §2.1 / §3.5).

Mirrors the A-share engineering skeleton (runners/resolve_canonical_asof.py): a pure,
injection-tested, canonical-ONLY resolver — it never classifies an explicit historical as_of
(that stays with the caller, so there is no drifting second predicate). US divergence from
A-share: A-share has a SINGLE close cutoff and ALWAYS resolves a canonical; US has TWO session
edges (open 09:30 / close 16:00 ET; half-day close 13:00 ET) and an intraday DEAD ZONE that
fails closed (OutOfWindowError) so the orchestrator emits nothing.

Pure / offline: resolves dates only — never selects stocks, fetches data, places orders, or
touches a provider. The session calendar is INJECTED (batch4 slice 4b static frozen NYSE
calendar will supply it); the Beijing->ET conversion lives in a thin runner (later slice), so
this pure function only ever sees ET wall-clock. No A-share crossing.
"""
from __future__ import annotations

from datetime import datetime, time

# Frozen RTH defaults (ET wall-clock; DST-invariant — DST is handled by the Beijing->ET
# conversion in the thin runner, not here). A session may override `close` for a half-day
# (early close 13:00 ET); `open` is 09:30 ET for regular and half-day sessions alike.
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)

# Session scope is RTH-only by design (§2.1 targets the RTH open; engine/us_short_price_clock.py
# pins session_scope == "RTH"). Hardcoded (NOT a public parameter) so the resolver and the price
# clock can never disagree — there is no extended-hours / non-RTH decision path in v1.
SESSION_SCOPE = "RTH"


class OutOfWindowError(Exception):
    """Intraday dead zone (§2.1): now_et falls inside some trading session's [open, close).

    Fail-closed — no canonical decision_date is resolved. Per §2.1 the run can neither decide
    FOR the current session (its RTH entry window has already opened) nor for the NEXT session
    (the current session has not closed, so the next session's price basis is not yet settled).
    The orchestrator catches this and emits nothing (no packet / no forward evidence).
    """


def _strict_hhmm(s):
    """'HH:MM' (zero-padded, ASCII) -> datetime.time. Strict: reject anything else."""
    if not (isinstance(s, str) and len(s) == 5 and s.isascii() and s[2] == ":"):
        raise ValueError(f"非法 HH:MM 时刻（须零填充 ASCII 'HH:MM'）: {s!r}")
    hh, mm = s[:2], s[3:]
    if not (hh.isdigit() and mm.isdigit()):
        raise ValueError(f"非法 HH:MM 时刻: {s!r}")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"HH:MM 越界: {s!r}")
    return time(h, m)


def _strict_yyyymmdd(s):
    """'YYYYMMDD' (8 ASCII digits AND a real calendar date) -> the validated string.

    Shape check (len/ascii/digit) THEN a real-date check via strptime, so a shape-valid but
    impossible date ('20260631' = June 31, '20260229' = non-leap Feb 29, month/day 00) is
    REJECTED rather than laundered into decision_date / price_basis_date. The resolver is the
    consumer-validation edge for the injected calendar (§2.1), so it fails closed on a bad row
    even though slice 4b is expected to supply clean dates. Lexicographic order == chronological.
    """
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        raise ValueError(f"session.date 须为 8 位 ASCII YYYYMMDD: {s!r}")
    try:
        datetime.strptime(s, "%Y%m%d")
    except ValueError:
        raise ValueError(f"session.date 非真实日历日（不存在的年/月/日）: {s!r}")
    return s


def _session_bounds(sess):
    """Injected session dict -> (date:str, open:time, close:time).

    {"date":"YYYYMMDD", "open"?:"HH:MM", "close"?:"HH:MM"} (ET). open default 09:30, close
    default 16:00; a half-day sets close="13:00". Strict: open must be < close.
    """
    if not isinstance(sess, dict):
        raise ValueError(f"session 须为 dict: {sess!r}")
    date = _strict_yyyymmdd(sess.get("date"))
    open_raw = sess.get("open")
    close_raw = sess.get("close")
    open_t = _strict_hhmm(open_raw) if open_raw is not None else RTH_OPEN
    close_t = _strict_hhmm(close_raw) if close_raw is not None else RTH_CLOSE
    if not (open_t < close_t):
        raise ValueError(f"session open 须严格早于 close: {sess!r}")
    return date, open_t, close_t


def resolve_canonical_asof(now_et, sessions):
    """now_et (ET wall-clock) + sessions (injected) -> canonical decision-day.

    See the module docstring; semantics = §2.1 / §3.5 (not restated here).

    now_et:   datetime treated as ET wall-clock (the caller converts Beijing->ET). This fn
              never fetches the clock and uses only .time()/.strftime, so passing a datetime in
              a NON-ET timezone would be MIS-read — the contract requires ET wall-clock.
    sessions: iterable of {"date":"YYYYMMDD", "open"?:"HH:MM", "close"?:"HH:MM"} (ET; open
              default 09:30, close default 16:00; a half-day sets close="13:00"). Order-free
              ONLY when dates are unique (sorted internally); a duplicate session date raises
              ValueError (no order-dependent last-wins).

    Returns dict {decision_date, price_basis_date, run_date, run_datetime_et, session_scope,
              window_state="live"}. Deterministic: same (now_et, sessions) -> same output; and
              every now_et inside ONE legal window (prior close -> target open) converges to the
              SAME decision_date + price_basis_date (downstream forward-evidence dedup and
              private dirs key on decision_date, so window-internal re-runs never inflate forward
              evidence). canonical decision_date >= run_date, hence window_state is always "live"
              (explicit historical as_of classification is intentionally NOT this fn's job, §2.1).
    Raises:   OutOfWindowError if now_et is inside a session's [open, close) (intraday dead zone);
              ValueError if sessions are empty / malformed (bad shape, impossible calendar date,
              duplicate session date, or open>=close), or the injected window covers no upcoming
              (price-decision) session or no settled (price-basis) session.
    session_scope is always "RTH" (SESSION_SCOPE, hardcoded — not a caller parameter, §2.1).
    """
    if not isinstance(now_et, datetime) or now_et.tzinfo is not None:
        raise ValueError("now_et 须为无时区 datetime（ET 墙钟；tz-aware 拒收，防跨端 PIT 时钟混淆）")
    run_date = now_et.strftime("%Y%m%d")
    now_t = now_et.time()

    parsed = {}
    for sess in sessions:
        date, open_t, close_t = _session_bounds(sess)
        if date in parsed:  # reject duplicates (no order-dependent last-wins, §2.1 consumer-validation)
            raise ValueError(
                f"重复 session date（日历每日至多一行；拒绝顺序相关的 last-wins）: {date!r}")
        parsed[date] = (open_t, close_t)
    if not parsed:
        raise ValueError("sessions 为空；无法解析 canonical decision_date（请扩大日历窗口）")

    settled = []   # close already passed at now_et (eligible price basis)
    upcoming = []  # not yet open at now_et (eligible decision target)
    for date in sorted(parsed):
        open_t, close_t = parsed[date]
        if date < run_date:
            settled.append(date)
        elif date > run_date:
            upcoming.append(date)
        else:  # date == run_date: only TODAY's session can be intraday -> split by time-of-day
            if now_t >= close_t:
                settled.append(date)
            elif now_t < open_t:
                upcoming.append(date)
            else:  # open <= now_t < close -> intraday dead zone, fail-closed (precedence)
                raise OutOfWindowError(
                    f"now_et={now_et.isoformat()} 落在交易日 {date} 盘中 "
                    f"[{open_t.strftime('%H:%M')}-{close_t.strftime('%H:%M')}) "
                    f"→ out-of-window，fail-closed、不解析 canonical")

    if not upcoming:
        raise ValueError("sessions 未覆盖任何「尚未开盘」的交易日（请扩大日历窗口 fwd 侧）")
    if not settled:
        raise ValueError("sessions 未覆盖任何「已收盘」的交易日（价格基准缺失，请扩大日历窗口 back 侧）")

    return {
        "decision_date": upcoming[0],     # earliest upcoming = 即将到来/未开盘的交易日
        "price_basis_date": settled[-1],  # latest settled = 前一已收盘交易日（§2.1 价格基准）
        "run_date": run_date,
        "run_datetime_et": now_et.isoformat(),
        "session_scope": SESSION_SCOPE,
        "window_state": "live",           # canonical decision_date >= run_date -> 恒 live（§2.1）
    }
