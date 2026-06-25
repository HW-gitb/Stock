# -*- coding: utf-8 -*-
"""US-short weekend-pipeline theme_probe cost floor — batch4 slice 4d-ii-h (§8 最小仓成本地板).

Design authority: docs/us_short_system_design.md §8 (line 232 最小仓成本地板, 真拦单) / §9
(observe_reason_type) / §18.2 batch4.

The post-pass after 4d-ii-g (`resolve_build_capacity`). A theme_probe is a forced min-executable build (§8
强制最小可执行仓); if even at that minimum size the expected gross profit to TP1 (盈一) is ≤ the round-trip
cost × the safety multiple, the probe is not worth trying — it is downgraded from 建仓 to
观察(`cost_inefficient_min_size`) (§8 line 232 真拦单, 不只打标签). This runs ONLY on the promoted theme_probe
rows (the rows 4d-ii-g emitted as `final_action == 建仓` carrying a `theme_probe` block) — a base build is a
normal risk-sized position, not a min-size probe, and the §8 cost floor is the probe-size handle. The cost
arithmetic reuses `engine/us_short_cost_floor.apply_cost_floor` (no new cost math).

Per probe it reads, from the carried 4d-ii-g/4d-ii-c row:
  - shares = `sizing.desired_model_shares` (= MIN_EXECUTABLE_SHARES, the 4d-ii-g forced-min)
  - entry  = `price.action_fields.valid_entry_high` (the conservative / highest fill, same anchor 4d-ii-c
             sizing used — a smaller profit-to-TP1, the safe side)
  - tp1    = `price.action_fields.take_profit_reduce_price` (盈一 = t1, the first take-profit; RR's numerator)
and, injected, the round-trip execution cost components (commission / slippage / spread, dollars). `apply_cost_floor`
is itself fail-closed (malformed shares / non-positive prices / tp1 ≤ entry / unverifiable cost → BLOCK), so a
degenerate probe geometry conservatively becomes 观察 rather than a live order.

`cost_inputs` must EXACTLY cover the promoted-probe ticker set (visible in the basket result, so no
predict-ahead) — a missing or stale key fails closed. A cost-floored probe keeps its `theme_probe` /
`sizing` / `selection_rank` as trace (only `final_action` + `observe_reason_type` change). The
commission / slippage / spread VALUES are offline fixture / cost-model inputs (a live cost model is batch5,
SR-PROVIDER-001); this stage performs no provider / live / network call, no broker / auto-order, no A-share
crossing.
"""
from __future__ import annotations

from engine.us_short_cost_floor import OBSERVE_REASON_COST, apply_cost_floor
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_position_sizing import MIN_EXECUTABLE_SHARES
from engine.us_short_theme_probe import RISK_TAG as _PROBE_RISK_TAG
from engine.us_short_weekend_decision import OBSERVE_REASONS, action_reason_error

_BUILD = "建仓"
_OBSERVE = "观察"
_R_COST = OBSERVE_REASON_COST   # cost_inefficient_min_size (single-source from the cost_floor engine)
_COST_KEYS = frozenset({"commission_round_trip", "slippage_dollars", "spread_dollars"})
_PROBE_TRACE_KEYS = frozenset({"risk_tag", "entry_mode_constraint"})   # the 4d-ii-g promoted-probe theme_probe block
_PROBE_SIZING_REASON = "theme_probe_forced_min"
# legal entry-mode constraints a 4d-ii-g probe trace can carry. Provenance: engine/us_short_theme_probe.py
# defensive_entry_constraint() returns exactly these three; pinned to that engine by a triangulation test.
_ENTRY_MODE_CONSTRAINTS = ("none", "pullback_only", "breakout_exception_allowed")

assert _R_COST in OBSERVE_REASONS, "cost_floor observe reason drifted from §9 vocab"


class WeekendCostFloorError(Exception):
    """The injected basket_result / cost_inputs is malformed (fail-closed before the cost floor)."""


def _is_probe(row):
    """A promoted 4d-ii-g theme_probe row = `final_action == 建仓` carrying a `theme_probe` block."""
    return row["final_action"] == _BUILD and "theme_probe" in row


def apply_probe_cost_floor(basket_result, *, cost_inputs):
    """4d-ii-h cost floor. Runs the §8 最小仓成本地板 on every promoted theme_probe row in the 4d-ii-g
    `resolve_build_capacity` result: a probe whose min-size expected profit-to-盈一 ≤ round-trip cost ×
    safety multiple is downgraded 建仓 → 观察(`cost_inefficient_min_size`). Base builds and non-建仓 rows
    carry through unchanged; `build_count` is recomputed.

    basket_result = the `resolve_build_capacity` output {regime, rows, weekly_build_limit, build_count}.
    cost_inputs = {<promoted-probe canonical ticker>: {"commission_round_trip": $, "slippage_dollars": $,
                   "spread_dollars": $}}  # must EXACTLY cover the promoted-probe set.

    Returns the basket_result with the same shape (rows cost-floored, build_count recomputed, every row's
    ticker emitted canonical UPPERCASE). Raises WeekendCostFloorError on a malformed basket_result / row /
    cost_inputs, an unknown final_action, an observe_reason_type inconsistent with final_action (观察 needs a
    frozen reason; a non-观察 row must carry none), a non-canonical / duplicate ticker identity, a
    promoted-probe trace whose keys OR values (risk_tag / entry_mode_constraint) are invalid, or a cost_inputs
    set that does not exactly (canonically) cover the promoted probes."""
    if not (isinstance(basket_result, dict) and isinstance(basket_result.get("regime"), dict)
            and isinstance(basket_result.get("rows"), list)):
        raise WeekendCostFloorError("basket_result 须为含 regime(dict) + rows(list) 的 4d-ii-g 输出")
    if not isinstance(cost_inputs, dict):
        raise WeekendCostFloorError("cost_inputs 须为 dict")

    # Pass 1 — VALUE-validate every row (not just shape — this stage emits the official action surface AND
    # uses ticker identity for cost_inputs coverage / build_count, exactly like the 4d-ii-e/f/g basket): the §9
    # action/reason contract; a canonical-unique ticker identity (non-canonical / A-share code / duplicate
    # canonical identity fail closed); and — for a promoted probe — the theme_probe trace VALUES (not just keys:
    # `risk_tag` must be the governance tag, `entry_mode_constraint` a legal constraint) so an exact-key but
    # arbitrary-value trace cannot pose as a valid probe. Collect the canonical promoted-probe set; cost_inputs
    # must exactly cover it.
    ct_by_index, seen, probe_tickers = {}, set(), set()
    for i, row in enumerate(basket_result["rows"]):
        if not (isinstance(row, dict) and isinstance(row.get("final_action"), str)):
            raise WeekendCostFloorError(f"basket row 形状非法（须为 4d-ii-g 输出行）: {row!r}")
        err = action_reason_error(row["final_action"], row.get("observe_reason_type"))   # §9 single-source (词表 + 观察⟺reason)
        if err:
            raise WeekendCostFloorError(err)
        ct = canonical_us_ticker(row.get("ticker"))
        if ct is None:
            raise WeekendCostFloorError(f"row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
        if ct in seen:
            raise WeekendCostFloorError(f"basket rows 含规范化后重复 ticker（一股一行、防双计 build_count）: {ct!r}")
        seen.add(ct)
        ct_by_index[i] = ct
        if _is_probe(row):
            tp = row["theme_probe"]   # promoted-probe trace = 4d-ii-g {risk_tag, entry_mode_constraint} with VALID values
            if not (isinstance(tp, dict) and set(tp) == _PROBE_TRACE_KEYS
                    and tp.get("risk_tag") == _PROBE_RISK_TAG
                    and tp.get("entry_mode_constraint") in _ENTRY_MODE_CONSTRAINTS):
                raise WeekendCostFloorError(
                    f"promoted-probe theme_probe trace 非法（键/risk_tag={_PROBE_RISK_TAG!r}/entry_mode_constraint∈{list(_ENTRY_MODE_CONSTRAINTS)}）: {tp!r}")
            sizing = row.get("sizing")
            pre_probe = sizing.get("pre_probe_risk_shares") if isinstance(sizing, dict) else None
            if not (isinstance(sizing, dict)
                    and sizing.get("status") == "sized"
                    and isinstance(sizing.get("desired_model_shares"), int)
                    and not isinstance(sizing.get("desired_model_shares"), bool)
                    and sizing["desired_model_shares"] == MIN_EXECUTABLE_SHARES
                    and sizing.get("reason") == _PROBE_SIZING_REASON
                    and isinstance(pre_probe, int)
                    and not isinstance(pre_probe, bool)
                    and pre_probe >= MIN_EXECUTABLE_SHARES):
                raise WeekendCostFloorError(
                    f"promoted-probe sizing 须为 4d-ii-g forced-min 输出（status='sized', desired_model_shares={MIN_EXECUTABLE_SHARES}, reason={_PROBE_SIZING_REASON!r}, pre_probe_risk_shares>=min）: {sizing!r}")
            probe_tickers.add(ct)
    if set(cost_inputs) != probe_tickers:
        raise WeekendCostFloorError(
            f"cost_inputs 须恰覆盖已促回 probe 的 canonical ticker 集（无缺/无陈旧/canonical 键）: cost_inputs={sorted(cost_inputs)} probes={sorted(probe_tickers)}")

    # Pass 2 — cost-floor each promoted probe; base builds + non-建仓 rows carry through. EVERY output row emits
    # the canonical UPPERCASE ticker (never echoed raw). build_count recomputed.
    out_rows, build_count = [], 0
    for i, row in enumerate(basket_result["rows"]):
        ct = ct_by_index[i]
        if not _is_probe(row):
            if row["final_action"] == _BUILD:
                build_count += 1
            out_rows.append({**row, "ticker": ct})
            continue
        ci = cost_inputs[ct]
        if not (isinstance(ci, dict) and set(ci) == _COST_KEYS):
            raise WeekendCostFloorError(
                f"cost_inputs[{ct!r}] 须为 {{'commission_round_trip','slippage_dollars','spread_dollars'}}: {ci!r}")
        af = row.get("price", {}).get("action_fields", {}) if isinstance(row.get("price"), dict) else {}
        sizing = row.get("sizing") if isinstance(row.get("sizing"), dict) else {}
        result = apply_cost_floor(
            sizing.get("desired_model_shares"), af.get("valid_entry_high"), af.get("take_profit_reduce_price"),
            ci["commission_round_trip"], ci["slippage_dollars"], ci["spread_dollars"])
        if result["status"] == "ok":
            build_count += 1
            out_rows.append({**row, "ticker": ct})         # probe cleared the cost floor — stays 建仓
        else:
            # §8 line 232 真拦单：too small to be worth it → 观察(cost_inefficient_min_size); theme_probe /
            # sizing / selection_rank kept as trace (only the action + reason change).
            out_rows.append({**row, "ticker": ct, "final_action": _OBSERVE, "observe_reason_type": _R_COST})
    return {**basket_result, "rows": out_rows, "build_count": build_count}
