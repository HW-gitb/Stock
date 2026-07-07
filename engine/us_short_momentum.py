# -*- coding: utf-8 -*-
"""US-short momentum / relative-strength block (§4.2 momentum sub-score) — pure engine.

Design authority: docs/us_short_system_design.md §4.2:
  core_score = 40% momentum + 35% theme + 25% catalyst − risk_downgrade
  momentum sub-features = 1mo/3mo trend, 5-10 day momentum, relative to SPY/QQQ, relative to sector,
  volume surge; "动量 = 全池分位" (full-pool percentile, mapped to 0-100).

This module is PURE (no network, no provider, no A-share crossing). It consumes already-fetched, PIT-bearing
daily series (each = {as_of, session, adjustment_mode, points:[{date, close, volume?}]}; the gated Massive
data layer assembles them — Cut 2b / SR-PROVIDER-001) for the ticker + the SPY/QQQ benchmark, computes
per-ticker momentum sub-features, then maps the composite to a 0-100 FULL-POOL PERCENTILE block that
engine/us_short_core_score.py consumes as its `momentum` block.

v1 momentum composite (a §13 forward-calibratable prior, NOT validated alpha): for each sub-feature take
the cross-sectional percentile; then for a SCORED ticker average those percentiles over the FULL sub-feature
set — a MISSING sub-feature is filled with the NEUTRAL percentile (never full-weighted on the available
remainder) — and finally percentile the composite across the scored pool. Equal-weight-of-percentiles is
robust to scale/outliers (no arbitrary z-score tuning). The relative-to-sector sub-feature is OPTIONAL (needs
sector classification, wired later).

Coverage gating + fail-closed (min-coverage, R-USSHORT-BATCH5-MOMENTUM-COVERAGE-PIT-COMPARABILITY-GAP): a
ticker must carry at least `min_coverage` sub-features to be SCORED — below that it goes to
`insufficient_coverage` (NOT scored on the handful it happens to have, so a sparse extreme can't outrank a
full-feature name); a ticker with NO sub-feature goes to `insufficient_history`. Neither gets a fake neutral;
the caller marks its data_quality and core_score applies its neutral-block rule (§4.2 缺分量). All numeric
inputs are strictly validated (reject bool / NaN / Inf / numeric string).

PIT + alignment (R-USSHORT-BATCH5-MOMENTUM-COVERAGE-PIT-COMPARABILITY-GAP, the input-rework half): each series
is validated + PIT-cut to its `as_of` — a point dated AFTER as_of is BLOCKED (never used, no look-ahead) — and
its dates must be a strictly-ascending unique axis (a corrupt axis fails closed: the ticker scores nothing). The
relative-strength sub-features are computed over the COMMON dates of the ticker and the benchmark (same-day
alignment) and ONLY when their as_of / session / adjustment_mode match; a mismatch or insufficient overlap OMITS
the rel feature (never a misaligned / cross-adjustment comparison). The LIVE series assembly stays gated
(SR-PROVIDER-001, Cut 2b); this engine validates + enforces PIT/alignment on the supplied series.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

# Trading-day lookbacks for the sub-features (approx calendar: 21≈1mo, 63≈3mo).
LOOKBACK_1M = 21
LOOKBACK_3M = 63
LOOKBACK_5D = 5
LOOKBACK_10D = 10
VOL_SURGE_SHORT = 10   # recent avg volume window
VOL_SURGE_LONG = 63    # baseline avg volume window
MIN_HISTORY_DAYS = LOOKBACK_5D + 1  # need at least a 5-day return to score anything


def _finite(x: Any) -> float | None:
    """Strict finite number: rejects bool, numeric strings, NaN/Inf; else float or None. A legitimate
    huge int (abs ≳ 1.8e308) that overflows float() is CONTAINED (returns None, never a raw OverflowError)
    so a forged/corrupt huge close or volume is dispositioned like any other bad value instead of bare-
    crashing a caller that (by design) hands raw closes straight to this single clean authority."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        xf = float(x)
    except OverflowError:
        return None
    return xf if math.isfinite(xf) else None


def _clean_series(series: Any) -> list[float] | None:
    """Validate an ascending-by-date CLOSE price series -> list[float]. None if not a list, fewer than
    MIN_HISTORY_DAYS points, or any point is non-finite OR NON-POSITIVE. A stock close is strictly positive —
    a 0 / negative close is malformed price data, never momentum evidence
    (R-USSHORT-BATCH5-MOMENTUM-NONPOSITIVE-CLOSE-AND-FUTURE-BADPOINT-GAP; mirrors engine/us_short_industry_heat.py).
    A bad point fails the WHOLE series (a hole would corrupt return math). Only the KEPT (<=as_of) closes reach
    here (future points are PIT-cut upstream by `_parse_dated_series`), so a future malformed close cannot reject
    a valid current series."""
    if not isinstance(series, (list, tuple)) or len(series) < MIN_HISTORY_DAYS:
        return None
    out = []
    for v in series:
        f = _finite(v)
        if f is None or f <= 0.0:
            return None
        out.append(f)
    return out


def _ret(series: list[float], lookback: int) -> float | None:
    """Simple return over `lookback` trading days: series[-1]/series[-1-lookback] - 1. None if the
    series is too short or the base price is non-positive."""
    if len(series) < lookback + 1:
        return None
    base = series[-1 - lookback]
    if base <= 0:
        return None
    return series[-1] / base - 1.0


def _valid_date(s: Any):
    """Strict YYYY-MM-DD -> datetime.date, else None (no other format / no timezone games)."""
    if not (isinstance(s, str) and len(s) == 10):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


_DATED_SERIES_KEYS = {"as_of", "session", "adjustment_mode", "points"}
_POINT_REQUIRED = {"date", "close"}
_POINT_ALLOWED = {"date", "close", "volume"}


def _parse_dated_series(series: Any) -> dict | None:
    """Validate + PIT-cut a date/as_of/session/adjustment-bearing series ->
    {as_of: date, session: str, adjustment_mode: str, dates: [date,...], closes: [float,...],
    volumes: [float|None,...]} or None (fail-closed).

    PIT: a point dated AFTER `as_of` is BLOCKED (excluded — its VALUE is not even validated, so a future
    non-finite close can never over-reject an otherwise-valid ≤as_of series; no look-ahead). The RAW point
    axis must be strictly ascending + unique by date BEFORE the cut (a corrupt/duplicated axis -> None, never
    a silently-reordered series). The KEPT (≤as_of) closes are strictly finite (via `_clean_series`, which
    also enforces the MIN_HISTORY_DAYS floor after the cut — an IPO/short name -> None); each kept volume is
    finite or None.
    """
    if not (isinstance(series, dict) and set(series) == _DATED_SERIES_KEYS):
        return None
    as_of = _valid_date(series["as_of"])
    if as_of is None:
        return None
    session, adj = series["session"], series["adjustment_mode"]
    if not (isinstance(session, str) and session and isinstance(adj, str) and adj):
        return None
    pts = series["points"]
    if not isinstance(pts, list) or not pts:
        return None
    # Validate the RAW axis (shape + date + strictly-ascending-unique) over ALL points; but only the KEPT
    # (<= as_of) points are PIT-relevant, so close / volume VALUES are validated only for kept points — a future
    # point's value is BLOCKED and never validated, so a future non-finite close cannot over-reject an otherwise
    # valid <=as_of series (mirrors engine/us_short_industry_heat.py; future data we exclude must not gate us).
    kept_dates: list = []
    kept_closes: list = []
    kept_vols: list = []
    prev = None
    for p in pts:
        if not (isinstance(p, dict) and _POINT_REQUIRED <= set(p) <= _POINT_ALLOWED):
            return None
        d = _valid_date(p["date"])
        if d is None:
            return None
        if prev is not None and d <= prev:
            return None                       # raw axis must be strictly ascending + unique (corrupt -> None)
        prev = d
        if d <= as_of:                        # PIT cut: future points BLOCKED (value not even validated)
            kept_dates.append(d)
            kept_closes.append(p["close"])    # raw; _clean_series validates finiteness of the USED data
            fv = _finite(p["volume"]) if p.get("volume") is not None else None
            # non-negative finite volume contract: a NEGATIVE volume is malformed market data, never evidence —
            # map it to None so vol_surge is UNAVAILABLE for that window (it can never enter the average); a
            # valid zero volume is kept (R-USSHORT-BATCH5-MOMENTUM-NONPOSITIVE-CLOSE-AND-FUTURE-BADPOINT-GAP residual).
            kept_vols.append(fv if (fv is None or fv >= 0.0) else None)
    if not kept_dates:
        return None
    closes = _clean_series(kept_closes)        # finite + MIN_HISTORY_DAYS floor (post-cut)
    if closes is None:
        return None
    return {"as_of": as_of, "session": session, "adjustment_mode": adj,
            "dates": kept_dates, "closes": closes, "volumes": kept_vols}


def _aligned_rel_1m(own: dict, bench_series: Any) -> tuple[float | None, str]:
    """ticker 1m return − benchmark 1m return, computed over the COMMON dates of the two PIT series
    (same-day alignment) and ONLY when as_of / session / adjustment_mode match. Returns (rel|None, note);
    note ∈ {ok, no_benchmark, parse_failed, as_of_mismatch, session_mismatch, adjustment_mismatch,
    insufficient_overlap} so the caller can audit WHY a rel feature was omitted (never a misaligned compare)."""
    if bench_series is None:
        return None, "no_benchmark"
    bench = _parse_dated_series(bench_series)
    if bench is None:
        return None, "parse_failed"
    if own["as_of"] != bench["as_of"]:
        return None, "as_of_mismatch"
    if own["session"] != bench["session"]:
        return None, "session_mismatch"
    if own["adjustment_mode"] != bench["adjustment_mode"]:
        return None, "adjustment_mismatch"   # cross-adjustment relative return is meaningless -> omit
    bench_by_date = dict(zip(bench["dates"], bench["closes"]))
    aligned = [(c, bench_by_date[d]) for d, c in zip(own["dates"], own["closes"]) if d in bench_by_date]
    if len(aligned) < LOOKBACK_1M + 1:
        return None, "insufficient_overlap"
    own_r = _ret([a for a, _ in aligned], LOOKBACK_1M)
    bench_r = _ret([b for _, b in aligned], LOOKBACK_1M)
    if own_r is None or bench_r is None:
        return None, "insufficient_overlap"
    return own_r - bench_r, "ok"


def compute_momentum_features(
    ticker_series: Any,
    *,
    spy_series: Any = None,
    qqq_series: Any = None,
) -> dict[str, Any]:
    """Per-ticker momentum sub-features from a PIT-bearing dated daily series (+ optional SPY/QQQ benchmark
    series of the SAME shape). Each series = {as_of, session, adjustment_mode, points:[{date, close, volume?}]}.

    Absolute returns (ret_1m/3m/5d/10d) come from the ticker's own PIT-cut closes; relative-strength
    (rel_spy_1m / rel_qqq_1m) is computed over the COMMON dates of ticker+benchmark and only on matching
    as_of/session/adjustment (else omitted, see `_aligned_rel_1m`); vol_surge needs a fully-covered volume
    series. Returns {features: {name: value}, n_features: int, pit: {...}|None, alignment: {rel: note}}.
    A sub-feature that can't be computed (insufficient history / misaligned / missing benchmark) is omitted,
    never faked. A malformed / look-ahead / corrupt-axis ticker series -> empty features (fail-closed)."""
    own = _parse_dated_series(ticker_series)
    if own is None:
        return {"features": {}, "n_features": 0, "pit": None, "alignment": {}}
    px = own["closes"]

    feats: dict[str, float] = {}
    for name, lb in (("ret_1m", LOOKBACK_1M), ("ret_3m", LOOKBACK_3M),
                     ("ret_5d", LOOKBACK_5D), ("ret_10d", LOOKBACK_10D)):
        r = _ret(px, lb)
        if r is not None:
            feats[name] = r

    alignment: dict[str, str] = {}
    for name, bench in (("rel_spy_1m", spy_series), ("rel_qqq_1m", qqq_series)):
        rel, note = _aligned_rel_1m(own, bench)
        alignment[name] = note
        if rel is not None:
            feats[name] = rel

    # vol_surge needs only the VOL_SURGE_LONG window it actually averages (short ⊂ long ⊂ this tail), so an
    # earlier missing volume must NOT omit a computable surge (over-omission would drop the ticker's feature
    # count and could push it below min_coverage).
    vols = own["volumes"]
    window = vols[-VOL_SURGE_LONG:]
    if len(vols) >= VOL_SURGE_LONG and all(v is not None for v in window):
        short_avg = sum(window[-VOL_SURGE_SHORT:]) / VOL_SURGE_SHORT
        long_avg = sum(window) / VOL_SURGE_LONG
        if long_avg > 0:
            feats["vol_surge"] = short_avg / long_avg

    return {"features": feats, "n_features": len(feats),
            "pit": {"as_of": own["as_of"].isoformat(), "session": own["session"],
                    "adjustment_mode": own["adjustment_mode"], "n_points": len(px)},
            "alignment": alignment}


def _percentile_rank(values: dict[str, float]) -> dict[str, float]:
    """Map {key: raw value} -> {key: percentile 0-100} by cross-sectional rank. Ties share the average
    rank. A single value -> 50.0 (mid). Empty -> {}."""
    if not values:
        return {}
    keys = list(values)
    if len(keys) == 1:
        return {keys[0]: 50.0}
    ordered = sorted(keys, key=lambda k: values[k])
    n = len(ordered)
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[ordered[j + 1]] == values[ordered[i]]:
            j += 1
        avg_pos = (i + j) / 2.0           # average rank position for the tie group [i, j]
        pct = 100.0 * avg_pos / (n - 1)   # mapped to 0-100
        for k in range(i, j + 1):
            out[ordered[k]] = pct
        i = j + 1
    return out


NEUTRAL_PERCENTILE = 50.0
# §13 prior (#14 打分标准化口径): a ticker must carry at least this many of the sub-features to receive a PRIMARY
# momentum score; below it it is `insufficient_coverage` (NOT scored on the remainder) and the caller applies
# §4.2's neutral-block / data_quality rule. Calibratable; default = the four core return features.
MIN_SUBFEATURE_COVERAGE = 4


def momentum_block(
    features_by_ticker: dict[str, dict[str, float]],
    *,
    sub_features: tuple[str, ...] = ("ret_1m", "ret_3m", "ret_5d", "ret_10d",
                                     "rel_spy_1m", "rel_qqq_1m", "vol_surge"),
    min_coverage: int = MIN_SUBFEATURE_COVERAGE,
) -> dict[str, Any]:
    """Map per-ticker momentum sub-features -> a 0-100 FULL-POOL percentile momentum block.

    For each sub-feature, percentile-rank the tickers that HAVE it (cross-sectional).

    MIN-COVERAGE + NEUTRAL-FILL (R-USSHORT-BATCH5-MOMENTUM-COVERAGE-PIT-COMPARABILITY-GAP): a ticker must carry
    at least `min_coverage` of the sub-features to receive a PRIMARY score — below it it is NOT scored on the
    handful it happens to have (it goes to `insufficient_coverage`, never auto-full-weighted), so a sparse ticker
    with one extreme feature can no longer outrank a full-feature ticker. For a SCORED ticker every MISSING
    sub-feature counts as the NEUTRAL percentile (50), so every scored ticker's composite is the mean over the
    SAME full `sub_features` set (one denominator) — comparable across unequal coverage. The composite is then
    percentile-ranked across the scored pool ("动量 = 全池分位"). A ticker with NO sub-feature goes to
    `insufficient_history` (no fake neutral — §4.2 缺分量).

    Returns {momentum_block: {ticker: 0-100}, insufficient_history: [ticker, ...],
             insufficient_coverage: [ticker, ...], sub_feature_coverage: {sub_feature: count},
             coverage_matrix: {ticker: {"n_present": int, "scored": bool}}, min_coverage: int}.
    """
    if not isinstance(features_by_ticker, dict):
        features_by_ticker = {}
    if not (isinstance(min_coverage, int) and not isinstance(min_coverage, bool) and min_coverage >= 1):
        raise ValueError("min_coverage 须为 >=1 的 int")

    # 1) per-sub-feature cross-sectional percentile
    per_sub_pct: dict[str, dict[str, float]] = {}
    coverage: dict[str, int] = {}
    for sf in sub_features:
        raw = {}
        for tkr, feats in features_by_ticker.items():
            if not isinstance(feats, dict):
                continue
            v = _finite(feats.get(sf))
            if v is not None:
                raw[tkr] = v
        coverage[sf] = len(raw)
        if raw:
            per_sub_pct[sf] = _percentile_rank(raw)

    # 2) per-ticker coverage + min-coverage gate; SCORED composite = mean over the FULL sub_feature set with a
    #    MISSING sub-feature filled NEUTRAL (never full-weight on the available remainder).
    composite: dict[str, float] = {}
    insufficient_history: list[str] = []
    insufficient_coverage: list[str] = []
    coverage_matrix: dict[str, dict[str, Any]] = {}
    for tkr, feats in features_by_ticker.items():
        present = {sf for sf in sub_features if sf in per_sub_pct and tkr in per_sub_pct[sf]}
        n_present = len(present)
        scored = n_present >= min_coverage
        coverage_matrix[tkr] = {"n_present": n_present, "scored": scored}
        if n_present == 0:
            insufficient_history.append(tkr)
        elif not scored:
            insufficient_coverage.append(tkr)
        else:
            vals = [per_sub_pct[sf][tkr] if sf in present else NEUTRAL_PERCENTILE for sf in sub_features]
            composite[tkr] = sum(vals) / len(sub_features)

    # 3) final momentum block = full-pool percentile of the composite (over the scored pool only)
    block = _percentile_rank(composite)
    return {
        "momentum_block": block,
        "insufficient_history": sorted(insufficient_history),
        "insufficient_coverage": sorted(insufficient_coverage),
        "sub_feature_coverage": coverage,
        "coverage_matrix": coverage_matrix,
        "min_coverage": min_coverage,
    }
