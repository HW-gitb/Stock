# -*- coding: utf-8 -*-
"""US-short per-symbol re-entry cooldown (§8 单票再入场冷静期) — anti-revenge-buy gate.

Design authority: docs/us_short_system_design.md §8; frozen rules in
presets/us_short_symbol_cooldown_governance_20260620.json (LOADED here).

A symbol enters cooldown ONLY after a FILLED-then-failure (filled_then_stop_loss /
filled_then_breakout_failure); an unfilled breakout (never filled) is NOT punished (没进场不罚, §18.1 #16).
During cooldown the action is downgraded to observe. A full re-buy requires ALL of: a new catalyst AND
a new structure AND the cooldown has expired (§8 anti-revenge-buy — all three, never any one).

`symbol_cooldown_status` is the action_table column; `cooldown_until` / `reentry_allowed_reason` are
machine-layer. Cooldown length / recovery params are §13.1 #23 forward priors. Every public input is
strict (only exact True / the exact trigger names count). Pure/offline; no provider, no A-share crossing.
"""
import json
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_symbol_cooldown_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

ENTERS_COOLDOWN_ON = tuple(_GOV["enters_cooldown_on"])      # (filled_then_stop_loss, filled_then_breakout_failure)
REENTRY_REQUIRES = tuple(_GOV["reentry_requires"])         # (new_catalyst, new_structure, cooldown_expired)
DURING_COOLDOWN_ACTION = _GOV["during_cooldown_action"]    # "downgrade_to_observe"


def enters_cooldown(trigger):
    """A symbol enters cooldown ONLY on a FILLED-then-failure trigger (filled_then_stop_loss /
    filled_then_breakout_failure, §8). An unfilled breakout — or any other / unknown / malformed
    trigger — does NOT enter cooldown (没进场不罚: a position that never filled isn't punished). Strict
    membership; returns bool."""
    return trigger in ENTERS_COOLDOWN_ON


def reentry_allowed(new_catalyst, new_structure, cooldown_expired):
    """A full re-buy after cooldown requires ALL of: a new catalyst AND a new structure AND the cooldown
    has expired (§8 anti-revenge-buy — all three, not any one). Each is strict True (a truthy-but-not-True
    flag does NOT satisfy it — fail closed, harder to re-enter). Returns bool."""
    return new_catalyst is True and new_structure is True and cooldown_expired is True


def symbol_cooldown_status(in_cooldown, trigger=None, new_catalyst=False, new_structure=False,
                           cooldown_expired=False):
    """High-level §8 status for a symbol. `in_cooldown` is strict 3-way: exactly True → in cooldown;
    exactly False → not in cooldown; anything else (malformed) fails CLOSED to the in-cooldown/observe
    restriction (a state we can't trust must not yield an unrestricted symbol). When not in cooldown a
    fresh FILLED-then-failure `trigger` puts it into cooldown; while in cooldown the action is downgraded
    to observe UNLESS the full re-entry gate (all three) is satisfied. Returns {status, action,
    reentry_allowed} with status ∈ {none, entering_cooldown, in_cooldown, reentry_allowed}."""
    if in_cooldown is False:
        if enters_cooldown(trigger):
            return {"status": "entering_cooldown", "action": DURING_COOLDOWN_ACTION, "reentry_allowed": False}
        return {"status": "none", "action": None, "reentry_allowed": False}
    if in_cooldown is True and reentry_allowed(new_catalyst, new_structure, cooldown_expired):
        return {"status": "reentry_allowed", "action": None, "reentry_allowed": True}
    # in_cooldown is True (gate not satisfied) OR malformed → fail closed to observe
    return {"status": "in_cooldown", "action": DURING_COOLDOWN_ACTION, "reentry_allowed": False}
