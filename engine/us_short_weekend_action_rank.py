# -*- coding: utf-8 -*-
"""US-short weekend-pipeline action ranking — batch4 slice 4d-ii-j (§9 操作排名 action_rank).

Design authority: docs/us_short_system_design.md §9 (操作排名, line 248 survival-first) / §18.2 batch4.

The post-pass after 4d-ii-i (`apply_cash_allocation`). It assigns every finalized row its §9 `action_group`
(1-5) and the global `action_rank` (这周先干哪个 — distinct from selection_rank = 多强), reusing
`engine/us_short_action_rank.rank_actions` (no new ranking logic). The ordering is GROUP-MAJOR + survival-first
(a must-act holding reduce/clear can never rank below a new 建仓, §9 line 248 防把必须止损的持仓排到新买点后);
groups 2-5 order by `selection_rank`. This stage adds ranking only — it downgrades nothing.

Every input is consumer-validated fail-closed with the single-source weekend validators (§9 action/reason via
`action_reason_error`, canonical-unique ticker identity), the same boundary the basket / cost-floor / cash
stages enforce; the underlying `rank_actions` is itself frozen-vocab strict on `final_action`. Every output
row emits the canonical UPPERCASE ticker + carries `action_group` / `action_rank`. Pure/offline; no provider /
live / network call, no broker / auto-order, no A-share crossing.
"""
from __future__ import annotations

from engine.us_short_action_rank import rank_actions
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_result_effects import finalize_result_effects
from engine.us_short_weekend_decision import action_reason_error


class WeekendActionRankError(Exception):
    """The injected cash-allocated result is malformed (fail-closed before ranking)."""


def apply_action_rank(cash_result):
    """4d-ii-j action ranking. Assigns each row of the 4d-ii-i `apply_cash_allocation` result its §9
    `action_group` (1-5) + global `action_rank` (group-major + survival-first, then selection_rank), reusing
    `rank_actions`. Adds ranking only — no row is downgraded.

    cash_result = the `apply_cash_allocation` output {regime, rows, weekly_build_limit, build_count}.

    Returns the result with the same shape (every row + {action_group, action_rank}, ticker canonical
    UPPERCASE). Raises WeekendActionRankError on a malformed result / row, an unknown final_action, an
    observe_reason_type inconsistent with final_action, or a non-canonical / duplicate ticker identity."""
    if not (isinstance(cash_result, dict) and isinstance(cash_result.get("regime"), dict)
            and isinstance(cash_result.get("rows"), list)):
        raise WeekendActionRankError("cash_result 须为含 regime(dict) + rows(list) 的 4d-ii-i 输出")

    # Pass 1 — VALUE-validate every row (§9 action/reason single-source + canonical-unique ticker identity),
    # the same consumer-validation boundary as the basket / cost-floor / cash stages.
    ct_by_index, seen = {}, set()
    for i, row in enumerate(cash_result["rows"]):
        if not (isinstance(row, dict) and isinstance(row.get("final_action"), str)):
            raise WeekendActionRankError(f"row 形状非法（须为 4d-ii-i 输出行）: {row!r}")
        err = action_reason_error(row["final_action"], row.get("observe_reason_type"))   # §9 single-source
        if err:
            raise WeekendActionRankError(err)
        ct = canonical_us_ticker(row.get("ticker"))
        if ct is None:
            raise WeekendActionRankError(f"row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
        if ct in seen:
            raise WeekendActionRankError(f"rows 含规范化后重复 ticker（一股一行）: {ct!r}")
        seen.add(ct)
        ct_by_index[i] = ct

    # §9 ranking (group-major + survival-first; rank_actions reads final_action + selection_rank, ticker-agnostic).
    rankings = rank_actions(cash_result["rows"])

    finalized = finalize_result_effects(cash_result) if any(
        isinstance(row, dict) and "result_effects" in row for row in cash_result["rows"]
    ) else cash_result
    out_rows = []
    for i, row in enumerate(finalized["rows"]):
        out_rows.append({**row, "ticker": ct_by_index[i],
                         "action_group": rankings[i]["action_group"], "action_rank": rankings[i]["action_rank"]})
    return {**finalized, "rows": out_rows}
