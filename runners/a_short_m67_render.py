#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 A-short 周报(a_short_weekly_report JSON)渲染成易读的 Markdown 面板.

用户(2026-06-11):M6.7 的 JSON 太难读,要"面板"式清晰输出。本模块读 weekly_m67.json(或任意
a_short_weekly_report dict),产出一份 Markdown:顶部诚实横幅 + 一句话汇总 + 一览表(每票操作/优先级/
关键价位)+ 逐票卡片(精简结论区 7 项 + 执行清单)。纯函数(`render_weekly_markdown`)可单测;
`main` 薄层读 json 写 md。**只渲染、不改任何分析结论**;非生产、edge 未验证的底色照样标在最上。
"""
from __future__ import annotations

import argparse
import json
import os

_BANNER = ("> ⚠️ **非生产 / A-short risk_filter_only / edge 未验证**。所有「建仓」均为 **试探仓**,"
           "**止损无条件**(盘中由你手动),仅供参考,非买卖指令。\n")


def _cell(v):
    return "" if v is None else str(v)


def render_weekly_markdown(weekly: dict) -> str:
    reports = weekly.get("reports", [])
    as_of = weekly.get("as_of", "")
    n = len(reports)
    acts = {"建仓": 0, "观察": 0, "否决": 0}
    for r in reports:
        a = r["m67"]["table"]["操作"]
        acts[a] = acts.get(a, 0) + 1
    env = reports[0]["m67"]["精简结论区"]["当前环境"] if reports else ""
    vol = reports[0]["m67"]["精简结论区"]["波动率状态"] if reports else ""

    out = [f"# A-short 周报 M6.7 — {as_of}", "", _BANNER,
           f"**环境**:{env}　|　**波动率**:{vol}",
           f"**共 {n} 只** — 建仓 {acts.get('建仓',0)} / 观察 {acts.get('观察',0)} / 否决 {acts.get('否决',0)}",
           "", "## 一览",
           "| 票 | 名称 | 操作 | 优先级 | 类型 | 入 | 损 | 盈一 | 盈二 | 股数 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in reports:
        t = r["m67"]["table"]
        out.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            _cell(r.get("ts_code")), _cell(r.get("name")), _cell(t["操作"]), _cell(t["优先级"]),
            _cell(t["类型"]), _cell(t["入"]), _cell(t["损"]), _cell(t["盈一"]), _cell(t["盈二"]),
            _cell(t["股数"])))

    out += ["", "## 逐票"]
    for r in reports:
        jq = r["m67"]["精简结论区"]
        t = r["m67"]["table"]
        out.append(f"### {_cell(r.get('ts_code'))} {_cell(r.get('name'))} — {t['操作']}　{_cell(t['优先级'])}")
        for k in ("当前环境", "波动率状态", "现价与成本", "否决审查触发", "板块资金事件", "风控触发"):
            out.append(f"- {k}:{jq.get(k, '')}")
        out.append(f"- **操作建议**:{jq.get('操作建议', '')}")
        if t["操作"] == "建仓":
            out.append(f"- 执行清单:入 {_cell(t['入'])} / 损 {_cell(t['损'])} / 盈一 {_cell(t['盈一'])} "
                       f"/ 盈二 {_cell(t['盈二'])} / 股数 {_cell(t['股数'])}")
        out.append(f"- 触发/说明:{_cell(t['触发条件'])}")
        out.append("")
    return "\n".join(out)


def write_weekly_markdown(weekly: dict, out_path: str, semantic_panel: str = None) -> None:
    """渲染周报 .md。`semantic_panel`(可选)= 语义风险 advisory 面板 markdown,**仅追加到 .md 末尾、
    与确定性 M6.7 用 `---` 分隔**;它绝不进确定性周报 JSON(advisory 不混入确定性字段)。"""
    md = render_weekly_markdown(weekly)
    if semantic_panel:
        md = md + "\n\n---\n\n" + semantic_panel.rstrip("\n") + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(md)
    os.replace(tmp, out_path)


def main(argv=None):
    p = argparse.ArgumentParser(description="Render A-short weekly M6.7 JSON → readable Markdown panel")
    p.add_argument("--weekly", required=True, help="weekly_m67.json path")
    p.add_argument("--out", help="output .md path (default: alongside the json as weekly_m67.md)")
    args = p.parse_args(argv)
    with open(args.weekly, encoding="utf-8") as f:
        weekly = json.load(f)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.weekly)), "weekly_m67.md")
    write_weekly_markdown(weekly, out)
    print(f"[m67_render] {len(weekly.get('reports', []))} 票 -> {out}")


if __name__ == "__main__":
    main()
