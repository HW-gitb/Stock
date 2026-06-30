# -*- coding: utf-8 -*-
"""US-short momentum / relative-strength block (§4.2 momentum sub-score) — pure engine.

Design authority: docs/us_short_system_design.md §4.2:
  core_score = 40% momentum + 35% theme + 25% catalyst − risk_downgrade
  momentum sub-features = 1mo/3mo trend, 5-10 day momentum, relative to SPY/QQQ, relative to sector,
  volume surge; "动量 = 全池分位" (full-pool percentile, mapped to 0-100).

This module is PURE (no network, no provider, no A-share crossing). It consumes already-fetched daily
price/volume series (the Massive grouped-daily data layer supplies them in round-2 slice 2) and the
benchmark (SPY/QQQ) series, computes per-ticker momentum sub-features, then maps the composite to a
0-100 FULL-POOL PERCENTILE block that engine/us_short_core_score.py consumes as its `momentum` block.

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
"""
from __future__ import annotations

import math
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
    """Strict finite number: rejects bool, numeric strings, NaN/Inf; else float or None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _clean_series(series: Any) -> list[float] | None:
    """Validate an ascending-by-date price/volume series -> list[float]. None if not a list or fewer
    than MIN_HISTORY_DAYS valid points. A non-finite point breaks the series (return None) rather than
    being silently dropped (a hole would corrupt return math)."""
    if not isinstance(series, (list, tuple)) or len(series) < MIN_HISTORY_DAYS:
        return None
    out = []
    for v in series:
        f = _finite(v)
        if f is None:
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


def compute_momentum_features(
    closes: Any,
    *,
    volumes: Any = None,
    spy_closes: Any = None,
    qqq_closes: Any = None,
) -> dict[str, Any]:
    """Per-ticker momentum sub-features from an ascending daily close series (+ optional volume and
    SPY/QQQ benchmark close series). Returns {features: {name: value}, n_features: int}. A sub-feature
    that can't be computed (insufficient history / missing benchmark) is omitted (not faked)."""
    px = _clean_series(closes)
    if px is None:
        return {"features": {}, "n_features": 0}

    feats: dict[str, float] = {}
    for name, lb in (("ret_1m", LOOKBACK_1M), ("ret_3m", LOOKBACK_3M),
                     ("ret_5d", LOOKBACK_5D), ("ret_10d", LOOKBACK_10D)):
        r = _ret(px, lb)
        if r is not None:
            feats[name] = r

    # Relative strength vs benchmarks over 1 month (ticker 1m return − benchmark 1m return).
    own_1m = feats.get("ret_1m")
    for name, bench in (("rel_spy_1m", spy_closes), ("rel_qqq_1m", qqq_closes)):
        bs = _clean_series(bench)
        if own_1m is not None and bs is not None:
            br = _ret(bs, LOOKBACK_1M)
            if br is not None:
                feats[name] = own_1m - br

    # Volume surge: recent short-window avg volume / longer baseline avg volume.
    vol = _clean_series(volumes) if volumes is not None else None
    if vol is not None and len(vol) >= VOL_SURGE_LONG:
        short_avg = sum(vol[-VOL_SURGE_SHORT:]) / VOL_SURGE_SHORT
        long_avg = sum(vol[-VOL_SURGE_LONG:]) / VOL_SURGE_LONG
        if long_avg > 0:
            feats["vol_surge"] = short_avg / long_avg

    return {"features": feats, "n_features": len(feats)}


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
