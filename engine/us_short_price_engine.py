# -*- coding: utf-8 -*-
"""US-short price engine (§6 + §6.1) — v1's 2 real engines, pure price geometry.

Design authority: ``docs/us_short_system_design.md`` §6 (价格引擎 + 交易质量) / §6.1 (持仓价位映射).

Two real engines (the §6 contract — no third engine in v1; ``ema_trailing_engine`` /
``earnings_gap_engine`` are §13 #6 registered-not-implemented and NOT emitted here):

  * ``support_atr_engine``  — new-entry / add: effective support/resistance (de-spiked) +
    ATR define entry band, protective stop, take-profit, RR gate, side-aware tick rounding,
    and a post-round RR recheck. Two ``price_sub_mode``: ``pullback`` (回踩) / ``breakout``
    (突破: failure line as stop, chase cap, ATR fallback take-profit, higher RR floor).
  * ``holding_exit_engine`` — holding: passive trailing stop / take-profit / event clear
    reference levels (§6.1: v1 emits base levels only; active scale-out logic is §13 #34).

Mirrors the proven A-short geometry in ``runners/a_short_phase5_engine.py``
(``effective_support`` / ``effective_resistance`` / side-aware ``_tick`` / ``exit_and_size``
post-round recheck / ``holding_levels`` trailing ratchet), which the design explicitly says
to mirror. US differences: $0.01 tick with a sub-penny ($0.0001, price < $1) carve-out
(§3.4); no limit-up/down so long wicks are more extreme → de-spike matters more (§6);
**sizing is NOT here** — this engine is pure price geometry, §8 owns shares.

Numeric thresholds are §13.1 forward-calibration PRIORS (engine defaults), NOT frozen
const — there is deliberately no ``us_short`` price governance preset (the action_table
contract leaves ``structure_quality`` / ``min_rr_gate_status`` / ``post_round_rr_status`` /
``gap_policy`` as un-tokenized deferred-vocab columns, and the de-spike/RR/breakout numbers
calibrate forward via ``us_short_lifecycle_eval`` §13). Each prior is tagged with its §13.1
item below.

Output conforms to the frozen ``us_short_action_table_contract`` price columns + locked
vocab (``price_engine_used`` / ``price_sub_mode`` / ``order_type`` / ``order_expiry``); the
batch-3 no-dangling / evidence-traceback validator CONSUMES this — it is not run here.
Pure/offline; VIX etc. never touched; no provider/live/DataHub; no A-share crossing.
"""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP, ROUND_DOWN

# ── Forward-calibration priors (engine defaults; NOT frozen const — §13.1 items) ───────────
# Regime labels are owned by §7 (us_short_regime_governance); the price engine only looks up
# regime-keyed priors with a neutral default, so an unrecognized regime degrades safely.
_NEUTRAL_RR_FLOOR = 1.5
_NEUTRAL_ATR_MULT = 1.25

RR_FLOOR = {"进攻": 1.5, "震荡": 1.5, "防御": 2.0, "极度防御": 2.0}   # §13 #16 min_rr_gate (defensive stricter)
ATR_MULT = {"进攻": 1.75, "震荡": 1.25, "防御": 1.0, "极度防御": 1.0}  # §13 #4/#33 trailing-stop / pullback-stop ATR multiple
BREAKOUT_RR_BONUS = 0.5        # §13 #16/#33 breakout entry sits above price → higher RR floor (+0.5)
BREAKOUT_FAIL_ATR = 0.5        # §13 #33 breakout failure line = effective_resistance − this×ATR (近期突破位下沿, NOT far structure)
BREAKOUT_CHASE_ATR = 0.5       # §13 #33/#13 breakout chase cap (valid_entry_high) = close + this×ATR
BREAKOUT_TP_ATR = 3.0          # §13 #20 突破 tp ATR 倍数: breakout take-profit (no overhead resistance) = close + this×ATR
PULLBACK_BAND_ATR = 0.5        # §13 #13 pullback valid_entry_low = max(support, close − this×ATR)
TP2_RISK_MULT = 2.0            # §13 #20 second take-profit floor = close + this×risk
SR_SPIKE_ATR = 1.0            # §13 #24 de-spike: single-day extreme > this×ATR beyond 2nd value → wick
SR_LOOKBACK = 20             # support/resistance window
ATR_WINDOW = 14

SR_QUALITY = ("strong", "weak", "fallback_extreme")

# US tick: $0.01 normally; $0.0001 sub-penny for 0 < price < $1.00 (§3.4 microstructure).
_TICK_PENNY = Decimal("0.01")
_TICK_SUBPENNY = Decimal("0.0001")
_SUBPENNY_PRICE = 1.00

PRICE_ENGINES = ("support_atr_engine", "holding_exit_engine")
PRICE_SUB_MODES = ("pullback", "breakout")

# Frozen action_table_contract price columns each engine populates (subset; values default
# to None and are filled progressively — honest partial output on observe, never fabricated).
NEW_ENTRY_COLUMNS = (
    "order_type", "entry_plan", "pullback_entry_price", "breakout_entry_price",
    "limit_order_price", "valid_entry_low", "valid_entry_high", "order_expiry",
    "gap_policy", "effective_support", "effective_resistance", "structure_quality",
    "stop_clear_price", "take_profit_reduce_price", "take_profit_exit_price",
    "event_clear_reference_price", "risk_reward_ratio", "min_rr_gate_status",
    "post_round_rr_status", "price_engine_used", "price_sub_mode",
)
HOLDING_COLUMNS = (
    "effective_support", "effective_resistance", "structure_quality",
    "stop_clear_price", "take_profit_reduce_price", "take_profit_exit_price",
    "event_clear_reference_price", "risk_reward_ratio", "min_rr_gate_status",
    "post_round_rr_status", "price_engine_used", "price_sub_mode",
)


# ── side-aware tick (Decimal; None / non-finite → None, never fabricate a price) ───────────
def tick_size_for(price):
    """US tick: $0.01 normally; $0.0001 sub-penny for 0 < price < $1.00 (§3.4)."""
    try:
        pf = float(price)
    except (TypeError, ValueError):
        return _TICK_PENNY
    if math.isfinite(pf) and 0 < pf < _SUBPENNY_PRICE:
        return _TICK_SUBPENNY
    return _TICK_PENNY


def _tick(x, rounding, tick_size):
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return float(Decimal(str(xf)).quantize(tick_size, rounding=rounding))


def tick_ref(x, tick_size):
    """Display / reference price: half-up to tick."""
    return _tick(x, ROUND_HALF_UP, tick_size)


def tick_up(x, tick_size):
    """Stop: round up to tick (executable stop is not below the system risk line)."""
    return _tick(x, ROUND_UP, tick_size)


def tick_down(x, tick_size):
    """Take-profit / band ceiling: round down to tick (don't overstate a target)."""
    return _tick(x, ROUND_DOWN, tick_size)


# ── indicators (pure; bars oldest→newest, each {high, low, close}) ────────────────────────
def atr(bars, n=ATR_WINDOW):
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(len(bars) - n, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def effective_support(bars, atr_val):
    """De-spiked structural support (§6, mirrors A-short #5). raw_low = min(window low). If the
    lowest low is more than SR_SPIKE_ATR×ATR below the 2nd-lowest → single-day wick, take the
    2nd-lowest (quality 'weak'); else the extreme is backed (quality 'strong'). ATR missing /
    window < 2 → fall back to raw_low (quality 'fallback_extreme', never fabricate structure).
    Returns (support, quality, recent_low)."""
    lows = [b["low"] for b in bars[-SR_LOOKBACK:]]
    if not lows:
        return None, None, None
    raw_low = min(lows)
    if atr_val is None or atr_val <= 0 or len(lows) < 2:
        return raw_low, "fallback_extreme", raw_low
    second_low = sorted(lows)[1]
    if second_low - raw_low > SR_SPIKE_ATR * atr_val:
        return second_low, "weak", raw_low
    return raw_low, "strong", raw_low


def effective_resistance(bars, atr_val):
    """De-spiked structural resistance (§6, symmetric to effective_support). raw_high = max(window
    high). If the highest high is more than SR_SPIKE_ATR×ATR above the 2nd-highest → wick, take the
    2nd-highest (quality 'weak'); else 'strong'. ATR missing / window < 2 → fall back to raw_high
    ('fallback_extreme'). Returns (resistance, quality, recent_high). Drives the new-entry t1/RR
    numerator AND the holding trailing-stop basis (recent_high − ATR×mult), so de-spiking it keeps
    both from being distorted by a single-day spike."""
    highs = [b["high"] for b in bars[-SR_LOOKBACK:]]
    if not highs:
        return None, None, None
    raw_high = max(highs)
    if atr_val is None or atr_val <= 0 or len(highs) < 2:
        return raw_high, "fallback_extreme", raw_high
    second_high = sorted(highs)[-2]
    if raw_high - second_high > SR_SPIKE_ATR * atr_val:
        return second_high, "weak", raw_high
    return raw_high, "strong", raw_high


def compute_price_indicators(bars):
    """Pure: ATR + de-spiked effective support/resistance + qualities. Missing → None (honest)."""
    a = atr(bars)
    sup, sup_q, recent_low = effective_support(bars, a)
    res, res_q, recent_high = effective_resistance(bars, a)
    return {
        "atr": a,
        "effective_support": sup, "support_quality": sup_q, "recent_low": recent_low,
        "effective_resistance": res, "resistance_quality": res_q, "recent_high": recent_high,
    }


def _result(executable, engine, fields, reason, tick_size, regime, trace_extra=None):
    trace = {"execution_tick": float(tick_size), "regime": regime}
    if trace_extra:
        trace.update(trace_extra)
    return {
        "executable": executable,
        "price_engine_used": engine,
        "price_sub_mode": fields.get("price_sub_mode"),
        "action_fields": fields,
        "reject_reason": reason,
        "trace": trace,
    }


def _indicators(inp):
    return inp.get("indicators") or compute_price_indicators(inp.get("bars") or [])


# ── §6 support_atr_engine (new-entry / add; pure geometry, NO sizing) ──────────────────────
def support_atr_engine(inp, regime, sub_mode="pullback"):
    """New-entry / add price plan. ``inp`` = {close, bars | indicators}. Returns a price-result
    dict: ``executable`` (could a valid buy plan be built?) + ``action_fields`` (frozen
    action_table price columns, None where not computable — never fabricated) + ``reject_reason``
    + ``trace``. Degrade-to-observe on missing close/ATR/structure. ``sub_mode`` ∈ {pullback,
    breakout}; an unknown sub_mode is treated as pullback (safe default)."""
    if sub_mode not in PRICE_SUB_MODES:
        sub_mode = "pullback"
    f = {c: None for c in NEW_ENTRY_COLUMNS}
    f["price_engine_used"] = "support_atr_engine"
    f["price_sub_mode"] = sub_mode
    f["entry_plan"] = sub_mode
    f["order_type"] = "breakout_stop_limit" if sub_mode == "breakout" else "pullback_limit"
    f["order_expiry"] = "first_regular_session_only"
    f["gap_policy"] = "limit_band_first_session_no_chase"  # §2.1 跳空校准 (deferred-vocab free string)

    inp = inp if isinstance(inp, dict) else {}   # malformed / non-dict inp → degrade-to-observe, never raw AttributeError
    close = inp.get("close")
    ind = _indicators(inp)
    sup, res, a = ind.get("effective_support"), ind.get("effective_resistance"), ind.get("atr")
    f["effective_support"], f["effective_resistance"] = sup, res
    # structure_quality = reliability of the structure the protective stop relies on
    f["structure_quality"] = ind.get("resistance_quality") if sub_mode == "breakout" else ind.get("support_quality")
    tick = tick_size_for(close)

    def observe(reason):
        return _result(False, "support_atr_engine", f, reason, tick, regime)

    if close is None or a is None or a <= 0:
        return observe("缺价/ATR,无法精算入场结构")

    # sub-mode geometry: stop basis + entry band (raw, pre-tick)
    if sub_mode == "breakout":
        if res is None:
            return observe("缺有效压力,无法定位突破失效线")
        # failure line = just below the broken structural level (NOT the far 20-day support)
        stop_raw = res - BREAKOUT_FAIL_ATR * a
        valid_low_raw, valid_high_raw = close, close + BREAKOUT_CHASE_ATR * a
    else:  # pullback
        if sup is None:
            return observe("缺有效支撑,无法精算止损")
        if sup >= close:  # support must be BELOW price for a pullback; support≥close is not a valid low-absorb structure
            return observe("有效支撑≥现价,非有效低吸结构,转观察")
        stop_raw = sup - ATR_MULT.get(regime, _NEUTRAL_ATR_MULT) * a
        valid_low_raw, valid_high_raw = max(sup, close - PULLBACK_BAND_ATR * a), close

    if stop_raw >= close:
        return observe("止损≥现价(明显无效结构)")
    risk = close - stop_raw
    rr_floor = RR_FLOOR.get(regime, _NEUTRAL_RR_FLOOR) + (BREAKOUT_RR_BONUS if sub_mode == "breakout" else 0.0)
    use_structural_res = bool(res is not None and res > close)
    if use_structural_res:
        t1_raw, t1_basis = res, "structural_resistance"
    elif sub_mode == "breakout":
        t1_raw, t1_basis = close + BREAKOUT_TP_ATR * a, "breakout_atr_fallback"  # §13 #20 突破无上方阻力 → ATR 倍数兜底
    else:
        t1_raw, t1_basis = close + rr_floor * risk, "rr_floor_fallback"
    t2_raw = max(t1_raw + ATR_MULT.get(regime, _NEUTRAL_ATR_MULT) * a, close + TP2_RISK_MULT * risk)

    rr_ref = (t1_raw - close) / risk if risk > 0 else 0.0
    if rr_ref < rr_floor:
        f["risk_reward_ratio"] = round(rr_ref, 3)
        f["min_rr_gate_status"] = "fail_below_floor"
        return observe(f"RR {rr_ref:.2f} < {rr_floor}")

    # side-aware tick = final executable price, then re-check structure post-round
    entry_t = tick_ref(close, tick)
    stop_t = tick_up(stop_raw, tick)
    t1_t = tick_down(t1_raw, tick)
    t2_t = tick_down(t2_raw, tick)
    if None in (entry_t, stop_t, t1_t, t2_t):
        f["post_round_rr_status"] = "broke_after_round"
        return observe("价格非有限,取整失败")
    if not (stop_t < entry_t and t1_t > entry_t and t2_t >= t1_t):
        f["post_round_rr_status"] = "broke_after_round"
        return observe("取整后结构失效(止损≥入/止盈≤入/盈二<盈一)")

    # entry band (side-aware: low up, high down). A contradictory/degenerate band is a structural
    # invalidity, NOT something to rescue into a current-price plan → fail closed to observe.
    valid_low_t = tick_up(valid_low_raw, tick)
    valid_high_t = tick_down(valid_high_raw, tick)
    if valid_low_t is None or valid_high_t is None or valid_low_t > valid_high_t:
        f["post_round_rr_status"] = "broke_after_round"
        return observe("入场区间取整后失效(low>high 或非有限),转观察")

    # worst-case RR re-check at the band ceiling (don't ship a plan that's only OK at the best fill)
    risk_eh = valid_high_t - stop_t
    if risk_eh <= 0:
        f["post_round_rr_status"] = "broke_after_round"
        return observe("区间上沿≤止损(最不利价无效)")
    rr_eh = (t1_t - valid_high_t) / risk_eh
    if rr_eh < rr_floor:
        f["risk_reward_ratio"] = round(rr_eh, 3)
        f["min_rr_gate_status"] = "fail_below_floor"
        f["post_round_rr_status"] = "broke_after_round"
        return observe(f"最不利价 RR {rr_eh:.2f} < {rr_floor}")

    f["pullback_entry_price"] = valid_low_t if sub_mode == "pullback" else None
    f["breakout_entry_price"] = valid_low_t if sub_mode == "breakout" else None
    f["limit_order_price"] = valid_high_t  # limit ceiling = worst fill we'll accept (chase cap for breakout)
    f["valid_entry_low"], f["valid_entry_high"] = valid_low_t, valid_high_t
    f["stop_clear_price"] = stop_t
    f["take_profit_reduce_price"], f["take_profit_exit_price"] = t1_t, t2_t
    f["risk_reward_ratio"] = round(rr_eh, 3)
    f["min_rr_gate_status"] = "pass"
    f["post_round_rr_status"] = "ok"
    return _result(True, "support_atr_engine", f, None, tick, regime,
                   {"t1_basis": t1_basis, "rr_reference": round(rr_ref, 3),
                    "risk_per_share": round(close - stop_t, 6)})


# ── §6.1 holding_exit_engine (passive base levels; v1 no active scale-out) ─────────────────
def holding_exit_engine(inp, regime, event_reference_price=None):
    """Holding passive levels (§6.1). Trailing stop = effective_resistance (de-spiked recent high)
    − ATR_MULT[regime]×ATR, side-aware ticked + post-round re-check. ``inp`` = {close, bars |
    indicators}; optional ``event_reference_price`` = event hard-risk clear reference (manual
    execution, non-technical). Returns the same result shape. ``executable`` = levels computed;
    a breach (close ≤ ticked stop) still returns executable with ``trace.breached`` True and
    take-profit None (honest, never fabricated). Missing price/ATR/structure → not executable."""
    f = {c: None for c in HOLDING_COLUMNS}
    f["price_engine_used"] = "holding_exit_engine"
    f["price_sub_mode"] = None  # holding is not pullback/breakout

    inp = inp if isinstance(inp, dict) else {}   # malformed / non-dict inp → degrade-to-observe, never raw AttributeError
    close = inp.get("close")
    ind = _indicators(inp)
    sup, res, a = ind.get("effective_support"), ind.get("effective_resistance"), ind.get("atr")
    recent_high = res  # trailing-stop basis = de-spiked recent high
    f["effective_support"], f["effective_resistance"] = sup, res
    f["structure_quality"] = ind.get("resistance_quality")
    tick = tick_size_for(close)
    f["event_clear_reference_price"] = tick_ref(event_reference_price, tick) if event_reference_price is not None else None

    def observe(reason):
        return _result(False, "holding_exit_engine", f, reason, tick, regime)

    if close is None or a is None or a <= 0 or recent_high is None:
        return observe("缺价/ATR/有效压力,无法精算跟踪止损")

    stop = tick_up(recent_high - ATR_MULT.get(regime, _NEUTRAL_ATR_MULT) * a, tick)
    if stop is None:
        return observe("止损非有限,取整失败")
    f["stop_clear_price"] = stop

    risk = close - stop
    if risk <= 0:  # breached: price has hit the trailing stop (passive honesty, no fabricated tp)
        f["post_round_rr_status"] = "ok"
        return _result(True, "holding_exit_engine", f, "现价≤跟踪止损(已破位)", tick, regime, {"breached": True})

    rr_floor = RR_FLOOR.get(regime, _NEUTRAL_RR_FLOOR)
    raw_t1 = res if (res is not None and res > close) else close + rr_floor * risk
    t1 = tick_down(raw_t1, tick)
    t2 = tick_down(max(raw_t1 + ATR_MULT.get(regime, _NEUTRAL_ATR_MULT) * a, close + TP2_RISK_MULT * risk), tick)
    if t1 is None or t2 is None or not (t1 > close and t2 >= t1):
        # close > stop here (the risk<=0 breach branch already returned), so this is NOT a breach — the
        # take-profit just can't round into a valid order. Emit the valid stop, honest no-TP, breached=False.
        f["take_profit_reduce_price"], f["take_profit_exit_price"] = None, None
        f["post_round_rr_status"] = "tp_not_computable"
        return _result(True, "holding_exit_engine", f, "止盈位取整后不可精算(止损有效,未破位)", tick, regime, {"breached": False})

    f["take_profit_reduce_price"], f["take_profit_exit_price"] = t1, t2
    f["risk_reward_ratio"] = round((t1 - close) / risk, 3)
    f["post_round_rr_status"] = "ok"
    return _result(True, "holding_exit_engine", f, None, tick, regime, {"breached": False})
