# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_hard_veto_governance
(US-short batch 1, design §5 Hard Veto 分层).

The contract freezes the §5 severity-ordered veto tier ladder (the field-registry operation_impact
vocabulary maps onto it), the §5.3 never-solo-veto safety list, and the §5.1b semantic-advisory-first
policy. Tests assert (a) the const-pins, (b) byte-faithful single-source triangulation
schema==preset==design for the ladder + §5.3 list, (c) the §5.2 calibration route (#7) resolves
against the lifecycle registry, and (d) a full battery of negative schema cases
(tier rename/effect-drift/reorder/drop/add, list drift, policy flip).
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

SCHEMA = ROOT / "schemas" / "us_short_hard_veto_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_hard_veto_governance_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_section_5():
    text = DESIGN.read_text(encoding="utf-8")
    start = re.search(r"^## 5\. ", text, re.M).end()
    end = re.search(r"^## 6\. ", text, re.M).start()
    return text[start:end]


def _design_veto_tiers():
    """Re-extract the §5 ladder table (same logic as the generator) for triangulation."""
    rows = []
    for line in _design_section_5().splitlines():
        m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", line)
        if not m:
            continue
        tier, effect = m.group(1).strip("`"), m.group(2)
        if tier == "层级" or set(tier) <= set("-: "):
            continue
        rows.append({"tier": tier, "effect": effect})
    return rows


def _design_must_not_solo_veto():
    """Re-extract the §5.3 list (same strip-trailing-。 logic as the generator)."""
    m = re.search(r"不应单独硬否决\*\*：(.+)$", _design_section_5(), re.M)
    return [re.sub(r"。$", "", s.strip()) for s in m.group(1).split(" / ")]


class UsShortHardVetoGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.tiers = cls.preset["veto_tiers"]

    # --- structural / positive ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_veto_tiers_severity_order(self):
        # strongest -> weakest, exact ids and order
        self.assertEqual(
            [t["tier"] for t in self.tiers],
            ["entry_hard_veto", "position_hard_veto", "strong_downgrade", "soft_risk_tag", "shadow_record"],
        )
        ids = [t["tier"] for t in self.tiers]
        self.assertEqual(len(ids), len(set(ids)), "duplicate tier")

    def test_must_not_solo_veto_count_and_unique(self):
        lst = self.preset["must_not_solo_veto"]
        self.assertEqual(len(lst), 6)
        self.assertEqual(len(lst), len(set(lst)), "duplicate solo-veto item")

    # --- triangulation: schema-const == preset == design (single source) ---
    def test_schema_const_equals_preset(self):
        props = self.schema["properties"]
        self.assertEqual(props["veto_tiers"]["const"], self.tiers)
        self.assertEqual(props["must_not_solo_veto"]["const"], self.preset["must_not_solo_veto"])
        self.assertEqual(props["candidate_veto_calibration_item_id"]["const"], self.preset["candidate_veto_calibration_item_id"])

    def test_veto_tiers_byte_faithful_to_design_5(self):
        self.assertEqual(self.tiers, _design_veto_tiers())

    def test_must_not_solo_veto_byte_faithful_to_design_5_3(self):
        self.assertEqual(self.preset["must_not_solo_veto"], _design_must_not_solo_veto())
        # the trailing sentence period must NOT leak into the last item
        self.assertFalse(self.preset["must_not_solo_veto"][-1].endswith("。"))

    # --- cross-schema: §5.2 calibration route resolves against the lifecycle registry ---
    def test_candidate_veto_calibration_item_id_resolves(self):
        cid = self.preset["candidate_veto_calibration_item_id"]
        self.assertEqual(cid, 7)
        registry = {it["number"] for it in _load(LIFECYCLE_PRESET)["calibration_items"]}
        self.assertIn(cid, registry, "candidate_veto_calibration_item_id not in lifecycle registry")
        # anchor: §13.1 #7 must actually be the §5.2 candidate-veto item (not some other renumbered item)
        title7 = next(it["title"] for it in _load(LIFECYCLE_PRESET)["calibration_items"] if it["number"] == 7)
        self.assertIn("候选硬否决", title7)

    # --- semantic-veto policy ---
    def test_semantic_veto_policy_pinned(self):
        sp = self.preset["semantic_veto_policy"]
        self.assertTrue(sp["advisory_first"])
        self.assertTrue(sp["unavailable_not_hard_block"])
        self.assertTrue(sp["high_confidence_min_restricted_not_clean"])
        self.assertEqual(sp["unavailable_token"], "semantic_audit_unavailable")

    def test_semantic_token_provenance_in_design(self):
        self.assertIn("semantic_audit_unavailable", _design_section_5())

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_tier_renamed(self):
        self._reject(lambda d: d["veto_tiers"][0].__setitem__("tier", "entry_block"))

    def test_schema_rejects_tier_effect_drift(self):
        self._reject(lambda d: d["veto_tiers"][1].__setitem__("effect", "持仓沉默清仓"))

    def test_schema_rejects_reordered_tiers(self):
        def swap(d):
            t = d["veto_tiers"]
            t[0], t[1] = t[1], t[0]
        self._reject(swap)   # severity order is const-pinned

    def test_schema_rejects_dropped_tier(self):
        self._reject(lambda d: d["veto_tiers"].pop())

    def test_schema_rejects_added_tier(self):
        self._reject(lambda d: d["veto_tiers"].append({"tier": "mega_veto", "effect": "x"}))

    def test_schema_rejects_solo_veto_item_drift(self):
        self._reject(lambda d: d["must_not_solo_veto"].__setitem__(0, "单独高 RSI"))

    def test_schema_rejects_solo_veto_item_dropped(self):
        self._reject(lambda d: d["must_not_solo_veto"].pop())

    def test_schema_rejects_semantic_advisory_flipped(self):
        self._reject(lambda d: d["semantic_veto_policy"].__setitem__("advisory_first", False))

    def test_schema_rejects_semantic_token_change(self):
        self._reject(lambda d: d["semantic_veto_policy"].__setitem__("unavailable_token", "semantic_unknown"))

    def test_schema_rejects_calibration_item_id_change(self):
        self._reject(lambda d: d.__setitem__("candidate_veto_calibration_item_id", 5))

    def test_schema_rejects_semantic_policy_unknown_key(self):
        self._reject(lambda d: d["semantic_veto_policy"].__setitem__("auto_block", True))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
