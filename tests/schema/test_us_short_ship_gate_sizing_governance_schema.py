# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_ship_gate_sizing_governance
(US-short batch 1, design §8 ship-gate sizing + hard-veto=0).

The contract freezes the live_permission_status vocab, the sizing/permission fields, and the
maturity-is-reminder-not-cap / ungraduated-not-full-size / real-money-manual / hard-veto-zero
safety rules. Tests assert (a) the const-pins, (b) vocab byte-faithfulness + == action_table +
fields ⊆ action_table columns, (c) calibration (#12) resolves against the lifecycle registry, (d)
provenance in §8, and (e) negative schema cases incl. ungraduated→full-size and hard-veto-allows-
position drifts.
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

SCHEMA = ROOT / "schemas" / "us_short_ship_gate_sizing_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_ship_gate_sizing_governance_20260620.json"
ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_vocab():
    line = next(ln for ln in _TEXT.splitlines() if "ship-gate 成熟度" in ln)
    span = next(s for s in re.findall(r"`([^`]+)`", line) if "paper_or_minimal_only" in s)
    return [s.strip() for s in span.split("/")]


class UsShortShipGateSizingGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.at = _load(ACTION_TABLE_PRESET)

    # --- structural ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_live_permission_status_vocab(self):
        self.assertEqual(self.preset["live_permission_status_vocab"],
                         ["paper_or_minimal_only", "not_full_size_eligible", "full_size_eligible"])

    def test_sizing_fields_count_and_unique(self):
        f = self.preset["sizing_fields"]
        self.assertEqual(len(f), 4)
        self.assertEqual(len(f), len(set(f)))

    # --- triangulation / cross-schema ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        self.assertEqual(p["live_permission_status_vocab"]["const"], self.preset["live_permission_status_vocab"])
        self.assertEqual(p["sizing_fields"]["const"], self.preset["sizing_fields"])
        self.assertEqual(p["calibration_item_id"]["const"], self.preset["calibration_item_id"])

    def test_vocab_byte_faithful_to_design_8(self):
        self.assertEqual(self.preset["live_permission_status_vocab"], _design_vocab())

    def test_vocab_matches_action_table(self):
        self.assertEqual(self.preset["live_permission_status_vocab"],
                         self.at["design_locked_enums"]["live_permission_status"])

    def test_sizing_fields_subset_of_action_table_columns(self):
        self.assertTrue(set(self.preset["sizing_fields"]) <= set(self.at["core_columns"]))

    def test_calibration_item_id_resolves(self):
        cid = self.preset["calibration_item_id"]
        self.assertEqual(cid, 12)
        items = _load(LIFECYCLE_PRESET)["calibration_items"]
        self.assertIn(cid, {it["number"] for it in items})
        self.assertIn("ship-gate", next(it["title"] for it in items if it["number"] == 12))

    # --- safety rules ---
    def test_maturity_is_reminder_not_cap(self):
        self.assertTrue(self.preset["maturity_is_reminder_not_cap"])

    def test_ungraduated_not_full_size_license(self):
        self.assertTrue(self.preset["ungraduated_not_full_size_license"])

    def test_real_money_amount_manual(self):
        self.assertTrue(self.preset["real_money_amount_manual"])

    def test_hard_veto_zero_position(self):
        self.assertTrue(self.preset["hard_veto_zero_position"])

    def test_provenance_in_design(self):
        for phrase in ("ship-gate 成熟度", "提醒、不是算式帽", "未毕业不得当真金满仓许可",
                       "真金投多少手动定", "hard veto = 0 仓"):
            self.assertIn(phrase, _TEXT, f"§8 ship-gate sizing provenance phrase missing: {phrase}")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_vocab_drift(self):
        self._reject(lambda d: d["live_permission_status_vocab"].__setitem__(2, "full_size_ok"))

    def test_schema_rejects_vocab_dropped(self):
        self._reject(lambda d: d["live_permission_status_vocab"].pop())

    def test_schema_rejects_vocab_reorder(self):
        def swap(d):
            v = d["live_permission_status_vocab"]
            v[0], v[2] = v[2], v[0]
        self._reject(swap)

    def test_schema_rejects_field_drift(self):
        self._reject(lambda d: d["sizing_fields"].__setitem__(0, "position_size_amount"))

    def test_schema_rejects_field_dropped(self):
        self._reject(lambda d: d["sizing_fields"].pop())

    def test_schema_rejects_maturity_becomes_cap(self):
        # maturity must stay a reminder, never a system sizing cap
        self._reject(lambda d: d.__setitem__("maturity_is_reminder_not_cap", False))

    def test_schema_rejects_ungraduated_full_size_license(self):
        # an un-graduated track must never become a real-money full-size license
        self._reject(lambda d: d.__setitem__("ungraduated_not_full_size_license", False))

    def test_schema_rejects_hard_veto_allows_position(self):
        # hard veto must force zero position
        self._reject(lambda d: d.__setitem__("hard_veto_zero_position", False))

    def test_schema_rejects_real_money_auto_sized(self):
        # real-money amount must stay manual — auto-sizing it is a safety drift (未毕业不得满仓/真金手动定)
        self._reject(lambda d: d.__setitem__("real_money_amount_manual", False))

    def test_every_safety_boolean_has_negative_guard(self):
        # checklist §A point4 (enumerable named set → cover ALL members): every const-true top-level
        # boolean invariant must be schema-rejected when flipped, so no safety boolean — current or
        # future — is left unguarded. real_money_amount_manual was the originally-missed member.
        bool_consts = [k for k, v in self.schema["properties"].items()
                       if isinstance(v, dict) and v.get("const") is True]
        self.assertEqual(
            set(bool_consts),
            {"maturity_is_reminder_not_cap", "ungraduated_not_full_size_license",
             "real_money_amount_manual", "hard_veto_zero_position"},
        )
        for k in bool_consts:
            self._reject(lambda d, key=k: d.__setitem__(key, False))

    def test_schema_rejects_calibration_item_id_change(self):
        self._reject(lambda d: d.__setitem__("calibration_item_id", 13))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
