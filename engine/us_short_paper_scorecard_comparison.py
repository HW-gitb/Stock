# -*- coding: utf-8 -*-
"""US-short §12.2 比较轨 two-way scorecard comparison — batch-3 (#13/#24 follow-up): balanced-vs-shadow 双向诚实.

Design authority: docs/us_short_system_design.md §12.2 (双向诚实: 成绩单必须报每档全口径——多买的亏损票 / 成本 /
空仓·现金拖累 / 坏票率, 不只 balanced 错过的大牛, 否则永远得出"赛道越激进越好"的偏结论; ship-gate 隔离: shadow
永不计毕业; theme_off: balanced − theme_off = 赛道边际贡献 #24) / §12 / §18.1 #27 (paper 永不计 full-size ship-gate).
Consumes ``engine.us_short_paper_scorecard.build_paper_scorecard`` outputs (one per scoring_profile's basket).

Pairs the FROZEN scoring_profile set's per-basket scorecards (balanced = the primary, theme_plus / theme_aggressive
/ theme_off = shadow) for a decision_date and answers the §12.2 question "is a heavier theme weight actually
better?" HONESTLY — by reporting each profile's WHOLE-caliber scorecard side by side (so the shadow's extra losers /
cost / cash drag / bad-pick rate are visible, not only its missed winners) plus the per-metric delta vs balanced:

  * ``profiles`` = the 4 embedded de-identified scorecards (full caliber, §12.2 双向全口径) — all sharing the same
    fixed-TopN ``selected_total`` denominator (§12.2 固定 TopN; a mixed-size basket comparison fails closed);
  * ``vs_balanced[shadow]`` = ``{<metric>_delta = shadow − balanced}`` over net_basket / bad_pick_rate /
    total_cost_fraction / win_count / loss_count / unfilled_cash_count (a None net / rate delta when either side is
    unrealized — an open basket is never compared, §12.1 不虚高);
  * ``theme_weight_marginal_net`` = ``balanced.net_basket − theme_off.net_basket`` — the §4.2 theme weight's
    marginal realized contribution (#24 NAV-level; None when either is unrealized);
  * a FROZEN ship-gate-isolation + paper-only ``boundary`` (``track=comparison_non_production`` /
    ``evidence_level=paper`` / ``shadow_counts_ship_gate=False`` / ``full_size_ship_gate_allowed=False``) so a
    consumer can NEVER read a shadow profile, or any paper basket, as full-size ship-gate evidence (§12 / §13 / §18.1 #27).

De-identified (counts / normalized deltas only — the embedded scorecards are de-identified, no tickers). The
path-dependent drawdown (needs the daily NAV path → flows into each scorecard then here), the §12.1 复权/公司行动
evaluability gate (not_evaluable → no upgrade/downgrade conclusion), and the anti-self-deception upgrade gate are
later §12.2 cuts. ``validate_scorecard_comparison`` is CLOSED-WORLD (exact key set + frozen boundary + every
embedded scorecard re-validated + every delta re-derived) so a doctored delta / flipped boundary / smuggled field
fails closed. Pure / offline: arithmetic on dicts; no provider / live / DataHub / network; no A-share crossing;
malformed input fails closed (``ScorecardComparisonError``).
"""
from __future__ import annotations

import datetime

from engine.us_short_core_score import PROFILE_NAMES, PRIMARY_PROFILE
from engine.us_short_paper_scorecard import validate_paper_scorecard

# the §12.2 honest-caliber metrics compared shadow-vs-balanced (drawdown is added once the NAV-path cut lands)
_DELTA_METRICS = ("net_basket", "bad_pick_rate", "total_cost_fraction", "win_count", "loss_count", "unfilled_cash_count")
_THEME_OFF = "theme_off"  # the §4.2/§12.2 #24 theme-weight-zero attribution baseline (a member of the frozen PROFILE_NAMES)
# the FROZEN ship-gate-isolation + paper-only boundary every comparison carries
_BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "paper",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
}
_COMPARISON_KEYS = frozenset({"as_of", "primary_profile", "profiles", "vs_balanced", "theme_weight_marginal_net", "boundary"})
_DELTA_KEYS = frozenset(m + "_delta" for m in _DELTA_METRICS)


class ScorecardComparisonError(ValueError):
    """Raised when the §12.2 two-way scorecard comparison contract is violated (coverage / delta / boundary)."""


def _strict_yyyymmdd(s) -> bool:
    # inlined (with the isascii() guard — the whole-class DATE-ASCII lesson) so this stays jsonschema-free
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return True
    except ValueError:
        return False


def _delta(shadow_v, balanced_v):
    """Numeric ``shadow − balanced`` delta; None if EITHER side is None (an unrealized / undefined metric — e.g. a
    net_basket of an open basket, or a bad_pick_rate with nothing filled — is never compared, §12.1 不虚高)."""
    if shadow_v is None or balanced_v is None:
        return None
    return shadow_v - balanced_v


def _assert_same_denominator(profiles) -> None:
    """§12.2 固定 TopN / 禁止挑样本: every profile's basket MUST share the same fixed-TopN denominator
    (``selected_total``) — a 1-stock shadow basket can never be compared against a 3-stock balanced basket, else
    net / bad-pick / count deltas are not apples-to-apples (the upstream shadow_comparison + de-id summary already
    lock each profile's count to ``min(top_n, pool_size)``). Raises ``ScorecardComparisonError`` on any mismatch."""
    denom = profiles[PRIMARY_PROFILE]["selected_total"]
    for name in PROFILE_NAMES:
        st = profiles[name]["selected_total"]
        if st != denom:
            raise ScorecardComparisonError(
                "all profile scorecards must share the same fixed-TopN denominator (selected_total), §12.2 固定 TopN/禁止挑样本: %s=%d != balanced=%d"
                % (name, st, denom))


def build_scorecard_comparison(scorecards_by_profile, *, as_of) -> dict:
    """Build the §12.2 two-way balanced-vs-shadow comparison from one scorecard per scoring_profile.

    ``scorecards_by_profile`` = ``{profile: build_paper_scorecard output}`` — must cover EXACTLY the frozen
    PROFILE_NAMES (balanced + the 3 shadows), and every scorecard is re-validated (``validate_paper_scorecard``).
    ``as_of`` = the decision_date (YYYYMMDD). Returns the embedded full-caliber scorecards + per-shadow deltas vs
    balanced + the #24 theme-weight marginal net + a frozen ship-gate-isolation / paper-only boundary; re-validated
    through ``validate_scorecard_comparison`` before return. Raises ``ScorecardComparisonError`` /
    ``PaperScorecardError`` on malformed input."""
    if not _strict_yyyymmdd(as_of):
        raise ScorecardComparisonError("as_of must be a strict real YYYYMMDD, got %r" % (as_of,))
    if not isinstance(scorecards_by_profile, dict):
        raise ScorecardComparisonError("scorecards_by_profile must be a dict, got %r" % (type(scorecards_by_profile).__name__,))
    if set(scorecards_by_profile) != set(PROFILE_NAMES):
        raise ScorecardComparisonError(
            "scorecards_by_profile must cover EXACTLY the frozen profiles %s, got %s"
            % (sorted(PROFILE_NAMES), sorted(map(str, scorecards_by_profile))))
    for name in PROFILE_NAMES:
        validate_paper_scorecard(scorecards_by_profile[name])  # each must be a valid de-identified paper scorecard
    _assert_same_denominator(scorecards_by_profile)            # §12.2 固定 TopN: same selected_total across profiles
    balanced = scorecards_by_profile[PRIMARY_PROFILE]
    vs_balanced = {}
    for name in PROFILE_NAMES:
        if name == PRIMARY_PROFILE:
            continue
        s = scorecards_by_profile[name]
        vs_balanced[name] = {m + "_delta": _delta(s[m], balanced[m]) for m in _DELTA_METRICS}
    result = {
        "as_of": as_of,
        "primary_profile": PRIMARY_PROFILE,
        "profiles": {name: scorecards_by_profile[name] for name in PROFILE_NAMES},  # full-caliber, §12.2 双向全口径
        "vs_balanced": vs_balanced,
        "theme_weight_marginal_net": _delta(balanced["net_basket"], scorecards_by_profile[_THEME_OFF]["net_basket"]),
        "boundary": dict(_BOUNDARY),
    }
    validate_scorecard_comparison(result)
    return result


def validate_scorecard_comparison(comparison) -> None:
    """Fail-closed CLOSED-WORLD self-check: the EXACT comparison key set (no smuggled field); the FROZEN
    ship-gate-isolation / paper-only boundary; primary_profile == balanced; a strict REAL as_of; ``profiles``
    covers EXACTLY the frozen profile set, every embedded scorecard re-validates, AND all share the same fixed-TopN
    ``selected_total`` denominator (§12.2 固定 TopN — no mixed basket sizes); ``vs_balanced`` covers EXACTLY
    the shadow profiles with EXACTLY the frozen delta keys, each delta == the re-derived ``shadow − balanced``; and
    ``theme_weight_marginal_net`` == ``balanced.net_basket − theme_off.net_basket``. Raises
    ``ScorecardComparisonError`` / ``PaperScorecardError``."""
    if not isinstance(comparison, dict):
        raise ScorecardComparisonError("comparison must be a dict, got %r" % (type(comparison).__name__,))
    if set(comparison) != _COMPARISON_KEYS:
        raise ScorecardComparisonError(
            "comparison must carry EXACTLY %s (closed-world): missing %s, extra %s"
            % (sorted(_COMPARISON_KEYS), sorted(map(str, _COMPARISON_KEYS - set(comparison))), sorted(map(str, set(comparison) - _COMPARISON_KEYS))))
    if comparison["boundary"] != _BOUNDARY:
        raise ScorecardComparisonError("boundary must be the frozen ship-gate-isolation / paper-only block %r, got %r" % (_BOUNDARY, comparison["boundary"]))
    if comparison["primary_profile"] != PRIMARY_PROFILE:
        raise ScorecardComparisonError("primary_profile must be %r, got %r" % (PRIMARY_PROFILE, comparison["primary_profile"]))
    if not _strict_yyyymmdd(comparison["as_of"]):
        raise ScorecardComparisonError("as_of must be a strict real YYYYMMDD, got %r" % (comparison["as_of"],))
    profiles = comparison["profiles"]
    if not isinstance(profiles, dict) or set(profiles) != set(PROFILE_NAMES):
        raise ScorecardComparisonError(
            "profiles must cover EXACTLY %s, got %s"
            % (sorted(PROFILE_NAMES), sorted(map(str, profiles)) if isinstance(profiles, dict) else type(profiles).__name__))
    for name in PROFILE_NAMES:
        validate_paper_scorecard(profiles[name])  # re-validate every embedded scorecard (closed-world + paper boundary)
    _assert_same_denominator(profiles)            # §12.2 固定 TopN: same selected_total across profiles (no mixed basket sizes)
    balanced = profiles[PRIMARY_PROFILE]
    vs = comparison["vs_balanced"]
    shadow_names = [n for n in PROFILE_NAMES if n != PRIMARY_PROFILE]
    if not isinstance(vs, dict) or set(vs) != set(shadow_names):
        raise ScorecardComparisonError(
            "vs_balanced must cover EXACTLY the shadow profiles %s, got %s"
            % (sorted(shadow_names), sorted(map(str, vs)) if isinstance(vs, dict) else type(vs).__name__))
    for name in shadow_names:
        d = vs[name]
        if not isinstance(d, dict) or set(d) != _DELTA_KEYS:
            raise ScorecardComparisonError("vs_balanced[%r] must carry EXACTLY %s, got %s" % (name, sorted(_DELTA_KEYS), sorted(map(str, d)) if isinstance(d, dict) else type(d).__name__))
        for m in _DELTA_METRICS:
            if d[m + "_delta"] != _delta(profiles[name][m], balanced[m]):
                raise ScorecardComparisonError("vs_balanced[%r].%s_delta inconsistent with the scorecards" % (name, m))
    if comparison["theme_weight_marginal_net"] != _delta(balanced["net_basket"], profiles[_THEME_OFF]["net_basket"]):
        raise ScorecardComparisonError("theme_weight_marginal_net inconsistent with balanced − theme_off net_basket")
