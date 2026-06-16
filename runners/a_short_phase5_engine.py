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


def support_resistance(series: list):
    lows = [x["low"] for x in series[-SUPPORT_LOOKBACK:]]
    highs = [x["high"] for x in series[-RESISTANCE_LOOKBACK:]]
    return (min(lows) if lows else None, max(highs) if highs else None)


def effective_support(series: list, atr):
    """#5 有效支撑(策略口径,仅建仓侧):抗单日极值结构位 + 质量标记。
    `raw_low = min(近20日 low)`。若**最低 low 比次低 low 还低 > SR_SPIKE_ATR×ATR** → 判单日插针,支撑取**次低**
    (quality=`weak`);否则极值被次低背书,支撑=`raw_low`(quality=`strong`)。ATR 缺失/窗口不足两根 → 退 `raw_low`
    (quality=`fallback_extreme`,绝不伪造结构)。返回 `(support, quality, recent_low_20)`。**只影响建仓 stop/低吸带/RR
    (谁能建仓);不碰持仓**——holding 跟踪止损用 `resistance`(近20日高 raw),本切片不动 resistance(交叉引用 §5 C2/F8)。"""
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
    _, res = support_resistance(series)                  # resistance = 近20日 high raw(holding 跟踪止损依赖,本切片不动)
    atr = atr14(series)
    sup, sup_q, recent_low_20 = effective_support(series, atr)
    return {"ma5": ma(closes, 5), "ma10": ma(closes, 10), "ma20": ma(closes, 20),
            "rsi14": rsi14(closes), "atr14": atr, "support": sup, "support_quality": sup_q,
            "recent_low_20": recent_low_20, "resistance": res}


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
    t1 = res if (res and res > close) else close + rr_floor * risk
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
            "shares": shares, "avg_amount_5d": amt5, "sizing_notes": notes}, None


def holding_levels(inp: dict, ind: dict, regime: str):
    """持仓恒列入 S3a:持仓**系统**止损/止盈(被动显示,动作恒「持有」、不算股数)。跟踪止损(ratchet)=
    `recent_high(近20日最高 = ind['resistance']) − ATR_MULT[regime]×ATR`;side-aware tick(止损向上、止盈向下,
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


def build_m67_report(inp: dict, as_of: str, generated_at: str) -> dict:
    ind = compute_indicators(inp.get("price_series", []))
    fam = classify_risk_families(inp, ind)
    regime = inp.get("market_regime", "震荡期")
    regime_fallback = inp.get("regime_fallback") or {}
    regime_unknown_fallback = bool(regime_fallback.get("active"))
    regime_fallback_reason = regime_fallback.get("reason") or "EGS market_regime unknown/missing→按震荡期保守处理"
    iv_pct = (inp.get("iv") or {}).get("iv_percentile_252d")
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
        advice = (f"低吸/突破建仓建议(类型:{etype})。⭐×{star}、盈亏比 {plan['rr']}({floor_note})。{rng}。"
                  f"**试探仓**(edge 未验证,A-short 仅 risk_filter_only)。"
                  f"**止损 {plan['stop']} 无条件执行(盘中由你手动)**(基准:结构支撑 {plan['support']}、质量 {plan['support_quality']})。"
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
        advice = (f"已有持仓,本周不按新开仓处理,禁止自动加仓。持仓 {shares_hint} 股/均价 {cost_hint}。"
                  f"{sys_txt}。{manual_txt}。价格已按 A 股 0.01 规整。"
                  + (f"降级:{'/'.join(downgrades)}。" if downgrades else ""))
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
            "波动率状态": (f"IV分位≈{iv_pct}% | Rule3减半:{'是' if iv_halve else '否'}"
                          if iv_known else "IV未知(feed 缺失,未执行 IV 风控,保守减半)"),
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
            "stateful_risk": stateful,
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


def build_holding_report(inp: dict, as_of: str, generated_at: str) -> dict:
    """持仓恒列入 S1: Tier-3(本周 EGS 粗筛未覆盖)持仓的 M6.7 报告。

    **关键诚实点**:Tier-3 没有 EGS/流动性/事件数据。**绝不跑 `classify_risk_families`**——否则会在
    缺失数据上**伪造**风险族结论(实测:无流动性 → 误判流动性硬否决 → 错误「否决」一只持仓;无事件 →
    误判"无 ST")。本函数只做:持仓技术指标 + Rule12/Rule13(真实账户)+ 诚实标 EGS/语义/ST「未核查」。
    action 恒「持有」(S1 被动;主动止损/止盈/加仓是 S3)。产出与 `build_m67_report` 同形、过
    `validate_m67_consistency`。coverage_status / row_source 由 pipeline 在 build_weekly_report 后打。"""
    ind = compute_indicators(inp.get("price_series", []))
    stateful = inp.get("stateful_risk") or {}
    position = stateful.get("position") or {}
    regime = inp.get("market_regime", "震荡期")
    iv_pct = (inp.get("iv") or {}).get("iv_percentile_252d")
    iv_known = iv_pct is not None
    # EGS 派生风险族一律 not-evaluated(未核查,非 hit);stateful_risk 从真实 Rule12/Rule13。
    fam = {k: {"hit": False, "action": "none", "reasons": []} for k in
           ("market_regime", "overheat_crowding", "portfolio_concentration", "liquidity_impact",
            "event_hard_veto", "semantic_official", "stateful_risk")}
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
    advice = (f"已有持仓(本周 EGS 粗筛未覆盖,EGS/语义/ST 未自动核查)。本周不按新开仓处理、禁止自动加仓。"
              f"{sys_txt}。价格已按 A 股 0.01 规整。新闻 / ST / 监管 / 减持请人工核查。")
    m67 = {
        "精简结论区": {
            "当前环境": regime,
            "波动率状态": vol_state if iv_known else f"{vol_state}(未执行 IV 风控)",
            "现价与成本": price_cost,
            "否决审查触发": "未核查(本周 EGS 粗筛未覆盖)",
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
            "layer": {"hard_veto": [], "downgrade": sr_down, "observe_only": observe, "llm_enrichment": []},
            "entry_exit_size_star": {"action": "持有", "type": "已有持仓", "star": 0,
                                     "plan": plan, "reject_reason": hl_reject},
            "iv_gate": {"iv_percentile_252d": iv_pct, "halve": False, "status": iv_status},
            "stateful_risk": stateful, "consumption": consumption,
        },
        "boundary": {"production": False, "real_money": False,
                     "is_validated_alpha": False, "satisfies_ship_gate": False},
    }


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
