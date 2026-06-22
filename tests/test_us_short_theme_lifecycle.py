# -*- coding: utf-8 -*-
"""Tests for the US-short theme lifecycle state machine (engine/us_short_theme_lifecycle.py) — §4.3.

Adversarial focus (fewer FAIL->修复 rounds): the load-bearing gates are down-fast / up-slow anti-chatter,
retired re-entry only via a full provisional gate, the §18.1 #14 non-dangling validator, and the
invariant that NO state mechanically clears a holding. Conformance triangulates the state set + effect
table against the frozen governance preset.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_theme_lifecycle as tl  # noqa: E402

_GOV = ROOT / "presets" / "us_short_theme_lifecycle_governance_20260620.json"


class TransitionTests(unittest.TestCase):
    def test_downgrade_is_immediate_and_steps_one_rung(self):
        self.assertEqual(tl.next_theme_lifecycle_state("provisional_active", deteriorating=True), ("cooling", 0))
        self.assertEqual(tl.next_theme_lifecycle_state("confirmed_active", deteriorating=True), ("cooling", 0))
        self.assertEqual(tl.next_theme_lifecycle_state("cooling", deteriorating=True), ("decayed", 0))
        self.assertEqual(tl.next_theme_lifecycle_state("decayed", deteriorating=True), ("retired", 0))
        self.assertEqual(tl.next_theme_lifecycle_state("retired", deteriorating=True), ("retired", 0))

    def test_deterioration_takes_precedence_over_confirmation(self):
        self.assertEqual(
            tl.next_theme_lifecycle_state("provisional_active", deteriorating=True, confirming=True), ("cooling", 0))

    def test_upgrade_needs_consecutive_confirmation(self):
        first = tl.next_theme_lifecycle_state("provisional_active", confirming=True, confirm_count=0)
        self.assertEqual(first, ("provisional_active", 1))    # held, streak building
        second = tl.next_theme_lifecycle_state("provisional_active", confirming=True, confirm_count=1)
        self.assertEqual(second, ("confirmed_active", 0))     # confirmed -> step up

    def test_recovery_from_cooling_is_up_slow(self):
        self.assertEqual(tl.next_theme_lifecycle_state("cooling", confirming=True, confirm_count=0), ("cooling", 1))
        self.assertEqual(tl.next_theme_lifecycle_state("cooling", confirming=True, confirm_count=1),
                         ("provisional_active", 0))

    def test_stable_holds_and_resets_streak(self):
        self.assertEqual(tl.next_theme_lifecycle_state("provisional_active", confirm_count=1), ("provisional_active", 0))

    def test_retired_reentry_only_via_full_provisional_gate(self):
        self.assertEqual(tl.next_theme_lifecycle_state("retired", confirming=True), ("retired", 0))  # no bounce-back
        self.assertEqual(tl.next_theme_lifecycle_state("retired", confirming=True, confirm_count=5), ("retired", 0))
        self.assertEqual(tl.next_theme_lifecycle_state("retired", passes_provisional_gate=True),
                         ("provisional_active", 0))

    def test_unknown_prior_state_fails_closed(self):
        with self.assertRaises(ValueError):
            tl.next_theme_lifecycle_state("bogus")

    def test_upgrade_confirm_runs_below_two_fails_closed(self):
        # REVERSE-FAILURE control: the up-slow invariant can't be weakened to an immediate upgrade via a
        # 0 / 1 / negative / bool / non-int threshold — any such value must fail closed
        for bad in (0, 1, -1, True, False, 2.0, None):
            with self.assertRaises(ValueError):
                tl.next_theme_lifecycle_state("provisional_active", confirming=True, confirm_count=1,
                                              upgrade_confirm_runs=bad)

    def test_malformed_confirm_count_fails_closed(self):
        # REVERSE-FAILURE control: the consecutive-confirmation STREAK can't be short-circuited into a
        # single-round upgrade via a bool / non-int / negative confirm_count (True+1=2 would trip a 2-run gate)
        for bad in (True, False, 1.5, "1", -1, None):
            with self.assertRaises(ValueError):
                tl.next_theme_lifecycle_state("provisional_active", confirming=True, confirm_count=bad)

    def test_stricter_three_run_upgrade_is_allowed(self):
        # a forward-calibrated stricter threshold is fine: 3 runs -> still held at run 2, up at run 3
        self.assertEqual(tl.next_theme_lifecycle_state("provisional_active", confirming=True,
                                                       confirm_count=1, upgrade_confirm_runs=3),
                         ("provisional_active", 2))
        self.assertEqual(tl.next_theme_lifecycle_state("provisional_active", confirming=True,
                                                       confirm_count=2, upgrade_confirm_runs=3),
                         ("confirmed_active", 0))


class EffectTableTests(unittest.TestCase):
    def test_cooling_halves_seats_blocks_probe_tags_holding(self):
        eff = tl.lifecycle_effects("cooling")
        self.assertEqual(eff["theme_seats_multiplier"], 0.5)
        self.assertFalse(eff["new_theme_probe_allowed"])
        self.assertTrue(eff["holding_effects"]["action_confidence_down"])
        self.assertTrue(eff["holding_effects"]["theme_decay_tag"])

    def test_decayed_zero_seats_new_entry_observe(self):
        eff = tl.lifecycle_effects("decayed")
        self.assertEqual(eff["theme_seats_multiplier"], 0.0)
        self.assertEqual(eff["new_entry_routing"], "observe")

    def test_retired_removed_from_theme_table(self):
        eff = tl.lifecycle_effects("retired")
        self.assertFalse(eff["in_theme_table"])
        self.assertEqual(eff["new_entry_routing"], "blocked_from_theme")

    def test_active_states_have_full_seats_and_probe(self):
        for s in ("provisional_active", "confirmed_active"):
            eff = tl.lifecycle_effects(s)
            self.assertEqual(eff["theme_seats_multiplier"], 1.0)
            self.assertTrue(eff["new_theme_probe_allowed"])

    def test_unknown_state_effects_fail_closed(self):
        with self.assertRaises(KeyError):
            tl.lifecycle_effects("bogus")

    def test_returned_effect_is_copy_safe(self):
        # REVERSE-FAILURE control: mutating the RETURNED effect must NOT corrupt the frozen single-source
        # table (an ordinary downstream consumer can't change later lifecycle_effects/validate results)
        eff = tl.lifecycle_effects("cooling")
        eff["holding_effects"]["mechanical_clear"] = True
        eff["theme_seats_multiplier"] = 99.0
        self.assertFalse(tl.lifecycle_effects("cooling")["holding_effects"]["mechanical_clear"])
        self.assertEqual(tl.lifecycle_effects("cooling")["theme_seats_multiplier"], 0.5)
        self.assertTrue(tl.validate_lifecycle_landing("cooling"))


class ValidatorTests(unittest.TestCase):
    def test_every_state_is_non_dangling(self):
        for s in tl.THEME_STATES:
            self.assertTrue(tl.validate_lifecycle_landing(s), f"{s} must land an effect (non-dangling)")

    def test_no_state_mechanically_clears_a_holding(self):
        # REVERSE-FAILURE invariant: degraded states tag + §9-reeval but NEVER auto-clear (§4.3)
        for s in tl.THEME_STATES:
            self.assertFalse(tl.lifecycle_effects(s)["holding_effects"]["mechanical_clear"], s)

    def test_validator_flags_a_mechanical_clear_as_dangling(self):
        # planted control: if a degraded state ever set mechanical_clear, the validator must reject it
        import copy
        saved = copy.deepcopy(tl.TRANSITION_ACTIONS["cooling"])
        try:
            tl.TRANSITION_ACTIONS["cooling"]["holding_effects"]["mechanical_clear"] = True
            self.assertFalse(tl.validate_lifecycle_landing("cooling"))
        finally:
            tl.TRANSITION_ACTIONS["cooling"] = saved


class ContractConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_state_set_matches_preset(self):
        self.assertEqual(tl.THEME_STATES, tuple(self.gov["states"]))

    def test_anti_chatter_policy_declared_in_preset(self):
        # triangulate the engine's hardcoded down-fast / up-slow / retired-gate logic against the
        # frozen governance declaration so a preset policy change can't silently diverge from the code
        ac = self.gov["anti_chatter"]
        self.assertEqual(ac["downgrade"], "immediate_on_first_deterioration")
        self.assertEqual(ac["upgrade"], "requires_consecutive_confirmation")
        self.assertEqual(ac["retired_reentry"], "full_provisional_re_confirmation")

    def test_every_state_has_complete_effect_keys(self):
        required = {"new_theme_probe_allowed", "theme_seats_multiplier", "new_entry_routing",
                    "in_theme_table", "holding_effects"}
        he_required = {"action_confidence_down", "theme_decay_tag", "section9_reeval", "mechanical_clear"}
        for s in tl.THEME_STATES:
            eff = tl.lifecycle_effects(s)
            self.assertEqual(set(eff), required, s)
            self.assertEqual(set(eff["holding_effects"]), he_required, s)


if __name__ == "__main__":
    unittest.main()
