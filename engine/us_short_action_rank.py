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
numeric → fail-closed to last-within-group (a malformed rank never jumps ahead). The global `action_rank` is
group-major (every group-1 row precedes every group-2 row, …). Pure/offline; no provider, no A-share crossing.
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


def _rank_value(x):
    """selection_rank as a positive integer (1 = best). Malformed → None → sorts last within its group (a
    row we can't rank never jumps ahead of a properly-ranked one)."""
    if isinstance(x, bool) or not isinstance(x, int):
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
    (every group-1 row precedes every group-2 row, …); within a group, by `selection_rank` ascending (a
    malformed rank sorts last), then input order for stability. Raises ValueError on a non-dict row or an
    unknown `final_action` (frozen-vocab strict)."""
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    enriched = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {i} is not a dict")
        group = action_group(row.get("final_action"))
        sr = _rank_value(row.get("selection_rank"))
        enriched.append({"index": i, "group": group,
                         "sort_rank": sr if sr is not None else math.inf})

    order = sorted(enriched, key=lambda e: (e["group"], e["sort_rank"], e["index"]))
    results = [None] * len(rows)
    for action_rank, e in enumerate(order, start=1):
        results[e["index"]] = {"action_group": e["group"], "action_rank": action_rank}
    return results
