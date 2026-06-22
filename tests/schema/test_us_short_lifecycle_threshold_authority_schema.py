# -*- coding: utf-8 -*-
"""Schema + integrity tests for us_short_lifecycle_threshold_authority (batch-3 R2 §13.2 threshold authority).

The authority pins the machine-readable §13.2 per-category thresholds (const) + the §13.1 item→category map
(priors). These tests assert the const-pinned 7 thresholds == preset, that the categories equal the 7 §13.2
categories, and that the item→category map covers the §13.1 numbers (1..39) with in-vocabulary categories —
the cross-refs the lifecycle eval relies on so the register's due is fully governed.
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

SCHEMA = json.loads((ROOT / "schemas" / "us_short_lifecycle_threshold_authority.schema.json").read_text(encoding="utf-8"))
PRESET = json.loads((ROOT / "presets" / "us_short_lifecycle_threshold_authority_20260622.json").read_text(encoding="utf-8"))
CALIBRATION = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
S132_CATEGORIES = {row["object"] for row in CALIBRATION["default_reminder_thresholds"]}
GOV_NUMBERS = {it["number"] for it in CALIBRATION["calibration_items"]}


class ThresholdAuthoritySchema(unittest.TestCase):
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(SCHEMA)

    def test_preset_validates(self):
        jsonschema.validate(PRESET, SCHEMA)

    def test_category_thresholds_const_equals_preset(self):
        props = SCHEMA["properties"]["category_thresholds"]["properties"]
        for cat, sub in props.items():
            self.assertEqual(sub["const"], PRESET["category_thresholds"][cat], cat)

    def test_item_category_const_equals_preset(self):
        # the FULL 39-entry map is const-pinned (no silent same-shape remap)
        self.assertEqual(SCHEMA["properties"]["item_category"]["const"], PRESET["item_category"])

    def test_governed_categories_equal_the_7_s132(self):
        self.assertEqual(set(PRESET["category_thresholds"]), S132_CATEGORIES)
        self.assertEqual(set(SCHEMA["properties"]["category_thresholds"]["required"]), S132_CATEGORIES)

    def test_item_category_covers_the_39_in_vocab(self):
        mapped = {int(k) for k in PRESET["item_category"]}
        self.assertEqual(mapped, GOV_NUMBERS)
        self.assertTrue(set(PRESET["item_category"].values()) <= set(PRESET["category_thresholds"]))

    def test_each_governed_threshold_has_valid_unit_and_positive_min(self):
        for cat, th in PRESET["category_thresholds"].items():
            self.assertIn(th["count_type"], {"weeks", "samples", "triggers"}, cat)
            self.assertGreaterEqual(th["min_count"], 1, cat)
            self.assertIsInstance(th["secondary_required"], bool, cat)

    def _reject(self, mutate):
        bad = copy.deepcopy(PRESET)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, SCHEMA)

    def test_dropping_a_category_is_rejected(self):
        self._reject(lambda d: d["category_thresholds"].pop("scoring weight"))

    def test_drifting_a_threshold_const_is_rejected(self):
        self._reject(lambda d: d["category_thresholds"].__setitem__(
            "scoring weight", {"count_type": "weeks", "min_count": 1, "secondary_required": False}))

    def test_non_digit_item_key_is_rejected(self):
        self._reject(lambda d: d["item_category"].__setitem__("abc", "scoring weight"))

    def test_same_shape_item_category_remap_rejected(self):
        # a same-shape remap (item #7 hard_veto -> scoring weight) must fail the const, not just non-digit keys
        self._reject(lambda d: d["item_category"].__setitem__("7", "scoring weight"))

    def test_unknown_top_level_property_rejected(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
