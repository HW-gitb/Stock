# ============================================================================================
# FROZEN byte-exact copy of engine/a_short_regime_features.py at the pre-performance-optimization
# revision (commit 5b20f09c). DO NOT EDIT and DO NOT import from production code.
#
# Sole purpose: the perf optimization of `compute_regime_daily_features` (group-by-trade_date once
# instead of re-scanning the full daily/stk_limit panel per window-day) MUST be byte-for-byte output
# preserving. `tests/test_a_short_regime_features.py` runs THIS original implementation and the new
# optimized one over the same panels across many as_of and asserts every emitted row is identical.
# If you change the engine's regime semantics on purpose, regenerate this file from the new engine
# in the SAME commit so the equality test pins "optimized == intended", never a stale contract.
# ============================================================================================
"""A-short V14.3 regime daily-feature computation (slice 2b-impl ①, pure logic, comparison-only).

Computes ONE ``a_short_market_regime_daily`` row for an ``as_of`` from in-memory panels, faithful to
the slice-1 governance metric definitions (PIT, unadjusted ``daily`` + ``stk_limit`` same-caliber
prices respecting ±10% / ±20% / ST ±5% via each stock's own up/down limit). It is the producer the
slice-2b ledger persists; kept pure (takes DataFrames, returns a dict) so it is fully unit-testable
without any Tushare fetch.

Boundary (hard): **comparison-only, non-production.** No data fetch, no EGS wiring, no file write, no
Phase 5 / veto / sizing. The fetch + ledger append + panel block + bootstrap runner are slice 2b-②.

Inputs (all PIT, restricted to dates ``<= as_of`` internally — never look-ahead):
- ``daily``: rows for ALL stocks over a trailing window, columns ``ts_code, trade_date, high, close``
  (others ignored). >= 20 trading days needed for pct_above_ma20; a few for streak/promotion.
- ``stk_limit``: ``ts_code, trade_date, up_limit, down_limit`` (per-stock caliber). Missing/unusable
  limit (or daily price) for an as_of traded stock FAILS CLOSED (raises) — non-null count fields
  can't encode "unknown"; prior-window gaps degrade via flags. See compute() for the full contract.
- ``csi300`` / ``csi1000``: index ``trade_date, close`` (>= 20 days for csi1000 MA20).
- ``iv_percentile_252d``: float or None, sourced from the batch-① IV feed (NOT recomputed here).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from engine.a_short_regime_ledger import is_canonical_date, daily_row_semantic_errors

LIMIT_TOL = 0.999                 # close >= up_limit*0.999 counts as limit-up (caliber tolerance)
MA_WINDOW = 20                    # pct_above_ma20 / csi1000_below_ma20 window
MIN_PROMOTION_DENOM = 5           # promotion_rate denom floor; below → null + insufficient_sample
                                  # (governance says "denom too small → insufficient_sample, never
                                  #  hard-judge attack"; the exact floor is a slice-2b-impl constant
                                  #  to be pinned into governance if it ever feeds production)


def _num(s) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _trade_dates(daily: pd.DataFrame, as_of: str) -> list[str]:
    """Ascending unique trade dates ``<= as_of`` present in ``daily`` (PIT cap)."""
    if daily is None or daily.empty or "trade_date" not in daily.columns:
        return []
    ds = {str(d) for d in daily["trade_date"] if str(d) <= str(as_of)}
    return sorted(ds)


def _limit_sets(daily_day: pd.DataFrame, limit_day: pd.DataFrame) -> dict:
    """Limit sets for one day. Returns dict of ts_code sets: up, down, touched_up, failed_up.

    Empty/missing ``limit_day`` → all empty. (Coverage is enforced by the caller's usable-price+limit
    gate: missing/unusable as_of data fails closed, prior-window gaps set
    ``stk_limit_history_incomplete``.) Uses each stock's own up_limit/down_limit so ±10/±20/ST±5
    calibers are respected automatically.
    """
    empty = {"up": set(), "down": set(), "touched_up": set(), "failed_up": set(), "have_limit": False}
    if daily_day is None or daily_day.empty or limit_day is None or limit_day.empty:
        return empty
    m = daily_day.merge(limit_day[["ts_code", "up_limit", "down_limit"]], on="ts_code", how="inner")
    if m.empty:
        return empty
    close = _num(m["close"]); high = _num(m["high"])
    up_lim = _num(m["up_limit"]); down_lim = _num(m["down_limit"])
    ok = close.notna() & up_lim.notna() & up_lim.gt(0)
    up = m["ts_code"][ok & (close >= up_lim * LIMIT_TOL)]
    touched = m["ts_code"][ok & high.notna() & (high >= up_lim * LIMIT_TOL)]
    failed = m["ts_code"][ok & high.notna() & (high >= up_lim * LIMIT_TOL) & (close < up_lim * LIMIT_TOL)]
    ok_d = close.notna() & down_lim.notna() & down_lim.gt(0)
    down = m["ts_code"][ok_d & (close <= down_lim * (2 - LIMIT_TOL))]
    return {"up": set(up), "down": set(down), "touched_up": set(touched),
            "failed_up": set(failed), "have_limit": True}


def _usable_limit_codes(limit_day: pd.DataFrame) -> set:
    """ts_codes on a day with a USABLE limit row = finite positive up_limit AND down_limit.

    Row presence is not enough: NaN / nonnumeric / zero / negative up/down are unusable (they
    contribute nothing to detection and must not be counted as coverage)."""
    if limit_day is None or limit_day.empty:
        return set()
    up = _num(limit_day["up_limit"]); down = _num(limit_day["down_limit"])
    ok = np.isfinite(up) & (up > 0) & np.isfinite(down) & (down > 0)   # isfinite excludes NaN AND ±Inf
    return set(limit_day["ts_code"][ok])


def _usable_price_codes(daily_day: pd.DataFrame) -> set:
    """ts_codes on a day with a USABLE daily price row = finite positive close AND high, high>=close.

    A NaN/nonnumeric/zero/negative close or high, or an impossible high<close, is a broken price row
    that must not be counted as a real limit-up/down/no-limit observation."""
    if daily_day is None or daily_day.empty:
        return set()
    close = _num(daily_day["close"]); high = _num(daily_day["high"])
    ok = np.isfinite(close) & (close > 0) & np.isfinite(high) & (high > 0) & (high >= close)
    return set(daily_day["ts_code"][ok])


def _assert_canonical_panel_dates(df: pd.DataFrame, name: str) -> None:
    """Reject non-canonical YYYYMMDD ``trade_date`` so lexicographic PIT filters/sorts are sound."""
    if df is None or df.empty or "trade_date" not in df.columns:
        return
    bad = sorted({str(d) for d in df["trade_date"] if not is_canonical_date(str(d))})
    if bad:
        raise ValueError(f"{name}: non-canonical trade_date values {bad[:3]}")


def _assert_unique(df: pd.DataFrame, keys: list, name: str, as_of: str) -> None:
    """Reject duplicate ``keys`` among rows at/<= as_of (a dup can fabricate counts / index returns)."""
    if df is None or df.empty:
        return
    sub = df[df["trade_date"].astype(str) <= str(as_of)][keys].astype(str)
    if sub.duplicated().any():
        ex = sub[sub.duplicated(keep=False)].drop_duplicates().head(3).to_dict("records")
        raise ValueError(f"{name}: duplicate rows for {keys} at/<= as_of, e.g. {ex}")


def _max_limit_streak(up_sets: dict, dates: list[str]) -> int:
    """Max over stocks of consecutive limit-up days ending at the last date."""
    if not dates:
        return 0
    streak_by_code: dict[str, int] = {}
    best = 0
    # walk dates backward from the end; a stock's streak is unbroken consecutive membership
    alive = set(up_sets.get(dates[-1], set()))
    for code in alive:
        streak_by_code[code] = 0
    for d in reversed(dates):
        ups = up_sets.get(d, set())
        still = set()
        for code in alive:
            if code in ups:
                streak_by_code[code] += 1
                still.add(code)
        alive = still
        if not alive:
            break
    if streak_by_code:
        best = max(streak_by_code.values())
    return int(best)


def _pct_above_ma20(daily: pd.DataFrame, dates: list[str]) -> tuple:
    """(pct_above_ma20 or None, eligible_count). Eligible = stock with >= MA_WINDOW closes <= as_of."""
    if len(dates) < MA_WINDOW:
        return None, 0
    window = dates[-MA_WINDOW:]
    sub = daily[daily["trade_date"].astype(str).isin(window)][["ts_code", "trade_date", "close"]].copy()
    sub["close"] = _num(sub["close"])
    sub = sub.dropna(subset=["close"])
    g = sub.groupby("ts_code")
    above = 0; eligible = 0
    as_of = dates[-1]
    for code, grp in g:
        if grp["trade_date"].astype(str).nunique() < MA_WINDOW:
            continue
        today = grp[grp["trade_date"].astype(str) == as_of]
        if today.empty:
            continue
        eligible += 1
        if float(today["close"].iloc[0]) > float(grp["close"].mean()):
            above += 1
    if eligible == 0:
        return None, 0
    return round(above / eligible * 100, 6), eligible


def _index_ret_and_below(idx: pd.DataFrame, as_of: str) -> tuple:
    """(ret_1d_pct or None, below_ma20 or None) for an index panel, REQUIRING a current as_of row.

    Freshness: if the latest index row at/<= ``as_of`` is not exactly ``as_of`` (stale/missing index
    data), return ``(None, None)`` — never emit a stale return or a stale below_ma20 (which would
    fabricate/suppress the broad-index-crash / slow-bleed operands)."""
    if idx is None or idx.empty or "close" not in idx.columns:
        return None, None
    df = idx[idx["trade_date"].astype(str) <= str(as_of)].copy()
    df["close"] = _num(df["close"])
    df = df[np.isfinite(df["close"])].sort_values("trade_date")   # drop NaN AND ±Inf closes
    if df.empty or str(df["trade_date"].astype(str).iloc[-1]) != str(as_of):
        return None, None                              # stale/missing current-day index → unavailable
    if len(df) < 2:
        ret = None
    else:
        prev, last = float(df["close"].iloc[-2]), float(df["close"].iloc[-1])
        ret = round((last / prev - 1) * 100, 6) if prev else None
    below = None
    if len(df) >= MA_WINDOW:
        ma = float(df["close"].iloc[-MA_WINDOW:].mean())
        below = bool(float(df["close"].iloc[-1]) < ma)
    return ret, below


def compute_regime_daily_features(as_of: str, daily: pd.DataFrame, stk_limit: pd.DataFrame,
                                  csi300: pd.DataFrame, csi1000: pd.DataFrame,
                                  iv_percentile_252d: float | None = None) -> dict:
    """Compute one ``a_short_market_regime_daily`` row for ``as_of`` (comparison-only, PIT).

    Layered contract:
    - **Source-panel integrity (raises)**: every ``trade_date`` in ``daily``/``stk_limit``/``csi300``/
      ``csi1000`` must be canonical YYYYMMDD; ``daily``/``stk_limit`` must be unique per
      ``(trade_date, ts_code)`` and the indices unique per ``trade_date`` (at/<= as_of); ``as_of``
      itself must be canonical.
    - **Fail-closed on as_of (raises)**: the limit count fields are non-null integers that cannot
      honestly represent "unknown", so if ANY as_of traded stock lacks a usable daily price (finite
      positive close & high, high>=close) AND a usable ``stk_limit`` (finite positive up & down),
      this RAISES rather than fabricate zeros that would misread as a real observation (e.g.
      max_limit_streak=0 firing streak_collapse, or close=0 fabricating a limit-down). A real trading
      day always has complete usable data; an incomplete one is a fetch failure the runner resolves.
    - **Nullable / prior-window degrade via ``data_quality_flags``**: ``stk_limit_history_incomplete``
      (a PRIOR window day's price/limit is incomplete → promotion nulled, streak best-effort),
      ``insufficient_sample`` (thin promotion denom), ``ma20_insufficient_window``,
      ``csi300_unavailable`` / ``csi1000_unavailable`` (missing/stale index), ``iv_unavailable`` (IV
      None/NaN/Inf or outside [0,100]).

    The returned row passes ``a_short_market_regime_daily.schema.json`` AND
    ``engine.a_short_regime_ledger.daily_row_semantic_errors``.
    """
    as_of = str(as_of)
    if not is_canonical_date(as_of):
        raise ValueError(f"compute_regime_daily_features: as_of {as_of!r} is not a real YYYYMMDD date")
    flags: list[str] = []

    sl = stk_limit if stk_limit is not None else pd.DataFrame(columns=["ts_code", "trade_date", "up_limit", "down_limit"])

    # source-panel integrity (before any lexicographic PIT filter / metric): canonical dates so
    # ordering is sound, and one row per (date,stock)/(date) so a dup can't fabricate counts/returns.
    for df, nm in ((daily, "daily"), (sl, "stk_limit"), (csi300, "csi300"), (csi1000, "csi1000")):
        _assert_canonical_panel_dates(df, nm)
    _assert_unique(daily, ["trade_date", "ts_code"], "daily", as_of)
    _assert_unique(sl, ["trade_date", "ts_code"], "stk_limit", as_of)
    _assert_unique(csi300, ["trade_date"], "csi300", as_of)
    _assert_unique(csi1000, ["trade_date"], "csi1000", as_of)

    dates = _trade_dates(daily, as_of)
    if not dates or dates[-1] != as_of:
        raise ValueError(f"compute_regime_daily_features: daily has no rows for as_of {as_of}")

    def _daily_codes(day: str) -> set:
        return set(daily[daily["trade_date"].astype(str) == day]["ts_code"])

    def _usable_codes(day: str) -> set:
        """ts_codes on ``day`` with BOTH a usable daily price AND a usable limit row."""
        dd = daily[daily["trade_date"].astype(str) == day]
        ld = sl[sl["trade_date"].astype(str) == day]
        return _usable_price_codes(dd) & _usable_limit_codes(ld)

    def _incomplete(day: str) -> bool:
        """True if some daily-traded stock on ``day`` lacks a usable price+limit observation."""
        dcodes = _daily_codes(day)
        if not dcodes:
            return False
        return bool(dcodes - _usable_codes(day))

    # FAIL CLOSED on as_of: limit_up/down/net/streak/failed are non-null integer/ratio fields that
    # CANNOT honestly represent "unknown" — a fabricated 0 (from missing/unusable limit OR broken
    # daily price) misreads as a real observation (e.g. max_limit_streak=0 firing streak_collapse, or
    # close=0 fabricating a limit-down). A real A-share trading day always has complete usable price +
    # stk_limit; an incomplete one is a fetch failure the runner must resolve, so refuse to emit a
    # fabricated row rather than poison the evidence ledger.
    if _incomplete(as_of):
        dcodes = _daily_codes(as_of)
        raise ValueError(
            f"compute_regime_daily_features: as_of {as_of} has missing/unusable daily-price or "
            f"stk_limit data for {len(dcodes - _usable_codes(as_of))}/{len(dcodes)} traded stocks; "
            f"cannot compute limit breadth (re-fetch) — refusing to fabricate zeros")

    # per-day up-sets over the window (for streak + promotion); today's full sets for counts
    up_sets: dict[str, set] = {}
    for d in dates:
        dd = daily[daily["trade_date"].astype(str) == d]
        ld = sl[sl["trade_date"].astype(str) == d]
        up_sets[d] = _limit_sets(dd, ld)["up"]

    today_dd = daily[daily["trade_date"].astype(str) == as_of]
    today_ld = sl[sl["trade_date"].astype(str) == as_of]
    today = _limit_sets(today_dd, today_ld)   # as_of guaranteed fully usable by the fail-closed gate

    # prior window days (streak/promotion inputs) may still be incomplete — degrade, don't fail.
    history_incomplete = any(_incomplete(d) for d in dates[:-1])
    if history_incomplete:
        flags.append("stk_limit_history_incomplete")

    limit_up_count = len(today["up"])
    limit_down_count = len(today["down"])
    net_limit = limit_up_count - limit_down_count

    # failed_limit_rate = failed_up / touched_up; denom 0 → None
    touched = len(today["touched_up"])
    failed_limit_rate = round(len(today["failed_up"]) / touched, 6) if touched else None

    max_limit_streak = _max_limit_streak(up_sets, dates)

    # promotion_rate = (prev-day limit-up that limit-up again today) / prev-day limit-up count
    if len(dates) >= 2:
        prev_up = up_sets.get(dates[-2], set())
        denom = len(prev_up)
        if _incomplete(dates[-2]):
            promotion_rate = None          # prior-day denom from a subset → unreliable (history flag set)
        elif denom < MIN_PROMOTION_DENOM:
            promotion_rate = None
            flags.append("insufficient_sample")
        else:
            promotion_rate = round(len(prev_up & today["up"]) / denom, 6)
    else:
        promotion_rate = None
        flags.append("insufficient_sample")

    pct_above_ma20, _elig = _pct_above_ma20(daily, dates)
    if pct_above_ma20 is None:
        flags.append("ma20_insufficient_window")

    csi300_ret_1d, _ = _index_ret_and_below(csi300, as_of)
    if csi300_ret_1d is None:
        flags.append("csi300_unavailable")
    csi1000_ret_1d, csi1000_below_ma20 = _index_ret_and_below(csi1000, as_of)
    if csi1000_ret_1d is None or csi1000_below_ma20 is None:
        flags.append("csi1000_unavailable")

    iv = None
    if iv_percentile_252d is not None and isinstance(iv_percentile_252d, (int, float)) \
            and math.isfinite(float(iv_percentile_252d)) and 0.0 <= float(iv_percentile_252d) <= 100.0:
        iv = round(float(iv_percentile_252d), 6)
    else:
        flags.append("iv_unavailable")   # None / NaN / Inf / out-of-[0,100] → unavailable

    row = {
        "schema_name": "a_short_market_regime_daily",
        "schema_version": "1.0.0",
        "as_of": as_of,
        "limit_up_count": int(limit_up_count),
        "limit_down_count": int(limit_down_count),
        "net_limit": int(net_limit),
        "max_limit_streak": int(max_limit_streak),
        "promotion_rate": promotion_rate,
        "failed_limit_rate": failed_limit_rate,
        "iv_percentile_252d": iv,
        "csi300_ret_1d": csi300_ret_1d,
        "csi1000_ret_1d": csi1000_ret_1d,
        "pct_above_ma20": pct_above_ma20,
        "csi1000_below_ma20": csi1000_below_ma20,
        "data_quality_flags": sorted(set(flags)),
        "boundary": {"production": False, "comparison_only": True,
                     "drives_phase5_risk_posture": False},
    }
    # self-check the advertised contract: a returned row MUST pass the ledger semantic validator
    # (finite floats, net_limit==up−down, canonical date). A non-empty result is a producer bug, not
    # a degradable state, so raise rather than let a semantic-invalid row escape into the ledger.
    errs = daily_row_semantic_errors(row)
    if errs:
        raise ValueError(f"compute_regime_daily_features: produced semantically invalid row: {errs}")
    return row
