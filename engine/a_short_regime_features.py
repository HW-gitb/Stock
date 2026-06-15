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

Performance (slice-2b-perf, behavior-preserving): a 252-day bootstrap calls this 252 times over the
SAME ~1.3M-row panel. The implementation is therefore VECTORIZED over the whole panel — limit
up/down/touched/failed events (one inner merge), per-day price+limit usability (one left merge), and
pct_above_ma20 (one groupby) are each computed in a single pass instead of the prior per-window-day
``daily["trade_date"].astype(str) == day`` rescans / per-day merges / per-stock Python loops. Every
emitted field is byte-identical to the original per-day implementation (pinned by the optimized-vs-
frozen-reference equality test); only the execution strategy changed.
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


def _assert_canonical_panel_dates(df: pd.DataFrame, name: str, str_dates: pd.Series | None = None) -> None:
    """Reject non-canonical YYYYMMDD ``trade_date`` so lexicographic PIT filters/sorts are sound.

    Only the DISTINCT date strings are strptime-round-tripped (a panel has ~hundreds of unique dates
    over millions of rows); validating the unique set is equivalent to validating every row but avoids
    millions of redundant per-row ``is_canonical_date`` calls. ``str_dates`` is the caller's reused
    ``df["trade_date"].astype(str)`` when available."""
    if df is None or df.empty or "trade_date" not in df.columns:
        return
    sd = str_dates if str_dates is not None else df["trade_date"].astype(str)
    bad = sorted(d for d in sd.unique() if not is_canonical_date(str(d)))
    if bad:
        raise ValueError(f"{name}: non-canonical trade_date values {bad[:3]}")


def _assert_unique(df: pd.DataFrame, keys: list, name: str, as_of: str,
                   str_dates: pd.Series | None = None) -> None:
    """Reject duplicate ``keys`` among rows at/<= as_of (a dup can fabricate counts / index returns).

    ``str_dates`` is the caller's reused ``df["trade_date"].astype(str)`` (avoids a second full
    str-cast of the panel); behavior is identical to casting inline."""
    if df is None or df.empty:
        return
    sd = str_dates if str_dates is not None else df["trade_date"].astype(str)
    sub = df[sd <= str(as_of)][keys].astype(str)
    if sub.duplicated().any():
        ex = sub[sub.duplicated(keep=False)].drop_duplicates().head(3).to_dict("records")
        raise ValueError(f"{name}: duplicate rows for {keys} at/<= as_of, e.g. {ex}")


def _incomplete_by_date(daily: pd.DataFrame, sl: pd.DataFrame, dstr: pd.Series | None,
                        lstr: pd.Series | None, as_of: str) -> tuple:
    """Vectorized usable-data coverage per trade date.

    A daily ``(date, ts_code)`` row is FULLY USABLE iff it has a usable price (finite positive close &
    high, ``high>=close`` — the old ``_usable_price_codes`` rule) AND a usable ``stk_limit`` row exists
    for the same ``(date, ts_code)`` (finite positive up & down — the old ``_usable_limit_codes`` rule).
    A date is INCOMPLETE iff any daily-traded stock that day is not fully usable, i.e. the count of
    fully-usable rows is below the count of daily rows (``daily``/``stk_limit`` are unique per
    ``(date, ts_code)``, enforced upstream, so a code-set difference and a row-count difference agree).

    Returns ``(incomplete_by_date, asof_total, asof_usable)`` — a dict ``date -> bool`` plus the as_of
    daily-row total and fully-usable count (for the fail-closed message). One left merge + one groupby
    replaces the prior per-day ``_incomplete`` set-difference loop; the verdict is byte-identical."""
    if daily is None or daily.empty:
        return {}, 0, 0
    close = _num(daily["close"]).to_numpy()
    high = _num(daily["high"]).to_numpy()
    price_ok = np.isfinite(close) & (close > 0) & np.isfinite(high) & (high > 0) & (high >= close)
    dd = dstr.to_numpy()
    if sl is None or sl.empty or lstr is None:
        fully = np.zeros(len(dd), dtype=bool)             # no usable limit anywhere → nothing usable
    else:
        up = _num(sl["up_limit"]).to_numpy()
        down = _num(sl["down_limit"]).to_numpy()
        lok = np.isfinite(up) & (up > 0) & np.isfinite(down) & (down > 0)
        left = pd.DataFrame({"_d": dd, "ts_code": daily["ts_code"].to_numpy(),
                             "price_ok": price_ok, "_o": np.arange(len(dd))})
        right = pd.DataFrame({"_d": lstr.to_numpy()[lok], "ts_code": sl["ts_code"].to_numpy()[lok],
                              "_lim": True})
        mer = left.merge(right, on=["_d", "ts_code"], how="left").sort_values("_o")
        fully = mer["price_ok"].to_numpy() & mer["_lim"].notna().to_numpy()
    agg = pd.DataFrame({"_d": dd, "ok": fully}).groupby("_d")["ok"].agg(["sum", "count"])
    vals = agg.to_numpy()   # columns: [sum_usable, count_total]
    incomplete = {d: int(vals[i, 0]) < int(vals[i, 1]) for i, d in enumerate(agg.index)}
    a = str(as_of)
    if a in agg.index:
        asof_usable, asof_total = (int(agg.at[a, "sum"]), int(agg.at[a, "count"]))
    else:
        asof_usable = asof_total = 0
    return incomplete, asof_total, asof_usable


def _limit_events(daily: pd.DataFrame, sl: pd.DataFrame, dstr: pd.Series | None,
                  lstr: pd.Series | None, as_of: str) -> tuple:
    """Vectorized limit-up/down/touched/failed over the whole panel (one inner merge).

    Reproduces the per-day ``_limit_sets`` inner merge of ``daily`` × ``stk_limit`` on ``(date, code)``
    using each stock's own up/down limit (so ±10/±20/ST±5 calibers are respected), with the IDENTICAL
    boolean conditions. Returns ``(up_by_date, asof)`` where ``up_by_date`` maps each date ``<= as_of``
    with at least one limit-up to its set of limit-up ts_codes (streak/promotion inputs), and ``asof``
    holds the as_of-day up-code set + up/down/touched/failed counts. Because every consumer takes
    order-independent set cardinalities / memberships, the one-pass merge is byte-identical to the
    272 per-day merges it replaces."""
    empty = {"up": set(), "up_count": 0, "down_count": 0, "touched": 0, "failed": 0}
    if daily is None or daily.empty or sl is None or sl.empty or lstr is None:
        return {}, empty
    left = pd.DataFrame({"_d": dstr.to_numpy(), "ts_code": daily["ts_code"].to_numpy(),
                         "close": _num(daily["close"]).to_numpy(), "high": _num(daily["high"]).to_numpy()})
    right = pd.DataFrame({"_d": lstr.to_numpy(), "ts_code": sl["ts_code"].to_numpy(),
                          "up_limit": _num(sl["up_limit"]).to_numpy(),
                          "down_limit": _num(sl["down_limit"]).to_numpy()})
    m = left.merge(right, on=["_d", "ts_code"], how="inner")
    if m.empty:
        return {}, empty
    close = m["close"]; high = m["high"]; up = m["up_limit"]; down = m["down_limit"]
    ok = close.notna() & up.notna() & up.gt(0)
    up_mask = (ok & (close >= up * LIMIT_TOL)).to_numpy()
    touched_mask = (ok & high.notna() & (high >= up * LIMIT_TOL)).to_numpy()
    failed_mask = (ok & high.notna() & (high >= up * LIMIT_TOL) & (close < up * LIMIT_TOL)).to_numpy()
    ok_d = close.notna() & down.notna() & down.gt(0)
    down_mask = (ok_d & (close <= down * (2 - LIMIT_TOL))).to_numpy()
    md = m["_d"].to_numpy(); mc = m["ts_code"].to_numpy()
    a = str(as_of)
    asof = md == a
    pit = md <= a
    up_by_date: dict[str, set] = {}
    for d, c in zip(md[up_mask & pit], mc[up_mask & pit]):
        s = up_by_date.get(d)
        if s is None:
            up_by_date[d] = s = set()
        s.add(c)
    counts = {"up": set(mc[up_mask & asof]),
              "up_count": int((up_mask & asof).sum()),
              "down_count": int((down_mask & asof).sum()),
              "touched": int((touched_mask & asof).sum()),
              "failed": int((failed_mask & asof).sum())}
    return up_by_date, counts


def _max_limit_streak(up_by_date: dict, dates: list[str]) -> int:
    """Max over stocks of consecutive limit-up days ending at the last date."""
    if not dates:
        return 0
    streak_by_code: dict[str, int] = {}
    best = 0
    # walk dates backward from the end; a stock's streak is unbroken consecutive membership
    alive = set(up_by_date.get(dates[-1], set()))
    for code in alive:
        streak_by_code[code] = 0
    for d in reversed(dates):
        ups = up_by_date.get(d, set())
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


def _pct_above_ma20(daily: pd.DataFrame, dstr: pd.Series, dates: list[str]) -> tuple:
    """(pct_above_ma20 or None, eligible_count). Eligible = stock with >= MA_WINDOW closes <= as_of.

    Vectorized: select the MA_WINDOW-day window with one positional mask (carrying each row's
    precomputed date string), then per stock compute the distinct-window-day count and the window-mean
    via groupby. Eligible = stocks with >= MA_WINDOW distinct window days AND a row at as_of; a stock
    counts as above iff its as_of close exceeds its window mean. Row selection preserves the original
    ``daily`` order, so each per-stock mean is over the identical values in the identical order — the
    above-count is byte-identical to the prior per-stock Python loop."""
    if len(dates) < MA_WINDOW:
        return None, 0
    window = set(dates[-MA_WINDOW:])
    as_of = dates[-1]
    mask = dstr.isin(window).to_numpy()
    if not mask.any():
        return None, 0
    sub = pd.DataFrame({"code": daily["ts_code"].to_numpy()[mask], "td": dstr.to_numpy()[mask],
                        "close": _num(daily["close"]).to_numpy()[mask]})
    sub = sub.dropna(subset=["close"])
    if sub.empty:
        return None, 0
    g = sub.groupby("code", sort=False)
    ndist = g["td"].nunique()
    mean_close = g["close"].mean()
    today = sub[sub["td"] == as_of].set_index("code")["close"]
    elig = ndist.index[ndist.to_numpy() >= MA_WINDOW].intersection(today.index)
    eligible = len(elig)
    if eligible == 0:
        return None, 0
    above = int((today.loc[elig].to_numpy() > mean_close.loc[elig].to_numpy()).sum())
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

    # PERF: cast each big panel's trade_date to str ONCE and reuse it for the canonical-date check, the
    # uniqueness check, the PIT trade-day axis, and every vectorized whole-panel pass below.
    dstr = daily["trade_date"].astype(str) \
        if (daily is not None and not daily.empty and "trade_date" in daily.columns) else None
    lstr = sl["trade_date"].astype(str) if (not sl.empty and "trade_date" in sl.columns) else None

    # source-panel integrity (before any lexicographic PIT filter / metric): canonical dates so
    # ordering is sound, and one row per (date,stock)/(date) so a dup can't fabricate counts/returns.
    _assert_canonical_panel_dates(daily, "daily", dstr)
    _assert_canonical_panel_dates(sl, "stk_limit", lstr)
    _assert_canonical_panel_dates(csi300, "csi300")
    _assert_canonical_panel_dates(csi1000, "csi1000")
    _assert_unique(daily, ["trade_date", "ts_code"], "daily", as_of, dstr)
    _assert_unique(sl, ["trade_date", "ts_code"], "stk_limit", as_of, lstr)
    _assert_unique(csi300, ["trade_date"], "csi300", as_of)
    _assert_unique(csi1000, ["trade_date"], "csi1000", as_of)

    # PIT cap (defends the "rows > as_of ignored" contract): restrict the working daily/stk_limit
    # frames + their reused date-string series to dates <= as_of BEFORE any vectorized merge/groupby.
    # The original capped every per-day filter to <= as_of, so a future row must never alter or break
    # the current row — in particular a future-dated DUPLICATE stk_limit row, which the uniqueness
    # check (only at/<= as_of) cannot see, would otherwise inflate the left-merge cardinality and raise.
    # Capping also shrinks early-as_of work during a 252-day bootstrap.
    if dstr is not None:
        dmask = dstr <= as_of
        daily, dstr = daily[dmask], dstr[dmask]
    if lstr is not None:
        lmask = lstr <= as_of
        sl, lstr = sl[lmask], lstr[lmask]

    # ascending unique PIT trade dates (<= as_of) from the (now-capped) date column (no row scan)
    dates = sorted(dstr.unique()) if dstr is not None else []
    if not dates or dates[-1] != as_of:
        raise ValueError(f"compute_regime_daily_features: daily has no rows for as_of {as_of}")

    # one vectorized coverage pass: which trade dates have a missing/unusable daily-price or stk_limit
    # observation for some traded stock (fail-closed on as_of, degrade on prior window days).
    incomplete_by_date, asof_total, asof_usable = _incomplete_by_date(daily, sl, dstr, lstr, as_of)

    # FAIL CLOSED on as_of: limit_up/down/net/streak/failed are non-null integer/ratio fields that
    # CANNOT honestly represent "unknown" — a fabricated 0 (from missing/unusable limit OR broken
    # daily price) misreads as a real observation (e.g. max_limit_streak=0 firing streak_collapse, or
    # close=0 fabricating a limit-down). A real A-share trading day always has complete usable price +
    # stk_limit; an incomplete one is a fetch failure the runner must resolve, so refuse to emit a
    # fabricated row rather than poison the evidence ledger.
    if incomplete_by_date.get(as_of, False):
        raise ValueError(
            f"compute_regime_daily_features: as_of {as_of} has missing/unusable daily-price or "
            f"stk_limit data for {asof_total - asof_usable}/{asof_total} traded stocks; "
            f"cannot compute limit breadth (re-fetch) — refusing to fabricate zeros")

    # prior window days (streak/promotion inputs) may still be incomplete — degrade, don't fail.
    history_incomplete = any(incomplete_by_date.get(d, False) for d in dates[:-1])
    if history_incomplete:
        flags.append("stk_limit_history_incomplete")

    # one vectorized limit-event pass: per-day limit-up sets (streak/promotion) + as_of breadth counts.
    up_by_date, asof = _limit_events(daily, sl, dstr, lstr, as_of)

    limit_up_count = asof["up_count"]
    limit_down_count = asof["down_count"]
    net_limit = limit_up_count - limit_down_count

    # failed_limit_rate = failed_up / touched_up; denom 0 → None
    touched = asof["touched"]
    failed_limit_rate = round(asof["failed"] / touched, 6) if touched else None

    max_limit_streak = _max_limit_streak(up_by_date, dates)

    # promotion_rate = (prev-day limit-up that limit-up again today) / prev-day limit-up count
    if len(dates) >= 2:
        prev_up = up_by_date.get(dates[-2], set())
        denom = len(prev_up)
        if incomplete_by_date.get(dates[-2], False):
            promotion_rate = None          # prior-day denom from a subset → unreliable (history flag set)
        elif denom < MIN_PROMOTION_DENOM:
            promotion_rate = None
            flags.append("insufficient_sample")
        else:
            promotion_rate = round(len(prev_up & asof["up"]) / denom, 6)
    else:
        promotion_rate = None
        flags.append("insufficient_sample")

    pct_above_ma20, _elig = _pct_above_ma20(daily, dstr, dates)
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
