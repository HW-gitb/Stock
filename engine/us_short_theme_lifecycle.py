# -*- coding: utf-8 -*-
"""US-short theme lifecycle state machine (§4.3) — 5-state lifecycle + transition actions.

Design authority: docs/us_short_system_design.md §4.3; frozen state set + per-state transition-action
table + anti-chatter in presets/us_short_theme_lifecycle_governance_20260620.json (LOADED here so the
effect table is single-sourced from the const-pinned governance, not re-typed).

5 states: provisional_active → confirmed_active (up) … cooling → decayed → retired (decay). The
per-state EFFECTS (theme_seats_multiplier, new_theme_probe_allowed, new_entry_routing, in_theme_table,
holding_effects) are the frozen transition-action table; this engine consumes it. The state-machine
LOGIC is frozen — down-fast (immediate on first deterioration), up-slow (consecutive confirmation),
retired re-entry only via a full provisional re-confirmation — while the transition THRESHOLDS
(breadth / leader_rs / persistence lines, confirmation run counts) are §13.1 #30 forward priors that
the caller classifies into deteriorating / confirming.

§18.0 P0 / §18.1 #14 lifecycle validator: a theme_lifecycle_state MUST land an effect
(seats / probe / routing / a holding effect) so it is never dangling, AND a degraded state tags +
triggers §9 re-eval but NEVER mechanically clears a holding (mechanical_clear is False in every state).
Pure/offline; §8 sizing / §9 action_rank consume these effects. No provider, no A-share crossing.
"""
import copy
import json
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_theme_lifecycle_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

THEME_STATES = tuple(_GOV["states"])                  # frozen 5-state set (§4.3)
TRANSITION_ACTIONS = _GOV["transition_actions"]       # frozen per-state effect table (single source)
_ACTIVE = ("provisional_active", "confirmed_active")  # healthy: normal seats + probe

# decay sequence (down-fast): an active/cooling/decayed theme steps one rung down on deterioration
_DECAY_DOWN = {"provisional_active": "cooling", "confirmed_active": "cooling",
               "cooling": "decayed", "decayed": "retired", "retired": "retired"}
# recovery sequence (up-slow): one rung up per confirmed upgrade (retired is excluded — full re-confirm)
_RECOVER_UP = {"provisional_active": "confirmed_active", "confirmed_active": "confirmed_active",
               "cooling": "provisional_active", "decayed": "provisional_active"}
UPGRADE_CONFIRM_RUNS = 2   # §13.1 #30 forward anti-chatter: consecutive confirming runs needed to step up


def lifecycle_effects(state):
    """Frozen §4.3 transition-action effects for a state, returned as a DEEP COPY so a consumer can
    never mutate the single-source governance table process-wide. Raises KeyError on an unknown state
    (fail closed — no silent default effect)."""
    return copy.deepcopy(TRANSITION_ACTIONS[state])


def next_theme_lifecycle_state(prior_state, deteriorating=False, confirming=False,
                               confirm_count=0, passes_provisional_gate=False,
                               upgrade_confirm_runs=UPGRADE_CONFIRM_RUNS):
    """Frozen §4.3 transition. Deterioration takes precedence over confirmation (down-fast: step down
    immediately). Up-slow: a non-retired state steps up only after `upgrade_confirm_runs` consecutive
    confirming runs. Retired re-entry: only via a full provisional re-confirmation (`passes_provisional_gate`),
    never a direct bounce-back. Returns (next_state, new_confirm_count). The deteriorating / confirming
    classification (vs §13 #30 thresholds) is the caller's. Raises ValueError on an unknown prior_state."""
    if prior_state not in THEME_STATES:
        raise ValueError(f"unknown theme_lifecycle_state {prior_state!r}")
    if not isinstance(upgrade_confirm_runs, int) or isinstance(upgrade_confirm_runs, bool) or upgrade_confirm_runs < 2:
        # up-slow invariant: an upgrade needs ≥ 2 consecutive confirmations; a 0/1 (or non-int) value
        # would weaken anti-chatter to an immediate upgrade → fail closed, never silently bypass it
        raise ValueError(f"upgrade_confirm_runs must be an int ≥ 2 (up-slow consecutive confirmation); "
                         f"got {upgrade_confirm_runs!r}")
    if deteriorating:                                 # down-fast: immediate, reset the confirm streak
        return _DECAY_DOWN[prior_state], 0
    if prior_state == "retired":                      # retired re-entry only through the full provisional gate
        return ("provisional_active", 0) if passes_provisional_gate else ("retired", 0)
    if confirming:                                    # up-slow: need consecutive confirmations
        c = confirm_count + 1
        if c >= upgrade_confirm_runs:
            return _RECOVER_UP[prior_state], 0
        return prior_state, c
    return prior_state, 0                             # stable: hold, reset streak (confirmations must be consecutive)


def validate_lifecycle_landing(state):
    """§18.1 #14 lifecycle validator: True iff the state is non-dangling — an active state's landing
    IS full seats + probe; a degraded state must differ from the active baseline in seats / probe /
    routing / a holding effect. Also enforces the invariant that NO state mechanically clears a holding.
    Raises KeyError on an unknown state."""
    eff = lifecycle_effects(state)
    if eff["holding_effects"]["mechanical_clear"]:    # invariant: degraded states tag + §9-reeval, never auto-clear
        return False
    if state in _ACTIVE:
        return bool(eff["new_theme_probe_allowed"]) and eff["theme_seats_multiplier"] == 1.0
    he = eff["holding_effects"]
    return bool(eff["theme_seats_multiplier"] < 1.0 or not eff["new_theme_probe_allowed"]
                or eff["new_entry_routing"] != "normal"
                or he["action_confidence_down"] or he["theme_decay_tag"] or he["section9_reeval"])
