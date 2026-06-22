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

This module produces the orthogonal residual in BOTH directions (`orthogonalize_industry_on_theme` and the
swapped `orthogonalize_theme_on_industry`) over a generic `_orthogonalize(pool, base_key, residual_key)`; the
directional 35%-block COMBINATION (theme-base vs pure-GICS-base by rule, residual coefficient §13 #38) lives
in `engine/us_short_theme_block.py`, which consumes these residuals.
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


def _orthogonalize(pool, base_key, residual_key, min_paired=MIN_PAIRED):
    """Cross-sectional: regress `residual_key` on `base_key` across the pool, take the residual (the part of
    `residual_key` NOT explained by `base_key`), percentile-normalise to 0-100 — so the overlap between the
    two heat sources is counted ONCE. Returns a list aligned with `pool`: the orthogonal residual (0-100) for
    rows where `residual_key` is a valid number, else None. Degenerate (< min_paired both-present rows, or
    ~zero `base_key` variance) → `residual_key` percentile fallback (the base can't separate). A PERFECT fit
    (zero residual dispersion) → all paired rows get a non-boosting 0.0 (no separable signal — overlap counted
    once, NOT a max-percentile boost). A non-list pool / non-dict / malformed row → no usable value (fail
    closed)."""
    rows = pool if isinstance(pool, list) else []
    mp = _safe_min_paired(min_paired)
    out = [None] * len(rows)

    y_idx, y_vals, paired = [], [], []
    for i, row in enumerate(rows):
        r = row if isinstance(row, dict) else {}
        x = _finite_number(r.get(base_key))
        y = _finite_number(r.get(residual_key))
        if y is not None:
            y_idx.append(i)
            y_vals.append(y)
        if x is not None and y is not None:
            paired.append((i, x, y))

    if not y_idx:
        return out

    if len(paired) < mp or _variance([x for (_i, x, _y) in paired]) < 1e-9:
        for i, pr in zip(y_idx, _percentile_rank_0_100(y_vals)):   # degenerate → residual_key percentile
            out[i] = pr
        return out

    xs = [x for (_i, x, _y) in paired]
    ys = [y for (_i, _x, y) in paired]
    slope, intercept = _ols(xs, ys)
    resid = [y - (slope * x + intercept) for (_i, x, y) in paired]
    if _variance(resid) < 1e-9:        # residual_key perfectly explained by base_key → no separable info
        for (i, _x, _y) in paired:     # → non-boosting 0 (NOT max percentile); the overlap is counted once
            out[i] = 0.0
        return out
    for (i, _x, _y), pr in zip(paired, _percentile_rank_0_100(resid)):  # residual percentile for paired rows
        out[i] = pr
    return out


def orthogonalize_industry_on_theme(pool, min_paired=MIN_PAIRED):
    """industry⊥theme (§4.3): regress `industry_heat_score` on `theme_heat_score`, residual percentile. The
    orthogonal INDUSTRY contribution used when the THEME is the base (a cross-sector theme, §13.1 #38)."""
    return _orthogonalize(pool, "theme_heat_score", "industry_heat_score", min_paired)


def orthogonalize_theme_on_industry(pool, min_paired=MIN_PAIRED):
    """theme⊥industry (§4.3, the swapped direction): regress `theme_heat_score` on `industry_heat_score`,
    residual percentile. The orthogonal THEME contribution used when GICS industry is the base (pure-GICS,
    §13.1 #38)."""
    return _orthogonalize(pool, "industry_heat_score", "theme_heat_score", min_paired)
