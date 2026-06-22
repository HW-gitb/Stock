# -*- coding: utf-8 -*-
"""US-short 35% theme block assembly (§4.3 赛道/主题热度块方向合成) — directional, overlap-counted-once.

Design authority: docs/us_short_system_design.md §4.3 + §13.1 #38 (line 366). core_score = 40% momentum +
**35% 赛道/主题热度** + 25% catalyst − risk_downgrade (line 121); this engine builds that 35% block from the
two overlapping heat sources (`theme_heat_score` cross-industry theme strength + `industry_heat_score` GICS
industry strength), counting their overlap ONCE.

§13.1 #38 FIXES the direction by RULE (not a free choice): a 跨界主题 (cross-sector theme) → THEME is the base
and industry is orthogonalised on theme (industry⊥theme residual); a 纯 GICS (pure GICS industry) → INDUSTRY
is the base and theme is orthogonalised on industry (theme⊥industry residual). The fail-safe default is the
INDUSTRY base — GICS is the official hard grouping (§4.3 line 132), so a row is theme-base ONLY when it
explicitly asserts `theme_is_cross_sector is True`.

Per row: block_raw = base_percentile + RESIDUAL_COEF × orthogonal_residual (the base heat percentiled within
its own source; the orthogonal residual is the 0-100 §4.3 orthogonalisation value, OR a non-boosting 0 when the
opposite heat source is absent — the residual is an ADDITIVE de-dup term, NOT a prerequisite for the base);
then block_raw is re-percentiled across the pool to the 0-100 block score. RESIDUAL_COEF is the §13.1 #38
forward prior (module constant, not caller-overridable). ONLY a row whose SELECTED BASE is unusable → None; a
missing opposite source does NOT null the block (a pure-GICS industry-only row ranks by industry, a cross-sector
theme-only row by theme). Pure/offline; no provider, no A-share crossing. macro_cluster duplicate-heat is a
SEPARATE soft warning (§8), not a hard deduction here.
"""
from engine.us_short_theme_orthogonalize import (
    orthogonalize_industry_on_theme,
    orthogonalize_theme_on_industry,
    _finite_number,
    _percentile_rank_0_100,
)

RESIDUAL_COEF = 0.5   # §13.1 #38 forward prior: weight of the orthogonal residual on top of the base


def _pool_percentile(rows, key):
    """Percentile-rank a per-row heat `key` within its OWN source across the pool (0-100); None where the row
    is a non-dict or the value is malformed (fail closed)."""
    idx, vals = [], []
    for i, row in enumerate(rows):
        v = _finite_number(row.get(key)) if isinstance(row, dict) else None
        if v is not None:
            idx.append(i)
            vals.append(v)
    out = [None] * len(rows)
    for i, pr in zip(idx, _percentile_rank_0_100(vals)):
        out[i] = pr
    return out


def assemble_theme_block(pool):
    """Build the §4.3 35% theme block (0-100) for each row of `pool`. Each row carries `theme_heat_score`,
    `industry_heat_score`, and `theme_is_cross_sector` (strict True → theme base; otherwise the fail-safe
    GICS industry base). Returns a list aligned with `pool`: the block score for every row whose SELECTED
    BASE heat is usable — a missing OPPOSITE heat source just contributes a non-boosting 0 residual (the base
    alone is a valid block, §13 #38: the residual is an additive de-dup term, not a prerequisite), so a pure-
    GICS industry-only row ranks by industry and a cross-sector theme-only row ranks by theme. Only a row whose
    SELECTED base itself is malformed → None. A non-list pool → []."""
    rows = pool if isinstance(pool, list) else []
    if not rows:
        return []

    ind_resid = orthogonalize_industry_on_theme(rows)   # industry⊥theme → theme-base rows
    thm_resid = orthogonalize_theme_on_industry(rows)   # theme⊥industry → industry-base rows
    theme_pct = _pool_percentile(rows, "theme_heat_score")
    industry_pct = _pool_percentile(rows, "industry_heat_score")

    combined = [None] * len(rows)
    for i, row in enumerate(rows):
        cross_sector = isinstance(row, dict) and row.get("theme_is_cross_sector") is True
        if cross_sector:
            base_pct, residual = theme_pct[i], ind_resid[i]
        else:
            base_pct, residual = industry_pct[i], thm_resid[i]   # fail-safe GICS base
        if base_pct is None:
            continue                                      # no usable base heat → genuinely unusable
        # a MISSING opposite source = no orthogonal contribution (residual 0), NOT a dropped row — the
        # selected base alone is a valid block (§13 #38: the residual is an additive de-dup term, not a
        # prerequisite for the base heat to exist)
        combined[i] = base_pct + RESIDUAL_COEF * (residual if residual is not None else 0.0)

    usable = [i for i, c in enumerate(combined) if c is not None]
    block = [None] * len(rows)
    if usable:
        for i, pr in zip(usable, _percentile_rank_0_100([combined[i] for i in usable])):
            block[i] = pr
    return block
