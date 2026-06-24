# -*- coding: utf-8 -*-
"""US-short §12.2 比较轨 multi-week two-way comparison — batch-3 (#13/#24 follow-up): balanced-vs-shadow ≥12 周双向诚实.

Design authority: docs/us_short_system_design.md §12.2 (双向诚实: 成绩单必须报每档全口径——多买亏损票 / 回撤 / 成本 /
现金拖累 / 坏票率, 不只 balanced 错过的大牛, 否则永远得"赛道越激进越好"偏结论; ≥12 周 + 双向全口径净值对比后再升
硬约束 §13; ship-gate 隔离: shadow 永不计毕业; theme_off: balanced − theme_off = 赛道边际 #24) / §12 / §18.1 #27
(paper 永不计 full-size ship-gate). Consumes ``engine.us_short_paper_multiweek_scorecard.build_multiweek_scorecard``
outputs (one per scoring_profile over the SAME forward weeks).

This is the multi-week analog of the single-week ``engine.us_short_paper_scorecard_comparison`` — it pairs the
FROZEN scoring_profile set's per-profile ≥12-week aggregates (balanced = primary, theme_plus / theme_aggressive /
theme_off = shadow) for the SAME forward window and answers the §12.2 question "is a heavier theme weight ACTUALLY
better over the window?" HONESTLY — by reporting each profile's WHOLE-caliber multi-week aggregate side by side
(cumulative losers / cost / cash drag / bad-pick AND the equity-curve drawdown, not only the missed winners) plus
the per-shadow delta vs balanced:

  * ``profiles`` = the 4 embedded de-identified multiweek aggregates (full caliber, §12.2 双向全口径) — all over the
    SAME aligned weeks AND the same fixed-TopN per week (a mis-aligned window / mixed-TopN basket fails closed);
  * ``vs_balanced[shadow]`` = ``{<metric>_delta = shadow − balanced}`` over final_cumulative_net / max_drawdown /
    overall_bad_pick_rate / cum_total_cost_fraction / cum_loss / cum_unfilled_cash / cum_win (a None delta when
    either side is None — an unrealized cumulative net / drawdown / undefined bad-pick is never compared, §12.1 不虚高);
  * ``theme_weight_marginal_net`` = ``balanced.final_cumulative_net − theme_off.final_cumulative_net`` — the §4.2
    theme weight's marginal realized contribution over the window (#24 NAV-level; None when either is unrealized);
  * a FROZEN ship-gate-isolation + paper-only ``boundary`` so a consumer can NEVER read a shadow profile / any paper
    aggregate as full-size ship-gate evidence (§12 / §13 / §18.1 #27).

De-identified (the embedded aggregates are de-identified, no tickers). ``validate_multiweek_comparison`` is
CLOSED-WORLD: it re-validates every embedded aggregate, re-checks the week / fixed-TopN alignment, and RE-DERIVES
every delta + a STRICT numeric-type gate on each delta (None or finite, bool refused — so a `False==0.0` /
`True==1.0` numerically-equal bool can't slip past the `==`), so a doctored delta / flipped boundary / mis-aligned
window fails closed. Pure / offline: arithmetic on dicts; no provider / live / DataHub / network; no A-share
crossing; malformed input fails closed (``MultiweekComparisonError``).
"""
from __future__ import annotations

import math

from engine.us_short_core_score import PROFILE_NAMES, PRIMARY_PROFILE
from engine.us_short_paper_multiweek_scorecard import validate_multiweek_scorecard

# the §12.2 honest-caliber metrics compared shadow-vs-balanced + where each lives in the multiweek aggregate
# (the bottom line + the risk + quality + cost + extra losers + cash drag + winners = the full 双向 caliber)
_METRIC_PATH = {
    "final_cumulative_net": ("nav_drawdown", "final_cumulative_net"),
    "max_drawdown": ("nav_drawdown", "max_drawdown"),
    "overall_bad_pick_rate": ("cumulative", "overall_bad_pick_rate"),
    "cum_total_cost_fraction": ("cumulative", "cum_total_cost_fraction"),
    "cum_loss": ("cumulative", "cum_loss"),
    "cum_unfilled_cash": ("cumulative", "cum_unfilled_cash"),
    "cum_win": ("cumulative", "cum_win"),
}
_DELTA_METRICS = tuple(_METRIC_PATH)
_THEME_OFF = "theme_off"  # the §4.2/§12.2 #24 theme-weight-zero attribution baseline (a member of PROFILE_NAMES)
# the FROZEN ship-gate-isolation + paper-only boundary every comparison carries (mirrors the single-week comparison)
_BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "paper",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
}
_COMPARISON_KEYS = frozenset({"primary_profile", "profiles", "vs_balanced", "theme_weight_marginal_net", "boundary"})
_DELTA_KEYS = frozenset(m + "_delta" for m in _DELTA_METRICS)


class MultiweekComparisonError(ValueError):
    """Raised when the §12.2 multi-week two-way comparison contract is violated (coverage / alignment / delta / boundary)."""


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _metric(mw, m):
    block, key = _METRIC_PATH[m]
    return mw[block][key]


def _delta(shadow_v, balanced_v):
    """Numeric ``shadow − balanced`` delta; None if EITHER side is None (an unrealized / undefined metric — e.g. a
    final_cumulative_net / max_drawdown with no realized week, or an overall_bad_pick_rate with nothing filled — is
    never compared, §12.1 不虚高)."""
    if shadow_v is None or balanced_v is None:
        return None
    return shadow_v - balanced_v


def _window(mw):
    """The aligned-window signature of a multiweek aggregate: the ordered per-week ``(as_of, selected_total)`` — the
    weeks AND the fixed-TopN per week. Two profiles are comparable only if these match exactly (§12.2 PIT-frozen same
    window + 固定 TopN)."""
    return [(it["as_of"], it["scorecard"]["selected_total"]) for it in mw["period_source"]]


def _assert_aligned(profiles) -> None:
    """§12.2 same PIT-frozen window + 固定 TopN: every profile's multiweek aggregate MUST be over the SAME ordered
    weeks AND the same fixed-TopN per week (else cumulative / drawdown / count deltas are not apples-to-apples — a
    profile run over different weeks or a different TopN can't be compared). Raises ``MultiweekComparisonError``."""
    ref = _window(profiles[PRIMARY_PROFILE])
    for name in PROFILE_NAMES:
        w = _window(profiles[name])
        if w != ref:
            raise MultiweekComparisonError(
                "all profile aggregates must be over the SAME aligned weeks + fixed-TopN per week (§12.2 PIT window / 固定 TopN): %s diverges from balanced" % (name,))


def build_multiweek_comparison(multiweek_by_profile) -> dict:
    """Build the §12.2 multi-week balanced-vs-shadow comparison from one multiweek aggregate per scoring_profile.

    ``multiweek_by_profile`` = ``{profile: build_multiweek_scorecard output}`` — must cover EXACTLY the frozen
    PROFILE_NAMES (balanced + the 3 shadows), every aggregate is re-validated, and ALL must be over the same aligned
    weeks + fixed-TopN. Returns the embedded full-caliber aggregates + per-shadow deltas vs balanced + the #24
    theme-weight marginal net + a frozen ship-gate-isolation / paper-only boundary; re-validated through
    ``validate_multiweek_comparison`` before return. Raises ``MultiweekComparisonError`` /
    ``PaperMultiweekScorecardError`` on malformed input."""
    if not isinstance(multiweek_by_profile, dict):
        raise MultiweekComparisonError("multiweek_by_profile must be a dict, got %r" % (type(multiweek_by_profile).__name__,))
    if set(multiweek_by_profile) != set(PROFILE_NAMES):
        raise MultiweekComparisonError(
            "multiweek_by_profile must cover EXACTLY the frozen profiles %s, got %s"
            % (sorted(PROFILE_NAMES), sorted(map(str, multiweek_by_profile))))
    for name in PROFILE_NAMES:
        validate_multiweek_scorecard(multiweek_by_profile[name])  # each must be a valid de-identified multiweek aggregate
    _assert_aligned(multiweek_by_profile)                         # §12.2 same window + fixed-TopN
    balanced = multiweek_by_profile[PRIMARY_PROFILE]
    vs_balanced = {}
    for name in PROFILE_NAMES:
        if name == PRIMARY_PROFILE:
            continue
        s = multiweek_by_profile[name]
        vs_balanced[name] = {m + "_delta": _delta(_metric(s, m), _metric(balanced, m)) for m in _DELTA_METRICS}
    result = {
        "primary_profile": PRIMARY_PROFILE,
        "profiles": {name: multiweek_by_profile[name] for name in PROFILE_NAMES},  # full-caliber, §12.2 双向全口径
        "vs_balanced": vs_balanced,
        "theme_weight_marginal_net": _delta(_metric(balanced, "final_cumulative_net"), _metric(multiweek_by_profile[_THEME_OFF], "final_cumulative_net")),
        "boundary": dict(_BOUNDARY),
    }
    validate_multiweek_comparison(result)
    return result


def validate_multiweek_comparison(comparison) -> None:
    """Fail-closed CLOSED-WORLD self-check: the EXACT comparison key set (no smuggled field); the FROZEN
    ship-gate-isolation / paper-only boundary; primary_profile == balanced; ``profiles`` covers EXACTLY the frozen
    profile set, every embedded aggregate re-validates, AND all share the same aligned weeks + fixed-TopN;
    ``vs_balanced`` covers EXACTLY the shadow profiles with EXACTLY the frozen delta keys, each delta None-or-finite
    (bool refused — a numerically-equal `False==0.0` can't slip past) AND == the re-derived ``shadow − balanced``;
    and ``theme_weight_marginal_net`` None-or-finite AND == ``balanced − theme_off`` final_cumulative_net. Raises
    ``MultiweekComparisonError`` / ``PaperMultiweekScorecardError``."""
    if not isinstance(comparison, dict):
        raise MultiweekComparisonError("comparison must be a dict, got %r" % (type(comparison).__name__,))
    if set(comparison) != _COMPARISON_KEYS:
        raise MultiweekComparisonError(
            "comparison must carry EXACTLY %s (closed-world): missing %s, extra %s"
            % (sorted(_COMPARISON_KEYS), sorted(map(str, _COMPARISON_KEYS - set(comparison))), sorted(map(str, set(comparison) - _COMPARISON_KEYS))))
    if comparison["boundary"] != _BOUNDARY:
        raise MultiweekComparisonError("boundary must be the frozen ship-gate-isolation / paper-only block %r, got %r" % (_BOUNDARY, comparison["boundary"]))
    if comparison["primary_profile"] != PRIMARY_PROFILE:
        raise MultiweekComparisonError("primary_profile must be %r, got %r" % (PRIMARY_PROFILE, comparison["primary_profile"]))
    profiles = comparison["profiles"]
    if not isinstance(profiles, dict) or set(profiles) != set(PROFILE_NAMES):
        raise MultiweekComparisonError(
            "profiles must cover EXACTLY %s, got %s"
            % (sorted(PROFILE_NAMES), sorted(map(str, profiles)) if isinstance(profiles, dict) else type(profiles).__name__))
    for name in PROFILE_NAMES:
        validate_multiweek_scorecard(profiles[name])  # re-validate every embedded aggregate (closed-world + source-traceable)
    _assert_aligned(profiles)                          # §12.2 same window + fixed-TopN
    balanced = profiles[PRIMARY_PROFILE]
    vs = comparison["vs_balanced"]
    shadow_names = [n for n in PROFILE_NAMES if n != PRIMARY_PROFILE]
    if not isinstance(vs, dict) or set(vs) != set(shadow_names):
        raise MultiweekComparisonError(
            "vs_balanced must cover EXACTLY the shadow profiles %s, got %s"
            % (sorted(shadow_names), sorted(map(str, vs)) if isinstance(vs, dict) else type(vs).__name__))
    for name in shadow_names:
        d = vs[name]
        if not isinstance(d, dict) or set(d) != _DELTA_KEYS:
            raise MultiweekComparisonError("vs_balanced[%r] must carry EXACTLY %s, got %s" % (name, sorted(_DELTA_KEYS), sorted(map(str, d)) if isinstance(d, dict) else type(d).__name__))
        for m in _DELTA_METRICS:
            got = d[m + "_delta"]
            if got is not None and not _finite(got):  # STRICT type gate: None or finite (bool refused) BEFORE the == below
                raise MultiweekComparisonError("vs_balanced[%r].%s_delta must be None or a finite number (bool refused), got %r" % (name, m, got))
            if got != _delta(_metric(profiles[name], m), _metric(balanced, m)):
                raise MultiweekComparisonError("vs_balanced[%r].%s_delta inconsistent with the aggregates" % (name, m))
    tw = comparison["theme_weight_marginal_net"]
    if tw is not None and not _finite(tw):
        raise MultiweekComparisonError("theme_weight_marginal_net must be None or a finite number (bool refused), got %r" % (tw,))
    if tw != _delta(_metric(balanced, "final_cumulative_net"), _metric(profiles[_THEME_OFF], "final_cumulative_net")):
        raise MultiweekComparisonError("theme_weight_marginal_net inconsistent with balanced − theme_off final_cumulative_net")
