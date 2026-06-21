# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_exclusion_summary_governance
(US-short batch 1, design §11.4 exclusion_summary).

The contract freezes the exclusion category set, two-pass coverage, the privacy split, and the
hot_excluded audit (never rescues hard-veto / never changes admission). Tests assert (a) the
const-pins, (b) byte-faithful category triangulation + exclusion_summary ∈ the weekly_report
section set, (c) provenance in §11.4, and (d) negative schema cases incl. exposing real-holding
exclusions and letting hot_excluded rescue a hard veto / change admission.
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

SCHEMA = ROOT / "schemas" / "us_short_exclusion_summary_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_exclusion_summary_governance_20260620.json"
WEEKLY_PRESET = ROOT / "presets" / "us_short_weekly_report_contract_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_categories():
    line = next(ln for ln in _TEXT.splitlines() if "本周剔除" in ln and "分类" in ln)
    return [s.strip() for s in re.search(r"分类（([^）]+)）", line).group(1).split("/")]


class UsShortExclusionSummaryGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)

    # --- structural ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_exclusion_categories_count_and_unique(self):
        c = self.preset["exclusion_categories"]
        self.assertEqual(len(c), 8)
        self.assertEqual(len(c), len(set(c)))

    def test_covers_both_passes(self):
        self.assertEqual(self.preset["covers_passes"], ["pass1_eligibility", "pass2_audit_gate"])

    # --- triangulation / cross-schema ---
    def test_schema_const_equals_preset(self):
        p = self.schema["properties"]
        self.assertEqual(p["exclusion_categories"]["const"], self.preset["exclusion_categories"])
        self.assertEqual(p["covers_passes"]["const"], self.preset["covers_passes"])

    def test_exclusion_categories_byte_faithful_to_design_11_4(self):
        self.assertEqual(self.preset["exclusion_categories"], _design_categories())

    def test_is_weekly_report_section(self):
        # exclusion_summary is the §11.2 weekly_report 本周剔除摘要 section
        sections = _load(WEEKLY_PRESET)["sections"]
        self.assertTrue(any("exclusion_summary" in s for s in sections),
                        "exclusion_summary not found in weekly_report section set")

    # --- rules ---
    def test_privacy_split(self):
        pv = self.preset["privacy"]
        self.assertTrue(pv["real_holding_exclusion_private"])
        self.assertTrue(pv["public_universe_count_trackable"])

    def test_hot_excluded_audit_only(self):
        h = self.preset["hot_excluded"]
        self.assertEqual(h["purpose"], "find_mistaken_kills_only")
        self.assertTrue(h["never_rescue_hard_veto"])
        self.assertTrue(h["never_change_admission"])
        self.assertTrue(h["holding_rows_private"])

    def test_provenance_in_design(self):
        for phrase in ("exclusion_summary", "防误杀", "过度保守", "hot_excluded", "高热度被剔除审计",
                       "绝不救回 hard veto", "不改准入", "真实持仓被剔"):
            self.assertIn(phrase, _TEXT, f"§11.4 exclusion_summary provenance phrase missing: {phrase}")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_category_drift(self):
        self._reject(lambda d: d["exclusion_categories"].__setitem__(0, "波动率"))

    def test_schema_rejects_category_dropped(self):
        self._reject(lambda d: d["exclusion_categories"].pop())

    def test_schema_rejects_covers_passes_drift(self):
        self._reject(lambda d: d["covers_passes"].pop())

    def test_hot_excluded_const_contract_fully_guarded(self):
        # checklist §A point4 (cover ALL members — same class as the ship-gate safety-boolean gap, this
        # time on the NESTED hot_excluded object): every required hot_excluded const must be schema
        # const == preset AND rejected when drifted — not just the 3 safety booleans.
        he = self.schema["properties"]["hot_excluded"]
        keys = he["required"]
        self.assertEqual(set(keys), set(self.preset["hot_excluded"]))   # required == preset keys
        self.assertEqual(
            set(keys),
            {"enabled", "criteria", "purpose", "never_rescue_hard_veto", "never_change_admission",
             "holding_rows_private", "public_universe_heat_count_trackable", "feeds_section13_review"},
        )
        for k in keys:
            const_v = he["properties"][k]["const"]
            self.assertEqual(self.preset["hot_excluded"][k], const_v)    # schema const == preset (nested)
            bad = (not const_v) if isinstance(const_v, bool) else (const_v + "_DRIFT")
            self._reject(lambda d, key=k, v=bad: d["hot_excluded"].__setitem__(key, v))

    def test_schema_rejects_holding_exclusion_exposed(self):
        # real-holding exclusions must stay private
        self._reject(lambda d: d["privacy"].__setitem__("real_holding_exclusion_private", False))

    def test_schema_rejects_hot_excluded_rescues_hard_veto(self):
        # the core safety rule: hot_excluded must never rescue a hard veto
        self._reject(lambda d: d["hot_excluded"].__setitem__("never_rescue_hard_veto", False))

    def test_schema_rejects_hot_excluded_changes_admission(self):
        self._reject(lambda d: d["hot_excluded"].__setitem__("never_change_admission", False))

    def test_schema_rejects_hot_excluded_holding_public(self):
        self._reject(lambda d: d["hot_excluded"].__setitem__("holding_rows_private", False))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
