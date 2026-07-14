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


def _holding_state(report: dict):
    """4.3-C:从 `machine.stateful_risk` 派生「持仓/冷静状态」标签 + 一句说明。**纯渲染、只解释**,
    不改 action/star/hard_veto/sizing。来源信息(trades/manual_controls/转换器推进)在转换器 lineage
    旁产物里,不在被引擎消费的 account_state 里,故此处不渲染「状态来源」(M6.7 推不出)。
    无账户 / 老报告(无 stateful_risk)→ ("—", "");持仓 → "已持仓"。空仓候选**并列所有适用标签**
    (组合级 Rule12 在前 + per-stock Rule13 在后,如 `Rule12冷静 + Rule13待复核`),重叠时不隐藏任一态
    (R-ASHORT-43C-HOLDING-STATE-MULTILABEL-DROP)。返回 (label, reason)。"""
    sr = (report.get("machine") or {}).get("stateful_risk") or {}
    if not sr:
        return "—", ""
    reason = "；".join(str(x) for x in (sr.get("reasons") or []))
    if sr.get("position_state") == "held":
        return "已持仓", reason
    # 空仓候选:组合并列所有适用态——组合级 Rule12 + per-stock Rule13 同时命中时两个都显示,
    # 不让 Rule13 盖掉组合级 Rule12 冷静/恢复(否则读者会以为只有单票冷静、看不出全组合也在冷静)。
    r12 = (sr.get("rule12") or {}).get("status")
    r13 = (sr.get("rule13") or {}).get("status")
    parts = []
    if r12 == "active_cooldown":
        parts.append("Rule12冷静")
    elif r12 == "recovery_1":
        parts.append("Rule12恢复")
    if r13 == "active_cooldown":
        parts.append("Rule13冷静")
    elif r13 == "pending_recheck":
        parts.append("Rule13待复核")
    elif r13 == "cleared_for_reentry":
        parts.append("Rule13可再入")
    return (" + ".join(parts) if parts else "空仓"), reason


# 持仓恒列入 S1: 账户持仓(非本周候选)的行来源(渲染分区用);其余 row_source(egs_candidate /
# egs_candidate_with_position / 缺省)归"本周 EGS 候选"段,保持既有渲染不变。
_HOLDING_SOURCES = ("account_position_egs_full", "account_position_only")
_ACCOUNT_ROW_SOURCES = _HOLDING_SOURCES + ("egs_candidate_with_position",)


def _weekly_has_account_data(weekly: dict) -> bool:
    """判断 weekly 是否含真实账户/持仓私密信息(决定 standalone 渲染是否需私密路径守门)。判据(任一):
    run_lineage.account_status=='provided'(带 --account 跑)/ 有 holdings_manual_review(真持仓无价旁路)/ 任一 report
    row_source 是账户持仓源 / 任一 operation_impact privacy_class 私密。无账户的 observation-only 周报 → False(不过度守门)。"""
    rl = weekly.get("run_lineage") or {}
    if rl.get("account_status") == "provided":
        return True
    if weekly.get("holdings_manual_review"):
        return True
    for rep in (weekly.get("reports") or []):
        if rep.get("row_source") in _ACCOUNT_ROW_SOURCES:
            return True
        for imp in ((rep.get("machine") or {}).get("operation_impact") or []):
            if imp.get("privacy_class") in ("private_account", "secret_or_raw_provider"):
                return True
    return False


def _has_semantic(report: dict) -> bool:
    """4.2 S2: 该持仓本周是否**真跑过语义**(非中性 trace)。`build_m67_report` 对所有行恒写 semantic_risk
    (候选行有意义),持仓无 semantic 输入时 trace 全 unknown → **不算已核查**(否则把"没核查"误标"已核查",
    违反 no-semantic-must-show-unchecked,R-...-S2-...-RENDER-DRIFT 残留);已核查 = official_status 或
    web_llm.status 任一非 unknown(核查了,无论 clear/risk)。已跑 → 显 S2 状态、不标 S1;未跑(无 trace / 全 unknown)→ 仍标未核查。"""
    sr = ((report.get("machine") or {}).get("layer") or {}).get("semantic_risk") or {}
    if not sr:
        return False
    return (sr.get("official_status", "unknown") != "unknown"
            or (sr.get("web_llm") or {}).get("status", "unknown") != "unknown")


def _coverage_label(report: dict) -> str:
    src = report.get("row_source")
    _sem = "语义已核查" if _has_semantic(report) else "语义未核查"
    # S1:所有注入持仓的语义/新闻层都未跑 → 标签必带"语义未核查";Tier-2 vs Tier-3 的区别在 EGS 维度。
    if src == "account_position_egs_full":
        return f"复用egs_full·{_sem}"
    if src == "account_position_only":
        return f"EGS未覆盖(粗筛)·{_sem}"
    if src == "egs_candidate_with_position":
        return "EGS候选·已持仓"
    return report.get("coverage_status") or "本周EGS"


def _card_field(report: dict, key: str) -> str:
    """coverage-aware 取 精简结论区 字段:**只有 EGS 未覆盖的 Tier-3 持仓(row_source=account_position_only)**
    才把 EGS 派生字段(否决审查触发/板块资金事件)显示为'未核查',**不让引擎 False-默认的'无'被误读成
    '已核查、无风险'**(§18.3 简化≠藏安全)。Tier-2(account_position_egs_full)EGS 真实评分过 → 原样显示
    (语义未核查另由专门一行标,见 _render_holdings_section);候选不受影响。"""
    val = report["m67"]["精简结论区"].get(key, "")
    if report.get("row_source") == "account_position_only" and key in ("否决审查触发", "板块资金事件"):
        # S2: 已跑语义的持仓,否决审查触发 含真实语义警告 → 不 mask(否则藏住 S2 警告)。
        if key == "否决审查触发" and _has_semantic(report):
            return val
        # 板块资金事件 含「龙虎榜对照」/「大宗交易对照」= 独立真取数(top_list/top_inst/block_trade,非 EGS 维度)→ 不掩;EGS 未覆盖另有专门一行标注。
        if key == "板块资金事件" and any(m in val for m in ("龙虎榜对照", "大宗交易对照")):
            return val
        return "未核查(本周 EGS 粗筛未覆盖,请人工核查 ST/新闻/监管)"
    return val


def _disposition_line(t: dict):
    """S3b R1+R2: 持仓处置 + 禁止加仓 逐票行(仅持仓行 table 带 持仓处置;候选行返回 None 不渲染)。
    S3b R3: reduce/clear disposition 附 advisory 减仓价/清仓价/减仓比例(复用 S3a 损/盈一,**不自动下单**);到价提示/移保本=R4a(见 _active_alert_line 行)、跨周持久收紧 ratchet=R4b。"""
    d = t.get("持仓处置")
    if not d:
        return None
    bits = [f"持仓处置:{d}（禁止加仓:{'是' if t.get('禁止加仓') else '否'}）"]
    if "清仓价" in t:
        _cp = t.get("清仓价")
        bits.append(f"清仓价(=系统止损):{_cp if _cp is not None else '未算出'}")
    if "减仓价" in t:
        _rp = t.get("减仓价")
        bits.append(f"减仓价(=盈一):{_rp if _rp is not None else '未算出'}、减仓比例:{t.get('减仓比例')}")
    return "- " + "；".join(bits) + "（advisory 复核建议,不自动下单;到价提示/移保本见 R4a 行、跨周持久收紧 ratchet=R4b）"


def _active_alert_line(r: dict):
    """S3b R4a: 持仓行 到价提示 + 移保本 逐票 advisory 行(读 machine.price_cross/move_to_breakeven,仅持仓行;无 advisory→None)。
    全 advisory:**不自动卖出 / 不自动改止损**;跨周持久收紧 ratchet = R4b。"""
    mc = r.get("machine") or {}
    pc = mc.get("price_cross")
    mtb = mc.get("move_to_breakeven") or {}
    bits = []
    if pc == "reduce_price_reached":
        bits.append("⚠️ 已到减仓价(=盈一):建议复核减仓")
    elif pc == "clear_price_reached":
        bits.append("⚠️ 已到清仓价(=系统止损):建议复核清仓")
    if mtb.get("triggered"):
        bits.append(f"浮盈已达1R:建议把保护止损上移至成本价 {mtb.get('breakeven_price')}（保本）")
    if not bits:
        return None
    return "- 到价/移保本:" + "；".join(bits) + "（advisory,不自动卖出 / 不自动改止损;跨周收紧=R4b）"


def _ratchet_line(r: dict):
    """S3b R4b: 持仓行 跨周持久收紧 ratchet 逐票 advisory 行(读 machine.ratchet,仅持仓行;无 ratchet→None,如非 --account/--skip-ratchet run)。
    建议保护止损 = 跨周只升不降 ratcheted_stop(不改系统止损 table.损);周数;跨周滚动到价(现价到上周减仓价/跌破跨周收紧止损)。全 advisory:不自动卖 / 不自动改止损。"""
    mc = r.get("machine") or {}
    rt = mc.get("ratchet")
    if not rt:
        return None
    rs = rt.get("ratcheted_stop")
    bits = [f"第{rt.get('week_count')}周{'·首周/换仓重置' if rt.get('bootstrap') else ''}",
            f"建议保护止损 {rs if rs is not None else '未算出'}（只升不降；不改系统止损）"]
    cw = rt.get("cross_week_price_cross")
    if cw == "reduce_price_reached":
        bits.append("⚠️ 现价已达上周减仓价(盈一):建议复核减仓")
    elif cw == "clear_price_reached":
        bits.append("⚠️ 现价已跌破跨周收紧止损:建议复核清仓")
    return "- 跨周 ratchet:" + "；".join(bits) + "（advisory,不自动卖出 / 不自动改止损）"


def _render_holdings_section(holding_reports: list, manual_review: list) -> list:
    """持仓恒列入 S1:渲染"账户持仓(非本周候选)"段 + "需人工管理(无价/停牌)"段。与"本周 EGS 候选"
    分区显示,避免把账户持仓误读成本周选中;partial 覆盖行显式标 EGS 未覆盖、不伪造安全。"""
    out = []
    if holding_reports:
        out += ["", "## 账户持仓(非本周 EGS 候选)",
                "> 这些是你账户里、但**本周没进 EGS top-N** 的持仓。`复用egs_full`=本周已评分;"
                "`EGS未覆盖(粗筛)`=本周 EGS 粗筛未覆盖,**仅价格/技术 + 账户状态;ST/新闻/监管未自动核查,请人工核查**。",
                "| 票 | 名称 | 操作 | 持仓处置 | 禁止加仓 | 持仓/冷静 | 覆盖 | 损(系统跟踪) | 盈一 | 盈二 | EGS分 |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in holding_reports:
            t = r["m67"]["table"]
            out.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                _cell(r.get("ts_code")), _cell(r.get("name")), _cell(t["操作"]),
                _cell(t.get("持仓处置")), ("是" if t.get("禁止加仓") else "否"),
                _cell(_holding_state(r)[0]), _coverage_label(r),
                _cell(t.get("损")), _cell(t.get("盈一")), _cell(t.get("盈二")), _cell(t.get("EGS分"))))
        out += ["", "### 账户持仓逐票"]
        for r in holding_reports:
            t = r["m67"]["table"]
            out.append(f"#### {_cell(r.get('ts_code'))} {_cell(r.get('name'))} — {t['操作']}（{_coverage_label(r)}）")
            for k in ("当前环境", "波动率状态", "现价与成本", "否决审查触发", "板块资金事件", "风控触发"):
                out.append(f"- {k}:{_card_field(r, k)}")
            hs_label, hs_reason = _holding_state(r)
            if hs_label not in ("空仓", "—"):
                out.append(f"- 持仓/冷静:{hs_label}" + (f"（{hs_reason}）" if hs_reason else ""))
            _dl = _disposition_line(t)          # S3b R1+R2: 持仓处置 + 禁止加仓(持仓行)
            if _dl:
                out.append(_dl)
            _al = _active_alert_line(r)         # S3b R4a: 到价提示 + 移保本(持仓行)
            if _al:
                out.append(_al)
            _rl = _ratchet_line(r)              # S3b R4b: 跨周持久收紧 ratchet(持仓行)
            if _rl:
                out.append(_rl)
            if r.get("row_source") == "account_position_only":   # Tier-3:EGS 维度也未覆盖
                out.append("- ⚠️ **EGS 未覆盖**:本周该持仓未进 EGS 评分集(粗筛排除),EGS 量化分/赛道未自动核查。")
            # S2: **真跑过语义**(_has_semantic: trace 非全 unknown)→ 显 S2 语义状态行(从 trace 渲染);未跑(无 trace / 全
            # unknown)→ 仍显式标未核查,绝不让缺失语义被读成"无利空 / 已核查"。用 _has_semantic(非 _semantic_line 非空)与
            # coverage label 口径一致:build_m67 对持仓恒写 unknown trace,_semantic_line 对它非空,会误显已核查(R-...-S2-RENDER-DRIFT)。
            if _has_semantic(r):
                out.append(_semantic_line(r))
            else:
                out.append("- ⚠️ **语义/新闻未核查(S1)**:本周未对该持仓自动核查 ST / 重大利空 / 监管 / 减持;请人工核查(S2 接入)。")
            if r.get("consistency_warning"):
                out.append(f"- ⚠️ 对账(4.3-D):{r['consistency_warning']}")
            out.append(f"- 执行清单(系统位):损 {_cell(t['损'])} / 盈一 {_cell(t['盈一'])} / 盈二 {_cell(t['盈二'])}"
                       "(止损无条件、盘中由你手动;系统跟踪止损=近20日高−ATR×倍数)")
            out.append(f"- **操作建议**:{r['m67']['精简结论区'].get('操作建议', '')}")
            out.append(f"- 触发/说明:{_cell(t['触发条件'])}")
            out.append("")
    if manual_review:
        out += ["", "## 账户持仓·需人工管理(无价/停牌/价格陈旧)",
                "> 以下持仓本周**抓不到一致的最新价**(停牌/无价/价格陈旧),系统**不下任何持有/止损结论**,请人工管理。",
                "| 票 | 名称 | 原因 |", "|---|---|---|"]
        for h in manual_review:
            out.append(f"| {_cell(h.get('ts_code'))} | {_cell(h.get('name'))} | {_cell(h.get('reason'))} |")
    return out


def render_weekly_markdown(weekly: dict) -> str:
    reports = weekly.get("reports", [])
    # 持仓恒列入 S1: 分区——"本周 EGS 候选"(既有渲染,保持不变)与"账户持仓(非本周候选)"分开。
    cand_reports = [r for r in reports if r.get("row_source") not in _HOLDING_SOURCES]
    holding_reports = [r for r in reports if r.get("row_source") in _HOLDING_SOURCES]
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
    # regime-unknown 全局横幅:把"全员保守压星"说成市场级状态,而非个股质量差(个股质量看下表「EGS分」)。
    if ("regime unknown" in env) or ("保守fallback" in env) or ("保守 fallback" in env):
        out.append("> ⚠️ **市场 regime 未知 → 全员按震荡期保守降级(统一 −1 星)**。星级反映的是**当前市场保守状态**,"
                   "不是个股质量差;**个股质量看下表「EGS分」列**。(V14.3 regime 分类器接入 production 前,每次实盘都会如此。)")
    # Slice 3b-2: durable run_lineage banner — esp. the no-account no-sizing warning so a reader of THIS
    # artifact (not just the terminal) cannot mistake a sizing-artifact 观察 for a real avoid signal.
    rl = weekly.get("run_lineage") or {}
    if rl:
        out.append("**run**:id=`" + str(rl.get("run_id", "?")) +
                   "` | candidate_digest=`" + str(rl.get("candidate_digest", "?")) +
                   "` | stage=" + str(rl.get("stage_status", "?")))
    if rl.get("sizing_mode") and rl.get("sizing_mode") != "sized":
        out.append("> ⚠️ **无账户(account_status=" + str(rl.get("account_status", "?")) +
                   "):仓位 sizing N/A —— 建仓候选会渲染为「观察」(可建股数/金额不足),这是 **sizing 假象、非真 avoid 信号**;"
                   "传 `--account` / `-Account`(account-state JSON: cash/positions/Rule12/Rule13)以获真 sizing/持仓判断。**")
    if rl:
        out.append("**lineage**:analysis_input=`" + str(rl.get("analysis_input", "?")) + "` | iv_feed=`" +
                   str(rl.get("iv_feed", "?")) + "` | account=" + str(rl.get("account_status", "?")) +
                   " | account_ref=`" + str(rl.get("account_ref", "")) + "`" +
                   " | sizing=" + str(rl.get("sizing_mode", "?")))
    snap = rl.get("account_snapshot") or {}
    if snap:
        out.append("**account snapshot**:facts_as_of=`" + str(snap.get("facts_as_of")) +
                   "` | decision_as_of=`" + str(snap.get("decision_as_of")) +
                   "` | snapshot_id=`" + str(snap.get("snapshot_id")) +
                   "` | positions=" + str(snap.get("positions_count", 0)) +
                   " | integrity=" + str(snap.get("integrity_status", "?")))
        if snap.get("integrity_status") == "blocked":
            out.append("> ⚠️ **账户持仓对账阻断**：禁止新开仓；已有持仓继续管理。原因=`" +
                       ",".join(snap.get("blocking_kinds") or []) + "`")
    ivf = rl.get("iv_freshness") or {}
    if ivf:
        out.append("**IV clock**:status=" + str(ivf.get("status")) +
                   " | IV数据截至 `" + str(ivf.get("iv_data_through")) + "`")
    mr = rl.get("market_regime") or {}
    if mr:
        out.append("**market regime**:source=`" + str(mr.get("source_status")) +
                   "` | effective=`" + str(mr.get("effective_status")) +
                   "` (" + str(mr.get("effective_regime")) + ") | fallback=" +
                   str(mr.get("fallback_active")).lower())
    # 价格时钟(诚实标注 M6.7 技术指标实际用到的价格日期;盘中容忍前一交易日时尤其要显眼,免得读者把
    # as_of=周一 误读成价格也到周一)。
    pf = rl.get("price_freshness") or {}
    if pf:
        out.append("**price clock**:mode=" + str(pf.get("mode", "?")) +
                   " | 价格数据截至 `" + str(pf.get("price_data_through", "?")) + "`" +
                   (" | run_date=`" + str(pf.get("run_date")) + "`" if pf.get("run_date") else "") +
                   (" | 前一交易日 `" + str(pf.get("accepted_prior_settled_date")) + "`"
                    if pf.get("accepted_prior_settled_date") else ""))
        if pf.get("mode") == "intraday_prior_settled" and str(pf.get("price_data_through")) != str(as_of):
            out.append("> ⚠️ **价格时钟**:本周报技术指标用的是**前一交易日(" + str(pf.get("price_data_through")) +
                       ")已结算行情**(实盘盘中跑、as_of " + str(as_of) + " 当日 EOD 尚未发布);新闻/语义层窗口仍到 as_of。"
                       "**价格特征截至 " + str(pf.get("price_data_through")) + ",非 " + str(as_of) + "。**")
    out += ["", "## 一览",
            "| 票 | 名称 | 操作 | 持仓/冷静 | EGS分 | 优先级 | 类型 | 入 | 损 | 盈一 | 盈二 | 股数 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in cand_reports:
        t = r["m67"]["table"]
        out.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            _cell(r.get("ts_code")), _cell(r.get("name")), _cell(t["操作"]), _cell(_holding_state(r)[0]),
            _cell(t.get("EGS分")), _cell(t["优先级"]), _cell(t["类型"]), _cell(t["入"]), _cell(t["损"]),
            _cell(t["盈一"]), _cell(t["盈二"]), _cell(t["股数"])))

    out += ["", "## 逐票"]
    for r in cand_reports:
        jq = r["m67"]["精简结论区"]
        t = r["m67"]["table"]
        out.append(f"### {_cell(r.get('ts_code'))} {_cell(r.get('name'))} — {t['操作']}　{_cell(t['优先级'])}")
        for k in ("当前环境", "波动率状态", "现价与成本", "否决审查触发", "板块资金事件", "风控触发"):
            out.append(f"- {k}:{jq.get(k, '')}")
        hs_label, hs_reason = _holding_state(r)      # 4.3-C:仅在持仓/冷静态显式标出(空仓/无账户不加噪音)
        if hs_label not in ("空仓", "—"):
            out.append(f"- 持仓/冷静:{hs_label}" + (f"（{hs_reason}）" if hs_reason else ""))
        sl = _semantic_line(r)
        if sl:
            out.append(sl)
        out.append(f"- **操作建议**:{jq.get('操作建议', '')}")
        _dl = _disposition_line(t)          # S3b R1+R2: held 候选(操作=持有)显 持仓处置 + 禁止加仓
        if _dl:
            out.append(_dl)
        _al = _active_alert_line(r)         # S3b R4a: 到价提示 + 移保本(held 候选)
        if _al:
            out.append(_al)
        _rl = _ratchet_line(r)              # S3b R4b: 跨周持久收紧 ratchet(held 候选)
        if _rl:
            out.append(_rl)
        if t["操作"] == "建仓":
            out.append(f"- 执行清单:入 {_cell(t['入'])} / 损 {_cell(t['损'])} / 盈一 {_cell(t['盈一'])} "
                       f"/ 盈二 {_cell(t['盈二'])} / 股数 {_cell(t['股数'])}")
        out.append(f"- 触发/说明:{_cell(t['触发条件'])}")
        out.append("")
    # 持仓恒列入 S1: 账户持仓(非本周候选)段 + 无价/停牌人工管理段(与候选分区显示)
    out += _render_holdings_section(holding_reports, weekly.get("holdings_manual_review") or [])
    # #1 除权除息提示(advisory,非决策):近端将除权的候选/持仓 —— 价已前复权,提醒未复权市价/成本将在除权日跳变。
    _notices = weekly.get("ex_div_notices") or []
    if _notices:
        out += ["", "## ⚠️ 除权除息提示(advisory · 非决策:价已前复权,提醒未复权市价/成本将在除权日跳变)",
                "| 票 | 名称 | 除权日 | 距今(日) |", "|---|---|---|---|"]
        out += [f"| {n['ts_code']} | {n['name']} | {n['ex_date']} | {n['days_to_ex']} |" for n in _notices]
    # 4.2 forward_events 第1刀: 未来已知事件日历(advisory · analysis-only · 不改决策)。unknown-not-clear: status=unknown → 显未核查/不可得,不当无事件。
    _ue = weekly.get("upcoming_events")
    if _ue:
        if _ue.get("status") == "checked":
            _uevs = _ue.get("events") or []
            out += ["", "## 📅 未来已知事件日历(advisory · analysis-only · 不改决策)"]
            if _uevs:
                out += ["| 票 | 名称 | 事件 | 事件日 | 距今(日) | 公告日(PIT) | 建议 | 来源 |", "|---|---|---|---|---|---|---|---|"]
                out += [f"| {e['ts_code']} | {e['name']} | {e['event_type']} | {e['event_date']} | {e['days_to_event']} | {e['observed_at']} | {e['expected_effect']} | {e['source_id']} |"
                        for e in _uevs]
            else:
                out.append("> 本周已查:候选/持仓近端无已公告的未来事件。")
            _unck = _ue.get("unchecked_codes") or []
            if _unck:                                  # per-(票,类) unknown-not-clear:部分票/类取数失败,显式标未核查(绝不当无事件)
                out.append(f"> ⚠️ 另有 {len(_unck)} 项未能核查未来事件(数据缺失/取数失败),**不代表无未来事件**,请人工核查:"
                           + "、".join(f"{u['ts_code']}{u['name']}({u['event_type']})" for u in _unck))
        else:
            out += ["", "## 📅 未来已知事件日历",
                    "> ⚠️ 未核查/不可得(`unknown_or_unavailable`):本周未取到未来事件日历(provider 未授权/不可用);**不代表无未来事件**,请人工核查解禁/财报等。"]
    # 4.2 Round5 龙虎榜(近N交易日 · comparison-only · 不改决策/EGS/选股):checked 列上榜 / unknown 显未核查(unknown-not-clear)。
    # 逐票 板块资金事件 已含「龙虎榜对照」(_card_field/逐票卡片自动渲染);此处为全局对照表 + unknown 可见性。
    _dl = weekly.get("dragon_list")
    if _dl:
        _n = _dl.get("lookback_trading_days")
        if _dl.get("status") == "checked":
            _dlevs = _dl.get("events") or []
            out += ["", f"## 🐯 龙虎榜(近{_n}交易日 · comparison-only · 不改决策/EGS/选股/股数)"]
            if _dlevs:
                def _seatcell(e):                     # 第二刀 席位:查成→「N席/机构净X」;未附(未核查日/未接线)→「未核查」
                    s = e.get("seats")
                    if s is None:
                        return "未核查"
                    inb = e.get("inst_net_buy")
                    return f"{len(s)}席" + (f"/机构净{inb}" if inb is not None else "")
                out += ["| 票 | 名称 | 上榜日 | 净额(原值) | 席位 | 原因 |", "|---|---|---|---|---|---|"]
                out += [f"| {e['ts_code']} | {e['name']} | {e['trade_date']} | "
                        f"{e['net_amount'] if e.get('net_amount') is not None else '—'} | {_seatcell(e)} | {e.get('reason') or '—'} |"
                        for e in _dlevs]
            else:
                out.append(f"> 本周已查:候选+持仓近{_n}交易日无上龙虎榜记录。")
            _udl = _dl.get("unchecked_dates") or []
            if _udl:                                  # per-交易日 unknown-not-clear:部分交易日取数失败,显式标(绝不当无上榜)
                out.append(f"> ⚠️ 另有 {len(_udl)} 个交易日未能核查龙虎榜(取数失败),**不代表无上榜**,请人工核查:"
                           + "、".join(_udl))
            if _dl.get("seats_status") == "unknown_or_unavailable":   # 第二刀 席位层未核查(unknown-not-clear)
                out.append("> ⚠️ 席位(top_inst)未核查/不可得:本周未取到龙虎榜席位明细;**不代表无机构/游资参与**,请人工核查。")
            _usd = _dl.get("unchecked_seat_dates") or []
            if _usd:
                out.append(f"> ⚠️ 另有 {len(_usd)} 个交易日席位(top_inst)取数失败,该日上榜「席位」栏显示「未核查」:"
                           + "、".join(_usd))
        else:
            out += ["", f"## 🐯 龙虎榜(近{_n}交易日)",
                    "> ⚠️ 未核查/不可得(`unknown_or_unavailable`):本周未取到龙虎榜(provider 未授权/不可用);**不代表无上榜**,请人工核查。"]
    # 4.2 Round5 大宗交易(近N交易日 · comparison-only · 不改决策/EGS/选股):checked 列大宗 / unknown 显未核查。
    _bt = weekly.get("block_trade")
    if _bt:
        _bn = _bt.get("lookback_trading_days")
        if _bt.get("status") == "checked":
            _btevs = _bt.get("events") or []
            out += ["", f"## 💰 大宗交易(近{_bn}交易日 · comparison-only · 不改决策/EGS/选股/股数)"]
            if _btevs:
                def _bttop(e):                            # 最大笔(按金额)party,买卖方/折价率同口径展示;无 parties→None
                    ps = e.get("parties") or []
                    return max(ps, key=lambda p: (p.get("amount") or 0)) if ps else None
                def _btparty(e):                          # 第二刀 买卖方: 最大笔的 买→卖 营业部(+其余笔数);无 parties→「—」
                    top = _bttop(e)
                    if top is None:
                        return "—"
                    ps = e.get("parties") or []
                    return f"{top.get('buyer') or '?'}→{top.get('seller') or '?'}" + (f"(+{len(ps) - 1})" if len(ps) > 1 else "")
                def _btdisc(e):                           # 第三刀 折价率: 最大笔的折价率(负=折价/抛压,正=溢价);未查成/无→「—」
                    top = _bttop(e)
                    d = top.get("discount") if top else None
                    return f"{d * 100:+.2f}%" if d is not None else "—"
                out += ["| 票 | 名称 | 成交日 | 成交金额(原值) | 笔数 | 买卖方(最大笔) | 折价率(最大笔) |", "|---|---|---|---|---|---|---|"]
                out += [f"| {e['ts_code']} | {e['name']} | {e['trade_date']} | "
                        f"{e['amount'] if e.get('amount') is not None else '—'} | {e['trade_count']} | {_btparty(e)} | {_btdisc(e)} |"
                        for e in _btevs]
            else:
                out.append(f"> 本周已查:候选+持仓近{_bn}交易日无大宗交易记录。")
            _btu = _bt.get("unchecked_dates") or []
            if _btu:
                out.append(f"> ⚠️ 另有 {len(_btu)} 个交易日未能核查大宗交易(取数失败),**不代表无大宗**,请人工核查:" + "、".join(_btu))
            _btdu = _bt.get("unchecked_discount_dates") or []
            if _bt.get("discount_status") == "unknown_or_unavailable":
                out.append("> ⚠️ 折价率未核查/不可得(当日收盘价取数失败),折价率列以「—」示,**不代表无折价**。")
            elif _btdu:
                out.append(f"> ⚠️ 另有 {len(_btdu)} 个交易日折价率未能核查(收盘价取数失败),该日折价率以「—」示,**不代表无折价**:" + "、".join(_btdu))
        else:
            out += ["", f"## 💰 大宗交易(近{_bn}交易日)",
                    "> ⚠️ 未核查/不可得(`unknown_or_unavailable`):本周未取到大宗交易(provider 未授权/不可用);**不代表无大宗**,请人工核查。"]
    # 4.2 财报质量趋势(②forecast/③income/④balancesheet · candidate-only · comparison-only · 不改决策/EGS/选股):checked 列红旗 / unknown 显未核查。
    # 逐票 风控触发 已含「财报趋势对照」(逐票卡片自动渲染);此处为全局红旗汇总 + unknown 可见性。
    _ft = weekly.get("financial_trends")
    if _ft:
        _ftlabel = {"forecast": "业绩预告", "income": "利润表", "balancesheet": "资产负债表"}
        if _ft.get("status") == "checked":
            _ftrecs = _ft.get("records") or []
            out += ["", "## 📊 财报质量趋势(candidate-only · comparison-only · 不改决策/EGS/选股/股数)"]
            if _ftrecs:
                out += ["| 票 | 名称 | 报表 | 报告期 | 公告日(PIT) | 红旗摘要 |", "|---|---|---|---|---|---|"]
                out += [f"| {r['ts_code']} | {r['name']} | {_ftlabel.get(r['statement_type'], r['statement_type'])} | "
                        f"{r['period']} | {r['observed_at']} | {r['summary']} |" for r in _ftrecs]
            else:
                out.append("> 本周已查:候选财报报表无红旗。")
            _ftu = _ft.get("unchecked_codes") or []
            if _ftu:                                  # per-(票,类) unknown-not-clear:部分票/类取数失败,显式标(绝不当无红旗)
                out.append(f"> ⚠️ 另有 {len(_ftu)} 项财报报表未能核查(数据缺失/取数失败),**不代表无红旗**,请人工核查:"
                           + "、".join(f"{u['ts_code']}{u['name']}({_ftlabel.get(u['statement_type'], u['statement_type'])})" for u in _ftu))
        else:
            out += ["", "## 📊 财报质量趋势",
                    "> ⚠️ 未核查/不可得(`unknown_or_unavailable`):本周未取到财报报表(provider 未授权/不可用);**不代表无红旗**,请人工核查业绩预告/利润表/资产负债表。"]
    # 4.2 财报质量趋势⑤ 行业基本面(advisory-only · summary_only · 候选 scope · 不改决策):按 SW L2 行业聚合③④候选财报红旗。只列有红旗行业。
    _indf = weekly.get("industry_fundamentals")
    if _indf and (_indf.get("by_industry") or []):
        out += ["", "## 🏭 行业基本面(advisory-only · 基于本周候选聚合③④财报红旗 · 非全行业普查 · 不改决策/EGS/选股)",
                "| SW二级行业 | 候选数 | 有红旗 | 红旗候选 | 摘要 |", "|---|---|---|---|---|"]
        out += [f"| {g['sw_l2_name']} | {g['candidate_count']} | {g['red_flag_candidate_count']} | "
                f"{'、'.join(g['red_flag_codes'])} | {g['summary']} |" for g in _indf["by_industry"]]
    # 4.2 Round2 上游过滤批次级摘要(无 M6.7 个股行,仅计数,不含个股/持仓 → public)
    _excl = weekly.get("exclusion_summary")
    if _excl:
        out += ["", f"## 本轮上游过滤摘要(批次级 · 无 M6.7 个股行 · 仅计数不含个股/持仓 · 共 {_excl['total_excluded']} 只)",
                _excl.get("m67_text", ""),
                "| 原因 | stage | 类型 | 只数 |", "|---|---|---|---|"]
        out += [f"| {r['source_field']} | {r['stage']} | {r['veto_class']} | {r['count']} |"
                for r in (_excl.get("by_reason") or [])]
    return "\n".join(out)


def write_weekly_markdown(weekly: dict, out_path: str, allow_nonprivate_account_out: bool = False) -> None:
    """渲染周报 .md。语义风险 advisory 自 Slice 3b 起**逐票行内化**(见 `_semantic_line`,从每票
    `machine.layer.semantic_risk` 渲染),不再有独立面板参数;advisory 仍只是引擎层 trace 的渲染,
    不进确定性周报 JSON、不改任何结论。

    **隐私/生产路径守门(standalone 第三写出路径)**:复用 weekly pipeline 同口径守门——无条件拒生产桶
    `result/a_short/<date>`;weekly 含真实账户/持仓数据时(`_weekly_has_account_data`)拒落仓库内非 gitignored 路径
    (防 git 提交泄漏持仓 .md),仓库外 / gitignored `state/a_short/weekly_private/<as_of>/` 放行,
    `--allow-nonprivate-account-out` 可显式放行。pipeline 主路径在入口已守门(本守门幂等、再确认);standalone
    main / 任意 caller 经本函数得同等守门(R-ASHORT-M67-RENDER-STANDALONE-PRIVACY-PROD-GUARD-GAP)。"""
    from runners.a_short_weekly_pipeline import (  # 延迟导入避免与 pipeline 形成模块级循环依赖
        _reject_production_output_path, _reject_nonprivate_account_output_path)
    _reject_production_output_path(out_path)                        # 无条件拒生产桶
    if _weekly_has_account_data(weekly):                            # 含账户/持仓 → 私密路径守门(git check-ignore 真值)
        _reject_nonprivate_account_output_path(out_path, True, allow_nonprivate_account_out)
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
    p.add_argument("--allow-nonprivate-account-out", action="store_true",
                   help="显式放行:weekly 含真实账户/持仓时允许输出落仓库内非私密目录(默认拒,防持仓 .md 被 git 提交泄漏)")
    args = p.parse_args(argv)
    with open(args.weekly, encoding="utf-8") as f:
        weekly = json.load(f)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.weekly)), "weekly_m67.md")
    write_weekly_markdown(weekly, out, allow_nonprivate_account_out=args.allow_nonprivate_account_out)
    print(f"[m67_render] {len(weekly.get('reports', []))} 票 -> {out}")


if __name__ == "__main__":
    main()
