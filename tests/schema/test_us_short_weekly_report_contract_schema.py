# -*- coding: utf-8 -*-
"""Schema + invariant tests for us_short_weekly_report_contract (US-short batch 1, design §11.2).

Freezes the weekly_report.md section set/order + mandatory honest-banner + price_clock fields.
Section titles are Chinese: the schema pins only structure (exactly 13 strings); the EXACT section
content+order is single-source-guarded against design §11.2 here (re-extracted from the doc, so no
Chinese is hardcoded/transcribed in the test). Pairs with the §11.3 action_table contract.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "us_short_weekly_report_contract.schema.json"
PRESET = ROOT / "presets" / "us_short_weekly_report_contract_20260620.json"
ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

EXPECTED_PRICE_CLOCK_FIELDS = ["price_data_through", "news_window_through", "session_scope", "decision_date"]
EXPECTED_BANNER_IDS = ["①", "②", "③", "④", "⑤", "⑥"]
EXPECTED_BANNER_TAGS = ["true_false_observe_split", "macro_cluster_warning", "ship_gate_progress",
                       "price_clock", "hot_excluded_notice", "forward_policy_comparison_reminder"]


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_11_2_sections():
    """Re-extract the §11.2 section list straight from the design (single source of truth)."""
    lines = DESIGN.read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(lines):
        if l.startswith("### 11.2"):
            secline = lines[i + 1]
            return [s.strip() for s in secline.split("。")[0].split(" / ")]
    raise AssertionError("could not locate §11.2 section line in design doc")


class UsShortWeeklyReportContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)

    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_sections_count_is_13_and_unique(self):
        secs = self.preset["sections"]
        self.assertEqual(len(secs), 13)
        self.assertEqual(len(secs), len(set(secs)), "duplicate section title")

    def test_sections_triangulate_schema_const_preset_design(self):
        # single-source guard (checklist §B2): the schema CONST, the preset, and the design §11.2
        # extraction must all be byte-identical (set+ORDER). The schema now const-pins sections, so
        # rename/reorder is rejected by the schema itself; this triangulation keeps the three in sync.
        design = _design_11_2_sections()
        schema_const = self.schema["properties"]["sections"]["const"]
        self.assertEqual(self.preset["sections"], design)
        self.assertEqual(schema_const, design)
        self.assertEqual(schema_const, self.preset["sections"])

    def test_price_clock_always_shown_and_fields(self):
        pc = self.preset["price_clock"]
        self.assertTrue(pc["always_shown"])                      # §11.2 ④ 必显
        self.assertEqual(pc["fields"], EXPECTED_PRICE_CLOCK_FIELDS)

    def test_price_clock_fields_present_in_design(self):
        # single-source: each pinned price_clock field token actually occurs in design §11.2 (no invented field)
        text = DESIGN.read_text(encoding="utf-8")
        for f in EXPECTED_PRICE_CLOCK_FIELDS:
            self.assertIn(f, text, f)

    def test_mandatory_banner_six_elements_ids_and_tags(self):
        mb = self.preset["mandatory_banner"]
        self.assertEqual(mb["count"], 6)
        self.assertEqual([e["id"] for e in mb["elements"]], EXPECTED_BANNER_IDS)
        self.assertEqual([e["tag"] for e in mb["elements"]], EXPECTED_BANNER_TAGS)   # tags now const-pinned

    def test_only_price_clock_banner_is_always_shown(self):
        # §11.2: only ④ price_clock is 必显; all other banner elements are conditional
        for e in self.preset["mandatory_banner"]["elements"]:
            self.assertEqual(e["always_shown"], e["id"] == "④", e["id"])

    def test_lifecycle_count_consistency_invariant_pinned(self):
        # now a structured const invariant (not prose): section 1 count == section 12 count
        lc = self.preset["lifecycle_reminder_count_consistency"]
        self.assertEqual(lc["rule"], "lifecycle_reminder_count_must_match_across_sections")
        self.assertEqual(lc["section_number_a"], 1)
        self.assertEqual(lc["section_number_b"], 12)
        self.assertTrue(lc["must_match"])

    def test_pairs_with_action_table_contract(self):
        # the §11 output surface = this (§11.2) + the action_table contract (§11.3); assert the partner exists
        self.assertEqual(_load(ACTION_TABLE_PRESET)["schema_name"], "us_short_action_table_contract")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_dropped_section(self):
        self._reject(lambda d: d["sections"].pop())            # 12 != const(13)

    def test_schema_rejects_added_section(self):
        self._reject(lambda d: d["sections"].append("额外节"))   # 14 != const(13)

    def test_schema_rejects_section_rename(self):
        # Codex gap #1: same-count rename must now be rejected by the schema (sections const-pinned)
        self._reject(lambda d: d["sections"].__setitem__(0, "本周运行情况"))

    def test_schema_rejects_section_reorder(self):
        # Codex gap #1: same-count reorder must now be rejected by the schema
        def swap(d):
            s = d["sections"]
            s[0], s[1] = s[1], s[0]
        self._reject(swap)

    def test_schema_rejects_banner_tag_drift(self):
        # Codex gap #3: banner tag drift must now be rejected (tags const-pinned)
        self._reject(lambda d: d["mandatory_banner"]["elements"][0].__setitem__("tag", "observe_split"))

    def test_schema_rejects_lifecycle_rule_weakened(self):
        # Codex gap #2: weakening the lifecycle invariant must be rejected (must_match const true)
        self._reject(lambda d: d["lifecycle_reminder_count_consistency"].__setitem__("must_match", False))

    def test_schema_rejects_lifecycle_section_number_drift(self):
        # Codex gap #2 (whole-class on the invariant fields): drifting a pinned section number must fail
        self._reject(lambda d: d["lifecycle_reminder_count_consistency"].__setitem__("section_number_b", 11))

    def test_schema_rejects_price_clock_field_drift(self):
        self._reject(lambda d: d["price_clock"]["fields"].__setitem__(0, "price_asof"))

    def test_schema_rejects_price_clock_not_always_shown(self):
        self._reject(lambda d: d["price_clock"].__setitem__("always_shown", False))

    def test_schema_rejects_banner_count_drift(self):
        self._reject(lambda d: d["mandatory_banner"].__setitem__("count", 4))

    def test_schema_rejects_price_clock_banner_not_always_shown(self):
        # element ④ losing always_shown=true must fail (tuple item const)
        self._reject(lambda d: d["mandatory_banner"]["elements"][3].__setitem__("always_shown", False))

    def test_schema_rejects_banner_id_drift(self):
        self._reject(lambda d: d["mandatory_banner"]["elements"][0].__setitem__("id", "⓪"))

    def test_schema_rejects_extra_banner_element(self):
        self._reject(lambda d: d["mandatory_banner"]["elements"].append(
            {"id": "⑦", "tag": "x", "always_shown": False, "ref": "y"}))

    def test_schema_rejects_unknown_top_level_key(self):
        self._reject(lambda d: d.__setitem__("rendered_md", "..."))


if __name__ == "__main__":
    unittest.main()
