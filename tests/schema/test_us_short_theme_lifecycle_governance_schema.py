# -*- coding: utf-8 -*-
"""Schema + invariant tests for us_short_theme_lifecycle_governance (US-short batch 1, design §4.3)."""
import copy
import json
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "us_short_theme_lifecycle_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_theme_lifecycle_governance_20260620.json"

STATES = ("provisional_active", "confirmed_active", "cooling", "decayed", "retired")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


class UsShortThemeLifecycleGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.actions = cls.preset["transition_actions"]

    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_states_are_the_five_design_values(self):
        self.assertEqual(self.preset["states"], list(STATES))
        self.assertEqual(set(self.actions), set(STATES))   # action table covers every state

    def test_no_state_mechanically_clears_a_holding(self):
        # design §4.3: cooling/decayed/retired tag + re-evaluate, NEVER mechanically clear
        for s in STATES:
            self.assertFalse(self.actions[s]["holding_effects"]["mechanical_clear"], s)

    def test_degraded_states_carry_theme_decay_tag_and_section9_reeval(self):
        # design §4.3: cooling / decayed / retired holdings ALL get a theme_decay tag + §9 re-eval
        for s in ("cooling", "decayed", "retired"):
            self.assertTrue(self.actions[s]["holding_effects"]["theme_decay_tag"], s)
            self.assertTrue(self.actions[s]["holding_effects"]["section9_reeval"], s)
        for s in ("provisional_active", "confirmed_active"):
            self.assertFalse(self.actions[s]["holding_effects"]["theme_decay_tag"], s)
            self.assertFalse(self.actions[s]["holding_effects"]["section9_reeval"], s)

    def test_only_cooling_lowers_confidence(self):
        for s in STATES:
            self.assertEqual(self.actions[s]["holding_effects"]["action_confidence_down"], s == "cooling", s)

    def test_theme_seats_multiplier_per_state(self):
        self.assertEqual(self.actions["provisional_active"]["theme_seats_multiplier"], 1.0)
        self.assertEqual(self.actions["confirmed_active"]["theme_seats_multiplier"], 1.0)
        self.assertEqual(self.actions["cooling"]["theme_seats_multiplier"], 0.5)   # halved
        self.assertEqual(self.actions["decayed"]["theme_seats_multiplier"], 0.0)   # no seats
        self.assertEqual(self.actions["retired"]["theme_seats_multiplier"], 0.0)

    def test_probe_allowed_only_for_active_states(self):
        for s in STATES:
            self.assertEqual(self.actions[s]["new_theme_probe_allowed"],
                             s in ("provisional_active", "confirmed_active"), s)

    def test_in_theme_table_false_only_for_retired(self):
        for s in STATES:
            self.assertEqual(self.actions[s]["in_theme_table"], s != "retired", s)

    def test_anti_chatter_down_fast_up_slow(self):
        ac = self.preset["anti_chatter"]
        self.assertEqual(ac["downgrade"], "immediate_on_first_deterioration")
        self.assertEqual(ac["upgrade"], "requires_consecutive_confirmation")
        self.assertEqual(ac["retired_reentry"], "full_provisional_re_confirmation")

    # --- negative SCHEMA tests: the const-pinned action table / anti-chatter / states must be
    #     rejected by jsonschema across MULTIPLE states + fields (checklist §A: cover the whole set) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_mechanical_clear_true(self):
        self._reject(lambda d: d["transition_actions"]["decayed"]["holding_effects"].__setitem__("mechanical_clear", True))

    def test_schema_rejects_cooling_loses_theme_decay_tag(self):
        self._reject(lambda d: d["transition_actions"]["cooling"]["holding_effects"].__setitem__("theme_decay_tag", False))

    def test_schema_rejects_cooling_loses_section9_reeval(self):
        self._reject(lambda d: d["transition_actions"]["cooling"]["holding_effects"].__setitem__("section9_reeval", False))

    def test_schema_rejects_cooling_loses_confidence_down(self):
        self._reject(lambda d: d["transition_actions"]["cooling"]["holding_effects"].__setitem__("action_confidence_down", False))

    def test_schema_rejects_cooling_seats_drift(self):
        self._reject(lambda d: d["transition_actions"]["cooling"].__setitem__("theme_seats_multiplier", 0.9))

    def test_schema_rejects_retired_in_theme_table_true(self):
        self._reject(lambda d: d["transition_actions"]["retired"].__setitem__("in_theme_table", True))

    def test_schema_rejects_decayed_routing_normal(self):
        self._reject(lambda d: d["transition_actions"]["decayed"].__setitem__("new_entry_routing", "normal"))

    def test_schema_rejects_active_probe_disabled(self):
        self._reject(lambda d: d["transition_actions"]["confirmed_active"].__setitem__("new_theme_probe_allowed", False))

    def test_schema_rejects_anti_chatter_drift(self):
        self._reject(lambda d: d["anti_chatter"].__setitem__("downgrade", "slow"))

    def test_schema_rejects_extra_state(self):
        self._reject(lambda d: d.__setitem__("states", list(STATES) + ["surging"]))

    def test_schema_rejects_calibration_id_drift(self):
        self._reject(lambda d: d.__setitem__("threshold_calibration_item_id", 99))


if __name__ == "__main__":
    unittest.main()
