#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short Phase 5 确定性执行引擎(批① part 2;Slice B v1).

实现父设计 `docs/a_short_theme_overlay_phase5_design_spec_20260610.md`(§3 四层 + 5 风险族 + M2.7
改造 + 执行字段 + 唯一输出 M6.7 + §4 不变量 + §9 周频边界 + §10 定性分层)。

**纯决策引擎**:吃一个**归一化输入**(候选 + 价格序列 + EGS 分 + Slice A overlay + IV feed +
账户 + 市场环境),产出一份 report:对外 `m67`(精简结论区 + 执行清单),机器层 `machine`(指标/
风险族/分层/消费映射,沉底可追溯)。真实 I/O(读 analysis_input / 前复权价 / overlay / iv_feed)
是执行期薄接线(批② pipeline),不在本引擎。

**底色(诚实护栏)**:A-short 是 `risk_filter_only`,edge 未验证。任何"建仓"必在操作建议行带
"试探仓 / edge 未验证 / 止损无条件"。不动 production / egs_main / V14.2;不真钱、不接券商、不自动下单。
**周频边界(§9)**:不监控盘中;只给周末预设价位 + 人工执行前提。
"""
from __future__ import annotations

import argparse
import json
import math
import os

import jsonschema

SCHEMA_NAME = "a_short_m67_report"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas", "a_short_m67_report.schema.json")
GOV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "presets", "a_short_phase5_engine_governance_20260610.json")

# ── 冻结阈值(参数化,与 governance artifact 逐字 parity;§4 阈值治理)──────────
REGIMES = ("进攻期", "震荡期", "防御期", "收缩期")
ATR_MULT = {"进攻期": 1.75, "震荡期": 1.25, "防御期": 1.0, "收缩期": 1.25}   # 主板中值
RR_FLOOR = {"进攻期": 1.5, "震荡期": 1.5, "防御期": 2.0, "收缩期": 1.5}
SINGLE_CAP_PCT = {"进攻期": 0.50, "震荡期": 0.40, "防御期": 0.25, "收缩期": 0.0}  # 收缩期禁新建仓
IV_HALVE_PCT = 80.0            # Rule 3:IV>80 分位 → 新建仓减半
IV_NOBUILD_PCT = 90.0          # Rule 3:IV>90 分位 → 不可建仓(硬)
OVERHEAT_5D = 8.0
OVERHEAT_20D = 22.0
MIN_AVG_AMOUNT_5D = 5e7        # 5日均成交额下限(流动性底线)
LOWXI_BAND = 0.015            # 低吸:现价在支撑 ±1.5%
SUPPORT_LOOKBACK = 20
RESISTANCE_LOOKBACK = 20
MIN_SHARES = 100
MIN_AMOUNT = 1e4
IMPACT_COST_FRAC = 0.005     # 单只建仓 ≤ 5日均成交额 × 0.5%(冲击成本)

GOVERNANCE = {
    "atr_mult": ATR_MULT, "rr_floor": RR_FLOOR, "single_cap_pct": SINGLE_CAP_PCT,
    "iv_halve_pct": IV_HALVE_PCT, "iv_nobuild_pct": IV_NOBUILD_PCT,
    "overheat_5d": OVERHEAT_5D, "overheat_20d": OVERHEAT_20D,
    "min_avg_amount_5d": MIN_AVG_AMOUNT_5D, "lowxi_band": LOWXI_BAND,
    "support_lookback": SUPPORT_LOOKBACK, "resistance_lookback": RESISTANCE_LOOKBACK,
    "min_shares": MIN_SHARES, "min_amount": MIN_AMOUNT, "impact_cost_frac": IMPACT_COST_FRAC,
}

RISK_FAMILIES = ("overheat_crowding", "liquidity_execution", "negative_event",
                 "market_regime", "portfolio_concentration", "semantic_official",
                 "semantic_web_llm")

# 语义 web/LLM 层(Slice 2)只允许产生 downgrade 的已评估风险态(绝不 hard_veto;tailwind/clear_light/unknown 不降级)
_WEB_DOWNGRADE_STATUSES = ("risk_candidate", "risk", "headwind")


# ── 技术指标(纯函数;price_series oldest→newest,每项 high/low/close)──────────
def ma(closes: list, n: int):
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def rsi14(closes: list, n: int = 14):
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(len(closes) - n, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def atr14(series: list, n: int = 14):
    if len(series) < n + 1:
        return None
    trs = []
    for i in range(len(series) - n, len(series)):
        h, l, pc = series[i]["high"], series[i]["low"], series[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def support_resistance(series: list):
    lows = [x["low"] for x in series[-SUPPORT_LOOKBACK:]]
    highs = [x["high"] for x in series[-RESISTANCE_LOOKBACK:]]
    return (min(lows) if lows else None, max(highs) if highs else None)


def compute_indicators(series: list) -> dict:
    closes = [x["close"] for x in series]
    sup, res = support_resistance(series)
    return {"ma5": ma(closes, 5), "ma10": ma(closes, 10), "ma20": ma(closes, 20),
            "rsi14": rsi14(closes), "atr14": atr14(series), "support": sup, "resistance": res}


# ── 语义官方层消费方校验(fail-closed,单一来源)────────────────────────────────
_SEM_STATUSES = ("risk", "clear", "unknown")
_SEM_SEVERITIES = ("high", "medium", "low")
# official_structured 事件证据形(与 build_official_structured 产出口径一致):驱动 M6.7 否决/待核
# 的官方证据必须齐全且 PIT,否则 fail-closed。url_or_pdf 单列(present+string,但允许空——见 validator)。
_SEM_EVENT_NONEMPTY = ("source", "title", "category", "disclosure_date", "risk_type", "severity")


def _validate_semantic_official(sem, as_of):
    """语义官方层(official_structured)消费契约,fail-closed:接受 None,或
    {status∈{risk,clear,unknown}, events:list[dict]}。每个 event:source/title/category/disclosure_date/
    risk_type/severity 必须 trim 后非空字符串、`source=="cninfo"`、`severity∈{high,medium,low}`、
    `disclosure_date` canonical 历法日且 `<= as_of`(PIT);`url_or_pdf` 必须 present+string,但**允许为空**
    (cninfo 偶缺 adjunctUrl——空 URL 不 abort,而在 build_m67_report 把缺 URL 的 high 事件降为 pending 待核,
    方案 A);且 clear/unknown 不得带 events、risk 必带 ≥1 event、`had_pit_announcements` bool 且 risk 时 True。
    非法/伪造/未来日/手工源/残缺非 url 字段 → ValueError(写盘前 abort)。返回同一已校验对象,
    family / impact / severity_max / trace 全部据此派生。"""
    if sem is None:
        return None
    if not isinstance(sem, dict):
        raise ValueError(f"semantic official 非 dict:{type(sem).__name__}")
    status = sem.get("status")
    if status not in _SEM_STATUSES:
        raise ValueError(f"semantic official status 非法:{status!r}")
    events = sem.get("events", [])
    if not isinstance(events, list):
        raise ValueError(f"semantic official events 非 list:{type(events).__name__}")
    for e in events:
        if not isinstance(e, dict):
            raise ValueError(f"semantic official event 非 dict:{type(e).__name__}")
        # 证据字段(除 url_or_pdf 外)必须 trim 后非空字符串(present-but-empty/纯空白 拒)。
        for k in _SEM_EVENT_NONEMPTY:
            v = e.get(k)
            if not (isinstance(v, str) and v.strip()):
                raise ValueError(f"semantic official event 证据字段 {k} 缺失/空/非字符串:{v!r}")
        # url_or_pdf 必须 present + string,但**允许为空**(cninfo 偶缺 adjunctUrl,build_official_structured
        # 会 emit "")。Slice 1b 方案 A:空 URL 不 abort、也不驱动否决——build_m67_report 把"缺 URL 的 high
        # 事件"降为 pending 待核(证据不全)。这里只保证类型,空值的 veto 降级在 build 层处理。
        if not isinstance(e.get("url_or_pdf"), str):
            raise ValueError(f"semantic official event url_or_pdf 非字符串:{e.get('url_or_pdf')!r}")
        if e["source"] != "cninfo":
            raise ValueError(f"semantic official event source 非 official cninfo:{e['source']!r}")
        if e["severity"] not in _SEM_SEVERITIES:
            raise ValueError(f"semantic official event severity 非法:{e['severity']!r}")
        dd = e["disclosure_date"]
        if not _is_valid_date(dd):
            raise ValueError(f"semantic official event disclosure_date 非 canonical 历法日:{dd!r}")
        if str(dd) > str(as_of):
            raise ValueError(f"semantic official event disclosure_date {dd} > as_of {as_of}(PIT 泄漏)")
    if status in ("clear", "unknown") and events:
        raise ValueError(f"semantic official status={status} 不得带 events(自相矛盾)")
    if status == "risk" and not events:
        raise ValueError("semantic official status=risk 必带 ≥1 event(自相矛盾)")
    hpa = sem.get("had_pit_announcements")
    if not isinstance(hpa, bool):
        raise ValueError(f"semantic official had_pit_announcements 非 bool:{type(hpa).__name__}")
    if status == "risk" and not hpa:
        raise ValueError("semantic official status=risk 但 had_pit_announcements=False(自相矛盾)")
    return sem


# ── 风险族分类(§5 归并:每族最多一次硬处理)──────────────────────────────────
def classify_risk_families(inp: dict, ind: dict) -> dict:
    d = inp.get("derived", {})
    ev = inp.get("event", {})
    liq = inp.get("liquidity", {})
    iv_pct = (inp.get("iv") or {}).get("iv_percentile_252d")
    regime = inp.get("market_regime", "震荡期")
    fam = {f: {"hit": False, "action": None, "reasons": []} for f in RISK_FAMILIES}

    # overheat_crowding(含 overlay crowding;一次硬处理)
    oh = bool(d.get("overheat") or d.get("chasing_high") or d.get("chase")
              or (inp.get("overlay") or {}).get("crowding_hit"))
    if oh:
        fam["overheat_crowding"].update(hit=True, action="downgrade", reasons=["过热/追高/拥挤"])

    # liquidity_execution
    lr = []
    if (liq.get("avg_amount_5d") or 0) < MIN_AVG_AMOUNT_5D:
        lr.append("5日均成交额低于底线")
    if d.get("limit_locked"):
        lr.append("涨跌停锁")
    if d.get("suspended"):
        lr.append("停牌")
    if lr:
        fam["liquidity_execution"].update(hit=True, action="hard_veto", reasons=lr)

    # negative_event(硬否决)
    ner = []
    if ev.get("holder_reduction_active"):
        ner.append("减持进行中")
    if ev.get("st_or_delisting"):
        ner.append("ST/退市")
    if d.get("crash_veto"):
        ner.append("闪崩")
    if d.get("hard_veto"):
        ner.append("EGS hard_veto(上游聚合,无条件否决)")  # 即使分解原因未单独命中也硬杀
    if ev.get("regulatory_legacy_vetoed"):
        ner.append("EGS 上游监管 veto(legacy)")  # §10:上游 legacy 已剔,这里只记录
    if ner:
        fam["negative_event"].update(hit=True, action="hard_veto", reasons=ner)

    # market_regime(IV 闸门 + 防御/收缩)
    mr = []
    if iv_pct is not None and iv_pct > IV_NOBUILD_PCT:
        mr.append(f"IV分位{iv_pct}>{IV_NOBUILD_PCT} 不可建仓")
        fam["market_regime"].update(hit=True, action="hard_veto", reasons=mr)
    elif regime == "收缩期":
        fam["market_regime"].update(hit=True, action="hard_veto", reasons=["收缩期禁新建仓"])
    elif iv_pct is not None and iv_pct > IV_HALVE_PCT:
        fam["market_regime"].update(hit=True, action="downgrade", reasons=[f"IV分位{iv_pct}>{IV_HALVE_PCT} 减半"])

    # portfolio_concentration
    pc = []
    if (inp.get("portfolio") or {}).get("same_l2_exposure_over_cap"):
        pc.append("同 SW L2 暴露超限")
    if (inp.get("portfolio") or {}).get("factor_resonance"):
        pc.append("因子共振")
    if pc:
        fam["portfolio_concentration"].update(hit=True, action="downgrade", reasons=pc)
    # semantic_official 由 build_m67_report 用 _validate_semantic_official 校验后的对象统一填充
    # (family / impact / trace 同源,避免 status↔events 不一致)。
    return fam


# ── 入场类型 / 止损止盈 / 仓位(M2.7 收紧 + Rule 7 ATR + §9)────────────────────
def entry_type(inp: dict, ind: dict):
    close = inp.get("close")
    sup, ma5, ma10, ma20 = ind.get("support"), ind.get("ma5"), ind.get("ma10"), ind.get("ma20")
    if close is None:
        return "观察", "现价缺失"
    if ma5 and ma10 and ma20 and close < ma5 and close < ma10 and close < ma20:
        return "观察", "现价跌破 MA5/10/20,等收复"
    if inp.get("derived", {}).get("breakout") and ma10 and close >= ma10 and inp.get("derived", {}).get("vol_confirm"):
        return "突破", "站稳 MA10 + 放量"
    if sup and abs(close - sup) / sup <= LOWXI_BAND:
        return "低吸", "现价近关键支撑"
    return "观察", "未到低吸/突破触发"


def exit_and_size(inp: dict, ind: dict, regime: str, extra_halve: bool = False, halve_reason: str = ""):
    """返回 (entry, stop, t1, t2, rr, rr_floor, shares, sizing_notes) 或拒绝原因。
    extra_halve:IV>80(Rule3)或 IV feed 缺失(保守)时在试探仓基础上再减半。"""
    close, sup, res, atr = inp.get("close"), ind.get("support"), ind.get("resistance"), ind.get("atr14")
    notes = []
    if close is None or sup is None or atr is None or atr <= 0:
        return None, "缺价/支撑/ATR,无法精算"
    stop = sup - ATR_MULT.get(regime, 1.25) * atr
    # M2.7 收紧:只对明显坏结构硬停
    if stop >= close or close <= sup:
        return None, "现价≤支撑或止损≥现价(明显无效结构)"
    risk = close - stop
    rr_floor = RR_FLOOR.get(regime, 1.5)
    t1 = res if (res and res > close) else close + rr_floor * risk
    t2 = max(t1 + ATR_MULT.get(regime, 1.25) * atr, close + 2.0 * risk)
    rr = (t1 - close) / risk if risk > 0 else 0.0
    if rr < rr_floor:
        return None, f"盈亏比 {rr:.2f} < {rr_floor}"
    # 仓位:单只上限 + 冲击成本 + 100股 + 试探仓(诚实护栏)+ IV 减半
    cap_pct = SINGLE_CAP_PCT.get(regime, 0.40)
    if cap_pct <= 0:
        return None, "本环境禁新建仓"
    avail = (inp.get("account") or {}).get("available_cash") or 0.0
    amt5 = (inp.get("liquidity") or {}).get("avg_amount_5d") or 0.0
    cap = min(avail * cap_pct, amt5 * IMPACT_COST_FRAC)
    cap *= 0.5            # 试探仓:edge 未验证,默认半仓打底
    notes.append("试探仓(edge 未验证,默认上限×0.5)")
    if extra_halve:
        cap *= 0.5
        notes.append(halve_reason or "保守再减半")
    shares = int(cap // close // 100) * 100 if close > 0 else 0
    if shares < MIN_SHARES or shares * close < MIN_AMOUNT:
        return None, "可建股数/金额不足(放弃)"
    return {"entry": round(close, 3), "stop": round(stop, 3), "t1": round(t1, 3),
            "t2": round(t2, 3), "rr": round(rr, 3), "rr_floor": rr_floor,
            "shares": shares, "sizing_notes": notes}, None


def compute_star(inp: dict, fam: dict, eligible: bool) -> int:
    star = 3
    if eligible:
        star += 1                         # overlay 赛道红利
    if inp.get("industry_trend") == "headwind":
        star -= 1
    for f in ("overheat_crowding", "portfolio_concentration"):
        if fam[f]["hit"]:
            star -= 1
    return max(1, min(5, star))


# ── 组装 M6.7 报告(唯一对外 m67 + 机器层 machine + 消费映射)──────────────────
def _web_llm_error(web, sources):
    """web_llm 跨字段不变式校验(单一来源 = a_short_semantic_risk_summary,lazy import 防循环依赖)。
    返回错误字符串(或残缺结构的描述)/ None。结构残缺一律视为非法(fail-closed)。"""
    from runners.a_short_semantic_risk_summary import _web_llm_consistency_error
    try:
        return _web_llm_consistency_error(web, sources)
    except (KeyError, TypeError) as e:
        return f"web_llm 结构残缺:{e}"


def build_m67_report(inp: dict, as_of: str, generated_at: str) -> dict:
    ind = compute_indicators(inp.get("price_series", []))
    fam = classify_risk_families(inp, ind)
    regime = inp.get("market_regime", "震荡期")
    iv_pct = (inp.get("iv") or {}).get("iv_percentile_252d")
    eligible = bool((inp.get("overlay") or {}).get("eligible"))

    # 语义官方层(Slice 1,advisory):先 fail-closed 校验(非法 provider 输出 → 写盘前 abort),
    # 再用**同一已校验对象**派生 family / impact / trace(避免 status↔events 不一致 / 非 dict AttributeError)。
    # 经校验后:有 events ⟺ status==risk,severity 合法。**证据齐全(非空 url_or_pdf)的 high** → semantic_official
    # hard_veto(进下方 hard→否决,绝不救回);**缺 URL 的 high → 待核(不否决)**;medium/low → 仅"待核"
    # (不扣分/不清/不降星);clear/unknown/无输入 → 中性。(下方 high_full/high_incomplete 实现此分流)
    sem = _validate_semantic_official(inp.get("semantic"), as_of)
    sem_status = sem.get("status") if sem else "unknown"          # None → unknown(中性)
    sem_events = sem["events"] if (sem and sem_status == "risk") else []
    sem_sevs = [e["severity"] for e in sem_events]
    # 方案 A(Slice 1b):只有**证据齐全(含非空 url_or_pdf)**的 high 事件才驱动 M6.7 否决;
    # high 但缺 URL/PDF(cninfo 偶缺 adjunctUrl)→ 证据不全,降为"待核"(不否决、不崩);medium/low 同样仅待核。
    high_full = [e for e in sem_events if e["severity"] == "high" and e["url_or_pdf"].strip()]
    high_incomplete = [e for e in sem_events if e["severity"] == "high" and not e["url_or_pdf"].strip()]
    if high_full:
        fam["semantic_official"].update(
            hit=True, action="hard_veto",
            reasons=[f"语义官方:{e['risk_type']}(high)" for e in high_full])
    sem_has_high = bool(high_full)                                # 仅证据齐全 high 计 veto
    sem_pending = bool(sem_events) and not high_full             # risk 有事件但无证据齐全 high → 待核

    # 语义 web/LLM 层(Slice 2,advisory,DeepSeek 判官)。输入 inp["semantic_web_llm"] =
    # {"web_llm": {...}, "sources": [...]} 或 None。校验复用 _web_llm_consistency_error(单一来源)。
    # 影响(§8.4):risk_candidate/risk/headwind 且有 sources → downgrade(**绝不 hard_veto**);
    # tailwind/clear_light 不降级、不救回硬风控;unknown/无输入 → 中性。**非法 web 中性化 + trace 标记
    # (advisory 非阻断,绝不 abort/raise,区别于 official 的 fail-closed abort)。**
    sw = inp.get("semantic_web_llm")
    web = sw.get("web_llm") if isinstance(sw, dict) else None
    web_sources = (sw.get("sources") or []) if isinstance(sw, dict) else []
    web_invalid = (sw is not None) and (not isinstance(web, dict)
                                        or _web_llm_error(web, web_sources) is not None)
    if web_invalid:
        web, web_sources = None, []
    web_status = web["status"] if web else "unknown"
    web_downgrade = bool(web) and web_status in _WEB_DOWNGRADE_STATUSES
    if web_downgrade:
        fam["semantic_web_llm"].update(
            hit=True, action="downgrade",
            reasons=[f"语义web/LLM:{web_status}({web.get('risk_level')})"])

    hard = [r for f in RISK_FAMILIES if fam[f]["action"] == "hard_veto" for r in fam[f]["reasons"]]
    downgrades = [r for f in RISK_FAMILIES if fam[f]["action"] == "downgrade" for r in fam[f]["reasons"]]
    observe = list(inp.get("observe_only") or [])     # 缺数据项(§3 层3 / §9 盘中类不在此,见 out_of_scope)
    llm_notes = list(inp.get("llm_enrichment") or []) # §10 Tier C:只解释,不改判决

    if sem_pending:
        sem_reason = ("官方 high 缺 URL/PDF 证据(证据不全)" if high_incomplete else "官方 medium/low 命中(例行件)")
        observe.append(f"semantic_pending_review={sem_reason}(待核,未扣分)")
    else:
        sem_reason = ""
    sem_impact = "veto" if sem_has_high else ("pending" if sem_pending else "none")
    sem_note = (f"语义待核:{sem_reason},待复核(未扣分,待 web/LLM 实判)" if sem_pending else "")

    # IV 状态(R-ASHORT-PHASE5-IV-MISSING-FAIL-OPEN):feed 缺失不假装执行 IV 风控
    iv_known = iv_pct is not None
    iv_status = "ok" if iv_known else "observe_only_missing_feed"
    iv_halve = (iv_known and IV_HALVE_PCT < iv_pct <= IV_NOBUILD_PCT and regime != "收缩期")
    if not iv_known:
        observe.append("iv_regime_status=observe_only_missing_feed")
    extra_halve = iv_halve or (not iv_known)
    halve_reason = ("IV>80分位 Rule3 再减半" if iv_halve
                    else ("IV feed 缺失,保守再减半" if not iv_known else ""))

    # 决策
    if hard:
        action, etype, plan, reject = "否决", "N/A", None, "|".join(hard)
    else:
        etype, etype_reason = entry_type(inp, ind)
        if etype == "观察":
            action, plan, reject = "观察", None, etype_reason
        else:
            plan, reject = exit_and_size(inp, ind, regime, extra_halve, halve_reason)
            action = "建仓" if plan else "观察"
    star = compute_star(inp, fam, eligible) if action != "否决" else 0

    # 操作建议行(诚实护栏:建仓必带置信/试探/止损)
    if action == "建仓":
        iv_caveat = "" if iv_known else " **IV feed 缺失,未执行 IV 风控,仓位已保守再减半**。"
        advice = (f"低吸/突破建仓建议(类型:{etype})。⭐×{star}、盈亏比 {plan['rr']}。"
                  f"**试探仓**(edge 未验证,A-short 仅 risk_filter_only)。"
                  f"**止损 {plan['stop']} 无条件执行(盘中由你手动)**。" + iv_caveat)
    elif action == "观察":
        advice = f"观察,不建仓。原因:{reject}。" + (f"降级:{'/'.join(downgrades)}。" if downgrades else "")
    else:
        advice = f"否决,禁止建仓。硬否决:{reject}。"

    # 消费映射(§4 消费完整性:每个被消费输入 → 它对 m67 的影响)
    consumption = {
        "indicators": "→ 入场类型/止损/止盈/盈亏比/股数",
        "risk_families": "→ hard_veto(否决)/ downgrade(降星·减仓)/ market_regime(IV闸门)",
        "overlay.eligible": "→ 星级(赛道红利)",
        "iv.iv_percentile_252d": "→ Rule3 IV 闸门(>90否决 / >80减半)",
        "industry_trend": "→ 逆风降星",
        "observe_only": "→ M6.5 观察项(不改动作);缺数据保守",
        "llm_enrichment": "→ M6.7 风险摘要(不改 deterministic decision)",
        "account/liquidity": "→ 仓位上限/冲击成本/100股",
        "semantic": "→ semantic_official 族(official high **且证据齐全(非空 url_or_pdf)**→否决;缺 URL 的 high→待核;"
                    "medium·low→待核不扣分)/ semantic_web_llm 族(web risk/headwind **有 sources 证据→downgrade,绝不 hard_veto**;"
                    "tailwind/clear_light 不救回硬风控;unknown/无输入/违反契约→中性)/ trace machine.layer.semantic_risk",
    }

    table = {
        "操作": action,
        "股数": (plan["shares"] if plan else None),
        "入": (plan["entry"] if plan else None),
        "盈一": (plan["t1"] if plan else None),
        "盈二": (plan["t2"] if plan else None),
        "损": (plan["stop"] if plan else None),
        "类型": (etype if action == "建仓" else "N/A"),
        "优先级": (f"⭐×{star}" if star else "—"),
        "触发条件": (f"现价≤{plan['entry']};持仓周期1-3周;{';'.join(plan['sizing_notes'])}"
                     if plan else (reject or "")),
    }
    m67 = {
        "精简结论区": {
            "当前环境": regime,
            "波动率状态": (f"IV分位≈{iv_pct}% | Rule3减半:{'是' if iv_halve else '否'}"
                          if iv_known else "IV未知(feed 缺失,未执行 IV 风控,保守减半)"),
            "现价与成本": f"{inp.get('close')} | 试探仓",
            "否决审查触发": (("|".join(hard) + (" | " + sem_note if sem_note else "")) if hard
                              else (sem_note if sem_note else "无")),
            "板块资金事件": (inp.get("industry_trend") or "unknown") +
                            (f" | {'/'.join(llm_notes)}" if llm_notes else ""),
            "风控触发": ("|".join(downgrades) if downgrades else "无"),
            "操作建议": advice,
        },
        "table": table,
    }
    return {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "ts_code": str(inp.get("ts_code", "")), "name": str(inp.get("name", "")),
        "m67": m67,
        "machine": {
            "indicators": ind, "risk_families": fam,
            "layer": {"hard_veto": hard, "downgrade": downgrades,
                      "observe_only": observe, "llm_enrichment": llm_notes,
                      "semantic_risk": {
                          "official_status": sem_status,
                          "severity_max": ("high" if "high" in sem_sevs else  # 全事件(含缺证据 high)
                                           ("medium" if "medium" in sem_sevs else
                                            ("low" if "low" in sem_sevs else None))),
                          "events": (list(sem["events"]) if sem else []),
                          "impact": sem_impact,    # veto(证据齐全 high→否决) / pending(待核) / none
                          "evidence_incomplete_high": len(high_incomplete),  # high 但缺 URL/PDF → 仅待核
                          "web_llm": {"status": web_status,
                                      "risk_level": (web.get("risk_level") if web else "unknown"),
                                      "action": (web.get("action") if web else "no_action"),
                                      "sources_count": len(web_sources),
                                      "impact": ("downgrade" if web_downgrade else "none"),
                                      "invalid_neutralized": web_invalid}}},
            "entry_exit_size_star": {"action": action, "type": etype if action != "否决" else "N/A",
                                     "star": star, "plan": plan, "reject_reason": reject},
            "iv_gate": {"iv_percentile_252d": iv_pct, "halve": iv_halve, "status": iv_status},
            "consumption": consumption,
        },
        "boundary": {"production": False, "real_money": False,
                     "is_validated_alpha": False, "satisfies_ship_gate": False},
    }


def _is_valid_date(s) -> bool:
    from datetime import datetime
    try:
        datetime.strptime(str(s), "%Y%m%d")
        return True
    except ValueError:
        return False


def validate_m67_consistency(report: dict) -> None:
    """§4 不变量 + R-ASHORT-M67-...-WRITE-CONTRACT:消费完整性 / 热度不覆盖硬风控 / 诚实护栏 /
    每族一次 / as_of 历法 / table↔machine 一致 / 建仓正数+plan匹配 / 非建仓 null / IV缺失显式。"""
    mc = report["machine"]
    m67 = report["m67"]
    tbl = m67["table"]
    action = mc["entry_exit_size_star"]["action"]
    plan = mc["entry_exit_size_star"].get("plan")
    # as_of 历法
    if not _is_valid_date(report["as_of"]):
        raise ValueError("as_of 非合法日历日期")
    # 每族最多一次硬处理
    for f, v in mc["risk_families"].items():
        if v["hit"] and v["action"] not in ("hard_veto", "downgrade"):
            raise ValueError(f"风险族 {f} 命中但 action 非法")
    # 热度不覆盖硬风控:有 hard_veto → 必否决
    if mc["layer"]["hard_veto"] and action != "否决":
        raise ValueError("存在 hard_veto 却未否决(热度/分数不得救回硬风控)")
    # table 操作必须 == machine action
    if tbl["操作"] != action:
        raise ValueError("M6.7 table 操作 与 machine action 不一致")
    if action == "建仓":
        # 诚实护栏
        adv = m67["精简结论区"]["操作建议"]
        if not ("试探仓" in adv and "止损" in adv and "未验证" in adv):
            raise ValueError("建仓建议缺 试探仓/止损/edge未验证(诚实护栏)")
        # 必须有 plan,且 table 数值为正并与 plan 一致
        if plan is None:
            raise ValueError("建仓但 machine plan 为空")
        for k in ("入", "盈一", "盈二", "损"):
            if tbl[k] is None or tbl[k] <= 0:
                raise ValueError(f"建仓但 table {k} 非正")
        if tbl["股数"] is None or tbl["股数"] <= 0:
            raise ValueError("建仓但 股数 非正")
        if (tbl["股数"] != plan.get("shares")
                or abs(tbl["入"] - plan.get("entry", -1)) > 1e-9
                or abs(tbl["盈一"] - plan.get("t1", -1)) > 1e-9
                or abs(tbl["盈二"] - plan.get("t2", -1)) > 1e-9
                or abs(tbl["损"] - plan.get("stop", -1)) > 1e-9):
            raise ValueError("M6.7 table 数值与 machine plan 不一致(股数/入/盈一/盈二/损)")
    else:  # 观察 / 否决:交易字段必须全 null
        for k in ("股数", "入", "盈一", "盈二", "损"):
            if tbl[k] is not None:
                raise ValueError(f"非建仓({action})但 table {k} 非空")
    # IV 缺失必须显式 observe + 波动率状态标 IV未知(不 fail-open)
    if mc["iv_gate"].get("status") == "observe_only_missing_feed":
        if not any("iv_regime_status" in str(o) for o in mc["layer"]["observe_only"]):
            raise ValueError("IV feed 缺失但 observe_only 未标 iv_regime_status")
        if "IV未知" not in m67["精简结论区"]["波动率状态"]:
            raise ValueError("IV 缺失但波动率状态未标 IV未知")
    # 消费完整性
    for key in ("indicators", "risk_families", "iv.iv_percentile_252d", "overlay.eligible"):
        if key not in mc["consumption"]:
            raise ValueError(f"消费映射缺 {key}(悬挂输入)")
    # boundary 不得声称已验证
    if any(report["boundary"].values()):
        raise ValueError("boundary 必须全 false(非 production/真钱/已验证/ship-gate)")


def write_m67_report(report: dict, out_path: str) -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(report, schema)
    validate_m67_consistency(report)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def main(argv=None):
    p = argparse.ArgumentParser(description="A-short Phase 5 deterministic engine (M6.7-only)")
    p.add_argument("--engine-input", required=True, help="归一化输入 JSON(批② pipeline 产出)")
    p.add_argument("--as-of", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    # NOTE: 归一化输入的真实接线(analysis_input + 前复权价 + overlay + iv_feed + 账户/环境)
    # 由批② 周末 pipeline 负责;本引擎是纯决策核,已单测。
    raise SystemExit("[INFO] normalized-input wiring is batch-② pipeline work; pure engine is unit-tested. "
                     "See design + tests.")


if __name__ == "__main__":
    main()
