# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_sizing_stack_governance
(US-short batch 1, design §8 削减叠法 / position sizing reduction stack).

The contract freezes the ordered 5-step sizing pipeline, the risk-discount factor set with the
take-harshest-not-compound safety rule, the min() cap set, and the below-min→observe floor. Tests
assert (a) the const-pins, (b) byte-faithful triangulation of factors/caps, (c) cap_value
calibration (#4) resolves against the lifecycle registry and the environment source matches the
regime governance, (d) provenance in §8, and (e) negative schema cases incl. reordering the
pipeline and allowing risk-discount compounding.
"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = ROOT / "schemas" / "us_short_sizing_stack_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_sizing_stack_governance_20260620.json"
REGIME_PRESET = ROOT / "presets" / "us_short_regime_governance_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")
_L226 = next(ln for ln in _TEXT.splitlines() if "削减叠法" in ln)


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_factors():
    return re.search(r"风险折扣（([^）]+)）", _L226).group(1).split("——")[0].split("/")


def _design_caps():
    return re.search(r"取最小\(([^)]+)\)", _L226).group(1).split("/")


class UsShortSizingStackGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)

    # --- structural ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_pipeline_5_steps_ordered(self):
        steps = self.preset["sizing_pipeline"]
        self.assertEqual([s["step"] for s in steps], [1, 2, 3, 4, 5])
        self.assertEqual(
            [s["op"] for s in steps],
            ["base_shares", "multiply_environment_multiplier", "multiply_risk_discount",
             "min_of_caps", "below_min_to_observe"],
        )

    def test_risk_discount_factors_count(self):
        self.assertEqual(len(self.preset["risk_discount_factors"]), 4)

    def test_min_caps_count_and_unique(self):
        caps = self.preset["min_caps"]
        self.assertEqual(len(caps), 6)
        self.assertEqual(len(caps), len(set(caps)), "duplicate min cap")

    # --- triangulation ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        self.assertEqual(p["sizing_pipeline"]["const"], self.preset["sizing_pipeline"])
        self.assertEqual(p["risk_discount_factors"]["const"], self.preset["risk_discount_factors"])
        self.assertEqual(p["min_caps"]["const"], self.preset["min_caps"])
        self.assertEqual(p["cap_value_calibration_item_id"]["const"], self.preset["cap_value_calibration_item_id"])

    def test_risk_discount_factors_byte_faithful_to_design_8(self):
        self.assertEqual(self.preset["risk_discount_factors"], _design_factors())

    def test_min_caps_byte_faithful_to_design_8(self):
        self.assertEqual(self.preset["min_caps"], _design_caps())

    # --- safety policy ---
    def test_risk_discount_no_compounding(self):
        rp = self.preset["risk_discount_policy"]
        self.assertTrue(rp["take_harshest_single"])
        self.assertTrue(rp["no_compounding"])

    def test_below_min_to_observe(self):
        self.assertTrue(self.preset["below_min_executable_to_observe"])

    def test_environment_multiplier_source(self):
        self.assertEqual(self.preset["environment_multiplier_source"], "market_risk_regime")

    def test_provenance_in_design(self):
        for phrase in ("削减叠法", "底仓股数", "环境乘数", "风险折扣", "取最狠的一个", "不连乘",
                       "取最小", "最小可执行", "降观察"):
            self.assertIn(phrase, _TEXT, f"§8 削减叠法 provenance phrase missing: {phrase}")

    # --- cross-schema ---
    def test_cap_value_calibration_item_id_resolves(self):
        cid = self.preset["cap_value_calibration_item_id"]
        self.assertEqual(cid, 4)
        items = _load(LIFECYCLE_PRESET)["calibration_items"]
        self.assertIn(cid, {it["number"] for it in items})
        self.assertIn("仓位参数", next(it["title"] for it in items if it["number"] == 4))

    def test_environment_source_matches_regime_governance(self):
        # the step-② multiplier source must be the actual regime-governance domain
        self.assertIn("market_risk_regime_caps", _load(REGIME_PRESET))

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_pipeline_reorder(self):
        def swap(d):
            s = d["sizing_pipeline"]
            s[2], s[3] = s[3], s[2]   # swapping discount and min() reorders the stack
        self._reject(swap)

    def test_schema_rejects_pipeline_step_dropped(self):
        self._reject(lambda d: d["sizing_pipeline"].pop())   # dropping ⑤ below-min floor

    def test_schema_rejects_pipeline_op_drift(self):
        self._reject(lambda d: d["sizing_pipeline"][0].__setitem__("op", "fixed_shares"))

    def test_schema_rejects_risk_discount_factor_drift(self):
        self._reject(lambda d: d["risk_discount_factors"].__setitem__(0, "数据正常"))

    def test_schema_rejects_risk_discount_factor_dropped(self):
        self._reject(lambda d: d["risk_discount_factors"].pop())

    def test_schema_rejects_compounding_allowed(self):
        # the core safety rule: discounts must NOT compound
        self._reject(lambda d: d["risk_discount_policy"].__setitem__("no_compounding", False))

    def test_schema_rejects_min_cap_dropped(self):
        self._reject(lambda d: d["min_caps"].pop())

    def test_schema_rejects_min_cap_drift(self):
        self._reject(lambda d: d["min_caps"].__setitem__(0, "单票下限"))

    def test_schema_rejects_below_min_floor_removed(self):
        self._reject(lambda d: d.__setitem__("below_min_executable_to_observe", False))

    def test_schema_rejects_environment_source_change(self):
        self._reject(lambda d: d.__setitem__("environment_multiplier_source", "vix_only"))

    def test_schema_rejects_calibration_item_id_change(self):
        self._reject(lambda d: d.__setitem__("cap_value_calibration_item_id", 31))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
