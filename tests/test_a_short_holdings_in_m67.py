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
from runners.a_short_weekly_pipeline import _build_holdings, main  # noqa: E402
from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402
from tests.test_a_short_weekly_pipeline import (AS_OF, _analysis_input, _ai_candidate,  # noqa: E402
                                                _account, _feed, _series)

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


# ── egs_full adapter ──────────────────────────────────────────────────────────
class EgsFullAdapterTests(unittest.TestCase):
    def test_load_missing_file_returns_empty(self):
        self.assertEqual(load_egs_full("20990101"), {})        # 不存在 → {}(诚实降级,非错误)

    def test_load_and_header_validation(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "A-EGS" / "Result"
            d.mkdir(parents=True)
            (d / "egs_full_20260612.csv").write_text(
                ",".join(EGS_FULL_REQUIRED_COLUMNS) + "\n"
                + ",".join(_egs_full_row()[c] for c in EGS_FULL_REQUIRED_COLUMNS) + "\n",
                encoding="utf-8")
            m = load_egs_full("20260612", root=td)
            self.assertIn("600519.SH", m)
            # 缺必需列 → ValueError(契约漂移,拒绝静默错位)
            (d / "egs_full_20260613.csv").write_text("ts_code,name\n600000.SH,x\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_egs_full("20260613", root=td)

    def test_row_to_candidate_maps_real_fields(self):
        c = egs_full_row_to_candidate(_egs_full_row(final_score="80.1"))
        self.assertEqual(c["scores"]["final_score"], 80.1)
        self.assertTrue(c["derived_flags"]["vol_confirm"])
        self.assertFalse(c["derived_flags"]["has_crash_veto"])

    def test_row_to_candidate_derives_st_and_suspension(self):
        st = egs_full_row_to_candidate(_egs_full_row(name="ST 某某"))
        self.assertTrue(st["event_risk"]["delisting"]["st_flag"])
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


# ── render: 分区 / partial 未核查 / manual_review / 4.3-D / 无持仓回归 ──────────
def _min_report(ts_code, action="持有", coverage=None, row_source=None, veto="无", egs=None,
                position_state="held", cons=None):
    rep = {
        "schema_name": "a_short_m67_report", "as_of": AS_OF, "ts_code": ts_code, "name": "测试",
        "m67": {"精简结论区": {"当前环境": "震荡期", "波动率状态": "IV分位≈55%", "现价与成本": "10 | 持仓",
                              "否决审查触发": veto, "板块资金事件": "neutral", "风控触发": "无",
                              "操作建议": "持有。"},
                "table": {"操作": action, "股数": None, "入": None, "盈一": None, "盈二": None, "损": None,
                          "类型": "已有持仓", "EGS分": egs, "优先级": "⭐×2", "触发条件": "x"}},
        "machine": {"stateful_risk": {"position_state": position_state, "rule12": {"status": "inactive"},
                                      "rule13": {"status": "none"}, "reasons": []}},
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
        self.assertIn("语义/新闻未核查(S1)", md)             # 但语义未跑 → 必须显式标(不伪装已核查)

    def test_consistency_warning_rendered(self):
        hold = _min_report("603667.SH", coverage="partial", row_source="account_position_only",
                           cons="603667.SH:positions 300 股 vs trades 净额 200 股")
        md = render_weekly_markdown(_weekly_dict([hold]))
        self.assertIn("对账(4.3-D)", md)
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
        (Path(td) / "acct.json").write_text(json.dumps(acct), encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
