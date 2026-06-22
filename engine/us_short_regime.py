# -*- coding: utf-8 -*-
"""US-short market risk-regime engine (§7) — the worst_of risk axis → position cap.

Design authority: docs/us_short_system_design.md §7; frozen policy in
presets/us_short_regime_governance_20260620.json (consumed here).

Computes `market_risk_regime = worst_of(VIX, market_trend, breadth)` → position cap
(进攻 1.0 / 震荡 0.8 / 防御 0.5 / 极度防御 0.0), with anti-chatter (downgrade fast / upgrade
slow — an upgrade needs 2 consecutive better runs) and unknown-degradation (NEVER default
aggressive on incomplete data; missing critical → ≥ 防御; severe data loss → restricted).

This is the RISK axis ONLY (it caps size). The other axis — `theme_opportunity_state` — is
§4.3-theme-driven and its vocabulary is design-deferred (only 'extreme' appears, §8), so it
is intentionally OUT of this slice; the two-axis split (weak market + strong theme still
probes) is realized in §8 sizing, which consumes this cap plus the theme axis.

VIX is provider-authorization-gated (§3 / SR-PROVIDER-001): an unapproved/unavailable VIX is
just an `unknown` axis here (never fetched), and the regime falls back to trend+breadth. The
worst_of / anti-chatter / unknown / cap POLICY is frozen; the threshold VALUES (VIX 18/25/35,
trend/breadth lines) are §13.1 #3 forward priors, NOT frozen const. Pure/offline; affects
sizing / new-entry permission, NEVER a hard veto, NEVER replaces per-stock analysis. No
A-share crossing.
"""
import math

# Frozen regime identity, severity ASCENDING (进攻 least defensive … 极度防御 most), §7.
REGIMES = ("进攻", "震荡", "防御", "极度防御")
_SEVERITY = {r: i for i, r in enumerate(REGIMES)}
UNKNOWN = "unknown"

# Frozen cap ladder (== presets/us_short_regime_governance_20260620.json market_risk_regime_caps;
# a conformance test triangulates engine == preset so this consumer copy cannot silently drift).
POSITION_CAP = {"进攻": 1.0, "震荡": 0.8, "防御": 0.5, "极度防御": 0.0}

_RISK_AXES = ("vix", "market_trend", "breadth")
CRITICAL_AXES = ("market_trend",)   # §7: the QQQ-required market trend is the critical axis
UPGRADE_CONFIRM_RUNS = 2            # frozen anti-chatter: an upgrade needs this many consecutive better runs

# §13.1 #3 forward priors (design-hinted VIX cut points 18/25/35), NOT frozen const.
VIX_CUTS = ((18.0, "进攻"), (25.0, "震荡"), (35.0, "防御"))  # value < cut → that regime; ≥ last bound → 极度防御


def classify_vix(value):
    """VIX value → risk regime tier (§13.1 #3 forward thresholds). None / non-finite → 'unknown'
    (never guessed; an unknown VIX degrades the regime via fallback, it does not pass as 进攻)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return UNKNOWN
    if not math.isfinite(v):
        return UNKNOWN
    for cut, regime in VIX_CUTS:
        if v < cut:
            return regime
    return "极度防御"


def _more_defensive(a, b):
    return a if _SEVERITY[a] >= _SEVERITY[b] else b


def _bump(regime, steps):
    return REGIMES[min(_SEVERITY[regime] + steps, len(REGIMES) - 1)]


def compute_market_risk_regime(axis_regimes, prior_regime=None, prior_upgrade_count=0):
    """axis_regimes = {'vix': r|'unknown'|None, 'market_trend': ..., 'breadth': ...}, r ∈ REGIMES.

    Pipeline (frozen §7 policy): worst_of(available axes) → never-default-aggressive degradation on
    any missing/unknown axis (each missing axis adds a conservative downgrade tier; missing the
    critical trend axis floors at 防御; no axis usable → restricted + 极度防御) → anti-chatter vs the
    prior regime (a downgrade applies immediately; an upgrade needs UPGRADE_CONFIRM_RUNS consecutive
    better runs). Returns the effective regime, its frozen cap, new-entry permission, a restricted
    flag, the raw (pre-anti-chatter) regime, and the new upgrade-confirmation count. Pure."""
    present = {k: v for k, v in (axis_regimes if isinstance(axis_regimes, dict) else {}).items()
               if k in _RISK_AXES and v in _SEVERITY}        # keep only valid regime values
    missing = set(_RISK_AXES) - set(present)

    restricted = False
    if not present:                                          # severe: nothing usable → restricted, most defensive
        raw, restricted = "极度防御", True
    else:
        raw = None
        for v in present.values():
            raw = v if raw is None else _more_defensive(raw, v)   # worst_of
        if missing:                                          # never default aggressive: more missing → more defensive
            raw = _bump(raw, len(missing))                   # (each missing axis incl. an unavailable VIX = one tier)
        if missing.intersection(CRITICAL_AXES):              # missing the critical (QQQ-required) trend → ≥ 防御
            raw = _more_defensive(raw, "防御")

    # anti-chatter: downgrade (or equal) immediate; upgrade requires consecutive confirmation
    if prior_regime not in _SEVERITY:
        effective, upgrade_count = raw, 0
    elif _SEVERITY[raw] >= _SEVERITY[prior_regime]:          # same / more defensive → apply now
        effective, upgrade_count = raw, 0
    else:                                                    # less defensive (upgrade) → confirm first
        upgrade_count = prior_upgrade_count + 1
        if upgrade_count >= UPGRADE_CONFIRM_RUNS:
            effective, upgrade_count = raw, 0
        else:
            effective = prior_regime                         # hold the more-defensive prior until confirmed

    cap = POSITION_CAP[effective]
    return {
        "market_risk_regime": effective,
        "position_cap": cap,
        "new_entry_permitted": cap > 0.0,                    # 极度防御 cap 0 → no new entry (§8 consumes this)
        "restricted": restricted,
        "raw_regime": raw,
        "upgrade_count": upgrade_count,
        "missing_axes": sorted(missing),
    }
