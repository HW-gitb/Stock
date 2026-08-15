"""持仓恒列入 M6.7 — S1 测试(adapter / _build_holdings Tier 路由 / render 分区 / main 集成).

矩阵(设计 §19.4 + §10.2.10):无 account 旧流程不变 / 持仓不在 top-N 也进 M6.7 / Tier-1 去重 /
Tier-2 复用 egs_full / Tier-3 不伪造 EGS 分(render 显未核查)/ 无价停牌→人工管理不炸轮 /
egs_full adapter 表头校验 + ST/停牌派生 / 4.3-D warning 渲染 / 分区显示。
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_egs_full_adapter import (load_egs_full, egs_full_row_to_candidate,  # noqa: E402
                                             EGS_FULL_REQUIRED_COLUMNS)
from engine.a_short_run_revision import public_revision_root, sha256_file  # noqa: E402
from runners.a_short_weekly_pipeline import (_build_holdings, main,  # noqa: E402
                                             _reject_nonprivate_account_output_path,
                                             _is_account_output_git_ignored)
from engine.a_short_regulatory_advisory import event_fingerprint, holding_universe_digest  # noqa: E402
import os  # noqa: E402
from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402
from tests.test_a_short_weekly_pipeline import (AS_OF, _analysis_input, _ai_candidate,  # noqa: E402
                                                _account, _feed, _series, _write_account)

PDT = AS_OF   # price_data_through (candidate clock) used by holdings injection tests


def _series_bars(n=25):
    return [{"open": 10.0, "high": 10.3, "low": 9.7, "close": 10.0 + (i % 3) * 0.1, "vol": 1000 + i}
            for i in range(n)]


def _egs_full_row(ts_code="600519.SH", name="贵州茅台", final_score="71.5", **over):
    row = {c: "" for c in EGS_FULL_REQUIRED_COLUMNS}
    row.update({"ts_code": ts_code, "name": name, "close": "1620.0",
                "avg_amount_5d": "2e8", "avg_amount_20d": "2e8",
                "esp_score": "55.0", "l4_score": "70.0", "final_score": final_score,
                "is_lock": "False", "is_breakout": "False", "vol_confirm": "True",
                "has_crash_veto": "False", "overheat_flag": "False", "chasing_high": "False",
                "reduce_deduct": "0", "l1_name": "食品饮料", "l2_name": "白酒", "list_status": "L"})
    row.update(over)
    return row


def _held_acct(codes_shares):
    a = copy.deepcopy(_account())
    a["positions"] = [{"ts_code": c, "name": "持仓", "shares": s, "avg_cost": 9.5,
                       "entry_date": "20260601", "stop_loss": 9.0, "take_profit_1": None,
                       "take_profit_2": None, "last_exit_date": None, "last_exit_reason": None}
                      for c, s in codes_shares]
    return a


def _holding_confirmation(bundle, ts_code, event, *, snapshot_digest=None, universe_digest=None):
    positions = bundle["account"]["positions"]
    return {
        "schema_name": "a_short_regulatory_holding_confirmation",
        "schema_version": "1.0.0",
        "as_of": AS_OF,
        "account_snapshot_digest": snapshot_digest or bundle["snapshot_digest"],
        "holding_universe_digest": universe_digest or holding_universe_digest(positions),
        "confirmations": [{
            "ts_code": ts_code,
            "event_fingerprint": event_fingerprint(ts_code, event),
            "decision": "confirmed_material",
            "reviewed_at": "2026-06-09T09:30:00+08:00",
            "note": "Official holding event checked manually.",
        }],
        "boundary": {
            "advisory_only": True,
            "modifies_egs_or_rule6": False,
            "automates_order": False,
            "private_account_only": True,
        },
    }


# ── egs_full adapter ──────────────────────────────────────────────────────────
class EgsFullAdapterTests(unittest.TestCase):
    def test_load_missing_file_returns_empty(self):
        self.assertEqual(load_egs_full("20990101"), {})        # 不存在 → {}(诚实降级,非错误)

    def test_load_and_header_validation(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "result" / "a_short" / "20260612"
            d.mkdir(parents=True)
            (d / "egs_full_20260612.csv").write_text(
                ",".join(EGS_FULL_REQUIRED_COLUMNS) + "\n"
                + ",".join(_egs_full_row()[c] for c in EGS_FULL_REQUIRED_COLUMNS) + "\n",
                encoding="utf-8")
            m = load_egs_full("20260612", root=td)
            self.assertIn("600519.SH", m)
            # 缺必需列 → ValueError(契约漂移,拒绝静默错位)
            d2 = Path(td) / "result" / "a_short" / "20260613"
            d2.mkdir(parents=True)
            (d2 / "egs_full_20260613.csv").write_text(
                "ts_code,name\n600000.SH,x\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_egs_full("20260613", root=td)

    def test_selected_revision_requires_bound_official_full_rank(self):
        with tempfile.TemporaryDirectory() as td:
            revision = "a" * 32
            root = Path(td)
            bundle = public_revision_root(root, "20260614", revision)
            bundle.mkdir(parents=True)
            full = bundle / "egs_full_20260614.csv"
            full.write_text(
                ",".join(EGS_FULL_REQUIRED_COLUMNS) + "\n"
                + ",".join(_egs_full_row()[c] for c in EGS_FULL_REQUIRED_COLUMNS) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(FileNotFoundError):
                load_egs_full("20260614", root=root, run_revision_id=revision)
            marker = bundle / "official_publish.json"
            marker.write_text(json.dumps({
                "stage_status": "complete",
                "trade_date": "20260614",
                "files": {"full_rank": {"path": full.name, "sha256": "0" * 64}},
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_egs_full("20260614", root=root, run_revision_id=revision)
            marker.write_text(json.dumps({
                "stage_status": "complete",
                "trade_date": "20260614",
                "files": {"full_rank": {"path": full.name, "sha256": sha256_file(full)}},
            }), encoding="utf-8")
            self.assertIn("600519.SH", load_egs_full(
                "20260614", root=root, run_revision_id=revision
            ))

    def test_row_to_candidate_maps_real_fields(self):
        c = egs_full_row_to_candidate(_egs_full_row(final_score="80.1"))
        self.assertEqual(c["scores"]["final_score"], 80.1)
        self.assertTrue(c["derived_flags"]["vol_confirm"])
        self.assertFalse(c["derived_flags"]["has_crash_veto"])

    def test_row_to_candidate_derives_st_and_suspension(self):
        st = egs_full_row_to_candidate(_egs_full_row(name="ST 某某"))
        self.assertTrue(st["event_risk"]["delisting"]["st_flag"])
        delisted = egs_full_row_to_candidate(_egs_full_row(name="康美退"))
        self.assertTrue(delisted["event_risk"]["delisting"]["delisting_warning"])
        ordinary = egs_full_row_to_candidate(_egs_full_row(name="退货公司"))
        self.assertFalse(ordinary["event_risk"]["delisting"]["delisting_warning"])
        historical = egs_full_row_to_candidate(
            _egs_full_row(name="康美股份", list_status="D"), historical=True
        )
        self.assertFalse(historical["event_risk"]["delisting"]["delisting_warning"])
        susp = egs_full_row_to_candidate(_egs_full_row(list_status="P"))
        self.assertTrue(susp["event_risk"]["suspension"]["is_suspended"])
        reduce = egs_full_row_to_candidate(_egs_full_row(reduce_deduct="-3"))
        self.assertTrue(reduce["event_risk"]["holder_reduction"]["active_plan"])


# ── _build_holdings: Tier 路由 / 去重 / 价格门旁路 ─────────────────────────────
class BuildHoldingsTests(unittest.TestCase):
    def _call(self, acct, cand_codes, provider, egs_full):
        return _build_holdings(acct, cand_codes, AS_OF, provider, 55.0, {"available_cash": 5e5},
                               "震荡期", {}, PDT, egs_full=egs_full)

    def test_tier3_not_in_egs_full(self):
        acct = _held_acct([("600519.SH", 100)])
        hn, meta, mr = self._call(acct, {"600000.SH"}, lambda c: (_series_bars(), PDT), egs_full={})
        self.assertEqual(len(hn), 1)
        self.assertEqual(meta["600519.SH"], {"row_source": "account_position_only", "coverage_status": "partial"})
        self.assertEqual(mr, [])

    def test_tier2_in_egs_full(self):
        acct = _held_acct([("600519.SH", 100)])
        hn, meta, mr = self._call(acct, {"600000.SH"}, lambda c: (_series_bars(), PDT),
                                  egs_full={"600519.SH": _egs_full_row(final_score="71.5")})
        self.assertEqual(meta["600519.SH"]["row_source"], "account_position_egs_full")
        # S1:所有注入持仓 coverage=partial(语义未跑),不伪装 full
        self.assertEqual(meta["600519.SH"]["coverage_status"], "partial")
        self.assertEqual(hn[0]["egs_score"], 71.5)        # 复用 egs_full 本轮评分

    def test_tier2_close_uses_price_clock_not_egsfull(self):
        # R-ASHORT-HOLDINGS-S1-TIER2-EGSFULL-CLOSE-PRICE-CLOCK-DRIFT 回归:egs_full 快照 close 与抓到的
        # 价格序列最新 bar 不同 → 现价必须用 price provider 的最新 bar,不是 egs_full.close。
        acct = _held_acct([("600519.SH", 100)])
        series = [{"open": 10, "high": 10.4, "low": 9.9, "close": 10.25, "vol": 1000} for _ in range(25)]
        hn, meta, mr = self._call(acct, {"600000.SH"}, lambda c: (series, PDT),
                                  egs_full={"600519.SH": _egs_full_row(close="999.0", final_score="71.5")})
        self.assertEqual(hn[0]["close"], 10.25)           # 价格钟一致(非 egs_full 的 999.0)
        self.assertEqual(hn[0]["egs_score"], 71.5)        # EGS 分仍复用 egs_full

    def test_dedup_holding_in_topn_not_injected(self):
        acct = _held_acct([("600000.SH", 100)])           # 600000 在 top-N → 不重复注入
        hn, meta, mr = self._call(acct, {"600000.SH"}, lambda c: (_series_bars(), PDT), egs_full={})
        self.assertEqual((hn, meta, mr), ([], {}, []))

    def test_no_price_goes_to_manual_review_not_held(self):
        acct = _held_acct([("600519.SH", 100)])
        hn, meta, mr = self._call(acct, {"600000.SH"}, lambda c: ([], None), egs_full={})
        self.assertEqual(hn, [])                            # 不进 reports、不伪造持有
        self.assertEqual(mr[0]["ts_code"], "600519.SH")
        self.assertIn("无价", mr[0]["reason"])

    def test_stale_price_goes_to_manual_review(self):
        acct = _held_acct([("600519.SH", 100)])
        hn, meta, mr = self._call(acct, {"600000.SH"}, lambda c: (_series_bars(), "20260601"), egs_full={})
        self.assertEqual(hn, [])
        self.assertIn("陈旧", mr[0]["reason"])              # 最新 bar != 决策价格日 → 旁路、人工管理

    def test_price_provider_failure_goes_to_manual_review_without_aborting_report(self):
        acct = _held_acct([("600519.SH", 100)])
        hn, meta, mr = self._call(
            acct, {"600000.SH"},
            lambda c: (_ for _ in ()).throw(SystemExit("provider failed")), egs_full={},
        )
        self.assertEqual((hn, meta), ([], {}))
        self.assertEqual(mr[0]["ts_code"], "600519.SH")
        self.assertIn("价格数据获取失败", mr[0]["reason"])

    def test_s2_semantic_provider_threads_to_holding(self):
        # 4.2 S2: semantic_provider 结果接进持仓 normalize → 端到端经 build_holding_report 发 holding_row_impact
        from runners.a_short_phase5_engine import build_holding_report, validate_m67_consistency
        acct = _held_acct([("600519.SH", 100)])
        event = {"source": "cninfo", "title": "立案", "category": "监管", "disclosure_date": "20260601",
                 "risk_type": "litigation", "severity": "high", "url_or_pdf": "http://x.pdf"}
        sem = {"600519.SH": {"status": "risk", "had_pit_announcements": True, "events": [event],
                               "regulatory_advisory": {"event_decisions": [{
                                   "event_fingerprint": event_fingerprint("600519.SH", event),
                                   "decision": "confirmed_material",
                               }]}}}
        hn, meta, mr = _build_holdings(acct, {"600000.SH"}, AS_OF, lambda c: (_series_bars(), PDT), 55.0,
                                       {"available_cash": 5e5}, "震荡期", {}, PDT, egs_full={},
                                       semantic_provider=lambda c: sem.get(str(c)))
        r = build_holding_report(hn[0], AS_OF, "t")          # Tier-3 → build_holding 路径
        imp = [i for i in (r["machine"].get("operation_impact") or [])
               if i["source_field"] == "semantic_official_high_confirmed"]
        self.assertTrue(imp and imp[0]["holding_effect"] == "clear_review")   # provider→normalize→build_holding emit
        self.assertEqual(r["m67"]["table"]["操作"], "持有")   # 持仓 semantic 不否决
        validate_m67_consistency(r)

    def test_s2_holding_provider_cap_covers_beyond_top15(self):
        # 4.2 S2 + Finding 1 fix: 持仓 provider output 覆盖 >15(不止 fetcher 看到 20,而是 provider(code) 非 None);
        # build_summary_from_fetches 内部二次 Top15 由分批绕过。候选默认仍 Top15(provider(第20只)=None,行为不变)。
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider
        codes = [f"60{i:04d}.SH" for i in range(20)]         # 20 主板码
        def stub(main_codes, as_of, lookback):               # 每码 ok+空公告 → official_structured 非 None
            return [{"ts_code": c, "ok": True, "error_category": None, "announcements": []} for c in main_codes]
        prov = _build_cninfo_semantic_provider(codes, AS_OF, 90, fetcher=stub, cap=len(codes))
        self.assertIsNotNone(prov(codes[15]))                # 第 16 只(>Top15)output 覆盖
        self.assertIsNotNone(prov(codes[-1]))                # 第 20 只 output 覆盖
        prov15 = _build_cninfo_semantic_provider(codes, AS_OF, 90, fetcher=stub)   # 候选默认 Top15
        self.assertIsNone(prov15(codes[-1]))                 # 第 20 只不在候选 Top15 → None(候选行为不变)


# ── render: 分区 / partial 未核查 / manual_review / 4.3-D / 无持仓回归 ──────────
def _min_report(ts_code, action="持有", coverage=None, row_source=None, veto="无", egs=None,
                position_state="held", cons=None, semantic_risk=None):
    rep = {
        "schema_name": "a_short_m67_report", "as_of": AS_OF, "ts_code": ts_code, "name": "测试",
        "m67": {"精简结论区": {"当前环境": "震荡期", "波动率状态": "IV分位≈55%", "现价与成本": "10 | 持仓",
                              "否决审查触发": veto, "板块资金事件": "neutral", "风控触发": "无",
                              "操作建议": "持有。"},
                "table": {"操作": action, "股数": None, "入": None, "盈一": None, "盈二": None, "损": None,
                          "类型": "已有持仓", "EGS分": egs, "优先级": "⭐×2", "触发条件": "x"}},
        "machine": {"stateful_risk": {"position_state": position_state, "rule12": {"status": "inactive"},
                                      "rule13": {"status": "none"}, "reasons": []},
                    **({"layer": {"semantic_risk": semantic_risk}} if semantic_risk else {})},
        "boundary": {"production": False, "real_money": False, "is_validated_alpha": False,
                     "satisfies_ship_gate": False},
    }
    if coverage:
        rep["coverage_status"] = coverage
    if row_source:
        rep["row_source"] = row_source
    if cons:
        rep["consistency_warning"] = cons
    return rep


def _weekly_dict(reports, manual_review=None):
    w = {"schema_name": "a_short_weekly_report", "as_of": AS_OF, "n_stocks": len(reports),
         "reports": reports}
    if manual_review is not None:
        w["holdings_manual_review"] = manual_review
    return w


class RenderHoldingsSectionTests(unittest.TestCase):
    def test_partition_holdings_separate_section(self):
        cand = _min_report("600000.SH", action="观察", row_source="egs_candidate", position_state="flat")
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_only")
        md = render_weekly_markdown(_weekly_dict([cand, hold]))
        self.assertIn("## 账户持仓(非本周 EGS 候选)", md)
        self.assertIn("603667.SH", md)

    def test_tier3_partial_shows_weihecha_not_wu(self):
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_only", veto="无")
        md = render_weekly_markdown(_weekly_dict([hold]))
        self.assertIn("未核查", md)                          # 否决审查触发 被 coverage-aware 改成未核查
        self.assertIn("⚠️ **EGS 未覆盖**", md)               # 安全 caveat 表内可见(非藏 trace)

    def test_tier2_egs_shown_but_semantic_unchecked(self):
        # R-...-SEMANTIC-UNCHECKED-MISRENDERED-CLEAR 回归:Tier-2 EGS 真实评分过 → 否决审查触发 原样显示
        # (不 override 成未核查);但 S1 没跑语义 → 必须显式标"语义/新闻未核查",绝不让缺失语义被读成已核查。
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_egs_full",
                           veto="无", egs=71.5)
        md = render_weekly_markdown(_weekly_dict([hold]))
        self.assertIn("否决审查触发:无", md)                 # Tier-2 EGS 覆盖了 → 不被改成未核查(仍显示)
        self.assertNotIn("⚠️ **EGS 未覆盖**", md)             # Tier-2 EGS 维度覆盖 → 不显 EGS未覆盖

    # ── 4.2 S2 render(R-...-S2-HOLDING-SEMANTIC-TOPN-RENDER-DRIFT Finding 2): 已跑语义 → 显 S2 状态,不显 S1 未核查 ──
    _SR = {"official_status": "risk", "severity_max": "high", "events": [{}], "impact": "veto",
           "evidence_incomplete_high": 0,
           "web_llm": {"status": "unknown", "risk_level": "unknown", "action": "no_action",
                       "sources_count": 0, "impact": "none", "invalid_neutralized": False}}

    def test_s2_semantic_checked_holding_shows_state_not_s1(self):
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_egs_full",
                           veto="语义官方 high(非生产 advisory)", egs=71.5, semantic_risk=self._SR)
        md = render_weekly_markdown(_weekly_dict([hold]))
        self.assertIn("语义已核查", md)                       # coverage label 翻成已核查
        self.assertIn("语义风险(advisory", md)                # _semantic_line 渲染 S2 状态
        self.assertNotIn("语义/新闻未核查(S1)", md)           # 不再误标未核查

    def test_s2_tier3_semantic_not_masked(self):
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_only",
                           veto="官方结构化 high(非生产 advisory):建议清仓复核", semantic_risk=self._SR)
        md = render_weekly_markdown(_weekly_dict([hold]))
        self.assertIn("建议清仓复核", md)                     # Tier-3 已跑语义 → 否决审查触发不被 EGS-未覆盖文案 mask
        self.assertNotIn("语义/新闻未核查(S1)", md)

    def test_s2_no_semantic_holding_still_unchecked(self):
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_only")  # 无 semantic_risk
        md = render_weekly_markdown(_weekly_dict([hold]))
        self.assertIn("语义/新闻未核查(S1)", md)              # 向后兼容:无语义仍显未核查
        self.assertIn("语义未核查", md)

    def test_s2_tier2_unknown_trace_still_unchecked(self):
        # 残留 fix(R-...-S2-...-RENDER-DRIFT): build_m67(Tier-2)恒写 semantic_risk;无 semantic 输入时 trace 全 unknown
        # → 不算已核查(否则误标已核查、违反 no-semantic-must-show-unchecked)。仍显未核查。
        sr_unknown = {"official_status": "unknown", "severity_max": None, "events": [], "impact": "none",
                      "evidence_incomplete_high": 0,
                      "web_llm": {"status": "unknown", "risk_level": "unknown", "action": "no_action",
                                  "sources_count": 0, "impact": "none", "invalid_neutralized": False}}
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_egs_full",
                           egs=71.5, semantic_risk=sr_unknown)
        md = render_weekly_markdown(_weekly_dict([hold]))
        self.assertIn("语义未核查", md)                       # unknown trace → 未核查(不误标已核查)
        self.assertIn("语义/新闻未核查(S1)", md)
        self.assertIn("语义/新闻未核查(S1)", md)             # 但语义未跑 → 必须显式标(不伪装已核查)

    def test_consistency_warning_rendered(self):
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_only",
                           cons="603667.SH:positions 300 股 vs trades 净额 200 股")
        md = render_weekly_markdown(_weekly_dict([hold]))
        self.assertIn("对账(4.3-D)", md)
        self.assertIn("净额 200 股", md)

    def test_consistency_warning_rendered_for_held_topn_candidate(self):
        candidate = _min_report("600000.SH", row_source="egs_candidate_with_position",
                                cons="600000.SH:positions 300 股 vs trades 净额 200 股")
        md = render_weekly_markdown(_weekly_dict([candidate]))
        self.assertEqual(md.count("对账(4.3-D)"), 1)
        self.assertIn("净额 200 股", md)

    def test_manual_review_section(self):
        md = render_weekly_markdown(_weekly_dict(
            [_min_report("600000.SH", action="观察", row_source="egs_candidate", position_state="flat")],
            manual_review=[{"ts_code": "603001.SH", "name": "停牌股", "reason": "无价/停牌(价格序列不足 < 20 交易日)"}]))
        self.assertIn("需人工管理", md)
        self.assertIn("603001.SH", md)
        self.assertIn("无价/停牌", md)

    def test_no_holdings_render_unchanged(self):
        # 回归:全候选、无持仓行 → 无"账户持仓"段(既有渲染不变)
        cand = _min_report("600000.SH", action="观察", row_source="egs_candidate", position_state="flat")
        md = render_weekly_markdown(_weekly_dict([cand]))
        self.assertNotIn("## 账户持仓", md)
        self.assertNotIn("需人工管理", md)


# ── main 集成:持仓恒列入 + 无账户回归 ────────────────────────────────────────
class MainIntegrationTests(unittest.TestCase):
    def _write(self, td, acct):
        ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
        (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
        (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
        _write_account(Path(td) / "acct.json", acct)

    def _run(self, td, acct):
        out = Path(td) / "weekly.json"
        # as_of=20260609 无 egs_full → 持仓走 Tier-3(确定);价格 provider 返回列表 → 严格 as_of 时钟
        main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
              "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
              "--out", str(out)], price_provider=lambda code: _series())
        return json.loads(out.read_text(encoding="utf-8"))

    def test_holding_not_in_topn_enters_m67(self):
        with tempfile.TemporaryDirectory() as td:
            acct = _held_acct([("603667.SH", 300)])        # 不在候选 → 应被注入(Tier-3)
            self._write(td, acct)
            w = self._run(td, acct)
        codes = {r["ts_code"]: r for r in w["reports"]}
        self.assertIn("603667.SH", codes)                  # 持仓恒列入
        self.assertEqual(codes["603667.SH"]["row_source"], "account_position_only")
        self.assertEqual(codes["603667.SH"]["coverage_status"], "partial")
        self.assertEqual(codes["603667.SH"]["m67"]["table"]["操作"], "持有")
        self.assertEqual(w["n_stocks"], 3)                 # 2 候选 + 1 持仓

    def test_topn_candidate_rows_unchanged_and_tagged(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, _account())                    # 无持仓
            w = self._run(td, _account())
        # 候选行不变 + 打 egs_candidate;无持仓注入、无 manual_review
        self.assertEqual(w["n_stocks"], 2)
        self.assertTrue(all(r["row_source"] == "egs_candidate" for r in w["reports"]))
        self.assertNotIn("holdings_manual_review", w)

    def test_held_topn_candidate_has_one_candidate_row(self):
        with tempfile.TemporaryDirectory() as td:
            acct = _held_acct([("600000.SH", 300)])
            self._write(td, acct)
            w = self._run(td, acct)
        matches = [r for r in w["reports"] if r["ts_code"] == "600000.SH"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["row_source"], "egs_candidate_with_position")
        self.assertNotIn("holdings_manual_review", w)

    def test_holding_confirmation_applies_only_to_bound_non_topn_holding(self):
        event = {"source": "cninfo", "title": "official notice", "category": "regulatory",
                 "disclosure_date": AS_OF, "url_or_pdf": "https://example.invalid/notice.pdf",
                 "risk_type": "investigation", "severity": "high"}
        with tempfile.TemporaryDirectory() as td:
            acct = _held_acct([("603667.SH", 300)])
            self._write(td, acct)
            bundle = json.loads((Path(td) / "acct.json").read_text(encoding="utf-8"))
            confirmation_path = Path(td) / "holding-confirmation.json"
            confirmation_path.write_text(
                json.dumps(_holding_confirmation(bundle, "603667.SH", event)), encoding="utf-8"
            )
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out), "--holding-regulatory-confirmations", str(confirmation_path)],
                 price_provider=lambda code: _series(),
                 holding_semantic_provider=lambda code: (
                     {"status": "risk", "had_pit_announcements": True, "events": [event]}
                     if code == "603667.SH" else None
                 ))
            weekly = json.loads(out.read_text(encoding="utf-8"))
        holding = {row["ts_code"]: row for row in weekly["reports"]}["603667.SH"]
        impacts = [impact for impact in holding["machine"]["operation_impact"]
                   if impact["source_field"] == "semantic_official_high_confirmed"]
        self.assertTrue(impacts)
        self.assertEqual(impacts[0]["holding_effect"], "clear_review")

    def test_holding_confirmation_missing_path_fails_without_default_blocker(self):
        # Existing no-confirmation integration tests remain the default-path proof; an explicitly supplied
        # missing private file is instead a pre-publish FATAL.
        with tempfile.TemporaryDirectory() as td:
            self._write(td, _held_acct([("603667.SH", 300)]))
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(Path(td) / "weekly.json"),
                     "--holding-regulatory-confirmations", str(Path(td) / "missing.json")],
                     price_provider=lambda code: (_ for _ in ()).throw(AssertionError("must not fetch")))

    def test_holding_confirmation_requires_account_before_any_input_read(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "missing-ai.json"),
                      "--iv-feed", str(Path(td) / "missing-feed.json"), "--out", str(Path(td) / "weekly.json"),
                      "--holding-regulatory-confirmations", str(Path(td) / "holding-confirmation.json")],
                     price_provider=lambda code: (_ for _ in ()).throw(AssertionError("must not fetch")))

    def test_holding_confirmation_wrong_account_or_universe_fails_before_fetch(self):
        event = {"source": "cninfo", "title": "official notice", "category": "regulatory",
                 "disclosure_date": AS_OF, "url_or_pdf": "https://example.invalid/notice.pdf",
                 "risk_type": "investigation", "severity": "high"}
        for field, replacement in (("snapshot", "0" * 64), ("universe", "1" * 64)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                self._write(td, _held_acct([("603667.SH", 300)]))
                bundle = json.loads((Path(td) / "acct.json").read_text(encoding="utf-8"))
                confirmation = _holding_confirmation(
                    bundle,
                    "603667.SH",
                    event,
                    snapshot_digest=(replacement if field == "snapshot" else None),
                    universe_digest=(replacement if field == "universe" else None),
                )
                confirmation_path = Path(td) / "holding-confirmation.json"
                confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(Path(td) / "weekly.json"),
                          "--holding-regulatory-confirmations", str(confirmation_path)],
                         price_provider=lambda code: (_ for _ in ()).throw(AssertionError("must not fetch")))

    def test_holding_confirmation_stale_event_and_candidate_domain_are_rejected(self):
        event = {"source": "cninfo", "title": "official notice", "category": "regulatory",
                 "disclosure_date": AS_OF, "url_or_pdf": "https://example.invalid/notice.pdf",
                 "risk_type": "investigation", "severity": "high"}
        with tempfile.TemporaryDirectory() as td:
            self._write(td, _held_acct([("603667.SH", 300)]))
            bundle = json.loads((Path(td) / "acct.json").read_text(encoding="utf-8"))
            stale = _holding_confirmation(bundle, "603667.SH", event)
            stale["confirmations"][0]["event_fingerprint"] = "0" * 64
            confirmation_path = Path(td) / "holding-confirmation.json"
            confirmation_path.write_text(json.dumps(stale), encoding="utf-8")
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(Path(td) / "weekly.json"),
                      "--holding-regulatory-confirmations", str(confirmation_path)],
                     price_provider=lambda code: _series(),
                     holding_semantic_provider=lambda code: (
                         {"status": "risk", "had_pit_announcements": True, "events": [event]}
                         if code == "603667.SH" else None
                     ))
        with tempfile.TemporaryDirectory() as td:
            self._write(td, _held_acct([("600000.SH", 300)]))
            bundle = json.loads((Path(td) / "acct.json").read_text(encoding="utf-8"))
            confirmation_path = Path(td) / "holding-confirmation.json"
            confirmation_path.write_text(
                json.dumps(_holding_confirmation(bundle, "600000.SH", event)), encoding="utf-8"
            )
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(Path(td) / "weekly.json"),
                      "--holding-regulatory-confirmations", str(confirmation_path)],
                     price_provider=lambda code: _series(),
                     holding_semantic_provider=lambda code: (
                         {"status": "risk", "had_pit_announcements": True, "events": [event]}
                         if code == "600000.SH" else None
                     ))


class PrivacyGuardTests(unittest.TestCase):
    """持仓恒列入隐私护栏(固化):带 --account 的报告含真实持仓 → 绝不能落仓库内非私密目录。
    判据 = 仓库内 且 git 未忽略(`git check-ignore` 未命中)→ 拒;git 真忽略 / 仓库外(临时目录)/ 无 account / 显式放行 → 放行。"""
    INSIDE_NONPRIVATE = str(ROOT / "research" / "results" / "a_short" / "20260612" / "weekly_m67.json")
    INSIDE_PRIVATE = str(ROOT / "state" / "a_short" / "weekly_private" / "20260612" / "weekly_m67.json")
    OUTSIDE = str(Path(tempfile.gettempdir()) / "weekly_m67_guardtest.json")

    def test_account_inside_repo_nonprivate_refused(self):
        with self.assertRaises(SystemExit):
            _reject_nonprivate_account_output_path(self.INSIDE_NONPRIVATE, has_account=True)

    def test_account_inside_repo_private_ok(self):
        _reject_nonprivate_account_output_path(self.INSIDE_PRIVATE, has_account=True)        # 私密目录,不抛

    def test_account_outside_repo_ok(self):
        _reject_nonprivate_account_output_path(self.OUTSIDE, has_account=True)               # 仓库外,提交不到

    def test_no_account_nonprivate_ok(self):
        _reject_nonprivate_account_output_path(self.INSIDE_NONPRIVATE, has_account=False)    # observation-only 无持仓

    def test_override_allows_nonprivate(self):
        _reject_nonprivate_account_output_path(self.INSIDE_NONPRIVATE, has_account=True,
                                               allow_override=True)                          # 显式放行

    def test_holding_confirmation_path_cannot_use_output_override(self):
        # The weekly report's explicit output override cannot turn a private account-bound confirmation
        # into a tracked repository file.
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "missing-ai.json"),
                      "--iv-feed", str(Path(td) / "missing-feed.json"),
                      "--account", str(Path(td) / "missing-account.json"),
                      "--out", str(Path(td) / "weekly.json"), "--allow-nonprivate-account-out",
                      "--holding-regulatory-confirmations", self.INSIDE_NONPRIVATE],
                     price_provider=lambda code: (_ for _ in ()).throw(AssertionError("must not fetch")))

    def test_main_account_nonprivate_out_refused_before_fetch(self):
        # 集成:main() 带 --account + 仓库内非私密 --out → 取数/读文件前就 fail-fast(故 ai/feed 不存在也无妨)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"),
                      "--account", str(Path(td) / "acct.json"),
                      "--out", self.INSIDE_NONPRIVATE], price_provider=lambda code: _series())

    # ---- Codex 审查 FAIL 回归:护栏不能被仓库内"假 weekly_private"骗过(判据 = git check-ignore 真值) ----
    FAKE_RESEARCH = str(ROOT / "research" / "results" / "a_short" / "weekly_private" / "20260612" / "weekly_m67.json")
    FAKE_NESTED = str(ROOT / "state" / "a_short" / "sub" / "weekly_private" / "20260612" / "weekly_m67.json")
    CASE_VARIANT = str(ROOT / "state" / "a_short" / "WEEKLY_PRIVATE" / "20260612" / "weekly_m67.json")

    def test_fake_weekly_private_under_research_refused(self):
        # 洞①:research/.../weekly_private/ 含 "weekly_private" 但 .gitignore 只盖 state/*/weekly_private/ → git 不忽略 → 必拒
        self.assertFalse(_is_account_output_git_ignored(os.path.abspath(self.FAKE_RESEARCH), str(ROOT)))
        with self.assertRaises(SystemExit):
            _reject_nonprivate_account_output_path(self.FAKE_RESEARCH, has_account=True)

    def test_nested_fake_weekly_private_under_state_refused(self):
        # 嵌套:state/a_short/sub/weekly_private/ 未被 state/*/weekly_private/(单层)覆盖 → git 不忽略 → 必拒
        self.assertFalse(_is_account_output_git_ignored(os.path.abspath(self.FAKE_NESTED), str(ROOT)))
        with self.assertRaises(SystemExit):
            _reject_nonprivate_account_output_path(self.FAKE_NESTED, has_account=True)

    def test_case_variant_guard_matches_git(self):
        # 洞②:大小写变体 — 护栏判定必须与 git 实际 check-ignore 一致(跨平台正确:Win 忽略→放行,Linux 不忽略→拒)
        ignored = _is_account_output_git_ignored(os.path.abspath(self.CASE_VARIANT), str(ROOT))
        if ignored:
            _reject_nonprivate_account_output_path(self.CASE_VARIANT, has_account=True)   # git 忽略它 → 不抛
        else:
            with self.assertRaises(SystemExit):
                _reject_nonprivate_account_output_path(self.CASE_VARIANT, has_account=True)


if __name__ == "__main__":
    unittest.main()
