# -*- coding: utf-8 -*-
"""US-short weekend-pipeline global cash allocation — batch4 slice 4d-ii-i (§8 全局现金分配).

Design authority: docs/us_short_system_design.md §8 (全局现金分配, line 240) / §9 (observe_reason_type) /
§18.2 batch4.

The post-pass after 4d-ii-h (`apply_probe_cost_floor`). The finalized 建仓 set (base builds + cost-cleared
probes) competes for the short bucket's `available_cash`: rows are funded SEQUENTIALLY in
排名(selection_rank)-primary order at the conservative `valid_entry_high`, and a build the remaining cash
cannot fully cover is downgraded 建仓 → 观察(`cash_or_account_missing`) (§8 轮到现金不够→降观察, never a partial
order). The allocation arithmetic reuses `engine/us_short_cash_allocation.allocate_cash` (no new cash math);
the buildable-only safety boundary is enforced inside that engine from the authoritative `final_action`.

Per 建仓 row this attaches the 5 frozen §8 `cash_allocation_fields` (`cash_allocation_rank`,
`cash_required_at_entry_high`, `allocated_model_shares`, `remaining_cash_after`, `cash_allocation_status`);
a non-建仓 row carries through with those fields None (cash allocation N/A). `build_count` is recomputed.

Each 建仓's allocation inputs are read from the carried row: `desired_model_shares` (sizing), the conservative
`valid_entry_high` + `risk_reward_ratio` (price.action_fields), and `selection_rank` (排名). The 置信 / 流动性
tie-breaks are NOT yet computed in the weekend pipeline (action_confidence / a liquidity metric are later
work) — they are omitted, so the engine fail-closes them to the worst tie-break (rank-primary order is
unaffected). `available_cash` is an offline fixture / account_state value (a live account feed is batch5,
SR-PROVIDER-001). Every input is consumer-validated fail-closed with the single-source weekend validators
(§9 action/reason via `action_reason_error`, canonical-unique ticker identity); no provider / live / network
call, no broker / auto-order, no A-share crossing.
"""
from __future__ import annotations

import math

from engine.us_short_cash_allocation import CASH_ALLOCATION_FIELDS, allocate_cash
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_weekend_decision import OBSERVE_REASONS, action_reason_error

_BUILD = "建仓"
_OBSERVE = "观察"
_R_CASH = "cash_or_account_missing"   # §9 — funded build squeezed out when the global cash runs out (sizing artifact, not a system reject)
_NONE_CASH_FIELDS = {f: None for f in CASH_ALLOCATION_FIELDS}   # non-建仓 row: cash allocation N/A

assert _R_CASH in OBSERVE_REASONS, "cash observe reason drifted from §9 vocab"


class WeekendCashError(Exception):
    """The injected cost-floored result / available_cash is malformed (fail-closed before allocation)."""


def apply_cash_allocation(cost_floored_result, *, available_cash):
    """4d-ii-i global cash allocation. Funds the finalized 建仓 set of the 4d-ii-h `apply_probe_cost_floor`
    result against `available_cash` in 排名(selection_rank)-primary order at `valid_entry_high`; a build the
    remaining cash cannot cover is downgraded 建仓 → 观察(`cash_or_account_missing`). Every row gets the 5
    `cash_allocation_fields` (None on a non-建仓 row); `build_count` is recomputed.

    cost_floored_result = the `apply_probe_cost_floor` output {regime, rows, weekly_build_limit, build_count}.
    available_cash = the short bucket's deployable cash (float; an offline fixture / account_state value).

    Returns the result with the same shape (rows funded / downgraded, build_count recomputed, every row's
    ticker canonical UPPERCASE). Raises WeekendCashError on a malformed result / row, an unknown final_action,
    an observe_reason_type inconsistent with final_action, or a non-canonical / duplicate ticker identity."""
    if not (isinstance(cost_floored_result, dict) and isinstance(cost_floored_result.get("regime"), dict)
            and isinstance(cost_floored_result.get("rows"), list)):
        raise WeekendCashError("cost_floored_result 须为含 regime(dict) + rows(list) 的 4d-ii-h 输出")

    # Pass 1 — VALUE-validate every row (§9 action/reason single-source + canonical-unique ticker identity,
    # same consumer-validation boundary as the basket / cost-floor); collect the 建仓 rows + their allocation
    # inputs (flattened for the cash engine). A non-dict sizing / action_fields fails closed to a missing
    # input → the engine observes that row without spending.
    ct_by_index, seen = {}, set()
    build_indices, cash_inputs = [], []
    for i, row in enumerate(cost_floored_result["rows"]):
        if not (isinstance(row, dict) and isinstance(row.get("final_action"), str)):
            raise WeekendCashError(f"row 形状非法（须为 4d-ii-h 输出行）: {row!r}")
        err = action_reason_error(row["final_action"], row.get("observe_reason_type"))   # §9 single-source
        if err:
            raise WeekendCashError(err)
        ct = canonical_us_ticker(row.get("ticker"))
        if ct is None:
            raise WeekendCashError(f"row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
        if ct in seen:
            raise WeekendCashError(f"rows 含规范化后重复 ticker（一股一行）: {ct!r}")
        seen.add(ct)
        ct_by_index[i] = ct
        if row["final_action"] == _BUILD:
            sizing = row.get("sizing") if isinstance(row.get("sizing"), dict) else {}
            af = row.get("price", {}).get("action_fields", {}) if isinstance(row.get("price"), dict) else {}
            shares, entry, rank = sizing.get("desired_model_shares"), af.get("valid_entry_high"), row.get("selection_rank")
            # a 建仓 reaching this stage is a validated 4d-ii-h build — its cash-critical inputs must be sound
            # (so the only reason the engine can later observe it is genuine insufficient_cash, never bad data).
            if not (isinstance(shares, int) and not isinstance(shares, bool) and shares >= 1):
                raise WeekendCashError(f"建仓 行 desired_model_shares 须为正 int: {ct!r} → {shares!r}")
            if not (isinstance(entry, (int, float)) and not isinstance(entry, bool) and math.isfinite(entry) and entry > 0.0):
                raise WeekendCashError(f"建仓 行 valid_entry_high 须为正有限数: {ct!r} → {entry!r}")
            if not (isinstance(rank, int) and not isinstance(rank, bool) and rank >= 1):
                raise WeekendCashError(f"建仓 行 selection_rank 须为正 int（供现金分配排序）: {ct!r} → {rank!r}")
            build_indices.append(i)
            cash_inputs.append({
                "final_action": _BUILD, "desired_model_shares": shares, "valid_entry_high": entry,
                "rank": rank, "rr": af.get("risk_reward_ratio"),
            })

    allocations = allocate_cash(cash_inputs, available_cash)   # aligned with cash_inputs / build_indices

    # Pass 2 — attach the cash_allocation_fields; an insufficient-cash 建仓 → 观察(cash_or_account_missing).
    # build_count recomputed; every row emits the canonical UPPERCASE ticker. Non-建仓 rows: cash fields None.
    alloc_by_index = dict(zip(build_indices, allocations))
    out_rows, build_count = [], 0
    for i, row in enumerate(cost_floored_result["rows"]):
        ct = ct_by_index[i]
        if i not in alloc_by_index:
            out_rows.append({**row, "ticker": ct, **_NONE_CASH_FIELDS})
            continue
        alloc = alloc_by_index[i]
        cash_fields = {f: alloc[f] for f in CASH_ALLOCATION_FIELDS}
        if alloc["cash_allocation_status"] == "allocated":
            build_count += 1
            out_rows.append({**row, "ticker": ct, **cash_fields})              # funded — stays 建仓
        else:
            out_rows.append({**row, "ticker": ct, **cash_fields,
                             "final_action": _OBSERVE, "observe_reason_type": _R_CASH})   # 现金不够 → 观察
    return {**cost_floored_result, "rows": out_rows, "build_count": build_count}
