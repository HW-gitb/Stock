# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_cash_allocation_governance
(US-short batch 1, design §8 全局现金分配 / global cash allocation).

The contract freezes the cash-allocation field set, the ordering keys, the conservative
valid_entry_high basis, sequential allocation, and the insufficient-cash→observe floor. Tests assert
(a) the const-pins, (b) byte-faithful field/ordering triangulation + cash_allocation_status ∈
action_table, (c) ordering-weight calibration (#25) resolves against the lifecycle registry, (d)
provenance in §8, and (e) negative schema cases incl. a less-conservative entry basis and removing
the no-over-allocation floor.
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

SCHEMA = ROOT / "schemas" / "us_short_cash_allocation_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_cash_allocation_governance_20260620.json"
ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")
# anchor on cash_allocation_rank (line 226 also contains 全局现金分配额 in the sizing min-caps)
_L232 = next(ln for ln in _TEXT.splitlines() if "cash_allocation_rank" in ln)


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_cash_fields():
    return [s.strip() for s in re.search(r"`([^`]*cash_allocation_rank[^`]*)`", _L232).group(1).split("/")]


def _design_ordering_keys():
    return [s.strip() for s in re.search(r"按\s*(.+?)\s*排序", _L232).group(1).split("/")]


class UsShortCashAllocationGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)

    # --- structural ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_cash_fields_count_and_unique(self):
        f = self.preset["cash_allocation_fields"]
        self.assertEqual(len(f), 5)
        self.assertEqual(len(f), len(set(f)))

    def test_ordering_keys(self):
        self.assertEqual(self.preset["ordering_keys"], ["排名", "置信", "RR", "流动性"])

    # --- triangulation / cross-schema ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        self.assertEqual(p["cash_allocation_fields"]["const"], self.preset["cash_allocation_fields"])
        self.assertEqual(p["ordering_keys"]["const"], self.preset["ordering_keys"])
        self.assertEqual(p["ordering_weight_calibration_item_id"]["const"],
                         self.preset["ordering_weight_calibration_item_id"])

    def test_cash_fields_byte_faithful_to_design_8(self):
        self.assertEqual(self.preset["cash_allocation_fields"], _design_cash_fields())

    def test_ordering_keys_byte_faithful_to_design_8(self):
        self.assertEqual(self.preset["ordering_keys"], _design_ordering_keys())

    def test_cash_allocation_status_in_action_table(self):
        self.assertIn("cash_allocation_status", _load(ACTION_TABLE_PRESET)["core_columns"])

    def test_ordering_weight_calibration_item_id_resolves(self):
        cid = self.preset["ordering_weight_calibration_item_id"]
        self.assertEqual(cid, 25)
        items = _load(LIFECYCLE_PRESET)["calibration_items"]
        self.assertIn(cid, {it["number"] for it in items})
        self.assertIn("现金分配", next(it["title"] for it in items if it["number"] == 25))

    # --- rules ---
    def test_allocation_scope_buildable_only(self):
        sc = self.preset["allocation_scope"]
        self.assertEqual(sc["scope"], "buildable_only")          # §8 可建仓票
        self.assertTrue(sc["only_buildable_tickers"])
        self.assertTrue(sc["never_rescue_non_buildable"])

    def test_conservative_entry_basis(self):
        self.assertEqual(self.preset["conservative_entry_basis"], "valid_entry_high")

    def test_sequential_allocation(self):
        self.assertTrue(self.preset["sequential_allocation"])

    def test_insufficient_cash_to_observe(self):
        self.assertTrue(self.preset["insufficient_cash_to_observe"])

    def test_provenance_in_design(self):
        for phrase in ("全局现金分配", "可建仓票", "最保守", "依次分配", "现金不够", "降观察", "valid_entry_high"):
            self.assertIn(phrase, _TEXT, f"§8 cash_allocation provenance phrase missing: {phrase}")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_field_drift(self):
        self._reject(lambda d: d["cash_allocation_fields"].__setitem__(0, "cash_rank"))

    def test_schema_rejects_field_dropped(self):
        self._reject(lambda d: d["cash_allocation_fields"].pop())

    def test_schema_rejects_ordering_key_drift(self):
        self._reject(lambda d: d["ordering_keys"].__setitem__(0, "市值"))

    def test_schema_rejects_ordering_key_dropped(self):
        self._reject(lambda d: d["ordering_keys"].pop())

    def test_schema_rejects_scope_widened(self):
        # widening beyond 可建仓票 (e.g. allocating to all/observe rows) is a scope drift
        self._reject(lambda d: d["allocation_scope"].__setitem__("scope", "all_tickers"))

    def test_schema_rejects_non_buildable_rescue(self):
        self._reject(lambda d: d["allocation_scope"].__setitem__("never_rescue_non_buildable", False))

    def test_schema_rejects_less_conservative_entry_basis(self):
        # valid_entry_low would under-reserve cash → over-allocation; must be rejected
        self._reject(lambda d: d.__setitem__("conservative_entry_basis", "valid_entry_low"))

    def test_schema_rejects_sequential_flip(self):
        self._reject(lambda d: d.__setitem__("sequential_allocation", False))

    def test_schema_rejects_overallocation_floor_removed(self):
        self._reject(lambda d: d.__setitem__("insufficient_cash_to_observe", False))

    def test_schema_rejects_calibration_item_id_change(self):
        self._reject(lambda d: d.__setitem__("ordering_weight_calibration_item_id", 24))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
