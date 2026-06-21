# -*- coding: utf-8 -*-
"""US-short forward known-date events (§8.1) — window + direction-aware effect + sensitive-type data gap.

Design authority: docs/us_short_system_design.md §8.1 (未来已知事件日历).

Known-date forward events (earnings / index_inclusion / fda_pdufa / lockup_expiry / ex_dividend) within
a forward window (default 3 weeks) influence sizing / risk / display ONLY — they NEVER enter the
selection score and NEVER hard-veto (§8.1 不进选股分). Each has a fixed direction:
  * earnings → reduce-or-observe (临近财报降仓/可转观察)
  * lockup_expiry / fda_pdufa → reduce-caution (减/谨慎)
  * index_inclusion → bounded-positive (有界正向, discounted if already priced in)
  * ex_dividend → price-note (价格口径提示; ordinary = tag only)
`event_sensitive_type` makes a MISSING forward-event date worse than a plain unknown for sensitive
names: a biotech with no FDA/PDUFA date → at least restricted; a recent IPO/SPAC with no lockup date →
reduce-caution; an ordinary large-cap with no index event → a tag only.

Effect magnitudes / window length are §13.1 #15 forward priors, NOT frozen const. Every public input is
validated fail-closed (whole-class incl. default params): `event_type` / `event_sensitive_type` are set
membership (unknown → safe default), `days_to_event` / `window_days` use a strict `_finite_number`. Pure/
offline; no provider, no A-share crossing; §8 sizing / §9 action_rank / §11 display consume these.
"""
import math

WINDOW_DAYS = 21.0   # §13.1 #15 forward: default forward window = 3 weeks
EVENT_TYPES = ("earnings", "index_inclusion", "fda_pdufa", "lockup_expiry", "ex_dividend")
SENSITIVE_TYPES = ("biotech", "recent_ipo", "spac", "ordinary")   # canonical; spac variants accepted, unknown → fail closed

# Direction-aware effect per event type (§8.1; magnitudes are §13 #15 forward).
_EVENT_DIRECTION = {
    "earnings": "reduce_or_observe",
    "lockup_expiry": "reduce_caution",
    "fda_pdufa": "reduce_caution",
    "index_inclusion": "bounded_positive",
    "ex_dividend": "price_note",
}
_NONE = "none"


def _finite_number(x):
    """Strictly-typed finite number (int/float, NOT bool, NOT a numeric string); else None — so a
    malformed day count / window can't be parsed into a live value."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _safe_window(window_days):
    """Forward window must be a real, finite, positive number; a malformed / non-positive override falls
    back to the default (it can't crash or open an unbounded / empty window)."""
    w = _finite_number(window_days)
    return w if (w is not None and w > 0) else WINDOW_DAYS


def forward_event_effect(event_type, days_to_event, window_days=WINDOW_DAYS):
    """A known-date forward event in [0, window] days → its direction-aware effect (§8.1). Returns
    {event_type, in_window, days_to_event, direction}. An unknown event_type, a past (days < 0) /
    out-of-window / malformed `days_to_event`, or a malformed window → not in window (direction 'none').
    Forward events affect sizing/risk/display only, never a hard veto."""
    et = event_type if event_type in EVENT_TYPES else None
    d = _finite_number(days_to_event)
    wd = _safe_window(window_days)
    in_window = et is not None and d is not None and 0.0 <= d <= wd
    return {"event_type": et, "in_window": in_window,
            "days_to_event": d, "direction": _EVENT_DIRECTION[et] if in_window else _NONE}


def event_data_gap_status(event_sensitive_type, has_event_data):
    """§8.1 event_sensitive_type — a MISSING forward-event date is NOT a plain unknown for sensitive names
    (§8.1 / §3.5 缺数据≠普通 unknown). Returns {status} ∈ {ok, restricted, reduce_caution, tag}:
    `has_event_data` exactly True → ok; biotech (no FDA/PDUFA) → restricted; recent_ipo / SPAC (no lockup)
    → reduce_caution; an EXPLICIT ordinary large-cap → tag (only this is a label-only gap). An UNKNOWN /
    malformed `event_sensitive_type` (None / bool / unrecognised) with missing data FAILS CLOSED to
    restricted — it must never pass as an ordinary tag. The type is normalised (trim + lower) so case /
    whitespace variants resolve; `has_event_data` is strict (only exact True counts as present)."""
    if has_event_data is True:
        return {"status": "ok"}
    t = event_sensitive_type.strip().lower() if isinstance(event_sensitive_type, str) else None
    if t == "biotech":
        return {"status": "restricted"}
    if t in ("recent_ipo", "spac", "recent_spac", "recent_ipo_spac"):
        return {"status": "reduce_caution"}
    if t == "ordinary":
        return {"status": "tag"}                       # ONLY an explicit ordinary name is a label-only gap
    return {"status": "restricted"}                    # unknown / malformed type + missing data → fail closed
