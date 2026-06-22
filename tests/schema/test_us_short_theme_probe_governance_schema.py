# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_theme_probe_governance
(US-short batch 2, design §4.5/§7/§8 + §13.1 #27/#29; user-approved proposal 2026-06-22).

The contract freezes the 4-state theme_opportunity_state vocab, the §4.5 selection-seat map (#29), the
§8 theme_probe seat matrix (#27), the hard-zero precedence, the theme_probe invariants, and the
defensive-entry rule. Tests assert (a) the const-pins (schema == preset), (b) the design-given seat cells
match §8 + the matrix is monotonic non-decreasing in theme strength, (c) cross-schema (cost_floor reason ∈
observe_reason_types; calibration #27/#29 ∈ the lifecycle registry), (d) provenance in §4.5/§8, and (e)
negative schema cases incl. flipping an invariant, violating a design-given cell, and weakening the
defensive-entry rule.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = ROOT / "schemas" / "us_short_theme_probe_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_theme_probe_governance_20260622.json"
ACTION_GOV_PRESET = ROOT / "presets" / "us_short_action_governance_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
PORTFOLIO_GUARD_PRESET = ROOT / "presets" / "us_short_portfolio_guard_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


class UsShortThemeProbeGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.matrix = {row["regime"]: row for row in cls.preset["theme_probe_seat_matrix"]}

    # --- structural ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    # --- triangulation: schema const == preset ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        for key in ("theme_opportunity_state_vocab", "selection_seat_map", "theme_probe_seat_matrix",
                    "hard_zero_conditions", "portfolio_guard_blocking_status", "section8_caps_that_stack",
                    "seat_calibration_item_id", "selection_seat_calibration_item_id"):
            self.assertEqual(p[key]["const"], self.preset[key], key)

    # --- vocab ---
    def test_vocab_four_monotonic_states(self):
        self.assertEqual(self.preset["theme_opportunity_state_vocab"],
                         ["no_strong_theme", "normal", "strong", "extreme"])
        self.assertTrue(self.preset["vocab_is_monotonic_strength"])

    # --- §4.5 selection seats ---
    def test_selection_seat_map_sums_to_total(self):
        for row in self.preset["selection_seat_map"]:
            self.assertEqual(row["core_top"] + row["theme_momentum"], self.preset["selection_seat_total"], row)

    def test_selection_seat_design_given(self):
        m = {r["state"]: (r["core_top"], r["theme_momentum"]) for r in self.preset["selection_seat_map"]}
        self.assertEqual(m["no_strong_theme"], (12, 3))   # §4.5 line 163 无强赛道周
        self.assertEqual(m["normal"], (10, 5))            # 常
        self.assertEqual(m["strong"], (8, 7))             # 强赛道周

    # --- §8 theme_probe seat matrix ---
    def test_design_given_cells(self):
        for state in ("no_strong_theme", "normal", "strong", "extreme"):
            self.assertEqual(self.matrix["极度防御"][state], 0, state)   # line 221 极度防御 = 0
        self.assertEqual(self.matrix["防御"]["strong"], 1)               # line 221 防御 ≤1
        self.assertEqual(self.matrix["防御"]["extreme"], 1)
        self.assertEqual(self.matrix["进攻"]["extreme"], 2)              # line 221 进攻+极强 ≤2

    def test_no_probe_without_a_confirmed_strong_theme(self):
        for regime in self.matrix:
            self.assertEqual(self.matrix[regime]["no_strong_theme"], 0, regime)
            self.assertEqual(self.matrix[regime]["normal"], 0, regime)

    def test_seats_monotonic_non_decreasing_in_strength(self):
        # a STRONGER theme never gets fewer probe seats than a weaker one (same regime)
        for regime, row in self.matrix.items():
            seq = [row["no_strong_theme"], row["normal"], row["strong"], row["extreme"]]
            self.assertEqual(seq, sorted(seq), regime)

    def test_extreme_caps_at_design_max_two(self):
        for regime, row in self.matrix.items():
            self.assertLessEqual(row["extreme"], 2, regime)   # §8 nothing exceeds the 进攻+极强 ≤2 ceiling

    # --- hard-zero precedence ---
    def test_hard_zero_conditions(self):
        self.assertEqual(self.preset["hard_zero_conditions"],
                         ["regime_extreme_defensive", "symbol_cooldown_active", "portfolio_guard_cooldown", "hard_veto"])
        self.assertTrue(self.preset["defensive_entry"]["hard_zero_overrides_exception"])

    def test_both_cooldowns_hard_zero_a_new_probe(self):
        # §8 line 230: a theme_probe is a NEW entry, so PORTFOLIO-guard cooldown (禁新建/加仓) blocks it — not
        # only the symbol-level cooldown. Machine-guard the distinction + cross-check the portfolio-guard state.
        self.assertIn("symbol_cooldown_active", self.preset["hard_zero_conditions"])
        self.assertIn("portfolio_guard_cooldown", self.preset["hard_zero_conditions"])
        blocking = self.preset["portfolio_guard_blocking_status"]
        effects = {e["state"]: e["effects"] for e in _load(PORTFOLIO_GUARD_PRESET)["state_effects"]}
        self.assertIn(blocking, effects, blocking)
        self.assertTrue(effects[blocking]["block_new_entry"], blocking)   # the named state really blocks a new entry
        self.assertTrue(effects[blocking]["block_add"], blocking)

    # --- invariants ---
    def test_all_invariants_const_true(self):
        for k, v in self.preset["theme_probe_invariants"].items():
            self.assertIs(v, True, k)

    def test_section8_caps_stack_includes_the_risk_gates(self):
        for cap in ("hard_veto", "symbol_cooldown", "portfolio_guard", "available_cash", "single_ticker"):
            self.assertIn(cap, self.preset["section8_caps_that_stack"], cap)

    # --- defensive entry ---
    def test_defensive_entry_rule(self):
        de = self.preset["defensive_entry"]
        self.assertEqual(de["default_mode"], "pullback_only")
        self.assertEqual(de["max_breakout_probes_in_defensive"], 1)
        for req in ("regime_defensive", "theme_opportunity_state_extreme", "no_gap_week", "entry_in_valid_entry_band"):
            self.assertIn(req, de["breakout_exception_requires"], req)

    # --- cross-schema ---
    def test_cost_floor_reason_in_observe_reason_vocab(self):
        self.assertIn(self.preset["cost_floor_observe_reason"], _load(ACTION_GOV_PRESET)["observe_reason_types"])

    def test_calibration_ids_resolve(self):
        items = {it["number"]: it["title"] for it in _load(LIFECYCLE_PRESET)["calibration_items"]}
        self.assertIn(self.preset["seat_calibration_item_id"], items)              # #27
        self.assertIn(self.preset["selection_seat_calibration_item_id"], items)    # #29
        self.assertIn("theme_opportunity", items[27])
        self.assertIn("8+7", items[29])

    # --- provenance ---
    def test_provenance_in_design(self):
        for phrase in ("强赛道试探名额", "theme_probe", "最小可执行仓", "theme_probe_min_size",
                       "pullback_mode", "动态席位", "进攻+极强", "极度防御"):
            self.assertIn(phrase, _TEXT, f"§4.5/§8 theme_probe provenance phrase missing: {phrase}")

    # --- negative SCHEMA tests (checklist §A: whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_vocab_drift(self):
        self._reject(lambda d: d["theme_opportunity_state_vocab"].__setitem__(3, "mega"))

    def test_schema_rejects_vocab_dropped(self):
        self._reject(lambda d: d["theme_opportunity_state_vocab"].pop())

    def test_schema_rejects_extreme_defensive_nonzero(self):
        # 极度防御 must be 0 across the row (hard); a non-zero is a drift
        self._reject(lambda d: d["theme_probe_seat_matrix"][3].__setitem__("extreme", 1))

    def test_schema_rejects_defensive_over_one(self):
        self._reject(lambda d: d["theme_probe_seat_matrix"][2].__setitem__("strong", 2))

    def test_schema_rejects_aggressive_extreme_over_two(self):
        self._reject(lambda d: d["theme_probe_seat_matrix"][0].__setitem__("extreme", 3))

    def test_schema_rejects_invariant_flip(self):
        self._reject(lambda d: d["theme_probe_invariants"].__setitem__("cost_floor_applies", False))

    def test_schema_rejects_defensive_default_breakout(self):
        # turning the defensive default into breakout-anywhere drops the 关突破追高 protection
        self._reject(lambda d: d["defensive_entry"].__setitem__("default_mode", "breakout"))

    def test_schema_rejects_breakout_exception_weakened(self):
        self._reject(lambda d: d["defensive_entry"]["breakout_exception_requires"].remove("no_gap_week"))

    def test_schema_rejects_calibration_id_change(self):
        self._reject(lambda d: d.__setitem__("seat_calibration_item_id", 25))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
