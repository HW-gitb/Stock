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
_R_CAPACITY = "capacity_or_budget_deferred"  # §9 — total/theme dollar capacity is exhausted or cannot be verified
_NONE_CASH_FIELDS = {f: None for f in CASH_ALLOCATION_FIELDS}   # non-建仓 row: cash allocation N/A

# §8 / §13.1 #4 forward priors. They are enforced here at the final cross-row cash stage, after the
# weekly-count/theme-count gates and before cash is allocated, so an existing holding cannot be ignored by a
# new-build-only allocation path.
TOTAL_POSITION_CAP_FRAC = 0.60
SAME_THEME_DOLLAR_CAP_FRAC = 0.30

assert _R_CASH in OBSERVE_REASONS, "cash observe reason drifted from §9 vocab"
assert _R_CAPACITY in OBSERVE_REASONS, "capacity observe reason drifted from §9 vocab"


class WeekendCashError(Exception):
    """The injected cost-floored result / available_cash is malformed (fail-closed before allocation)."""


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _positive_int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 1 else None


def _capacity_state(portfolio_capacity):
    """Validate and value existing holdings for the §8 dollar-cap gate.

    A structurally malformed context raises before allocation. A well-shaped context with an unavailable current
    mark or theme returns ``unavailable``: all new builds will be downgraded, while existing holding advice can
    still render. This is fail-closed and never substitutes average cost or a stale/default theme for the current
    exposure required by the cap.
    """
    if not (isinstance(portfolio_capacity, dict)
            and set(portfolio_capacity) == {"short_bucket_dollars", "existing_positions"}
            and isinstance(portfolio_capacity["existing_positions"], list)):
        raise WeekendCashError(
            "portfolio_capacity 顶层键须恰为 {'short_bucket_dollars','existing_positions'}，且 existing_positions 为 list")
    bucket = _finite_number(portfolio_capacity["short_bucket_dollars"])
    if bucket is None or bucket <= 0.0:
        raise WeekendCashError("portfolio_capacity.short_bucket_dollars 须为正有限数")
    total_cap = bucket * TOTAL_POSITION_CAP_FRAC
    theme_cap = bucket * SAME_THEME_DOLLAR_CAP_FRAC
    if not math.isfinite(total_cap) or not math.isfinite(theme_cap):
        raise WeekendCashError("portfolio capacity dollar caps 非有限")

    seen, total, by_theme = set(), 0.0, {}
    for position in portfolio_capacity["existing_positions"]:
        if not (isinstance(position, dict)
                and set(position) == {"ticker", "shares", "mark_price", "theme"}):
            raise WeekendCashError(
                "portfolio_capacity.existing_positions[] 须恰为 {'ticker','shares','mark_price','theme'}")
        ticker = canonical_us_ticker(position["ticker"])
        if ticker is None or ticker in seen:
            raise WeekendCashError("portfolio_capacity.existing_positions 含非法或重复 canonical ticker")
        seen.add(ticker)
        shares = _positive_int(position["shares"])
        mark = _finite_number(position["mark_price"])
        theme = position["theme"]
        if shares is None or mark is None or mark <= 0.0 or not isinstance(theme, str) or not theme.strip():
            return {
                "status": "unavailable_existing_exposure",
                "total_cap_dollars": total_cap,
                "theme_cap_dollars": theme_cap,
                "existing_total_dollars": None,
                "existing_theme_dollars": {},
            }
        try:
            amount = float(shares) * mark
        except OverflowError:
            amount = float("inf")
        if not math.isfinite(amount) or amount < 0.0:
            return {
                "status": "unavailable_existing_exposure",
                "total_cap_dollars": total_cap,
                "theme_cap_dollars": theme_cap,
                "existing_total_dollars": None,
                "existing_theme_dollars": {},
            }
        total += amount
        cleaned_theme = theme.strip().casefold()
        by_theme[cleaned_theme] = by_theme.get(cleaned_theme, 0.0) + amount
    return {
        "status": "ready",
        "total_cap_dollars": total_cap,
        "theme_cap_dollars": theme_cap,
        "existing_total_dollars": total,
        "existing_theme_dollars": by_theme,
    }


def _apply_portfolio_capacity(cash_inputs, portfolio_capacity):
    """Apply total- and same-theme-dollar caps in canonical rank order before cash allocation.

    New positions are all-or-observe: a row that does not fit the remaining dollar capacity is not partially
    resized, so lower-ranked names cannot silently crowd through an already-full portfolio/theme bucket.
    """
    state = _capacity_state(portfolio_capacity)
    decisions = {}
    if state["status"] != "ready":
        for index in range(len(cash_inputs)):
            decisions[index] = "deferred_unavailable_existing_exposure"
        return decisions, state

    total = state["existing_total_dollars"]
    by_theme = dict(state["existing_theme_dollars"])
    for index, row in sorted(enumerate(cash_inputs), key=lambda item: (item[1]["rank"], item[1]["ticker"])):
        theme = row["portfolio_theme"]
        try:
            amount = float(row["desired_model_shares"]) * float(row["valid_entry_high"])
        except (TypeError, ValueError, OverflowError):
            amount = float("inf")
        if not math.isfinite(amount) or amount <= 0.0:
            raise WeekendCashError("validated build 的 portfolio capacity amount 非法")
        if total + amount > state["total_cap_dollars"]:
            decisions[index] = "deferred_total_cap"
            continue
        if by_theme.get(theme, 0.0) + amount > state["theme_cap_dollars"]:
            decisions[index] = "deferred_theme_cap"
            continue
        decisions[index] = "within_limits"
        total += amount
        by_theme[theme] = by_theme.get(theme, 0.0) + amount
    return decisions, {**state, "reserved_total_dollars": total, "reserved_theme_dollars": by_theme}


def apply_cash_allocation(cost_floored_result, *, available_cash, portfolio_capacity):
    """4d-ii-i global cash allocation. Funds the finalized 建仓 set of the 4d-ii-h `apply_probe_cost_floor`
    result first against the §8 total-position (60%) and same-theme (30%) dollar capacities in
    排名(selection_rank)-primary order at `valid_entry_high`, including every existing holding at its current
    mark; a build that does not fit is downgraded 建仓 → 观察(`capacity_or_budget_deferred`). The remaining
    in-capacity rows are then funded against `available_cash`; a build the remaining cash cannot cover is
    downgraded 建仓 → 观察(`cash_or_account_missing`). Every row gets the 5 `cash_allocation_fields` (None when
    capacity rejects it or it is non-建仓); `build_count` is recomputed.

    cost_floored_result = the `apply_probe_cost_floor` output {regime, rows, weekly_build_limit, build_count}.
    available_cash = the short bucket's deployable cash (float; an offline fixture / account_state value).
    portfolio_capacity = {short_bucket_dollars, existing_positions:[{ticker, shares, mark_price, theme}]}; the
      existing positions must be current-marked and themed, otherwise new builds fail closed to observe.

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
            theme = row.get("portfolio_theme")
            if not isinstance(theme, str) or not theme.strip():
                raise WeekendCashError(f"建仓 行 portfolio_theme 须为非空 str（同主题美元上限）: {ct!r}")
            build_indices.append(i)
            cash_inputs.append({
                "final_action": _BUILD, "desired_model_shares": shares, "valid_entry_high": entry,
                "rank": rank, "rr": af.get("risk_reward_ratio"), "ticker": ct,
                "portfolio_theme": theme.strip().casefold(),
            })

    capacity_by_input, capacity_summary = _apply_portfolio_capacity(cash_inputs, portfolio_capacity)
    fundable_input_indices = [idx for idx in range(len(cash_inputs)) if capacity_by_input[idx] == "within_limits"]
    allocations = allocate_cash([cash_inputs[idx] for idx in fundable_input_indices], available_cash)
    alloc_by_index = {
        build_indices[input_idx]: allocation
        for input_idx, allocation in zip(fundable_input_indices, allocations)
    }
    capacity_by_row_index = {
        build_indices[input_idx]: capacity_by_input[input_idx]
        for input_idx in range(len(cash_inputs))
    }

    # Pass 2 — attach the cash_allocation_fields; an insufficient-cash 建仓 → 观察(cash_or_account_missing).
    # build_count recomputed; every row emits the canonical UPPERCASE ticker. Non-建仓 rows: cash fields None.
    out_rows, build_count = [], 0
    for i, row in enumerate(cost_floored_result["rows"]):
        ct = ct_by_index[i]
        if i not in alloc_by_index:
            capacity_status = capacity_by_row_index.get(i)
            if capacity_status is None:
                out_rows.append({**row, "ticker": ct, **_NONE_CASH_FIELDS,
                                 "portfolio_capacity_status": None})
            else:
                out_rows.append({**row, "ticker": ct, **_NONE_CASH_FIELDS,
                                 "portfolio_capacity_status": capacity_status,
                                 "final_action": _OBSERVE, "observe_reason_type": _R_CAPACITY})
            continue
        alloc = alloc_by_index[i]
        cash_fields = {f: alloc[f] for f in CASH_ALLOCATION_FIELDS}
        if alloc["cash_allocation_status"] == "allocated":
            build_count += 1
            out_rows.append({**row, "ticker": ct, **cash_fields,
                             "portfolio_capacity_status": "within_limits"})   # funded — stays 建仓
        else:
            out_rows.append({**row, "ticker": ct, **cash_fields,
                             "portfolio_capacity_status": "within_limits",
                             "final_action": _OBSERVE, "observe_reason_type": _R_CASH})   # 现金不够 → 观察
    return {**cost_floored_result, "rows": out_rows, "build_count": build_count,
            "portfolio_capacity": capacity_summary}
