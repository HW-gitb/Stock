# -*- coding: utf-8 -*-
"""Schema + invariant + cross-schema tests for us_short_field_registry_governance
(US-short batch 1 CAPSTONE, design §10 no-dangling + evidence-traceback + field registry).

The contract freezes the per-field registry record schema, operation_impact levels, core-field
classes + impact targets, evidence claim types + traceback kinds, the no-dangling / evidence-traceback
policies, and the pre-generation checks. Tests assert (a) the const-pins, (b) byte-faithful
triangulation to §10, (c) cross-schema links (lifecycle_item_id / operation_impact in the record;
impact targets ⊆ action_table where they are columns), and (d) WHOLE-CLASS coverage — loops over every
const array AND every nested-policy const so no member (top-level or nested) is left unguarded.
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

SCHEMA = ROOT / "schemas" / "us_short_field_registry_governance.schema.json"
PRESET = ROOT / "presets" / "us_short_field_registry_governance_20260620.json"
ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
DESIGN = ROOT / "docs" / "us_short_system_design.md"

_TEXT = DESIGN.read_text(encoding="utf-8")
CONST_ARRAYS = ["registry_record_fields", "operation_impact_levels", "core_field_classes",
                "impact_targets", "evidence_claim_types", "evidence_ref_kinds", "pre_generation_checks"]
NESTED_POLICIES = ["no_dangling_policy", "evidence_traceback_policy"]


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _line(needle):
    return next(ln for ln in _TEXT.splitlines() if needle in ln)


def _bt(s):
    return [x.strip().strip("`") for x in s.split("/")]


# re-extractors mirroring the generator (single-source triangulation)
def _design_registry_fields():
    return _bt(next(s for s in re.findall(r"`([^`]+)`", _line("field_id")) if "field_id" in s))


def _design_operation_impact():
    return _bt(re.search(r"影响强度（([^）]+)）", _line("影响强度")).group(1))


def _design_core_classes():
    return _bt(re.search(r"核心字段（([^）]+)）", _line("核心字段")).group(1))


def _design_impact_targets():
    return _bt(next(s for s in re.findall(r"`([^`]+)`", _line("核心字段")) if "final_action" in s))


def _design_claim_types():
    return _bt(re.search(r"claim（([^）]+)）", _line("反查到 provider row")).group(1))


def _design_ref_kinds():
    return _bt(re.search(r"反查到 (provider row[^*]+)", _line("反查到 provider row")).group(1))


class UsShortFieldRegistryGovernance(unittest.TestCase):
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

    def test_set_sizes(self):
        self.assertEqual(len(self.preset["registry_record_fields"]), 10)
        self.assertEqual(len(self.preset["operation_impact_levels"]), 4)
        self.assertEqual(len(self.preset["core_field_classes"]), 10)
        self.assertEqual(len(self.preset["impact_targets"]), 6)
        self.assertEqual(len(self.preset["evidence_claim_types"]), 6)
        self.assertEqual(len(self.preset["evidence_ref_kinds"]), 3)
        self.assertEqual(len(self.preset["pre_generation_checks"]), 7)
        for k in CONST_ARRAYS:
            self.assertEqual(len(self.preset[k]), len(set(self.preset[k])), f"{k} has duplicates")

    # --- triangulation: schema-const == preset for every const array ---
    def test_schema_const_equals_preset_all_arrays(self):
        for k in CONST_ARRAYS:
            self.assertEqual(self.schema["properties"][k]["const"], self.preset[k], k)

    def test_byte_faithful_to_design_10(self):
        self.assertEqual(self.preset["registry_record_fields"], _design_registry_fields())
        self.assertEqual(self.preset["operation_impact_levels"], _design_operation_impact())
        self.assertEqual(self.preset["core_field_classes"], _design_core_classes())
        self.assertEqual(self.preset["impact_targets"], _design_impact_targets())
        self.assertEqual(self.preset["evidence_claim_types"], _design_claim_types())
        self.assertEqual(self.preset["evidence_ref_kinds"], _design_ref_kinds())

    # --- cross-schema links (capstone consumes other surfaces) ---
    def test_record_has_lifecycle_and_operation_impact_fields(self):
        # the registry record links each field to §13.1 (lifecycle_item_id) and to the impact vocab
        self.assertIn("lifecycle_item_id", self.preset["registry_record_fields"])
        self.assertIn("operation_impact", self.preset["registry_record_fields"])

    def test_impact_targets_that_are_columns_subset_action_table(self):
        at_cols = set(self.at["core_columns"])
        for t in ("final_action", "action_rank", "action_confidence", "risk_tags"):
            self.assertIn(t, self.preset["impact_targets"])
            self.assertIn(t, at_cols, f"impact target {t} not an action_table column")

    def test_lifecycle_registry_resolvable(self):
        # sanity: the lifecycle registry exists with numbered items (lifecycle_item_id resolves against it)
        nums = {it["number"] for it in _load(LIFECYCLE_PRESET)["calibration_items"]}
        self.assertEqual(nums, set(range(1, 40)))

    def test_provenance_in_design(self):
        for phrase in ("no-dangling", "landing_surface", "影响强度", "有计算无落点", "shadow_record",
                       "反向证据反查", "provider row", "lifecycle_item_id", "报告不 clean",
                       "无无证据 claim", "advisory/shadow"):
            self.assertIn(phrase, _TEXT, f"§10 field_registry provenance phrase missing: {phrase}")

    # --- policies ---
    def test_no_dangling_policy_pinned(self):
        p = self.preset["no_dangling_policy"]
        self.assertTrue(p["compute_without_landing_invalid"])
        self.assertTrue(p["advisory_shadow_label_is_valid_landing"])
        self.assertTrue(p["core_field_must_hit_impact_target_or_shadow_or_drop"])

    def test_evidence_traceback_policy_pinned(self):
        p = self.preset["evidence_traceback_policy"]
        self.assertTrue(p["every_claim_must_trace"])
        self.assertTrue(p["untraceable_not_output_as_operation_impact"])

    def test_pre_generation_checks(self):
        self.assertEqual(
            self.preset["pre_generation_checks"],
            ["every_field_has_landing", "every_claim_traceable", "hard_veto_covers_final_action",
             "risk_downgrade_affects_size_confidence_or_tag", "selection_vs_action_rank_explained",
             "no_dangling", "no_unevidenced_claim"],
        )

    # --- negative SCHEMA tests (checklist §A: WHOLE-CLASS coverage, every layer) ---
    def _reject(self, mutate):
        bad = copy.deepcopy(self.preset)
        mutate(bad)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_every_const_array_rejects_drop(self):
        # class guard: dropping any element of any const array is rejected (covers all 7 arrays)
        for k in CONST_ARRAYS:
            self._reject(lambda d, key=k: d[key].pop())

    def test_every_const_array_rejects_drift(self):
        # class guard: mutating the first element of any const array is rejected
        for k in CONST_ARRAYS:
            self._reject(lambda d, key=k: d[key].__setitem__(0, d[key][0] + "_DRIFT"))

    def test_every_nested_policy_const_guarded(self):
        # class guard (the lesson from the exclusion-summary nested-object gap): every nested-policy
        # const must be schema const == preset and rejected when flipped — both policy objects, all members
        for pol in NESTED_POLICIES:
            sch = self.schema["properties"][pol]
            self.assertEqual(set(sch["required"]), set(self.preset[pol]), pol)
            for k in sch["required"]:
                const_v = sch["properties"][k]["const"]
                self.assertEqual(self.preset[pol][k], const_v)
                self._reject(lambda d, p=pol, key=k, v=not const_v: d[p].__setitem__(key, v))

    def test_schema_rejects_added_registry_field(self):
        self._reject(lambda d: d["registry_record_fields"].append("extra_field"))

    def test_schema_rejects_operation_impact_extra_level(self):
        self._reject(lambda d: d["operation_impact_levels"].append("自动清仓"))

    def test_schema_rejects_unknown_top_level_property(self):
        self._reject(lambda d: d.__setitem__("surprise", 1))


if __name__ == "__main__":
    unittest.main()
