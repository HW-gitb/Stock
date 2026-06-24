# -*- coding: utf-8 -*-
"""US-short weekend-pipeline per-row action decision — batch4 slice 4d-ii-b (§6 priority chain → §9 final_action).

Design authority: docs/us_short_system_design.md §6 (优先级链) / §6.1 (持仓 v1 只出基础价位) / §9
(action_rank vocab + 5-group) / §5 (veto tiers) / §8.1 (forward) / §18.2 batch4.

The third batch-4 stage: consumes the 4d-ii-a analysis EVIDENCE ({regime, rows}) and assigns each row a
§9 `final_action` (+ `observe_reason_type` when 观察) from the §6 priority chain, using the EVIDENCE
ALONE (veto tier, price executable/reject, event-sensitive data gap). v1 decisions:

    holding:   position_hard_veto → 清仓-事件 ; price not executable → 观察(price_not_executable) ;
               price breached → 清仓-止损 ; else → 持有
    candidate: entry_hard_veto → 否决/避开 ; event_data_gap restricted → 观察(data_restricted) ;
               price not executable → 观察(price_not_executable) ; else → 建仓 (PROVISIONAL)

The 4d-ii-a evidence is VALUE-validated at the boundary (not just shape): a malformed veto tier, a
context-incompatible hard veto (candidate position_hard_veto / holding entry_hard_veto), a veto/row
context mismatch, a non-bool price `executable`, a missing/non-bool holding `breached` (when consumed),
or an unknown `event_data_gap.status` fails closed — it must never become a clean 建仓 / 持有.

A 建仓 here is PROVISIONAL: §8 sizing (below-min → 观察), the weekly build-limit / 同主题 cap /
theme_probe, and the global cash allocation can each still downgrade it to 观察 in the later sub-slices
(4d-ii-c sizing, 4d-ii-d basket + §9 action_rank). This stage does NO sizing / cash / ranking / machine
record / render. It also does NOT auto-decide 加仓 (§6 holding+add dual-engine path) or 减仓 / 清仓-止盈
(§6.1 active scale-out = §13 #34 deferred) — those vocab values exist but v1 does not emit them here.

`final_action` / `observe_reason_type` are emitted only from the frozen `design_locked_enums` vocab in
the action_table contract (a triangulation test pins the emitted subset, and the emitted final_action
values stay compatible with `us_short_action_rank.action_group`). Pure/offline; no provider/live/network;
no A-share crossing.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.us_short_hard_veto import NONE as _VETO_NONE, VETO_TIERS

_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_action_table_contract_20260620.json"
_ENUMS = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))["design_locked_enums"]
FINAL_ACTIONS = tuple(_ENUMS["final_action"])           # frozen §9/§6.1 trade-action vocab (9)
OBSERVE_REASONS = tuple(_ENUMS["observe_reason_type"])  # frozen §9 observe reasons (loaded from the contract enum)

# The SUBSET this evidence-only stage emits (v1). 加仓 (§6 dual-engine) and 减仓 / 清仓-止盈 (§6.1 active
# scale-out, §13 #34) are in the frozen vocab but NOT auto-decided here.
_A_REJECT, _A_OBSERVE, _A_BUILD = "否决/避开", "观察", "建仓"
_A_HOLD, _A_CLEAR_EVENT, _A_CLEAR_STOP = "持有", "清仓-事件", "清仓-止损"
_R_DATA_RESTRICTED, _R_PRICE_NOT_EXEC = "data_restricted", "price_not_executable"

# Evidence value-validation vocab (consumer-validation boundary). The veto tiers come from the §5 engine
# (single source — no second hardcoded ladder); the event-gap statuses mirror
# us_short_forward_events.event_data_gap_status (a behavioral triangulation test pins them).
_VALID_VETO_TIERS = frozenset(VETO_TIERS) | {_VETO_NONE}
_EVENT_GAP_STATUSES = ("ok", "restricted", "reduce_caution", "tag")


class WeekendDecisionError(Exception):
    """The injected analysis-evidence result is malformed (fail-closed before the decision runs)."""


def _validate_evidence_row(ev):
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
        return _A_HOLD, None                      # §6.1 v1 emits base levels; active scale-out (减仓/止盈) = §13 #34
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
        _validate_evidence_row(ev)
        action, reason = _decide_one(ev)
        decided.append({**ev, "final_action": action, "observe_reason_type": reason})
    return {"regime": analysis_result["regime"], "rows": decided}
