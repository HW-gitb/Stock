# -*- coding: utf-8 -*-
"""US-short §4.5 dynamic Top15 seats — theme_opportunity_state → core_top + theme_momentum split.

Design authority: docs/us_short_system_design.md §4.5 (line 163 动态席位 + line 52 强赛道周 Top6-15 龙头升级).
The split MAP (常 10+5 / 强赛道周 8+7 / 无强赛道周 12+3, total 15) is const-pinned (user-approved 2026-06-22)
in presets/us_short_theme_probe_governance_20260622.json `selection_seat_map` (LOADED here); the ratio
trigger + the leader-upgrade count are §13.1 #29 forward priors.

This is the SELECTION-layer placement of the second environment axis: theme_opportunity_state (from
engine/us_short_theme_opportunity.py) sets how the fixed 15 Top-list seats divide between core_top (momentum/
fundamentals rank) and theme_momentum (赛道) — "选股层放开、不是下注放开" (the 30% same-theme cap + weekly
≤2 are the §8 back-gates). A market-confirmed strong theme week additionally allows upgrading 1-2 Top6-15
theme leaders to full analysis (line 52; ≠ auto-build — it is the precondition for the §8 theme_probe).

Fail-closed: an unknown / malformed `theme_opportunity_state` returns the no_strong_theme split (12+3, the
fewest theme seats — the most conservative when the opportunity can't be read) and 0 leader upgrades. The seat
COMPOSITION (which stocks fill the theme seats: ≥2 auto-discovery / ≤2 watchlist / crowding / overlap /
core_backfill, §4.5 line 164) is a separate downstream concern. Pure/offline; no provider, no A-share crossing.
"""
import json
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_theme_probe_governance_20260622.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

SELECTION_SEAT_TOTAL = _GOV["selection_seat_total"]                              # 15
_SEAT_MAP = {r["state"]: {"core_top": r["core_top"], "theme_momentum": r["theme_momentum"]}
             for r in _GOV["selection_seat_map"]}
_FALLBACK_STATE = "no_strong_theme"                                             # fewest theme seats (12+3)

# §13.1 #29 forward priors (NOT frozen const), module constants.
STRONG_THEME_WEEK_STATES = ("strong", "extreme")        # 强赛道周 (both share the 8+7 split)
STRONG_THEME_LEADER_UPGRADE_MAX = 2                      # 强赛道周 Top6-15 龙头升级完整分析上限 (line 52, 1-2)


def selection_seats(theme_opportunity_state):
    """§4.5 Top15 split for a `theme_opportunity_state` → {core_top, theme_momentum} (sums to
    SELECTION_SEAT_TOTAL = 15). An unknown / malformed state fails closed to the no_strong_theme split
    (12+3 — the fewest theme seats; an unreadable opportunity must not inflate the 赛道 allocation). Returns
    a COPY so a consumer can't mutate the frozen map."""
    row = _SEAT_MAP.get(theme_opportunity_state) or _SEAT_MAP[_FALLBACK_STATE]
    return dict(row)


def strong_theme_leader_upgrade_max(theme_opportunity_state):
    """§4.5 line 52: in a 强赛道周 (theme_opportunity_state ∈ {strong, extreme}) up to
    STRONG_THEME_LEADER_UPGRADE_MAX Top6-15 theme leaders may be upgraded to full analysis (the §8 theme_probe
    precondition; ≠ auto-build). Any other / unknown / malformed state → 0."""
    return STRONG_THEME_LEADER_UPGRADE_MAX if theme_opportunity_state in STRONG_THEME_WEEK_STATES else 0
