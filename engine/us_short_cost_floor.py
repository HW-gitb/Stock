# -*- coding: utf-8 -*-
"""US-short minimum-size cost floor (§8 最小仓成本地板) — P0 真拦单 cost-efficiency gate.

Design authority: docs/us_short_system_design.md §8 (line 224). 口径: 若 预计到盈一的净利润空间 ≤
(佣金 + 滑点 + 点差) 往返成本 × 安全倍数, 则不试探、转观察 (observe_reason_type = cost_inefficient_min_size).
**实现时必须真拦单、不只打标签** — so this gate returns a HARD zero-share observe result (the order is
blocked), NOT a tag added alongside a live position. The safety multiple is a §13.1 #27 forward prior carried
as a module constant (NOT caller-overridable — a caller must not be able to pass a tiny multiple to bypass the
floor). `cost_inefficient_min_size` is the frozen §9 observe_reason_type (us_short_action_governance).

Every public input is fail-closed (whole-class incl. the cost components): if the expected profit to TP1 or
the round-trip cost cannot be verified (malformed shares / prices / cost), the order is BLOCKED (observe) —
an unverifiable cost-efficiency must never place a live order. Pure/offline; no provider, no broker /
auto-order, no A-share crossing.
"""
import math

COST_SAFETY_MULT = 3.0   # §13.1 #27 forward prior: expected profit-to-TP1 must EXCEED round-trip cost by this multiple
OBSERVE_REASON_COST = "cost_inefficient_min_size"   # frozen §9 observe_reason_type (us_short_action_governance)


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        return float(x) if math.isfinite(x) else None
    except OverflowError:
        return None


def _count(x):
    """A proposed position is a positive integer share count (≥ 1). Fractional / bool / string / ≤ 0 → None."""
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    if x < 1:
        return None
    try:
        return x if math.isfinite(x) else None
    except OverflowError:
        return None


def round_trip_cost(commission_round_trip, slippage_dollars, spread_dollars):
    """§8 往返成本 = 佣金 + 滑点 + 点差 (round-trip, in dollars). Returns the summed cost, or None if ANY
    component is malformed / negative (a cost we cannot trust must fail closed, not silently under-count)."""
    parts = [_finite_number(commission_round_trip), _finite_number(slippage_dollars), _finite_number(spread_dollars)]
    if any(p is None or p < 0.0 for p in parts):
        return None
    return sum(parts)


def apply_cost_floor(shares, entry_price, tp1_price, commission_round_trip, slippage_dollars, spread_dollars):
    """P0 最小仓成本地板 (§8 line 224, 真拦单). If the expected NET profit to TP1
    (shares × (tp1 − entry) − round-trip cost) ≤ round-trip cost × COST_SAFETY_MULT, the order is BLOCKED — returns a hard
    zero-share observe (`cost_inefficient_min_size`), NOT a tag on a live position. Fail-closed: malformed
    shares / non-positive prices / tp1 ≤ entry / an unverifiable round-trip cost all BLOCK the order (an
    unverifiable cost-efficiency must never place a live order). Returns
    {shares, status, observe_reason_type, reason}."""
    sh = _count(shares)
    entry = _finite_number(entry_price)
    tp1 = _finite_number(tp1_price)
    cost = round_trip_cost(commission_round_trip, slippage_dollars, spread_dollars)
    if sh is None or entry is None or entry <= 0.0 or tp1 is None or tp1 <= 0.0 or tp1 <= entry or cost is None:
        return _blocked("unverifiable_cost_inputs")
    net_profit_to_tp1 = sh * (tp1 - entry) - cost   # §8 口径 = 净利润 (gross − round-trip cost), NOT gross
    if net_profit_to_tp1 <= cost * COST_SAFETY_MULT:
        return _blocked("profit_below_cost_floor")
    return {"shares": sh, "status": "ok", "observe_reason_type": None, "reason": "cost_floor_cleared"}


def _blocked(reason):
    return {"shares": 0, "status": "observe", "observe_reason_type": OBSERVE_REASON_COST, "reason": reason}
