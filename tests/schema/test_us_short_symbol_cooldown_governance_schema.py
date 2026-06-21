# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_symbol_cooldown_governance
(US-short batch 1, design §8 单票再入场冷静期 / symbol re-entry cooldown).

The contract freezes the no-penalty-if-unfilled rule, the cooldown triggers, the in-cooldown
action, and the anti-revenge-buy re-entry conjunction. Tests assert (a) the const-pins, (b) field
byte-faithfulness + symbol_cooldown_status ∈ action_table, (c) param calibration (#23) resolves
against the lifecycle registry, (d) provenance in §8, and (e) negative schema cases incl. removing
the no-penalty rule and weakening the all-required re-entry gate to any-of.
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

SCHEMA = ROOT / "schemas" / "us_short_symbol_cooldown_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_symbol_cooldown_governance_20260620.json"
ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_cooldown_fields():
    line = next(ln for ln in _TEXT.splitlines() if "单票再入场冷静期" in ln)
    span = re.search(r"`([^`]*symbol_cooldown_status[^`]*)`", line).group(1)
    return [s.strip() for s in span.split("/")]


class UsShortSymbolCooldownGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)

    # --- structural ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_cooldown_fields(self):
        self.assertEqual(self.preset["cooldown_fields"],
                         ["symbol_cooldown_status", "cooldown_until", "reentry_allowed_reason"])

    # --- triangulation / cross-schema ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        self.assertEqual(p["cooldown_fields"]["const"], self.preset["cooldown_fields"])
        self.assertEqual(p["reentry_requires"]["const"], self.preset["reentry_requires"])
        self.assertEqual(p["param_calibration_item_id"]["const"], self.preset["param_calibration_item_id"])

    def test_cooldown_fields_byte_faithful_to_design_8(self):
        self.assertEqual(self.preset["cooldown_fields"], _design_cooldown_fields())

    def test_symbol_cooldown_status_in_action_table(self):
        self.assertIn("symbol_cooldown_status", _load(ACTION_TABLE_PRESET)["core_columns"])

    def test_param_calibration_item_id_resolves(self):
        cid = self.preset["param_calibration_item_id"]
        self.assertEqual(cid, 23)
        items = _load(LIFECYCLE_PRESET)["calibration_items"]
        self.assertIn(cid, {it["number"] for it in items})
        self.assertIn("冷静期", next(it["title"] for it in items if it["number"] == 23))

    # --- rules ---
    def test_breakout_unfilled_no_cooldown(self):
        self.assertTrue(self.preset["breakout_unfilled_no_cooldown"])   # 没进场不罚

    def test_enters_cooldown_on(self):
        self.assertEqual(self.preset["enters_cooldown_on"], ["filled_then_stop_loss", "filled_then_breakout_failure"])

    def test_all_cooldown_triggers_require_fill(self):
        # §18.1 #16 成交后失败才进 — every cooldown-entry trigger must be a filled_then_* event,
        # consistent with breakout_unfilled_no_cooldown (an unfilled breakout is never penalized)
        for t in self.preset["enters_cooldown_on"]:
            self.assertTrue(t.startswith("filled_then_"), f"cooldown trigger lacks fill precondition: {t}")

    def test_during_cooldown_action(self):
        self.assertEqual(self.preset["during_cooldown_action"], "downgrade_to_observe")

    def test_reentry_requires_all_three(self):
        self.assertEqual(self.preset["reentry_requires"], ["new_catalyst", "new_structure", "cooldown_expired"])
        self.assertTrue(self.preset["reentry_all_required"])

    def test_purpose(self):
        self.assertEqual(self.preset["purpose"], "prevent_revenge_buy")

    def test_provenance_in_design(self):
        for phrase in ("单票再入场冷静期", "没进场不罚", "突破单未成交", "期内动作降观察",
                       "新催化剂", "新结构", "期满", "revenge-buy",
                       "成交后失败才进", "突破单未成交不进冷静期"):   # §18.1 #16 filled precondition
            self.assertIn(phrase, _TEXT, f"§8/§18.1 symbol_cooldown provenance phrase missing: {phrase}")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_field_drift(self):
        self._reject(lambda d: d["cooldown_fields"].__setitem__(0, "cooldown_state"))

    def test_schema_rejects_field_dropped(self):
        self._reject(lambda d: d["cooldown_fields"].pop())

    def test_schema_rejects_no_penalty_rule_removed(self):
        # 没进场不罚 must hold — penalizing an unfilled breakout is a drift
        self._reject(lambda d: d.__setitem__("breakout_unfilled_no_cooldown", False))

    def test_schema_rejects_enters_cooldown_drift(self):
        self._reject(lambda d: d["enters_cooldown_on"].__setitem__(0, "filled_then_profit"))

    def test_schema_rejects_unqualified_breakout_failure(self):
        # broad breakout_failure drops the fill precondition (§18.1 #16) — could penalize an unfilled breakout
        self._reject(lambda d: d["enters_cooldown_on"].__setitem__(1, "breakout_failure"))

    def test_schema_rejects_reentry_requirement_dropped(self):
        # weakening the anti-revenge-buy gate by dropping a requirement
        self._reject(lambda d: d["reentry_requires"].pop())

    def test_schema_rejects_reentry_any_of(self):
        # turning the AND conjunction into any-of weakens the gate
        self._reject(lambda d: d.__setitem__("reentry_all_required", False))

    def test_schema_rejects_during_cooldown_action_change(self):
        self._reject(lambda d: d.__setitem__("during_cooldown_action", "allow_full_buy"))

    def test_schema_rejects_calibration_item_id_change(self):
        self._reject(lambda d: d.__setitem__("param_calibration_item_id", 24))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
