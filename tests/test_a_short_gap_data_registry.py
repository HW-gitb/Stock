"""Tests for 4.2 第1轮: 缺口数据字段清单(registry) + governance + reduce_deduct operation_impact
+ no-dangling/advisory-isolation guard.

零新取数、不改既有动作派生: reduce_deduct 早已驱动 操作=否决,本轮只补 field-level operation_impact
记录 + 把"每个字段都有落点、不悬空"做成 schema 焊死 + 运行时 guard。复用 phase5 测试的 _good_input。
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_phase5_engine import (  # noqa: E402
    build_m67_report, validate_m67_consistency, validate_operation_impact_no_dangling,
)
from tests.test_a_short_phase5_engine import _good_input, _held_state  # noqa: E402

REG_SCHEMA = ROOT / "schemas" / "a_short_gap_data_field_registry.schema.json"
REG_EXAMPLE = ROOT / "schemas" / "examples" / "a_short_gap_data_field_registry.example.json"
GOV_SCHEMA = ROOT / "schemas" / "a_short_gap_data_operation_impact_governance.schema.json"
GOV = ROOT / "presets" / "a_short_gap_data_operation_impact_governance_20260617.json"
M67_SCHEMA = ROOT / "schemas" / "a_short_m67_report.schema.json"
AS_OF = "20260617"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _reduce_input(**over):
    """holder_reduction_active=True(= reduce_deduct 命中)的归一化候选输入。"""
    ev = {"holder_reduction_active": True, "st_or_delisting": False, "regulatory_legacy_vetoed": False}
    return _good_input(event=ev, **over)


class RegistrySchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = _load(REG_SCHEMA)
        self.example = _load(REG_EXAMPLE)

    def test_example_validates(self):
        jsonschema.validate(self.example, self.schema)

    def test_missing_required_col_rejected(self):
        bad = copy.deepcopy(self.example)
        del bad["fields"][0]["evidence_ref_kind"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_nondangling_terminal_required(self):
        # 非 out_of_scope 行 terminal_surface_target=null → schema 拒(no-dangling 焊进 schema)
        bad = copy.deepcopy(self.example)
        row = next(f for f in bad["fields"] if f["visibility_shape"] == "candidate_row_impact")
        row["terminal_surface_target"] = None
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_text_landing_requires_successor(self):
        # 非 implemented(只落文本/未来结构化)却无 pending_successor_slice → schema 拒
        bad = copy.deepcopy(self.example)
        row = next(f for f in bad["fields"] if f["implementation_status"] == "design_only_current_text_landing")
        row["pending_successor_slice"] = None
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_out_of_scope_self_consistent(self):
        # out_of_scope 行被强制 operation_impact_target=none / out_of_scope_by_cadence / out_of_scope_no_landing
        bad = copy.deepcopy(self.example)
        row = next(f for f in bad["fields"] if f["visibility_shape"] == "out_of_scope")
        row["operation_impact_target"] = "new_entry"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.schema = _load(GOV_SCHEMA)
        self.gov = _load(GOV)

    def test_validates(self):
        jsonschema.validate(self.gov, self.schema)

    def test_unset_thresholds_comparison_only(self):
        mr = self.gov["merge_rules"]
        self.assertIsNone(mr["sizing_down_floor_pct"])
        self.assertEqual(mr["sizing_down_when_floor_unset"], "comparison_only")
        self.assertTrue(mr["anti_rescue_required"])

    def test_no_uningested_field_thresholds(self):
        # 决策4: 第一刀不给未接入字段(北向/融资/龙虎榜/大宗)预写阈值块
        for k in ("northbound", "margin", "lhb", "block_trade"):
            self.assertNotIn(k, self.gov)


class ReduceDeductImpactTests(unittest.TestCase):
    def test_reduce_deduct_denies_and_emits_impact(self):
        r = build_m67_report(_reduce_input(), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        self.assertTrue(r["machine"]["layer"]["hard_veto"])          # 非空
        imps = r["machine"].get("operation_impact")
        self.assertTrue(imps and len(imps) == 1)
        imp = imps[0]
        self.assertEqual(imp["source_field"], "holder_reduction_deduct_30d")
        self.assertEqual(imp["veto_class"], "production_hard_veto")
        self.assertTrue(imp["m67_landing_surface"])
        self.assertTrue(imp["terminal_surface_target"])
        self.assertEqual(imp["evidence_ref"]["kind"], "lineage_key")
        validate_m67_consistency(r)                                  # guard 内联通过

    def test_report_validates_against_m67_schema(self):
        r = build_m67_report(_reduce_input(), AS_OF, "t")
        jsonschema.validate(r, _load(M67_SCHEMA))

    def test_normal_input_no_impact_key(self):
        # 向后兼容: 未命中 reduce_deduct → 不加 operation_impact key,正常报告零改动
        r = build_m67_report(_good_input(), AS_OF, "t")
        self.assertNotIn("operation_impact", r["machine"])
        validate_m67_consistency(r)

    def test_anti_rescue_positive_fields_still_deny(self):
        # hard_veto + 强 overlay/score → 仍否决(热度/分数不得救回)
        r = build_m67_report(_reduce_input(overlay={"eligible": True, "crowding_hit": False},
                                           esp_score=99, l4_score=99), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        self.assertTrue(r["machine"]["layer"]["hard_veto"])
        validate_m67_consistency(r)

    def test_held_position_reduce_no_impact(self):
        # R-ASHORT-GAP42-ROUND1-HOLDING-SCOPE-DRIFT: 持仓+减持仍走既有 hard_veto→否决,但 Round 1 不发
        # operation_impact(持仓的结构化减仓/清仓处置属 S3b,不能在 Round 1 误标 already_structured)
        r = build_m67_report(_reduce_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        self.assertNotIn("operation_impact", r["machine"])
        validate_m67_consistency(r)

    def test_m67_schema_requires_evidence_ref(self):
        # R-ASHORT-GAP42-ROUND1-EVIDENCE-REF-GUARD-GAP: schema 层 evidence_ref 必填
        r = build_m67_report(_reduce_input(), AS_OF, "t")
        del r["machine"]["operation_impact"][0]["evidence_ref"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(r, _load(M67_SCHEMA))

    def test_m67_schema_rejects_batch_visibility(self):
        # R-ASHORT-GAP42-ROUND1-VISIBILITY-SHAPE-GUARD-GAP: schema 层只许逐票形态
        r = build_m67_report(_reduce_input(), AS_OF, "t")
        r["machine"]["operation_impact"][0]["visibility_shape"] = "batch_exclusion"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(r, _load(M67_SCHEMA))

    def test_m67_schema_requires_evidence_ref_as_of(self):
        # R-ASHORT-GAP42-ROUND1-EVIDENCE-REF-GUARD-GAP residual: schema 层 evidence_ref.as_of 必填
        r = build_m67_report(_reduce_input(), AS_OF, "t")
        del r["machine"]["operation_impact"][0]["evidence_ref"]["as_of"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(r, _load(M67_SCHEMA))


class NoDanglingGuardTests(unittest.TestCase):
    def _report(self):
        return build_m67_report(_reduce_input(), AS_OF, "t")

    def test_missing_landing_raises(self):
        r = self._report()
        r["machine"]["operation_impact"][0]["m67_landing_surface"] = ""
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_missing_terminal_raises(self):
        r = self._report()
        r["machine"]["operation_impact"][0]["terminal_surface_target"] = ""
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_text_only_without_successor_raises(self):
        r = self._report()
        imp = r["machine"]["operation_impact"][0]
        imp["implementation_status"] = "design_only_current_text_landing"
        imp["pending_successor_slice"] = None
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_advisory_cannot_claim_production_veto(self):
        r = self._report()
        r["machine"]["operation_impact"][0]["production_effect_enabled"] = False  # 仍标 production_hard_veto
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_production_veto_must_deny(self):
        r = self._report()
        r["m67"]["table"]["操作"] = "观察"   # production_hard_veto hard_veto 却未否决
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_evidence_ref_deletion_raises(self):
        # R-ASHORT-GAP42-ROUND1-EVIDENCE-REF-GUARD-GAP: 运行时 guard 也拦 evidence_ref 缺失
        r = self._report()
        del r["machine"]["operation_impact"][0]["evidence_ref"]
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_evidence_ref_bad_kind_raises(self):
        r = self._report()
        r["machine"]["operation_impact"][0]["evidence_ref"] = {"kind": "free_text", "value": "x"}
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_evidence_ref_empty_value_raises(self):
        r = self._report()
        r["machine"]["operation_impact"][0]["evidence_ref"]["value"] = ""
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_batch_exclusion_visibility_raises(self):
        # R-ASHORT-GAP42-ROUND1-VISIBILITY-SHAPE-GUARD-GAP: 运行时 guard 也拦非逐票形态
        r = self._report()
        r["machine"]["operation_impact"][0]["visibility_shape"] = "batch_exclusion"
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_evidence_ref_stale_as_of_raises(self):
        # residual: 证据日期漂移(stale,旧日期)→ 拒(防 stale trace 看似 current)
        r = self._report()
        r["machine"]["operation_impact"][0]["evidence_ref"]["as_of"] = "20250101"
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_evidence_ref_missing_as_of_raises(self):
        r = self._report()
        del r["machine"]["operation_impact"][0]["evidence_ref"]["as_of"]
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_evidence_ref_bad_format_as_of_raises(self):
        r = self._report()
        r["machine"]["operation_impact"][0]["evidence_ref"]["as_of"] = "bad"
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_clean_impact_passes(self):
        validate_operation_impact_no_dangling(self._report())       # 不 raise

    def test_no_impacts_is_noop(self):
        validate_operation_impact_no_dangling(build_m67_report(_good_input(), AS_OF, "t"))


if __name__ == "__main__":
    unittest.main()
