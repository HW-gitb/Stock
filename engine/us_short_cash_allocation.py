# -*- coding: utf-8 -*-
"""US-short global cash allocation (§8 全局现金分配) — buildable-only sequential funding.

Design authority: docs/us_short_system_design.md §8 (全局现金分配, line 232); frozen scope + field set +
ordering keys + conservative basis in presets/us_short_cash_allocation_governance_20260620.json (LOADED).

Only **buildable** tickers are funded (§8 可建仓票): buildability is determined HERE from the authoritative
frozen `final_action` field (us_short_action_table_contract) — only the cash-deploying build actions
(建仓 / 加仓) are funded; every other action-table value (减仓 / 清仓-* / 持有 / 观察 / 否决避开), a hard-vetoed
row, and any unknown / malformed value are NEVER allocated cash or rescued (§8 never_rescue_non_buildable,
enforced not assumed). Rows are ordered by 排名 / 置信 / RR / 流动性 (the ordering WEIGHTS are §13.1 #25 forward
priors — v1 uses a rank-primary lexicographic order, NOT a fabricated weighted sum), then cash is allocated
SEQUENTIALLY using the most conservative `valid_entry_high` to size each occupied position. When it is a
row's turn and the remaining cash cannot cover its full position, that row is downgraded to observe (never a
partial / unaffordable order — 轮到现金不够→降观察, no over-allocation).

Per-row output carries the 5 frozen `cash_allocation_fields` (`cash_allocation_rank`,
`cash_required_at_entry_high`, `allocated_model_shares`, `remaining_cash_after`, `cash_allocation_status`)
plus a machine-layer `reason`. Only `cash_allocation_status` is an action_table column. Every public input
is fail-closed (whole-class): a malformed share count / entry price → that row observes without consuming
cash; a malformed available_cash → 0 (everything observes); a malformed sort key sinks the row to the back
(an untrustworthy rank never jumps the funding queue). Pure/offline; no provider, no A-share crossing.
"""
import json
import math
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_cash_allocation_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

CASH_ALLOCATION_FIELDS = tuple(_GOV["cash_allocation_fields"])
ORDERING_KEYS = tuple(_GOV["ordering_keys"])                 # 排名 / 置信 / RR / 流动性
CONSERVATIVE_ENTRY_BASIS = _GOV["conservative_entry_basis"]  # "valid_entry_high"
_BUILDABLE_ONLY = bool(_GOV["allocation_scope"]["only_buildable_tickers"])


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _count(x):
    """A positive integer share count: exactly an int (not bool), >= 1. Fractional / bool / string /
    <= 0 / NaN → None (a buildable row must want a whole, positive number of shares)."""
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    return x if x >= 1 else None


def _rank_value(x):
    """The PRIMARY ranking position: a positive integer (1 = best). Negative / zero / fractional / bool /
    numeric-string / NaN is malformed → None, so it sorts to the back — an untrustworthy rank must NEVER
    jump ahead of a valid rank-1 row to grab scarce cash."""
    if isinstance(x, bool) or not isinstance(x, int):
        return None
    return x if x >= 1 else None


def _rank_field(row, key):
    """A CONTINUOUS tie-break field (confidence / RR / liquidity — higher is better), fail-closed: a missing
    / malformed value returns None so it sorts to the worst tie-break position. These are genuine continuous
    domains (unlike the integer rank), so `_finite_number` is the right validator; a malformed one only
    affects ordering AMONG equal ranks and always loses, never jumping a better primary rank."""
    return _finite_number(row.get(key)) if isinstance(row, dict) else None


# §8 可建仓票 = the cash-DEPLOYING action-table actions. The authoritative `final_action` vocabulary is the
# frozen 9-value Chinese const in schemas/us_short_action_table_contract.schema.json; of those only 建仓 (new
# build) and 加仓 (add) draw NEW capital from available_cash — ALL others (减仓 / 清仓-* / 持有 / 观察 / 否决避开)
# need no new cash. ALLOW-LIST (fail-closed), never a deny-list: an unknown / missing / English / typo value
# is NOT buildable.
_BUILDABLE_FINAL_ACTIONS = ("建仓", "加仓")


def _veto_blocks(hard_veto):
    """A hard veto is a safety BLOCK (opposite polarity of a grant flag): a row is vetoed UNLESS its
    `hard_veto` is ABSENT (no veto signal at all → rely on the `final_action` gate) or an explicit clean
    boolean `False`. A present True / truthy-non-True (`1` / `"yes"` / `[1]`) / malformed value all FAIL
    CLOSED to a veto (§8 hard veto = 0 position) — a present veto field that is not a clean `False` must
    never be silently read as buildable. (Absent differs from ship_gate's default-`False` param: here the
    veto is an OPTIONAL dict key via `.get`, so a missing key is no-veto, not a block.)"""
    return hard_veto is not None and hard_veto is not False


def _is_buildable(row):
    """The buildable-only safety boundary (§8 `never_rescue_non_buildable`), enforced at the API against the
    AUTHORITATIVE frozen `final_action` field (us_short_action_table_contract). A row is fundable ONLY if its
    `final_action` is a cash-deploying build action (建仓 / 加仓) AND it is not hard-vetoed. Every other
    action-table value (减仓 / 清仓-止损 / 清仓-止盈 / 清仓-事件 / 持有 / 观察 / 否决/避开) and any unknown /
    missing / malformed / case-or-whitespace-drifted value fails closed to not-buildable — never funded, never
    revived by cash ordering. A non-dict row is not buildable."""
    if not isinstance(row, dict):
        return False
    if _veto_blocks(row.get("hard_veto")):                   # absolute override — §8 hard veto = 0 position
        return False
    return row.get("final_action") in _BUILDABLE_FINAL_ACTIONS


def _sort_key(prepared):
    # non-fundable rows last; then rank ascending (1 = best); then confidence / RR / liquidity descending.
    # None rank → +inf (worst); None tiebreak → -inf (worst for a descending key); original index breaks ties.
    rank = prepared["rank"]
    conf, rr, liq = prepared["confidence"], prepared["rr"], prepared["liquidity"]
    return (
        0 if prepared["fundable"] else 1,
        rank if rank is not None else math.inf,
        -(conf if conf is not None else -math.inf),
        -(rr if rr is not None else -math.inf),
        -(liq if liq is not None else -math.inf),
        prepared["index"],
    )


def allocate_cash(buildable_rows, available_cash):
    """Allocate `available_cash` across `buildable_rows` (§8). Each row is a dict that is fundable ONLY if its
    authoritative `final_action` is a cash-deploying build action (建仓 / 加仓) and it is not hard-vetoed — the
    buildable-only boundary is enforced HERE, not assumed (§8 never_rescue_non_buildable); any other
    final_action / hard-vetoed / unknown row observes (`not_buildable`) and is never funded or revived. A
    fundable row carries `desired_model_shares`
    (post-reduction-stack model shares before the global cash cap), `valid_entry_high` (the conservative
    occupied-cash basis), and ordering fields `rank` (a positive integer, 1 = best) / `confidence` / `rr` /
    `liquidity`. Returns a list aligned with the INPUT order; each element has the 5 frozen
    `cash_allocation_fields` + `reason`. Fundable rows are funded sequentially in rank-primary order at
    `valid_entry_high`; a row the remaining cash cannot fully cover observes (`insufficient_cash`) without
    spending. A malformed-sized row observes (`invalid_row`); a malformed `rank` sinks to the back; a non-list
    `buildable_rows` → []."""
    if not isinstance(buildable_rows, list):
        return []
    cash = _finite_number(available_cash)
    remaining = cash if (cash is not None and cash >= 0.0) else 0.0   # malformed / negative cash → 0 (all observe)

    prepared = []
    for i, row in enumerate(buildable_rows):
        is_dict = isinstance(row, dict)
        shares = _count(row.get("desired_model_shares")) if is_dict else None
        entry = _finite_number(row.get("valid_entry_high")) if is_dict else None
        if not is_dict:
            skip_reason = "invalid_row"                         # malformed shape
        elif not _is_buildable(row):
            skip_reason = "not_buildable"                       # safety boundary (precedence over sizing)
        elif shares is None or entry is None or entry <= 0.0:
            skip_reason = "invalid_row"
        else:
            skip_reason = None
        prepared.append({
            "index": i, "fundable": skip_reason is None, "skip_reason": skip_reason,
            "shares": shares, "entry": entry,
            "rank": _rank_value(row.get("rank")) if is_dict else None,
            "confidence": _rank_field(row, "confidence"),
            "rr": _rank_field(row, "rr"),
            "liquidity": _rank_field(row, "liquidity"),
        })

    results = [None] * len(buildable_rows)
    for order_pos, p in enumerate(sorted(prepared, key=_sort_key), start=1):
        if not p["fundable"]:
            required, allocated, status, reason = None, 0, "observe", p["skip_reason"]
        else:
            required = p["shares"] * p["entry"]
            if required <= remaining:
                allocated, status, reason = p["shares"], "allocated", "funded"
                remaining -= required
            else:
                allocated, status, reason = 0, "observe", "insufficient_cash"
        results[p["index"]] = {
            "cash_allocation_rank": order_pos,
            "cash_required_at_entry_high": required,
            "allocated_model_shares": allocated,
            "remaining_cash_after": remaining,
            "cash_allocation_status": status,
            "reason": reason,
        }
    return results
