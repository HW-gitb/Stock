# -*- coding: utf-8 -*-
"""US-short position sizing (§8 按风险定仓 + 削减叠法) — risk-based base size and the reduction stack.

Design authority: docs/us_short_system_design.md §8 (line 217 risk-based sizing, line 226 削减叠法). There is
NO governance preset — the sizing parameters (per-trade risk %, the §13.1 #4 caps, min executable) are forward
priors, carried here as module constants (not caller-overridable, to avoid a sizing bypass), exactly like the
§6 price engine. This engine produces `model_position_size_shares` (an action_table column) that §8 ship-gate
sizing + §8 cash allocation + §9 action_rank consume.

Risk-based base (§8 line 217, long-only): 能亏的钱 = 短线桶 × 单笔最大风险%; 每股风险 = 入场 − 止损;
底仓股数 = ⌊能亏的钱 ÷ 每股风险⌋. 削减叠法 (line 226): ① base ② × market_risk_regime multiplier ③ × the
HARSHEST single risk discount (data-degraded / theme-crowding / cluster-over-concentration / pre-earnings —
**take the harshest one, do NOT multiply them**) ④ min(single-ticker / remaining-total / remaining-theme /
liquidity / available-cash / global-cash-allocation caps) ⑤ < min executable → 降观察.

Every public input is fail-closed (whole-class): a malformed bucket / price / multiplier / cap collapses
toward the conservative (smaller) side — never inflates a position. Pure/offline; no provider, no broker /
auto-order, no A-share crossing.
"""
import math

# §13.1 #4 forward priors (NOT frozen const), module constants (not caller-overridable → no sizing bypass).
PER_TRADE_RISK_FRAC = 0.0075     # 单笔最大风险 % of the short bucket (v1 start 0.75%, range 0.5-1.0)
MIN_EXECUTABLE_SHARES = 1        # below this → 降观察


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _frac_0_1(x):
    """A multiplier in [0, 1] (regime cap / risk discount). Non-finite / bool / string / <0 / >1 → None."""
    v = _finite_number(x)
    return v if (v is not None and 0.0 <= v <= 1.0) else None


def _nonneg_int(x):
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    return x if x >= 0 else None


def risk_based_base_shares(bucket_dollars, entry_price, stop_price):
    """① 底仓股数 = ⌊(bucket × PER_TRADE_RISK_FRAC) ÷ (entry − stop)⌋ (§8 line 217, long-only). Returns an int
    ≥ 0. Fail-closed to 0 on a malformed / non-positive bucket, or a price state that is not a valid long
    setup: `entry` and `stop` must be finite POSITIVE prices with `entry > stop` (a non-positive entry/stop,
    or `entry ≤ stop`, is malformed — a real long has a positive stop below a positive entry)."""
    bucket = _finite_number(bucket_dollars)
    entry = _finite_number(entry_price)
    stop = _finite_number(stop_price)
    if bucket is None or bucket <= 0.0 or entry is None or stop is None:
        return 0
    if entry <= 0.0 or stop <= 0.0 or entry <= stop:      # long setup: entry/stop are positive prices, stop below entry
        return 0
    return int(math.floor((bucket * PER_TRADE_RISK_FRAC) / (entry - stop)))


def harshest_risk_discount(discount_mults):
    """③ The HARSHEST single risk discount — `min` of the multipliers, NOT their product (§8 取最狠的一个、
    不连乘, so co-occurring risks are not double-counted). An EXPLICITLY empty list / tuple → 1.0 (no
    reduction). A malformed CONTAINER (non-list/tuple — None / scalar / string / bool / dict) fails closed
    to 0.0, and so does a malformed multiplier inside the list (non-finite / bool / string / <0 / >1) — an
    untrustworthy risk signal must not silently leave the position un-discounted."""
    if not isinstance(discount_mults, (list, tuple)):
        return 0.0                       # malformed container → fail closed to the harshest (not silently 1.0)
    if not discount_mults:
        return 1.0                       # explicitly no discounts → no reduction
    vals = []
    for m in discount_mults:
        v = _frac_0_1(m)
        vals.append(v if v is not None else 0.0)   # malformed → harshest
    return min(vals)


def reduction_stack(base_shares, regime_multiplier, discount_mults, cap_shares, min_executable=MIN_EXECUTABLE_SHARES):
    """②③④⑤ of 削减叠法. sized = ⌊base × regime_multiplier × harshest_discount⌋, then ④ min against every
    cap in `cap_shares` (a list of non-negative share caps the caller derives from the §13.1 #4 限额 +
    portfolio state + cash), then ⑤ if the result < min executable → observe. Returns
    {shares, status, reason} with status ∈ {sized, observe}. Fail-closed (whole-class incl. the containers):
    a malformed base / regime / cap collapses toward 0, and a missing / non-list / empty `cap_shares`
    container → 0 (a position MUST be cap-bounded — never an uncapped or inflated position)."""
    base = _nonneg_int(base_shares)
    if base is None:
        base = 0                                    # malformed base → 0
    rm = _frac_0_1(regime_multiplier)
    if rm is None:
        rm = 0.0                                    # malformed / out-of-range regime cap → no position
    sized = int(math.floor(base * rm * harshest_risk_discount(discount_mults)))

    if not isinstance(cap_shares, (list, tuple)) or not cap_shares:
        candidates = [0]                                     # missing / malformed / empty cap container → fail closed (a position MUST be cap-bounded)
    else:
        candidates = [sized]
        for c in cap_shares:
            cv = _nonneg_int(c)
            candidates.append(cv if cv is not None else 0)   # malformed cap → 0 (fail closed, most restrictive)
    final = max(0, min(candidates))

    me = _nonneg_int(min_executable)
    me = me if (me is not None and me >= 1) else MIN_EXECUTABLE_SHARES
    if final < me:
        return {"shares": 0, "status": "observe", "reason": "below_min_executable"}
    return {"shares": final, "status": "sized", "reason": "risk_budget_capped"}
