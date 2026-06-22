# -*- coding: utf-8 -*-
"""Tests for US-short theme_probe (engine/us_short_theme_probe.py) — §8 强赛道试探名额.

Adversarial focus: the seat matrix (unknown → 0), hard-zero precedence with safety blockers that fail
closed on True / malformed / OMITTED, the §4.3 lifecycle gate (cooling/decayed/retired/unknown → no probe),
the action_table coverage vocab {full, partial}, and the 防御 pullback-only + single-breakout exception.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_theme_probe as tp  # noqa: E402

_GOV = ROOT / "presets" / "us_short_theme_probe_governance_20260622.json"
_ACTION_TABLE_SCHEMA = ROOT / "schemas" / "us_short_action_table_contract.schema.json"


class SeatMatrixTests(unittest.TestCase):
    def test_design_given_and_v1_cells(self):
        self.assertEqual(tp.theme_probe_seats("进攻", "extreme"), 2)
        self.assertEqual(tp.theme_probe_seats("防御", "strong"), 1)
        self.assertEqual(tp.theme_probe_seats("防御", "extreme"), 1)
        self.assertEqual(tp.theme_probe_seats("震荡", "strong"), 1)
        self.assertEqual(tp.theme_probe_seats("进攻", "strong"), 1)

    def test_no_probe_without_strong_theme(self):
        for state in ("no_strong_theme", "normal"):
            for regime in ("进攻", "震荡", "防御", "极度防御"):
                self.assertEqual(tp.theme_probe_seats(regime, state), 0, (regime, state))

    def test_extreme_defensive_row_zero(self):
        for state in tp.THEME_OPPORTUNITY_STATES:
            self.assertEqual(tp.theme_probe_seats("极度防御", state), 0, state)

    def test_unknown_regime_or_state_fails_closed_to_zero(self):
        self.assertEqual(tp.theme_probe_seats("bull", "extreme"), 0)
        self.assertEqual(tp.theme_probe_seats("进攻", "mega"), 0)
        self.assertEqual(tp.theme_probe_seats(None, None), 0)


class HardZeroTests(unittest.TestCase):
    def test_each_hard_zero_condition_blocks(self):
        self.assertTrue(tp.hard_zero_for_probe("极度防御", False, False, False))
        self.assertTrue(tp.hard_zero_for_probe("进攻", in_symbol_cooldown=True, in_portfolio_guard_cooldown=False, hard_veto=False))
        self.assertTrue(tp.hard_zero_for_probe("进攻", in_symbol_cooldown=False, in_portfolio_guard_cooldown=True, hard_veto=False))
        self.assertTrue(tp.hard_zero_for_probe("进攻", in_symbol_cooldown=False, in_portfolio_guard_cooldown=False, hard_veto=True))

    def test_all_clear_requires_explicit_false(self):
        self.assertFalse(tp.hard_zero_for_probe("进攻", False, False, False))

    def test_omitted_blocker_fails_closed(self):
        # the load-bearing fix: an OMITTED safety blocker defaults to BLOCK (must pass explicit False)
        self.assertTrue(tp.hard_zero_for_probe("进攻"))                                  # all omitted
        self.assertTrue(tp.hard_zero_for_probe("进攻", in_portfolio_guard_cooldown=False, hard_veto=False))  # symbol omitted
        self.assertTrue(tp.hard_zero_for_probe("进攻", in_symbol_cooldown=False, hard_veto=False))           # portfolio omitted
        self.assertTrue(tp.hard_zero_for_probe("进攻", in_symbol_cooldown=False, in_portfolio_guard_cooldown=False))  # veto omitted

    def test_malformed_blocking_flag_fails_closed(self):
        for bad in (None, 1, 0, "no", []):
            self.assertTrue(tp.hard_zero_for_probe("进攻", in_portfolio_guard_cooldown=bad, in_symbol_cooldown=False, hard_veto=False), repr(bad))
            self.assertTrue(tp.hard_zero_for_probe("进攻", hard_veto=bad, in_symbol_cooldown=False, in_portfolio_guard_cooldown=False), repr(bad))


class LifecycleGateTests(unittest.TestCase):
    def test_active_states_allow(self):
        for s in ("provisional_active", "confirmed_active"):
            self.assertTrue(tp.lifecycle_allows_probe(s), s)

    def test_degraded_states_block(self):
        for s in ("cooling", "decayed", "retired"):
            self.assertFalse(tp.lifecycle_allows_probe(s), s)

    def test_unknown_or_missing_lifecycle_blocks(self):
        for s in (None, "bogus", "", 1):
            self.assertFalse(tp.lifecycle_allows_probe(s), repr(s))


class DefensiveEntryTests(unittest.TestCase):
    def test_defensive_default_pullback_only(self):
        self.assertEqual(tp.defensive_entry_constraint("防御", "strong"), "pullback_only")
        self.assertEqual(tp.defensive_entry_constraint("防御", "extreme"), "pullback_only")

    def test_defensive_extreme_no_gap_in_band_allows_one_breakout(self):
        self.assertEqual(tp.defensive_entry_constraint("防御", "extreme", no_gap_week=True, entry_in_band=True),
                         "breakout_exception_allowed")

    def test_exception_requires_all_three_strict(self):
        self.assertEqual(tp.defensive_entry_constraint("防御", "strong", no_gap_week=True, entry_in_band=True), "pullback_only")
        self.assertEqual(tp.defensive_entry_constraint("防御", "extreme", no_gap_week=False, entry_in_band=True), "pullback_only")
        self.assertEqual(tp.defensive_entry_constraint("防御", "extreme", no_gap_week=1, entry_in_band=True), "pullback_only")

    def test_non_defensive_regime_no_constraint(self):
        self.assertEqual(tp.defensive_entry_constraint("进攻", "extreme", no_gap_week=True, entry_in_band=True), "none")


class DecisionTests(unittest.TestCase):
    def _ok(self, **kw):
        base = dict(regime="进攻", theme_opportunity_state="extreme", theme_lifecycle_state="confirmed_active",
                    high_confidence=True, coverage_status="full",
                    in_symbol_cooldown=False, in_portfolio_guard_cooldown=False, hard_veto=False)
        base.update(kw)
        return tp.theme_probe_decision(**base)

    def test_full_allow(self):
        out = self._ok()
        self.assertTrue(out["probe_allowed"])
        self.assertEqual(out["seats"], 2)
        self.assertEqual(out["entry_mode_constraint"], "none")
        self.assertEqual(out["risk_tag"], "theme_probe_min_size")

    def test_hard_zero_blocks_even_with_seats_and_confidence(self):
        for kw in (dict(regime="极度防御"), dict(in_portfolio_guard_cooldown=True),
                   dict(in_symbol_cooldown=True), dict(hard_veto=True)):
            out = self._ok(**kw)
            self.assertFalse(out["probe_allowed"], kw)
            self.assertEqual(out["reason"], "hard_zero", kw)

    def test_omitted_safety_blocker_blocks_decision(self):
        # call theme_probe_decision WITHOUT wiring a blocker → fail-closed hard_zero (the integrator-forgot case)
        out = tp.theme_probe_decision("进攻", "extreme", theme_lifecycle_state="confirmed_active",
                                      high_confidence=True, coverage_status="full")   # blockers omitted
        self.assertFalse(out["probe_allowed"])
        self.assertEqual(out["reason"], "hard_zero")

    def test_degraded_lifecycle_blocks_decision(self):
        for s in ("cooling", "decayed", "retired", None, "bogus"):
            out = self._ok(theme_lifecycle_state=s)
            self.assertFalse(out["probe_allowed"], repr(s))
            self.assertEqual(out["reason"], "lifecycle_no_new_probe", repr(s))

    def test_no_seat_when_no_strong_theme(self):
        out = self._ok(theme_opportunity_state="no_strong_theme")
        self.assertFalse(out["probe_allowed"])
        self.assertEqual(out["reason"], "no_seat")

    def test_eligibility_requires_high_confidence_and_non_restricted_coverage(self):
        self.assertFalse(self._ok(high_confidence=False)["probe_allowed"])
        self.assertFalse(self._ok(high_confidence=1)["probe_allowed"])
        for cov in ("restricted", "blocked", None, "clean", "usable_with_fallback", "unknown"):
            out = self._ok(coverage_status=cov)
            self.assertFalse(out["probe_allowed"], cov)
            self.assertEqual(out["reason"], "not_high_confidence_or_coverage_restricted", cov)

    def test_full_and_partial_coverage_are_eligible(self):
        self.assertTrue(self._ok(coverage_status="full")["probe_allowed"])
        self.assertTrue(self._ok(coverage_status="partial")["probe_allowed"])

    def test_defensive_probe_is_pullback_only(self):
        out = self._ok(regime="防御", theme_opportunity_state="strong")
        self.assertTrue(out["probe_allowed"])
        self.assertEqual(out["seats"], 1)
        self.assertEqual(out["entry_mode_constraint"], "pullback_only")

    def test_defensive_extreme_breakout_exception_in_decision(self):
        out = self._ok(regime="防御", theme_opportunity_state="extreme", no_gap_week=True, entry_in_band=True)
        self.assertTrue(out["probe_allowed"])
        self.assertEqual(out["entry_mode_constraint"], "breakout_exception_allowed")


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_vocab_and_risk_tag_match_preset(self):
        self.assertEqual(tp.THEME_OPPORTUNITY_STATES, tuple(self.gov["theme_opportunity_state_vocab"]))
        self.assertEqual(tp.RISK_TAG, self.gov["risk_tag"])

    def test_seats_match_preset_matrix(self):
        for row in self.gov["theme_probe_seat_matrix"]:
            for state in self.gov["theme_opportunity_state_vocab"]:
                self.assertEqual(tp.theme_probe_seats(row["regime"], state), row[state], (row["regime"], state))

    def test_hard_zero_includes_portfolio_guard(self):
        self.assertIn("portfolio_guard_cooldown", self.gov["hard_zero_conditions"])

    def test_coverage_eligible_is_action_table_non_restricted(self):
        contract = json.loads(_ACTION_TABLE_SCHEMA.read_text(encoding="utf-8"))
        enum = contract["properties"]["design_locked_enums"]["properties"]["coverage_status"]["const"]
        self.assertTrue(set(tp.COVERAGE_ELIGIBLE).issubset(enum))     # eligible values are real coverage_status values
        self.assertNotIn("restricted", tp.COVERAGE_ELIGIBLE)          # and exclude the restricted / blocked ones
        self.assertNotIn("blocked", tp.COVERAGE_ELIGIBLE)


if __name__ == "__main__":
    unittest.main()
