# -*- coding: utf-8 -*-
"""US-short 强赛道试探名额 theme_probe (§8) — the anti-conservative "弱市强赛道仍能试探" handle.

Design authority: docs/us_short_system_design.md §8 (line 220-224 强赛道试探名额 + line 223 防御档入场);
const-pinned vocab / seat matrix / hard-zero / invariants / defensive-entry in
presets/us_short_theme_probe_governance_20260622.json (LOADED). User-approved 2026-06-22.

A theme_probe is an EXTRA build slot beyond the regime's normal weekly new-build cap, granted ONLY when
there is a market-confirmed strong theme. Seats come from the regime×theme_opportunity_state matrix (#27).
The probe is forced to MINIMUM-executable size + high confidence and bypasses risk-budget amplification, but
STILL stacks under every §8 cap; the cost floor still applies. Hard-zero precedence (before the matrix): an
极度防御 regime, an active per-symbol cooldown, an account-level **portfolio_guard cooldown** (禁新建/加仓,
line 230 — a probe is a new entry), or a hard veto force 0. In a 防御 regime new probes are pullback-only,
the SOLE exception being an `extreme` theme with no weekly gap and entry inside the valid band → 1 breakout
probe.

It also consumes the §4.3 `theme_lifecycle_state` (via `engine/us_short_theme_lifecycle.lifecycle_effects`):
a `cooling` / `decayed` / `retired` theme — or an unknown/missing one — allows NO new probe even if its
`theme_opportunity_state` is still `extreme` (prevents the "only enters, never exits" lifecycle failure).
`coverage_status` is the action_table enum {full, partial, restricted, blocked}; a probe needs a
non-restricted value {full, partial}.

This engine decides seat availability + lifecycle/eligibility gating + the defensive entry-mode constraint;
the caller forces min-executable size (see §8 position sizing), tags `theme_probe_min_size`, and runs the
already-built cost floor (engine/us_short_cost_floor.py). Every public input is fail-closed: each safety
BLOCKER (cooldowns / hard_veto) defaults to BLOCK and must be passed an explicit `False` to clear (a
forgotten safety wire never silently permits a probe); GRANTING flags (high_confidence / no_gap_week /
entry_in_band) are strict True; vocab membership is strict. Pure/offline; no provider, no broker/auto-order,
no A-share crossing.
"""
import json
from pathlib import Path

from engine.us_short_theme_lifecycle import lifecycle_effects

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_theme_probe_governance_20260622.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

THEME_OPPORTUNITY_STATES = tuple(_GOV["theme_opportunity_state_vocab"])   # no_strong_theme<normal<strong<extreme
_SEAT_MATRIX = {row["regime"]: row for row in _GOV["theme_probe_seat_matrix"]}
REGIMES = tuple(_SEAT_MATRIX.keys())                                      # 进攻 / 震荡 / 防御 / 极度防御
RISK_TAG = _GOV["risk_tag"]                                               # theme_probe_min_size

_HARD_ZERO_REGIME = "极度防御"
_DEFENSIVE_REGIME = "防御"
_EXTREME = "extreme"
# §11.3 action_table `coverage_status` enum is {full, partial, restricted, blocked}; a probe needs coverage
# NOT restricted/blocked (§8 coverage 非 restricted) → the non-restricted allow-list is {full, partial}.
COVERAGE_ELIGIBLE = ("full", "partial")


def theme_probe_seats(regime, theme_opportunity_state):
    """§8 #27 seat upper bound for (regime × theme_opportunity_state) from the frozen matrix. An unknown
    regime or theme_opportunity_state fails closed to 0 (no probe on an un-pinned state)."""
    if regime not in _SEAT_MATRIX or theme_opportunity_state not in THEME_OPPORTUNITY_STATES:
        return 0
    return _SEAT_MATRIX[regime][theme_opportunity_state]


def _flag_blocks(flag):
    """A safety-BLOCKING flag fails CLOSED: it blocks the probe if it is True OR malformed (not a clean
    bool). Only an explicit `False` lets the probe past — an unknown / None / non-bool safety state must not
    silently permit a probe."""
    return (not isinstance(flag, bool)) or flag


def hard_zero_for_probe(regime, in_symbol_cooldown=None, in_portfolio_guard_cooldown=None, hard_veto=None):
    """§8 hard-zero precedence (before the matrix and before the defensive exception): an 极度防御 regime,
    an active per-symbol cooldown, an account-level portfolio_guard cooldown (禁新建/加仓, line 230), or a
    hard veto → no probe. The regime is matched exactly; each blocking flag fails closed — True, malformed,
    OR OMITTED (default None) blocks, so a caller must EXPLICITLY pass `False` for every safety state to
    clear it (a forgotten safety wire can never silently permit a probe)."""
    return (regime == _HARD_ZERO_REGIME
            or _flag_blocks(in_symbol_cooldown)
            or _flag_blocks(in_portfolio_guard_cooldown)
            or _flag_blocks(hard_veto))


def defensive_entry_constraint(regime, theme_opportunity_state, no_gap_week=False, entry_in_band=False):
    """§8 line 223 / §9 test #25 defensive-regime entry constraint. In a 防御 regime a new probe is
    `pullback_only`; the SOLE exception (`breakout_exception_allowed`, max 1) is an `extreme` theme with no
    weekly gap AND entry inside the valid band (both strict True). Outside 防御 the rule does not apply →
    `none` (normal entry-mode determination)."""
    if regime != _DEFENSIVE_REGIME:
        return "none"
    if theme_opportunity_state == _EXTREME and no_gap_week is True and entry_in_band is True:
        return "breakout_exception_allowed"
    return "pullback_only"


def lifecycle_allows_probe(theme_lifecycle_state):
    """§4.3: a degraded theme stops new probes — only `provisional_active` / `confirmed_active`
    (`new_theme_probe_allowed=true`) permit one; `cooling` / `decayed` / `retired` (false) do not. Returns
    True ONLY when the lifecycle effect explicitly allows it; a missing / unknown / malformed lifecycle state
    fails closed to False (a theme whose lifecycle we can't read must not be probed — prevents the
    'only enters, never exits' failure)."""
    try:
        effects = lifecycle_effects(theme_lifecycle_state)
    except (KeyError, TypeError):
        return False
    return effects.get("new_theme_probe_allowed") is True


def theme_probe_decision(regime, theme_opportunity_state, theme_lifecycle_state=None, high_confidence=False,
                         coverage_status=None, in_symbol_cooldown=None, in_portfolio_guard_cooldown=None,
                         hard_veto=None, no_gap_week=False, entry_in_band=False):
    """§8 strong-theme probe decision. Returns {probe_allowed, seats, entry_mode_constraint, risk_tag,
    reason}. Order: hard-zero (极度防御 / symbol cooldown / portfolio_guard cooldown / hard_veto) → lifecycle
    permission (§4.3: cooling/decayed/retired allow no new probe) → seat availability (matrix; 0 if no
    confirmed strong theme or unknown state) → eligibility (forced `high_confidence is True` AND
    `coverage_status` ∈ {full, partial}, the action_table non-restricted values) → the 防御-regime entry-mode
    constraint. The allowed probe is min-size (caller-forced) + tagged `theme_probe_min_size` + still subject
    to all §8 caps and the cost floor. Fail-closed: every safety blocker defaults to block (must be passed an
    explicit False), an un-readable lifecycle state blocks, an un-pinned theme state / non-eligible coverage →
    not allowed."""
    if hard_zero_for_probe(regime, in_symbol_cooldown, in_portfolio_guard_cooldown, hard_veto):
        return _blocked("hard_zero")
    if not lifecycle_allows_probe(theme_lifecycle_state):
        return _blocked("lifecycle_no_new_probe")        # §4.3 degraded/retired/unknown theme → no new probe
    seats = theme_probe_seats(regime, theme_opportunity_state)
    if seats <= 0:
        return _blocked("no_seat")                       # no confirmed strong theme (or unknown regime/state)
    if high_confidence is not True or coverage_status not in COVERAGE_ELIGIBLE:
        return _blocked("not_high_confidence_or_coverage_restricted")
    return {
        "probe_allowed": True,
        "seats": seats,
        "entry_mode_constraint": defensive_entry_constraint(regime, theme_opportunity_state, no_gap_week, entry_in_band),
        "risk_tag": RISK_TAG,
        "reason": "probe_eligible",
    }


def _blocked(reason):
    return {"probe_allowed": False, "seats": 0, "entry_mode_constraint": "none", "risk_tag": None, "reason": reason}
