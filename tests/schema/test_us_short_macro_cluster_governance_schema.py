# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_macro_cluster_governance
(US-short batch 1, design §8 宏观集群集中度 / macro_cluster pseudo-diversification gate).

The contract freezes the macro_cluster_warning_level vocab, the four governed fields, the v1
soft-effect/no-hard-cap policy, and the high-warning effects — while marking the cluster TAG vocab
explicitly OPEN. Tests assert (a) the const-pins, (b) byte-faithful warning-level triangulation +
cross-checks vs action_table (vocab + columns), (c) hard-cap calibration (#31) resolves against the
lifecycle registry, (d) provenance in §8, and (e) negative schema cases incl. closing the open tag
vocab and setting a v1 hard cap.
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

SCHEMA = ROOT / "schemas" / "us_short_macro_cluster_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_macro_cluster_governance_20260620.json"
ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_warning_levels():
    line = next(ln for ln in _TEXT.splitlines() if "macro_cluster_warning_level" in ln and "none" in ln)
    span = next(s for s in re.findall(r"`([^`]+)`", line) if "none" in s)
    return [s.strip() for s in span.split("/")]


class UsShortMacroClusterGovernance(unittest.TestCase):
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

    def test_warning_levels(self):
        self.assertEqual(self.preset["warning_levels"], ["none", "elevated", "high"])

    def test_macro_cluster_fields_count_and_unique(self):
        f = self.preset["macro_cluster_fields"]
        self.assertEqual(len(f), 4)
        self.assertEqual(len(f), len(set(f)))

    # --- triangulation / cross-schema ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        self.assertEqual(p["warning_levels"]["const"], self.preset["warning_levels"])
        self.assertEqual(p["macro_cluster_fields"]["const"], self.preset["macro_cluster_fields"])
        self.assertEqual(p["hard_cap_calibration_item_id"]["const"], self.preset["hard_cap_calibration_item_id"])

    def test_warning_levels_byte_faithful_to_design_8(self):
        self.assertEqual(self.preset["warning_levels"], _design_warning_levels())

    def test_warning_levels_match_action_table(self):
        self.assertEqual(self.preset["warning_levels"],
                         self.at["design_locked_enums"]["macro_cluster_warning_level"])

    def test_macro_cluster_fields_subset_of_action_table_columns(self):
        self.assertTrue(set(self.preset["macro_cluster_fields"]) <= set(self.at["core_columns"]))

    def test_hard_cap_calibration_item_id_resolves(self):
        cid = self.preset["hard_cap_calibration_item_id"]
        self.assertEqual(cid, 31)
        items = _load(LIFECYCLE_PRESET)["calibration_items"]
        self.assertIn(cid, {it["number"] for it in items})
        self.assertIn("macro_cluster", next(it["title"] for it in items if it["number"] == 31))

    # --- policy ---
    def test_cluster_tag_vocab_is_open(self):
        self.assertTrue(self.preset["macro_cluster_vocab_is_open"])

    def test_v1_no_hard_cap(self):
        v = self.preset["v1_policy"]
        self.assertTrue(v["no_hard_cap"])
        self.assertTrue(v["soft_effect_and_banner"])

    def test_high_warning_effects_soft_only(self):
        e = self.preset["high_warning_effects"]
        self.assertTrue(e["risk_tag"])
        self.assertTrue(e["lower_action_confidence"])
        self.assertTrue(e["shrink_model_position_size"])
        self.assertTrue(e["via_sizing_stack_step3_no_extra_compound"])
        self.assertTrue(e["records_macro_cluster_size_adjustment"])
        self.assertTrue(e["report_banner"])

    def test_provenance_in_design(self):
        for phrase in ("宏观集群集中度", "伪分散", "v1 不设硬上限", "软影响", "横幅",
                       "取最狠的一个", "不额外连乘", "macro_cluster_size_adjustment"):
            self.assertIn(phrase, _TEXT, f"§8 macro_cluster provenance phrase missing: {phrase}")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_warning_level_drift(self):
        self._reject(lambda d: d["warning_levels"].__setitem__(2, "critical"))

    def test_schema_rejects_warning_level_dropped(self):
        self._reject(lambda d: d["warning_levels"].pop())

    def test_schema_rejects_warning_level_reorder(self):
        def swap(d):
            w = d["warning_levels"]
            w[0], w[2] = w[2], w[0]
        self._reject(swap)

    def test_schema_rejects_field_drift(self):
        self._reject(lambda d: d["macro_cluster_fields"].__setitem__(0, "macro_group"))

    def test_schema_rejects_field_dropped(self):
        self._reject(lambda d: d["macro_cluster_fields"].pop())

    def test_schema_rejects_closing_open_vocab(self):
        # the tag vocab must stay open — flipping it to closed is a drift
        self._reject(lambda d: d.__setitem__("macro_cluster_vocab_is_open", False))

    def test_schema_rejects_v1_hard_cap(self):
        # v1 must not set a hard cap (thresholds unproven; hard cap = §13 #31 forward)
        self._reject(lambda d: d["v1_policy"].__setitem__("no_hard_cap", False))

    def test_schema_rejects_extra_compounding(self):
        # the size shrink must fold into the sizing stack's no-compound rule
        self._reject(lambda d: d["high_warning_effects"].__setitem__("via_sizing_stack_step3_no_extra_compound", False))

    def test_schema_rejects_high_effect_becomes_hard(self):
        # high warning is soft-only; turning off the risk_tag soft effect is a drift
        self._reject(lambda d: d["high_warning_effects"].__setitem__("risk_tag", False))

    def test_schema_rejects_calibration_item_id_change(self):
        self._reject(lambda d: d.__setitem__("hard_cap_calibration_item_id", 8))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
