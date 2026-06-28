# -*- coding: utf-8 -*-
"""US-short risk_downgrade — §4.2 soft 'less attractive as a pick' signals (§5.2 good-data-bad-reaction).

Design authority: docs/us_short_system_design.md §4.2 (risk_downgrade) + §5.2 (好数据坏反应 v1 soft).

`risk_downgrade` is the SUM of soft, never-hard-veto signals that make a stock a less attractive PICK
(it subtracts from core_score, §4.2). v1 carries three:
  * current_good_data_bad_reaction_event (§5.2) — instant, soft, with an SPY/QQQ RELATIVE exemption:
    good earnings (beat) but the stock fell next day IS a stock-specific bad reaction ONLY if the stock
    underperformed the market (stock next-day return <= market return − X); if the stock fell no more
    than the market (stock return > market − X) the fall is systematic and is NOT a downgrade.
  * earnings_reaction_history_score — a slow, multi-quarter habit score; the CURRENT period's event
    does NOT feed it (two-field separation), so one market-wide down day can't permanently tag a stock.
  * a collective analyst downgrade.

Escalating any of these to a hard veto stays the §5.2 candidate path (accrue >= N triggers + manual
review, §13 #7) — NOT done here; this engine is soft-only (`hard_veto` is always False). All thresholds
(exempt margin X, soft point sizes, history cap) are §13.1 #7 forward priors, NOT frozen const.
Pure/offline; no provider, no A-share crossing; §4.2 core_score consumes the points.
"""
import math

# §13.1 #7 forward priors (NOT frozen const)
EXEMPT_MARGIN = 0.02          # SPY/QQQ relative exemption: stock next-day return > market − this → exempt
SOFT_EVENT_PENALTY = 10.0      # soft points for a current good-data-bad-reaction event
HISTORY_PER_QUARTER = 5.0      # soft points per prior bad-reaction quarter (slow-changing habit)
HISTORY_MAX_QUARTERS = 4       # cap on the history lookback
ANALYST_DOWNGRADE_PENALTY = 8.0  # soft points for a collective analyst downgrade


def _strict_true(flag):
    """Only an explicit bool True is a live signal — truthy strings / ints / unknown values are NOT
    (fail closed: a malformed upstream flag must never fabricate a downgrade)."""
    return flag is True


def _finite_number(x):
    """A strictly-typed finite number (int/float, NOT bool, NOT a numeric string); else None. Used for
    point/score fields that must be a real number — a string like "10" fails closed, not parses."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _safe_margin(margin):
    """A relative-exemption margin must be a real, finite, non-negative number (same strict policy as
    the point/score fields: `_finite_number` rejects numeric strings and bools, so `"0.0"` / `"999"` /
    `True` / `False` can't become live overrides). A bad / negative / non-finite value falls back to the
    default so it can't crash, invert, weaken, strengthen, or suppress the exemption gate."""
    m = _finite_number(margin)
    return m if (m is not None and m >= 0.0) else EXEMPT_MARGIN


def current_good_data_bad_reaction_event(earnings_beat, stock_next_day_return, market_next_day_return,
                                         exempt_margin=EXEMPT_MARGIN):
    """§5.2 current event (instant, soft, SPY/QQQ-relative-exempt). A downgrade event fires ONLY when the
    report was good (earnings_beat) AND the stock fell next day (bad reaction) AND it is NOT exempt — i.e.
    the stock underperformed the market by at least exempt_margin (`stock <= market − X`), a stock-specific
    bad reaction rather than a systematic market fall. Returns {is_event, exempt, soft_penalty}. NEVER a
    hard veto; this event does not feed the history score (two-field separation)."""
    s = _finite_number(stock_next_day_return)
    mkt = _finite_number(market_next_day_return)
    if not _strict_true(earnings_beat) or s is None or mkt is None or s >= 0:  # strict beat + a real next-day fall
        return {"is_event": False, "exempt": False, "soft_penalty": 0.0}
    if s > mkt - _safe_margin(exempt_margin):                    # fell no more than the market → systematic
        return {"is_event": False, "exempt": True, "soft_penalty": 0.0}
    return {"is_event": True, "exempt": False, "soft_penalty": SOFT_EVENT_PENALTY}


def earnings_reaction_history_score(bad_reaction_quarters):
    """§5.2 multi-quarter habit (slow-changing). Soft points from the count of PRIOR quarters that showed
    a good-data-bad-reaction pattern, capped. The current period's event does NOT feed this (two-field
    separation) — the caller passes only the prior-quarter count. A non-int / negative count → 0."""
    n = bad_reaction_quarters if isinstance(bad_reaction_quarters, int) and not isinstance(bad_reaction_quarters, bool) else 0
    n = max(0, n)
    return min(n, HISTORY_MAX_QUARTERS) * HISTORY_PER_QUARTER


_RISK_DOWNGRADE_COMPONENTS = ("history", "current_event", "analyst")
_RISK_DOWNGRADE_KEYS = frozenset({"points", "hard_veto", "components"})


def validate_risk_downgrade_input(rd):
    """SINGLE-SOURCE consumer-validation of an INJECTED §4.2 risk_downgrade input — the EXACT typed output of
    `risk_downgrade()` carried on a scored candidate analysis row (batch4 offline / batch5 provider behind the
    same seam). Returns the normalized {points, components} (floats) or raises ValueError (the caller wraps it in
    its own typed error). A scored candidate is NEVER scored on an absent / malformed risk input (缺数据≠安全,
    §3.3). CLOSED-WORLD producer shape: the top-level keys are EXACTLY {points, hard_veto, components} (a missing
    `hard_veto` or any extra key is rejected — not normalized away); `hard_veto` is exactly False (§5.2 soft-only
    — never a hard veto); `points` finite NON-NEGATIVE; `components` = exactly {history, current_event, analyst}
    each finite non-negative; and `points == Σcomponents` (proving it is the genuine engine output, not a forged
    total)."""
    if not (isinstance(rd, dict) and set(rd) == _RISK_DOWNGRADE_KEYS):
        raise ValueError(f"risk_downgrade 输入顶层键须恰为 {sorted(_RISK_DOWNGRADE_KEYS)}（§4.2 typed 引擎输出 closed-world）: {rd!r}")
    if rd["hard_veto"] is not False:
        raise ValueError(f"risk_downgrade.hard_veto 须为 False（§5.2 soft-only）: {rd['hard_veto']!r}")
    pts = _finite_number(rd["points"])
    if pts is None or pts < 0.0:
        raise ValueError(f"risk_downgrade.points 须为有限非负数: {rd['points']!r}")
    comp = rd["components"]
    if not (isinstance(comp, dict) and set(comp) == set(_RISK_DOWNGRADE_COMPONENTS)):
        raise ValueError(f"risk_downgrade.components 须恰为 {list(_RISK_DOWNGRADE_COMPONENTS)}: {comp!r}")
    out, total = {}, 0.0
    for k in _RISK_DOWNGRADE_COMPONENTS:
        cv = _finite_number(comp[k])
        if cv is None or cv < 0.0:
            raise ValueError(f"risk_downgrade.components[{k!r}] 须为有限非负数: {comp[k]!r}")
        out[k] = cv
        total += cv
    if abs(total - pts) > 1e-6:
        raise ValueError(f"risk_downgrade.points {pts!r} != Σcomponents {total!r}（须为引擎 typed 输出）")
    # return the FULL normalized producer shape (hard_veto≡False) so a downstream consumer that re-validates
    # (the machine-record official gate) sees the same closed-world {points, hard_veto, components}.
    return {"points": pts, "hard_veto": False, "components": out}


def risk_downgrade(history_score=0.0, current_event=None, analyst_collective_downgrade=False):
    """§4.2 risk_downgrade = the SUM of the soft signals (history + current event + analyst downgrade),
    NEVER a hard veto. `current_event` is a `current_good_data_bad_reaction_event` result (its penalty
    counts only if `is_event`). Returns {points, hard_veto: False, components} — the components stay
    separate so the current event can't contaminate the slow history score."""
    hsv = _finite_number(history_score)
    hs = max(0.0, hsv) if hsv is not None else 0.0               # non-number / string / NaN / negative history → 0
    # validate the event shape at the API boundary: only an exact-True is_event with a real, finite,
    # NON-NEGATIVE soft_penalty counts — a malformed event (truthy-string is_event, string/None/negative/NaN
    # penalty, or a non-dict) fails closed to 0, never a fabricated penalty, a score boost, NaN/Inf, or crash.
    ev = current_event if isinstance(current_event, dict) else {}
    ev_pts = 0.0
    if _strict_true(ev.get("is_event")):
        p = _finite_number(ev.get("soft_penalty"))
        ev_pts = p if (p is not None and p >= 0.0) else 0.0
    an_pts = ANALYST_DOWNGRADE_PENALTY if _strict_true(analyst_collective_downgrade) else 0.0
    return {"points": hs + ev_pts + an_pts, "hard_veto": False,
            "components": {"history": hs, "current_event": ev_pts, "analyst": an_pts}}
