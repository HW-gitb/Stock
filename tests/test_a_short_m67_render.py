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

from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402


def _report(ts_code, action, **tbl):
    table = {"操作": action, "股数": None, "入": None, "盈一": None, "盈二": None, "损": None,
             "类型": "N/A", "优先级": "—", "触发条件": "未到低吸/突破触发"}
    table.update(tbl)
    return {
        "ts_code": ts_code, "name": "测试",
        "m67": {
            "精简结论区": {"当前环境": "震荡期", "波动率状态": "IV分位≈55%", "现价与成本": "2.90 | 试探仓",
                          "否决审查触发": "无", "板块资金事件": "neutral", "风控触发": "无",
                          "操作建议": "观察,不建仓。" if action == "观察" else "低吸建仓建议。试探仓。止损无条件。未验证。"},
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
        self.assertIn("建仓 1 / 观察 1 / 否决 0", md)     # action tally
        self.assertIn("000001.SZ", md)
        self.assertIn("执行清单:入 2.9", md)             # 建仓 shows the plan
        self.assertIn("## 逐票", md)

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


if __name__ == "__main__":
    unittest.main()
