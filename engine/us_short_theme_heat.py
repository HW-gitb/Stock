# -*- coding: utf-8 -*-
"""US-short per-stock theme-heat scoring (§4.3) — market-confirmation gate + continuous theme score.

Design authority: docs/us_short_system_design.md §4.3; the continuous score mirrors the A-short overlay
`theme_eff` (runners/a_short_theme_overlay_comparison.py: heat × persistence_mult × fit_mult).

Scope of THIS slice = the per-stock "does a stock earn theme score, and how much" logic:
  * market_confirmation_passed — a provisional theme earns theme score only if >= MIN of the 7
    market-confirmation items pass AND the stock itself is strong (§4.3 个股闸). A stock that is not
    strong, or a theme passing < MIN items, earns NO theme score even if heat is high.
  * fit_mult_from_score — maps theme_fit_score → fit multiplier (§4.3 'fit_mult 由 fit_score 映射'):
    0 below the floor (gate), else the clamped fit_score (continuous, not a flat 1).
  * continuous_theme_score — theme_score = heat × max(persistence_mult, floor) × fit_mult AFTER the
    gate (§4.3 门内连续打分), so a just-confirmed high-heat theme scores proportionally rather than
    being flattened; the persistence FLOOR applies only after the gate (a fresh theme isn't crushed);
    returns 0 if the gate didn't pass or the stock is chasing_extreme (§4.3 overextension strips theme
    heat to base).

The cross-sectional industry⊥theme orthogonalization (防双重计数) belongs with the §4.2 core_score
35%-block assembly (pool-level) and is NOT in this per-stock slice. All thresholds (min items / fit
floor / persistence floor / fit mapping) are §13.1 #32 forward priors, NOT frozen const. Pure/offline;
no provider, no A-share crossing.
"""
import math

# §13.1 #32 forward priors (NOT frozen const)
THEME_CONFIRMATION_ITEMS = ("theme_source_count", "theme_member_count", "theme_breadth_up_frac",
                            "theme_volume_confirm_frac", "theme_leader_rs", "theme_persistence_weeks",
                            "theme_fit_score")
MIN_CONFIRMATION_ITEMS = 3     # >= 3 of the 7 items
FIT_FLOOR = 0.40             # fit_mult gate (mirrors A-short FIT_FLOOR)
PERSISTENCE_FLOOR = 0.30      # persistence_mult floor AFTER the gate


def _finite(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def market_confirmation_passed(item_pass_flags, stock_is_strong, min_items=MIN_CONFIRMATION_ITEMS):
    """A provisional theme earns theme score only if >= min_items of the 7 market-confirmation items
    pass AND the stock itself is strong (§4.3 个股闸). item_pass_flags = {item: truthy} over the 7 items;
    only the 7 known items are counted (an unknown key can't pad the count)."""
    flags = item_pass_flags if isinstance(item_pass_flags, dict) else {}
    passed = sum(1 for k in THEME_CONFIRMATION_ITEMS if flags.get(k))
    return passed >= min_items and bool(stock_is_strong)


def fit_mult_from_score(fit_score, fit_floor=FIT_FLOOR):
    """Map theme_fit_score → fit multiplier (§4.3 'fit_mult 由 fit_score 映射'): 0 below the floor
    (gate), else the clamped-[0,1] fit_score itself (continuous). None / non-finite → 0."""
    f = _finite(fit_score)
    if f is None or f < fit_floor:
        return 0.0
    return max(0.0, min(1.0, f))


def continuous_theme_score(theme_heat, persistence_mult, fit_mult, gate_passed, chasing_extreme=False,
                           persistence_floor=PERSISTENCE_FLOOR):
    """theme_score = heat × max(persistence_mult, floor) × clamp(fit_mult) AFTER the confirmation gate
    (§4.3 门内连续打分). Returns 0.0 when the gate didn't pass, the stock is chasing_extreme (theme heat
    stripped to base, §4.3 overextension), or any input is non-finite. The persistence floor applies
    only after the gate so a fresh high-heat theme isn't crushed by a low multiplier."""
    if not gate_passed or chasing_extreme:
        return 0.0
    h, pm, fm = _finite(theme_heat), _finite(persistence_mult), _finite(fit_mult)
    if h is None or pm is None or fm is None:
        return 0.0
    return max(0.0, h) * max(pm, persistence_floor) * max(0.0, min(1.0, fm))
