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
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP, ROUND_DOWN

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
BREAKOUT_RR_BONUS = 0.5       # #6 V14.2 迁移(proposal §6 首项):突破型追高 entry_high 在现价上方、风险更大 → RR 门在 regime 基础上 +0.5(只建仓侧;持仓无 etype 不受影响)
SINGLE_CAP_PCT = {"进攻期": 0.50, "震荡期": 0.40, "防御期": 0.25, "收缩期": 0.0}  # 收缩期禁新建仓
IV_HALVE_PCT = 80.0            # Rule 3:IV>80 分位 → 新建仓减半
IV_NOBUILD_PCT = 90.0          # Rule 3:IV>90 分位 → 不可建仓(硬)
IV_HV_RATIO_HI = 1.2          # #6 IV-HV advisory:IV/HV ≥ 此 → 隐含显著高于已实现(期权偏贵/避险情绪);纯信息,不改 decision
IV_HV_RATIO_LO = 0.9          # #6 IV-HV advisory:IV/HV ≤ 此 → 隐含低于已实现(情绪偏松/或低估波动);纯信息,不改 decision
OVERHEAT_5D = 8.0
OVERHEAT_20D = 22.0
MIN_AVG_AMOUNT_5D = 5e7        # 5日均成交额下限(流动性底线)
LOWXI_BAND = 0.015            # 低吸:现价在支撑 ±1.5%
SUPPORT_LOOKBACK = 20
RESISTANCE_LOOKBACK = 20
SR_SPIKE_ATR = 1.0            # #5 有效支撑:最低 low 比次低 low 还低 > 1×ATR → 判单日插针,支撑取次低(抗单日极值)
SR_QUALITY = ("strong", "weak", "fallback_extreme")   # 有效支撑质量标记(strong=极值被次低背书 / weak=插针被剔→取次低 / fallback_extreme=无法评估退原始极值)
MIN_SHARES = 100
MIN_AMOUNT = 1e4
IMPACT_COST_FRAC = 0.005     # 单只建仓 ≤ 5日均成交额 × 0.5%(冲击成本)

GOVERNANCE = {
    "atr_mult": ATR_MULT, "rr_floor": RR_FLOOR, "single_cap_pct": SINGLE_CAP_PCT,
    "iv_halve_pct": IV_HALVE_PCT, "iv_nobuild_pct": IV_NOBUILD_PCT,
    "iv_hv_ratio_hi": IV_HV_RATIO_HI, "iv_hv_ratio_lo": IV_HV_RATIO_LO,
    "overheat_5d": OVERHEAT_5D, "overheat_20d": OVERHEAT_20D,
    "min_avg_amount_5d": MIN_AVG_AMOUNT_5D, "lowxi_band": LOWXI_BAND,
    "support_lookback": SUPPORT_LOOKBACK, "resistance_lookback": RESISTANCE_LOOKBACK,
    "sr_spike_atr": SR_SPIKE_ATR, "breakout_rr_bonus": BREAKOUT_RR_BONUS,
    "min_shares": MIN_SHARES, "min_amount": MIN_AMOUNT, "impact_cost_frac": IMPACT_COST_FRAC,
}

RISK_FAMILIES = ("overheat_crowding", "liquidity_execution", "negative_event",
                 "market_regime", "portfolio_concentration", "semantic_official",
                 "semantic_web_llm", "stateful_risk")

# 语义 web/LLM 层(Slice 2)只允许产生 downgrade 的已评估风险态(绝不 hard_veto;tailwind/clear_light/unknown 不降级)
_WEB_DOWNGRADE_STATUSES = ("risk_candidate", "risk", "headwind")
# 4.2 第3轮:semantic advisory 否决的用户可见标记(单一来源)。m67_advisory_veto 必须在
# 否决审查触发/操作建议中标此串(非生产、不进 EGS/回测),与 production hard veto 物理区分;
# guard(validate_operation_impact_no_dangling ⑨)按此串校验,缺则 fail。
ADVISORY_VETO_TAG = "非生产 advisory"

# ── #6 IV-HV advisory(市场级 50ETF 隐含 vs 已实现;纯信息,绝不改 decision)──────────
IV_HV_REGIMES = ("iv_rich", "iv_inline", "iv_cheap", "unknown")
_IV_HV_TEXT = {"iv_rich": "IV>HV 隐含溢价(期权偏贵/避险情绪)",
               "iv_cheap": "IV<HV 隐含偏低(情绪偏松/或低估波动)",
               "iv_inline": "IV≈HV", "unknown": "IV-HV未知"}


def iv_hv_tag(iv_value, hv_value, hi: float = IV_HV_RATIO_HI, lo: float = IV_HV_RATIO_LO):
    """市场级 IV(50ETF 隐含)vs HV(50ETF 已实现)的 regime 标注。**纯 advisory**——建仓/减半
    仍只由 Rule3 IV 分位闸门(IV_HALVE_PCT/IV_NOBUILD_PCT),此标签不翻动任何 action。返回
    (regime, ratio_or_None):iv_rich=IV/HV≥hi、iv_cheap=IV/HV≤lo、iv_inline=之间;任一缺失/非有限/
    ≤0 → ('unknown', None)(绝不伪造比值)。"""
    for v in (iv_value, hv_value):
        try:
            vf = float(v)
        except (TypeError, ValueError):
            return "unknown", None
        if not math.isfinite(vf) or vf <= 0:
            return "unknown", None
    ratio = round(float(iv_value) / float(hv_value), 4)
    if ratio >= hi:
        return "iv_rich", ratio
    if ratio <= lo:
        return "iv_cheap", ratio
    return "iv_inline", ratio


def iv_hv_vol_note(iv_value, hv_value):
    """波动率状态 文案 + machine 标签:返回 (note_text, regime, ratio)。"""
    regime, ratio = iv_hv_tag(iv_value, hv_value)
    txt = _IV_HV_TEXT[regime]
    note = (f"IV/HV {ratio} {txt}(advisory)" if ratio is not None else f"{txt}(advisory)")
    return note, regime, ratio


# ── A股 tick 取整(Slice 0:M6.7 价格计算优化;side-aware,= 价格提案 §2)────────
_TICK = Decimal("0.01")


def _tick(x, rounding):
    """A股主板最小变动 0.01 的方向敏感取整;None/非有限值 → None(绝不伪造价)。"""
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(xf):
        return None
    return float(Decimal(str(xf)).quantize(_TICK, rounding=rounding))


def tick_ref(x):
    """展示/参考价:half-up 到 0.01(不用 banker's round / float 偏置)。"""
    return _tick(x, ROUND_HALF_UP)


def tick_up(x):
    """止损:向上取 tick(实际止损价不低于系统风险线)。"""
    return _tick(x, ROUND_UP)


def tick_down(x):
    """止盈 / 买入上沿:向下取 tick(不高估可实现目标 / 不超计算上沿)。"""
    return _tick(x, ROUND_DOWN)


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


def effective_resistance(series: list, atr):
    """#6 有效压力(resistance 有效化,对称 #5 effective_support):抗单日极值结构位 + 质量标记。
    `raw_high = max(近20日 high)`。若**最高 high 比次高 high 还高 > SR_SPIKE_ATR×ATR** → 判单日插针,压力取**次高**
    (quality=`weak`);否则极值被次高背书,压力=`raw_high`(quality=`strong`)。ATR 缺失/窗口不足两根 → 退 `raw_high`
    (quality=`fallback_extreme`,绝不伪造结构)。返回 `(resistance, quality, recent_high_20)`。**双侧消费**:建仓 `t1`
    (= resistance 当 resistance>close)→ RR 门**分子**——上插针顶高会让 t1/RR 虚高、marginal 建仓假性过门;+ 持仓跟踪
    止损基准(`recent_high − ATR×mult`)——上插针会让止损过紧、提前出局。故与 support 一样去插针:本切片补全 RR 门的
    抗插针**对称**(#5 只护了分母 support;此处护分子 resistance),并**改持仓跟踪止损口径**(用户已确认接受)。"""
    highs = [x["high"] for x in series[-RESISTANCE_LOOKBACK:]]
    if not highs:
        return None, None, None
    raw_high = max(highs)
    if atr is None or atr <= 0 or len(highs) < 2:
        return raw_high, "fallback_extreme", raw_high
    second_high = sorted(highs)[-2]
    if raw_high - second_high > SR_SPIKE_ATR * atr:      # 最高是孤立插针(> 1 ATR 高于次高)→ 取次高为结构压力
        return second_high, "weak", raw_high
    return raw_high, "strong", raw_high                   # 极值被次高背书 → 用 raw_high


def effective_support(series: list, atr):
    """#5 有效支撑(策略口径,仅建仓侧):抗单日极值结构位 + 质量标记。
    `raw_low = min(近20日 low)`。若**最低 low 比次低 low 还低 > SR_SPIKE_ATR×ATR** → 判单日插针,支撑取**次低**
    (quality=`weak`);否则极值被次低背书,支撑=`raw_low`(quality=`strong`)。ATR 缺失/窗口不足两根 → 退 `raw_low`
    (quality=`fallback_extreme`,绝不伪造结构)。返回 `(support, quality, recent_low_20)`。**影响建仓 stop/低吸带/RR
    的分母(risk)**;RR 分子侧的 resistance 由 `effective_resistance` 同样去插针(#6 resistance 有效化,2026-06-17;
    该切片同时改持仓跟踪止损口径)。"""
    lows = [x["low"] for x in series[-SUPPORT_LOOKBACK:]]
    if not lows:
        return None, None, None
    raw_low = min(lows)
    if atr is None or atr <= 0 or len(lows) < 2:
        return raw_low, "fallback_extreme", raw_low
    second_low = sorted(lows)[1]
    if second_low - raw_low > SR_SPIKE_ATR * atr:        # 最低是孤立插针(> 1 ATR 低于次低)→ 取次低为结构支撑
        return second_low, "weak", raw_low
    return raw_low, "strong", raw_low                    # 极值被次低背书 → 用 raw_low


def compute_indicators(series: list) -> dict:
    closes = [x["close"] for x in series]
    atr = atr14(series)
    sup, sup_q, recent_low_20 = effective_support(series, atr)
    res, res_q, recent_high_20 = effective_resistance(series, atr)   # #6:resistance 同样去插针(建仓 t1/RR 分子 + 持仓止损基准)
    return {"ma5": ma(closes, 5), "ma10": ma(closes, 10), "ma20": ma(closes, 20),
            "rsi14": rsi14(closes), "atr14": atr, "support": sup, "support_quality": sup_q,
            "recent_low_20": recent_low_20, "resistance": res, "resistance_quality": res_q,
            "recent_high_20": recent_high_20}


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
    regime_fallback = inp.get("regime_fallback") or {}
    regime_unknown_fallback = bool(regime_fallback.get("active"))
    regime_fallback_reason = regime_fallback.get("reason") or "market_regime unknown→按震荡期保守处理"
    stateful = inp.get("stateful_risk") or {}
    has_position = stateful.get("position_state") == "held"
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
    if regime_unknown_fallback:
        mr.append(regime_fallback_reason)
    if iv_pct is not None and iv_pct > IV_NOBUILD_PCT:
        mr.append(f"IV分位{iv_pct}>{IV_NOBUILD_PCT} 不可建仓")
        fam["market_regime"].update(hit=True, action="hard_veto", reasons=mr)
    elif regime == "收缩期":
        mr.append("收缩期禁新建仓")
        fam["market_regime"].update(hit=True, action="hard_veto", reasons=mr)
    elif iv_pct is not None and iv_pct > IV_HALVE_PCT:
        mr.append(f"IV分位{iv_pct}>{IV_HALVE_PCT} 减半")
        fam["market_regime"].update(hit=True, action="downgrade", reasons=mr)
    elif regime_unknown_fallback:
        fam["market_regime"].update(hit=True, action="downgrade", reasons=mr)

    # portfolio_concentration
    pc = []
    if (inp.get("portfolio") or {}).get("same_l2_exposure_over_cap"):
        pc.append("同 SW L2 暴露超限")
    if (inp.get("portfolio") or {}).get("factor_resonance"):
        pc.append("因子共振")
    if pc:
        fam["portfolio_concentration"].update(hit=True, action="downgrade", reasons=pc)

    # stateful_risk(Rule12/Rule13 + 当前持仓):已有持仓只做持仓管理/禁止加仓;
    # flat candidate 在 Rule12 冷静期或 Rule13 再入冷静期内不可新建仓。
    sr_hard = []
    sr_down = []
    if has_position:
        sr_down.append("已有持仓:按持仓管理输出,不按新开仓处理")
    r12 = stateful.get("rule12") or {}
    if r12.get("status") == "active_cooldown":
        if has_position:
            sr_down.append("Rule12 active_cooldown:已有持仓仅管理/不加仓")
        else:
            sr_hard.append("Rule12 active_cooldown:禁止新开仓")
    elif r12.get("status") == "recovery_1":
        mult = stateful.get("size_multiplier")
        sr_down.append(f"Rule12 recovery_1:恢复首笔仓位上限×{mult if mult is not None else 0.5}")
    r13 = stateful.get("rule13") or {}
    if not has_position:
        if r13.get("reentry_blocked") or r13.get("status") == "active_cooldown":
            sr_hard.append(f"Rule13 {r13.get('status', 'active_cooldown')}:禁止止损后再入")
        elif r13.get("status") in ("pending_recheck", "cleared_for_reentry"):
            mult = stateful.get("size_multiplier")
            sr_down.append(f"Rule13 {r13.get('status')}:再入仓位上限×{mult if mult is not None else 0.5}")
    if sr_hard:
        fam["stateful_risk"].update(hit=True, action="hard_veto", reasons=sr_hard)
    elif sr_down:
        fam["stateful_risk"].update(hit=True, action="downgrade", reasons=sr_down)
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
    # #6-ii:is_breakout 现为 v14.2 spec 突破信号(站稳MA10 + 当日量>5日均量×1.2,EGS 算)。引擎本地复查
    # close>=ma10 作安全门;**不再叠加旧 vol_confirm(近5日上涨日额>下跌日额)门**——那是非-spec 额外量能,
    # 会把合法的 spec 突破误判成观察(vol_confirm 仅留作 EGS l4_score 评分输入,不门控突破)。
    if inp.get("derived", {}).get("breakout") and ma10 and close >= ma10:
        return "突破", "站稳 MA10 + 放量"
    if sup and abs(close - sup) / sup <= LOWXI_BAND:
        return "低吸", "现价近关键支撑"
    return "观察", "未到低吸/突破触发"


def exit_and_size(inp: dict, ind: dict, regime: str, etype: str = "低吸", extra_halve: bool = False,
                  halve_reason: str = "", size_multiplier: float = 1.0, size_multiplier_reason: str = ""):
    """返回 (plan, None) | (None, reject)。plan 含入场区间 entry_low/high(#2)、最不利价 RR、按区间上沿的股数。
    etype:低吸/突破(决定区间口径)。extra_halve:IV>80(Rule3)或 IV feed 缺失(保守)时在试探仓基础上再减半。"""
    close, sup, res, atr = inp.get("close"), ind.get("support"), ind.get("resistance"), ind.get("atr14")
    notes = []
    if close is None or sup is None or atr is None or atr <= 0:
        return None, "缺价/支撑/ATR,无法精算"
    stop = sup - ATR_MULT.get(regime, 1.25) * atr
    # M2.7 收紧:只对明显坏结构硬停
    if stop >= close or close <= sup:
        return None, "现价≤支撑或止损≥现价(明显无效结构)"
    risk = close - stop
    rr_floor = RR_FLOOR.get(regime, 1.5) + (BREAKOUT_RR_BONUS if etype == "突破" else 0.0)   # #6:突破型更高 RR 门
    use_structural_res = bool(res is not None and res > close)   # #6:结构阻力仅在高于现价时用作 t1,否则走 RR 门兜底
    t1 = res if use_structural_res else close + rr_floor * risk
    t1_basis = "structural_resistance" if use_structural_res else "rr_floor_fallback"   # 决定 advice 目标基准文案真实性
    t2 = max(t1 + ATR_MULT.get(regime, 1.25) * atr, close + 2.0 * risk)
    rr = (t1 - close) / risk if risk > 0 else 0.0
    if rr < rr_floor:
        return None, f"盈亏比 {rr:.2f} < {rr_floor}"
    # Slice 0(§2.1):side-aware tick = 最终执行价(入参考 half-up、损向上、盈向下),取整后结构重校验。
    entry_t, stop_t, t1_t, t2_t = tick_ref(close), tick_up(stop), tick_down(t1), tick_down(t2)
    if None in (entry_t, stop_t, t1_t, t2_t):
        return None, "价格非有限,取整失败"
    if not (stop_t < entry_t and t1_t > entry_t and t2_t >= t1_t):
        return None, "取整后结构失效(止损≥入/止盈≤入/盈二<盈一)"
    # #2 入场区间(价格提案 §3 + §11.2):低吸 [max(sup,close−0.5ATR), close];突破 [close, close+0.3ATR] + 追价失效线。
    # side-aware:buy_limit_low 向上取、buy_limit_high 向下取;退化(low>high 或非有限)→ 回退单点参考价。
    if etype == "突破":
        lo_raw, hi_raw, chase = close, close + 0.3 * atr, tick_down(close + 0.5 * atr)
    else:                                   # 低吸(默认)
        lo_raw, hi_raw, chase = max(sup, close - 0.5 * atr), close, None
    entry_low, entry_high, entry_invalid_reason = tick_up(lo_raw), tick_down(hi_raw), None
    if entry_low is None or entry_high is None or entry_low > entry_high:
        entry_low = entry_high = entry_t
        entry_invalid_reason = "区间退化(low>high 或非有限)→ 回退单点参考价"
    # #2 最不利价 RR 门(§11.2):用区间上沿 entry_high 复算 RR,不够即拒(不输出"按上沿成交其实不够 RR"的建仓)。
    risk_eh = entry_high - stop_t
    if risk_eh <= 0:
        return None, "区间上沿 ≤ 止损(最不利价无效)"
    rr_eh = (t1_t - entry_high) / risk_eh
    if rr_eh < rr_floor:
        return None, f"最不利价(区间上沿)盈亏比 {rr_eh:.2f} < {rr_floor}"
    rr_ref = (t1_t - entry_t) / (entry_t - stop_t)        # 参考价 RR(展示用)
    # 仓位:单只上限 + 冲击成本 + 100股 + 试探仓 + IV 减半;股数/最小金额/现金上限按**最不利买入价 entry_high** 计(§11.3)。
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
    if size_multiplier < 1.0:
        cap *= size_multiplier
        notes.append(size_multiplier_reason or f"状态风控仓位上限×{size_multiplier}")
    shares = int(cap // entry_high // 100) * 100 if entry_high > 0 else 0
    if shares < MIN_SHARES or shares * entry_high < MIN_AMOUNT:
        return None, "可建股数/金额不足(按最不利价 entry_high 计;放弃)"
    return {"entry": entry_t, "entry_low": entry_low, "entry_high": entry_high,
            "entry_type": etype, "entry_for_risk": entry_high, "chase_invalid_above": chase,
            "entry_invalid_reason": entry_invalid_reason, "stop": stop_t, "t1": t1_t, "t2": t2_t,
            "rr": round(rr_ref, 3), "rr_at_entry_high": round(rr_eh, 3), "rr_floor": rr_floor,
            "support": sup, "support_quality": ind.get("support_quality"),   # #5 stop 的结构支撑基准 + 质量
            "resistance": res, "resistance_quality": ind.get("resistance_quality"),   # #6 t1/RR 的结构阻力基准 + 质量
            "t1_basis": t1_basis,   # #6:t1 来源(structural_resistance / rr_floor_fallback)——决定 advice 目标基准文案是否标结构阻力
            "shares": shares, "avg_amount_5d": amt5, "sizing_notes": notes}, None


def holding_levels(inp: dict, ind: dict, regime: str):
    """持仓恒列入 S3a:持仓**系统**止损/止盈(被动显示,动作恒「持有」、不算股数)。跟踪止损(ratchet)=
    `recent_high(= ind['resistance'];#6 起为**有效压力**=去单日插针后的近20日最高) − ATR_MULT[regime]×ATR`;side-aware tick(止损向上、止盈向下,
    = 最终可执行价)+ post-tick 重校验。缺价/ATR/最高价 → reject(render 显"未算出",**绝不伪造**);
    现价 ≤ 取整后跟踪止损,或取整后止盈结构失效 → `breached`(t1/t2=None,标已破位、不伪造止盈)。
    返回 (plan, None) | (None, reject_reason)。"""
    close, recent_high, atr = inp.get("close"), ind.get("resistance"), ind.get("atr14")
    res = ind.get("resistance")
    if close is None or recent_high is None or atr is None or atr <= 0:
        return None, "缺价/ATR/近20日最高,无法精算跟踪止损"
    stop = tick_up(recent_high - ATR_MULT.get(regime, 1.25) * atr)     # 止损向上取(不低于风险线)
    if stop is None:
        return None, "止损非有限,取整失败"
    base = {"entry": None, "shares": None, "stop": stop, "basis": "trailing_ratchet",
            "recent_high": recent_high, "atr": atr}
    risk = close - stop
    if risk <= 0:                          # 现价 ≤ 取整后跟踪止损 → 已破位(被动诚实,不伪造止盈)
        return {**base, "t1": None, "t2": None, "breached": True}, None
    rr_floor = RR_FLOOR.get(regime, 1.5)
    raw_t1 = res if (res and res > close) else close + rr_floor * risk
    t1 = tick_down(raw_t1)                 # 止盈向下取(不高估可实现目标)
    t2 = tick_down(max(raw_t1 + ATR_MULT.get(regime, 1.25) * atr, close + 2.0 * risk))
    if t1 is None or t2 is None or not (t1 > close and t2 >= t1):      # post-tick 结构失效 → 退破位
        return {**base, "t1": None, "t2": None, "breached": True}, None
    return {**base, "t1": t1, "t2": t2, "breached": False}, None


def compute_star(inp: dict, fam: dict, eligible: bool) -> int:
    star = 3
    if eligible:
        star += 1                         # overlay 赛道红利
    if inp.get("industry_trend") == "headwind":
        star -= 1
    for f in ("overheat_crowding", "portfolio_concentration"):
        if fam[f]["action"] == "downgrade":
            star -= 1
    if (fam["market_regime"]["action"] == "downgrade"
            and any("unknown" in str(r) for r in fam["market_regime"].get("reasons", []))):
        star -= 1                         # EGS regime unknown fallback: explicit downgrade
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


def _semantic_operation_impacts(high_full, web, web_downgrade, as_of, scope):
    """4.2 第3轮:把已校验的 semantic 信号(official 证据齐全 high / web downgrade)统一成 advisory
    operation_impact(复用 build_m67/holding 已算标志,不重复校验,DRY 单一来源)。
    scope='new_entry'(候选行)→ candidate_row_impact / 已结构化落点;
    scope='existing_holding'(持仓行)→ holding_row_impact / 持仓处置文本、最终结构化列待 S3b。
    semantic 永远 advisory:production_effect_enabled=False;official→m67_advisory_veto、web_llm→veto_class=none
    (web/LLM 永久 advisory-only,绝不 hard_veto)。持仓 blocked_add=True(禁止加仓)、私密(private_account)。"""
    impacts, as_of = [], str(as_of)
    is_holding = scope == "existing_holding"
    if high_full:
        impacts.append({
            "source_field": "semantic_official_high",
            "field_class": "semantic_advisory",
            "visibility_shape": "holding_row_impact" if is_holding else "candidate_row_impact",
            "impact_scope": scope,
            "new_entry_effect": "none" if is_holding else "hard_veto",
            "holding_effect": "clear_review" if is_holding else "none",
            "blocked_add_required": is_holding,
            "veto_class": "m67_advisory_veto",
            "reason": ("持仓官方结构化 high+证据齐全 → 清仓复核建议(人工,不自动卖出;减仓价待 S3b)" if is_holding
                       else f"官方结构化 high+证据齐全(非空 url_or_pdf) → M6.7 advisory 否决({ADVISORY_VETO_TAG},不进 EGS/回测)"),
            "evidence_ref": {"kind": "lineage_key",
                             "value": "machine.layer.semantic_risk.official_status/events",
                             "as_of": as_of},
            "confidence": "high",
            "pit_basis": "disclosure_date",
            "production_effect_enabled": False,
            "implementation_status": "future_s3b_schema_render_required" if is_holding else "implemented",
            "m67_landing_surface": ("精简结论区.操作建议+风控触发(持仓处置复核文本)" if is_holding
                                    else "table.操作=否决 + 精简结论区.否决审查触发"),
            "terminal_surface_target": "s3b_持仓处置_列+减仓价" if is_holding else "already_structured",
            "pending_successor_slice": "S3b" if is_holding else None,
            "privacy_class": "private_account" if is_holding else "public_tracked",
        })
    if web_downgrade and web:
        impacts.append({
            "source_field": "semantic_web_llm",
            "field_class": "semantic_advisory",
            "visibility_shape": "holding_row_impact" if is_holding else "candidate_row_impact",
            "impact_scope": scope,
            "new_entry_effect": "none" if is_holding else "priority_down",
            "holding_effect": "hold_watch" if is_holding else "none",
            "blocked_add_required": is_holding,
            "veto_class": "none",
            "reason": (f"web/LLM 语义 {web.get('status')}({web.get('risk_level')})+有 sources → "
                       + ("持仓警戒(advisory,绝不 hard_veto/自动减仓)" if is_holding
                          else "降级 priority_down(advisory,绝不 hard_veto)")),
            "evidence_ref": {"kind": "lineage_key",
                             "value": "machine.layer.semantic_risk.web_llm.status/sources_count",
                             "as_of": as_of},
            "confidence": "medium",
            "pit_basis": "live_only",
            "production_effect_enabled": False,
            "implementation_status": "future_s3b_schema_render_required" if is_holding else "implemented",
            "m67_landing_surface": ("精简结论区.风控触发(持仓警戒文本)" if is_holding
                                    else "精简结论区.风控触发"),
            "terminal_surface_target": "s3b_持仓处置_列+减仓价" if is_holding else "already_structured",
            "pending_successor_slice": "S3b" if is_holding else None,
            "privacy_class": "private_account" if is_holding else "public_tracked",
        })
    return impacts


def _consume_semantic(inp: dict, as_of: str) -> dict:
    """4.2 第3轮/S2: semantic 消费的单一来源(build_m67 候选行 + build_holding 持仓行共用,防两份校验/派生漂移)。
    official 走 _validate_semantic_official(fail-closed),web 走 _web_llm_error 中性化非法(advisory 非阻断)。
    只产派生信号 + machine trace,**不决定 action**(候选的 hard_veto→否决 与持仓的 advisory 处置由各自 build 决定)。"""
    sem = _validate_semantic_official(inp.get("semantic"), as_of)
    sem_status = sem.get("status") if sem else "unknown"
    sem_events = sem["events"] if (sem and sem_status == "risk") else []
    sem_sevs = [e["severity"] for e in sem_events]
    # 只有证据齐全(非空 url_or_pdf)的 high 才计 veto/清仓复核;缺 URL 的 high → 待核(pending)。
    high_full = [e for e in sem_events if e["severity"] == "high" and e["url_or_pdf"].strip()]
    high_incomplete = [e for e in sem_events if e["severity"] == "high" and not e["url_or_pdf"].strip()]
    sem_pending = bool(sem_events) and not high_full
    sem_impact = "veto" if high_full else ("pending" if sem_pending else "none")
    sw = inp.get("semantic_web_llm")
    web = sw.get("web_llm") if isinstance(sw, dict) else None
    web_sources = (sw.get("sources") or []) if isinstance(sw, dict) else []
    web_invalid = (sw is not None) and (not isinstance(web, dict)
                                        or _web_llm_error(web, web_sources) is not None)
    if web_invalid:
        web, web_sources = None, []
    web_status = web["status"] if web else "unknown"
    web_downgrade = bool(web) and web_status in _WEB_DOWNGRADE_STATUSES
    trace = {"official_status": sem_status,
             "severity_max": ("high" if "high" in sem_sevs else
                              ("medium" if "medium" in sem_sevs else
                               ("low" if "low" in sem_sevs else None))),
             "events": (list(sem["events"]) if sem else []),
             "impact": sem_impact,
             "evidence_incomplete_high": len(high_incomplete),
             "web_llm": {"status": web_status,
                         "risk_level": (web.get("risk_level") if web else "unknown"),
                         "action": (web.get("action") if web else "no_action"),
                         "sources_count": len(web_sources),
                         "impact": ("downgrade" if web_downgrade else "none"),
                         "invalid_neutralized": web_invalid}}
    return {"sem": sem, "sem_status": sem_status, "sem_events": sem_events, "sem_sevs": sem_sevs,
            "high_full": high_full, "high_incomplete": high_incomplete, "sem_pending": sem_pending,
            "sem_impact": sem_impact, "web": web, "web_sources": web_sources, "web_status": web_status,
            "web_downgrade": web_downgrade, "trace": trace}


def _semantic_holding_lines(sc: dict) -> list:
    """4.2 S2: 持仓 semantic 的用户可见文本行(build_m67 持仓分支 + build_holding_report 共用,防漂移)。
    official 证据齐全 high → 清仓复核(标非生产 advisory);web → 持仓警戒;pending → 待核。持仓恒持有、不自动卖出、减仓价待 S3b。"""
    lines = []
    if sc["high_full"]:
        lines.append(f"官方结构化 high({ADVISORY_VETO_TAG}):建议清仓复核(人工,不自动卖出,减仓价待 S3b)")
    if sc["web_downgrade"]:
        lines.append(f"web/LLM {sc['web_status']}({sc['web'].get('risk_level')}):持仓警戒(advisory)")
    if sc["sem_pending"]:
        lines.append("官方语义待核(证据不全/medium·low,未扣分)")
    return lines


def build_m67_report(inp: dict, as_of: str, generated_at: str) -> dict:
    ind = compute_indicators(inp.get("price_series", []))
    fam = classify_risk_families(inp, ind)
    regime = inp.get("market_regime", "震荡期")
    regime_fallback = inp.get("regime_fallback") or {}
    regime_unknown_fallback = bool(regime_fallback.get("active"))
    regime_fallback_reason = regime_fallback.get("reason") or "EGS market_regime unknown/missing→按震荡期保守处理"
    iv_pct = (inp.get("iv") or {}).get("iv_percentile_252d")
    iv_hv_note, iv_hv_regime, iv_hv_ratio = iv_hv_vol_note(
        (inp.get("iv") or {}).get("iv_value"), (inp.get("iv") or {}).get("hv_value"))
    eligible = bool((inp.get("overlay") or {}).get("eligible"))
    stateful = inp.get("stateful_risk") or {}
    has_position = stateful.get("position_state") == "held"
    position = stateful.get("position") or {}
    try:
        state_size_multiplier = float(stateful.get("size_multiplier", 1.0))
    except (TypeError, ValueError):
        state_size_multiplier = 1.0
    if state_size_multiplier <= 0 or state_size_multiplier > 1:
        state_size_multiplier = 1.0
    state_size_reason = "；".join(str(x) for x in (stateful.get("reasons") or []))

    # 语义官方层(Slice 1,advisory):先 fail-closed 校验(非法 provider 输出 → 写盘前 abort),
    # 再用**同一已校验对象**派生 family / impact / trace(避免 status↔events 不一致 / 非 dict AttributeError)。
    # 经校验后:有 events ⟺ status==risk,severity 合法。**证据齐全(非空 url_or_pdf)的 high** → semantic_official
    # hard_veto(进下方 hard→否决,绝不救回);**缺 URL 的 high → 待核(不否决)**;medium/low → 仅"待核"
    # (不扣分/不清/不降星);clear/unknown/无输入 → 中性。(下方 high_full/high_incomplete 实现此分流)
    # 语义消费单一来源(_consume_semantic: build_m67 候选行 + build_holding 持仓行共用,防两份校验/派生漂移)。
    sc = _consume_semantic(inp, as_of)
    high_full, high_incomplete = sc["high_full"], sc["high_incomplete"]
    web, web_status, web_downgrade = sc["web"], sc["web_status"], sc["web_downgrade"]
    sem_pending = sc["sem_pending"]
    # 候选行决策路径(持仓走 build_holding_report 的 advisory 路径,不在此):证据齐全 high → fam hard_veto(进否决,
    # reason 标非生产 advisory);web risk/headwind+sources → fam downgrade(绝不 hard_veto);tailwind/clear/unknown → 中性。
    # S2: semantic 的 hard_veto/downgrade 路径**只对候选行**(not has_position)。持仓(任何 Tier,无论走 build_m67
    # 还是 build_holding)的 semantic 永远 advisory:official high → 持有 + 清仓复核(下方 op_impacts existing_holding),
    # 绝不进候选 hard_veto→否决(R-ASHORT-GAP42-S2-HOLDING-SEMANTIC-TOPN-RENDER-DRIFT);web → 持仓警戒,不进候选 downgrade。
    if high_full and not has_position:
        fam["semantic_official"].update(
            hit=True, action="hard_veto",
            reasons=[f"语义官方:{e['risk_type']}(high,{ADVISORY_VETO_TAG})" for e in high_full])
    if web_downgrade and not has_position:
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
    sem_note = (f"语义待核:{sem_reason},待复核(未扣分,待 web/LLM 实判)" if sem_pending else "")

    # IV 状态(R-ASHORT-PHASE5-IV-MISSING-FAIL-OPEN):feed 缺失不假装执行 IV 风控
    iv_known = iv_pct is not None
    iv_status = "ok" if iv_known else "observe_only_missing_feed"
    iv_halve = (iv_known and IV_HALVE_PCT < iv_pct <= IV_NOBUILD_PCT and regime != "收缩期")
    if not iv_known:
        observe.append("iv_regime_status=observe_only_missing_feed")
    if regime_unknown_fallback:
        observe.append("market_regime_status=unknown_fallback_to_shock")
    halve_reasons = []
    if iv_halve:
        halve_reasons.append("IV>80分位 Rule3 再减半")
    if not iv_known:
        halve_reasons.append("IV feed 缺失,保守再减半")
    if regime_unknown_fallback:
        halve_reasons.append("regime unknown→震荡期保守减半")
    extra_halve = bool(halve_reasons)
    halve_reason = "；".join(halve_reasons)

    # 决策
    if hard:
        action, etype, plan, reject = "否决", "N/A", None, "|".join(hard)
    elif has_position:
        action, etype = "持有", "已有持仓"
        plan, hl_reject = holding_levels(inp, ind, regime)   # S3a:系统跟踪止损/止盈(被动显示)
        reject = "已有持仓:按持仓管理输出,不按新开仓处理;禁止自动加仓"
    else:
        etype, etype_reason = entry_type(inp, ind)
        if etype == "观察":
            action, plan, reject = "观察", None, etype_reason
        else:
            plan, reject = exit_and_size(inp, ind, regime, etype, extra_halve, halve_reason,
                                         size_multiplier=state_size_multiplier,
                                         size_multiplier_reason=state_size_reason)
            action = "建仓" if plan else "观察"
    star = compute_star(inp, fam, eligible) if action != "否决" else 0

    # 操作建议行(诚实护栏:建仓必带置信/试探/止损)
    if action == "建仓":
        iv_caveat = "" if iv_known else " **IV feed 缺失,未执行 IV 风控,仓位已保守再减半**。"
        regime_caveat = (" **EGS regime unknown,按震荡期保守降级并减半**。"
                         if regime_unknown_fallback else "")
        rng = (f"**挂单区间 {plan['entry_low']}–{plan['entry_high']}**(参考价 {plan['entry']}、最不利价盈亏比 {plan['rr_at_entry_high']})"
               + (f";突破追价超过 {plan['chase_invalid_above']} 不追" if plan.get("chase_invalid_above") is not None else "")
               + (f";{plan['entry_invalid_reason']}" if plan.get("entry_invalid_reason") else ""))
        # #6-i RR 门槛文案 type-aware:仅突破标「突破型更严」,低吸不带(否则低吸行误看成也被加严)。
        floor_note = f"门槛 {plan['rr_floor']}" + ("(突破型更严)" if etype == "突破" else "")
        # #6 t1 目标基准文案按真实来源分支(R-ASHORT-M67-PRICE-RESISTANCE-T1-BASIS-DANGLING):结构阻力仅在确为 t1
        # (resistance>现价)时标为「目标基准」;否则 t1 走 RR 门兜底,明确标兜底、并把结构阻力/质量降为旁注 context,绝不虚标为目标依据。
        if plan["t1_basis"] == "structural_resistance":
            t1_note = (f"**盈一 {plan['t1']} 目标基准:结构阻力 {plan['resistance']}、质量 {plan['resistance_quality']}**"
                       f"(上插针顶高时取次高,RR 不虚高)。")
        else:
            t1_note = (f"**盈一 {plan['t1']} 由 RR 门槛兜底推算**(结构阻力 {plan['resistance']}/质量 "
                       f"{plan['resistance_quality']} 未用作目标:不高于现价)。")
        advice = (f"低吸/突破建仓建议(类型:{etype})。⭐×{star}、盈亏比 {plan['rr']}({floor_note})。{rng}。"
                  f"**试探仓**(edge 未验证,A-short 仅 risk_filter_only)。"
                  f"**止损 {plan['stop']} 无条件执行(盘中由你手动)**(基准:结构支撑 {plan['support']}、质量 {plan['support_quality']})。"
                  + t1_note +
                  f"价格已按 A 股 0.01 规整。" + iv_caveat + regime_caveat)
    elif action == "观察":
        advice = f"观察,不建仓。原因:{reject}。" + (f"降级:{'/'.join(downgrades)}。" if downgrades else "")
    elif action == "持有":
        cost_hint = position.get("avg_cost", "未知")
        shares_hint = position.get("shares", "未知")
        manual_ref = position.get("stop_loss")
        manual_txt = (f"你的手填参考止损={manual_ref}(仅参考)" if manual_ref is not None else "无手填参考止损")
        if plan is None:                                     # S3a:系统止损未算出 → 有手填参考才回退执行;无参考则诚实标"无可执行止损位",不伪造执行不存在的止损
            sys_txt = (f"系统止损未算出({hl_reject});请按手填参考止损 {manual_ref} 盘中无条件手动执行"
                       if manual_ref is not None
                       else f"系统止损未算出({hl_reject})、且无手填参考止损 → 本周无可执行止损位,请人工核查并补一个保护止损")
        elif plan.get("breached"):                           # 现价已跌破系统跟踪止损
            sys_txt = f"⚠️ 现价已跌破系统跟踪止损 {plan['stop']} —— 触发后由你盘中无条件手动执行"
        else:
            sys_txt = (f"系统跟踪止损 {plan['stop']}(无条件、盘中由你手动执行);"
                       f"止盈 盈一 {plan['t1']} / 盈二 {plan['t2']}")
        _sem_h = _semantic_holding_lines(sc)        # S2: 持仓(在 TopN/Tier-1·2 走 build_m67)的 semantic advisory 文本
        advice = (f"已有持仓,本周不按新开仓处理,禁止自动加仓。持仓 {shares_hint} 股/均价 {cost_hint}。"
                  f"{sys_txt}。{manual_txt}。价格已按 A 股 0.01 规整。"
                  + (f"降级:{'/'.join(downgrades)}。" if downgrades else "")
                  + (" 语义:" + "；".join(_sem_h) + "。" if _sem_h else ""))
    else:
        held_suffix = ("已有持仓也不得加仓;如硬风控触发止损/清仓条件,由你手动执行。" if has_position else "")
        advice = f"否决,禁止建仓。硬否决:{reject}。{held_suffix}"

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
        "stateful_risk": "→ positions 决定 持有/新开仓 分流;Rule12 冷静期禁新开仓/恢复首笔限仓;Rule13 止损后再入冷静期或复核限仓",
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
        "类型": (etype if action in ("建仓", "持有") else "N/A"),
        "EGS分": inp.get("egs_score"),        # EGS 质量总分(选股层);与下面的风控星级是两个维度
        "优先级": (f"⭐×{star}" if star else "—"),
        "触发条件": (f"挂单区间 {plan['entry_low']}–{plan['entry_high']};持仓周期1-3周;{';'.join(plan['sizing_notes'])}"
                     if (plan and action == "建仓")
                     else ("持仓管理(系统位被动显示,到价由你盘中手动);周期1-3周" if action == "持有"
                           else (reject or ""))),
    }
    price_cost = f"{inp.get('close')} | 试探仓"
    if has_position:
        price_cost = (f"{inp.get('close')} | 持仓:{position.get('shares')}股/"
                      f"均价{position.get('avg_cost')}/建仓{position.get('entry_date')}/"
                      f"手填参考止损{position.get('stop_loss') if position.get('stop_loss') is not None else '无'}")
    m67 = {
        "精简结论区": {
            "当前环境": (regime if not regime_unknown_fallback
                         else f"{regime}(EGS regime unknown,保守fallback)"),
            "波动率状态": ((f"IV分位≈{iv_pct}% | Rule3减半:{'是' if iv_halve else '否'}"
                           if iv_known else "IV未知(feed 缺失,未执行 IV 风控,保守减半)")
                          + f" | {iv_hv_note}"),
            "现价与成本": price_cost,
            "否决审查触发": (("|".join(hard) + (" | " + sem_note if sem_note else "")) if hard
                              else (sem_note if sem_note else "无")),
            "板块资金事件": (inp.get("industry_trend") or "unknown") +
                            (f" | {'/'.join(llm_notes)}" if llm_notes else ""),
            "风控触发": ("|".join(downgrades) if downgrades else "无"),
            "操作建议": advice,
        },
        "table": table,
    }
    # 4.2 第1轮: reduce_deduct(= event_risk.holder_reduction.active_plan = bool(reduce_deduct), egs_main:672)
    # → EGS 聚合 hard_veto → 操作=否决。发一条 production_hard_veto operation_impact,只补 field-level traceability,
    # 不改既有动作派生(action 仍由 hard_veto/anti-rescue:888 决定)。落点/最终落点非空由 m67 schema 焊死,
    # 跨字段不变式(production_hard_veto⟹否决 / advisory 不冒充生产 / 文本须挂后继 slice)由 validate_operation_impact_no_dangling 守。
    # Round 1 scope = 非持仓候选行 only(R-ASHORT-GAP42-ROUND1-HOLDING-SCOPE-DRIFT):持仓的减仓/清仓结构化处置属
    # S3b,不能在 Round 1 把持仓 impact 误标 already_structured;持仓+减持仍走既有 hard_veto→否决,只是不加这条 traceability。
    op_impacts = []
    if (inp.get("event") or {}).get("holder_reduction_active") and not has_position:
        op_impacts.append({
            "source_field": "holder_reduction_deduct_30d",
            "field_class": "structured",
            "visibility_shape": "candidate_row_impact",
            "impact_scope": "new_entry",
            "new_entry_effect": "hard_veto",
            "holding_effect": "none",
            "blocked_add_required": False,
            "veto_class": "production_hard_veto",
            "reason": "30日减持(event_risk.holder_reduction.active_plan)→ EGS 聚合 hard_veto → 操作=否决",
            "evidence_ref": {"kind": "lineage_key",
                             "value": "event_risk.holder_reduction.active_plan / derived_flags.hard_veto",
                             "as_of": str(as_of)},
            "confidence": "high",
            "pit_basis": "disclosure_date",
            "production_effect_enabled": True,
            "implementation_status": "implemented",
            "m67_landing_surface": "table.操作=否决 + 精简结论区.否决审查触发",
            "terminal_surface_target": "already_structured",
            "pending_successor_slice": None,
            "privacy_class": "public_tracked",
        })
    # 4.2 第3轮+S2: semantic advisory operation_impact。scope 依 has_position(不依哪个 builder 收到行):
    # 候选行 → new_entry(official 证据齐全 high → m67_advisory_veto 否决 / web downgrade → priority_down);
    # 持仓行(含在 TopN 走 build_m67 的 Tier-1·2 持仓)→ existing_holding(official → clear_review / web → hold_watch、
    # blocked_add、持有不否决)。semantic 永 advisory(production_effect_enabled=False、web_llm 绝不 hard_veto)。
    op_impacts.extend(_semantic_operation_impacts(
        high_full, web, web_downgrade, str(as_of), "existing_holding" if has_position else "new_entry"))
    result = {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "ts_code": str(inp.get("ts_code", "")), "name": str(inp.get("name", "")),
        "m67": m67,
        "machine": {
            "indicators": ind, "risk_families": fam,
            "layer": {"hard_veto": hard, "downgrade": downgrades,
                      "observe_only": observe, "llm_enrichment": llm_notes,
                      "semantic_risk": sc["trace"]},
            "entry_exit_size_star": {"action": action, "type": etype if action != "否决" else "N/A",
                                     "star": star, "plan": plan, "reject_reason": reject},
            "iv_gate": {"iv_percentile_252d": iv_pct, "halve": iv_halve, "status": iv_status,
                        "iv_value": (inp.get("iv") or {}).get("iv_value"),
                        "hv_value": (inp.get("iv") or {}).get("hv_value"),
                        "iv_hv_ratio": iv_hv_ratio, "iv_hv_regime": iv_hv_regime},
            "stateful_risk": stateful,
            "consumption": consumption,
        },
        "boundary": {"production": False, "real_money": False,
                     "is_validated_alpha": False, "satisfies_ship_gate": False},
    }
    if op_impacts:                       # 仅命中时加 key,正常报告零改动(向后兼容)
        result["machine"]["operation_impact"] = op_impacts
    return result


def _is_valid_date(s) -> bool:
    from datetime import datetime
    try:
        datetime.strptime(str(s), "%Y%m%d")
        return True
    except ValueError:
        return False


def build_holding_report(inp: dict, as_of: str, generated_at: str) -> dict:
    """持仓恒列入 S1: Tier-3(本周 EGS 粗筛未覆盖)持仓的 M6.7 报告。

    **关键诚实点**:Tier-3 没有 EGS/流动性/事件数据。**绝不跑 `classify_risk_families`**——否则会在
    缺失数据上**伪造**风险族结论(实测:无流动性 → 误判流动性硬否决 → 错误「否决」一只持仓;无事件 →
    误判"无 ST")。本函数只做:持仓技术指标 + Rule12/Rule13(真实账户)+ 诚实标 EGS/ST「未核查」;语义(4.2 S2)经
    semantic provider 注入则核查并发 holding_row_impact advisory(clear_review/hold_watch,不否决)、无 provider 则「未核查」(S1)。
    action 恒「持有」(S1 被动;主动止损/止盈/加仓是 S3)。产出与 `build_m67_report` 同形、过
    `validate_m67_consistency`。coverage_status / row_source 由 pipeline 在 build_weekly_report 后打。"""
    ind = compute_indicators(inp.get("price_series", []))
    stateful = inp.get("stateful_risk") or {}
    position = stateful.get("position") or {}
    regime = inp.get("market_regime", "震荡期")
    iv_pct = (inp.get("iv") or {}).get("iv_percentile_252d")
    iv_known = iv_pct is not None
    iv_hv_note, iv_hv_regime, iv_hv_ratio = iv_hv_vol_note(
        (inp.get("iv") or {}).get("iv_value"), (inp.get("iv") or {}).get("hv_value"))
    # EGS 派生风险族一律 not-evaluated(未核查,非 hit);stateful_risk 从真实 Rule12/Rule13。
    fam = {k: {"hit": False, "action": "none", "reasons": []} for k in
           ("market_regime", "overheat_crowding", "portfolio_concentration", "liquidity_impact",
            "event_hard_veto", "semantic_official", "stateful_risk")}
    # 4.2 S2: 持仓 semantic 数据接入(让持仓也抓 cninfo/web 语义)。复用 _consume_semantic(候选/持仓单一来源)+
    # _semantic_operation_impacts(scope=existing_holding → holding_row_impact: clear_review/hold_watch + blocked_add
    # + pending S3b)。持仓 action 恒「持有」(不否决/不自动卖出,减仓价待 S3b);official 证据齐全 high → 清仓复核 advisory
    # (标非生产)、web → 持仓警戒;web/LLM 永久 advisory-only、绝不 hard_veto。**无 semantic 输入(provider None)→ 全 unknown、
    # 零 op_impact、文本保持「未核查」(S1 向后兼容)**。涉真实持仓 → 私密路由(weekly_private,带 --account 自动私密)。
    has_semantic_input = inp.get("semantic") is not None or inp.get("semantic_web_llm") is not None
    sc = _consume_semantic(inp, as_of)
    # Finding 2 fix: 「已核查」文本判据用**真核查**(official_status 或 web_status 任一非 unknown,= render `_has_semantic` 同一判据),
    # 不用 has_semantic_input —— 有输入但 trace 全 unknown(取数失败/无结果)时,has_semantic_input 会误写「语义已核查」,
    # 与 render `_has_semantic`(精确判未核查)同一份 Markdown 自相矛盾(违反 no-false-clear)。
    sem_checked = sc["sem_status"] != "unknown" or sc["web_status"] != "unknown"
    sem_op_impacts = _semantic_operation_impacts(sc["high_full"], sc["web"], sc["web_downgrade"], as_of, "existing_holding")
    sem_lines = _semantic_holding_lines(sc)          # S2: 与 build_m67 持仓分支共用单一来源
    sr_down = ["已有持仓:按持仓管理输出,不按新开仓处理"]
    r12 = (stateful.get("rule12") or {})
    if r12.get("status") == "active_cooldown":
        sr_down.append("Rule12 active_cooldown:已有持仓仅管理/不加仓")
    elif r12.get("status") == "recovery_1":
        sr_down.append("Rule12 recovery_1:恢复期")
    fam["stateful_risk"].update(hit=True, action="downgrade", reasons=sr_down)
    close = inp.get("close")
    plan, hl_reject = holding_levels(inp, ind, regime)   # S3a:系统跟踪止损/止盈(被动;Tier-3 有价亦可算)
    price_cost = (f"{close} | 持仓:{position.get('shares')}股/均价{position.get('avg_cost')}/"
                  f"建仓{position.get('entry_date')}/手填参考止损{position.get('stop_loss')}")
    vol_state = (f"IV分位≈{iv_pct}%" if iv_known else "IV未知(feed 缺失)")
    iv_status = "holding_uncovered" if iv_known else "observe_only_missing_feed"
    observe = [] if iv_known else ["iv_regime_status:missing"]
    manual_ref = position.get("stop_loss")
    if plan is None:                                     # 系统止损未算出 → 有手填参考才回退执行;无参考则诚实标"无可执行止损位"
        sys_txt = (f"系统止损未算出({hl_reject});请按手填参考止损 {manual_ref} 盘中无条件手动执行"
                   if manual_ref is not None
                   else f"系统止损未算出({hl_reject})、且无手填参考止损 → 本周无可执行止损位,请人工核查并补一个保护止损")
    elif plan.get("breached"):
        sys_txt = f"⚠️ 现价已跌破系统跟踪止损 {plan['stop']} —— 触发后由你盘中无条件手动执行"
    else:
        sys_txt = f"系统跟踪止损 {plan['stop']}(无条件、盘中由你手动执行);止盈 盈一 {plan['t1']} / 盈二 {plan['t2']}"
    _uncovered = "EGS/ST 未自动核查(语义已核查)" if sem_checked else "EGS/语义/ST 未自动核查"
    advice = (f"已有持仓(本周 EGS 粗筛未覆盖,{_uncovered})。本周不按新开仓处理、禁止自动加仓。"
              f"{sys_txt}。价格已按 A 股 0.01 规整。新闻 / ST / 监管 / 减持请人工核查。"
              + (" 语义:" + "；".join(sem_lines) + "。" if sem_lines else ""))
    m67 = {
        "精简结论区": {
            "当前环境": regime,
            "波动率状态": (vol_state if iv_known else f"{vol_state}(未执行 IV 风控)") + f" | {iv_hv_note}",
            "现价与成本": price_cost,
            "否决审查触发": ("；".join(sem_lines) + "(EGS 粗筛未覆盖)" if sem_lines
                              else ("语义已核查无官方高风险(EGS 粗筛未覆盖)" if sem_checked
                                    else "未核查(本周 EGS 粗筛未覆盖)")),
            "板块资金事件": "未核查(本周 EGS 粗筛未覆盖)",
            "风控触发": "|".join(sr_down),
            "操作建议": advice,
        },
        "table": {"操作": "持有", "股数": None, "入": None,
                  "盈一": (plan["t1"] if plan else None), "盈二": (plan["t2"] if plan else None),
                  "损": (plan["stop"] if plan else None),
                  "类型": "已有持仓", "EGS分": None, "优先级": "—",
                  "触发条件": "持仓管理(系统位被动显示,到价由你盘中手动);本周 EGS 未覆盖(粗筛排除)"},
    }
    consumption = {"indicators": "→ 持仓技术参考(MA/RSI/ATR/支撑压力)",
                   "risk_families": "→ stateful(Rule12/Rule13)+ EGS 派生族未核查",
                   "iv.iv_percentile_252d": "→ 仅参考(未执行 IV 闸门)",
                   "overlay.eligible": "→ 未覆盖",
                   "stateful_risk": "→ 持仓管理 + Rule12/Rule13",
                   "egs_coverage": "未覆盖(粗筛排除;EGS/语义/ST 未自动核查)"}
    return {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "ts_code": str(inp.get("ts_code", "")), "name": str(inp.get("name", "")),
        "m67": m67,
        "machine": {
            "indicators": ind, "risk_families": fam,
            "layer": {"hard_veto": [], "downgrade": sr_down, "observe_only": observe, "llm_enrichment": [],
                      **({"semantic_risk": sc["trace"]} if has_semantic_input else {})},
            "entry_exit_size_star": {"action": "持有", "type": "已有持仓", "star": 0,
                                     "plan": plan, "reject_reason": hl_reject},
            "iv_gate": {"iv_percentile_252d": iv_pct, "halve": False, "status": iv_status,
                        "iv_value": (inp.get("iv") or {}).get("iv_value"),
                        "hv_value": (inp.get("iv") or {}).get("hv_value"),
                        "iv_hv_ratio": iv_hv_ratio, "iv_hv_regime": iv_hv_regime},
            "stateful_risk": stateful, "consumption": consumption,
            **({"operation_impact": sem_op_impacts} if sem_op_impacts else {}),
        },
        "boundary": {"production": False, "real_money": False,
                     "is_validated_alpha": False, "satisfies_ship_gate": False},
    }


def validate_operation_impact_no_dangling(report: dict) -> None:
    """4.2 第1轮 no-dangling + 第3轮 advisory-isolation guard。逐条 machine.operation_impact:
    ① m67_landing_surface 非空 + terminal_surface_target 非空(m67 schema 已焊,此处兜底);
    ② visibility_shape ∈ {candidate_row_impact, holding_row_impact}(逐票形态;batch/summary/out_of_scope 走周报 exclusion_summary);
    ③ evidence_ref 可解析 + PIT 绑定(kind ∈ artifact_path|lineage_key|source_id、value 非空、as_of 为 8 位且 == 报告 as_of);
    ④ implementation_status != implemented → 必挂 pending_successor_slice(防只落文本变永久悬空);
    ⑤ production_effect_enabled=False 绝不标 production_hard_veto(advisory 不冒充生产硬否决);
    ⑥ veto_class ∈ {production_hard_veto, m67_advisory_veto} 的 new_entry hard_veto → table.操作 必须 == 否决(声称硬否决就必须真否决,呼应 anti-rescue);
    ⑦【第3轮】veto_class==m67_advisory_veto ⟹ production_effect_enabled==False(advisory 否决必非生产,⑤ 的反向闭合);
    ⑧【第3轮】field_class==semantic_advisory 或 source_field 以 semantic_ 开头 ⟹ production_effect_enabled==False
      且 veto_class!=production_hard_veto;semantic_official_high 必须保持 m67_advisory_veto;semantic_web_llm 必须保持 none
      且 new_entry_effect!='hard_veto'(web/LLM 永久 advisory-only,绝不 hard_veto)。
    报告级(存在该类 impact 时):
    ⑨【第3轮】任一 m67_advisory_veto ⟹ 否决审查触发/操作建议 含 ADVISORY_VETO_TAG(advisory 否决须显式标非生产,与生产硬否决物理区分);
    ⑩【第3轮】任一 blocked_add_required==True ⟹ 操作建议/风控触发 含「禁止加仓」(独立旗标必用户可见,不被其它处置吞掉)。
    ⑪【4.2 forward_events】source_field 以 'forward_event_' 开头(覆盖 limit_unlock/earnings_disclosure/未来类) ⟹ 永久 analysis-only:
      field_class=='structured'、production_effect_enabled is False、veto_class=='none'、new_entry_effect!='hard_veto'、
      holding_effect∈{none,hold_watch}(source-class 级绑定,防篡改 veto_class/effect 伪装生产硬否决;呼应 semantic-isolation ⑧)。
    ⑫【4.2 forward_events ADVICE-LANDING】任一 forward_event_ impact ⟹ 操作建议含未来事件提示「未来已知事件」
      (候选/持仓不得仍像干净建仓——未来事件须落用户主看的操作建议,不只风控触发;字面同步 pipeline _FORWARD_EVENT_MARKER)。
    operation_impact 可选(缺省=无 impact)→ no-op,向后兼容。"""
    mc = report.get("machine") or {}
    impacts = mc.get("operation_impact")
    if not impacts:
        return
    action = report["m67"]["table"]["操作"]
    cut = report["m67"]["精简结论区"]
    veto_text = str(cut.get("否决审查触发", ""))
    advice_text = str(cut.get("操作建议", ""))
    risk_text = str(cut.get("风控触发", ""))
    for imp in impacts:
        sf = imp.get("source_field", "?")
        if not imp.get("m67_landing_surface"):
            raise ValueError(f"operation_impact {sf} 无 m67_landing_surface(悬空)")
        if not imp.get("terminal_surface_target"):
            raise ValueError(f"operation_impact {sf} 无 terminal_surface_target(悬空)")
        if imp.get("visibility_shape") not in ("candidate_row_impact", "holding_row_impact"):
            raise ValueError(f"operation_impact {sf} visibility_shape={imp.get('visibility_shape')!r} 不是逐票形态"
                             "(batch_exclusion/summary_only/out_of_scope 走周报 exclusion_summary,不得进 row-level operation_impact)")
        ev = imp.get("evidence_ref")
        if (not isinstance(ev, dict) or ev.get("kind") not in ("artifact_path", "lineage_key", "source_id")
                or not ev.get("value")):
            raise ValueError(f"operation_impact {sf} evidence_ref 缺失/不可解析"
                             "(须 kind∈artifact_path|lineage_key|source_id 且 value 非空)")
        ev_as_of = ev.get("as_of")
        if not (isinstance(ev_as_of, str) and len(ev_as_of) == 8 and ev_as_of.isascii() and ev_as_of.isdigit()):
            raise ValueError(f"operation_impact {sf} evidence_ref.as_of 缺失或非 YYYYMMDD(PIT 不可审计)")
        if ev_as_of != report.get("as_of"):
            raise ValueError(f"operation_impact {sf} evidence_ref.as_of={ev_as_of!r} != 报告 as_of={report.get('as_of')!r}"
                             "(证据日期漂移,非 PIT)")
        if imp.get("implementation_status") != "implemented" and not imp.get("pending_successor_slice"):
            raise ValueError(f"operation_impact {sf} 非 implemented 却无 pending_successor_slice(文本恐变永久悬空)")
        if imp.get("production_effect_enabled") is False and imp.get("veto_class") == "production_hard_veto":
            raise ValueError(f"operation_impact {sf} production_effect_enabled=false 却标 production_hard_veto(advisory 冒充生产)")
        if (imp.get("veto_class") in ("production_hard_veto", "m67_advisory_veto")
                and imp.get("new_entry_effect") == "hard_veto"
                and action != "否决"):
            raise ValueError(f"operation_impact {sf} 声称 {imp.get('veto_class')} 硬否决却未否决(action={action})")
        if imp.get("veto_class") == "m67_advisory_veto" and imp.get("production_effect_enabled") is not False:
            raise ValueError(f"operation_impact {sf} m67_advisory_veto 却 production_effect_enabled!=false(advisory 否决必非生产)")
        # ⑧ semantic 来源(field_class==semantic_advisory 或 source_field 以 semantic_ 开头)= 永久 advisory。
        #   source-class 级绑定(不只按 veto_class 分支,防"改 veto_class/丢分类绕过";堵三类伪装:official→production_hard_veto+enabled /
        #   official hard_veto 丢 advisory 分类 / web_llm production-enabled):一律非生产、绝不 production_hard_veto;
        #   semantic_official_high 必保 m67_advisory_veto;semantic_web_llm 必保 veto_class=none 且非 hard_veto。单一 block = 未来加 semantic 不变式只在此处。
        if imp.get("field_class") == "semantic_advisory" or str(imp.get("source_field", "")).startswith("semantic_"):
            if imp.get("production_effect_enabled") is not False:
                raise ValueError(f"operation_impact {sf} semantic 来源必须 production_effect_enabled=false(语义永久 advisory,不进生产)")
            if imp.get("veto_class") == "production_hard_veto":
                raise ValueError(f"operation_impact {sf} semantic 来源不得标 production_hard_veto(语义不进生产硬否决)")
            if imp.get("source_field") == "semantic_official_high" and imp.get("veto_class") != "m67_advisory_veto":
                raise ValueError(f"operation_impact {sf} semantic_official_high 必须 m67_advisory_veto(不得丢 advisory 分类)")
            if imp.get("source_field") == "semantic_web_llm" and (
                    imp.get("veto_class") != "none" or imp.get("new_entry_effect") == "hard_veto"):
                raise ValueError(f"operation_impact {sf} semantic_web_llm 必须 veto_class=none 且非 hard_veto(web/LLM 永久 advisory-only)")
        # ⑪ forward_event 来源(source_field 以 `forward_event_` 开头,覆盖 limit_unlock/earnings_disclosure/未来类)= 永久
        #   analysis-only(4.2 forward_events:不改决策、绝不 hard_veto/rescue)。source-class 级绑定(不按 veto_class 分支/不枚举
        #   具体类,防"篡改 veto_class/effect 伪装生产硬否决"+"加新类漏覆盖"):field_class 必 structured、production_effect_enabled
        #   必 False、veto_class 必 none、new_entry_effect 非 hard_veto、holding_effect ∈ {none, hold_watch}。单一 block。
        if str(imp.get("source_field", "")).startswith("forward_event_"):
            if imp.get("field_class") != "structured":
                raise ValueError(f"operation_impact {sf} forward_event 必须 field_class=structured")
            if imp.get("production_effect_enabled") is not False:
                raise ValueError(f"operation_impact {sf} forward_event 必须 production_effect_enabled=false(永久 analysis-only)")
            if imp.get("veto_class") != "none":
                raise ValueError(f"operation_impact {sf} forward_event 必须 veto_class=none(绝不否决/救回)")
            if imp.get("new_entry_effect") == "hard_veto":
                raise ValueError(f"operation_impact {sf} forward_event 不得 new_entry_effect=hard_veto")
            if imp.get("holding_effect") not in ("none", "hold_watch"):
                raise ValueError(f"operation_impact {sf} forward_event holding_effect={imp.get('holding_effect')!r} 越界(只允许 none/hold_watch)")
    if any(imp.get("veto_class") == "m67_advisory_veto" for imp in impacts) and (
            ADVISORY_VETO_TAG not in veto_text and ADVISORY_VETO_TAG not in advice_text):
        raise ValueError(f"存在 m67_advisory_veto 但 否决审查触发/操作建议 未标「{ADVISORY_VETO_TAG}」(advisory 否决须显式标非生产)")
    if any(imp.get("blocked_add_required") for imp in impacts) and (
            "禁止加仓" not in (advice_text + risk_text) and "禁止自动加仓" not in (advice_text + risk_text)):
        raise ValueError("存在 blocked_add_required=true 但 操作建议/风控触发 未显示禁止加仓(独立旗标必用户可见)")
    # ⑫ ADVICE-LANDING(R-...-ADVICE-LANDING-GAP):任一 forward_event 落地 ⟹ 操作建议含未来事件提示(候选/持仓不得仍像干净建仓;
    #   未来事件须落用户主看的操作建议,不只风控触发)。字面「未来已知事件」同步 pipeline _FORWARD_EVENT_MARKER。
    if any(str(imp.get("source_field", "")).startswith("forward_event_") for imp in impacts) and "未来已知事件" not in advice_text:
        raise ValueError("存在 forward_event_ impact 但 操作建议未含未来事件提示「未来已知事件」(候选/持仓不得仍像干净建仓)")


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
    # 4.2 第1轮: operation_impact no-dangling + advisory-isolation guard(仅当 machine.operation_impact 存在时生效)
    validate_operation_impact_no_dangling(report)
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
        # #4 no-dangling(价格提案 §8 + R-ASHORT-M67-PRICE-NODANGLE-SUBSTRING-FALSE-NEGATIVE):机器算的入场区间
        # 必须以**精确带标签短语**出现在 advice。松散 `str(x) in adv` 会被子串碰撞放过(如 entry_low=10.0 是
        # entry_high=110.0 的子串),无法证明 low 真被展示。故按 build_m67_report 生成口径精确匹配
        # 「挂单区间 {low}–{high}」(en-dash U+2013)与突破的「突破追价超过 {chase}」。
        if plan.get("entry_low") is not None and plan.get("entry_high") is not None:
            if f"挂单区间 {plan['entry_low']}–{plan['entry_high']}" not in adv:
                raise ValueError("建仓 advice 缺精确入场区间短语「挂单区间 entry_low–entry_high」(no-dangling)")
            if plan.get("chase_invalid_above") is not None and f"突破追价超过 {plan['chase_invalid_above']}" not in adv:
                raise ValueError("突破建仓 advice 缺精确追价短语「突破追价超过 chase_invalid_above」(no-dangling)")
        # #5 有效支撑(no-dangling §8 + R-ASHORT-M67-PRICE5-SUPPORT-VALUE-NODANGLE):support_quality 须 ∈ 枚举,
        # 且**支撑价位 + 质量**须以精确带标签短语在 advice 可见——只查「质量 {q}」会放过删掉支撑价位的 advice
        # (支撑是 stop/低吸带/RR 的结构价格输入,必须可见可复核)。短语须与 build_m67_report 生成口径一致。
        sq = plan.get("support_quality")
        if sq not in SR_QUALITY:
            raise ValueError(f"建仓 plan support_quality 非法 {sq!r}(须 ∈ {SR_QUALITY})")
        if f"结构支撑 {plan['support']}、质量 {sq}" not in adv:
            raise ValueError("建仓 advice 缺精确支撑短语「结构支撑 {support}、质量 {quality}」(no-dangling:须含支撑价位+质量)")
        # #6 有效压力 + t1 目标基准真实性(no-dangling §8;R-ASHORT-M67-PRICE-RESISTANCE-EFFECTIVE +
        # R-ASHORT-M67-PRICE-RESISTANCE-T1-BASIS-DANGLING):resistance_quality ∈ 枚举;t1_basis ∈ 枚举且与 t1 值 + advice
        # 文案绑定——structural 才标「目标基准:结构阻力」(且 t1 == tick_down(resistance)),fallback 标「RR 门槛兜底推算」
        # 且 advice **不得**出现「目标基准:结构阻力」(防把未用作 t1 的结构阻力虚标为目标依据,= Codex 抓到的 dangling)。
        rq = plan.get("resistance_quality")
        if rq not in SR_QUALITY:
            raise ValueError(f"建仓 plan resistance_quality 非法 {rq!r}(须 ∈ {SR_QUALITY})")
        t1_basis = plan.get("t1_basis")
        if t1_basis not in ("structural_resistance", "rr_floor_fallback"):
            raise ValueError(f"建仓 plan t1_basis 非法 {t1_basis!r}")
        if t1_basis == "structural_resistance":
            if plan.get("resistance") is None or tick_down(plan["resistance"]) != plan["t1"]:
                raise ValueError("t1_basis=structural_resistance 但 t1 ≠ tick_down(resistance)(目标基准与值不符)")
            if f"盈一 {plan['t1']} 目标基准:结构阻力 {plan['resistance']}、质量 {rq}" not in adv:
                raise ValueError("建仓 advice 缺精确结构阻力目标基准短语「盈一 {t1} 目标基准:结构阻力 {res}、质量 {q}」(no-dangling)")
        else:                                   # rr_floor_fallback:结构阻力未用作 t1 → 须标兜底、且不得虚标结构阻力为目标基准
            # 分支真实性(R-ASHORT-M67-PRICE-RESISTANCE-T1-BASIS-BRANCH-GUARD-GAP):**不只信声明分支 + 文案**——由 plan
            # 数学反算:`t1 == tick_down(resistance)` 说明 t1 其实就是结构阻力,绝不能标 fallback(否则可把 structural plan
            # 整体改标 fallback + 换 fallback 文案蒙混)。与上面 structural⇒t1==tick_down(res) 构成双向绑定(== ⟺ structural)。
            if plan.get("resistance") is not None and tick_down(plan["resistance"]) == plan["t1"]:
                raise ValueError("t1_basis=rr_floor_fallback 但 t1 == tick_down(resistance)(t1 实为结构阻力,分支标错/伪造)")
            if f"盈一 {plan['t1']} 由 RR 门槛兜底推算" not in adv:
                raise ValueError("RR 兜底建仓 advice 缺「盈一 {t1} 由 RR 门槛兜底推算」短语(no-dangling)")
            if "目标基准:结构阻力" in adv:
                raise ValueError("t1_basis=rr_floor_fallback 但 advice 仍标「目标基准:结构阻力」(虚假目标基准)")
        # #6-i RR 门槛(no-dangling §8 + R-ASHORT-M67-PRICE6-RR-FLOOR-NODANGLE):突破型抬升后的 rr_floor 是是否放行
        # 的判据,必须以精确「门槛 {rr_floor}」落到用户可见 advice(否则 render/refactor 可隐藏实际门槛而 validator 仍判一致)。
        if f"门槛 {plan['rr_floor']}" not in adv:
            raise ValueError("建仓 advice 缺精确 RR 门槛短语「门槛 {rr_floor}」(no-dangling)")
    elif action == "持有":   # S3a:持仓系统位被动显示。入/股数 必 null;损/盈一/盈二 可非空但须与 machine plan 一致。
        if tbl["入"] is not None or tbl["股数"] is not None:
            raise ValueError("持有但 table 入/股数 非空(持仓不新开仓/不重算股数)")
        if plan is not None:
            for k, pk in (("损", "stop"), ("盈一", "t1"), ("盈二", "t2")):
                pv = plan.get(pk)
                if pv is None:
                    if tbl[k] is not None:
                        raise ValueError(f"持有 table {k} 与 machine plan({pk}=None)不一致")
                elif tbl[k] is None or abs(tbl[k] - pv) > 1e-9:
                    raise ValueError(f"持有 table {k} 与 machine plan {pk} 不一致")
        else:                # 系统位未算出 → 交易字段全 null(不伪造)
            for k in ("损", "盈一", "盈二"):
                if tbl[k] is not None:
                    raise ValueError(f"持有但 machine plan 为空时 table {k} 应为 null")
        adv = m67["精简结论区"]["操作建议"]
        if "止损" not in adv:
            raise ValueError("持有建议缺 止损(诚实护栏)")
        # S3a 诚实护栏(R-ASHORT-S3A-HOLDING-LEVELS-MISSING-MANUAL-STOP-ADVICE):**按 machine 状态(plan + 手填参考)绑死**
        # advice,不靠固定短语。manual_ref = machine.stateful_risk.position.stop_loss(report 内可得)。
        manual_ref = ((mc.get("stateful_risk") or {}).get("position") or {}).get("stop_loss")
        instructs_ref = "请按手填参考止损" in adv
        if plan is not None:
            # 系统位已算出 → advice 必含执行纪律(无条件/盘中手动),不得只剩裸"止损"
            if not ("无条件" in adv or "盘中" in adv):
                raise ValueError("持有(系统位已算出)advice 缺 无条件/盘中手动 执行纪律")
        elif manual_ref is None:
            # 系统位未算出 + 无手填参考 → 绝不指示执行不存在的参考止损;须诚实标"无可执行止损位"
            if instructs_ref:
                raise ValueError("持有 系统位未算出且无手填参考止损,advice 却指示按手填参考止损执行(伪造不存在的止损)")
            if "无可执行止损位" not in adv:
                raise ValueError("持有 系统位未算出且无手填参考止损,advice 须诚实标 无可执行止损位")
        else:
            # 系统位未算出 + 有手填参考 → 须指示按手填参考止损执行
            if not instructs_ref:
                raise ValueError("持有 系统位未算出但有手填参考止损,advice 须指示按手填参考止损执行")
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
    # #6 IV-HV advisory(机器↔文案↔原始值 = 不可伪造整体;纯信息,不翻 decision):iv_gate 四键(iv_value /
    # hv_value / iv_hv_ratio / iv_hv_regime)**必存**;regime + ratio **必由 raw iv_value/hv_value 经 iv_hv_tag
    # (单一来源)重算一致**——防 raw/ratio/regime 各自漂移、防 ratio 陈旧(1.5→1.3 仍标 rich)、防 unknown 配有效 raw;
    # 文案与档位绑定(非 unknown 含「IV/HV」、unknown 含「IV-HV未知」)。
    ig = mc["iv_gate"]
    for k in ("iv_value", "hv_value", "iv_hv_ratio", "iv_hv_regime"):
        if k not in ig:
            raise ValueError(f"machine.iv_gate 缺 IV-HV 键 {k}(机器轨不完整)")
    reg, ratio = ig["iv_hv_regime"], ig["iv_hv_ratio"]
    vs = m67["精简结论区"]["波动率状态"]
    if reg not in IV_HV_REGIMES:
        raise ValueError(f"iv_hv_regime 非法 {reg!r}(须 ∈ {IV_HV_REGIMES})")
    exp_reg, exp_ratio = iv_hv_tag(ig["iv_value"], ig["hv_value"])   # 由 raw 重算的权威档位/比值(单一来源)
    if reg != exp_reg:
        raise ValueError(f"iv_hv_regime={reg} 与 raw iv_value/hv_value 重算({exp_reg})不一致")
    if reg == "unknown":
        if ratio is not None:
            raise ValueError("iv_hv_regime=unknown 但 iv_hv_ratio 非空(缺数据不得伪造比值)")
        if "IV-HV未知" not in vs:
            raise ValueError("iv_hv_regime=unknown 但波动率状态未标 IV-HV未知")
    else:
        if ratio is None or exp_ratio is None or abs(ratio - exp_ratio) > 1e-9:
            raise ValueError("iv_hv_ratio 与 round(iv_value/hv_value,4) 不一致(机器比值被篡改/漂移)")
        if "IV/HV" not in vs:
            raise ValueError(f"iv_hv_regime={reg} 但波动率状态缺 IV/HV 文案")
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
