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

`compute_overextension_metrics(closes, volumes)` builds the pattern metrics this classifier consumes
(ma5 / ma10 / ma20 / vol_ratio / daily_change / vertical_run / weak_retrace) from a clean oldest→newest
close (+ aligned volume) series — the same volume-bearing daily series the §4.2 momentum engine already
parses; the caller merges the §6 price-indicator `close` + `atr` in before classifying. Each metric is an
honest None / False when its window is missing / short / bad (never fabricated); its windows / thresholds
are §13.1 #36 forward priors too.

`compute_overextension_features(ohlcv_series)` is the per-ticker producer entry: it PIT-parses a dated OHLCV
daily series (the Pass-1 grouped-daily reconstruction), computes ATR via the §6 price engine (high/low/close)
+ the metrics above (close/volume), and returns the classify_overextension tier (+ `disposition` / `pit`).
It is computed at the SCORING stage (before ranking) so `chasing_extreme` can strip theme at the §4.3
selection layer; a point dated after `as_of` is BLOCKED (no look-ahead), mirroring the momentum engine's PIT.
"""
import math
from datetime import datetime

from engine.us_short_price_engine import atr as price_engine_atr

# §13.1 #36 forward priors (NOT frozen const): the warning band + the multi-condition parabolic gate.
WARNING_MA10_ATR = 1.0        # warning: close > MA10 + this×ATR
DAILY_MOVE_ATR = 2.0          # parabolic condition: daily_change >= this×ATR
VOL_CLIMAX_RATIO = 2.5        # parabolic condition: volume ratio >= this
FAR_MA_ATR = 3.0             # parabolic condition: close - MA20 >= this×ATR (far above all MAs)
CHASING_MIN_CONDITIONS = 3    # chasing_extreme needs >= this many co-occurring conditions (never a single one)

OVEREXTENSION_STATES = ("none", "warning", "chasing_extreme")


def _finite(x):
    # strict: a real finite int/float only — NOT a bool, NOT a numeric string ("5" must fail closed, not
    # parse). A metric that isn't a clean number must not parse into a parabolic condition. A legitimate huge
    # int (abs ≳ 1.8e308) that overflows float() is CONTAINED to None (never a raw OverflowError) — the metrics
    # layer below is RAW-FACING (raw closes/volumes), so a forged/corrupt huge value must disposition like any
    # other bad value, not bare-crash a caller (mirrors engine/us_short_momentum.py::_finite, this session's
    # whole-class huge-int hardening).
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        xf = float(x)
    except OverflowError:
        return None
    return xf if math.isfinite(xf) else None


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


# ── §4.3 pattern-metrics layer (§13.1 #36 forward priors, NOT frozen const) ────────────────
# The classifier above consumes {close, ma5, ma10, ma20, atr, vol_ratio, daily_change, vertical_run,
# weak_retrace}. close + atr come from the §6 price indicators; this layer computes the REST from a clean
# oldest→newest close (+ aligned volume) series (the momentum engine's parsed shape). Windows/thresholds
# are §13.1 #36 priors, calibrated forward like the classifier's k1/m/K — nothing here is frozen const.
VOL_CLIMAX_BASELINE = 20      # vol_ratio = today volume / mean(prior VOL_CLIMAX_BASELINE volumes) — "量能高潮"
                              #   (a today-vs-baseline CLIMAX ratio; deliberately NOT the momentum vol_surge 10/63,
                              #   which is an elevated-10d-vs-63d SURGE — different window + semantics)
VERTICAL_RUN_DAYS = 4         # vertical_run = this many consecutive strictly-up closes ("连续垂直"); the AND-of-K
                              #   gate in the classifier supplies specificity, so a moderate run signal is fine
WEAK_RETRACE_WINDOW = 10      # window for the retracement-structure check ("回撤结构差")
WEAK_RETRACE_MIN_RUNUP = 0.10 # only a REAL run-up qualifies: net window gain must be >= this
WEAK_RETRACE_MIN_RUNUP_EX_LAST = 0.05  # ...AND the run-up must EXIST before the final bar (window[0]→[-2] >= this),
                                       #   so a lone last-day gap-up is NOT a weak-retrace STRUCTURE — a single
                                       #   move alone must never reach chasing_extreme (§4.3 绝不因单条件误判)
WEAK_RETRACE_MAX_DRAWDOWN = 0.05  # ...AND the deepest pullback from any running peak stayed < this (shallow retrace)


def _sma(closes, n):
    """Simple moving average of the last n closes (each strictly-positive finite), else None (honest)."""
    if len(closes) < n:
        return None
    vals = [_finite(c) for c in closes[-n:]]
    if any(v is None or v <= 0.0 for v in vals):
        return None
    return sum(vals) / n


def _daily_change(closes):
    """Signed close-to-close change (today − prior) — "当日涨幅"; the classifier compares it to m×ATR, so an
    UP move (positive) can trip the parabolic daily-move condition while a down day (negative) cannot. Needs
    two strictly-positive finite closes, else None."""
    if len(closes) < 2:
        return None
    prev, last = _finite(closes[-2]), _finite(closes[-1])
    if prev is None or last is None or prev <= 0.0 or last <= 0.0:
        return None
    return last - prev


def _vol_ratio(volumes):
    """Volume climax ratio = today's volume / mean(prior VOL_CLIMAX_BASELINE volumes). Needs the last
    VOL_CLIMAX_BASELINE+1 volumes all finite non-negative and a positive baseline average, else None (a
    single missing/None recent volume → unavailable, never fabricated)."""
    w = VOL_CLIMAX_BASELINE
    if len(volumes) < w + 1:
        return None
    today = _finite(volumes[-1])
    base = [_finite(v) for v in volumes[-1 - w:-1]]
    if today is None or today < 0.0 or any(v is None or v < 0.0 for v in base):
        return None
    avg = sum(base) / w
    if avg <= 0.0:
        return None
    return today / avg


def _vertical_run(closes):
    """True iff the last VERTICAL_RUN_DAYS transitions are all strictly up (a continuous vertical run). Needs
    VERTICAL_RUN_DAYS+1 strictly-positive finite closes; a missing/bad/non-up value → False (never fabricated)."""
    n = VERTICAL_RUN_DAYS
    if len(closes) < n + 1:
        return False
    window = [_finite(c) for c in closes[-(n + 1):]]
    if any(v is None or v <= 0.0 for v in window):
        return False
    return all(window[i] > window[i - 1] for i in range(1, len(window)))


def _weak_retrace(closes):
    """True iff over the last WEAK_RETRACE_WINDOW closes the stock ran up (net gain >= WEAK_RETRACE_MIN_RUNUP)
    over a SUSTAINED structure — the run-up must already exist before the final bar (window[0]→[-2] >=
    WEAK_RETRACE_MIN_RUNUP_EX_LAST) AND the deepest pullback from any running peak stayed shallow (<
    WEAK_RETRACE_MAX_DRAWDOWN). A flat/quiet window (no run-up) OR a lone last-day gap-up (no run-up before the
    final bar) is NOT weak_retrace — so a single move alone never contributes this parabolic condition (§4.3
    绝不因单条件误判). Needs WEAK_RETRACE_WINDOW strictly-positive finite closes, else False."""
    w = WEAK_RETRACE_WINDOW
    if len(closes) < w:
        return False
    window = [_finite(c) for c in closes[-w:]]
    if any(v is None or v <= 0.0 for v in window):
        return False
    if window[-1] / window[0] - 1.0 < WEAK_RETRACE_MIN_RUNUP:            # only a real net run-up can be "weak retrace"
        return False
    if window[-2] / window[0] - 1.0 < WEAK_RETRACE_MIN_RUNUP_EX_LAST:    # ...that EXISTS before the final bar —
        return False                                                    # a lone last-day gap-up is not a structure
    peak, max_dd = window[0], 0.0
    for c in window:
        if c > peak:
            peak = c
        dd = (peak - c) / peak                                  # drawdown from the running peak (peak > 0)
        if dd > max_dd:
            max_dd = dd
    return max_dd < WEAK_RETRACE_MAX_DRAWDOWN


def compute_overextension_metrics(closes, volumes):
    """Build the §4.3 pattern metrics `classify_overextension` consumes — {ma5, ma10, ma20, vol_ratio,
    daily_change, vertical_run, weak_retrace} — from a clean oldest→newest close (+ aligned volume) series
    (the §4.2 momentum engine's parsed `closes` / `volumes`). `close` + `atr` come from the §6 price
    indicators (NOT here); the caller merges them in before classifying. Each metric is an honest None /
    False when its window is missing / short / bad — never fabricated. Pure; strict finite (bool /
    numeric-string / NaN / Inf / overflowing huge-int are treated as unavailable, never a raw crash — this
    layer is raw-facing)."""
    closes = list(closes) if isinstance(closes, (list, tuple)) else []
    volumes = list(volumes) if isinstance(volumes, (list, tuple)) else []
    return {
        "ma5": _sma(closes, 5),
        "ma10": _sma(closes, 10),
        "ma20": _sma(closes, 20),
        "vol_ratio": _vol_ratio(volumes),
        "daily_change": _daily_change(closes),
        "vertical_run": _vertical_run(closes),
        "weak_retrace": _weak_retrace(closes),
    }


# ── §4.3 per-ticker producer entry (PIT-bearing OHLCV series → overextension tier) ─────────
# The Pass-1 scoring stage (where the grouped-daily OHLCV series lives) calls this per eligible ticker to get
# the overextension tier BEFORE ranking — so `chasing_extreme` can strip theme at the §4.3 selection layer.
# ATR needs high/low/close (the §6 price engine); the cut-1 metrics need close/volume; both come from the ONE
# OHLCV series. PIT: a point dated after `as_of` is BLOCKED — its values are never validated, so a future
# spike can neither leak into (no look-ahead: a future parabola must not make today chasing_extreme) nor
# over-reject a valid ≤as_of series (mirrors engine/us_short_momentum.py::_parse_dated_series).
_OHLCV_SERIES_KEYS = {"as_of", "session", "adjustment_mode", "points"}
_OHLCV_POINT_REQUIRED = {"date", "high", "low", "close"}
_OHLCV_POINT_ALLOWED = {"date", "open", "high", "low", "close", "volume"}


def _valid_date(s):
    """Strict YYYY-MM-DD → datetime.date, else None (no other format, no timezone games)."""
    if not (isinstance(s, str) and len(s) == 10):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_ohlcv_series(series):
    """Validate + PIT-cut an OHLCV dated series → {as_of, session, adjustment_mode, dates, highs, lows,
    closes, volumes} or None (fail-closed). Mirrors the momentum engine's PIT semantics: the RAW axis must be
    strictly ascending + unique BEFORE the cut; a point dated after `as_of` is BLOCKED (its values are never
    validated → a future non-finite/spike bar can neither leak nor over-reject a valid ≤as_of series, no
    look-ahead); each KEPT bar must be a clean positive bar (high ≥ low > 0, close > 0) or the WHOLE series
    fails (a hole would corrupt ATR/pattern math). Volume is finite-non-negative or None."""
    if not (isinstance(series, dict) and set(series) == _OHLCV_SERIES_KEYS):
        return None
    as_of = _valid_date(series["as_of"])
    if as_of is None:
        return None
    session, adj = series["session"], series["adjustment_mode"]
    if not (isinstance(session, str) and session and isinstance(adj, str) and adj):
        return None
    pts = series["points"]
    if not isinstance(pts, list) or not pts:
        return None
    dates, highs, lows, closes, vols = [], [], [], [], []
    prev = None
    for p in pts:
        if not (isinstance(p, dict) and _OHLCV_POINT_REQUIRED <= set(p) <= _OHLCV_POINT_ALLOWED):
            return None
        d = _valid_date(p["date"])
        if d is None:
            return None
        if prev is not None and d <= prev:
            return None                       # raw axis must be strictly ascending + unique (corrupt → None)
        prev = d
        if d <= as_of:                        # PIT cut: future points BLOCKED (values not even validated)
            hi, lo, cl = _finite(p["high"]), _finite(p["low"]), _finite(p["close"])
            if hi is None or lo is None or cl is None or not (hi >= lo > 0.0 and cl > 0.0):
                return None                   # a malformed kept bar corrupts ATR/pattern math → fail closed
            dates.append(d)
            highs.append(hi)
            lows.append(lo)
            closes.append(cl)
            fv = _finite(p["volume"]) if p.get("volume") is not None else None
            vols.append(fv if (fv is None or fv >= 0.0) else None)   # negative volume is malformed → None
    if not dates:
        return None
    return {"as_of": as_of, "session": session, "adjustment_mode": adj,
            "dates": dates, "highs": highs, "lows": lows, "closes": closes, "volumes": vols}


def compute_overextension_features(ohlcv_series):
    """Per-ticker §4.3 overextension tier from a PIT-bearing OHLCV daily series (the producer's grouped-daily
    reconstruction). Returns the `classify_overextension` result plus `disposition` ∈ {scored,
    insufficient_data} and `pit`. ATR = the §6 price engine on the PIT-cut high/low/close; MA/vol/pattern =
    `compute_overextension_metrics` on the closes/volumes; close = the last PIT close. A malformed / empty /
    all-future series → insufficient_data ('none', never fabricated); a series too short for ATR (< the price
    engine's window) also dispositions insufficient_data (classify honestly returns 'none' on a missing ATR).
    Pure; no look-ahead (future points are PIT-cut before any metric is computed)."""
    insufficient = {"overextension_state": "none", "strips_theme_score": False, "execution_flags": {},
                    "conditions_met": 0, "condition_names": [], "disposition": "insufficient_data", "pit": None}
    parsed = _parse_ohlcv_series(ohlcv_series)
    if parsed is None:
        return insufficient
    closes, volumes = parsed["closes"], parsed["volumes"]
    bars = [{"high": h, "low": l, "close": c} for h, l, c in zip(parsed["highs"], parsed["lows"], closes)]
    # `_finite` re-contains the ATR: it is None when the series is too short for the price engine's window, AND
    # when a forged/huge high overflows the TR sum to inf (atr() sums finite TRs but the sum can overflow AFTER
    # each input passed `_finite`). Re-containing here makes the disposition + classify AGREE ("scored" ⟺ a real
    # FINITE ATR classification ran) — else `inf > 0` would mislabel an unclassifiable ticker "scored".
    a = _finite(price_engine_atr(bars))
    result = classify_overextension({**compute_overextension_metrics(closes, volumes),
                                     "close": closes[-1], "atr": a})
    result["disposition"] = "scored" if (a is not None and a > 0.0) else "insufficient_data"
    result["pit"] = {"as_of": parsed["as_of"].isoformat(), "session": parsed["session"],
                     "adjustment_mode": parsed["adjustment_mode"], "n_points": len(closes)}
    return result
