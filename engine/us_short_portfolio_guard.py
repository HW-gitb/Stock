# -*- coding: utf-8 -*-
"""US-short portfolio-level circuit breaker (§8 组合级熔断) — portfolio_guard_status classifier.

Design authority: docs/us_short_system_design.md §8; frozen state set + per-state effect table +
trigger model + fail-safe in presets/us_short_portfolio_guard_governance_20260620.json (LOADED here).

`portfolio_guard_status` ∈ {normal, caution, cooldown, recovery} (== action_table vocab). The primary
trigger is the model_paper_track (consecutive stops / paper drawdown over threshold); the manual actual
account is secondary/advisory. ADVISORY ONLY — affects advice, never auto-trades. The load-bearing
safety rule (§12.1 / fail-safe): if the paper track is NOT evaluable (`paper_evaluable` not exactly
True) the guard must NEVER be clean — it fails closed to `caution` (no data ≠ safe); malformed metrics
on a claimed-evaluable track fail closed the same way.

Threshold VALUES (consecutive-stop count, drawdown %) are §13.1 #22 forward priors, NOT frozen const.
`portfolio_guard_effects` returns a COPY of the frozen per-state effects (a consumer can't mutate the
table). Every public input is fail-closed (strict). Pure/offline; no provider, no A-share crossing;
§8 sizing consumes the state + effects.
"""
import copy
import json
import math
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_portfolio_guard_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

PORTFOLIO_GUARD_STATES = tuple(_GOV["portfolio_guard_states"])          # frozen vocab
_STATE_EFFECTS = {e["state"]: e["effects"] for e in _GOV["state_effects"]}  # frozen per-state effect table

# §13.1 #22 forward priors (NOT frozen const), module constants (not caller-overridable to avoid bypass).
STOP_COOLDOWN = 3        # >= this many consecutive stops → cooldown
DD_COOLDOWN = 0.10       # paper drawdown >= this fraction → cooldown
DD_CAUTION = 0.05        # paper drawdown >= this fraction → caution


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _count(x):
    """A non-negative INTEGER event count (e.g. consecutive stops): exactly an int (not bool), >= 0. A
    fractional float (incl. integer-valued 3.0), bool, numeric string, negative, NaN/Inf or None is NOT a
    valid count → None (a count is an event tally, not a continuous metric)."""
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    return x if x >= 0 else None


def portfolio_guard_effects(state):
    """Frozen §8 per-state effects, returned as a DEEP COPY so a consumer can't mutate the single-source
    governance table. Raises KeyError on an unknown state (fail closed)."""
    return copy.deepcopy(_STATE_EFFECTS[state])


def classify_portfolio_guard(paper_evaluable, consecutive_stops=0, paper_drawdown_frac=0.0,
                             prior_state="normal"):
    """§8 portfolio_guard_status from the model_paper_track. Returns {state, fail_safe, reason, effects}.
    FAIL-SAFE first: if `paper_evaluable` is not exactly True, or the metrics are malformed on a
    claimed-evaluable track, the guard is `caution` (never clean — no data ≠ safe). `consecutive_stops`
    must be a non-negative INTEGER count (a fractional / bool / string count is malformed → caution) and
    `prior_state` must be a known guard state (a corrupted persisted state fails closed to caution, never
    a clean `normal`). Otherwise: consecutive_stops ≥ STOP_COOLDOWN or drawdown ≥ DD_COOLDOWN → cooldown;
    drawdown ≥ DD_CAUTION → caution; a `cooldown` prior with metrics now within limits → recovery; else
    normal. Advisory only, never a hard veto / auto-trade."""
    if paper_evaluable is not True:
        return _result("caution", True, "paper_track_not_evaluable")
    stops = _count(consecutive_stops)
    dd = _finite_number(paper_drawdown_frac)
    if stops is None or dd is None or dd < 0:
        return _result("caution", True, "malformed_paper_metrics")   # evaluable claimed but data bad → not clean
    if stops >= STOP_COOLDOWN or dd >= DD_COOLDOWN:
        return _result("cooldown", False, "consecutive_stops_or_drawdown")
    if dd >= DD_CAUTION:
        return _result("caution", False, "drawdown_caution")
    if prior_state not in PORTFOLIO_GUARD_STATES:
        return _result("caution", True, "malformed_prior_state")   # corrupted persisted guard state → not clean
    if prior_state == "cooldown":               # was halted, metrics now OK → step out via recovery, not straight to normal
        return _result("recovery", False, "recovering_from_cooldown")
    return _result("normal", False, "within_limits")


def _result(state, fail_safe, reason):
    return {"state": state, "fail_safe": fail_safe, "reason": reason, "effects": portfolio_guard_effects(state)}
