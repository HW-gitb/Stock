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
    "theme_lifecycle_state": {"owner_module": "engine.us_short_theme_probe", "data_source": "row.theme_probe (injected; live=batch5)",
                              "field_class": "theme_lifecycle_state", "lifecycle_item_id": 30},
    "theme_opportunity_state": {"owner_module": "engine.us_short_theme_probe", "data_source": "row.theme_probe (injected; live=batch5)",
                                "field_class": "theme_opportunity_state", "lifecycle_item_id": 27},
    "forward_event": {"owner_module": "engine.us_short_forward_events", "data_source": "row.forward_event (injected; live=batch5)",
                      "field_class": "trigger", "lifecycle_item_id": 15},
    "overextension_state": {"owner_module": "engine.us_short_overextension",
                            "data_source": "row.overextension (injected; live=batch5)",
                            "field_class": "overextension", "lifecycle_item_id": 36},
}


class WeekendMachineRecordError(Exception):
    """The injected ranked result / row is malformed, or the assembled machine record is not §10-clean
    (fail-closed before the record is treated as an official output)."""


def _fr(field_id, *, op, terminal, disposition, impact_target):
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
        "evidence_ref_kind": None,
        "lifecycle_item_id": spec["lifecycle_item_id"],
        "field_class": spec["field_class"],
        "disposition": disposition,
        "impact_target": impact_target,
        "claim_type": None,
        "evidence_ref": None,
    }


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

    # theme_probe rows (§8 強赛道试探) — the promoted strong-theme build was forced to a min position; both the
    # theme_lifecycle_state and the theme_opportunity_state landed on position_size.
    if isinstance(row.get("theme_probe"), dict):
        frs.append(_fr("theme_lifecycle_state", op="降仓", terminal="model_position_size_shares", disposition=_LANDED, impact_target="position_size"))
        frs.append(_fr("theme_opportunity_state", op="降仓", terminal="model_position_size_shares", disposition=_LANDED, impact_target="position_size"))

    # forward known-date event (§8.1) — v1 display-only (sizing/risk/display, never selection/veto); recorded
    # as a clean shadow until the live evidence_ref traceback (provider row / SEC filing) is wired in batch5.
    if isinstance(row.get("forward_event"), dict):
        frs.append(_fr("forward_event", op="仅标签", terminal=_SHADOW_TERMINAL, disposition=_SHADOW, impact_target=None))

    # §4.3 overextension_state (cut 2d) — the §4.3 tier computed at the scoring stage; its EXECUTION effect
    # (warning→forced pullback) is already registered via the `price` field_record (the plan is pullback), so
    # here the STATE lands on its own §11.3 overextension_state column as an advisory tag (仅标签). Emitted only
    # when the row carries a valid tier result (a malformed one was rejected by `_validate_ranked_row`).
    ox = row.get("overextension")
    if isinstance(ox, dict):
        frs.append(_fr("overextension_state", op="仅标签", terminal="overextension_state",
                       disposition=_LANDED, impact_target=None))

    return frs


def _decision_trace(row):
    """A non-empty per-row §10 decision_trace — where the deliberate selection_rank (多强) vs action_rank
    (先干哪个) divergence is explained: a must-act holding exit can outrank a stronger new build (§9 line 248)."""
    return ("final_action=%s observe_reason_type=%s | selection_rank=%s (多强) vs action_group=%s "
            "action_rank=%s (先干哪个, §9 survival-first); a must-act holding exit can outrank a stronger "
            "new 建仓 (§9 line 248)." % (
                row.get("final_action"), row.get("observe_reason_type"), row.get("selection_rank"),
                row.get("action_group"), row.get("action_rank")))


def _finite_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pos_int(x):
    return isinstance(x, int) and not isinstance(x, bool) and x >= 1


def _validate_ranked_row(row):
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
                            research_live_capability=None):
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
        _validate_ranked_row(row)   # VALUE-validate carried evidence before §10 field_records are emitted
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
