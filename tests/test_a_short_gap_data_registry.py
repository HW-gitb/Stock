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
    ADVISORY_VETO_TAG, build_m67_report, build_holding_report, validate_m67_consistency,
    validate_operation_impact_no_dangling, _semantic_operation_impacts,
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


# ── 4.2 第3轮: semantic 复用 → advisory operation_impact + 全 guard ────────────
# 合法 semantic 输入构造(过 _validate_semantic_official / _web_llm_consistency_error)。
_OFFICIAL_HIGH = {"status": "risk", "had_pit_announcements": True,
                  "events": [{"source": "cninfo", "title": "立案调查", "category": "监管",
                              "disclosure_date": "20260610", "risk_type": "litigation",
                              "severity": "high", "url_or_pdf": "http://cninfo.example/x.pdf"}]}
_OFFICIAL_HIGH_NOURL = {"status": "risk", "had_pit_announcements": True,
                        "events": [{"source": "cninfo", "title": "例行公告", "category": "监管",
                                    "disclosure_date": "20260610", "risk_type": "litigation",
                                    "severity": "high", "url_or_pdf": ""}]}   # 缺 URL → high 降为待核
_WEB_RISK = {"web_llm": {"status": "risk", "risk_level": "high", "action": "downgrade"},
             "sources": [{"title": "t", "url": "http://news.example/x"}]}
_WEB_TAILWIND = {"web_llm": {"status": "tailwind", "risk_level": "none", "action": "no_action"},
                 "sources": [{"title": "t", "url": "http://news.example/up"}]}


def _sem_impacts(r):
    return [i for i in (r["machine"].get("operation_impact") or []) if i["field_class"] == "semantic_advisory"]


def _holding_official_impact():
    """引擎 helper 产的合法持仓 semantic advisory impact(official high, existing_holding):
    holding_row_impact / clear_review / blocked_add / m67_advisory_veto / future_s3b + pending S3b / private_account。"""
    return _semantic_operation_impacts([_OFFICIAL_HIGH["events"][0]], None, False, AS_OF, "existing_holding")[0]


class SemanticAdvisoryImpactTests(unittest.TestCase):
    """4.2 第3轮: 候选行 semantic 统一成 advisory operation_impact(official 证据齐全 high → m67_advisory_veto;
    web downgrade → priority_down)。semantic 永 advisory / 非生产;web_llm 绝不 hard_veto。"""

    def test_official_high_emits_advisory_veto(self):
        r = build_m67_report(_good_input(semantic=_OFFICIAL_HIGH), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")               # advisory veto 仍落 操作=否决
        off = [i for i in _sem_impacts(r) if i["source_field"] == "semantic_official_high"]
        self.assertEqual(len(off), 1)
        self.assertEqual(off[0]["veto_class"], "m67_advisory_veto")       # 非 production_hard_veto
        self.assertFalse(off[0]["production_effect_enabled"])
        self.assertEqual(off[0]["visibility_shape"], "candidate_row_impact")
        self.assertEqual(off[0]["new_entry_effect"], "hard_veto")
        self.assertIn(ADVISORY_VETO_TAG, r["m67"]["精简结论区"]["否决审查触发"])   # ⑨ 文本标非生产
        validate_m67_consistency(r)                                       # 全 guard 通过

    def test_web_downgrade_emits_priority_down(self):
        r = build_m67_report(_good_input(semantic_web_llm=_WEB_RISK), AS_OF, "t")
        web = [i for i in _sem_impacts(r) if i["source_field"] == "semantic_web_llm"]
        self.assertEqual(len(web), 1)
        self.assertEqual(web[0]["veto_class"], "none")                    # web 绝不 veto
        self.assertEqual(web[0]["new_entry_effect"], "priority_down")
        self.assertFalse(web[0]["production_effect_enabled"])
        validate_m67_consistency(r)

    def test_official_high_no_url_no_advisory_veto(self):
        r = build_m67_report(_good_input(semantic=_OFFICIAL_HIGH_NOURL), AS_OF, "t")
        self.assertNotEqual(r["m67"]["table"]["操作"], "否决")             # 缺 URL → 待核, 不否决
        self.assertEqual([i for i in _sem_impacts(r) if i["source_field"] == "semantic_official_high"], [])

    def test_no_semantic_no_impact(self):
        self.assertEqual(_sem_impacts(build_m67_report(_good_input(), AS_OF, "t")), [])

    def test_semantic_impact_passes_schema(self):
        r = build_m67_report(_good_input(semantic=_OFFICIAL_HIGH, semantic_web_llm=_WEB_RISK), AS_OF, "t")
        jsonschema.validate(r, _load(M67_SCHEMA))
        self.assertEqual(len(_sem_impacts(r)), 2)                         # official + web 各一条

    def test_held_topn_official_high_holding_advisory_not_veto(self):
        # S2 fix(R-...-S2-HOLDING-SEMANTIC-TOPN-RENDER-DRIFT): 持仓在 TopN(走 build_m67)+ official high →
        # 持有(不否决) + holding_row_impact clear_review(按 has_position scope,不依 builder),绝不进候选 hard veto。
        r = build_m67_report(_good_input(semantic=_OFFICIAL_HIGH, stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertEqual(r["machine"]["layer"]["hard_veto"], [])
        imp = [i for i in _sem_impacts(r) if i["source_field"] == "semantic_official_high"][0]
        self.assertEqual(imp["visibility_shape"], "holding_row_impact")
        self.assertEqual(imp["holding_effect"], "clear_review")
        self.assertTrue(imp["blocked_add_required"])
        validate_m67_consistency(r)

    def test_held_topn_web_holding_hold_watch(self):
        r = build_m67_report(_good_input(semantic_web_llm=_WEB_RISK, stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        imp = [i for i in _sem_impacts(r) if i["source_field"] == "semantic_web_llm"][0]
        self.assertEqual(imp["holding_effect"], "hold_watch")
        validate_m67_consistency(r)

    def test_anti_rescue_semantic_tailwind_does_not_rescue(self):
        # production hard veto(reduce_deduct) + semantic 正面(tailwind) → 仍否决, 不救回
        r = build_m67_report(_reduce_input(semantic_web_llm=_WEB_TAILWIND), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        validate_m67_consistency(r)


class SemanticGuardTests(unittest.TestCase):
    """4.2 第3轮 guard ⑦⑧⑨⑩ + 持仓 holding_row_impact 合法形态(构造输入直接喂 guard)。"""

    def _veto_report(self):
        return build_m67_report(_good_input(semantic=_OFFICIAL_HIGH), AS_OF, "t")   # 候选 advisory-veto

    def test_guard7_advisory_veto_must_be_nonproduction(self):
        r = self._veto_report()
        [i for i in r["machine"]["operation_impact"]
         if i["source_field"] == "semantic_official_high"][0]["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_semantic_official_cannot_be_promoted_to_production_hard_veto(self):
        r = self._veto_report()
        imp = [i for i in r["machine"]["operation_impact"]
               if i["source_field"] == "semantic_official_high"][0]
        imp["veto_class"] = "production_hard_veto"
        imp["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_semantic_official_hard_veto_must_keep_advisory_veto_class(self):
        r = self._veto_report()
        imp = [i for i in r["machine"]["operation_impact"]
               if i["source_field"] == "semantic_official_high"][0]
        imp["veto_class"] = "none"
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_semantic_web_llm_must_stay_nonproduction(self):
        r = build_m67_report(_good_input(semantic_web_llm=_WEB_RISK), AS_OF, "t")
        [i for i in r["machine"]["operation_impact"]
         if i["source_field"] == "semantic_web_llm"][0]["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_any_semantic_advisory_cannot_claim_production_effect(self):
        r = self._veto_report()
        imp = [i for i in r["machine"]["operation_impact"]
               if i["source_field"] == "semantic_official_high"][0]
        imp["source_field"] = "semantic_future_feed"
        imp["veto_class"] = "production_hard_veto"
        imp["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_guard8_web_llm_never_veto(self):
        r = build_m67_report(_good_input(semantic_web_llm=_WEB_RISK), AS_OF, "t")
        [i for i in r["machine"]["operation_impact"]
         if i["source_field"] == "semantic_web_llm"][0]["veto_class"] = "m67_advisory_veto"
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_guard8_web_llm_never_hard_veto(self):
        r = build_m67_report(_good_input(semantic_web_llm=_WEB_RISK), AS_OF, "t")
        [i for i in r["machine"]["operation_impact"]
         if i["source_field"] == "semantic_web_llm"][0]["new_entry_effect"] = "hard_veto"
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_guard9_advisory_veto_text_tag_required(self):
        r = self._veto_report()
        r["m67"]["精简结论区"]["否决审查触发"] = "立案"            # 抹掉 advisory tag
        r["m67"]["精简结论区"]["操作建议"] = "否决,禁止建仓。"      # 无 tag
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_guard10_blocked_add_must_be_visible(self):
        r = self._veto_report()
        r["m67"]["table"]["操作"] = "持有"
        r["machine"]["operation_impact"] = [_holding_official_impact()]   # blocked_add=True
        r["m67"]["精简结论区"]["操作建议"] = f"持有。复核({ADVISORY_VETO_TAG})。"   # 含 tag(过⑨)但无禁止加仓
        r["m67"]["精简结论区"]["风控触发"] = "无"
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_holding_advisory_impact_legal_form_passes(self):
        r = self._veto_report()
        r["m67"]["table"]["操作"] = "持有"
        r["machine"]["operation_impact"] = [_holding_official_impact()]
        r["m67"]["精简结论区"]["操作建议"] = f"已有持仓,禁止加仓。清仓复核建议({ADVISORY_VETO_TAG})。"
        validate_operation_impact_no_dangling(r)                          # holding_row_impact 合法形态 → 不 raise


class HoldingSemanticS2Tests(unittest.TestCase):
    """4.2 S2: build_holding_report 接 semantic → holding_row_impact(advisory) + 文本; action 恒「持有」(不否决/不自动卖出)。
    无 semantic 输入 → S1 向后兼容(零 impact / 否决审查触发未核查 / 无 semantic_risk trace)。"""

    def _held_inp(self, **over):
        inp = {"ts_code": "600000.SH", "name": "x", "close": 2.90,
               "price_series": [{"high": 2.92, "low": 2.88, "close": 2.90}] * 30,
               "market_regime": "震荡期", "iv": {"iv_percentile_252d": 55.0},
               "stateful_risk": _held_state()}
        inp.update(over)
        return inp

    def test_official_high_holding_clear_review(self):
        r = build_holding_report(self._held_inp(semantic=_OFFICIAL_HIGH), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")          # 持仓 semantic 绝不翻否决
        imp = [i for i in r["machine"]["operation_impact"] if i["source_field"] == "semantic_official_high"][0]
        self.assertEqual(imp["visibility_shape"], "holding_row_impact")
        self.assertEqual(imp["holding_effect"], "clear_review")
        self.assertEqual(imp["new_entry_effect"], "none")
        self.assertTrue(imp["blocked_add_required"])
        self.assertEqual(imp["veto_class"], "m67_advisory_veto")
        self.assertFalse(imp["production_effect_enabled"])
        self.assertEqual(imp["pending_successor_slice"], "S3b")        # 减仓价待 S3b
        self.assertEqual(imp["privacy_class"], "private_account")      # 涉真实持仓 → 私密
        self.assertIn(ADVISORY_VETO_TAG, r["m67"]["精简结论区"]["操作建议"])   # guard ⑨
        validate_m67_consistency(r)

    def test_web_downgrade_holding_hold_watch(self):
        r = build_holding_report(self._held_inp(semantic_web_llm=_WEB_RISK), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        imp = [i for i in r["machine"]["operation_impact"] if i["source_field"] == "semantic_web_llm"][0]
        self.assertEqual(imp["holding_effect"], "hold_watch")
        self.assertEqual(imp["veto_class"], "none")                   # web/LLM 绝不 veto
        self.assertTrue(imp["blocked_add_required"])
        validate_m67_consistency(r)

    def test_no_semantic_holding_s1_unchanged(self):
        r = build_holding_report(self._held_inp(), AS_OF, "t")        # provider None → S1 不变
        self.assertNotIn("operation_impact", r["machine"])
        self.assertEqual(r["m67"]["精简结论区"]["否决审查触发"], "未核查(本周 EGS 粗筛未覆盖)")
        self.assertNotIn("semantic_risk", r["machine"]["layer"])
        validate_m67_consistency(r)

    def test_official_high_no_url_holding_pending(self):
        r = build_holding_report(self._held_inp(semantic=_OFFICIAL_HIGH_NOURL), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertEqual([i for i in (r["machine"].get("operation_impact") or [])
                          if i["source_field"] == "semantic_official_high"], [])   # 缺 URL → 待核, 不发 advisory veto
        validate_m67_consistency(r)

    def test_holding_semantic_does_not_hard_veto(self):
        r = build_holding_report(self._held_inp(semantic=_OFFICIAL_HIGH), AS_OF, "t")
        self.assertEqual(r["machine"]["layer"]["hard_veto"], [])      # 持仓 semantic 不进 hard_veto(S1 被动持有)

    def test_official_unknown_holding_text_not_checked(self):
        # Finding 2 fix: official unknown(有输入但 trace 全 unknown)→ engine text 不写「语义已核查」(与 render _has_semantic
        # 同一判据,no-false-clear);unknown 仍显未核查。
        unknown_sem = {"status": "unknown", "had_pit_announcements": False, "events": []}
        r = build_holding_report(self._held_inp(semantic=unknown_sem), AS_OF, "t")
        veto = r["m67"]["精简结论区"]["否决审查触发"]
        self.assertNotIn("语义已核查", veto)
        self.assertNotIn("语义已核查", r["m67"]["精简结论区"]["操作建议"])
        self.assertIn("未核查", veto)
        validate_m67_consistency(r)


if __name__ == "__main__":
    unittest.main()
