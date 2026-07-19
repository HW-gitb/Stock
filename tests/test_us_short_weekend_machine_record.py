# -*- coding: utf-8 -*-
"""Tests for US-short weekend §10 machine-record assembly (batch4 slice 4d-ii-k).

Covers: faithful per-row field_record assembly (each CORE computed field lands or is a clean shadow with the
right operation_impact / impact_target / disposition — a behavioral assertion, not mere presence, for the
high-drift theme_lifecycle_state etc., §18.1 #9); a fired hard veto reaches a kill/exit final_action while a
soft / clean tier is a shadow; selection-vs-action_rank explained in a non-empty decision_trace; the assembled
record is §10-clean and the rich machine layer rides along; canonical UPPERCASE ticker emission; and
fail-closed on a malformed result / row, a bad §9 action/reason pair, a non-canonical / duplicate ticker, a
bad as_of, and an INCONSISTENT input the §10 validator rejects (hard veto tier but a non-exit final_action).
Pure/offline; no provider/live; no A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_cost_floor as cf  # noqa: E402
import engine.us_short_weekend_machine_record as mr  # noqa: E402
import engine.us_short_theme_probe as tp_engine  # noqa: E402
from engine.us_short_action_rank import ACTION_RANK_SKELETON, action_group as _ag  # noqa: E402
from engine.us_short_hard_veto import VETO_TIERS  # noqa: E402
from engine.us_short_no_dangling_validator import (  # noqa: E402
    official_expected_field_ids, validate_machine_record, validate_official_machine_record)
from engine.us_short_position_sizing import MIN_EXECUTABLE_SHARES  # noqa: E402
from engine.us_short_regime import REGIMES  # noqa: E402
from engine.us_short_result_effects import apply_result_effects  # noqa: E402

_AS_OF = "20260112"


def _safe_group(final_action):
    try:
        return _ag(final_action)
    except ValueError:
        return 2   # unknown action (a bad-action fixture) — assemble rejects it at the §9 check, not here


def _row(ticker="AAA", final_action="建仓", observe_reason_type=None, row_source="top15_candidate",
         veto_tier="none", executable=True, has_score=True, sized=True, theme_probe=False,
         forward_event=False, selection_rank=1, action_rank=1, action_group=None):
    ctx = "holding" if "holding" in row_source else "candidate"
    row = {
        "ticker": ticker, "row_source": row_source, "final_action": final_action,
        "observe_reason_type": observe_reason_type, "row_context": ctx, "selection_rank": selection_rank,
        "action_rank": action_rank, "action_group": _safe_group(final_action) if action_group is None else action_group,
        "veto": {"veto_tier": veto_tier, "row_context": ctx},
        # holding executable rows carry a bool breached (consumed by the §6 evidence contract); candidates don't.
        # action_fields carry the §9 action↔price cells a real price engine emits (so the action-keyed price
        # contract `action_price_error` is satisfied — entry/stop/TP1/TP2/event-ref all positive).
        "price": {"executable": executable, "trace": {"breached": False} if ctx == "holding" else {},
                  "action_fields": {"limit_order_price": 10.0, "stop_clear_price": 9.0,
                                    "take_profit_reduce_price": 12.0, "take_profit_exit_price": 14.0,
                                    "event_clear_reference_price": 8.0}},
    }
    if has_score:
        row["score"] = {"core_score": 50.0}
        # §4.2 risk_downgrade typed input (zero-penalty default; a real penalty is exercised in dedicated tests)
        row["risk_downgrade"] = {"points": 0.0, "hard_veto": False,
                                 "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0}}
    if sized:
        row["sizing"] = {"status": "sized", "desired_model_shares": 10}
    if theme_probe:
        row["theme_probe"] = {"risk_tag": tp_engine.RISK_TAG, "entry_mode_constraint": "pullback_only"}
        # a real §8 promoted probe is a forced-min build (mirror 4d-ii-g/cost-floor sizing contract)
        row["sizing"] = {"status": "sized", "desired_model_shares": MIN_EXECUTABLE_SHARES,
                         "reason": "theme_probe_forced_min", "pre_probe_risk_shares": 50}
    if forward_event:
        row["forward_event"] = {"event_type": "earnings", "days_to_event": 5}
    return row


def _ranked(rows, regime="进攻"):
    return {"regime": {"market_risk_regime": regime}, "rows": rows, "weekly_build_limit": 3, "build_count": 1}


def _second_cut_effect_row(*, forward_event=None, event_data_gap=None):
    """A normal finalized build carrying real second-cut effects and evidence refs."""
    source_row = {"ticker": "AAA", "final_action": "建仓", "observe_reason_type": None}
    if forward_event is not None:
        source_row["forward_event"] = forward_event
    if event_data_gap is not None:
        source_row["event_data_gap"] = event_data_gap
    effected = apply_result_effects(
        {"regime": {"market_risk_regime": "进攻", "position_cap": 1.0}, "rows": [source_row]},
        portfolio_guard_result={"state": "normal", "evidence_ref": {
            "kind": "source_id", "value": "test:portfolio-guard", "as_of": _AS_OF}},
        cooldown_by_ticker={"AAA": {"status": "none", "cooldown_until": None,
                                     "reentry_allowed_reason": None, "evidence_ref": {
                                         "kind": "source_id", "value": "test:cooldown", "as_of": _AS_OF}}},
        as_of=_AS_OF,
    )["rows"][0]
    return {**_row(), **effected,
            "theme_context": {"theme_id": "industry:aaa", "theme_source": "industry_heat_v1",
                              "theme_lifecycle_state": "confirmed_active", "macro_cluster": "ai_complex",
                              "evidence_ref": {"kind": "source_id", "value": "test:theme:AAA", "as_of": _AS_OF}},
            "macro_cluster": "ai_complex", "macro_cluster_exposure_frac": 0.1,
            "macro_cluster_warning_level": "none", "macro_cluster_size_adjustment": 0}


def _fr_by_id(record, field_id, ri=0):
    return next(f for f in record["rows"][ri]["field_records"] if f["field_id"] == field_id)


def _ids(record, ri=0):
    return {f["field_id"] for f in record["rows"][ri]["field_records"]}


class HappyAssembly(unittest.TestCase):
    def test_clean_build_record(self):
        rec = mr.assemble_machine_record(_ranked([_row()]), as_of=_AS_OF)
        self.assertEqual(rec["schema_name"], "us_short_machine_record_contract")
        self.assertEqual(rec["as_of"], _AS_OF)
        self.assertTrue(validate_machine_record(rec)["clean"])

    def test_rich_machine_layer_rides_along(self):
        # §11.1: the machine layer carries 全字段 + 原始分数 — the raw evidence rides along on each row.
        rec = mr.assemble_machine_record(_ranked([_row()]), as_of=_AS_OF)
        r0 = rec["rows"][0]
        self.assertEqual(r0["sizing"], {"status": "sized", "desired_model_shares": 10})
        self.assertEqual(r0["score"], {"core_score": 50.0})
        self.assertEqual(r0["action_rank"], 1)

    def test_every_row_has_nonempty_decision_trace(self):
        rec = mr.assemble_machine_record(_ranked([_row(), _row(ticker="BBB", selection_rank=2)]), as_of=_AS_OF)
        for r in rec["rows"]:
            self.assertTrue(r["decision_trace"].strip())

    def test_realistic_carry_through_assembles_clean(self):
        # a real 4d-ii-j row rides along the full machine layer (cash fields / action_group / sub_mode /
        # row_context). None of these top-level keys is a design-locked action_table enum column, so the rich
        # carry-through must not trip the §10 validator's frozen-vocab check.
        row = _row()
        row.update({"cash_allocation_status": "allocated", "cash_allocation_rank": 1,
                    "allocated_model_shares": 10, "remaining_cash_after": 500.0,
                    "sub_mode_resolved": "pullback", "sub_mode_downgraded": False})
        rec = mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF)
        self.assertTrue(validate_machine_record(rec)["clean"])
        self.assertEqual(rec["rows"][0]["cash_allocation_status"], "allocated")


class FieldRecordLandings(unittest.TestCase):
    def test_build_candidate_landings(self):
        rec = mr.assemble_machine_record(_ranked([_row()]), as_of=_AS_OF)
        # selection → action_rank, price → price, sizing & regime → position_size, hard_veto clean → shadow
        self.assertEqual(_fr_by_id(rec, "core_score")["impact_target"], "action_rank")
        self.assertEqual(_fr_by_id(rec, "core_score")["disposition"], "landed")
        price = _fr_by_id(rec, "price")
        self.assertEqual((price["impact_target"], price["disposition"]), ("price", "landed"))
        for fid in ("sizing", "market_risk_regime"):
            self.assertEqual(_fr_by_id(rec, fid)["impact_target"], "position_size")
            self.assertEqual(_fr_by_id(rec, fid)["operation_impact"], "降仓")
        hv = _fr_by_id(rec, "hard_veto")
        self.assertEqual((hv["disposition"], hv["operation_impact"], hv["impact_target"]),
                         ("shadow_record", "仅标签", None))

    def test_fired_hard_veto_lands_on_kill_exit(self):
        # candidate entry_hard_veto → 否决/避开 (kill); the hard_veto field is 硬否决 landing on final_action
        rec = mr.assemble_machine_record(
            _ranked([_row(final_action="否决/避开", veto_tier="entry_hard_veto", sized=False)]), as_of=_AS_OF)
        hv = _fr_by_id(rec, "hard_veto")
        self.assertEqual((hv["operation_impact"], hv["disposition"], hv["impact_target"]),
                         ("硬否决", "landed", "final_action"))
        self.assertTrue(validate_machine_record(rec)["clean"])

    def test_holding_position_hard_veto_clears_event(self):
        rec = mr.assemble_machine_record(
            _ranked([_row(row_source="holding_pass2_only", final_action="清仓-事件",
                          veto_tier="position_hard_veto", has_score=False, sized=False)]), as_of=_AS_OF)
        self.assertEqual(_fr_by_id(rec, "hard_veto")["operation_impact"], "硬否决")
        self.assertNotIn("core_score", _ids(rec))  # holdings carry no selection score
        self.assertTrue(validate_machine_record(rec)["clean"])

    def test_event_clear_with_null_event_price_rejected_at_assembly(self):
        # R-USSHORT-BATCH4-ACTION-PRICE-MAPPING-GAP: a 清仓-事件 holding whose event reference price is null is
        # rejected at the machine-clean gate (§9 action↔price) — an event-clear can never be official without
        # its 事件清仓参考价, even though the rest of the holding evidence is valid.
        bad = _row(row_source="holding_pass2_only", final_action="清仓-事件",
                   veto_tier="position_hard_veto", has_score=False, sized=False)
        bad["price"]["action_fields"] = {k: v for k, v in bad["price"]["action_fields"].items()
                                         if k != "event_clear_reference_price"}
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record(_ranked([bad]), as_of=_AS_OF)

    def test_soft_veto_tier_is_shadow_not_hard(self):
        # a strong_downgrade tier is NOT acted on in v1 → recorded as a clean shadow, never 硬否决
        rec = mr.assemble_machine_record(_ranked([_row(veto_tier="strong_downgrade")]), as_of=_AS_OF)
        hv = _fr_by_id(rec, "hard_veto")
        self.assertEqual((hv["operation_impact"], hv["disposition"]), ("仅标签", "shadow_record"))
        self.assertTrue(validate_machine_record(rec)["clean"])

    def test_nonexecutable_price_is_shadow(self):
        rec = mr.assemble_machine_record(
            _ranked([_row(final_action="观察", observe_reason_type="price_not_executable",
                          executable=False, sized=False)]), as_of=_AS_OF)
        price = _fr_by_id(rec, "price")
        self.assertEqual((price["disposition"], price["impact_target"]), ("shadow_record", None))
        self.assertTrue(validate_machine_record(rec)["clean"])

    def test_unsized_row_regime_is_shadow_no_sizing(self):
        rec = mr.assemble_machine_record(
            _ranked([_row(final_action="观察", observe_reason_type="capacity_or_budget_deferred",
                          selection_rank=4, sized=False)]), as_of=_AS_OF)
        self.assertNotIn("sizing", _ids(rec))
        self.assertEqual(_fr_by_id(rec, "market_risk_regime")["disposition"], "shadow_record")
        self.assertTrue(validate_machine_record(rec)["clean"])

    def test_theme_probe_states_land_on_position(self):
        rec = mr.assemble_machine_record(_ranked([_row(theme_probe=True)]), as_of=_AS_OF)
        for fid in ("theme_lifecycle_state", "theme_opportunity_state"):
            fr = _fr_by_id(rec, fid)
            self.assertEqual((fr["disposition"], fr["impact_target"], fr["operation_impact"]),
                             ("landed", "position_size", "降仓"))
        self.assertTrue(validate_machine_record(rec)["clean"])

    def test_no_theme_probe_no_theme_fields(self):
        rec = mr.assemble_machine_record(_ranked([_row()]), as_of=_AS_OF)
        self.assertNotIn("theme_lifecycle_state", _ids(rec))
        self.assertNotIn("theme_opportunity_state", _ids(rec))

    def test_forward_event_is_display_shadow_no_claim(self):
        rec = mr.assemble_machine_record(_ranked([_row(forward_event=True)]), as_of=_AS_OF)
        fe = _fr_by_id(rec, "forward_event")
        self.assertEqual((fe["disposition"], fe["claim_type"], fe["evidence_ref"]),
                         ("shadow_record", None, None))  # v1: no fabricated offline evidence_ref
        self.assertTrue(validate_machine_record(rec)["clean"])

    def test_formal_forward_reduce_caution_uses_legal_reduce_position_impact(self):
        row = _second_cut_effect_row(forward_event={
            "event_type": "earnings", "days_to_event": 5.0, "in_window": True,
            "direction": "reduce_caution", "evidence_ref": {
                "kind": "SEC filing", "value": "sec:AAA:10-Q", "as_of": _AS_OF},
        })
        rec = mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF, require_result_effects=True)
        field = _fr_by_id(rec, "forward_event")
        self.assertEqual((field["operation_impact"], field["impact_target"], field["disposition"]),
                         ("降仓", "position_size", "landed"))

    def test_formal_event_gap_reduce_caution_uses_legal_reduce_position_impact(self):
        row = _second_cut_effect_row(event_data_gap={"status": "reduce_caution"})
        rec = mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF, require_result_effects=True)
        field = _fr_by_id(rec, "event_data_gap")
        self.assertEqual((field["operation_impact"], field["impact_target"], field["disposition"]),
                         ("降仓", "position_size", "landed"))

    def test_lifecycle_item_ids_resolve(self):
        rec = mr.assemble_machine_record(_ranked([_row(theme_probe=True, forward_event=True)]), as_of=_AS_OF)
        for f in rec["rows"][0]["field_records"]:
            self.assertIn(f["lifecycle_item_id"], range(1, 40))  # §13.1 registry 1..39


class HardVetoTierTriangulation(unittest.TestCase):
    def test_hard_tiers_are_engine_top_two(self):
        # the two HARD tiers must be exactly the engine ladder's top two (no silent drift)
        self.assertEqual(mr._HARD_VETO_TIERS, frozenset(VETO_TIERS[:2]))
        self.assertEqual(VETO_TIERS[:2], ("entry_hard_veto", "position_hard_veto"))


class CanonicalIdentity(unittest.TestCase):
    def test_lowercase_ticker_emitted_uppercase(self):
        rec = mr.assemble_machine_record(_ranked([_row(ticker="aaa")]), as_of=_AS_OF)
        self.assertEqual(rec["rows"][0]["ticker"], "AAA")

    def test_duplicate_canonical_ticker_rejected(self):
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record(_ranked([_row(ticker="AAA"), _row(ticker="aaa", selection_rank=2)]),
                                       as_of=_AS_OF)

    def test_non_us_ticker_rejected(self):
        for bad in ("600519", "", "  ", None):
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(_ranked([_row(ticker=bad)]), as_of=_AS_OF)


class ConsumerValidationFailClosed(unittest.TestCase):
    def test_bad_action_reason_pair_rejected(self):
        for fa, rr in (("观察", None), ("观察", "BANANA"), ("建仓", "data_restricted"), ("BANANA", None)):
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(_ranked([_row(final_action=fa, observe_reason_type=rr)]), as_of=_AS_OF)

    def test_malformed_result_rejected(self):
        for bad in (None, {}, {"regime": {}}, {"rows": []}, {"regime": [], "rows": []},
                    {"regime": {}, "rows": "x"}):
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(bad, as_of=_AS_OF)

    def test_malformed_row_rejected(self):
        for bad in ("x", {"ticker": "AAA"}, {"final_action": 1, "ticker": "AAA"}):
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(_ranked([bad]), as_of=_AS_OF)

    def test_bad_as_of_rejected(self):
        for bad in ("20260231", "2026", "2026-01-12", None, 20260112):
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(_ranked([_row()]), as_of=bad)

    def test_inconsistent_hard_veto_not_clean_raises(self):
        # entry_hard_veto evidence but final_action 建仓 (an inconsistent input the §6 chain never produces):
        # the assembler faithfully emits 硬否决 → final_action, and the §10 validator rejects it (hard veto
        # must reach a kill/exit) → fail closed.
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record(_ranked([_row(final_action="建仓", veto_tier="entry_hard_veto")]),
                                       as_of=_AS_OF)


class MalformedEvidenceFailClosed(unittest.TestCase):
    """R-USSHORT-BATCH4-MACHINE-RECORD-CONSUMER-VALIDATION-GAP: malformed carried 4d-ii-j evidence must fail
    closed at the official §10 boundary, never become a clean (shadow / landed) field_record. One adversarial
    case per Codex-reproduced probe + the cross-field 建仓-needs-executable check."""

    def _assert_rejects(self, mutate):
        row = _row()
        mutate(row)
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF)

    def test_missing_veto_rejected(self):
        self._assert_rejects(lambda r: r.pop("veto"))

    def test_unknown_veto_tier_rejected(self):
        self._assert_rejects(lambda r: r["veto"].update(veto_tier="BANANA"))

    def test_build_missing_price_rejected(self):
        self._assert_rejects(lambda r: r.pop("price"))

    def test_build_nonexecutable_price_rejected(self):
        # a 建仓 with executable=False is inconsistent (the §6 chain only builds on an executable plan)
        self._assert_rejects(lambda r: r["price"].update(executable=False))

    def test_empty_score_dict_rejected(self):
        self._assert_rejects(lambda r: r.update(score={}))

    def test_non_numeric_core_score_rejected(self):
        self._assert_rejects(lambda r: r.update(score={"core_score": "bad"}))

    def test_missing_action_rank_rejected(self):
        self._assert_rejects(lambda r: r.pop("action_rank"))

    def test_bad_action_group_rejected(self):
        self._assert_rejects(lambda r: r.update(action_group=99))

    def test_sized_sizing_missing_shares_rejected(self):
        self._assert_rejects(lambda r: r.update(sizing={"status": "sized"}))

    def test_bool_shares_rejected(self):
        self._assert_rejects(lambda r: r.update(sizing={"status": "sized", "desired_model_shares": True}))

    def test_bad_selection_rank_rejected(self):
        self._assert_rejects(lambda r: r.update(selection_rank=0))

    def test_wrong_theme_probe_trace_rejected(self):
        for bad in ({"risk_tag": "WRONG"},                                          # missing key + wrong value
                    {"risk_tag": "WRONG", "entry_mode_constraint": "none"},         # wrong risk_tag value
                    {"risk_tag": tp_engine.RISK_TAG, "entry_mode_constraint": "BANANA"}):  # illegal constraint
            row = _row(theme_probe=True)
            row["theme_probe"] = bad
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF)

    def test_valid_forced_min_theme_probe_passes(self):  # positive control
        for mode in ("none", "pullback_only", "breakout_exception_allowed"):
            row = _row(theme_probe=True)
            row["theme_probe"]["entry_mode_constraint"] = mode
            self.assertTrue(validate_machine_record(mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF))["clean"])

    def test_valid_nonexecutable_observe_passes(self):  # positive control: an observe legitimately non-executable
        rec = mr.assemble_machine_record(
            _ranked([_row(final_action="观察", observe_reason_type="price_not_executable",
                          executable=False, sized=False)]), as_of=_AS_OF)
        self.assertTrue(validate_machine_record(rec)["clean"])


class PositionTraceFailClosed(unittest.TestCase):
    """R-USSHORT-BATCH4-MACHINE-RECORD-POSITION-TRACE-VALIDATION-GAP: a theme_probe that lands theme states on
    position_size must be a real §8 forced-min build; market_risk_regime must be a validated value carried for
    traceback. One adversarial case per reproduced accept + positive controls."""

    def _reject_probe(self, mutate_sizing):
        row = _row(theme_probe=True)
        mutate_sizing(row["sizing"])
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF)

    def test_non_min_probe_shares_rejected(self):
        self._reject_probe(lambda s: s.update(desired_model_shares=500))   # 500 ≠ MIN_EXECUTABLE_SHARES

    def test_probe_missing_reason_rejected(self):
        self._reject_probe(lambda s: s.pop("reason"))

    def test_probe_bad_reason_rejected(self):
        self._reject_probe(lambda s: s.update(reason="WRONG"))

    def test_probe_missing_pre_probe_rejected(self):
        self._reject_probe(lambda s: s.pop("pre_probe_risk_shares"))

    def test_probe_bad_pre_probe_rejected(self):
        for bad in (True, 0, -1, "x"):
            row = _row(theme_probe=True)
            row["sizing"]["pre_probe_risk_shares"] = bad
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF)

    def test_probe_unsized_rejected(self):
        row = _row(theme_probe=True)
        row["sizing"] = {"status": "not_sized"}
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record(_ranked([row]), as_of=_AS_OF)

    def test_missing_regime_value_rejected(self):
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record({"regime": {}, "rows": [_row()]}, as_of=_AS_OF)

    def test_bad_regime_value_rejected(self):
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record({"regime": {"market_risk_regime": "BAD_REGIME"}, "rows": [_row()]}, as_of=_AS_OF)

    def test_valid_forced_min_probe_lands_theme_states(self):  # positive control
        rec = mr.assemble_machine_record(_ranked([_row(theme_probe=True)]), as_of=_AS_OF)
        self.assertTrue(validate_machine_record(rec)["clean"])
        self.assertEqual(_fr_by_id(rec, "theme_lifecycle_state")["impact_target"], "position_size")

    def test_valid_regime_value_carried(self):  # positive control: raw regime rides on each row for traceback
        rec = mr.assemble_machine_record(_ranked([_row()], regime="防御"), as_of=_AS_OF)
        self.assertEqual(rec["rows"][0]["market_risk_regime"], "防御")
        self.assertTrue(validate_machine_record(rec)["clean"])


class SingleSourceTriangulation(unittest.TestCase):
    def test_action_groups_single_source(self):
        self.assertEqual(mr._VALID_ACTION_GROUPS, frozenset(ACTION_RANK_SKELETON))

    def test_hard_veto_tiers_derived_from_engine(self):
        self.assertEqual(mr._HARD_VETO_TIERS, frozenset(VETO_TIERS[:2]))

    def test_probe_risk_tag_single_source(self):
        self.assertEqual(mr._PROBE_RISK_TAG, tp_engine.RISK_TAG)

    def test_min_shares_and_regime_vocab_single_source(self):
        self.assertEqual(mr.MIN_EXECUTABLE_SHARES, MIN_EXECUTABLE_SHARES)
        self.assertEqual(mr._MARKET_RISK_REGIMES, REGIMES)

    def test_probe_contract_reused_from_cost_floor(self):
        # the promoted-probe contract is REUSED from the cost-floor stage (single source, no third copy)
        self.assertIs(mr._PROBE_TRACE_KEYS, cf._PROBE_TRACE_KEYS)
        self.assertIs(mr._ENTRY_MODE_CONSTRAINTS, cf._ENTRY_MODE_CONSTRAINTS)
        self.assertEqual(mr._PROBE_SIZING_REASON, cf._PROBE_SIZING_REASON)

    def test_entry_mode_constraints_triangulated(self):
        # the reused entry-mode set is pinned to theme_probe.defensive_entry_constraint (cost-floor anti-drift)
        seen = {
            tp_engine.defensive_entry_constraint("进攻", "extreme"),                            # none
            tp_engine.defensive_entry_constraint("防御", "strong"),                             # pullback_only
            tp_engine.defensive_entry_constraint("防御", "extreme", no_gap_week=True, entry_in_band=True),  # breakout
        }
        self.assertEqual(seen, set(mr._ENTRY_MODE_CONSTRAINTS))


class RegistryReverseCompletenessTests(unittest.TestCase):
    """R-USSHORT-BATCH4-MACHINE-REGISTRY-COMPLETENESS-GAP: the assembler reconciles the EMITTED field_records
    against an independently-derived expected-field MANIFEST, so a computed §10 field that produced no record
    (silent disappearance) or a fabricated/unexpected record fails closed at the machine-clean gate."""

    # --- the OFFICIAL manifest: UNCONDITIONAL floor (strip-proof) + build-contract + evidence-conditional ---
    def test_floor_is_unconditional_strip_proof(self):
        # the floor survives an evidence strip — this is what closes Codex's evidence-strip-to-empty-manifest forge
        self.assertEqual(official_expected_field_ids({}), {"hard_veto", "price", "market_risk_regime"})
        self.assertEqual(official_expected_field_ids({"final_action": "持有"}),
                         {"hard_veto", "price", "market_risk_regime"})

    def test_build_requires_score_and_sizing(self):
        self.assertEqual(official_expected_field_ids({"final_action": "建仓"}),
                         {"hard_veto", "price", "market_risk_regime", "core_score", "risk_downgrade", "sizing"})

    def test_evidence_conditional_extras(self):
        self.assertEqual(
            official_expected_field_ids({"final_action": "持有", "theme_probe": {"x": 1}, "forward_event": {"y": 1}}),
            {"hard_veto", "price", "market_risk_regime", "theme_lifecycle_state", "theme_opportunity_state", "forward_event"})

    def test_emitted_equals_official_manifest_for_representative_rows(self):
        # single-source pin: the assembler emits EXACTLY the official manifest for a valid row
        for kw in ({"has_score": True, "sized": True},
                   {"final_action": "持有", "row_source": "holding_pass2_only", "has_score": False, "sized": False},
                   {"has_score": True, "sized": True, "theme_probe": True, "forward_event": True}):
            row = _row(**kw)
            self.assertEqual({fr["field_id"] for fr in mr._field_records(row)},
                             official_expected_field_ids(row), kw)

    # --- planted-deletion / unexpected at the OFFICIAL gate (assemble) ---
    def test_dropped_field_record_rejected(self):
        import unittest.mock as mock
        orig = mr._field_records
        with mock.patch.object(mr, "_field_records",
                               lambda r: [fr for fr in orig(r) if fr["field_id"] != "sizing"]):
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(_ranked([_row(sized=True)]), as_of=_AS_OF)

    def test_unexpected_field_record_rejected(self):
        import unittest.mock as mock
        orig = mr._field_records
        def add_extra(r):
            frs = orig(r)
            frs.append(mr._fr("forward_event", op="仅标签", terminal=mr._SHADOW_TERMINAL,
                              disposition=mr._SHADOW, impact_target=None))
            return frs
        with mock.patch.object(mr, "_field_records", add_extra):
            with self.assertRaises(mr.WeekendMachineRecordError):   # row has no forward_event input
                mr.assemble_machine_record(_ranked([_row(forward_event=False)]), as_of=_AS_OF)

    # --- positive controls: legitimately-absent §10 fields assemble clean (no over-requirement) ---
    def test_minimal_row_assembles_clean(self):
        rec = mr.assemble_machine_record(
            _ranked([_row(final_action="持有", row_source="holding_pass2_only", has_score=False, sized=False)]),
            as_of=_AS_OF)
        self.assertTrue(validate_official_machine_record(rec)["clean"])

    def test_full_row_assembles_clean(self):
        rec = mr.assemble_machine_record(
            _ranked([_row(has_score=True, sized=True, forward_event=True)]), as_of=_AS_OF)
        self.assertTrue(validate_official_machine_record(rec)["clean"])

    # --- consumer boundary (Codex re-review-1/2): post-assembly tamper fails the OFFICIAL gate ---
    def test_deleted_field_record_rejected_at_consumer_gate(self):
        import engine.us_short_weekend_action_table as at
        rec = mr.assemble_machine_record(_ranked([_row(has_score=True, sized=True)]), as_of=_AS_OF)
        rec["rows"][0]["field_records"] = [fr for fr in rec["rows"][0]["field_records"]
                                           if fr["field_id"] != "price"]
        self.assertFalse(validate_official_machine_record(rec)["clean"])    # official gate rejects it
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(rec)                                  # and so does the §11.3 projection

    def test_evidence_strip_to_empty_manifest_rejected(self):
        # Codex re-review-2 probe: delete the raw `veto` evidence AND all field_records — an evidence-gated
        # manifest would go empty and pass; the UNCONDITIONAL floor rejects it at the official gate + flatten.
        import engine.us_short_weekend_action_table as at
        rec = mr.assemble_machine_record(
            _ranked([_row(final_action="持有", row_source="holding_pass2_only", has_score=False, sized=False)]),
            as_of=_AS_OF)
        rec["rows"][0].pop("veto", None)
        rec["rows"][0]["field_records"] = []
        self.assertFalse(validate_official_machine_record(rec)["clean"])
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(rec)

    def test_deleting_any_field_record_breaks_clean(self):
        # behavioral triangulation: for a FULL assembled row every emitted manifest record is required → deleting
        # ANY single one makes the record fail the OFFICIAL gate (none silently drops).
        import copy
        base = mr.assemble_machine_record(
            _ranked([_row(has_score=True, sized=True, forward_event=True)]), as_of=_AS_OF)
        n = len(base["rows"][0]["field_records"])
        self.assertGreaterEqual(n, 5)
        for i in range(n):
            rec = copy.deepcopy(base)
            del rec["rows"][0]["field_records"][i]
            self.assertFalse(validate_official_machine_record(rec)["clean"], f"deleting field_record[{i}] must break clean")


class RiskDowngradeLanding(unittest.TestCase):
    """R-USSHORT-BATCH4-RISK-DOWNGRADE-WIRING-GAP: a scored candidate carries a §10 risk_downgrade field_record —
    LANDED on action_rank (the REAL populated surface the penalty changes via core_score) at a real penalty, a
    clean SHADOW at zero; it is in the official manifest so a planted deletion fails the gate and a scored row
    missing it fails assembly closed."""

    def _scored(self, points):
        row = _row()   # 建仓 candidate, has_score
        row["risk_downgrade"] = {"points": points, "hard_veto": False,
                                 "components": {"history": points, "current_event": 0.0, "analyst": 0.0}}
        return row

    def test_penalty_lands_on_action_rank_a_real_populated_surface(self):
        rec = mr.assemble_machine_record(_ranked([self._scored(15.0)]), as_of=_AS_OF)
        rd = _fr_by_id(rec, "risk_downgrade")
        self.assertEqual((rd["disposition"], rd["operation_impact"], rd["impact_target"], rd["terminal_surface_target"]),
                         ("landed", "调信心", "action_rank", "action_rank"))
        # the landing surface is REAL, not phantom: the assembled row actually carries an action_rank value
        # (unlike the never-computed action_confidence cell, which the false landing previously claimed).
        self.assertIsInstance(rec["rows"][0]["action_rank"], int)
        self.assertIsNone(rec["rows"][0].get("action_confidence"))
        self.assertTrue(validate_official_machine_record(rec)["clean"])

    def test_zero_penalty_is_clean_shadow(self):
        rec = mr.assemble_machine_record(_ranked([self._scored(0.0)]), as_of=_AS_OF)
        rd = _fr_by_id(rec, "risk_downgrade")
        self.assertEqual((rd["disposition"], rd["operation_impact"], rd["impact_target"]),
                         ("shadow_record", "仅标签", None))
        self.assertTrue(validate_official_machine_record(rec)["clean"])

    def test_planted_deletion_fails_official_gate(self):
        rec = mr.assemble_machine_record(_ranked([self._scored(15.0)]), as_of=_AS_OF)
        rec["rows"][0]["field_records"] = [f for f in rec["rows"][0]["field_records"]
                                           if f["field_id"] != "risk_downgrade"]
        self.assertFalse(validate_official_machine_record(rec)["clean"])

    def test_scored_row_missing_risk_downgrade_rejected(self):
        bad = _row()
        del bad["risk_downgrade"]
        with self.assertRaises(mr.WeekendMachineRecordError):
            mr.assemble_machine_record(_ranked([bad]), as_of=_AS_OF)


_OX_WARNING = {"overextension_state": "warning", "strips_theme_score": False,
               "execution_flags": {"force_pullback": True, "reduce_size": True, "raise_rr_gate": True},
               "conditions_met": 0, "condition_names": []}


class OverextensionFieldRecord(unittest.TestCase):
    """cut 2d: a row carrying a §4.3 overextension result emits an `overextension_state` §10 field_record that
    lands on its own §11.3 column as an advisory tag (its execution effect is via the `price` record); a
    malformed present record fails closed; absent → no field_record."""

    def _with_ox(self, ox):
        r = _row()
        r["overextension"] = ox
        return mr.assemble_machine_record(_ranked([r]), as_of=_AS_OF)

    def test_field_record_emitted_lands_on_column_and_clean(self):
        rec = self._with_ox(_OX_WARNING)   # assemble_machine_record raises unless §10-clean, so success = clean
        self.assertIn("overextension_state", _ids(rec))
        fr = _fr_by_id(rec, "overextension_state")
        self.assertEqual(fr["operation_impact"], "仅标签")
        self.assertEqual(fr["terminal_surface_target"], "overextension_state")
        self.assertEqual(fr["current_landing_surface"], "overextension_state")
        self.assertEqual(fr["disposition"], "landed")
        self.assertEqual(fr["lifecycle_item_id"], 36)   # §13.1 #36 过热分档阈值
        self.assertEqual(fr["field_class"], "overextension")
        self.assertTrue(validate_official_machine_record(rec)["clean"])

    def test_all_three_states_emit_clean(self):
        records = {
            "none": {"overextension_state": "none", "strips_theme_score": False,
                     "execution_flags": {}, "conditions_met": 0, "condition_names": []},
            "warning": _OX_WARNING,
            "chasing_extreme": {"overextension_state": "chasing_extreme", "strips_theme_score": True,
                                "execution_flags": {}, "conditions_met": 3,
                                "condition_names": ["vertical_run", "volume_climax", "weak_retrace"]},
        }
        for st, tier in records.items():
            rec = self._with_ox(tier)
            self.assertIn("overextension_state", _ids(rec))

    def test_no_field_record_when_absent(self):
        rec = mr.assemble_machine_record(_ranked([_row()]), as_of=_AS_OF)   # no overextension
        self.assertNotIn("overextension_state", _ids(rec))
        self.assertTrue(validate_official_machine_record(rec)["clean"])

    def test_not_in_official_manifest(self):
        # overextension_state is NOT a manifest field_id → the reverse-completeness mandate neither requires nor
        # forbids it (so an absent one is not a "missing" violation, a present one not "unexpected/fabricated").
        self.assertNotIn("overextension_state", official_expected_field_ids(_row()))

    def test_malformed_overextension_fails_closed(self):
        for bad in ("not-a-dict", 42, {"overextension_state": "bogus", "execution_flags": {}},
                    {"overextension_state": "warning", "execution_flags": "nope"}, {"execution_flags": {}},
                    {**_OX_WARNING, "strips_theme_score": True}):
            r = _row()
            r["overextension"] = bad
            with self.assertRaises(mr.WeekendMachineRecordError):
                mr.assemble_machine_record(_ranked([r]), as_of=_AS_OF)


if __name__ == "__main__":
    unittest.main()
