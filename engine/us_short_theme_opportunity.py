# -*- coding: utf-8 -*-
"""US-short theme_opportunity_state determination (§7 两轴环境第二轴 / §4.5 driver).

Design authority: docs/us_short_system_design.md §7 (line 210 theme_opportunity_state = 赛道机会强度),
§4.3 (line 133 market-confirmation gate ≥3/7 + line 137 continuous theme_score), §4.5 (line 163 dynamic
seats driven by this state). The 4-state vocab is const-pinned (user-approved 2026-06-22) in
presets/us_short_theme_probe_governance_20260622.json (LOADED); the TRIGGER thresholds are §13.1 #29 forward
priors (module constants, not caller-overridable).

theme_opportunity_state is the SECOND axis of the two-axis environment (the first, market_risk_regime, is the
risk/size cap; this one is the theme-opportunity strength). It is the WEEK-level driver of §4.5 dynamic Top15
seats AND §8 theme_probe seats. v1 determination rule (in-slice design, submitted for review):
  - `extreme`         — a market-confirmed theme (passed the §4.3 ≥3/7 gate) whose continuous theme_score
                        reaches EXTREME_SCORE (主线级: AI 存储/半导体/核电 类).
  - `strong`          — at least one market-confirmed theme (a 强赛道周) below the extreme bar.
  - `normal`          — no market-confirmed theme, but some theme activity (a theme_score ≥ ACTIVITY_FLOOR).
  - `no_strong_theme` — otherwise (the most conservative: fewest theme seats 12+3, no probe).

Determination is PURE (consumes the §4.3 confirmation signals, no provider): each theme is
{market_confirmed: bool, theme_score: float 0-100}. Every public input is fail-closed: `market_confirmed`
strict True, theme_score strict `_finite_number`, a malformed theme is ignored, a non-list / empty pool →
`no_strong_theme` (no opportunity). No A-share crossing. The §4.5 seat-split application is
`engine/us_short_dynamic_seats.py`.
"""
import json
import math
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_theme_probe_governance_20260622.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

THEME_OPPORTUNITY_STATES = tuple(_GOV["theme_opportunity_state_vocab"])   # no_strong_theme<normal<strong<extreme

# §13.1 #29 forward priors (NOT frozen const), module constants. theme_score is the §4.3 continuous 0-100 score.
EXTREME_SCORE = 80.0     # a market-confirmed theme at/above this is 主线级 extreme
ACTIVITY_FLOOR = 20.0    # a theme at/above this counts as activity (normal vs no_strong_theme)


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _theme_score(theme):
    """A theme's continuous §4.3 theme_score (0-100), strict; None if the theme is a non-dict, the score is
    malformed, OR it falls OUTSIDE [0, 100] (a finite score out of the documented domain is a scale /
    normalization bug — it is ignored, NEVER clamped into opportunity, so it can't upgrade the state)."""
    if not isinstance(theme, dict):
        return None
    score = _finite_number(theme.get("theme_score"))
    if score is None or score < 0.0 or score > 100.0:
        return None
    return score


def classify_theme_opportunity_state(themes):
    """§7/§4.5 week-level theme_opportunity_state from the §4.3 theme pool. `themes` is a list of dicts, each
    {market_confirmed: bool (passed the ≥3/7 gate), theme_score: 0-100}. Returns one of THEME_OPPORTUNITY_STATES.
    A market-confirmed theme at/above EXTREME_SCORE → `extreme`; ≥1 market-confirmed theme → `strong`; else a
    theme at/above ACTIVITY_FLOOR → `normal`; otherwise `no_strong_theme`. Fail-closed: a non-list / empty pool,
    or all-malformed themes, → `no_strong_theme` (no measurable opportunity → the most conservative state)."""
    if not isinstance(themes, list):
        return "no_strong_theme"

    confirmed_scores, all_scores = [], []
    for theme in themes:
        score = _theme_score(theme)
        if score is None:
            continue
        all_scores.append(score)
        if isinstance(theme, dict) and theme.get("market_confirmed") is True:
            confirmed_scores.append(score)

    if confirmed_scores:
        if max(confirmed_scores) >= EXTREME_SCORE:
            return "extreme"
        return "strong"
    if any(s >= ACTIVITY_FLOOR for s in all_scores):
        return "normal"
    return "no_strong_theme"
