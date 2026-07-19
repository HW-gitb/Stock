# -*- coding: utf-8 -*-
"""US-short weekend-pipeline per-row action decision — batch4 slice 4d-ii-b (§6 priority chain → §9 final_action).

Design authority: docs/us_short_system_design.md §6 (优先级链) / §6.1 (持仓 v1 只出基础价位) / §9
(action_rank vocab + 5-group) / §5 (veto tiers) / §8.1 (forward) / §18.2 batch4.

The third batch-4 stage: consumes the 4d-ii-a analysis EVIDENCE ({regime, rows}) and assigns each row a
§9 `final_action` (+ `observe_reason_type` when 观察) from the §6 priority chain, using the EVIDENCE
ALONE (veto tier, price executable/reject, event-sensitive data gap). v1 decisions:

    holding:   position_hard_veto → 清仓-事件 ; price not executable → 观察(price_not_executable) ;
               price breached → 清仓-止损 ; else → holding action planner (TP2 full close / TP1 10% reduce / hold)
    candidate: entry_hard_veto → 否决/避开 ; event_data_gap restricted → 观察(data_restricted) ;
               price not executable → 观察(price_not_executable) ; else → 建仓 (PROVISIONAL)

The 4d-ii-a evidence is VALUE-validated at the boundary (not just shape): a malformed veto tier, a
context-incompatible hard veto (candidate position_hard_veto / holding entry_hard_veto), a veto/row
context mismatch, a non-bool price `executable`, a missing/non-bool holding `breached` (when consumed),
or an unknown `event_data_gap.status` fails closed — it must never become a clean 建仓 / 持有.

A 建仓 here is PROVISIONAL: §8 sizing (below-min → 观察), the weekly build-limit / 同主题 cap /
theme_probe, and the global cash allocation can each still downgrade it to 观察 in the later sub-slices
(4d-ii-c sizing, 4d-ii-d basket + §9 action_rank). This stage does NO sizing / cash / ranking / machine
record / render. It does NOT auto-decide 加仓 (§6 holding+add dual-engine path). The first-cut holding planner
may emit 减仓 (TP1 fixed 10% of reconciled shares) or 清仓-止盈 (TP2 full close); it does not implement add,
ratchet, move-to-breakeven, or multi-day active management.

`final_action` / `observe_reason_type` are emitted only from the frozen `design_locked_enums` vocab in
the action_table contract (a triangulation test pins the emitted subset, and the emitted final_action
values stay compatible with `us_short_action_rank.action_group`). Pure/offline; no provider/live/network;
no A-share crossing.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from engine.us_short_hard_veto import NONE as _VETO_NONE, VETO_TIERS
from engine.us_short_holding_action import TP1_REDUCE_FRACTION, plan_holding_action

_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_action_table_contract_20260620.json"
_ENUMS = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))["design_locked_enums"]
FINAL_ACTIONS = tuple(_ENUMS["final_action"])           # frozen §9/§6.1 trade-action vocab (9)
OBSERVE_REASONS = tuple(_ENUMS["observe_reason_type"])  # frozen §9 observe reasons (loaded from the contract enum)

# The base decision never emits 加仓. The holding planner below may additionally emit 减仓 / 清仓-止盈
# under the governed first-cut TP policy.
_A_REJECT, _A_OBSERVE, _A_BUILD = "否决/避开", "观察", "建仓"
_A_HOLD, _A_CLEAR_EVENT, _A_CLEAR_STOP = "持有", "清仓-事件", "清仓-止损"
_R_DATA_RESTRICTED, _R_PRICE_NOT_EXEC = "data_restricted", "price_not_executable"

# Evidence value-validation vocab (consumer-validation boundary). The veto tiers come from the §5 engine
# (single source — no second hardcoded ladder); the event-gap statuses mirror
# us_short_forward_events.event_data_gap_status (a behavioral triangulation test pins them).
_VALID_VETO_TIERS = frozenset(VETO_TIERS) | {_VETO_NONE}
_EVENT_GAP_STATUSES = ("ok", "restricted", "reduce_caution", "tag")


def action_reason_error(final_action, observe_reason_type):
    """SINGLE SOURCE §9 validator for the (final_action, observe_reason_type) pair — EVERY weekend-pipeline
    stage that emits OR carries the action/reason surface (decision / sizing / basket / cost-floor / any
    future stage) MUST use this and must NOT re-implement the check inline (a structural guard
    `tests/test_us_short_weekend_action_reason_contract.py` pins single-source + adversarially proves each
    stage rejects a bad pair). Returns an error-message string if the pair violates the frozen §9 action-table
    contract, else None: `final_action` must be a frozen action; a `观察` row must carry an
    `observe_reason_type ∈ OBSERVE_REASONS`; every OTHER action must carry `observe_reason_type is None` — so a
    bad / missing / stale reason on the wrong action can never pass a stage boundary."""
    if final_action not in FINAL_ACTIONS:
        return f"final_action 非法（不在冻结词表）: {final_action!r}"
    if final_action == _A_OBSERVE:
        if observe_reason_type not in OBSERVE_REASONS:
            return f"观察 行 observe_reason_type 须 ∈ 冻结词表: {observe_reason_type!r}"
    elif observe_reason_type is not None:
        return f"非观察行（{final_action}）不得带 observe_reason_type: {observe_reason_type!r}"
    return None


# §9 action↔price 一一对应契约 (design §9 line 253 + §6.1 line 210): an OFFICIAL final_action that NAMES a price
# MUST carry that execution/reference price — a priced state with a blank/non-finite price decouples 动作 from
# 价位 (设计明确禁止 "状态/价位脱钩"; R-USSHORT-BATCH4-ACTION-PRICE-MAPPING-GAP). SINGLE SOURCE for the matrix:
# the consumers (machine-record assembly BEFORE §10-clean via `_validate_ranked_row`; the §11.3 action_table
# projection via `_validate_price_projection`; and — through `flatten_machine_record` — private persistence) all
# call `action_price_error` and never re-hardcode the mapping. The field names are triangulated ⊆ the frozen
# §11.3 price columns and the keys == FINAL_ACTIONS by a test (no third drift surface). The matrix covers ALL 9
# frozen actions incl. the v1-deferred ones (加仓 / 减仓 / 清仓-止盈) so a later activation cannot bypass the gate;
# the N/A actions (持有 / 观察 / 否决-避开) require no price. Keyed by ACTION, not row-class — independent of
# `executable` (a non-executable 清仓-事件 must still carry its event reference price).
_A_ADD, _A_REDUCE, _A_CLEAR_TP = "加仓", "减仓", "清仓-止盈"
_ENTRY_PRICE_FIELDS = ("limit_order_price",)   # 建仓 / 加仓 → entry 价（可执行委托价）
ACTION_REQUIRED_PRICE_FIELDS = {
    _A_BUILD: _ENTRY_PRICE_FIELDS,
    _A_ADD: _ENTRY_PRICE_FIELDS,
    _A_REDUCE: ("take_profit_reduce_price",),    # 减仓（部分止盈）→ TP1
    _A_CLEAR_STOP: ("stop_clear_price",),        # 清仓-止损 → stop
    _A_CLEAR_TP: ("take_profit_exit_price",),    # 清仓-止盈 → TP2
    _A_CLEAR_EVENT: ("event_clear_reference_price",),  # 清仓-事件 → 事件清仓参考价
    _A_HOLD: (),
    _A_OBSERVE: (),
    _A_REJECT: (),
}


def _finite_positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0.0


def action_price_error(final_action, action_fields):
    """SINGLE SOURCE §9 action↔price validator — EVERY weekend-pipeline stage that builds OR flattens an
    OFFICIAL row (machine-record assembly / §11.3 action_table projection / private write) MUST use this and
    must NOT re-implement the mapping inline. An OFFICIAL `final_action` that names a price must carry that
    execution/reference price in `action_fields` as a finite POSITIVE number, else 动作与价位脱钩 (设计禁止).
    `action_fields` = the row's §6 price-engine `price.action_fields` dict. Returns an error-message string if
    the action's required price is missing / non-positive / non-finite, else None. N/A actions
    (持有 / 观察 / 否决-避开) and any action outside the matrix (the vocab gate is `action_reason_error`) require
    no price. Independent of `executable` / row class (an action-keyed contract, not a row-class one)."""
    required = ACTION_REQUIRED_PRICE_FIELDS.get(final_action, ())
    if not required:
        return None
    if not isinstance(action_fields, dict):
        return f"{final_action} 行 price.action_fields 须为 dict（§9 action↔price 一一对应）: {action_fields!r}"
    for field in required:
        v = action_fields.get(field)
        if not _finite_positive(v):
            return f"{final_action} 须带有限正 {field}（§9 action↔price 一一对应；缺/非正/非有限即脱钩）: {v!r}"
    return None


def action_quantity_error(final_action, row):
    """Validate the first-cut holding ``action → quantity → price`` closure.

    ``model_position_size_shares`` is a target size for a new build and is never accepted as a one-time
    sell quantity. Holding rows instead carry the typed ``action_proposal`` generated from reconciled shares.
    """
    if not isinstance(row, dict) or row.get("row_context") != "holding":
        return None
    proposal = row.get("action_proposal")
    if not isinstance(proposal, dict):
        return ("holding reduce/take-profit close lacks action_proposal (action/quantity/price closure)"
                if final_action in (_A_REDUCE, _A_CLEAR_TP) else None)
    shares = proposal.get("recommended_action_shares")
    remaining = proposal.get("remaining_shares")
    if final_action == _A_OBSERVE and remaining is None:
        return None  # explicit fail-closed account/state observe; it must not invent a holding quantity
    if final_action in (_A_CLEAR_STOP, _A_CLEAR_EVENT) and shares is None and remaining is None:
        expected_field = ACTION_REQUIRED_PRICE_FIELDS[final_action][0]
        if proposal.get("reason") != "mandatory_holding_exit_manual_share_confirmation":
            return f"{final_action} without reconciled shares must require manual share confirmation"
        if proposal.get("price_target_field") != expected_field:
            return f"{final_action} action_proposal.price_target_field must be {expected_field!r}"
        return None
    if not (isinstance(remaining, int) and not isinstance(remaining, bool) and remaining >= 1):
        return "holding action_proposal.remaining_shares must be a positive int"
    if final_action in (_A_REDUCE, _A_CLEAR_STOP, _A_CLEAR_TP, _A_CLEAR_EVENT):
        if not (isinstance(shares, int) and not isinstance(shares, bool) and 1 <= shares <= remaining):
            return f"{final_action} requires a positive reconciled recommended_action_shares"
        expected_field = ACTION_REQUIRED_PRICE_FIELDS[final_action][0]
        if proposal.get("price_target_field") != expected_field:
            return f"{final_action} action_proposal.price_target_field must be {expected_field!r}"
        if final_action == _A_REDUCE:
            if proposal.get("tp1_completed") is True:
                return "TP1-completed holding may not emit another TP1 reduction"
            expected_shares = int(remaining * TP1_REDUCE_FRACTION)
            if expected_shares < 1 or shares != expected_shares:
                return "TP1 reduction must equal the governed 10% of remaining shares"
        elif shares != remaining:
            return f"{final_action} must recommend all reconciled remaining shares"
    elif shares is not None:
        return f"{final_action} holding must not carry a sell quantity"
    return None


class WeekendDecisionError(Exception):
    """The injected analysis-evidence result is malformed (fail-closed before the decision runs)."""


def validate_evidence_row(ev):
    """Fail-closed VALUE validation of one 4d-ii-a evidence row before it maps to a §9 action — a
    malformed veto tier, a context-incompatible hard veto, a veto/row context mismatch, a non-bool price
    `executable`, a missing/non-bool holding `breached` (when consumed), or an unknown
    `event_data_gap.status` must NOT become a clean 建仓 / 持有 (the consumer-validation boundary)."""
    if not (isinstance(ev, dict) and ev.get("row_context") in ("candidate", "holding")):
        raise WeekendDecisionError(f"analysis-evidence row 须为含 row_context(candidate/holding) 的 dict: {ev!r}")
    ctx = ev["row_context"]
    veto = ev.get("veto")
    if not isinstance(veto, dict) or veto.get("veto_tier") not in _VALID_VETO_TIERS:
        raise WeekendDecisionError(f"veto 须为含合法 veto_tier(∈ {sorted(_VALID_VETO_TIERS)}) 的 dict: {veto!r}")
    tier = veto["veto_tier"]
    vctx = veto.get("row_context")
    if vctx is not None and vctx != ctx:
        raise WeekendDecisionError(f"veto.row_context({vctx!r}) 与 row_context({ctx!r}) 不一致")
    if ctx == "candidate" and tier == "position_hard_veto":
        raise WeekendDecisionError("candidate 行不得带 position_hard_veto（context-incompatible 证据）")
    if ctx == "holding" and tier == "entry_hard_veto":
        raise WeekendDecisionError("holding 行不得带 entry_hard_veto（context-incompatible 证据）")
    price = ev.get("price")
    if not (isinstance(price, dict) and isinstance(price.get("executable"), bool)
            and isinstance(price.get("trace"), dict)):
        raise WeekendDecisionError(f"price 须为含 bool executable + trace dict 的 dict: {price!r}")
    if ctx == "holding" and price["executable"] and not isinstance(price["trace"].get("breached"), bool):
        raise WeekendDecisionError("executable holding 的 price.trace.breached 须为 bool（被消费）")
    gap = ev.get("event_data_gap")
    if gap is not None and not (isinstance(gap, dict) and gap.get("status") in _EVENT_GAP_STATUSES):
        raise WeekendDecisionError(f"event_data_gap.status 须 ∈ {_EVENT_GAP_STATUSES}: {gap!r}")


def _decide_one(ev):
    """§6 priority chain → §9 (final_action, observe_reason_type) for one VALIDATED 4d-ii-a evidence row.
    Holdings exit on a hard position veto (manual event clear), observe a non-executable (data-degraded)
    price (never a clean hold from missing levels, §6), clear on a breached trailing stop, else hold;
    candidates are rejected on an entry hard veto, observed on a restricted event-data gap or a
    non-executable price plan, else a PROVISIONAL 建仓 (downstream sizing / build-limit / cash may still
    downgrade to 观察)."""
    veto_tier = ev["veto"]["veto_tier"]
    price = ev["price"]
    if ev["row_context"] == "holding":
        if veto_tier == "position_hard_veto":
            return _A_CLEAR_EVENT, None          # §5/§9 hard position risk → manual event clear (event_clear_reference_price)
        if not price["executable"]:
            return _A_OBSERVE, _R_PRICE_NOT_EXEC  # §6 data-degraded holding: levels not computable → not a clean hold
        if price["trace"]["breached"]:            # validated bool when an executable holding is consumed
            return _A_CLEAR_STOP, None            # §6.1 price hit the trailing stop
        return _A_HOLD, None                      # the reconciled TP planner decides any first-cut reduction/TP2 exit
    # candidate
    if veto_tier == "entry_hard_veto":
        return _A_REJECT, None
    if (ev.get("event_data_gap") or {}).get("status") == "restricted":
        return _A_OBSERVE, _R_DATA_RESTRICTED     # §8.1 sensitive name missing its event data → don't build
    if not price["executable"]:
        return _A_OBSERVE, _R_PRICE_NOT_EXEC      # §6 no executable price plan (RR / structure / missing-data reject)
    return _A_BUILD, None                         # provisional build (§8 sizing / build-limit / cash downstream)


def decide_actions(analysis_result):
    """4d-ii-b action-decision stage. Consumes the 4d-ii-a `analyze_rows` result ({regime, rows}) and
    enriches each evidence row with `final_action` (+ `observe_reason_type`, None unless 观察), decided
    from the §6 priority chain over the evidence alone (additive — every evidence field is carried
    through for the downstream sizing / basket / machine-record stages).

    Returns {"regime": <carried>, "rows": [{...evidence, "final_action", "observe_reason_type"}, ...]}.
    Raises WeekendDecisionError on a malformed analysis_result / rows container, or an evidence-row whose
    shape OR value is invalid (bad veto tier, context-incompatible veto, non-bool price executable /
    holding breached, unknown event_data_gap.status) — malformed evidence never becomes a clean action."""
    if not (isinstance(analysis_result, dict) and "regime" in analysis_result and "rows" in analysis_result):
        raise WeekendDecisionError("analysis_result 须为含 regime + rows 的 4d-ii-a 输出")
    rows = analysis_result["rows"]
    if not isinstance(rows, list):
        raise WeekendDecisionError("analysis_result.rows 须为 list")
    decided = []
    for ev in rows:
        validate_evidence_row(ev)
        action, reason = _decide_one(ev)
        proposal, decided_price = None, ev["price"]
        if ev["row_context"] == "holding":
            action, reason, proposal, decided_price = plan_holding_action(ev, action, reason)
        err = action_reason_error(action, reason)   # producer self-check: no _decide_one path may emit a bad §9 pair
        if err:
            raise WeekendDecisionError(err)
        decided.append({**ev, "price": decided_price, "action_proposal": proposal,
                        "final_action": action, "observe_reason_type": reason})
    return {"regime": analysis_result["regime"], "rows": decided}
