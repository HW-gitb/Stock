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
from unittest.mock import patch
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_phase5_engine import (  # noqa: E402
    ADVISORY_VETO_TAG, build_m67_report, build_holding_report, validate_m67_consistency,
    validate_operation_impact_no_dangling, _semantic_operation_impacts,
    _merge_holding_disposition, _apply_holding_disposition, _HOLDING_DISPOSITION_LABEL,
    _REDUCE_RATIO_ADVISORY, _holding_active_alerts,
    _holding_ratchet, _ratchet_report_error, _severity_max_disposition,
)
from engine.a_short_regulatory_advisory import event_fingerprint  # noqa: E402
from runners.a_short_m67_render import _active_alert_line, _ratchet_line  # noqa: E402
from runners.a_short_weekly_pipeline import (  # noqa: E402
    load_holding_ratchet, _apply_holding_ratchet, save_holding_ratchet, _holding_ratchet_key,
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
        # 非 implemented / 非 out_of_scope(只落文本/未来结构化)却无 pending_successor_slice → schema 拒
        bad = copy.deepcopy(self.example)
        row = copy.deepcopy(bad["fields"][0])
        row["field_id"] = "synthetic_design_only_without_successor"
        row["implementation_status"] = "design_only_current_text_landing"
        row["pending_successor_slice"] = None
        bad["fields"].append(row)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_holding_capable_rows_private_holding_shape(self):
        # R-ASHORT-GAP42-ROUND5-DRAGON-HOLDING-REGISTRY-PRIVACY-GAP: 涉持仓的 registry 行必须用持仓侧表达
        # (private_account + holding_row_impact),且不得 operation_impact_target=both —— 隐私/可见性是单值,
        # 不能在一行同时表达候选(public/candidate)+持仓(private/holding)两侧,必须拆两行(§10.3/§12.2)。
        for f in self.example["fields"]:
            t = f["operation_impact_target"]
            self.assertNotEqual(t, "both",
                f"{f['field_id']}: operation_impact_target=both 须拆成 new_entry(public/candidate)+existing_holding(private/holding)两行")
            if t == "existing_holding" or f["visibility_shape"] == "holding_row_impact":
                self.assertEqual(f["visibility_shape"], "holding_row_impact",
                    f"{f['field_id']}: 持仓侧 visibility 须 holding_row_impact")
                self.assertIn(f["privacy_class"], ("private_account", "secret_or_raw_provider"),
                    f"{f['field_id']}: 持仓侧涉真实持仓须 private_account/secret(§10.3/§12.2)")

    def test_new_fetch_source_fields_flag_provider_call(self):
        # R-ASHORT-GAP42-ROUND5-DRAGON-LIST-REGISTRY-PROVIDER-FLAG-GAP: 凡 owner/ref/落点 描述出现真新增取数来源
        # (top_list/top_inst/block_trade 龙虎榜/大宗;pro.forecast/pro.income/pro.balancesheet 财报报表 ②③④)的字段,必须标
        # needs_new_provider_call=true —— 不得像复用 egs_main 既有 fetch 的字段(holder_reduction/share_float/financial_quality
        # 复用 fina_indicator…)那样标 false(否则治理表误导:看似无需取数,实则依赖新增 provider call)。复用既有 fetch 的字段不含这些
        # marker → 不受约束(可 false)。pro. 前缀避免与 net_income 等子串误撞(财报报表行 owner_ref 用 pro.X 记法,镜像 dragon 行 pro.top_list)。
        markers = ("top_list", "top_inst", "block_trade", "pro.forecast", "pro.income", "pro.balancesheet")
        scanned = 0
        for f in self.example["fields"]:
            blob = " ".join(str(f.get(k, "")) for k in
                            ("field_id", "current_owner_file", "current_owner_ref", "m67_landing_surface"))
            if any(m in blob for m in markers):
                scanned += 1
                self.assertTrue(f["needs_new_provider_call"],
                                f"{f['field_id']} 提及新增取数来源{markers}却标 needs_new_provider_call=false(治理表误导)")
        self.assertGreaterEqual(scanned, 1)   # 至少覆盖 dragon_list_appearance(防 marker 漂移致空扫=无效 guard)

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
        # 决策4: 不给"无已定 effect 阈值"的字段预写阈值块。北向/融资/大宗仍未接入。
        # 龙虎榜(lhb)Round5 已接入但 **comparison-only**(只记上榜事实+净买卖,无 effect 阈值;
        # 近5交易日窗口是 module-level prior 常量 DRAGON_LIST_LOOKBACK_TRADING_DAYS,非 governance)→ 仍不进 gov,
        # 与 forward_events(window=21 module 常量、无 gov 块)同例。转生产 sizing 时另起 governance 轮 + Gate A。
        for k in ("northbound", "margin", "lhb", "block_trade", "dragon_list"):
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
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertEqual(r["machine"]["holding_management_signal"], "clear_review")
        self.assertTrue(r["machine"]["blocked_add_required"])
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
_OFFICIAL_HIGH_CONFIRMED = copy.deepcopy(_OFFICIAL_HIGH)
_OFFICIAL_HIGH_CONFIRMED["regulatory_advisory"] = {"event_decisions": [{
    "event_fingerprint": event_fingerprint("600000.SH", _OFFICIAL_HIGH_CONFIRMED["events"][0]),
    "decision": "confirmed_material",
}]}
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
    holding_row_impact / clear_review / blocked_add / m67_advisory_veto / implemented(S3b 已收官,经合并引擎落持仓处置) / private_account。"""
    return _semantic_operation_impacts([_OFFICIAL_HIGH["events"][0]], None, False, AS_OF, "existing_holding")[0]


class SemanticAdvisoryImpactTests(unittest.TestCase):
    """4.2 第3轮: 候选行 semantic 统一成 advisory operation_impact(official 证据齐全 high → m67_advisory_veto;
    web downgrade → priority_down)。semantic 永 advisory / 非生产;web_llm 绝不 hard_veto。"""

    def test_official_high_emits_advisory_veto(self):
        r = build_m67_report(_good_input(semantic=_OFFICIAL_HIGH_CONFIRMED), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")               # advisory veto 仍落 操作=否决
        off = [i for i in _sem_impacts(r) if i["source_field"] == "semantic_official_high_confirmed"]
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
        r = build_m67_report(_good_input(semantic=_OFFICIAL_HIGH_CONFIRMED, semantic_web_llm=_WEB_RISK), AS_OF, "t")
        jsonschema.validate(r, _load(M67_SCHEMA))
        self.assertEqual(len(_sem_impacts(r)), 2)                         # official + web 各一条

    def test_held_topn_official_high_holding_advisory_not_veto(self):
        # S2 fix(R-...-S2-HOLDING-SEMANTIC-TOPN-RENDER-DRIFT): 持仓在 TopN(走 build_m67)+ official high →
        # 持有(不否决) + holding_row_impact clear_review(按 has_position scope,不依 builder),绝不进候选 hard veto。
        r = build_m67_report(_good_input(semantic=_OFFICIAL_HIGH_CONFIRMED, stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertEqual(r["machine"]["layer"]["hard_veto"], [])
        imp = [i for i in _sem_impacts(r) if i["source_field"] == "semantic_official_high_confirmed"][0]
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
        return build_m67_report(_good_input(semantic=_OFFICIAL_HIGH_CONFIRMED), AS_OF, "t")   # 候选 advisory-veto

    def test_guard7_advisory_veto_must_be_nonproduction(self):
        r = self._veto_report()
        [i for i in r["machine"]["operation_impact"]
         if i["source_field"] == "semantic_official_high_confirmed"][0]["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_semantic_official_cannot_be_promoted_to_production_hard_veto(self):
        r = self._veto_report()
        imp = [i for i in r["machine"]["operation_impact"]
               if i["source_field"] == "semantic_official_high_confirmed"][0]
        imp["veto_class"] = "production_hard_veto"
        imp["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_semantic_official_hard_veto_must_keep_advisory_veto_class(self):
        r = self._veto_report()
        imp = [i for i in r["machine"]["operation_impact"]
               if i["source_field"] == "semantic_official_high_confirmed"][0]
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
               if i["source_field"] == "semantic_official_high_confirmed"][0]
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
        r["machine"]["stateful_risk"] = {"position_state": "held"}        # 持仓 advisory impact 属于持仓报告(真 builder existing_holding ⟺ position_state=held)
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
        r = build_holding_report(self._held_inp(semantic=_OFFICIAL_HIGH_CONFIRMED), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")          # 持仓 semantic 绝不翻否决
        imp = [i for i in r["machine"]["operation_impact"]
               if i["source_field"] == "semantic_official_high_confirmed"][0]
        self.assertEqual(imp["visibility_shape"], "holding_row_impact")
        self.assertEqual(imp["holding_effect"], "clear_review")
        self.assertEqual(imp["new_entry_effect"], "none")
        self.assertTrue(imp["blocked_add_required"])
        self.assertEqual(imp["veto_class"], "m67_advisory_veto")
        self.assertFalse(imp["production_effect_enabled"])
        self.assertIsNone(imp["pending_successor_slice"])              # S3b 已承接完成
        self.assertEqual(imp["implementation_status"], "implemented")
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
        r = build_holding_report(self._held_inp(semantic=_OFFICIAL_HIGH_CONFIRMED), AS_OF, "t")
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


class FinancialQualityImpactTests(unittest.TestCase):
    """4.2 财报质量①(复用,comparison-only):候选行红旗(EGS 既有 ESP-Q 旗标 / 扣非净利同比<0)→ advisory priority_down
    operation_impact + 落 风控触发「财报质量对照」;零新取数、绝不 hard_veto/非生产、不改 EGS/选股/股数;无红旗不发;持仓不发(候选 only)。"""

    def _fq(self, **over):
        fq = {"roe": 12.0, "q0_dt_yoy": -25.0, "q0_profit_dedt": 1e8, "ttm_profit_dedt": 4e8,
              "q0_net_income": 1.5e8, "ttm_ocf_ratio": 0.6, "l2_flags": "ESP-Q"}
        fq.update(over)
        return fq

    def _fqimps(self, r):
        return [i for i in (r["machine"].get("operation_impact") or []) if i["source_field"] == "financial_quality"]

    def test_redflag_emits_priority_down_and_lands(self):
        r = build_m67_report(_good_input(financial_quality=self._fq()), AS_OF, "t")
        imps = self._fqimps(r)
        self.assertEqual(len(imps), 1)
        imp = imps[0]
        self.assertEqual((imp["new_entry_effect"], imp["veto_class"], imp["production_effect_enabled"]),
                         ("priority_down", "none", False))
        self.assertEqual((imp["visibility_shape"], imp["field_class"], imp["holding_effect"]),
                         ("candidate_row_impact", "structured", "none"))
        self.assertEqual(imp["evidence_ref"]["kind"], "lineage_key")
        self.assertIn("财报质量对照", r["m67"]["精简结论区"]["风控触发"])      # no-dangling 真落地
        validate_operation_impact_no_dangling(r)
        validate_m67_consistency(r)
        jsonschema.validate(r, _load(M67_SCHEMA))

    def test_esp_q_flag_alone_triggers(self):
        r = build_m67_report(_good_input(financial_quality=self._fq(q0_dt_yoy=10.0, l2_flags="ESP-Q")), AS_OF, "t")
        self.assertEqual(len(self._fqimps(r)), 1)        # 仅 ESP-Q(同比非负)→ 仍发(复用 EGS 既有判据)

    def test_yoy_negative_alone_triggers(self):
        r = build_m67_report(_good_input(financial_quality=self._fq(q0_dt_yoy=-5.0, l2_flags="")), AS_OF, "t")
        self.assertEqual(len(self._fqimps(r)), 1)        # 仅扣非同比<0(无 ESP-Q)→ 发(自然符号红旗)

    def test_no_redflag_no_impact(self):
        r = build_m67_report(_good_input(financial_quality=self._fq(q0_dt_yoy=10.0, l2_flags="")), AS_OF, "t")
        self.assertEqual(self._fqimps(r), [])            # 无红旗 → 不发(避免噪声)

    def test_absent_financial_quality_no_impact(self):
        self.assertEqual(self._fqimps(build_m67_report(_good_input(), AS_OF, "t")), [])   # 旧候选向后兼容零改动

    def test_comparison_only_isolation(self):
        base = build_m67_report(_good_input(), AS_OF, "t")["m67"]["table"]
        red = build_m67_report(_good_input(financial_quality=self._fq()), AS_OF, "t")["m67"]["table"]
        self.assertEqual((red["操作"], red["EGS分"], red["股数"]), (base["操作"], base["EGS分"], base["股数"]))

    def test_holding_no_financial_quality_impact(self):
        # 第一刀=候选 only:持仓(has_position)不发 financial_quality(持仓财报质量留后续刀)
        r = build_m67_report(_good_input(financial_quality=self._fq(), stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(self._fqimps(r), [])

    def test_guard_rejects_hard_veto_effect(self):
        r = build_m67_report(_good_input(financial_quality=self._fq()), AS_OF, "t")
        self._fqimps(r)[0]["new_entry_effect"] = "hard_veto"   # veto_class 保持 none → 专测 ⑮ never-hard-veto
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_guard_rejects_production_enabled(self):
        r = build_m67_report(_good_input(financial_quality=self._fq()), AS_OF, "t")
        self._fqimps(r)[0]["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_guard_rejects_missing_marker(self):
        r = build_m67_report(_good_input(financial_quality=self._fq()), AS_OF, "t")
        r["m67"]["精简结论区"]["风控触发"] = "无"        # 抹掉 marker
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_guard_rejects_holding_shape_mutation(self):
        # 候选报告但 impact 被改成持仓形态 → guard 拒(候选 only:须 candidate_row_impact/new_entry/public_tracked)
        r = build_m67_report(_good_input(financial_quality=self._fq()), AS_OF, "t")
        self._fqimps(r)[0]["visibility_shape"] = "holding_row_impact"
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)

    def test_guard_rejects_held_report_financial_quality(self):
        # Codex probe: 持仓(held)报告手构带 financial_quality(持仓 shape + private)→ guard 拒(持仓财报质量留后续刀,须单独审查)
        r = build_m67_report(_good_input(financial_quality=self._fq()), AS_OF, "t")
        r["machine"]["stateful_risk"] = {"position_state": "held"}
        imp = self._fqimps(r)[0]
        imp["visibility_shape"], imp["impact_scope"], imp["privacy_class"] = (
            "holding_row_impact", "existing_holding", "private_account")
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(r)


class HoldingDispositionS3bTests(unittest.TestCase):
    """S3b R1+R2: 持仓处置 结构化列 + severity 合并引擎(advisory · 不自动卖出 · 减仓价待 R3 · 操作 enum 不扩 · 仅持仓行)。"""

    def _imp(self, holding_effect="hold_watch", blocked=False):
        return {"source_field": "x", "field_class": "structured", "visibility_shape": "holding_row_impact",
                "impact_scope": "existing_holding", "new_entry_effect": "none", "holding_effect": holding_effect,
                "blocked_add_required": blocked, "veto_class": "none",
                "evidence_ref": {"kind": "lineage_key", "value": "x", "as_of": AS_OF},
                "m67_landing_surface": "x", "terminal_surface_target": "s3b_持仓处置_列+减仓价",
                "pending_successor_slice": None, "production_effect_enabled": False,
                "implementation_status": "implemented", "privacy_class": "private_account"}

    def _cand_imp(self, holding_effect="clear_review", blocked=False, source_field="x"):
        # 候选/公开 shape 却被篡改带上持仓效应——绝不应参与持仓处置合并(scope fail-closed 的对抗输入)。
        return {"source_field": source_field, "field_class": "structured", "visibility_shape": "candidate_row_impact",
                "impact_scope": "new_entry", "new_entry_effect": "none", "holding_effect": holding_effect,
                "blocked_add_required": blocked, "veto_class": "none",
                "evidence_ref": {"kind": "lineage_key", "value": "x", "as_of": AS_OF},
                "m67_landing_surface": "x", "terminal_surface_target": "already_structured",
                "pending_successor_slice": None, "production_effect_enabled": False,
                "implementation_status": "implemented", "privacy_class": "public_tracked"}

    def _breached_held_inp(self):
        """Make the trailing high post-entry; B1 must not rely on a pre-entry high."""
        inp = _good_input(stateful_risk=_held_state())
        inp["price_series"] = [
            {**row, "high": 3.10} if row["trade_date"] == "20260601" else dict(row)
            for row in inp["price_series"]
        ]
        return inp

    # ── 合并引擎(severity-max + blocked_add OR + anti-rescue)──
    def test_merge_severity_max(self):
        self.assertEqual(_merge_holding_disposition(
            [self._imp("hold_watch"), self._imp("clear_review"), self._imp("hold")])[0], "clear_review")

    def test_merge_order_reduce_over_hold_watch(self):
        self.assertEqual(_merge_holding_disposition([self._imp("hold_watch"), self._imp("reduce_review")])[0], "reduce_review")

    def test_merge_anti_rescue(self):
        # severity-max = anti-rescue:高信号不被正面/低信号压低
        self.assertEqual(_merge_holding_disposition(
            [self._imp("clear_review"), self._imp("hold"), self._imp("hold_watch")])[0], "clear_review")

    def test_merge_blocked_add_or(self):
        self.assertTrue(_merge_holding_disposition([self._imp("hold", False), self._imp("hold_watch", True)])[1])
        self.assertFalse(_merge_holding_disposition([self._imp("hold"), self._imp("hold_watch")])[1])

    def test_merge_empty_default_hold(self):
        self.assertEqual(_merge_holding_disposition([]), ("hold", False))
        self.assertEqual(_merge_holding_disposition(None), ("hold", False))

    def test_merge_ignores_none_effect(self):
        self.assertEqual(_merge_holding_disposition([self._imp("none"), self._imp("hold_watch")])[0], "hold_watch")

    # ── build 接线(held 报告)──
    def test_held_report_default_hold(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertEqual(r["m67"]["table"]["持仓处置"], "持有")        # 无 holding 信号 → 默认 持有
        self.assertIn("禁止加仓", r["m67"]["table"])
        self.assertEqual(r["machine"]["holding_management_signal"], "hold")
        validate_m67_consistency(r)
        jsonschema.validate(r, _load(M67_SCHEMA))

    def test_held_report_clear_review_disposition(self):
        # held 报告注入 clear_review + blocked 信号 → 持仓处置=建议清仓复核 + 禁止加仓
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        self.assertEqual(r["m67"]["table"]["持仓处置"], "建议清仓复核")
        self.assertTrue(r["m67"]["table"]["禁止加仓"])
        self.assertEqual(r["machine"]["holding_management_signal"], "clear_review")
        validate_m67_consistency(r)

    def test_candidate_no_disposition(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        self.assertNotIn("持仓处置", r["m67"]["table"])
        self.assertNotIn("禁止加仓", r["m67"]["table"])
        validate_m67_consistency(r)

    def test_apply_idempotent(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        first = (r["m67"]["table"]["持仓处置"], r["m67"]["table"]["禁止加仓"])
        _apply_holding_disposition(r)
        self.assertEqual((r["m67"]["table"]["持仓处置"], r["m67"]["table"]["禁止加仓"]), first)

    def test_held_holding_report_tier3(self):
        r = build_holding_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertIn("持仓处置", r["m67"]["table"])
        validate_m67_consistency(r)

    # ── validator(独立重算比对)──
    def test_validator_rejects_candidate_disposition(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["m67"]["table"]["持仓处置"] = "持有"        # 非持有行不得带
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_signal_mismatch(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["holding_management_signal"] = "clear_review"   # op_impacts 空 → 重算 hold,不符
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_disposition_label_mismatch(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["m67"]["table"]["持仓处置"] = "建议清仓复核"   # machine.signal=hold,标签不符
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_blocked_mismatch(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["m67"]["table"]["禁止加仓"] = True          # machine.blocked=False
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    # ── S3a 边界 / 共存 ──
    def test_s3a_boundary_no_reduce_price(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual((r["m67"]["table"]["入"], r["m67"]["table"]["股数"]), (None, None))   # 持仓不新开仓/不重算股数
        self.assertNotIn("减仓价", r["m67"]["table"])   # R3 才有
        self.assertNotIn("清仓价", r["m67"]["table"])

    def test_label_map_complete(self):
        # 映射覆盖全 severity 档 + hold(默认)
        for k in ("hold", "hold_watch", "reduce_review", "clear_review", "manual_review"):
            self.assertIn(k, _HOLDING_DISPOSITION_LABEL)

    # ── R-ASHORT-S3B-HOLDING-DISPOSITION-SCOPE-GUARD-GAP: 合并/校验 fail-closed on scope ──
    def test_merge_ignores_candidate_shape_holding_effect(self):
        # 候选 shape 即便带 clear_review+blocked → 不是持仓侧信号 → 不参与合并 → 默认 ('hold', False)
        self.assertEqual(_merge_holding_disposition([self._cand_imp("clear_review", True)]), ("hold", False))

    def test_merge_ignores_public_privacy_holding_shape(self):
        # holding shape/scope 但 public_tracked(非私密)→ 不算合法持仓信号(涉真实持仓须私密)
        imp = self._imp("clear_review", True)
        imp["privacy_class"] = "public_tracked"
        self.assertEqual(_merge_holding_disposition([imp]), ("hold", False))

    def test_validator_rejects_wrong_shape_forward_event_held(self):
        # held 报告手构 forward_event 伪装成 candidate shape + 带持仓效应 → ⑪ 持仓 shape 闭合拒(否则会污染持仓处置)
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        fe = self._cand_imp("hold_watch", True, source_field="forward_event_limit_unlock")
        r["machine"]["operation_impact"] = [fe]
        r["m67"]["精简结论区"]["风控触发"] = "未来已知事件 禁止加仓"
        r["m67"]["精简结论区"]["操作建议"] = "未来已知事件 禁止加仓"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_generic_candidate_holding_effect(self):
        # held 报告注入 generic(非 source-class)候选 shape 带 holding_effect=clear_review → 全局持仓效应 shape 闭合(a)直接拒
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._cand_imp("clear_review", blocked=False)]
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_generic_blocked_add_wrong_shape(self):
        # held 报告:generic 候选 shape 仅带 blocked_add(holding_effect=none)→ blocked 也算持仓效应 → 全局闭合(a)拒
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._cand_imp("none", blocked=True)]
        r["m67"]["精简结论区"]["风控触发"] = "禁止加仓"
        r["m67"]["精简结论区"]["操作建议"] = "禁止加仓"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_nonheld_generic_holding_effect(self):
        # 非持有(候选)报告:generic 候选 shape 带持仓效应 → 全局闭合拒(候选 shape 非持仓侧)
        r = build_m67_report(_good_input(), AS_OF, "t")              # 非 held
        r["machine"]["operation_impact"] = [self._cand_imp("clear_review", blocked=False)]
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_nonheld_holding_shaped_effect(self):
        # 非持有报告即便 impact 是合法持仓 shape(_is_held_signal True)但带持仓效应 → 全局闭合(b)拒(持仓效应仅持仓报告)
        r = build_m67_report(_good_input(), AS_OF, "t")              # 非 held
        imp = self._imp("clear_review", True)                        # holding_row_impact/existing_holding/private
        imp["source_field"] = "x"
        r["machine"]["operation_impact"] = [imp]
        r["m67"]["精简结论区"]["风控触发"] = "禁止加仓"
        r["m67"]["精简结论区"]["操作建议"] = "禁止加仓"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_nonheld_machine_signal_leak(self):
        # 非持有(候选)报告泄漏 machine.holding_management_signal/blocked_add_required → 拒(持仓处置仅持仓行)
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["machine"]["holding_management_signal"] = "clear_review"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)
        r2 = build_m67_report(_good_input(), AS_OF, "t")
        r2["machine"]["blocked_add_required"] = True
        with self.assertRaises(ValueError):
            validate_m67_consistency(r2)

    # ── S3b R3: 减仓价/清仓价/减仓比例 = advisory 价位(复用 S3a 损/盈一,不自动下单=R4)──
    def _clean_held_inp(self):
        # 非破位持仓(close 高于跟踪止损)→ S3a plan 有 stop+t1+t2,供 reduce_review 减仓价(=盈一)非 None 测试
        series = [{"trade_date": f"202606{i + 1:02d}", "high": 9.0 + i * 0.05,
                   "low": 8.9 + i * 0.05, "close": 9.0 + i * 0.05} for i in range(30)]
        return _good_input(stateful_risk=_held_state(), close=10.6, price_series=series)

    def _structural_resistance_held_inp(self):
        series = [{"high": 12.0, "low": 8.0, "close": 10.6} for _ in range(30)]
        return _good_input(stateful_risk=_held_state(), close=10.6, price_series=series)

    def _breached_held_inp(self):
        dates = ([f"202605{day:02d}" for day in range(19, 32)]
                 + [f"202606{day:02d}" for day in range(1, 18)])
        series = []
        for i, trade_date in enumerate(dates):
            row = {"high": 2.92, "low": 2.88, "close": 2.90,
                   "trade_date": trade_date}
            if i in (13, 14):
                row.update(high=3.10, low=2.88 if i == 13 else 2.87)
            series.append(row)
        return _good_input(stateful_risk=_held_state(), price_series=series)

    def test_r3_clear_review_clear_price_eq_s3a_stop(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        self.assertEqual(r["m67"]["table"]["清仓价"], plan["stop"])          # 清仓价 = S3a 损
        self.assertEqual(r["machine"]["clear_price"], plan["stop"])
        self.assertNotIn("减仓价", r["m67"]["table"])
        self.assertNotIn("减仓比例", r["m67"]["table"])
        validate_m67_consistency(r)
        jsonschema.validate(r, _load(M67_SCHEMA))

    def test_r3_reduce_review_reduce_price_eq_s3a_t1(self):
        r = build_m67_report(self._clean_held_inp(), AS_OF, "t")
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        self.assertFalse(plan["breached"])
        self.assertIsNotNone(plan["t1"])
        r["machine"]["operation_impact"] = [self._imp("reduce_review", blocked=True)]
        _apply_holding_disposition(r)
        self.assertEqual(r["m67"]["table"]["减仓价"], plan["t1"])            # 减仓价 = S3a 盈一
        self.assertEqual(r["m67"]["table"]["减仓比例"], _REDUCE_RATIO_ADVISORY)
        self.assertEqual(r["machine"]["reduce_price"], plan["t1"])
        self.assertNotIn("清仓价", r["m67"]["table"])
        validate_m67_consistency(r)
        jsonschema.validate(r, _load(M67_SCHEMA))

    def test_r3_hold_no_prices(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")   # 无 signal → hold
        _apply_holding_disposition(r)
        for k in ("减仓价", "清仓价", "减仓比例"):
            self.assertNotIn(k, r["m67"]["table"])
        validate_m67_consistency(r)

    def test_r3_breached_reduce_price_null_not_fabricated(self):
        # 破位 → plan.t1=None → reduce_review 减仓价=null(诚实不伪造),减仓比例仍 advisory
        r = build_m67_report(self._breached_held_inp(), AS_OF, "t")
        self.assertTrue(r["machine"]["entry_exit_size_star"]["plan"]["breached"])
        r["machine"]["operation_impact"] = [self._imp("reduce_review", blocked=True)]
        _apply_holding_disposition(r)
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        self.assertEqual(r["machine"]["holding_management_signal"], "clear_review")
        self.assertEqual(r["m67"]["table"]["清仓价"], plan["stop"])
        self.assertNotIn("减仓价", r["m67"]["table"])
        self.assertNotIn("减仓比例", r["m67"]["table"])
        validate_m67_consistency(r)

    def test_r3_validator_rejects_wrong_disposition_price(self):
        # clear_review 不得带 减仓价
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        r["m67"]["table"]["减仓价"] = 9.99
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r3_validator_rejects_clear_price_mismatch(self):
        # 清仓价 != S3a 损 → 拒(独立比对 S3a plan,不信任 builder)
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        r["m67"]["table"]["清仓价"] = (r["machine"]["entry_exit_size_star"]["plan"]["stop"] or 0) + 1.0
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r3_validator_rejects_nonheld_price(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["m67"]["table"]["清仓价"] = 5.0
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)
        r2 = build_m67_report(_good_input(), AS_OF, "t")
        r2["machine"]["reduce_price"] = 5.0
        with self.assertRaises(ValueError):
            validate_m67_consistency(r2)

    def test_r3_idempotent_signal_change_clears_stale(self):
        # signal clear_review→hold 重算清掉旧清仓价(幂等)
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        self.assertIn("清仓价", r["m67"]["table"])
        r["machine"]["operation_impact"] = []
        _apply_holding_disposition(r)
        self.assertNotIn("清仓价", r["m67"]["table"])
        self.assertNotIn("clear_price", r["machine"])
        validate_m67_consistency(r)

    def test_r3_s3a_levels_coexist_unchanged(self):
        # R3 价位与 S3a 损/盈一/盈二 两维共存:清仓价==损(引用同值),S3a 列不被 R3 改
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        s3a_stop = r["m67"]["table"]["损"]
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        self.assertEqual(r["m67"]["table"]["损"], s3a_stop)
        self.assertEqual(r["m67"]["table"]["清仓价"], s3a_stop)

    # ── R-ASHORT-S3B-R3-EXPLICIT-NULL-PRICE-GUARD-GAP: 显式 null vs 键缺失(no-dangling)──
    def test_r3_rejects_missing_reduce_price_key(self):
        # breached reduce(减仓价=null present)删 table.减仓价 + machine.reduce_price(留减仓比例)→ 键缺失拒
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("reduce_review", blocked=True)]
        _apply_holding_disposition(r)
        validate_m67_consistency(r)                          # 正常显式 null present 先过
        del r["m67"]["table"]["减仓价"]
        del r["machine"]["reduce_price"]
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r3_rejects_missing_clear_price_key(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        del r["m67"]["table"]["清仓价"]
        del r["machine"]["clear_price"]
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r3_rejects_missing_machine_null_with_table_null(self):
        # 删 machine.clear_price 但留 table.清仓价 → machine 键集不符拒
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        del r["machine"]["clear_price"]
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r3_rejects_stray_machine_null_wrong_disposition(self):
        # clear_review 混入 machine.reduce_price=None(present null)→ machine 键集多带拒
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        r["machine"]["reduce_price"] = None
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r3_rejects_nonheld_machine_price_null(self):
        # 非持有报告 machine.reduce_price=None(present null)→ 键存在即泄漏拒
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["machine"]["reduce_price"] = None
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    # ── S3b R4a: 到价提示 price_cross + 移保本 move_to_breakeven(within-week advisory;不改 disposition/操作/不自动卖/不改止损)──
    # 到价(_holding_active_alerts 纯函数:现价 vs R3 减仓价/清仓价,按 disposition)
    def test_r4a_alerts_reduce_reached(self):
        pc, mtb = _holding_active_alerts(10.0, "reduce_review", 9.0, None, None, None)
        self.assertEqual(pc, "reduce_price_reached")
        self.assertEqual(mtb, {"triggered": False, "breakeven_price": None})

    def test_r4a_alerts_reduce_not_reached(self):
        self.assertEqual(_holding_active_alerts(8.0, "reduce_review", 9.0, None, None, None)[0], "none")

    def test_r4a_alerts_reduce_price_none(self):
        self.assertEqual(_holding_active_alerts(10.0, "reduce_review", None, None, None, None)[0], "none")

    def test_r4a_alerts_clear_reached(self):
        self.assertEqual(_holding_active_alerts(5.0, "clear_review", None, 6.0, None, None)[0], "clear_price_reached")

    def test_r4a_alerts_clear_not_reached(self):
        self.assertEqual(_holding_active_alerts(7.0, "clear_review", None, 6.0, None, None)[0], "none")

    def test_r4a_alerts_other_disposition_no_cross(self):
        # hold/hold_watch/manual_review 无 R3 价位 → price_cross 恒 none(即便传入价位)
        for sig in ("hold", "hold_watch", "manual_review"):
            self.assertEqual(_holding_active_alerts(10.0, sig, 9.0, 9.0, None, None)[0], "none")

    # 移保本(1R = 成本价 − S3a plan.stop;仅 plan.stop<成本价 且 现价≥成本价+R)
    def test_r4a_breakeven_triggered(self):
        pc, mtb = _holding_active_alerts(10.0, "hold", None, None, 6.0, 8.0)   # R=2,阈值 8+2=10,现价≥10
        self.assertEqual(pc, "none")
        self.assertEqual(mtb, {"triggered": True, "breakeven_price": 8.0})

    def test_r4a_breakeven_not_reached(self):
        self.assertFalse(_holding_active_alerts(9.9, "hold", None, None, 6.0, 8.0)[1]["triggered"])   # 9.9<10

    def test_r4a_breakeven_stop_at_cost_not_triggered(self):
        # plan.stop==成本价 → R=0(非>0)→ 不触发(已无亏损风险,移保本无意义)
        self.assertFalse(_holding_active_alerts(12.0, "hold", None, None, 8.0, 8.0)[1]["triggered"])

    def test_r4a_breakeven_stop_above_cost_not_triggered(self):
        # plan.stop>成本价 → R<0 → 不触发
        self.assertFalse(_holding_active_alerts(12.0, "hold", None, None, 9.0, 8.0)[1]["triggered"])

    def test_r4a_breakeven_missing_inputs_not_triggered(self):
        for close, stop, cost in ((10.0, 6.0, None), (10.0, None, 8.0), (None, 6.0, 8.0)):
            self.assertFalse(_holding_active_alerts(close, "hold", None, None, stop, cost)[1]["triggered"])

    def test_r4a_alerts_nonfinite_safe(self):
        # NaN/bool 现价或价位 → 不触发(pre-flight F:非有限值安全门)
        nan = float("nan")
        self.assertEqual(_holding_active_alerts(nan, "reduce_review", 9.0, None, None, None)[0], "none")
        self.assertFalse(_holding_active_alerts(10.0, "hold", None, None, 6.0, nan)[1]["triggered"])
        self.assertEqual(_holding_active_alerts(True, "reduce_review", 9.0, None, None, None)[0], "none")   # bool 非数值

    # build 接线(held 报告)
    def test_r4a_held_fields_present_and_clean(self):
        # 默认 held(破位)→ 三字段就位;hold disposition → price_cross none;avg_cost<plan.stop(破位)→ 移保本不触发
        r = build_m67_report(self._breached_held_inp(), AS_OF, "t")
        self.assertIn("current_close", r["machine"])
        self.assertEqual(r["machine"]["price_cross"], "clear_price_reached")
        self.assertEqual(r["machine"]["holding_management_signal"], "clear_review")
        self.assertEqual(r["machine"]["move_to_breakeven"], {"triggered": False, "breakeven_price": None})
        validate_m67_consistency(r)
        jsonschema.validate(r, _load(M67_SCHEMA))

    def test_r4a_clear_review_breached_price_cross_reached(self):
        # 破位 held + clear_review → 清仓价=plan.stop≥现价 → price_cross=clear_price_reached(到价清仓=S3a 破位)
        r = build_m67_report(self._breached_held_inp(), AS_OF, "t")
        self.assertTrue(r["machine"]["entry_exit_size_star"]["plan"]["breached"])
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        self.assertEqual(r["machine"]["price_cross"], "clear_price_reached")
        validate_m67_consistency(r)

    def test_r4a_breakeven_integration_and_s3a_stop_unchanged(self):
        # 非破位 held,把成本价调到 plan.stop 与现价之间 → 移保本触发;**table.损 仍 = S3a plan.stop(R4a 不改止损,跨周收紧=R4b)**
        r = build_m67_report(self._clean_held_inp(), AS_OF, "t")
        stop = r["machine"]["entry_exit_size_star"]["plan"]["stop"]
        close = r["machine"]["current_close"]
        avg = round(stop + 0.4 * (close - stop), 2)
        r["machine"]["stateful_risk"]["position"]["avg_cost"] = avg
        _apply_holding_disposition(r)
        self.assertEqual(r["machine"]["move_to_breakeven"], {"triggered": True, "breakeven_price": avg})
        self.assertEqual(r["m67"]["table"]["损"], stop)
        validate_m67_consistency(r)

    def test_r4a_holding_report_tier3_fields(self):
        r = build_holding_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        for k in ("current_close", "price_cross", "move_to_breakeven"):
            self.assertIn(k, r["machine"])
        validate_m67_consistency(r)

    def test_r4a_apply_idempotent(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["operation_impact"] = [self._imp("clear_review", blocked=True)]
        _apply_holding_disposition(r)
        snap = (r["machine"]["price_cross"], dict(r["machine"]["move_to_breakeven"]))
        _apply_holding_disposition(r)
        self.assertEqual((r["machine"]["price_cross"], r["machine"]["move_to_breakeven"]), snap)

    # validator(独立重算 + current_close provenance bind)
    def test_r4a_validator_rejects_missing_current_close(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        del r["machine"]["current_close"]
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r4a_validator_rejects_current_close_mismatch_price(self):
        # current_close 与 现价与成本 显示价不符 → provenance bind 拒(防判定基准与用户可见价脱节)
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["current_close"] = (r["machine"]["current_close"] or 0) + 5.0
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r4a_validator_rejects_price_cross_mismatch(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["price_cross"] = "reduce_price_reached"   # 默认 hold → 重算 none,不符
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r4a_validator_rejects_move_to_breakeven_mismatch(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        r["machine"]["move_to_breakeven"] = {"triggered": True, "breakeven_price": 1.0}   # 破位实为 not triggered
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r4a_validator_rejects_nonheld_r4a_keys(self):
        for key, val in (("current_close", 2.9), ("price_cross", "none"),
                         ("move_to_breakeven", {"triggered": False, "breakeven_price": None})):
            r = build_m67_report(_good_input(), AS_OF, "t")     # 候选(非持有)
            r["machine"][key] = val
            with self.assertRaises(ValueError):
                validate_m67_consistency(r)

    # render(_active_alert_line 用户可见;无 advisory→None)
    def test_r4a_render_active_alert_line(self):
        none_mtb = {"triggered": False, "breakeven_price": None}
        self.assertIsNone(_active_alert_line({"machine": {"price_cross": "none", "move_to_breakeven": none_mtb}}))
        self.assertIn("已到清仓价", _active_alert_line({"machine": {"price_cross": "clear_price_reached", "move_to_breakeven": none_mtb}}))
        self.assertIn("已到减仓价", _active_alert_line({"machine": {"price_cross": "reduce_price_reached", "move_to_breakeven": none_mtb}}))
        self.assertIn("成本价 8.0", _active_alert_line({"machine": {"price_cross": "none", "move_to_breakeven": {"triggered": True, "breakeven_price": 8.0}}}))


class HoldingRatchetS3bR4bTests(unittest.TestCase):
    """S3b R4b: 跨周持久收紧 ratchet(stop 只升不降 / disposition 只升档不降 / 滚动到价 / re-entry 重置 / bootstrap / 同周幂等 / 私密 sidecar IO)。"""

    def _tw(self, **over):
        d = {"ts_code": "600000.SH", "entry_date": "20260601", "as_of": "20260115", "close": 10.0,
             "stop": 8.0, "breakeven": None, "disposition": "hold", "reduce_price": 11.0, "clear_price": 8.0}
        d.update(over)
        return d

    def _lw(self, **over):
        d = {"ts_code": "600000.SH", "entry_date": "20260601", "last_as_of": "20260108",
             "ratcheted_stop": 9.0, "last_disposition": "hold", "last_reduce_price": 12.0,
             "last_clear_price": 9.0, "week_count": 1, "cross_week_price_cross": "none", "bootstrap": True}
        d.update(over)
        return d

    # ── 纯函数 _holding_ratchet ──
    def test_r4b_bootstrap(self):
        mr, row = _holding_ratchet(self._tw(stop=8.0, breakeven=None, disposition="hold"), None)
        self.assertEqual((mr["week_count"], mr["bootstrap"], mr["ratcheted_stop"], mr["cross_week_price_cross"]),
                         (1, True, 8.0, "none"))
        self.assertEqual(set(row), {"ts_code", "entry_date", "last_as_of", "ratcheted_stop", "last_disposition",
                                    "last_reduce_price", "last_clear_price", "week_count", "cross_week_price_cross", "bootstrap"})
        self.assertEqual(row["last_reduce_price"], 11.0)       # 本周 reduce_price 供下周滚动
        self.assertEqual(row["last_clear_price"], 8.0)         # = ratcheted_stop

    def test_r4b_reentry_reset(self):
        mr, _ = _holding_ratchet(self._tw(entry_date="20260610"), self._lw(entry_date="20260601", week_count=5))
        self.assertEqual((mr["week_count"], mr["bootstrap"]), (1, True))   # 换仓重置

    def test_r4b_stop_only_up_keeps_last(self):
        mr, _ = _holding_ratchet(self._tw(stop=8.0, breakeven=None, as_of="20260115"),
                                 self._lw(ratcheted_stop=10.0, last_as_of="20260108"))
        self.assertEqual(mr["ratcheted_stop"], 10.0)          # 本周 8<上周 10 → 保留 10(只升不降)
        self.assertEqual(mr["week_count"], 2)

    def test_r4b_stop_rises(self):
        mr, _ = _holding_ratchet(self._tw(stop=11.0, breakeven=None), self._lw(ratcheted_stop=10.0))
        self.assertEqual(mr["ratcheted_stop"], 11.0)          # 本周 11>上周 10 → 升

    def test_r4b_breakeven_feeds_stop(self):
        mr, _ = _holding_ratchet(self._tw(stop=6.0, breakeven=8.0), self._lw(ratcheted_stop=5.0))
        self.assertEqual(mr["ratcheted_stop"], 8.0)           # eff=max(6,8)=8 > 上周 5

    def test_r4b_disposition_only_up(self):
        mr, _ = _holding_ratchet(self._tw(disposition="hold"), self._lw(last_disposition="clear_review"))
        self.assertEqual(mr["ratcheted_disposition"], "clear_review")   # 本周 hold 不降上周 clear_review
        mr2, _ = _holding_ratchet(self._tw(disposition="clear_review"), self._lw(last_disposition="hold"))
        self.assertEqual(mr2["ratcheted_disposition"], "clear_review")  # 升档

    def test_r4b_cross_week_reduce_reached(self):
        mr, _ = _holding_ratchet(self._tw(close=13.0, stop=8.0), self._lw(ratcheted_stop=10.0, last_reduce_price=12.0))
        self.assertEqual(mr["cross_week_price_cross"], "reduce_price_reached")   # 现价13≥上周减仓价12

    def test_r4b_cross_week_clear_reached(self):
        mr, _ = _holding_ratchet(self._tw(close=9.0, stop=8.0), self._lw(ratcheted_stop=10.0, last_reduce_price=12.0))
        self.assertEqual(mr["cross_week_price_cross"], "clear_price_reached")    # 现价9<减仓价12 且 ≤ratcheted_stop10

    def test_r4b_same_week_idempotent(self):
        lw = self._lw(last_as_of="20260115", week_count=3, ratcheted_stop=10.0,
                      last_disposition="clear_review", cross_week_price_cross="reduce_price_reached", bootstrap=False)
        mr, row = _holding_ratchet(self._tw(as_of="20260115"), lw)
        self.assertEqual(mr["week_count"], 3)                 # 同周 re-run 不增
        self.assertEqual(mr["ratcheted_disposition"], "clear_review")
        self.assertEqual(mr["cross_week_price_cross"], "reduce_price_reached")
        self.assertEqual(row, lw)                              # row 原样

    def test_r4b_week_count_increments(self):
        mr, _ = _holding_ratchet(self._tw(as_of="20260115"), self._lw(week_count=4, last_as_of="20260108"))
        self.assertEqual(mr["week_count"], 5)

    # ── _severity_max_disposition ──
    def test_r4b_severity_max(self):
        self.assertEqual(_severity_max_disposition("hold", "clear_review"), "clear_review")
        self.assertEqual(_severity_max_disposition("reduce_review", "hold_watch"), "reduce_review")
        self.assertEqual(_severity_max_disposition("hold", "hold"), "hold")
        self.assertEqual(_severity_max_disposition("bogus", "hold_watch"), "hold_watch")   # 非法按 hold(最低)

    # ── _ratchet_report_error(within-report 弱不变式)──
    def _mc_with_ratchet(self, ratchet, plan_stop=8.0, breakeven=None, disp="hold", close=10.0):
        return {"entry_exit_size_star": {"plan": {"stop": plan_stop}},
                "move_to_breakeven": {"triggered": breakeven is not None, "breakeven_price": breakeven},
                "holding_management_signal": disp, "current_close": close, "ratchet": ratchet}

    def _good_ratchet(self, **over):
        d = {"ratcheted_stop": 9.0, "ratcheted_disposition": "hold", "week_count": 2,
             "cross_week_price_cross": "none", "bootstrap": False}
        d.update(over)
        return d

    def test_r4b_report_error_valid_none(self):
        self.assertIsNone(_ratchet_report_error(self._mc_with_ratchet(self._good_ratchet())))

    def test_r4b_report_error_no_ratchet(self):
        self.assertIsNone(_ratchet_report_error({"entry_exit_size_star": {"plan": {"stop": 8.0}}}))

    def test_r4b_report_error_missing_key(self):
        r = self._good_ratchet()
        del r["week_count"]
        self.assertIsNotNone(_ratchet_report_error(self._mc_with_ratchet(r)))

    def test_r4b_report_error_stop_below_eff(self):
        # ratcheted_stop=7 < 本周 eff_stop=max(plan8, be9)=9 → 错(只升不降)
        mc = self._mc_with_ratchet(self._good_ratchet(ratcheted_stop=7.0), plan_stop=8.0, breakeven=9.0)
        self.assertIsNotNone(_ratchet_report_error(mc))

    def test_r4b_report_error_disposition_below(self):
        # ratcheted_disposition=hold 但本周 disposition=clear_review → 错(只升档不降)
        mc = self._mc_with_ratchet(self._good_ratchet(ratcheted_disposition="hold"), disp="clear_review")
        self.assertIsNotNone(_ratchet_report_error(mc))

    def test_r4b_report_error_clear_inconsistent(self):
        # cross_week=clear_price_reached 但 现价12 > ratcheted_stop9 → 错
        mc = self._mc_with_ratchet(self._good_ratchet(cross_week_price_cross="clear_price_reached", ratcheted_stop=9.0), close=12.0)
        self.assertIsNotNone(_ratchet_report_error(mc))

    def test_r4b_report_error_week_count(self):
        self.assertIsNotNone(_ratchet_report_error(self._mc_with_ratchet(self._good_ratchet(week_count=0))))

    # ── validate_m67_consistency 集成 ──
    def test_r4b_validator_held_with_ratchet_passes(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        plan_stop = r["machine"]["entry_exit_size_star"]["plan"]["stop"]
        r["machine"]["ratchet"] = self._good_ratchet(ratcheted_stop=plan_stop, week_count=1)
        validate_m67_consistency(r)
        jsonschema.validate(r, _load(M67_SCHEMA))

    def test_r4b_validator_held_bad_ratchet_raises(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        plan_stop = r["machine"]["entry_exit_size_star"]["plan"]["stop"]
        r["machine"]["ratchet"] = self._good_ratchet(ratcheted_stop=(plan_stop or 0) - 5.0)   # < 本周 eff stop
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r4b_validator_nonheld_ratchet_raises(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["machine"]["ratchet"] = self._good_ratchet()
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    # ── pipeline IO(load/apply/save;私密 sidecar)──
    def _held_weekly(self):
        return {"reports": [build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")]}

    def test_r4b_pipeline_bootstrap_and_roundtrip(self):
        import os
        import tempfile
        w = self._held_weekly()
        state = _apply_holding_ratchet(w, {}, AS_OF)
        rt = w["reports"][0]["machine"]["ratchet"]
        self.assertEqual((rt["week_count"], rt["bootstrap"]), (1, True))
        key = _holding_ratchet_key("600000.SH", "20260601")
        self.assertIn(key, state)
        path = os.path.join(tempfile.mkdtemp(), "ratchet_state.json")
        save_holding_ratchet(path, state, AS_OF, "t")               # 过 schema
        self.assertEqual(load_holding_ratchet(path), state)         # roundtrip 相等

    def test_r4b_pipeline_idempotent_same_week(self):
        w = self._held_weekly()
        state = _apply_holding_ratchet(w, {}, AS_OF)
        snap = {k: dict(v) for k, v in state.items()}
        w2 = self._held_weekly()
        state2 = _apply_holding_ratchet(w2, state, AS_OF)           # 同 as_of re-run
        self.assertEqual(state2, snap)                              # 幂等:week_count 不增
        self.assertEqual(w2["reports"][0]["machine"]["ratchet"]["week_count"], 1)

    def test_r4b_pipeline_persisted_disposition_cannot_downgrade(self):
        # Required ②(a):上周 clear_review + 本周合并 hold → machine 与 sidecar 都只升不降。
        w = self._held_weekly()
        report = w["reports"][0]
        stop = report["machine"]["entry_exit_size_star"]["plan"]["stop"]
        key = _holding_ratchet_key("600000.SH", "20260601")
        previous = {key: self._lw(ratcheted_stop=stop, last_disposition="clear_review",
                                  last_clear_price=stop, last_as_of="20260610")}
        state = _apply_holding_ratchet(w, previous, AS_OF)
        self.assertEqual(report["machine"]["ratchet"]["ratcheted_disposition"], "clear_review")
        self.assertEqual(state[key]["last_disposition"], "clear_review")

    def test_r4b_pipeline_breach_escalates_disposition_and_persists(self):
        # Required ②(b):上周 hold + 本周 ratchet 使 close 破位 → 正常升到 clear_review 且不误拒。
        w = self._held_weekly()
        report = w["reports"][0]
        self.assertEqual(report["machine"]["holding_management_signal"], "hold")
        close = report["machine"]["current_close"]
        key = _holding_ratchet_key("600000.SH", "20260601")
        previous = {key: self._lw(ratcheted_stop=close + 0.5, last_disposition="hold",
                                  last_clear_price=close + 0.5, last_as_of="20260610")}
        state = _apply_holding_ratchet(w, previous, AS_OF)
        self.assertEqual(report["machine"]["ratchet"]["ratcheted_disposition"], "clear_review")
        self.assertEqual(state[key]["last_disposition"], "clear_review")

    def test_r4b_pipeline_writeback_rejects_injected_stop_downgrade(self):
        # Required ② reverse:绕过纯函数的 max，植入一个低于 sidecar 的 row，写回门必须有牙。
        w = self._held_weekly()
        report = w["reports"][0]
        plan_stop = report["machine"]["entry_exit_size_star"]["plan"]["stop"]
        key = _holding_ratchet_key("600000.SH", "20260601")
        previous_stop = plan_stop + 0.5
        previous = {key: self._lw(ratcheted_stop=previous_stop, last_clear_price=previous_stop,
                                  last_as_of="20260610")}
        injected_stop = plan_stop + 0.1
        injected_machine = {"ratcheted_stop": injected_stop, "ratcheted_disposition": "hold",
                            "week_count": 2, "cross_week_price_cross": "none", "bootstrap": False}
        injected_row = self._lw(ratcheted_stop=injected_stop, last_clear_price=injected_stop,
                                last_as_of=AS_OF)
        with patch("runners.a_short_phase5_engine._holding_ratchet",
                   return_value=(injected_machine, injected_row)):
            with self.assertRaisesRegex(ValueError, "跨周止损下降"):
                _apply_holding_ratchet(w, previous, AS_OF)
        self.assertEqual(previous[key]["ratcheted_stop"], previous_stop)

    def test_r4b_pipeline_writeback_rejects_injected_disposition_downgrade(self):
        # Required ② reverse:直接篡改 engine 输出为 hold，不能绕过写回前的跨周 anti-rescue。
        w = self._held_weekly()
        report = w["reports"][0]
        plan_stop = report["machine"]["entry_exit_size_star"]["plan"]["stop"]
        key = _holding_ratchet_key("600000.SH", "20260601")
        previous = {key: self._lw(ratcheted_stop=plan_stop, last_disposition="clear_review",
                                  last_clear_price=plan_stop, last_as_of="20260610")}
        from runners import a_short_phase5_engine as engine
        real_holding_ratchet = engine._holding_ratchet

        def corrupt_disposition(this_week, last_week):
            machine, row = real_holding_ratchet(this_week, last_week)
            machine["ratcheted_disposition"] = "hold"
            row["last_disposition"] = "hold"
            return machine, row

        with patch("runners.a_short_phase5_engine._holding_ratchet",
                   side_effect=corrupt_disposition):
            with self.assertRaisesRegex(ValueError, "跨周降档"):
                _apply_holding_ratchet(w, previous, AS_OF)
        self.assertEqual(previous[key]["last_disposition"], "clear_review")

    def test_r4b_pipeline_pit_future_rejected(self):
        w = self._held_weekly()
        bad = {_holding_ratchet_key("600000.SH", "20260601"):
               {"ts_code": "600000.SH", "entry_date": "20260601", "last_as_of": "20991231",
                "ratcheted_stop": 9.0, "last_disposition": "hold", "last_reduce_price": None,
                "last_clear_price": 9.0, "week_count": 1, "cross_week_price_cross": "none", "bootstrap": True}}
        with self.assertRaises(ValueError):
            _apply_holding_ratchet(w, bad, AS_OF)                   # 未来态 PIT 拒

    def test_r4b_pipeline_no_entry_date_skipped(self):
        w = self._held_weekly()
        w["reports"][0]["machine"]["stateful_risk"]["position"].pop("entry_date", None)
        _apply_holding_ratchet(w, {}, AS_OF)
        self.assertNotIn("ratchet", w["reports"][0]["machine"])     # 无稳定身份 → 跳过

    def test_r4b_pipeline_nonheld_noop(self):
        w = {"reports": [build_m67_report(_good_input(), AS_OF, "t")]}   # 候选(非持有)
        state = _apply_holding_ratchet(w, {}, AS_OF)
        self.assertEqual(state, {})
        self.assertNotIn("ratchet", w["reports"][0]["machine"])

    # ── sidecar 读入层 fail-closed(R-ASHORT-S3B-R4B-RATCHET-SIDECAR-DUPLICATE-PIT-BYPASS)──
    def _row(self, **over):
        d = {"ts_code": "600000.SH", "entry_date": "20260601", "last_as_of": "20260610",
             "ratcheted_stop": 9.0, "last_disposition": "hold", "last_reduce_price": None,
             "last_clear_price": 9.0, "week_count": 1, "cross_week_price_cross": "none", "bootstrap": True}
        d.update(over)
        return d

    def _write_sidecar(self, holdings, as_of="20260617"):
        import json as _json
        import os
        import tempfile
        doc = {"schema_name": "a_short_holding_ratchet", "schema_version": "1.0.0", "generated_at": "t",
               "as_of": as_of, "boundary": {"production": False, "comparison_only": True, "advisory_only": True},
               "holdings": holdings}
        path = os.path.join(tempfile.mkdtemp(), "rt.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(doc, f)
        return path

    def test_r4b_load_rejects_duplicate_key_hiding_future(self):
        # 重复 (ts_code,entry_date),首行藏未来 last_as_of → dict 折叠前拒(否则后一行静默覆盖、藏未来行绕 PIT)
        path = self._write_sidecar([self._row(last_as_of="20991231"), self._row(last_as_of="20260610")])
        with self.assertRaises(ValueError):
            load_holding_ratchet(path)

    def test_r4b_load_rejects_row_future_envelope(self):
        # 行 last_as_of(20991231)> envelope as_of(20260617)→ load 时 PIT envelope 拒
        path = self._write_sidecar([self._row(last_as_of="20991231")], as_of="20260617")
        with self.assertRaises(ValueError):
            load_holding_ratchet(path)

    def test_r4b_load_accepts_unique_valid(self):
        # 反向:唯一 + last_as_of ≤ as_of 仍正常 load(不误拒合法 sidecar)
        path = self._write_sidecar([self._row(ts_code="600000.SH"), self._row(ts_code="600001.SZ")], as_of="20260617")
        self.assertEqual(len(load_holding_ratchet(path)), 2)

    def test_r4b_save_rejects_duplicate_rows(self):
        # writer 对称 fail-closed:两个不同 dict key 映射到同 (ts_code,entry_date) → save 拒
        import os
        import tempfile
        state = {"a": self._row(), "b": self._row()}   # 同 (600000.SH,20260601)
        with self.assertRaises(ValueError):
            save_holding_ratchet(os.path.join(tempfile.mkdtemp(), "rt.json"), state, "20260617", "t")

    # ── ratcheted_stop=null 在本周有效 stop 时跳过不变式(R-ASHORT-S3B-R4B-RATCHET-INVARIANT-GUARD-GAP)+ save PIT envelope ──
    def test_r4b_report_error_null_stop_with_valid_eff(self):
        # 本周有效 stop(plan 3.05)但 ratcheted_stop=null → 拒(ratchet 必随本周止损落地,不得 null)
        mc = self._mc_with_ratchet(self._good_ratchet(ratcheted_stop=None), plan_stop=3.05, breakeven=None)
        self.assertIsNotNone(_ratchet_report_error(mc))

    def test_r4b_report_error_clear_null_stop(self):
        # clear_price_reached 但 ratcheted_stop=null(本周无 stop)→ 拒(到价清仓需有效跨周止损;同类不变式跳过)
        mc = self._mc_with_ratchet(self._good_ratchet(ratcheted_stop=None, cross_week_price_cross="clear_price_reached"),
                                   plan_stop=None, breakeven=None)
        self.assertIsNotNone(_ratchet_report_error(mc))

    def test_r4b_report_error_null_stop_no_eff_ok(self):
        # 反向:本周无 effective_stop(plan/breakeven 皆无)+ ratcheted_stop=null + cw none → 合法(不过度拒)
        mc = self._mc_with_ratchet(self._good_ratchet(ratcheted_stop=None, cross_week_price_cross="none"),
                                   plan_stop=None, breakeven=None)
        self.assertIsNone(_ratchet_report_error(mc))

    def test_r4b_validator_held_null_stop_with_valid_plan_raises(self):
        # Codex 探针:held 报告本周有效 plan.stop 但 machine.ratchet.ratcheted_stop=null → validate_m67_consistency 拒
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertIsNotNone(r["machine"]["entry_exit_size_star"]["plan"]["stop"])
        r["machine"]["ratchet"] = self._good_ratchet(ratcheted_stop=None)
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_r4b_save_rejects_future_envelope(self):
        # save-time PIT envelope:行 last_as_of(20991231)> 写回 as_of(20260617)→ save 拒(reader/writer 对称)
        import os
        import tempfile
        state = {"a": self._row(last_as_of="20991231")}
        with self.assertRaises(ValueError):
            save_holding_ratchet(os.path.join(tempfile.mkdtemp(), "rt.json"), state, "20260617", "t")

    def test_r4b_write_m67_rejects_null_stop(self):
        # Codex 探针:官方写边界 write_m67_report(engine,内含 validate_m67_consistency)对 held 报告本周有效 plan.stop 但 ratcheted_stop=null 也须拒
        import os
        import tempfile
        from runners.a_short_phase5_engine import write_m67_report
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertIsNotNone(r["machine"]["entry_exit_size_star"]["plan"]["stop"])
        r["machine"]["ratchet"] = self._good_ratchet(ratcheted_stop=None)                # 本周有效 stop 但 ratchet null
        with self.assertRaises(ValueError):
            write_m67_report(r, os.path.join(tempfile.mkdtemp(), "m67.json"))

    # ── render _ratchet_line ──
    def test_r4b_render_ratchet_line(self):
        self.assertIsNone(_ratchet_line({"machine": {}}))
        line = _ratchet_line({"machine": {"ratchet": {"ratcheted_stop": 9.5, "ratcheted_disposition": "hold",
                              "week_count": 3, "cross_week_price_cross": "reduce_price_reached", "bootstrap": False}}})
        self.assertIn("第3周", line)
        self.assertIn("建议保护止损 9.5", line)
        self.assertIn("已达上周减仓价", line)


class RegistrySchemaMutationTests(unittest.TestCase):
    """P1(Codex Slice5):schema contract 本身须拒未来坏 registry(不只循环当前 example):both / 持仓侧公开形态 由 schema 焊;
    field_id 唯一由 Python 焊(draft-07 表达不了数组内字段唯一)。"""

    def setUp(self):
        self.schema = _load(REG_SCHEMA)
        self.example = _load(REG_EXAMPLE)

    def test_operation_impact_target_both_rejected(self):
        bad = copy.deepcopy(self.example)
        bad["fields"][0]["operation_impact_target"] = "both"   # 去 enum 后 → schema 拒
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_existing_holding_candidate_public_shape_rejected(self):
        bad = copy.deepcopy(self.example)
        src = next(f for f in bad["fields"] if f["operation_impact_target"] != "existing_holding")
        row = copy.deepcopy(src)
        row["field_id"] = "synthetic_existing_holding_wrong_shape"
        row["operation_impact_target"] = "existing_holding"
        row["visibility_shape"] = "candidate_row_impact"   # 持仓侧却用候选形态 → existing_holding if-then 拒
        row["privacy_class"] = "public_tracked"
        bad["fields"].append(row)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_duplicate_field_id_python_uniqueness(self):
        ids = [f["field_id"] for f in self.example["fields"]]
        self.assertEqual(len(ids), len(set(ids)), "example field_id 必须唯一")
        dup = ids + [ids[0]]
        self.assertTrue([i for i in set(dup) if dup.count(i) > 1])   # field_id 唯一 draft-07 焊不了 → Python 检查兜


if __name__ == "__main__":
    unittest.main()
