# -*- coding: utf-8 -*-
"""US-short weekend-pipeline §10 machine-record assembly — batch4 slice 4d-ii-k (machine_record 装配 + no-dangling).

Design authority: docs/us_short_system_design.md §10 (不悬空 + 证据反查 + 字段 registry, 机器强制) /
§11.1 (机器层 = operation_impact + 全字段 + 原始分数 + decision_trace + registry → runs_private) /
§18.1 #9 / §18.2 batch4 slice 4d.

The post-pass after 4d-ii-j (`apply_action_rank`). It ASSEMBLES the finalized ranked rows into the §10
machine record (run-level as_of + rows[] each with `field_records[]` + `decision_trace`), then runs the
batch-3 `validate_official_machine_record` and FAILS CLOSED if the record is not §10-clean — a producer never emits a
not-clean machine record (the renderer / private-write stages downstream consume only a clean record). It
ASSEMBLES only — it does NOT render (4d-ii-m) or persist (4d-ii-n); the §10 cross-field invariants
(forward no-dangling, hard_veto→final_action kill/exit, core-field-hits-a-target-or-shadow,
risk-downgrade-soft, selection-vs-action_rank-explained) are OWNED by `validate_machine_record` reading the
frozen governance presets (single source — this module adds NO third copy of the §10 vocab).

Assembly is FAITHFUL to what each row actually computed (the additive carry-through from 4d-ii-a..j): for
each row it emits a `field_record` for every CORE field that was computed, with the disposition that reflects
whether the field LANDED on this row's action (drove final_action / action_rank / position_size / price) or
is recorded as a clean SHADOW (computed, did not drive THIS row). operation_impact mapping (a technical
choice over the §10 risk-centric taxonomy 硬否决/降仓/调信心/仅标签): a fired hard veto → 硬否决 landing on
final_action; a position-affecting field (sizing / market_risk_regime cap / theme_probe forced-min) → 降仓 →
position_size; a soft real driver (price levels / selection score) → 调信心 → price / action_rank; a
computed-but-not-driving field → 仅标签 on a `shadow_record` advisory landing (仅标签 is kept ONLY for true
advisory/shadow landings per §10, never for a real column impact).

This module fabricates NO evidence it does not have offline: a live provider-row / SEC-filing
`evidence_ref` for an event CLAIM (临近财报 / S-3 / FDA / 做空报告 / 赛道热度 / 新闻催化) is batch5, so v1
emits `claim_type=None` (no unevidenced claim is ever asserted as an operation impact — §10 反向证据反查).

Single-source consumer-validation (§9 action/reason via `action_reason_error`, canonical-unique ticker
identity), the same boundary the basket / cost-floor / cash / action-rank stages enforce. Pure/offline; no
provider/live/network; no broker/auto-order; no A-share crossing.
"""
from __future__ import annotations

import math

from engine.us_short_action_rank import ACTION_RANK_SKELETON, action_group as _expected_action_group
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_hard_veto import VETO_TIERS
from engine.us_short_no_dangling_validator import validate_official_machine_record
from engine.us_short_overextension import validate_overextension_result
from engine.us_short_position_sizing import MIN_EXECUTABLE_SHARES
from engine.us_short_regime import REGIMES as _MARKET_RISK_REGIMES
from engine.us_short_risk_downgrade import validate_risk_downgrade_input
from engine.us_short_result_effects import ResultEffectsError, validate_result_effects
from engine.us_short_result_source_linkage import ResultSourceLinkageError, validate_result_source_fact
from engine.us_short_macro_cluster import WARNING_LEVELS
from engine.us_short_theme_lifecycle import THEME_STATES
from engine.us_short_theme_selection import THEME_SOURCES
from engine.us_short_run_origin import (
    OFFLINE_TEST_RUN_ORIGIN,
    require_research_live_capability,
    validate_run_origin,
)
from engine.us_short_theme_probe import RISK_TAG as _PROBE_RISK_TAG
from engine.us_short_weekend_cost_floor import (
    _ENTRY_MODE_CONSTRAINTS,
    _PROBE_SIZING_REASON,
    _PROBE_TRACE_KEYS,
)
from engine.us_short_weekend_decision import (
    WeekendDecisionError,
    validate_evidence_row,
    action_reason_error,
    action_price_error,
    action_quantity_error,
)

_SCHEMA_NAME = "us_short_machine_record_contract"
_SCHEMA_VERSION = "1.0.0"

# §9 ranked-result vocab (single-source from the action_rank engine): the 5 valid action groups + the §9
# group mapping (`_expected_action_group`) used to verify a row's carried action_group is the real one.
_VALID_ACTION_GROUPS = frozenset(ACTION_RANK_SKELETON)  # (1,2,3,4,5)

# §8 4d-ii-g/4d-ii-h promoted-probe contract — REUSED from the cost-floor stage (single source, NO third copy):
# the trace keys, the legal entry-mode constraints (pinned to theme_probe.defensive_entry_constraint by the
# cost-floor triangulation test), and the forced-min sizing reason. A theme_probe is a §8 forced-min build, so
# the assembler validates the SAME forced-min sizing contract before it LANDS the theme states on position_size
# (risk_tag from the theme_probe engine, MIN_EXECUTABLE_SHARES from position_sizing, regime vocab from regime).
_BUILD = "建仓"

# The two §5 tiers that are a HARD veto (force a kill/exit final_action). The other VETO_TIERS members
# (strong_downgrade / soft_risk_tag / shadow_record) are soft and — in v1 — are NOT acted on by the §6
# decision chain (§5.2 candidate hard-vetoes are forward-gated, hard_veto.py docstring), so a soft tier is
# recorded as a clean SHADOW here, never a 硬否决. DERIVED from the engine ladder (single source): the two
# highest-severity tiers VETO_TIERS[:2] (entry_hard_veto / position_hard_veto), pinned by a triangulation test.
_HARD_VETO_TIERS = frozenset(VETO_TIERS[:2])

_LANDED = "landed"
_SHADOW = "shadow_record"
_SHADOW_TERMINAL = "shadow_record"  # an advisory landing (§10 ADVISORY_LANDINGS) for a computed-but-not-driving field

# Static §10 field-registry declarations. owner_module / data_source / pit_basis / privacy_class / field_class
# / lifecycle_item_id are STATIC per field_id; the landing / impact / op / disposition are RESOLVED per row by
# `_field_records`. lifecycle_item_id is grounded in us_short_lifecycle_calibration_governance §13.1 numbers
# (1 选股权重 / 3 环境阈值 / 4 仓位参数 / 6 候选价格引擎 / 7 §5.2 候选硬否决 / 15 未来事件 / 27 theme_opportunity 试探
# 仓 / 30 赛道退场衰减+状态转移). data_source is offline/injected in batch4; the live provider source is batch5.
_PIT = "decision_date"
_PRIVATE = "private"  # the machine layer lands in runs_private (§11.1)
_SPECS = {
    "hard_veto": {"owner_module": "engine.us_short_hard_veto", "data_source": "row.veto (injected; live=batch5)",
                  "field_class": "hard veto", "lifecycle_item_id": 7},
    "core_score": {"owner_module": "engine.us_short_core_score", "data_source": "row.score (injected; live=batch5)",
                   "field_class": "selection", "lifecycle_item_id": 1},
    "risk_downgrade": {"owner_module": "engine.us_short_risk_downgrade",
                       "data_source": "row.risk_downgrade (injected; live=batch5)",
                       "field_class": "risk downgrade", "lifecycle_item_id": 7},
    "price": {"owner_module": "engine.us_short_price_engine", "data_source": "row.price (injected; live=batch5)",
              "field_class": "price", "lifecycle_item_id": 6},
    "sizing": {"owner_module": "engine.us_short_position_sizing", "data_source": "row.sizing (injected; live=batch5)",
               "field_class": "sizing", "lifecycle_item_id": 4},
    "market_risk_regime": {"owner_module": "engine.us_short_regime", "data_source": "result.regime (injected; live=batch5)",
                           "field_class": "market_risk_regime", "lifecycle_item_id": 3},
    "theme_id": {"owner_module": "engine.us_short_theme_result_linkage",
                 "data_source": "row.theme_context.evidence_ref",
                 "field_class": "theme identity", "lifecycle_item_id": 1},
    "theme_source": {"owner_module": "engine.us_short_theme_result_linkage",
                     "data_source": "row.theme_context.evidence_ref",
                     "field_class": "theme identity", "lifecycle_item_id": 1},
    "theme_lifecycle_state": {"owner_module": "engine.us_short_theme_result_linkage",
                              "data_source": "row.theme_context.evidence_ref",
                              "field_class": "theme_lifecycle_state", "lifecycle_item_id": 30},
    "theme_opportunity_state": {"owner_module": "engine.us_short_theme_probe", "data_source": "row.theme_probe (injected; live=batch5)",
                                "field_class": "theme_opportunity_state", "lifecycle_item_id": 27},
    "forward_event": {"owner_module": "engine.us_short_forward_events", "data_source": "row.forward_event (injected; live=batch5)",
                      "field_class": "trigger", "lifecycle_item_id": 15},
    "event_data_gap": {"owner_module": "engine.us_short_forward_events", "data_source": "row.event_data_gap (injected; live=batch5)",
                       "field_class": "data quality", "lifecycle_item_id": 15},
    "portfolio_guard": {"owner_module": "engine.us_short_portfolio_guard", "data_source": "result.portfolio_guard_result (model-paper track)",
                        "field_class": "portfolio_guard", "lifecycle_item_id": 22},
    "symbol_cooldown": {"owner_module": "engine.us_short_symbol_cooldown_state", "data_source": "private symbol cooldown state + manual reconciliation",
                        "field_class": "symbol_cooldown", "lifecycle_item_id": 23},
    "overextension_state": {"owner_module": "engine.us_short_overextension",
                            "data_source": "row.overextension (injected; live=batch5)",
                            "field_class": "overextension", "lifecycle_item_id": 36},
    "macro_cluster": {"owner_module": "engine.us_short_macro_cluster",
                      "data_source": "row.theme_context.macro_cluster + provisional sizing exposure",
                      "field_class": "macro cluster", "lifecycle_item_id": 31},
    "source_coverage": {"owner_module": "engine.us_short_result_source_linkage",
                        "data_source": "row.source_result_facts.coverage (Batch5 receipt-bound)",
                        "field_class": "data quality", "lifecycle_item_id": 15},
    "source_catalyst": {"owner_module": "engine.us_short_result_source_linkage",
                        "data_source": "row.source_result_facts.catalyst (existing catalyst projection)",
                        "field_class": "data quality", "lifecycle_item_id": 1},
}


class WeekendMachineRecordError(Exception):
    """The injected ranked result / row is malformed, or the assembled machine record is not §10-clean
    (fail-closed before the record is treated as an official output)."""


def _fr(field_id, *, op, terminal, disposition, impact_target, claim_type=None, evidence_ref=None):
    """Build one §10 field_record (the 12 const-pinned registry keys + the runtime resolution). v1 carries no
    traceable claim offline → claim_type / evidence_ref None (the §10 reverse-traceback path is exercised by
    the batch-3 validator suite; the live provider/SEC evidence_ref is batch5)."""
    spec = _SPECS[field_id]
    return {
        "field_id": field_id,
        "owner_module": spec["owner_module"],
        "data_source": spec["data_source"],
        "pit_basis": _PIT,
        "privacy_class": _PRIVATE,
        "current_landing_surface": terminal,
        "terminal_surface_target": terminal,
        "operation_impact": op,
        "evidence_ref_kind": evidence_ref["kind"] if isinstance(evidence_ref, dict) else None,
        "lifecycle_item_id": spec["lifecycle_item_id"],
        "field_class": spec["field_class"],
        "disposition": disposition,
        "impact_target": impact_target,
        "claim_type": claim_type,
        "evidence_ref": evidence_ref,
    }


_EVENT_CLAIMS = {
    "earnings": "临近财报",
    "fda_pdufa": "FDA",
    "index_inclusion": "新闻催化",
    "lockup_expiry": "新闻催化",
    "ex_dividend": "新闻催化",
}


def _formal_effect_field_records(row):
    """Register second-cut producers at their actual final output landing without re-deciding them."""
    if "result_effects" not in row:
        return []
    effects = row["result_effects"]
    refs = effects["evidence_refs"]
    out = []

    guard = row["portfolio_guard_status"]
    guard_ref = refs["portfolio_guard"]
    if guard == "caution":
        out.append(_fr("portfolio_guard", op="调信心", terminal="action_confidence",
                       disposition=_LANDED, impact_target="action_confidence", evidence_ref=guard_ref))
    elif guard == "normal":
        out.append(_fr("portfolio_guard", op="仅标签", terminal="portfolio_guard_status",
                       disposition=_SHADOW, impact_target=None, evidence_ref=guard_ref))
    else:
        out.append(_fr("portfolio_guard", op="仅标签", terminal="risk_tags",
                       disposition=_LANDED, impact_target="risk_tags", evidence_ref=guard_ref))

    cooldown = row["symbol_cooldown_status"]
    cooldown_ref = refs["symbol_cooldown"]
    if cooldown == "none":
        out.append(_fr("symbol_cooldown", op="仅标签", terminal="symbol_cooldown_status",
                       disposition=_SHADOW, impact_target=None, evidence_ref=cooldown_ref))
    else:
        out.append(_fr("symbol_cooldown", op="仅标签", terminal="risk_tags",
                       disposition=_LANDED, impact_target="risk_tags", evidence_ref=cooldown_ref))

    forward = row.get("forward_event")
    if isinstance(forward, dict):
        if forward.get("in_window") is True:
            event_type = forward.get("event_type")
            event_ref = refs.get("upcoming_event:" + event_type) if isinstance(event_type, str) else None
            direction = forward.get("direction")
            claim_type = _EVENT_CLAIMS.get(event_type)
            if direction == "reduce_caution":
                out.append(_fr("forward_event", op="降仓", terminal="model_position_size_shares",
                               disposition=_LANDED, impact_target="position_size",
                               claim_type=claim_type, evidence_ref=event_ref))
            elif direction == "reduce_or_observe":
                out.append(_fr("forward_event", op="调信心", terminal="final_action",
                               disposition=_LANDED, impact_target="final_action",
                               claim_type=claim_type, evidence_ref=event_ref))
            else:
                out.append(_fr("forward_event", op="仅标签", terminal="risk_tags",
                               disposition=_LANDED, impact_target="risk_tags",
                               claim_type=claim_type, evidence_ref=event_ref))
        else:
            out.append(_fr("forward_event", op="仅标签", terminal=_SHADOW_TERMINAL,
                           disposition=_SHADOW, impact_target=None))

    gap = row.get("event_data_gap")
    if isinstance(gap, dict):
        if gap["status"] == "reduce_caution":
            out.append(_fr("event_data_gap", op="降仓", terminal="model_position_size_shares",
                           disposition=_LANDED, impact_target="position_size",
                           evidence_ref=refs.get("size:event_data_gap")))
        elif gap["status"] in {"restricted", "tag"}:
            out.append(_fr("event_data_gap", op="仅标签", terminal="risk_tags",
                           disposition=_LANDED, impact_target="risk_tags",
                           evidence_ref=refs.get("risk_tag:event_data_gap:" + gap["status"])))
        else:
            out.append(_fr("event_data_gap", op="仅标签", terminal=_SHADOW_TERMINAL,
                           disposition=_SHADOW, impact_target=None))
    return out


def _theme_macro_field_records(row):
    facts = row.get("source_result_facts")
    if facts is not None:
        try:
            validate_result_source_fact(
                facts, ticker=row.get("ticker"), row_source=row.get("row_source"),
                as_of=facts.get("as_of") if isinstance(facts, dict) else None,
                price_basis_date=facts.get("price_basis_date") if isinstance(facts, dict) else None,
            )
        except ResultSourceLinkageError as exc:
            raise WeekendMachineRecordError(f"Cut4 source_result_facts invalid: {exc}") from exc
        projections = {
            "coverage_status": facts["coverage"]["coverage_status"],
            "coverage_gap_tags": facts["coverage"]["coverage_gap_tags"],
            "data_quality_tags": facts["data_quality_tags"],
            "execution_constraints": facts["execution_constraints"],
        }
        for key, expected in projections.items():
            if row.get(key) != expected:
                raise WeekendMachineRecordError(f"Cut4 {key} is not projected from source_result_facts")

    theme = row.get("theme_context")
    if not isinstance(theme, dict):
        return []
    evidence = theme.get("evidence_ref")
    out = [
        _fr("theme_id", op="仅标签", terminal="theme_id",
            disposition=_LANDED, impact_target=None, evidence_ref=evidence),
        _fr("theme_source", op="仅标签", terminal="theme_source",
            disposition=_LANDED, impact_target=None, evidence_ref=evidence),
    ]
    effects = row.get("result_effects") if isinstance(row.get("result_effects"), dict) else {}
    refs = effects.get("evidence_refs") if isinstance(effects.get("evidence_refs"), dict) else {}
    lifecycle_source = "theme_lifecycle:" + str(theme.get("theme_lifecycle_state"))
    lifecycle_ref = refs.get("effect:" + lifecycle_source)
    override = effects.get("action_override")
    if isinstance(override, dict) and override.get("source") == lifecycle_source:
        out.append(_fr("theme_lifecycle_state", op="调信心", terminal="final_action",
                       disposition=_LANDED, impact_target="final_action", evidence_ref=lifecycle_ref))
    elif any(isinstance(item, dict) and item.get("source") == lifecycle_source
             for item in effects.get("confidence_cap_candidates", [])):
        out.append(_fr("theme_lifecycle_state", op="调信心", terminal="action_confidence",
                       disposition=_LANDED, impact_target="action_confidence", evidence_ref=lifecycle_ref))
    elif lifecycle_ref is not None:
        out.append(_fr("theme_lifecycle_state", op="仅标签", terminal="risk_tags",
                       disposition=_LANDED, impact_target="risk_tags", evidence_ref=lifecycle_ref))
    else:
        out.append(_fr("theme_lifecycle_state", op="仅标签", terminal="theme_lifecycle_state",
                       disposition=_SHADOW, impact_target=None, evidence_ref=evidence))

    warning = row.get("macro_cluster_warning_level")
    macro_source = "macro_cluster:" + str(warning)
    macro_ref = refs.get("effect:" + macro_source) or evidence
    if warning == "high" and row.get("macro_cluster_size_adjustment", 0) > 0 and any(
        isinstance(item, dict) and item.get("source") == macro_source
        for item in effects.get("size_reduction_candidates", [])
    ):
        out.append(_fr("macro_cluster", op="降仓", terminal="model_position_size_shares",
                       disposition=_LANDED, impact_target="position_size", evidence_ref=macro_ref))
    elif warning == "high":
        out.append(_fr("macro_cluster", op="调信心", terminal="action_confidence",
                       disposition=_LANDED, impact_target="action_confidence", evidence_ref=macro_ref))
    elif warning == "elevated":
        out.append(_fr("macro_cluster", op="仅标签", terminal="risk_tags",
                       disposition=_LANDED, impact_target="risk_tags", evidence_ref=macro_ref))
    else:
        out.append(_fr("macro_cluster", op="仅标签", terminal="macro_cluster",
                       disposition=_SHADOW, impact_target=None, evidence_ref=evidence))
    return out


def _source_result_field_records(row):
    """Register Cut4 receipt-bound source facts at their final result landing.

    A realized catalyst already entered the existing core score and therefore traces to action_rank.  An
    unavailable/gated catalyst is routed through the source-coverage confidence effect instead of receiving a
    second numerical penalty.
    """
    facts = row.get("source_result_facts")
    if not isinstance(facts, dict):
        return []
    catalyst = facts["catalyst"]
    out = [_fr("source_coverage", op="\u4ec5\u6807\u7b7e", terminal="coverage_status",
               disposition=_LANDED, impact_target="risk_tags", evidence_ref=facts["evidence_ref"])]
    out.append(_fr("source_catalyst", op="\u4ec5\u6807\u7b7e", terminal="data_quality_tags",
                   disposition=_LANDED, impact_target="risk_tags", evidence_ref=catalyst["evidence_ref"]))
    return out


def _field_records(row):
    """Assemble the §10 field_records for one finalized row, faithful to what it computed. Defensive reads
    (a malformed evidence field degrades to a conservative SHADOW, never a fabricated landing); the assembled
    record is the validator's responsibility to clear."""
    frs = []

    # hard_veto (§5) — always computed. A hard tier (entry/position_hard_veto) → 硬否决 landing on
    # final_action (the validator then checks this row's final_action is a kill/exit); any other tier
    # (soft / none / malformed) → the hard veto did not fire → clean shadow.
    veto = row.get("veto")
    tier = veto.get("veto_tier") if isinstance(veto, dict) else None
    if tier in _HARD_VETO_TIERS:
        frs.append(_fr("hard_veto", op="硬否决", terminal="final_action", disposition=_LANDED, impact_target="final_action"))
    else:
        frs.append(_fr("hard_veto", op="仅标签", terminal=_SHADOW_TERMINAL, disposition=_SHADOW, impact_target=None))

    # price (§6) — always computed. An executable plan lands on the price columns; a non-executable / malformed
    # price produced no usable plan → shadow.
    price = row.get("price")
    if isinstance(price, dict) and price.get("executable") is True:
        frs.append(_fr("price", op="调信心", terminal="entry_plan", disposition=_LANDED, impact_target="price"))
    else:
        frs.append(_fr("price", op="仅标签", terminal=_SHADOW_TERMINAL, disposition=_SHADOW, impact_target=None))

    # core_score / selection (§4.2) — only candidates carry a score; it lands on action_rank.
    if isinstance(row.get("score"), dict):
        frs.append(_fr("core_score", op="调信心", terminal="action_rank", disposition=_LANDED, impact_target="action_rank"))
        # §4.2 risk_downgrade (§5.2 soft, never a hard veto) is SUBTRACTED inside core_score, so a real penalty
        # (points>0) demonstrably lowers the core_score that drives the §9 action_rank (group-2 builds order by
        # selection_rank, set from core_score) → LANDED on `action_rank`, the SAME populated surface core_score
        # lands on (an always-present rank value, unlike the never-computed action_confidence cell). Zero penalty
        # → a clean SHADOW (computed, did not drive). Every scored candidate carries it
        # (R-USSHORT-BATCH4-RISK-DOWNGRADE-WIRING-GAP); the assembler validated the typed input above.
        rd = row.get("risk_downgrade")
        rd_pts = rd.get("points") if isinstance(rd, dict) else None
        if isinstance(rd_pts, (int, float)) and not isinstance(rd_pts, bool) and rd_pts > 0.0:
            frs.append(_fr("risk_downgrade", op="调信心", terminal="action_rank",
                           disposition=_LANDED, impact_target="action_rank"))
        else:
            frs.append(_fr("risk_downgrade", op="仅标签", terminal=_SHADOW_TERMINAL,
                           disposition=_SHADOW, impact_target=None))

    # sizing (§8) — a real sized build (incl. a build later downgraded to 观察 by cash/capacity, which still
    # carries the computed size on the model_position_size_shares column). market_risk_regime (§7) is always
    # computed run-level: on a sized row the regime cap fed that sizing → 降仓 → position_size; otherwise the
    # regime is recorded as shadow (it did not size THIS row).
    sizing = row.get("sizing")
    sized = isinstance(sizing, dict) and sizing.get("status") == "sized"
    if sized:
        frs.append(_fr("sizing", op="降仓", terminal="model_position_size_shares", disposition=_LANDED, impact_target="position_size"))
        frs.append(_fr("market_risk_regime", op="降仓", terminal="model_position_size_shares", disposition=_LANDED, impact_target="position_size"))
    else:
        frs.append(_fr("market_risk_regime", op="仅标签", terminal=_SHADOW_TERMINAL, disposition=_SHADOW, impact_target=None))

    # theme_probe rows (§8 強赛道试探) — lifecycle is now source-bound through theme_context; only the
    # opportunity-state landing remains probe-specific here.
    if isinstance(row.get("theme_probe"), dict):
        if not isinstance(row.get("theme_context"), dict):
            frs.append(_fr("theme_lifecycle_state", op="降仓", terminal="model_position_size_shares",
                           disposition=_LANDED, impact_target="position_size"))
        frs.append(_fr("theme_opportunity_state", op="降仓", terminal="model_position_size_shares", disposition=_LANDED, impact_target="position_size"))

    # forward known-date event (§8.1) — v1 display-only (sizing/risk/display, never selection/veto); recorded
    # as a clean shadow until the live evidence_ref traceback (provider row / SEC filing) is wired in batch5.
    if "result_effects" not in row and isinstance(row.get("forward_event"), dict):
        frs.append(_fr("forward_event", op="仅标签", terminal=_SHADOW_TERMINAL, disposition=_SHADOW, impact_target=None))

    # §4.3 overextension_state (cut 2d) — the §4.3 tier computed at the scoring stage; its EXECUTION effect
    # (warning→forced pullback) is already registered via the `price` field_record (the plan is pullback), so
    # here the STATE lands on its own §11.3 overextension_state column as an advisory tag (仅标签). Emitted only
    # when the row carries a valid tier result (a malformed one was rejected by `_validate_ranked_row`).
    ox = row.get("overextension")
    if isinstance(ox, dict):
        frs.append(_fr("overextension_state", op="仅标签", terminal="overextension_state",
                       disposition=_LANDED, impact_target=None))

    frs.extend(_formal_effect_field_records(row))
    frs.extend(_theme_macro_field_records(row))
    frs.extend(_source_result_field_records(row))

    return frs


def _decision_trace(row):
    """A non-empty per-row §10 decision_trace — where the deliberate selection_rank (多强) vs action_rank
    (先干哪个) divergence is explained: a must-act holding exit can outrank a stronger new build (§9 line 248)."""
    manual_quantity = (isinstance(row.get("action_proposal"), dict)
                       and row["action_proposal"].get("reason")
                       == "mandatory_holding_exit_manual_share_confirmation")
    theme = row.get("theme_context") if isinstance(row.get("theme_context"), dict) else {}
    return ("final_action=%s observe_reason_type=%s | selection_rank=%s (多强) vs action_group=%s "
            "action_rank=%s (先干哪个, §9 survival-first); a must-act holding exit can outrank a stronger "
            "new 建仓 (§9 line 248). theme=%s source=%s lifecycle=%s macro=%s/%s; "
            "manual_share_confirmation_required=%s" % (
                row.get("final_action"), row.get("observe_reason_type"), row.get("selection_rank"),
                row.get("action_group"), row.get("action_rank"), theme.get("theme_id"),
                theme.get("theme_source"), theme.get("theme_lifecycle_state"), row.get("macro_cluster"),
                row.get("macro_cluster_warning_level"), manual_quantity))


def _finite_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pos_int(x):
    return isinstance(x, int) and not isinstance(x, bool) and x >= 1


def _validate_ranked_row(row, *, as_of, require_result_effects):
    """Fail-closed VALUE validation of one 4d-ii-j ranked row BEFORE its §10 field_records are emitted. The
    machine record is the OFFICIAL pre-render clean gate, so malformed carried evidence must NOT silently
    become a clean (shadow / landed) field_record — the recurring batch4 consumer-validation class. Reuses the
    single-source 4d-ii-a evidence validator for the veto / price / event / row-context contract, then
    validates the later-stage fields THIS assembler lands. Raises WeekendMachineRecordError on any malformed
    PRESENT evidence (a legitimately ABSENT field for a row class is left to its emitter's shadow/skip)."""
    # 4d-ii-a evidence (veto dict + known veto_tier + veto/row-context consistency + context-incompatible veto;
    # price dict + bool executable + trace dict; holding breached bool; event_data_gap status) — single source.
    try:
        validate_evidence_row(row)
    except WeekendDecisionError as e:
        raise WeekendMachineRecordError(f"4d-ii-a 证据非法（machine-record 边界 fail-closed）: {e}")

    if require_result_effects:
        try:
            validate_result_effects(row, as_of=as_of)
        except ResultEffectsError as exc:
            raise WeekendMachineRecordError(f"第二刀 result_effects 未闭环: {exc}") from exc

    theme = row.get("theme_context")
    if (require_result_effects and row.get("row_source") in {"top15_candidate", "holding_in_top15"}
            and not isinstance(theme, dict)):
        raise WeekendMachineRecordError("Top15 row 缺 Cut3 source-bound theme_context")
    if theme is not None:
        evidence = theme.get("evidence_ref") if isinstance(theme, dict) else None
        if not (isinstance(theme, dict) and theme.get("theme_source") in THEME_SOURCES
                and theme.get("theme_lifecycle_state") in THEME_STATES
                and isinstance(theme.get("theme_id"), str) and theme["theme_id"].strip()
                and isinstance(theme.get("macro_cluster"), str) and theme["macro_cluster"].strip()
                and isinstance(evidence, dict) and set(evidence) == {"kind", "value", "as_of"}
                and evidence.get("kind") in {"provider row", "SEC filing", "source_id"}
                and isinstance(evidence.get("value"), str) and evidence["value"].strip()
                and evidence.get("as_of") == as_of):
            raise WeekendMachineRecordError("theme_context 身份/source/lifecycle/macro/evidence 非法")
        if row.get("macro_cluster") != theme["macro_cluster"]:
            raise WeekendMachineRecordError("macro_cluster 未从 theme_context 单源投影")
        warning = row.get("macro_cluster_warning_level")
        frac = row.get("macro_cluster_exposure_frac")
        adjustment = row.get("macro_cluster_size_adjustment")
        if warning not in WARNING_LEVELS:
            raise WeekendMachineRecordError("macro_cluster_warning_level 非法")
        if frac is not None and not (_finite_number(frac) and 0.0 <= float(frac) <= 1.0):
            raise WeekendMachineRecordError("macro_cluster_exposure_frac 须为 None 或 [0,1] 有限数")
        if not (isinstance(adjustment, int) and not isinstance(adjustment, bool) and adjustment >= 0):
            raise WeekendMachineRecordError("macro_cluster_size_adjustment 须为非负 int 股数差")

    facts = row.get("source_result_facts")
    if facts is not None and (not isinstance(facts, dict) or facts.get("as_of") != as_of):
        raise WeekendMachineRecordError("Cut4 source_result_facts is not bound to this decision date")

    final_action = row["final_action"]
    # ranked-result fields on EVERY 4d-ii-j row: action_group must be the real §9 engine group for this action
    # (a forged group / group-action mismatch fails), action_rank a positive int, selection_rank None or positive int.
    if row.get("action_group") != _expected_action_group(final_action):
        raise WeekendMachineRecordError(
            f"action_group {row.get('action_group')!r} != §9 engine group for final_action {final_action!r}")
    if not _pos_int(row.get("action_rank")):
        raise WeekendMachineRecordError(f"action_rank 须为正 int（已排名 4d-ii-j 行）: {row.get('action_rank')!r}")
    sr = row.get("selection_rank")
    if sr is not None and not _pos_int(sr):
        raise WeekendMachineRecordError(f"selection_rank 须为 None 或正 int: {sr!r}")

    # §9 action↔price 一一对应 (R-USSHORT-BATCH4-ACTION-PRICE-MAPPING-GAP): an OFFICIAL action that names a price
    # (建仓/加仓 entry / 减仓 TP1 / 清仓-止损 stop / 清仓-止盈 TP2 / 清仓-事件 event-ref) must carry that price in
    # price.action_fields BEFORE the §10 field_records are emitted (machine-clean gate) — keyed by ACTION, not
    # row class / executable, so a 清仓-事件 with a null event reference price can never become a clean official
    # row. Single source: action_price_error (decision §9). price is a dict here (validate_evidence_row proved it).
    price_err = action_price_error(final_action, row["price"].get("action_fields"))
    if price_err:
        raise WeekendMachineRecordError(price_err)
    quantity_err = action_quantity_error(final_action, row)
    if quantity_err:
        raise WeekendMachineRecordError(quantity_err)

    # a 建仓 is an actionable build: it must carry an EXECUTABLE price plan and a real sized position, else
    # price could be shadowed / sizing+regime fabricated onto position_size from a non-executable / unsized build.
    if final_action == _BUILD:
        if row["price"].get("executable") is not True:   # validate_evidence_row proved price is a dict w/ bool executable
            raise WeekendMachineRecordError("建仓 行 price 须 executable=True（不可执行的建仓不一致）")
        sizing = row.get("sizing")
        if not (isinstance(sizing, dict) and sizing.get("status") == "sized"):
            raise WeekendMachineRecordError(f"建仓 行须为真 sized build（sizing.status=='sized'）: {sizing!r}")

    # selection score — when present the assembler LANDS it on action_rank, so it must be a finite numeric core_score.
    score = row.get("score")
    if score is not None and not (isinstance(score, dict) and _finite_number(score.get("core_score"))):
        raise WeekendMachineRecordError(f"score 须为含有限 core_score 的 dict: {score!r}")
    # §4.2 risk_downgrade — a scored candidate MUST carry the typed soft-penalty input (it is subtracted in
    # core_score and lands a §10 field_record); the official gate re-validates it so a stripped/forged penalty
    # can never reach the machine layer (R-USSHORT-BATCH4-RISK-DOWNGRADE-WIRING-GAP).
    if isinstance(score, dict):
        try:
            validate_risk_downgrade_input(row.get("risk_downgrade"))
        except ValueError as e:
            raise WeekendMachineRecordError(f"评分行 risk_downgrade 非法: {e}")

    # sizing — when a sized payload rides on ANY row (incl. a downgraded 观察 carrying its computed size, which
    # the assembler lands on position_size) the model share count must be a valid positive int (not bool).
    sizing = row.get("sizing")
    if isinstance(sizing, dict) and sizing.get("status") == "sized" and not _pos_int(sizing.get("desired_model_shares")):
        raise WeekendMachineRecordError(f"sized sizing 须有正 int desired_model_shares: {sizing!r}")

    # theme_probe — when present the assembler LANDS theme_lifecycle_state / theme_opportunity_state on
    # position_size, so it must be a REAL §8 forced-min probe (not just a row that carries a theme_probe key).
    # Validate the SAME contract the cost-floor stage consumes: (a) trace VALUES (exact keys, risk_tag == the
    # governance tag, entry_mode_constraint a legal constraint) AND (b) the forced-min sizing (status sized,
    # desired_model_shares == single-source MIN_EXECUTABLE_SHARES, reason == theme_probe_forced_min, a valid
    # pre_probe_risk_shares trace) — else a non-min / risk-sized "probe" could land theme states on position_size.
    tp = row.get("theme_probe")
    if tp is not None:
        if not (isinstance(tp, dict) and set(tp) == _PROBE_TRACE_KEYS
                and tp.get("risk_tag") == _PROBE_RISK_TAG
                and tp.get("entry_mode_constraint") in _ENTRY_MODE_CONSTRAINTS):
            raise WeekendMachineRecordError(
                f"theme_probe trace 非法（键/risk_tag={_PROBE_RISK_TAG!r}/entry_mode_constraint∈{list(_ENTRY_MODE_CONSTRAINTS)}）: {tp!r}")
        psz = row.get("sizing")
        pre = psz.get("pre_probe_risk_shares") if isinstance(psz, dict) else None
        if not (isinstance(psz, dict) and psz.get("status") == "sized"
                and _pos_int(psz.get("desired_model_shares")) and psz["desired_model_shares"] == MIN_EXECUTABLE_SHARES
                and psz.get("reason") == _PROBE_SIZING_REASON and _pos_int(pre) and pre >= MIN_EXECUTABLE_SHARES):
            raise WeekendMachineRecordError(
                f"theme_probe sizing 须为 §8 forced-min（status='sized', desired_model_shares={MIN_EXECUTABLE_SHARES}, "
                f"reason={_PROBE_SIZING_REASON!r}, pre_probe_risk_shares>=min）: {psz!r}")

    # §4.3 overextension (cut 2d) — when a row carries the tier result, the assembler LANDS an
    # overextension_state §10 field_record + the flatten lifts the §11.3 column, so a malformed PRESENT record
    # must fail closed here (缺数据≠安全); a legitimately ABSENT overextension is left to the emitter's skip.
    ox = row.get("overextension")
    if ox is not None:
        try:
            validate_overextension_result(ox)
        except ValueError as exc:
            raise WeekendMachineRecordError(f"overextension 违反 §4.3 状态/效果闭集契约: {ox!r}") from exc


def assemble_machine_record(ranked_result, *, as_of, run_origin=OFFLINE_TEST_RUN_ORIGIN,
                            research_live_capability=None, require_result_effects=False):
    """4d-ii-k §10 machine-record assembly. Assembles the 4d-ii-j `apply_action_rank` result into the §10
    machine record and validates it with `validate_official_machine_record`, failing closed if it is not §10-clean.

    ranked_result = the `apply_action_rank` output {regime, rows, weekly_build_limit, build_count}; each row
        carries the additive 4d-ii-a..j fields (veto / price / score / sizing / theme_probe / forward_event /
        final_action / observe_reason_type / selection_rank / action_group / action_rank / row_source).
    as_of = the run's canonical decision_date (the §10 record PIT anchor); the run-level real-YYYYMMDD gate is
        enforced by `validate_official_machine_record` (single date source — this module adds no second date parser).
    run_origin = the immutable batch4 honesty-provenance fact (offline_test / caller_supplied_fixture /
        not_authorized) stamped on the record so a synthetic fixture run can never pass as operational output
        (R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP); validated single-source here.

    Returns the §10 machine record {schema_name, schema_version, as_of, run_origin (offline honesty fact), rows: [{...row (rich machine layer),
    ticker canonical UPPERCASE, market_risk_regime (carried for traceback), decision_trace, field_records}]}.
    Raises WeekendMachineRecordError on a malformed result / row, an invalid market_risk_regime, an unknown
    final_action, an observe_reason_type inconsistent with final_action, a non-canonical / duplicate ticker, a
    theme_probe that is not a §8 forced-min build, or an assembled record the §10 validator does not mark clean."""
    require_research_live_capability(
        run_origin, research_live_capability, decision_date=as_of,
    )   # consumer-layer honesty gate (Required A) — first
    if not (isinstance(ranked_result, dict) and isinstance(ranked_result.get("regime"), dict)
            and isinstance(ranked_result.get("rows"), list)):
        raise WeekendMachineRecordError("ranked_result 须为含 regime(dict) + rows(list) 的 4d-ii-j 输出")

    # §7 run-level regime VALUE (not just shape): the assembler lands market_risk_regime on position_size for
    # every sized row, so the raw value must be a valid regime (single-source vocab) AND be carried into each
    # machine-record row — else the landed field has no traceback evidence of which regime cap drove the size.
    market_risk_regime = ranked_result["regime"].get("market_risk_regime")
    if market_risk_regime not in _MARKET_RISK_REGIMES:
        raise WeekendMachineRecordError(
            f"regime.market_risk_regime 非法（须 ∈ {list(_MARKET_RISK_REGIMES)}）: {market_risk_regime!r}")

    rows_out, seen = [], set()
    for row in ranked_result["rows"]:
        if not (isinstance(row, dict) and isinstance(row.get("final_action"), str)):
            raise WeekendMachineRecordError(f"row 形状非法（须为 4d-ii-j 输出行）: {row!r}")
        err = action_reason_error(row["final_action"], row.get("observe_reason_type"))   # §9 single-source
        if err:
            raise WeekendMachineRecordError(err)
        ct = canonical_us_ticker(row.get("ticker"))
        if ct is None:
            raise WeekendMachineRecordError(f"row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
        if ct in seen:
            raise WeekendMachineRecordError(f"rows 含规范化后重复 ticker（一股一行）: {ct!r}")
        seen.add(ct)
        _validate_ranked_row(row, as_of=as_of, require_result_effects=require_result_effects)
        rows_out.append({**row, "ticker": ct, "market_risk_regime": market_risk_regime,
                         "decision_trace": _decision_trace(row), "field_records": _field_records(row)})
    # §10 field-registry 反向完整性 (R-USSHORT-BATCH4-MACHINE-REGISTRY-COMPLETENESS-GAP) is enforced by the OFFICIAL
    # gate `validate_official_machine_record` (no_dangling) — its UNCONDITIONAL manifest floor cannot be bypassed by
    # stripping evidence. The SAME gate is re-run by every official consumer (flatten / private), so a record whose
    # registry was stripped AFTER assembly cannot pass into official §11.3 output either.

    record = {"schema_name": _SCHEMA_NAME, "schema_version": _SCHEMA_VERSION, "as_of": as_of,
              "run_origin": validate_run_origin(run_origin), "rows": rows_out}

    result = validate_official_machine_record(record)
    if not result["clean"]:
        raise WeekendMachineRecordError(
            "assembled machine record is not §10-clean (a producer never emits a not-clean record); "
            f"first violations: {result['violations'][:5]!r}")
    return record
