"""Tests for the A-short M6.7 markdown renderer (runners/a_short_m67_render.py).

Pure render: weekly report dict → readable Markdown (honesty banner + summary line + 一览 table
+ per-stock cards). Renders only; no analysis logic.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_m67_render import render_weekly_markdown, write_weekly_markdown  # noqa: E402


def _report(ts_code, action, **tbl):
    table = {"操作": action, "股数": None, "入": None, "盈一": None, "盈二": None, "损": None,
             "类型": "N/A", "EGS分": None, "优先级": "—", "触发条件": "未到低吸/突破触发"}
    table.update(tbl)
    advice = "观察,不建仓。"
    if action == "建仓":
        advice = "低吸建仓建议。试探仓。止损无条件。未验证。"
    elif action == "持有":
        advice = "已有持仓,本周不按新开仓处理,禁止自动加仓。手动止损 2.55,触发后由你盘中无条件手动执行。"
    elif action == "否决":
        advice = "否决,禁止建仓。硬否决:ST/退市。已有持仓也不得加仓;如硬风控触发止损/清仓条件,由你手动执行。"
    return {
        "ts_code": ts_code, "name": "测试",
        "m67": {
            "精简结论区": {"当前环境": "震荡期", "波动率状态": "IV分位≈55%", "现价与成本": "2.90 | 试探仓",
                          "否决审查触发": "无", "板块资金事件": "neutral", "风控触发": "无",
                          "操作建议": advice},
            "table": table,
        },
    }


def _weekly(reports):
    return {"schema_name": "a_short_weekly_report", "as_of": "20260609",
            "n_stocks": len(reports), "reports": reports}


class RenderTests(unittest.TestCase):
    def test_markdown_structure(self):
        md = render_weekly_markdown(_weekly([
            _report("600000.SH", "观察"),
            _report("000001.SZ", "建仓", 股数=34400, 入=2.90, 盈一=3.10, 盈二=3.30, 损=2.82,
                    类型="低吸", 优先级="⭐×4"),
        ]))
        self.assertIn("# A-short 周报 M6.7 — 20260609", md)
        self.assertIn("edge 未验证", md)                 # honesty banner present
        self.assertIn("## 一览", md)
        self.assertIn("| 票 | 名称 | 操作 |", md)         # summary table header
        self.assertIn("建仓 1 / 持有 0 / 观察 1 / 否决 0", md)     # action tally
        self.assertIn("000001.SZ", md)
        self.assertIn("执行清单:入 2.9", md)             # 建仓 shows the plan
        self.assertIn("## 逐票", md)

    def test_holding_report_renders_position_management_path(self):
        held = _report("600000.SH", "持有", 类型="已有持仓", EGS分=72.0, 优先级="⭐×3",
                       触发条件="已有持仓:按持仓管理输出,不按新开仓处理;禁止自动加仓")
        held["m67"]["精简结论区"]["现价与成本"] = "2.90 | 持仓:1000股/均价2.7/建仓20260601/手动止损2.55"
        held["machine"] = {"stateful_risk": {"position_state": "held", "rule12": {"status": "inactive"},
                                             "rule13": {"status": "not_applicable_existing_position"}, "reasons": []}}
        md = render_weekly_markdown(_weekly([held]))
        self.assertIn("建仓 0 / 持有 1 / 观察 0 / 否决 0", md)
        self.assertIn("| 600000.SH | 测试 | 持有 | 已持仓 | 72.0 | ⭐×3 | 已有持仓 |", md)
        self.assertIn("持仓:1000股/均价2.7/建仓20260601/手动止损2.55", md)
        self.assertIn("禁止自动加仓", md)
        self.assertIn("已有持仓:按持仓管理输出", md)
        self.assertNotIn("执行清单:入", md)

    def test_holding_disposition_and_clear_price_render_with_same_table_truth(self):
        held = _report("600000.SH", "持有", 类型="已有持仓", 优先级="—",
                       触发条件="持仓管理", 持仓处置="建议清仓复核", 禁止加仓=True,
                       清仓价=2.55, 损=2.55)
        held["m67"]["精简结论区"]["操作建议"] = (
            "已有持仓。持仓处置=建议清仓复核（清仓价=2.55；advisory复核建议,不自动卖出）。")
        md = render_weekly_markdown(_weekly([held]))
        self.assertIn("持仓处置:建议清仓复核（禁止加仓:是）", md)
        self.assertIn("清仓价(=系统止损):2.55", md)
        self.assertIn("持仓处置=建议清仓复核", md)

    def test_empty(self):
        md = render_weekly_markdown(_weekly([]))
        self.assertIn("共 0 只", md)


def _report_sem(ts_code, semantic_risk):
    # a report carrying the engine's machine.layer.semantic_risk trace (Slice 3b inline render source)
    r = _report(ts_code, "观察")
    r["machine"] = {"layer": {"semantic_risk": semantic_risk}}
    return r


class SemanticInlineTests(unittest.TestCase):
    """Slice 3b: semantic advisory is rendered INLINE per-票 (from machine.layer.semantic_risk),
    replacing the retired standalone panel. Render-only; it's the engine trace shown, no logic."""

    def test_semantic_line_rendered_inline(self):
        sr = {"official_status": "risk", "severity_max": "high", "events": [{}, {}], "impact": "veto",
              "web_llm": {"status": "risk", "risk_level": "high", "action": "downgrade",
                          "sources_count": 2, "impact": "downgrade", "invalid_neutralized": False}}
        md = render_weekly_markdown(_weekly([_report_sem("600000.SH", sr)]))
        self.assertIn("语义风险(advisory", md)
        self.assertIn("官方 risk[high]·2事件·impact=veto", md)
        self.assertIn("web risk/high/downgrade·2源·impact=downgrade", md)

    def test_invalid_neutralized_flag_shown(self):
        sr = {"official_status": "clear", "severity_max": None, "events": [], "impact": "none",
              "web_llm": {"status": "unknown", "risk_level": "unknown", "action": "no_action",
                          "sources_count": 0, "impact": "none", "invalid_neutralized": True}}
        md = render_weekly_markdown(_weekly([_report_sem("600000.SH", sr)]))
        self.assertIn("官方 clear·impact=none", md)
        self.assertIn("已中性化", md)

    def test_no_semantic_line_when_no_machine_layer(self):
        # legacy report dicts without machine.layer.semantic_risk render with NO semantic line (no crash)
        md = render_weekly_markdown(_weekly([_report("600000.SH", "观察")]))
        self.assertNotIn("语义风险(advisory", md)


class RunLineageBannerTests(unittest.TestCase):
    """Slice 3b-2: the weekly .md carries a durable run_lineage banner — esp. a no-account no-sizing
    warning so a reader of the artifact can't mistake a sizing-artifact 观察 for a real avoid signal."""

    def _with_lineage(self, sizing_mode, account_status):
        w = _weekly([_report("600000.SH", "观察")])
        w["run_lineage"] = {"analysis_input": "result/a_short/20260609/analysis_input.json",
                            "selection_bucket": "result/a_short/20260609", "iv_feed": "iv_feed.json",
                            "account_status": account_status, "sizing_mode": sizing_mode}
        return w

    def test_no_sizing_banner_when_observation_only(self):
        md = render_weekly_markdown(self._with_lineage("observation_only_no_account", "absent"))
        self.assertIn("无账户", md)
        self.assertIn("sizing 假象", md)
        self.assertIn("result/a_short/20260609/analysis_input.json", md)   # lineage ties selection to M6.7
        self.assertIn("sizing=observation_only_no_account", md)

    def test_no_banner_when_sized(self):
        md = render_weekly_markdown(self._with_lineage("sized", "provided"))
        self.assertNotIn("无账户", md)            # no no-sizing banner when sized
        self.assertIn("sizing=sized", md)         # lineage line still present

    def test_no_lineage_renders_clean(self):
        md = render_weekly_markdown(_weekly([_report("600000.SH", "观察")]))   # legacy dict, no run_lineage
        self.assertNotIn("无账户", md)
        self.assertNotIn("lineage", md)


class EgsScoreAndRegimeBannerTests(unittest.TestCase):
    """Slice A: 一览表并列「EGS分」(选股质量分) + 风控星级,让 82 分和 56 分不再都只显示 2 星;
    regime unknown 做全局横幅(把"全员保守压星"说成市场状态,不是个股质量差)。纯渲染,不改打分逻辑。"""

    def test_egs_score_column_rendered(self):
        md = render_weekly_markdown(_weekly([
            _report("600000.SH", "观察", EGS分=82.66, 优先级="⭐×2")]))
        self.assertIn("| 票 | 名称 | 操作 | 持仓/冷静 | EGS分 | 优先级 |", md)   # EGS分 列(持仓/冷静在其左)
        self.assertIn("| 600000.SH | 测试 | 观察 | — | 82.66 | ⭐×2 |", md)      # 无账户→持仓/冷静=—,EGS 分并列

    def test_regime_unknown_global_banner(self):
        r = _report("600000.SH", "观察", EGS分=82.66, 优先级="⭐×2")
        r["m67"]["精简结论区"]["当前环境"] = "震荡期(EGS regime unknown,保守fallback)"
        md = render_weekly_markdown(_weekly([r]))
        self.assertIn("市场 regime 未知", md)         # 全局横幅出现
        self.assertIn("EGS分", md)                    # 横幅指向 EGS分 列

    def test_no_regime_banner_when_known(self):
        # 反向:regime 已知(非 unknown fallback)→ 无全局横幅(不误加)
        r = _report("600000.SH", "观察", EGS分=82.66, 优先级="⭐×3")
        r["m67"]["精简结论区"]["当前环境"] = "进攻期"
        md = render_weekly_markdown(_weekly([r]))
        self.assertNotIn("市场 regime 未知", md)


def _report_stateful(ts_code, action, stateful, **tbl):
    # a report carrying the engine's machine.stateful_risk ctx (4.3-C holding/cooldown render source)
    r = _report(ts_code, action, **tbl)
    r["machine"] = {"stateful_risk": stateful}
    return r


def _sr(position_state="flat", r12="inactive", r13="none", reasons=None):
    return {"position_state": position_state, "rule12": {"status": r12},
            "rule13": {"status": r13}, "reasons": reasons or []}


class HoldingStateTests(unittest.TestCase):
    """4.3-C: 一览表新增「持仓/冷静」列 + 逐票说明,纯渲染派生自 machine.stateful_risk;只解释、不改
    action/star/sizing。无「状态来源」列(来源在转换器 lineage,不在被 M6.7 消费的 account_state)。"""

    def _md(self, stateful, action="观察"):
        return render_weekly_markdown(_weekly([_report_stateful("600000.SH", action, stateful)]))

    def test_flat_empty_shows_kongcang_no_card_line(self):
        md = self._md(_sr())
        self.assertIn("| 票 | 名称 | 操作 | 持仓/冷静 | EGS分 |", md)
        self.assertIn("| 600000.SH | 测试 | 观察 | 空仓 |", md)
        self.assertNotIn("- 持仓/冷静:", md)            # 空仓不在逐票区加噪音

    def test_held_label_and_card_line(self):
        md = self._md(_sr(position_state="held", reasons=["已有持仓:仅管理/不加仓"]), action="持有")
        self.assertIn("| 600000.SH | 测试 | 持有 | 已持仓 |", md)
        self.assertIn("- 持仓/冷静:已持仓（已有持仓:仅管理/不加仓）", md)

    def test_rule13_states(self):
        self.assertIn("| 600000.SH | 测试 | 观察 | Rule13冷静 |", self._md(_sr(r13="active_cooldown")))
        self.assertIn("| 600000.SH | 测试 | 观察 | Rule13待复核 |", self._md(_sr(r13="pending_recheck")))
        self.assertIn("| 600000.SH | 测试 | 观察 | Rule13可再入 |", self._md(_sr(r13="cleared_for_reentry")))

    def test_rule12_states(self):
        self.assertIn("| 600000.SH | 测试 | 观察 | Rule12冷静 |", self._md(_sr(r12="active_cooldown")))
        self.assertIn("| 600000.SH | 测试 | 观察 | Rule12恢复 |", self._md(_sr(r12="recovery_1")))

    def test_overlapping_rule12_rule13_shows_both_tags(self):
        # R-ASHORT-43C-HOLDING-STATE-MULTILABEL-DROP regression: a flat stock hitting BOTH a portfolio
        # Rule12 state and a per-stock Rule13 state must show BOTH tags (Rule12 must NOT be hidden).
        md = self._md(_sr(r12="active_cooldown", r13="pending_recheck",
                          reasons=["Rule12 active_cooldown:block_new_entries", "Rule13 pending_recheck:block_reentry"]))
        self.assertIn("| 600000.SH | 测试 | 观察 | Rule12冷静 + Rule13待复核 |", md)   # overview row shows both
        self.assertIn("- 持仓/冷静:Rule12冷静 + Rule13待复核", md)                      # per-stock line shows both
        self.assertIn("Rule12 active_cooldown:block_new_entries", md)                  # both reasons kept in card
        self.assertIn("Rule13 pending_recheck:block_reentry", md)

    def test_overlapping_recovery_and_cleared_shows_both_tags(self):
        md = self._md(_sr(r12="recovery_1", r13="cleared_for_reentry"))
        self.assertIn("| 600000.SH | 测试 | 观察 | Rule12恢复 + Rule13可再入 |", md)

    def test_held_stays_single_label_but_rule12_reason_in_card(self):
        # held may stay a single dominant 已持仓 label (register-permitted); the portfolio Rule12 reason
        # is still surfaced in the per-stock card, so no information is lost.
        md = self._md(_sr(position_state="held", r12="active_cooldown",
                          reasons=["Rule12 active_cooldown:已有持仓仅管理/不加仓"]), action="持有")
        self.assertIn("| 600000.SH | 测试 | 持有 | 已持仓 |", md)
        self.assertIn("- 持仓/冷静:已持仓（Rule12 active_cooldown:已有持仓仅管理/不加仓）", md)

    def test_no_account_shows_dash_no_card_line(self):
        md = render_weekly_markdown(_weekly([_report("600000.SH", "观察")]))   # legacy/no machine.stateful_risk
        self.assertIn("| 600000.SH | 测试 | 观察 | — |", md)
        self.assertNotIn("- 持仓/冷静:", md)

    def test_render_only_does_not_alter_action_cell(self):
        # reverse: holding-state column is explanation-only; the 操作 cell still reflects the engine action
        md = self._md(_sr(r13="active_cooldown"), action="否决")
        self.assertIn("| 600000.SH | 测试 | 否决 | Rule13冷静 |", md)   # action unchanged by the new column


def _guard_weekly(account: bool, reports=None) -> dict:
    rl = {"analysis_input": "", "selection_bucket": "", "iv_feed": "x", "account_ref": "",
          "account_status": "provided" if account else "absent",
          "sizing_mode": "sized" if account else "observation_only_no_account",
          "price_freshness": {"mode": "strict_as_of", "run_date": None,
                              "accepted_prior_settled_date": None, "price_data_through": "20260616"}}
    reps = reports if reports is not None else [_report("000001.SZ", "观察")]
    return {"schema_name": "a_short_weekly_report", "schema_version": "1.0.0",
            "generated_at": "2026-06-16T15:00:00+08:00", "as_of": "20260616",
            "iv_feed_ref": "x", "n_stocks": len(reps), "reports": reps,
            "cash_allocation": None, "run_lineage": rl,
            "boundary": {"production": False, "real_money": False,
                         "is_validated_alpha": False, "satisfies_ship_gate": False}}


class WriteGuardTests(unittest.TestCase):
    """standalone renderer 写盘前隐私/生产路径守门(R-ASHORT-M67-RENDER-STANDALONE-PRIVACY-PROD-GUARD-GAP):
    无条件拒生产桶;含账户/持仓 weekly 拒落仓库内非 gitignored 路径;无账户 weekly 不过度守门(reverse)。"""

    def test_production_bucket_always_rejected(self):
        leak = ROOT / "result" / "a_short" / "__probe_m67__" / "weekly_m67.md"   # 生产桶
        with self.assertRaises(ValueError):                                       # _reject_production_output_path
            write_weekly_markdown(_guard_weekly(account=False), str(leak))
        self.assertFalse(leak.exists())                                           # 守门在写盘前 raise → 不创建

    def test_account_weekly_rejected_on_tracked_repo_path(self):
        leak = ROOT / "__m67_render_leak_probe__.md"                              # repo 根,git 不忽略
        try:
            with self.assertRaises(SystemExit):                                   # _reject_nonprivate_account_output_path
                write_weekly_markdown(_guard_weekly(account=True), str(leak))
        finally:
            if leak.exists():
                leak.unlink()
        self.assertFalse(leak.exists())

    def test_account_weekly_allowed_on_gitignored_private_path(self):
        import shutil
        base = ROOT / "state" / "a_short" / "weekly_private" / "__probe_m67__"
        out = base / "weekly_m67.md"
        try:
            write_weekly_markdown(_guard_weekly(account=True), str(out))
            self.assertTrue(out.exists())
        finally:
            if base.exists():
                shutil.rmtree(base, ignore_errors=True)

    def test_no_account_weekly_allowed_on_tracked_path(self):
        # reverse-failure: 无账户 observation-only 周报无持仓数据 → 不应被私密守门误拒(只挡生产桶)。
        out = ROOT / "__m67_render_obs_probe__.md"                                # repo 根 tracked,但无账户数据
        try:
            write_weekly_markdown(_guard_weekly(account=False), str(out))
            self.assertTrue(out.exists())
        finally:
            if out.exists():
                out.unlink()

    def test_account_weekly_allowed_on_tracked_path_with_override(self):
        out = ROOT / "__m67_render_override_probe__.md"
        try:
            write_weekly_markdown(_guard_weekly(account=True), str(out), allow_nonprivate_account_out=True)
            self.assertTrue(out.exists())
        finally:
            if out.exists():
                out.unlink()


if __name__ == "__main__":
    unittest.main()
