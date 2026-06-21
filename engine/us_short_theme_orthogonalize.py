# -*- coding: utf-8 -*-
"""US-short industry⊥theme orthogonalization (§4.3 热度去重/正交化) — cross-sectional, pure Python.

Design authority: docs/us_short_system_design.md §4.3 (防双重计数 + 防伪分散); mirrors the A-short
overlay `runners/a_short_theme_overlay_comparison.py::orthogonalize_industry_on_theme`.

The 35% theme block has two overlapping heat sources — `industry_heat_score` (GICS industry strength)
and `theme_heat_score` (cross-industry provisional-theme strength). To count the overlap ONCE, this
regresses industry on theme across the pool, takes the residual (the part of industry NOT explained by
theme), and percentile-normalises it to 0-100. Degenerate (too few paired rows, or ~zero theme
variance) → industry percentile fallback (theme carries no separable information). Pure Python OLS +
percentile (no numpy).

This slice produces ONLY the orthogonal industry residual; the directional 35%-block combination
(theme-base vs pure-GICS-base, residual coefficient §13 #38) is a separate assembly step, NOT here.
Every public input is validated fail-closed (whole-class, incl. the `min_paired` default param): pool
rows' values use a strict `_finite_number` (rejects bool + numeric string), a non-list pool / non-dict
row is treated as empty, and a malformed `min_paired` falls back to the default. Pure/offline; no
provider, no A-share crossing.
"""
import math

MIN_PAIRED = 3   # mirror A-short: fewer than this many BOTH-present rows → degenerate (can't regress)


def _finite_number(x):
    """Strictly-typed finite number (int/float, NOT bool, NOT a numeric string); else None — so a
    malformed pool value can't be parsed into a live heat score."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _safe_min_paired(min_paired):
    # MIN_PAIRED (3) is the hard floor: 2 points always fit a line perfectly (0 residual dispersion), so a
    # lower threshold is meaningless. A caller may RAISE it (calibration); anything < MIN_PAIRED → the floor.
    return min_paired if (isinstance(min_paired, int) and not isinstance(min_paired, bool) and min_paired >= MIN_PAIRED) else MIN_PAIRED


def _variance(xs):
    n = len(xs)
    if n == 0:
        return 0.0
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / n


def _ols(xs, ys):
    """Ordinary least squares slope + intercept (ys ~ slope·xs + intercept). Assumes Σ(x−x̄)² > 0."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 0 else 0.0
    return slope, my - slope * mx


def _percentile_rank_0_100(values):
    """Percentile rank of each value in 0-100 = (count of values <= it) / n × 100 (ties share the top
    rank). Empty → empty."""
    n = len(values)
    if n == 0:
        return []
    return [sum(1 for u in values if u <= v) / n * 100.0 for v in values]


def orthogonalize_industry_on_theme(pool, min_paired=MIN_PAIRED):
    """Cross-sectional: regress `industry_heat_score` on `theme_heat_score` across the pool, take the
    residual, percentile-normalise to 0-100 (industry/theme heat overlap counted once). Returns a list
    aligned with `pool`: the orthogonal industry value (0-100) for rows where industry is a valid number,
    else None. Degenerate (< min_paired both-present rows, or ~zero theme variance) → industry percentile
    fallback over all rows that have a valid industry value (theme can't separate). A PERFECT
    industry-on-theme fit (zero residual dispersion) → all paired rows get a non-boosting 0.0 (no
    separable industry signal — the overlap is counted once, NOT turned into a max-percentile boost).
    A non-list pool or non-dict / malformed row is treated as having no usable value (fail closed)."""
    rows = pool if isinstance(pool, list) else []
    mp = _safe_min_paired(min_paired)
    out = [None] * len(rows)

    ind_idx, ind_vals, paired = [], [], []
    for i, row in enumerate(rows):
        r = row if isinstance(row, dict) else {}
        t = _finite_number(r.get("theme_heat_score"))
        y = _finite_number(r.get("industry_heat_score"))
        if y is not None:
            ind_idx.append(i)
            ind_vals.append(y)
        if t is not None and y is not None:
            paired.append((i, t, y))

    if not ind_idx:
        return out

    if len(paired) < mp or _variance([t for (_i, t, _y) in paired]) < 1e-9:
        for i, pr in zip(ind_idx, _percentile_rank_0_100(ind_vals)):   # degenerate → industry percentile
            out[i] = pr
        return out

    xs = [t for (_i, t, _y) in paired]
    ys = [y for (_i, _t, y) in paired]
    slope, intercept = _ols(xs, ys)
    resid = [y - (slope * t + intercept) for (_i, t, y) in paired]
    if _variance(resid) < 1e-9:        # industry perfectly explained by theme → no separable industry info
        for (i, _t, _y) in paired:     # → non-boosting 0 (NOT max percentile); the overlap is counted once
            out[i] = 0.0
        return out
    for (i, _t, _y), pr in zip(paired, _percentile_rank_0_100(resid)):  # residual percentile for paired rows
        out[i] = pr
    return out
