# -*- coding: utf-8 -*-
"""US-short action ranking (§9 操作排名 action_rank) — survival-first 5-group skeleton.

Design authority: docs/us_short_system_design.md §9; frozen 5-group skeleton + final_action vocab +
grouping-not-weighting / survival-first policy in presets/us_short_action_governance_20260620.json (LOADED).

§9 ranks "what to do FIRST this week" (distinct from selection_rank = "how strong"). It uses 5 ordered
GROUPS, not a weighted score, so a must-act holding can NEVER rank below a new buy (§9 grouping_not_weighting
/ survival_first, line 248 防把必须止损的持仓排到新买点后). Group ORDER is the absolute priority:
  1 持仓强制减/清 — any holding reduce/clear (减仓 / 清仓-止损 / 清仓-止盈 / 清仓-事件; 止损/position veto are the
    survival-critical primary case, §9 line 248 '持仓侧并入①/③')
  2 可建仓新机会 (建仓) — ordered by selection_rank
  3 加仓
  4 持有 / 观察
  5 否决 / 放弃 (否决/避开)

`final_action` is a FROZEN-vocab categorical (always produced upstream from the action_table contract), so an
unknown value is a contract violation → ValueError (strict, like §5 row_context). `selection_rank` is a noisy
numeric → a clean positive rank or None. The global `action_rank` is group-major (every group-1 row precedes
every group-2 row, …); WITHIN group 1 a survival sub-order (止损/事件清仓 → 减仓 → 止盈清仓, §9 line 248) precedes
the rank, so an unranked 止损/事件清仓 deliberately outranks a ranked 减仓/止盈清仓, while groups 2-5 order by
`selection_rank`. Pure/offline; no provider, no A-share crossing.
"""
import json
import math
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_action_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

ACTION_RANK_SKELETON = tuple(g["group"] for g in _GOV["action_rank_skeleton"])      # (1,2,3,4,5), order = priority
_FINAL_ACTION_VOCAB = tuple(e["final_action"] for e in _GOV["final_action_price_map"])

# §9 final_action → survival-first group (design-grounded, §9 line 248). Holding reduce/clear actions (those
# whose price_target is a holding-exit field) → group 1; 建仓 → 2; 加仓 → 3; 持有/观察 → 4; 否决/避开 → 5.
FINAL_ACTION_GROUP = {
    "减仓": 1, "清仓-止损": 1, "清仓-止盈": 1, "清仓-事件": 1,
    "建仓": 2,
    "加仓": 3,
    "持有": 4, "观察": 4,
    "否决/避开": 5,
}

# §9 line 248 within-group-1 survival-first sub-order: among holding exits (group 1) a loss-preventing exit
# (止损 / 事件清仓) ranks before a partial 减仓, which ranks before a pure take-profit (止盈清仓). This is ONLY a
# sub-order INSIDE group 1 — for every other group it is a constant, so the existing selection_rank order is
# unchanged. (A 减仓's driver — stop- vs profit-driven — isn't carried on final_action, so it sits in the middle.)
_GROUP1_EXIT_PRIORITY = {"清仓-止损": 0, "清仓-事件": 0, "减仓": 1, "清仓-止盈": 2}


def _rank_value(x):
    """selection_rank as a positive integer (1 = best), else None. Accepts an integer-VALUED float (1.0 → 1,
    e.g. from JSON / numpy / upstream float math) for parity with the sibling engines' numeric handling; a
    non-integer float (1.5), a bool, a string, or a value < 1 → None. This only VALIDATES the rank value — the
    ordering (group-major, then the group-1 survival sub-order, then this rank) is the caller's, so a None here
    does NOT by itself mean 'last' (an unranked group-1 survival exit still outranks a ranked 减仓/止盈清仓)."""
    if isinstance(x, bool):
        return None
    if isinstance(x, float):
        if not math.isfinite(x) or x != int(x):     # non-integer / NaN / Inf float is not a clean rank
            return None
        x = int(x)
    if not isinstance(x, int):                       # string / None / other → malformed
        return None
    return x if x >= 1 else None


def action_group(final_action):
    """The §9 survival-first group (1-5) for a `final_action`. Raises ValueError on a value outside the
    frozen action_table vocabulary (a contract violation, not a runtime-noisy input)."""
    try:
        return FINAL_ACTION_GROUP[final_action]
    except (KeyError, TypeError):
        raise ValueError(f"unknown final_action {final_action!r} (not in the frozen action_table vocab)")


def rank_actions(rows):
    """Assign each row its §9 `action_group` (1-5) and a global `action_rank` (1-based). Returns a list
    aligned with the INPUT order; each element adds {action_group, action_rank}. Ordering is GROUP-MAJOR
    (every group-1 row precedes every group-2 row, …); WITHIN group 1 a survival-first sub-order applies
    (loss-preventing 止损/事件清仓 before a partial 减仓 before a 止盈清仓, §9 line 248) ahead of `selection_rank`,
    while groups 2-5 order by `selection_rank` ascending (a malformed rank sorts last); then input order for
    stability. Raises ValueError on a non-dict row or an unknown `final_action` (frozen-vocab strict)."""
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    enriched = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {i} is not a dict")
        fa = row.get("final_action")
        group = action_group(fa)
        sr = _rank_value(row.get("selection_rank"))
        survival = _GROUP1_EXIT_PRIORITY.get(fa, 0) if group == 1 else 0   # survival-first only INSIDE group 1
        enriched.append({"index": i, "group": group, "survival": survival,
                         "sort_rank": sr if sr is not None else math.inf})

    order = sorted(enriched, key=lambda e: (e["group"], e["survival"], e["sort_rank"], e["index"]))
    results = [None] * len(rows)
    for action_rank, e in enumerate(order, start=1):
        results[e["index"]] = {"action_group": e["group"], "action_rank": action_rank}
    return results
