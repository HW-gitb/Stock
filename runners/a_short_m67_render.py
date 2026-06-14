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


def _semantic_line(report: dict) -> str:
    """逐票语义风险 advisory 明细行(Slice 3b 行内化:取代独立面板),从该票
    `machine.layer.semantic_risk` 读;advisory·非确定·不进确定性字段(它已是引擎层 trace 的渲染,
    不改任何结论)。无语义层(老报告)→ 空串(不渲染)。"""
    sr = ((report.get("machine") or {}).get("layer") or {}).get("semantic_risk") or {}
    if not sr:
        return ""
    sev = sr.get("severity_max")
    n_ev = len(sr.get("events") or [])
    off = (f"官方 {sr.get('official_status', 'unknown')}"
           + (f"[{sev}]" if sev else "") + (f"·{n_ev}事件" if n_ev else "")
           + f"·impact={sr.get('impact', 'none')}")
    w = sr.get("web_llm") or {}
    web = (f"web {w.get('status', 'unknown')}/{w.get('risk_level', 'unknown')}/{w.get('action', 'no_action')}"
           + f"·{w.get('sources_count', 0)}源·impact={w.get('impact', 'none')}"
           + ("·已中性化" if w.get("invalid_neutralized") else ""))
    return f"- 语义风险(advisory·非确定·不进确定性字段):{off} / {web}"


def render_weekly_markdown(weekly: dict) -> str:
    reports = weekly.get("reports", [])
    as_of = weekly.get("as_of", "")
    n = len(reports)
    acts = {"建仓": 0, "持有": 0, "观察": 0, "否决": 0}
    for r in reports:
        a = r["m67"]["table"]["操作"]
        acts[a] = acts.get(a, 0) + 1
    env = reports[0]["m67"]["精简结论区"]["当前环境"] if reports else ""
    vol = reports[0]["m67"]["精简结论区"]["波动率状态"] if reports else ""

    out = [f"# A-short 周报 M6.7 — {as_of}", "", _BANNER,
           f"**环境**:{env}　|　**波动率**:{vol}",
           f"**共 {n} 只** — 建仓 {acts.get('建仓',0)} / 持有 {acts.get('持有',0)} / "
           f"观察 {acts.get('观察',0)} / 否决 {acts.get('否决',0)}"]
    # Slice 3b-2: durable run_lineage banner — esp. the no-account no-sizing warning so a reader of THIS
    # artifact (not just the terminal) cannot mistake a sizing-artifact 观察 for a real avoid signal.
    rl = weekly.get("run_lineage") or {}
    if rl.get("sizing_mode") and rl.get("sizing_mode") != "sized":
        out.append("> ⚠️ **无账户(account_status=" + str(rl.get("account_status", "?")) +
                   "):仓位 sizing N/A —— 建仓候选会渲染为「观察」(可建股数/金额不足),这是 **sizing 假象、非真 avoid 信号**;"
                   "传 `--account` / `-Account`(account-state JSON: cash/positions/Rule12/Rule13)以获真 sizing/持仓判断。**")
    if rl:
        out.append("**lineage**:analysis_input=`" + str(rl.get("analysis_input", "?")) + "` | iv_feed=`" +
                   str(rl.get("iv_feed", "?")) + "` | account=" + str(rl.get("account_status", "?")) +
                   " | account_ref=`" + str(rl.get("account_ref", "")) + "`" +
                   " | sizing=" + str(rl.get("sizing_mode", "?")))
    out += ["", "## 一览",
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
        sl = _semantic_line(r)
        if sl:
            out.append(sl)
        out.append(f"- **操作建议**:{jq.get('操作建议', '')}")
        if t["操作"] == "建仓":
            out.append(f"- 执行清单:入 {_cell(t['入'])} / 损 {_cell(t['损'])} / 盈一 {_cell(t['盈一'])} "
                       f"/ 盈二 {_cell(t['盈二'])} / 股数 {_cell(t['股数'])}")
        out.append(f"- 触发/说明:{_cell(t['触发条件'])}")
        out.append("")
    return "\n".join(out)


def write_weekly_markdown(weekly: dict, out_path: str) -> None:
    """渲染周报 .md。语义风险 advisory 自 Slice 3b 起**逐票行内化**(见 `_semantic_line`,从每票
    `machine.layer.semantic_risk` 渲染),不再有独立面板参数;advisory 仍只是引擎层 trace 的渲染,
    不进确定性周报 JSON、不改任何结论。"""
    md = render_weekly_markdown(weekly)
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
