# -*- coding: utf-8 -*-
"""Schema + invariant tests for us_short_scoring_profile_governance (US-short batch 1)."""
import copy
import json
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "us_short_scoring_profile_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_scoring_profile_governance_20260620.json"


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _live_profiles(preset):
    return sorted(n for n, p in preset["profiles"].items() if p["live_eligible"])


class UsShortScoringProfileGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)

    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_weights_sum_to_one(self):
        for name, p in self.preset["profiles"].items():
            self.assertAlmostEqual(sum(p["weights"].values()), 1.0, places=4, msg=name)

    def test_balanced_is_design_locked_40_35_25(self):
        b = self.preset["profiles"]["balanced"]["weights"]
        self.assertEqual((b["momentum"], b["theme"], b["catalyst"]), (0.40, 0.35, 0.25))

    def test_balanced_is_the_only_primary_live_profile(self):
        primaries = sorted(n for n, p in self.preset["profiles"].items() if p["role"] == "primary")
        self.assertEqual(primaries, ["balanced"])
        self.assertEqual(self.preset["primary_profile"], "balanced")
        self.assertEqual(_live_profiles(self.preset), ["balanced"])   # only balanced is live/ship-gate eligible
        for n, p in self.preset["profiles"].items():
            if n == "balanced":
                self.assertTrue(p["live_eligible"])
                self.assertFalse(p["shadow_only"])
            else:                                                     # shadow-only, never ship-gate
                self.assertFalse(p["live_eligible"], n)
                self.assertTrue(p["shadow_only"], n)

    def test_theme_off_has_zero_theme_weight(self):
        self.assertEqual(self.preset["profiles"]["theme_off"]["weights"]["theme"], 0.0)

    def test_theme_weight_ordering_balanced_lt_plus_lt_aggressive(self):
        th = lambda n: self.preset["profiles"][n]["weights"]["theme"]
        self.assertLess(th("balanced"), th("theme_plus"))
        self.assertLess(th("theme_plus"), th("theme_aggressive"))

    def test_live_profile_drift_is_detectable(self):
        # planted-failure: if a shadow profile is flipped live-eligible, the live-set is no longer [balanced]
        bad = copy.deepcopy(self.preset)
        bad["profiles"]["theme_plus"]["live_eligible"] = True
        self.assertNotEqual(_live_profiles(bad), ["balanced"])

    def test_weights_sum_drift_is_detectable(self):
        bad = copy.deepcopy(self.preset)
        bad["profiles"]["balanced"]["weights"]["momentum"] = 0.99
        self.assertNotAlmostEqual(sum(bad["profiles"]["balanced"]["weights"].values()), 1.0, places=4)

    # --- negative SCHEMA tests: the governed constants must be rejected by jsonschema itself (a future
    #     consumer that trusts schema validation must not accept governance drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_shadow_profile_flipped_live(self):
        self._reject(lambda d: d["profiles"]["theme_plus"].__setitem__("live_eligible", True))

    def test_schema_rejects_balanced_weight_drift(self):
        self._reject(lambda d: d["profiles"]["balanced"]["weights"].__setitem__("theme", 0.99))

    def test_schema_rejects_theme_off_non_proportional(self):
        self._reject(lambda d: d["profiles"]["theme_off"].__setitem__(
            "weights", {"momentum": 1.0, "theme": 0.0, "catalyst": 0.0}))

    def test_schema_rejects_comparison_weeks_below_12(self):
        self._reject(lambda d: d.__setitem__("min_comparison_weeks", 1))

    def test_schema_rejects_balanced_flipped_shadow(self):
        self._reject(lambda d: d["profiles"]["balanced"].__setitem__("role", "shadow_comparison"))

    def test_schema_rejects_theme_plus_weight_drift(self):
        # shadow weights are const-pinned at their v1 priors -> non-normalized drift is rejected
        self._reject(lambda d: d["profiles"]["theme_plus"].__setitem__(
            "weights", {"momentum": 0.9, "theme": 0.9, "catalyst": 0.9}))      # sum 2.7

    def test_schema_rejects_theme_aggressive_no_longer_aggressive(self):
        self._reject(lambda d: d["profiles"]["theme_aggressive"].__setitem__(
            "weights", {"momentum": 0.8, "theme": 0.1, "catalyst": 0.1}))      # theme underweight

    def test_calibration_routing_is_split_per_design_section13(self):
        self.assertEqual(self.preset["primary_weight_calibration_item_id"], 1)      # §13.1 #1 = primary 40/35/25
        self.assertEqual(self.preset["comparison_profile_calibration_item_id"], 28)  # §13.1 #28 = comparison weights/weeks
        self.assertNotIn("calibration_item_id", self.preset)   # the collapsed single-id field is gone


if __name__ == "__main__":
    unittest.main()
