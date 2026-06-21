# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_lifecycle_calibration_governance
(US-short batch 1, design §13.1 待校准清单 + §13.2 默认提醒门槛 + §13 policy).

The contract freezes the §13.1 stable-numbered calibration-item set (the backbone the reminder
mechanism `us_short_lifecycle_eval` traverses), the §13.2 reminder-threshold priors, and the §13
governing policy. Tests assert (a) the const-pins, (b) the preset stays byte-faithful to the design
(single-source triangulation schema==preset==design), (c) invariants draft-07 can't express —
contiguous numbering, item_count consistency, every '§13 #N' design cross-ref resolves, and every
sibling governance schema's *_calibration_item_id resolves to a real item — and (d) a full battery
of negative schema cases (drop/add/renumber/retitle/reorder/threshold-drift/policy-flip).
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

SCHEMA = ROOT / "schemas" / "us_short_lifecycle_calibration_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

# sibling governance presets that reference §13.1 item numbers via *_calibration_item_id
SIBLING_PRESETS = [
    ROOT / "presets" / "us_short_scoring_profile_governance_20260620.json",      # #1, #28
    ROOT / "presets" / "us_short_theme_lifecycle_governance_20260620.json",      # #30
]


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _design_13_1_items():
    """Extract §13.1 待校准清单 straight from the design (single source of truth)."""
    text = DESIGN.read_text(encoding="utf-8")
    start = re.search(r"^### 13\.1 ", text, re.M).end()
    end = re.search(r"^### 13\.2 ", text, re.M).start()
    items = []
    for line in text[start:end].splitlines():
        m = re.match(r"^(\d+)\.\s(.+)$", line)
        if m:
            items.append({"number": int(m.group(1)), "title": m.group(2)})
    return items


def _design_13_2_thresholds():
    """Extract §13.2 默认提醒门槛 table straight from the design (single source of truth)."""
    text = DESIGN.read_text(encoding="utf-8")
    start = re.search(r"^### 13\.2 ", text, re.M).end()
    end = re.search(r"^## 14\. ", text, re.M).start()
    rows = []
    for line in text[start:end].splitlines():
        m = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", line)
        if not m:
            continue
        obj, cond = m.group(1), m.group(2)
        if obj == "对象" or set(obj) <= set("-: "):   # skip header + separator rows
            continue
        rows.append({"object": obj, "min_condition": cond})
    return rows


def _collect_calibration_item_ids(obj):
    """Recursively collect every *_calibration_item_id integer value in a loaded preset."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith("calibration_item_id") and isinstance(v, int):
                out.append(v)
            else:
                out.extend(_collect_calibration_item_ids(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_collect_calibration_item_ids(v))
    return out


class UsShortLifecycleCalibrationGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMA)
        cls.preset = _load(PRESET)
        cls.items = cls.preset["calibration_items"]
        cls.numbers = [it["number"] for it in cls.items]
        cls.const_items = cls.schema["properties"]["calibration_items"]["const"]

    # --- structural / positive ---
    def test_schema_valid_draft7(self):
        jsonschema.Draft7Validator.check_schema(self.schema)

    def test_preset_validates(self):
        jsonschema.validate(self.preset, self.schema)

    def test_item_count_consistent(self):
        self.assertEqual(self.preset["item_count"], len(self.items))
        self.assertEqual(self.preset["item_count"], 39)

    def test_numbers_contiguous_1_to_n(self):
        # stable numbering with no gap/dupe — every cross-ref relies on this
        self.assertEqual(self.numbers, list(range(1, len(self.items) + 1)))
        self.assertEqual(len(self.numbers), len(set(self.numbers)), "duplicate item number")

    def test_titles_nonempty_and_unique(self):
        titles = [it["title"] for it in self.items]
        self.assertTrue(all(t.strip() for t in titles))
        self.assertEqual(len(titles), len(set(titles)), "duplicate item title")

    # --- triangulation: schema-const == preset == design (single source) ---
    def test_schema_const_equals_preset(self):
        self.assertEqual(self.const_items, self.items)
        self.assertEqual(
            self.schema["properties"]["default_reminder_thresholds"]["const"],
            self.preset["default_reminder_thresholds"],
        )
        self.assertEqual(self.preset["item_count"], self.schema["properties"]["item_count"]["const"])

    def test_calibration_items_byte_faithful_to_design_13_1(self):
        self.assertEqual(self.items, _design_13_1_items())

    def test_reminder_thresholds_byte_faithful_to_design_13_2(self):
        # the §13.2 table has 7 rows; byte-extraction guards against transcribing only the visible few
        design = _design_13_2_thresholds()
        self.assertEqual(self.preset["default_reminder_thresholds"], design)
        self.assertGreaterEqual(len(design), 7)

    # --- cross-ref integrity (killer guard) ---
    def test_design_cross_refs_resolve(self):
        # every '§13 #N' / '§13.1 #N' reference in the design must point to a real pinned item
        text = DESIGN.read_text(encoding="utf-8")
        refs = [int(n) for n in re.findall(r"§13(?:\.1)?\s*#\s*(\d+)", text)]
        self.assertGreaterEqual(len(refs), 30, "cross-ref regex found too few refs — guard likely broken")
        valid = set(self.numbers)
        for n in refs:
            self.assertIn(n, valid, f"design references §13 #{n} but no such calibration item")

    # --- cross-schema consumer integrity ---
    def test_sibling_calibration_item_ids_resolve(self):
        valid = set(self.numbers)
        seen = []
        for p in SIBLING_PRESETS:
            ids = _collect_calibration_item_ids(_load(p))
            self.assertTrue(ids, f"{p.name} declares no *_calibration_item_id (expected references)")
            for n in ids:
                self.assertIn(n, valid, f"{p.name} references calibration item #{n} not in registry")
            seen.extend(ids)
        # anchors: the known references must be present (a silent field rename would drop them)
        for anchor in (1, 28, 30):
            self.assertIn(anchor, seen, f"expected sibling reference to #{anchor} missing")

    # --- governance policy ---
    def test_governance_policy_all_true(self):
        gp = self.preset["governance_policy"]
        self.assertEqual(
            set(gp),
            {
                "numbering_stable_referenced_by_number",
                "all_items_enrolled_in_reminder_mechanism",
                "eval_traverses_all_items_dynamic_count",
                "eval_runs_before_weekly_report_render",
                "upgrade_requires_user_decision_never_auto_production",
            },
        )
        self.assertTrue(all(gp.values()))

    def test_governance_policy_provenance_in_design(self):
        # each pinned hard-policy flag must be backed by its verbatim design phrase (non-vacuous)
        text = DESIGN.read_text(encoding="utf-8")
        for phrase in ("编号稳定", "全进提醒机制", "动态、不硬编码条数", "渲染之前", "绝不自动切生产"):
            self.assertIn(phrase, text, f"policy provenance phrase missing from design: {phrase}")

    # --- negative SCHEMA tests (checklist §A: cover the whole class of drift) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_schema_rejects_dropped_item(self):
        self._reject(lambda d: d["calibration_items"].pop())

    def test_schema_rejects_added_item(self):
        self._reject(lambda d: d["calibration_items"].append({"number": 40, "title": "speculative"}))

    def test_schema_rejects_renumbered_item(self):
        self._reject(lambda d: d["calibration_items"][0].__setitem__("number", 99))

    def test_schema_rejects_retitled_item(self):
        # same-shape drift: identical structure, mutated title — must still be rejected by const
        self._reject(lambda d: d["calibration_items"][4].__setitem__("title", "benchmark (renamed)"))

    def test_schema_rejects_reordered_items(self):
        def swap(d):
            c = d["calibration_items"]
            c[0], c[1] = c[1], c[0]
        self._reject(swap)   # const array is order-sensitive

    def test_schema_rejects_item_count_mismatch(self):
        self._reject(lambda d: d.__setitem__("item_count", 40))

    def test_schema_rejects_threshold_drift(self):
        self._reject(lambda d: d["default_reminder_thresholds"][0].__setitem__("min_condition", "≥1 周"))

    def test_schema_rejects_dropped_threshold(self):
        self._reject(lambda d: d["default_reminder_thresholds"].pop())

    def test_schema_rejects_policy_flag_flipped(self):
        self._reject(lambda d: d["governance_policy"].__setitem__("upgrade_requires_user_decision_never_auto_production", False))

    def test_schema_rejects_policy_unknown_key(self):
        self._reject(lambda d: d["governance_policy"].__setitem__("auto_promote_ok", True))

    def test_schema_rejects_policy_dropped_key(self):
        self._reject(lambda d: d["governance_policy"].pop("eval_runs_before_weekly_report_render"))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
