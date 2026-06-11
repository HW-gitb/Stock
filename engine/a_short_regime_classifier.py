"""A-short V14.3 raw market-regime classifier (design slice 2a — pure logic, comparison-only).

This module is the **per-day raw** classifier only: given a trailing daily-feature history
(rows matching ``schemas/a_short_market_regime_daily.schema.json``), it returns the raw regime
label for ``as_of`` by the top-down priority defense → contraction → attack → shock(residual),
faithfully evaluating the const-pinned thresholds in
``presets/a_short_v14_3_regime_governance_20260611.json``.

Boundary (hard): **comparison-only, non-production.** It does NOT fetch data, does NOT touch the
EGS run, does NOT drive Phase 5 / veto / sizing, and does NOT auto-switch. V14.2 stays the frozen
production baseline. The multi-day **state machine** (confirm-days, hysteresis, cross-level jumps)
and scoring are slice 3 — this module records the per-day rule hits so slice 3 can apply
confirmation on top, but applies none itself.

Data producer (the in-EGS daily-feature materialization + the incremental 252d ledger) is slice 2b;
this module is deliberately producer-agnostic so it can be unit-tested with synthetic history.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_PATH = ROOT / "presets" / "a_short_v14_3_regime_governance_20260611.json"

RAW_REGIMES = ("defense", "contraction", "attack", "shock")
# V14.2 production regime labels (mirrors analysis_input market_regime.status enum, incl. 'unknown').
V14_2_REGIMES = ("attack", "shock", "defense", "contraction", "unknown")
# The fired-rule key each raw regime may carry — single source for classifier, validator, schema test.
FIRED_RULES_BY_REGIME = {
    "defense": ("iv_percentile_252d_gt_90", "limit_down_count_ge_max_p95_100",
                "broad_index_crash", "exhaustion"),
    "contraction": ("streak_collapse", "earning_effect_gone", "slow_bleed"),
    "attack": ("attack_all_of",),
    "shock": ("residual",),
}
# Forward-return measurement basis, const-pinned so every comparison record is comparable.
# CSI1000 (000852.SH) is the breadth-sensitive small/mid index the regime's limit/breadth signals
# track; the evidence question is "after V14.3 calls defense/contraction, did the market fall?",
# so a market-level RAW (not excess) forward return is the aligned outcome. Pinned, not silently
# defaulted — revisit only at the switch-candidate slice with review.
FORWARD_RETURN_BASIS = {
    "benchmark": "000852.SH",
    "benchmark_name": "CSI1000",
    "measure": "forward_close_to_close_simple_return",
    "horizons_trading_days": {"h1": 1, "h3": 3, "h5": 5, "h10": 10},
    "unit": "percent",
    "price_basis": "index_close_unadjusted",
    "cost_basis": "gross",
    "scope": "market_level_regime_indicator",
}
PERCENTILE_WINDOW = 252  # rolling trading-day window, <= as_of only (PIT)

# Metrics whose trailing-window percentiles the thresholds reference, and which percentiles.
# Kept in code AND pinned against the governance strings by a parity test, so code/governance
# cannot silently drift.
_PERCENTILE_NEEDS = {
    "limit_down_count": (25, 95),
    "failed_limit_rate": (50, 75),
    "max_limit_streak": (75,),
    "promotion_rate": (60,),
}


def _load_governance() -> dict:
    return json.loads(GOVERNANCE_PATH.read_text(encoding="utf-8"))


def _to_rows(history: Iterable[dict]) -> list[dict]:
    """Sort the daily-feature rows ascending by ``as_of`` (string YYYYMMDD sorts chronologically)."""
    rows = [dict(r) for r in history]
    rows.sort(key=lambda r: str(r.get("as_of", "")))
    return rows


def _trailing_window(rows: list[dict], window: int) -> list[dict]:
    return rows[-window:] if window and len(rows) > window else rows


def _percentile(values: list[float], q: float) -> float | None:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return float(np.percentile(np.asarray(vals, dtype=float), q))


def resolve_percentiles(rows: list[dict], window: int = PERCENTILE_WINDOW) -> dict:
    """Compute the trailing-window percentiles the thresholds need, from non-null values only.

    Returns ``{metric: {pNN: value|None}}`` plus ``_window_n`` (non-null counts are per metric).
    The window is the last ``window`` rows of an already-PIT (<= as_of) history.
    """
    win = _trailing_window(rows, window)
    out: dict = {"_window_n": len(win)}
    for metric, qs in _PERCENTILE_NEEDS.items():
        series = [r.get(metric) for r in win]
        out[metric] = {f"p{q}": _percentile(series, q) for q in qs}
        out[metric]["_n"] = sum(1 for v in series if v is not None)
    return out


# ---- threshold resolvers (mirror the governance const strings; parity-tested) -----------------

def _attack_streak_min(pc):   # "max(P75_252, 5)"
    p = pc["max_limit_streak"]["p75"]
    return max(p, 5) if p is not None else 5


def _attack_promotion_min(pc):  # "max(P60_252, 0.50)"
    p = pc["promotion_rate"]["p60"]
    return max(p, 0.50) if p is not None else 0.50


def _attack_limit_down_ceiling(pc):  # "min(50, max(P25_252, 10))" — a CEILING, not a floor
    p = pc["limit_down_count"]["p25"]
    return min(50, max(p, 10)) if p is not None else min(50, 10)


def _defense_limit_down_floor(pc):  # "max(P95_252, 100)"
    p = pc["limit_down_count"]["p95"]
    return max(p, 100) if p is not None else 100


# ---- consecutive / recent-day operands -------------------------------------------------------

def _last_n(rows: list[dict], n: int) -> list[dict]:
    return rows[-n:] if len(rows) >= n else rows


def _consecutive_lt(rows: list[dict], metric: str, threshold: float, days: int) -> bool:
    """True iff the last ``days`` rows ALL have a non-null ``metric`` strictly < ``threshold``.

    Requires at least ``days`` rows; a null in the window breaks the streak (honest, never coerce).
    """
    if len(rows) < days:
        return False
    window = rows[-days:]
    for r in window:
        v = r.get(metric)
        if v is None or not (float(v) < threshold):
            return False
    return True


# ---- per-rule predicates (faithful to governance thresholds) ---------------------------------

def _defense_hits(today: dict, pc: dict) -> list[str]:
    hits = []
    iv = today.get("iv_percentile_252d")
    if iv is not None and float(iv) > 90.0:
        hits.append("iv_percentile_252d_gt_90")
    ld = today.get("limit_down_count")
    if ld is not None and float(ld) >= _defense_limit_down_floor(pc):
        hits.append("limit_down_count_ge_max_p95_100")
    c1000 = today.get("csi1000_ret_1d")
    c300 = today.get("csi300_ret_1d")
    if (c1000 is not None and float(c1000) <= -3.5) or (c300 is not None and float(c300) <= -3.0):
        hits.append("broad_index_crash")
    pr = today.get("promotion_rate")
    nl = today.get("net_limit")
    flr = today.get("failed_limit_rate")
    p75_flr = pc["failed_limit_rate"]["p75"]
    if (pr is not None and float(pr) <= 0.10 and nl is not None and float(nl) < 0
            and flr is not None and p75_flr is not None and float(flr) > p75_flr):
        hits.append("exhaustion")
    return hits


def _contraction_hits(rows: list[dict], today: dict, pc: dict) -> list[str]:
    hits = []
    # streak_collapse: max_limit_streak<=3 AND recent_3d_peak_streak>=5 AND streak_drop>=2
    streak = today.get("max_limit_streak")
    last3 = [r.get("max_limit_streak") for r in _last_n(rows, 3)]
    last3 = [v for v in last3 if v is not None]
    if streak is not None and last3:
        peak3 = max(float(v) for v in last3)
        if float(streak) <= 3 and peak3 >= 5 and (peak3 - float(streak)) >= 2:
            hits.append("streak_collapse")
    # earning_effect_gone: promotion_rate<0.25 for 2 consecutive days AND failed_limit_rate>P75_252
    flr = today.get("failed_limit_rate")
    p75_flr = pc["failed_limit_rate"]["p75"]
    if (_consecutive_lt(rows, "promotion_rate", 0.25, 2)
            and flr is not None and p75_flr is not None and float(flr) > p75_flr):
        hits.append("earning_effect_gone")
    # slow_bleed: pct_above_ma20<30 for 5 consecutive days AND csi1000_below_ma20
    if _consecutive_lt(rows, "pct_above_ma20", 30.0, 5) and today.get("csi1000_below_ma20") is True:
        hits.append("slow_bleed")
    return hits


def _attack_all_satisfied(today: dict, pc: dict) -> bool:
    """attack = ALL of the 6 operands; any null operand fails the gate (never hard-judge attack)."""
    streak = today.get("max_limit_streak")
    pr = today.get("promotion_rate")
    nl = today.get("net_limit")
    ld = today.get("limit_down_count")
    flr = today.get("failed_limit_rate")
    iv = today.get("iv_percentile_252d")
    p50_flr = pc["failed_limit_rate"]["p50"]
    if any(v is None for v in (streak, pr, nl, ld, flr, iv)) or p50_flr is None:
        return False
    return (
        float(streak) >= _attack_streak_min(pc)
        and float(pr) >= _attack_promotion_min(pc)
        and float(nl) > 0
        and float(ld) <= _attack_limit_down_ceiling(pc)
        and float(flr) <= p50_flr
        and float(iv) <= 80.0
    )


# ---- public entry point ----------------------------------------------------------------------

def classify_raw_regime(history: Iterable[dict], as_of: str | None = None,
                        window: int = PERCENTILE_WINDOW) -> dict:
    """Classify the raw regime for the latest (or ``as_of``) row by top-down priority.

    ``history`` = daily-feature rows (each matching the daily schema), any order. The latest row
    at/<= ``as_of`` is "today"; percentiles use the trailing ``window`` of rows <= today.

    Returns a dict with: ``as_of``, ``raw_regime`` in :data:`RAW_REGIMES`, ``fired_rule`` (the
    winning rule key or ``"residual"``), ``candidate_hits`` (per-priority hit lists, so slice 3 can
    apply confirm-days), ``window_n``, ``insufficient_window`` (bool), ``data_quality_flags``, and
    ``boundary`` (comparison_only / non-production). No state machine, no confirmation applied here.
    """
    rows = _to_rows(history)
    if as_of is not None:
        rows = [r for r in rows if str(r.get("as_of", "")) <= str(as_of)]
    if not rows:
        raise ValueError("classify_raw_regime: empty history (no rows at/<= as_of)")
    today = rows[-1]
    eff_as_of = str(today.get("as_of"))

    pc = resolve_percentiles(rows, window)
    window_n = pc["_window_n"]
    insufficient = window_n < window

    flags = list(today.get("data_quality_flags") or [])
    if insufficient and "insufficient_252d_window" not in flags:
        flags.append("insufficient_252d_window")
    if today.get("csi1000_below_ma20") is None and "csi1000_unavailable" not in flags:
        # surfaced for visibility; the slow_bleed operand simply cannot fire (treated as not-below)
        flags.append("csi1000_unavailable")

    defense = _defense_hits(today, pc)
    contraction = _contraction_hits(rows, today, pc)
    attack = _attack_all_satisfied(today, pc)

    if defense:
        regime, fired = "defense", defense[0]
    elif contraction:
        regime, fired = "contraction", contraction[0]
    elif attack:
        regime, fired = "attack", "attack_all_of"
    else:
        regime, fired = "shock", "residual"

    return {
        "as_of": eff_as_of,
        "raw_regime": regime,
        "fired_rule": fired,
        "candidate_hits": {
            "defense": defense,
            "contraction": contraction,
            "attack": ["attack_all_of"] if attack else [],
        },
        "window_n": window_n,
        "insufficient_window": insufficient,
        "data_quality_flags": flags,
        "boundary": {"production": False, "comparison_only": True,
                     "drives_phase5_risk_posture": False},
    }


def build_comparison_record(history: Iterable[dict], v14_2_regime: str,
                            forward_returns: dict | None = None,
                            as_of: str | None = None,
                            generated_at: str | None = None,
                            window: int = PERCENTILE_WINDOW) -> dict:
    """Assemble one weekly comparison record: V14.2 production regime vs V14.3 raw regime.

    ``forward_returns`` maps horizon → realized forward return on :data:`FORWARD_RETURN_BASIS`
    (CSI1000 raw forward close-to-close return, NOT excess) keyed ``h1``/``h3``/``h5``/``h10``; any
    horizon not yet elapsed must be passed ``None`` (NEVER fabricated — that would be look-ahead),
    and is backfilled by a later run. The record is comparison-only and drives nothing. The result
    is self-validated (cross-field invariants + full schema) before return.
    """
    if v14_2_regime not in V14_2_REGIMES:
        raise ValueError(f"build_comparison_record: v14_2_regime {v14_2_regime!r} not in {V14_2_REGIMES}")
    raw = classify_raw_regime(history, as_of=as_of, window=window)
    fr = dict(forward_returns or {})
    horizons = {h: fr.get(h, None) for h in ("h1", "h3", "h5", "h10")}
    pending = [h for h in ("h1", "h3", "h5", "h10") if horizons[h] is None]
    record = {
        "schema_name": "a_short_regime_comparison_weekly",
        "schema_version": "1.0.0",
        "as_of": raw["as_of"],
        "generated_at": generated_at,
        "v14_2_regime": v14_2_regime,
        "v14_3_raw_regime": raw["raw_regime"],
        "divergence": v14_2_regime != raw["raw_regime"],
        "v14_3_fired_rule": raw["fired_rule"],
        "v14_3_window_n": raw["window_n"],
        "v14_3_insufficient_window": raw["insufficient_window"],
        "data_quality_flags": raw["data_quality_flags"],
        "forward_returns": horizons,
        "forward_returns_pending": pending,
        "backfill_complete": not pending,
        "forward_return_basis": dict(FORWARD_RETURN_BASIS),
        "boundary": {"production": False, "comparison_only": True,
                     "drives_phase5_risk_posture": False,
                     "mixes_with_overlay_star_or_m67_action": False},
    }
    validate_comparison_record(record)   # producer self-checks cross-field invariants
    return record


_HORIZONS = ("h1", "h3", "h5", "h10")


COMPARISON_SCHEMA_PATH = ROOT / "schemas" / "a_short_regime_comparison_weekly.schema.json"


def validate_comparison_record(record: dict) -> bool:
    """Sanctioned validity gate for a comparison record; raise ``ValueError`` on ANY invalidity.

    Runs BOTH (a) full JSON-Schema validation against
    ``schemas/a_short_regime_comparison_weekly.schema.json`` — field-local types/enums/consts,
    required keys, exact horizon keys, number|null forward-return values — and (b) the cross-field
    invariants schema cannot express: ``divergence == (v14_2 != v14_3_raw)``; ``fired_rule`` is a
    rule of ``v14_3_raw_regime``; ``forward_returns_pending`` equals exactly the null horizons;
    ``backfill_complete == (no nulls)``; basis equals the pinned one. Any schema error is reported
    as ``ValueError`` (single exception contract). Use BEFORE a record is written or counted toward
    switch-candidate evidence.
    """
    import jsonschema  # runtime validation dep (see SKILL.md); local import keeps classify dep-free

    errs = []
    try:
        schema = json.loads(COMPARISON_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(record, schema)
    except jsonschema.ValidationError as exc:
        errs.append(f"schema: {exc.message}")
    v2 = record.get("v14_2_regime")
    raw = record.get("v14_3_raw_regime")
    if v2 not in V14_2_REGIMES:
        errs.append(f"v14_2_regime {v2!r} not in {V14_2_REGIMES}")
    if raw not in RAW_REGIMES:
        errs.append(f"v14_3_raw_regime {raw!r} not in {RAW_REGIMES}")
    if record.get("divergence") != (v2 != raw):
        errs.append(f"divergence {record.get('divergence')!r} != (v14_2 {v2!r} != v14_3_raw {raw!r})")
    fr_rule = record.get("v14_3_fired_rule")
    if raw in FIRED_RULES_BY_REGIME and fr_rule not in FIRED_RULES_BY_REGIME[raw]:
        errs.append(f"fired_rule {fr_rule!r} not a rule of regime {raw!r} ({FIRED_RULES_BY_REGIME.get(raw)})")
    fwd = record.get("forward_returns") or {}
    # Non-finite guard: JSON Schema accepts NaN/+Inf/-Inf as "number", but they are not valid
    # forward-return observations and would emit non-standard JSON / poison the evidence clock.
    for h in _HORIZONS:
        v = fwd.get(h)
        if v is not None and isinstance(v, (int, float)) and not math.isfinite(float(v)):
            errs.append(f"forward_returns.{h} is non-finite ({v!r}); must be a finite number or null")
    null_h = sorted(h for h in _HORIZONS if fwd.get(h) is None)
    pending = sorted(record.get("forward_returns_pending") or [])
    if pending != null_h:
        errs.append(f"forward_returns_pending {pending} != null horizons {null_h}")
    if record.get("backfill_complete") != (len(null_h) == 0):
        errs.append(f"backfill_complete {record.get('backfill_complete')!r} != (no nulls = {len(null_h) == 0})")
    if record.get("forward_return_basis") != FORWARD_RETURN_BASIS:
        errs.append("forward_return_basis does not match the const-pinned FORWARD_RETURN_BASIS")
    if errs:
        raise ValueError("invalid comparison record: " + "; ".join(errs))
    return True
