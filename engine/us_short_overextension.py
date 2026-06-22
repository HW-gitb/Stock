# -*- coding: utf-8 -*-
"""US-short overextension tiering (§4.3 过热分档 / §0) — 3-value overheat state, two exclusive tiers.

Design authority: docs/us_short_system_design.md §4.3 (过热分档) + §0 总原则.

`overextension_state` ∈ {none, warning, chasing_extreme} (frozen action_table vocab):
  * warning — mild (close above MA10 + k1×ATR, trend intact / not parabolic): EXECUTION-side only
    (force pullback entry + reduce size + raise the RR gate); KEEPS the full theme score, never drops
    the stock from selection.
  * chasing_extreme — parabolic, only when >= K co-occurring conditions hold (vertical run / daily
    move ≥ m×ATR / volume climax / far above ALL MAs / weak retracement structure); a single big move
    ALONE never triggers it. SELECTION-side: strips the theme-heat score back to momentum+catalyst base.
The two are mutually exclusive (chasing_extreme precedence) so a stock is penalised once (§4.2 single
stage). Thresholds (k1 / m / volume-climax / far-MA distance / min condition count K) are §13.1 #36
forward priors, NOT frozen const. Missing key metrics → 'none' (honest, never fabricated). Pure; no
provider, no A-share crossing.
"""
import math

# §13.1 #36 forward priors (NOT frozen const): the warning band + the multi-condition parabolic gate.
WARNING_MA10_ATR = 1.0        # warning: close > MA10 + this×ATR
DAILY_MOVE_ATR = 2.0          # parabolic condition: daily_change >= this×ATR
VOL_CLIMAX_RATIO = 2.5        # parabolic condition: volume ratio >= this
FAR_MA_ATR = 3.0             # parabolic condition: close - MA20 >= this×ATR (far above all MAs)
CHASING_MIN_CONDITIONS = 3    # chasing_extreme needs >= this many co-occurring conditions (never a single one)

OVEREXTENSION_STATES = ("none", "warning", "chasing_extreme")


def _finite(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def classify_overextension(metrics):
    """metrics = {close, ma5, ma10, ma20, atr, vol_ratio, daily_change, vertical_run, weak_retrace}.
    Returns {overextension_state, strips_theme_score, execution_flags, conditions_met, condition_names}.

    chasing_extreme fires ONLY when >= CHASING_MIN_CONDITIONS parabolic conditions co-occur — a single
    condition (even a huge daily move) never reaches it. warning is the mild execution-side tier that
    KEEPS the theme score. The tiers are mutually exclusive (chasing_extreme precedence). Missing
    close/ATR → 'none' (no fabrication)."""
    m = metrics if isinstance(metrics, dict) else {}
    close, atr = _finite(m.get("close")), _finite(m.get("atr"))
    ma5, ma10, ma20 = _finite(m.get("ma5")), _finite(m.get("ma10")), _finite(m.get("ma20"))
    none_out = {"overextension_state": "none", "strips_theme_score": False,
                "execution_flags": {}, "conditions_met": 0, "condition_names": []}
    if close is None or atr is None or atr <= 0:
        return none_out

    # parabolic conditions (each a boolean; thresholds are §13 #36 forward)
    dc, vr = _finite(m.get("daily_change")), _finite(m.get("vol_ratio"))
    conds = {
        "vertical_run": bool(m.get("vertical_run")),
        "daily_move_ge_m_atr": dc is not None and dc >= DAILY_MOVE_ATR * atr,
        "volume_climax": vr is not None and vr >= VOL_CLIMAX_RATIO,
        "far_above_all_mas": (ma5 is not None and ma10 is not None and ma20 is not None
                              and close > ma5 > ma10 and (close - ma20) >= FAR_MA_ATR * atr),
        "weak_retrace": bool(m.get("weak_retrace")),
    }
    met = [k for k, v in conds.items() if v]

    if len(met) >= CHASING_MIN_CONDITIONS:           # parabolic → strip theme score (selection side)
        return {"overextension_state": "chasing_extreme", "strips_theme_score": True,
                "execution_flags": {}, "conditions_met": len(met), "condition_names": met}

    # warning (precedence: only if NOT chasing) — mild over-MA10, execution side only, KEEPS theme score
    if ma10 is not None and close > ma10 + WARNING_MA10_ATR * atr:
        return {"overextension_state": "warning", "strips_theme_score": False,
                "execution_flags": {"force_pullback": True, "reduce_size": True, "raise_rr_gate": True},
                "conditions_met": len(met), "condition_names": met}

    # not extended enough for either tier — report the actual conditions met (honest diagnostics; the
    # early none_out above keeps met=0 only because conditions were never computed on missing close/ATR)
    return {"overextension_state": "none", "strips_theme_score": False,
            "execution_flags": {}, "conditions_met": len(met), "condition_names": met}
