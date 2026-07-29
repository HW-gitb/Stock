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
import re

import jsonschema
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP, ROUND_DOWN

from engine.a_short_runtime_config import load_runtime_configuration
from engine.a_short_rule6_contract import assess_rule6_checks, render_rule6_d_tier_banner
from engine.a_short_regulatory_advisory import (
    RegulatoryAdvisoryContractError,
    event_fingerprint,
    resolve_regulatory_advisory,
)

SCHEMA_NAME = "a_short_m67_report"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "schemas", "a_short_m67_report.schema.json")
# ── 业务阈值只从 reviewed JSON runtime policy 导入;Python 不留数值后备 ────────
_RUNTIME_CONFIGURATION = load_runtime_configuration()
_PHASE5_POLICY = _RUNTIME_CONFIGURATION["m67"]["phase5"]
REGIMES = tuple(_PHASE5_POLICY["atr_mult"])
ATR_MULT = dict(_PHASE5_POLICY["atr_mult"])
RR_FLOOR = dict(_PHASE5_POLICY["rr_floor"])
BREAKOUT_RR_BONUS = _PHASE5_POLICY["breakout_rr_bonus"]
SINGLE_CAP_PCT = dict(_PHASE5_POLICY["single_cap_pct"])
IV_HALVE_PCT = _PHASE5_POLICY["iv_halve_pct"]
IV_NOBUILD_PCT = _PHASE5_POLICY["iv_nobuild_pct"]
IV_HV_RATIO_HI = _PHASE5_POLICY["iv_hv_ratio_hi"]
IV_HV_RATIO_LO = _PHASE5_POLICY["iv_hv_ratio_lo"]
MIN_AVG_AMOUNT_5D = _PHASE5_POLICY["min_avg_amount_5d"]
LOWXI_BAND = _PHASE5_POLICY["lowxi_band"]
SUPPORT_LOOKBACK = _PHASE5_POLICY["support_lookback"]
RESISTANCE_LOOKBACK = _PHASE5_POLICY["resistance_lookback"]
SR_SPIKE_ATR = _PHASE5_POLICY["sr_spike_atr"]
SR_QUALITY = ("strong", "weak", "fallback_extreme")   # 有效支撑质量标记(strong=极值被次低背书 / weak=插针被剔→取次低 / fallback_extreme=无法评估退原始极值)
MIN_SHARES = _PHASE5_POLICY["min_shares"]
MIN_AMOUNT = _PHASE5_POLICY["min_amount"]
IMPACT_COST_FRAC = _PHASE5_POLICY["impact_cost_frac"]

# Compatibility mirror for the pre-existing Phase 5 governance artifact and
# external readers. Both overheat values still come from the screening JSON;
# this mirror is not a second runtime source.
GOVERNANCE = dict(_PHASE5_POLICY) | {
    "overheat_5d": _RUNTIME_CONFIGURATION["screening"]["overheat_5d"],
    "overheat_20d": _RUNTIME_CONFIGURATION["screening"]["overheat_20d"],
}

RISK_FAMILIES = ("overheat_crowding", "liquidity_execution", "negative_event",
                 "market_regime", "semantic_official",
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


# ── P2 shadow-only true-pressure ladder ────────────────────────────────────
def _p2_price_series(series: list, price_data_through: str) -> list[dict]:
    """Validate a dated, PIT-bounded series before the P2 shadow calculator reads it."""
    if not isinstance(series, list) or not series:
        raise ValueError("P2 price series unavailable")
    through = str(price_data_through or "")
    if len(through) != 8 or not through.isdigit():
        raise ValueError("P2 price_data_through invalid")
    clean, previous = [], ""
    for raw in series:
        if not isinstance(raw, dict):
            raise ValueError("P2 price row invalid")
        trade_date = str(raw.get("trade_date") or "")
        if len(trade_date) != 8 or not trade_date.isdigit() or trade_date <= previous:
            raise ValueError("P2 price dates invalid")
        if trade_date > through:
            raise ValueError("P2 future price bar")
        row = {"trade_date": trade_date}
        for key in ("high", "low", "close"):
            value = raw.get(key)
            if isinstance(value, bool):
                raise ValueError("P2 price non-finite")
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("P2 price non-finite") from exc
            if not math.isfinite(value) or value <= 0:
                raise ValueError("P2 price non-finite")
            row[key] = value
        if row["low"] > row["high"]:
            raise ValueError("P2 price high/low invalid")
        clean.append(row)
        previous = trade_date
    return clean


def _p2_despiked_window_high(series: list, atr: float | None) -> tuple[float, str, str]:
    """Use the current resistance anti-spike rule without changing its M6.7 branch."""
    highs = sorted(series, key=lambda row: row["high"], reverse=True)
    raw = highs[0]
    if atr is None or atr <= 0 or len(highs) < 2:
        return raw["high"], raw["trade_date"], "fallback_extreme"
    second = highs[1]
    if raw["high"] - second["high"] > SR_SPIKE_ATR * atr:
        return second["high"], second["trade_date"], "weak"
    return raw["high"], raw["trade_date"], "strong"


def _p2_confirmed_swings(series: list) -> list[dict]:
    """Return only highs with two fully observed bars on both sides."""
    swings = []
    for index in range(2, len(series) - 2):
        high = series[index]["high"]
        left = [series[index - 2]["high"], series[index - 1]["high"]]
        right = [series[index + 1]["high"], series[index + 2]["high"]]
        if high >= max(left + right) and (high > max(left) or high > max(right)):
            swings.append({"price": high, "source_date": series[index]["trade_date"],
                           "source_kind": "confirmed_swing_high"})
    return swings


def _p2_cluster_pressure(candidates: list[dict], atr: float | None) -> list[dict]:
    """Merge close pressure levels; the lower side is the executable representative."""
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda row: (row["price"], row["source_date"], row["source_kind"]))
    groups: list[list[dict]] = []
    for candidate in ordered:
        if not groups:
            groups.append([candidate])
            continue
        previous = groups[-1][-1]
        threshold = max(0.5 * (atr or 0.0), candidate["price"] * 0.01)
        if candidate["price"] - previous["price"] <= threshold:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    zones = []
    for group in groups:
        representative = min(group, key=lambda row: (row["price"], row["source_date"]))
        has_window = any(row["source_kind"] == "window_high" for row in group)
        swing_dates = {row["source_date"] for row in group if row["source_kind"] == "confirmed_swing_high"}
        zones.append({
            "price": representative["price"],
            "price_basis": "qfq",
            "source_date": representative["source_date"],
            "source_kind": representative["source_kind"],
            "formal": has_window or len(swing_dates) >= 2,
            "cluster_sources": group,
        })
    return zones


def _p2_breakout_qualification(inp: dict, signal: dict, prior: list[dict], indicators: dict,
                               prior_atr: float | None) -> dict:
    """Freeze P2 breakout-entry eligibility independently of the target ladder."""
    momentum_confirmed = bool((inp.get("derived") or {}).get("breakout")) and \
        indicators.get("ma10") is not None and signal["close"] >= indicators["ma10"]
    if len(prior) < RESISTANCE_LOOKBACK:
        return {"momentum_confirmed": momentum_confirmed, "true_breakout": False,
                "prior_20_effective_resistance": None}
    prior_resistance, _, _ = effective_resistance(prior[-RESISTANCE_LOOKBACK:], prior_atr)
    return {"momentum_confirmed": momentum_confirmed,
            "true_breakout": bool(momentum_confirmed and prior_resistance is not None and
                                   signal["close"] > prior_resistance),
            "prior_20_effective_resistance": prior_resistance}


def _p2_target_ladder_signal(inp: dict, signal: dict, prior: list[dict], indicators: dict,
                             prior_atr: float | None) -> dict:
    """Target-exit's own frozen signal dependency; it does not share the breakout component surface."""
    momentum_confirmed = bool((inp.get("derived") or {}).get("breakout")) and \
        indicators.get("ma10") is not None and signal["close"] >= indicators["ma10"]
    if len(prior) < RESISTANCE_LOOKBACK:
        return {"momentum_confirmed": momentum_confirmed, "true_breakout": False,
                "prior_20_effective_resistance": None}
    prior_resistance, _, _ = effective_resistance(prior[-RESISTANCE_LOOKBACK:], prior_atr)
    return {"momentum_confirmed": momentum_confirmed,
            "true_breakout": bool(momentum_confirmed and prior_resistance is not None and
                                   signal["close"] > prior_resistance),
            "prior_20_effective_resistance": prior_resistance}


def _p2_target_pressure_ladder(inp: dict, entry_plan: dict | None, price_data_through: str,
                               prior: list[dict], prior_atr: float | None, target_signal: dict) -> dict:
    """Build only the P2 target-exit pressure ladder from its independently frozen signal input."""
    candidates = []
    for window in (20, 60, 120, 252):
        if len(prior) < window:
            continue
        price, source_date, quality = _p2_despiked_window_high(prior[-window:], prior_atr)
        candidates.append({"price": price, "source_date": source_date, "source_kind": "window_high",
                           "window": window, "quality": quality})
    candidates.extend(_p2_confirmed_swings(prior))
    zones = _p2_cluster_pressure(candidates, prior_atr)
    result = {
        "target_contract_version": "1.0.0", "price_basis": "qfq",
        "price_data_through": str(price_data_through), "history_bars": len(prior),
        "status": "unavailable", "reason": None, "t1": None, "t2": None, "zones": zones,
        "rr_at_entry_high": None, "rr_floor": None, "rr_eligible": None,
    }
    if not isinstance(entry_plan, dict):
        result["reason"] = "missing_official_entry_plan"
        return result
    try:
        entry_high = float(entry_plan["entry_high"])
        stop = float(entry_plan["stop"])
    except (KeyError, TypeError, ValueError, OverflowError):
        result["reason"] = "invalid_official_entry_plan"
        return result
    if not (math.isfinite(entry_high) and math.isfinite(stop) and stop < entry_high):
        result["reason"] = "invalid_official_entry_plan"
        return result
    formal_above = [zone for zone in zones if zone["formal"] and zone["price"] > entry_high]
    if formal_above:
        result["t1"] = formal_above[0]
        result["t2"] = formal_above[1] if len(formal_above) > 1 else None
        rr_floor = RR_FLOOR.get(str(inp.get("market_regime") or ""), 1.5) + \
            (BREAKOUT_RR_BONUS if target_signal["momentum_confirmed"] else 0.0)
        rr = (formal_above[0]["price"] - entry_high) / (entry_high - stop)
        result.update(status="available", rr_at_entry_high=round(rr, 6), rr_floor=rr_floor,
                      rr_eligible=rr >= rr_floor)
        if rr < rr_floor:
            result["status"] = "observe"
            result["reason"] = "real_t1_rr_below_current_gate"
        return result
    if target_signal["true_breakout"] and len(prior) >= 252:
        result.update(status="trailing_only", reason="true_breakout_no_formal_upper_pressure", rr_eligible=True)
        return result
    result["reason"] = ("insufficient_history_to_clear_upper_pressure" if len(prior) < 252
                        else "no_formal_upper_pressure_without_true_breakout")
    return result


def _p2_shadow_context(inp: dict, price_data_through: str) -> tuple[list[dict], dict, list[dict], dict, float | None]:
    """Freeze the PIT-bounded inputs shared by P2's two independent components."""
    series = _p2_price_series((inp or {}).get("price_series") or [], price_data_through)
    return series, series[-1], series[:-1], compute_indicators(series), atr14(series[:-1])


def build_p2_target_ladder(inp: dict, entry_plan: dict | None, price_data_through: str) -> dict:
    """Build the target-exit component without executing breakout-entry policy."""
    series, signal, prior, indicators, prior_atr = _p2_shadow_context(inp, price_data_through)
    del series  # the component consumes only the frozen signal/prior split below
    target_signal = _p2_target_ladder_signal(inp or {}, signal, prior, indicators, prior_atr)
    return _p2_target_pressure_ladder(inp or {}, entry_plan, price_data_through, prior, prior_atr, target_signal)


def build_p2_breakout_qualification(inp: dict, price_data_through: str) -> dict:
    """Build the breakout-entry component without executing target-ladder policy."""
    series, signal, prior, indicators, prior_atr = _p2_shadow_context(inp, price_data_through)
    del series
    return _p2_breakout_qualification(inp or {}, signal, prior, indicators, prior_atr)


def build_true_pressure_targets(inp: dict, entry_plan: dict | None, price_data_through: str) -> dict:
    """Build P2's shadow T1/T2 ladder without touching the official M6.7 plan.

    The signal-day bar is deliberately excluded from all resistance baselines.
    Returned values retain enough private provenance for later capture; callers
    decide whether to expose a de-identified summary.
    """
    # Compatibility facade for direct callers.  The P2 runner invokes the two
    # component wrappers separately so their epoch identities remain isolated.
    result = build_p2_target_ladder(inp, entry_plan, price_data_through)
    result.update(build_p2_breakout_qualification(inp, price_data_through))
    return result


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
def classify_risk_families(inp: dict, ind: dict, rule6_gate: dict | None = None) -> dict:
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
    rule6_gate = rule6_gate or assess_rule6_checks(inp.get("rule6_checks"))
    fam = {f: {"hit": False, "action": None, "reasons": []} for f in RISK_FAMILIES}

    # overheat_crowding only consumes the production EGS price/behaviour fields.
    # The theme overlay is a comparison artifact and must not enter a risk family.
    oh = bool(d.get("overheat") or d.get("chasing_high") or d.get("chase"))
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
    # Rule6's 50ETF IV row is the same market-wide "no new position" rule as
    # Rule3.  A held position must retain its S3a/S3b management path, so this
    # one market-level failure is advisory for holdings only.  Security-specific
    # Rule6 failures remain hard vetoes in either state.
    held_market_rule6_ids = (
        [check_id for check_id in rule6_gate["hard_veto_check_ids"]
         if check_id == "rule6_50etf_iv"]
        if has_position else []
    )
    negative_rule6_ids = [
        check_id for check_id in rule6_gate["hard_veto_check_ids"]
        if check_id not in held_market_rule6_ids
    ]
    if negative_rule6_ids:
        ner.append("Rule6 已命中:" + ",".join(negative_rule6_ids))
    if ner:
        fam["negative_event"].update(hit=True, action="hard_veto", reasons=ner)

    # market_regime(IV 闸门 + 防御/收缩)。**新建仓限制 vs 持仓管理**:IV>90/收缩期 是 v14.2 的
    # "终止所有建仓 / 禁新建仓"语义(Rule3 / M1),只约束**新开仓**,对**已有持仓**不应硬否决——持仓管理
    # (S3a 系统止损/止盈、S3b 处置)须继续。故市场级 hard_veto 仅对空仓(not has_position);持仓侧降为
    # advisory downgrade(reason 仍捕获、进 M6.7 降级文案,但不抹掉 持有 分支的 S3a/S3b)。镜像本函数
    # stateful_risk 的"新建仓硬限制仅空仓"范式;对齐 Tier-3 build_holding_report(持仓恒「持有」)。
    mr = []
    if regime_unknown_fallback:
        mr.append(regime_fallback_reason)
    nobuild_iv = iv_pct is not None and iv_pct > IV_NOBUILD_PCT
    held_suffix = "(已有持仓:持仓管理继续,advisory)" if has_position else ""
    if nobuild_iv:
        mr.append(f"IV分位{iv_pct}>{IV_NOBUILD_PCT} 不可建仓{held_suffix}")
    elif regime == "收缩期":
        mr.append(f"收缩期禁新建仓{held_suffix}")
    elif iv_pct is not None and iv_pct > IV_HALVE_PCT:
        mr.append(f"IV分位{iv_pct}>{IV_HALVE_PCT} 减半")
    if held_market_rule6_ids:
        mr.append("Rule6 市场级禁新建仓(" + ",".join(held_market_rule6_ids)
                  + ")；已有持仓继续管理(advisory)")
    if (nobuild_iv or regime == "收缩期") and not has_position:
        fam["market_regime"].update(hit=True, action="hard_veto", reasons=mr)  # 空仓:新建仓硬否决
    elif mr:
        # 持仓遇 IV>90/收缩期 → advisory downgrade(不硬否决,持有分支照走 holding_levels);
        # 空仓 IV>80 → 减半 downgrade;regime unknown → 保守 downgrade。
        fam["market_regime"].update(hit=True, action="downgrade", reasons=mr)

    # stateful_risk(Rule12/Rule13 + 当前持仓):已有持仓只做持仓管理/禁止加仓;
    # flat candidate 在 Rule12 冷静期或 Rule13 再入冷静期内不可新建仓。
    sr_hard = []
    sr_down = []
    if has_position:
        sr_down.append("已有持仓:按持仓管理输出,不按新开仓处理")
    integrity = stateful.get("account_integrity") or {}
    if integrity.get("new_entry_blocked"):
        kinds = ",".join(str(x) for x in (integrity.get("blocking_kinds") or [])) or "unknown"
        if has_position:
            sr_down.append(f"account_integrity blocked({kinds}):已有持仓仅管理/禁止加仓")
        else:
            sr_hard.append(f"account_integrity blocked({kinds}):持仓对账未闭环,禁止新开仓")
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
    if breakout_source_agreement(inp, ind) == "agree_true":
        return "突破", "站稳 MA10 + 放量"
    if sup and abs(close - sup) / sup <= LOWXI_BAND:
        return "低吸", "现价近关键支撑"
    return "观察", "未到低吸/突破触发"


def breakout_source_agreement(inp: dict, ind: dict) -> str:
    """Expose the existing conservative breakout AND-gate without changing it.

    EGS owns the upstream breakout predicate; Phase 5 independently verifies
    the local settled close against its own MA10.  This returns only the
    categorical agreement state, never a price or moving-average value.
    """
    egs_breakout = bool((inp.get("derived") or {}).get("breakout"))
    close, ma10 = inp.get("close"), ind.get("ma10")
    pipeline_breakout = bool(ma10 and close is not None and close >= ma10)
    if egs_breakout and pipeline_breakout:
        return "agree_true"
    if not egs_breakout and not pipeline_breakout:
        return "agree_false"
    return "egs_only" if egs_breakout else "pipeline_only"


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
    if not use_structural_res:
        # Fallback target and RR gate must share the same worst-case entry basis.  The old code
        # derived t1 from ``close`` and then judged it against ``entry_high``, making valid
        # breakout fallback cases structurally unreachable.
        t1_t = tick_up(entry_high + rr_floor * risk_eh)
        t2_t = tick_down(max(t1_t + ATR_MULT.get(regime, 1.25) * atr,
                             entry_high + 2.0 * risk_eh))
        if t1_t is None or t2_t is None or t2_t < t1_t:
            return None, "RR fallback 目标取整后结构失效"
    rr_eh = (t1_t - entry_high) / risk_eh
    if rr_eh < rr_floor:
        return None, f"最不利价(区间上沿)盈亏比 {rr_eh:.2f} < {rr_floor}"
    # The upper edge is the executable decision price. Keep gate, plan,
    # sizing, table, advice, and displayed RR on this one post-tick value.
    entry_t = entry_high
    if not (stop_t < entry_t and t1_t > entry_t):
        return None, "最不利价取整后结构失效(止损≥入/止盈≤入)"
    # 仓位:单只上限 + 冲击成本 + 100股 + 试探仓 + IV 减半;股数/最小金额/现金上限按**最不利买入价 entry_high** 计(§11.3)。
    cap_pct = SINGLE_CAP_PCT.get(regime, 0.40)
    if cap_pct <= 0:
        return None, "本环境禁新建仓"
    acct = inp.get("account") or {}
    avail = acct.get("available_cash") or 0.0
    amt5 = (inp.get("liquidity") or {}).get("avg_amount_5d") or 0.0
    bucket_capital = acct.get("bucket_capital")
    new_capacity = acct.get("new_exposure_capacity")
    if bucket_capital is not None or new_capacity is not None:
        if not isinstance(bucket_capital, (int, float)) or isinstance(bucket_capital, bool) or bucket_capital <= 0:
            return None, "bucket_capital 缺失/非法,禁止新建仓"
        if not isinstance(new_capacity, (int, float)) or isinstance(new_capacity, bool) or new_capacity <= 0:
            return None, "A-short bucket 已满/超限(new_exposure_capacity<=0),禁止新建仓"
        cap = min(float(avail), float(bucket_capital) * cap_pct,
                  float(new_capacity), amt5 * IMPACT_COST_FRAC)
        notes.append(
            f"bucket额度:capital={float(bucket_capital):.2f},remaining={float(new_capacity):.2f}")
    else:
        # Backward-compatible pure-engine mode. The production weekly pipeline always supplies the
        # bucket context; legacy direct unit callers remain usable until their fixtures migrate.
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
            "rr": round(rr_eh, 3), "rr_at_entry_high": round(rr_eh, 3), "rr_floor": rr_floor,
            "support": sup, "support_quality": ind.get("support_quality"),   # #5 stop 的结构支撑基准 + 质量
            "resistance": res, "resistance_quality": ind.get("resistance_quality"),   # #6 t1/RR 的结构阻力基准 + 质量
            "t1_basis": t1_basis,   # #6:t1 来源(structural_resistance / rr_floor_fallback)——决定 advice 目标基准文案是否标结构阻力
            "shares": shares, "avg_amount_5d": amt5, "sizing_notes": notes,
            "capital_context": ({"bucket_capital": float(bucket_capital),
                                 "new_exposure_capacity": float(new_capacity),
                                 "single_position_cap_pct": cap_pct}
                                if bucket_capital is not None else None)}, None


def holding_levels(inp: dict, ind: dict, regime: str):
    """持仓恒列入 S3a:持仓**系统**止损/止盈(被动显示,动作恒「持有」、不算股数)。跟踪止损(ratchet)=
    `recent_high(= ind['resistance'];#6 起为**有效压力**=去单日插针后的近20日最高) − ATR_MULT[regime]×ATR`;side-aware tick(止损向上、止盈向下,
    = 最终可执行价)+ post-tick 重校验。缺价/ATR/最高价 → reject(render 显"未算出",**绝不伪造**);
    现价 ≤ 取整后跟踪止损,或取整后止盈结构失效 → `breached`(t1/t2=None,标已破位、不伪造止盈)。
    返回 (plan, None) | (None, reject_reason)。"""
    close, atr = inp.get("close"), ind.get("atr14")
    position = ((inp.get("stateful_risk") or {}).get("position") or {})
    entry_date = str(position.get("entry_date") or "")
    manual_stop = position.get("stop_loss")
    price_series = inp.get("price_series") or []
    highest_since_entry = None
    if entry_date:
        if not _is_valid_date(entry_date):
            return None, "持仓入场日期非法，无法验证入场后最高价"
        dated_post_entry = []
        for row in price_series:
            if not isinstance(row, dict):
                return None, "持仓价格行缺失或非法，无法验证入场后最高价"
            trade_date = str(row.get("trade_date") or "")
            high = row.get("high")
            if not _is_valid_date(trade_date):
                return None, "持仓价格日期缺失或非法，无法验证入场后最高价"
            if trade_date >= entry_date:
                if (not isinstance(high, (int, float)) or isinstance(high, bool)
                        or not math.isfinite(float(high))):
                    return None, "入场后价格最高价缺失或非法，无法精算跟踪止损"
                dated_post_entry.append(float(high))
        if not dated_post_entry:
            return None, "缺入场后价格，无法精算跟踪止损"
        highest_since_entry = max(dated_post_entry)
    elif manual_stop is None:
        highest_since_entry = ind.get("resistance")
    if close is None or atr is None or atr <= 0 or (highest_since_entry is None and manual_stop is None):
        return None, "缺价/ATR/入场后最高价与初始止损,无法精算跟踪止损"
    stop_candidates = []
    if isinstance(manual_stop, (int, float)) and not isinstance(manual_stop, bool):
        stop_candidates.append(float(manual_stop))
    if highest_since_entry is not None:
        stop_candidates.append(highest_since_entry - ATR_MULT.get(regime, 1.25) * atr)
    stop = tick_up(max(stop_candidates))     # 初始止损锁定 + 入场后 trailing,只升不降
    if stop is None:
        return None, "止损非有限,取整失败"
    base = {"entry": None, "shares": None, "stop": stop, "basis": "trailing_ratchet",
            "recent_high": highest_since_entry, "highest_since_entry": highest_since_entry,
            "entry_stop": manual_stop, "entry_date": entry_date or None, "atr": atr}
    risk = close - stop
    if risk <= 0:                          # 现价 ≤ 取整后跟踪止损 → 已破位(被动诚实,不伪造止盈)
        return {**base, "t1": None, "t2": None, "breached": True}, None
    rr_floor = RR_FLOOR.get(regime, 1.5)
    res = ind.get("resistance")
    raw_t1 = res if (res and res > close) else close + rr_floor * risk
    t1 = tick_down(raw_t1)                 # 止盈向下取(不高估可实现目标)
    t2 = tick_down(max(raw_t1 + ATR_MULT.get(regime, 1.25) * atr, close + 2.0 * risk))
    if t1 is None or t2 is None or not (t1 > close and t2 >= t1):      # post-tick 结构失效 → 退破位
        return {**base, "t1": None, "t2": None, "breached": True}, None
    return {**base, "t1": t1, "t2": t2, "breached": False}, None


def compute_star(inp: dict, fam: dict, eligible: bool) -> int:
    star = 3
    # `eligible` is retained only for call compatibility. The theme overlay
    # is comparison-only and can neither add nor remove a production star.
    del eligible
    # Only the source-bound deterministic SW-L2 industry trend may apply this
    # formal -1. The LLM fundamental/policy advisory is display-only.
    if inp.get("industry_trend") == "headwind":
        star -= 1
    if fam["overheat_crowding"]["action"] == "downgrade":
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


_FINANCIAL_QUALITY_MARKER = "财报质量对照"   # build_m67 落 风控触发 + guard ⑮ 据此判 no-dangling(单一来源)


def _financial_quality_operation_impacts(fq, as_of):
    """4.2 财报质量①(复用,comparison-only):把 egs_main 已取的 fina_indicator 派生(扣非净利/同比/ROE/现金流质量/质量旗标)
    surface 成 advisory operation_impact —— **零新取数、绝不 hard_veto、production_effect_enabled=false、不改 EGS/选股/股数/否决**
    (这些值本就已被 EGS 评分消费,此处只把红旗落地透明化)。仅候选行(new_entry);仅在有红旗(EGS 既有 ESP-Q 质量旗标 或
    扣非净利同比<0 利润下滑)时发,无红旗不发(避免噪声)。持仓财报质量留后续刀。red-flag 复用 EGS 既有判据/自然符号,不新设阈值(决策4)。"""
    fq = fq or {}
    flags = str(fq.get("l2_flags") or "")
    yoy = fq.get("q0_dt_yoy")
    esp_q = "ESP-Q" in flags
    decline = isinstance(yoy, (int, float)) and not isinstance(yoy, bool) and yoy < 0
    if not (esp_q or decline):
        return []
    bits = []
    if yoy is not None:
        bits.append(f"扣非净利同比{yoy}%")
    if fq.get("q0_profit_dedt") is not None:
        bits.append(f"扣非净利{fq.get('q0_profit_dedt')}")
    if fq.get("roe") is not None:
        bits.append(f"ROE{fq.get('roe')}%")
    if fq.get("ttm_ocf_ratio") is not None:
        bits.append(f"经营现金流/利润{fq.get('ttm_ocf_ratio')}")
    red = ([] + (["EGS扣非净利质量旗标(ESP-Q)"] if esp_q else [])
           + (["扣非净利同比为负(利润下滑)"] if decline else []))
    reason = (f"{_FINANCIAL_QUALITY_MARKER}(comparison-only,不改决策/EGS/选股/股数):{'、'.join(red)}"
              + (f";{' / '.join(bits)}" if bits else "")
              + "(财报质量红旗,仅 advisory 降优先级参考,绝不否决)")
    return [{
        "source_field": "financial_quality",
        "field_class": "structured",
        "visibility_shape": "candidate_row_impact",
        "impact_scope": "new_entry",
        "new_entry_effect": "priority_down",
        "holding_effect": "none",
        "blocked_add_required": False,
        "veto_class": "none",
        "reason": reason,
        "evidence_ref": {"kind": "lineage_key",
                         "value": "fundamental.profitability / fundamental.quality / scores.l2_flags",
                         "as_of": str(as_of)},
        "confidence": "high",
        "pit_basis": "disclosure_date",
        "production_effect_enabled": False,
        "implementation_status": "implemented",
        "m67_landing_surface": "精简结论区.风控触发(财报质量对照)",
        "terminal_surface_target": "already_structured",
        "pending_successor_slice": None,
        "privacy_class": "public_tracked",
    }]


def _semantic_operation_impacts(high_material, web, web_downgrade, as_of, scope):
    """4.2 第3轮:把已校验的 semantic 信号(official high 经人工确认重大 / web downgrade)统一成 advisory
    operation_impact(复用 build_m67/holding 已算标志,不重复校验,DRY 单一来源)。
    scope='new_entry'(候选行)→ candidate_row_impact / 已结构化落点;
    scope='existing_holding'(持仓行)→ holding_row_impact / 持仓处置列 + 禁止加仓 + R3 减仓价/清仓价(经合并引擎/_apply);到价提示/移保本=R4a(within-week advisory)、跨周持久收紧 ratchet=R4b。
    semantic 永远 advisory:production_effect_enabled=False;只有人工确认重大的 official high→m67_advisory_veto、web_llm→veto_class=none
    (web/LLM 永久 advisory-only,绝不 hard_veto)。持仓 blocked_add=True(禁止加仓)、私密(private_account)。"""
    impacts, as_of = [], str(as_of)
    is_holding = scope == "existing_holding"
    if high_material:
        impacts.append({
            "source_field": "semantic_official_high_confirmed",
            "field_class": "semantic_advisory",
            "visibility_shape": "holding_row_impact" if is_holding else "candidate_row_impact",
            "impact_scope": scope,
            "new_entry_effect": "none" if is_holding else "hard_veto",
            "holding_effect": "clear_review" if is_holding else "none",
            "blocked_add_required": is_holding,
            "veto_class": "m67_advisory_veto",
            "reason": ("持仓官方结构化 high+证据齐全+人工确认重大 → 清仓复核建议(人工,不自动卖出;清仓价见 R3 结构化列、到价提示/移保本=R4a(within-week advisory)、跨周持久收紧 ratchet=R4b)" if is_holding
                       else f"官方结构化 high+证据齐全(非空 url_or_pdf)+人工确认重大 → M6.7 advisory 否决({ADVISORY_VETO_TAG},不进 EGS/回测)"),
            "evidence_ref": {"kind": "lineage_key",
                             "value": "machine.layer.semantic_risk.official_status/events",
                             "as_of": as_of},
            "confidence": "high",
            "pit_basis": "disclosure_date",
            "production_effect_enabled": False,
            "implementation_status": "implemented",
            "m67_landing_surface": ("持仓处置/禁止加仓 + 清仓价/减仓价 + 到价提示/移保本 + ratchet advisory" if is_holding
                                    else "table.操作=否决 + 精简结论区.否决审查触发"),
            "terminal_surface_target": "already_structured",
            "pending_successor_slice": None,
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
            "implementation_status": "implemented",
            "m67_landing_surface": ("持仓处置/禁止加仓 + 清仓价/减仓价 + 到价提示/移保本 + ratchet advisory" if is_holding
                                    else "精简结论区.风控触发"),
            "terminal_surface_target": "already_structured",
            "pending_successor_slice": None,
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
    try:
        regulatory = resolve_regulatory_advisory(sem, str(inp.get("ts_code") or ""))
    except RegulatoryAdvisoryContractError as exc:
        raise ValueError(f"regulatory advisory confirmation invalid: {exc}") from exc
    # 只有证据齐全(非空 url_or_pdf)且人工确认重大的 high 才计 veto/清仓复核;其余 high → 待人工确认。
    high_full = [e for e in sem_events if e["severity"] == "high" and e["url_or_pdf"].strip()]
    high_incomplete = [e for e in sem_events if e["severity"] == "high" and not e["url_or_pdf"].strip()]
    high_material = list(regulatory["high_material"])
    sem_pending = bool(sem_events) and (
        bool(regulatory["pending_high"])
        or any(event["severity"] in ("medium", "low") for event in sem_events)
    )
    sem_impact = "veto" if high_material else ("pending" if sem_pending else "none")
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
             "regulatory_confirmation": {
                 "status": regulatory["status"],
                 "event_fingerprints": [event_fingerprint(str(inp.get("ts_code") or ""), event)
                                        for event in sem_events],
                 "confirmed_material_event_fingerprints": [
                     event_fingerprint(str(inp.get("ts_code") or ""), event)
                     for event in high_material
                 ],
                 "pending_high_event_fingerprints": [
                     event_fingerprint(str(inp.get("ts_code") or ""), event)
                     for event in regulatory["pending_high"]
                 ],
                 "confirmed_material_high_count": len(high_material),
                 "pending_high_count": len(regulatory["pending_high"]),
                 "confirmed_not_material_count": regulatory["confirmed_not_material_count"],
                 "needs_more_information_count": regulatory["needs_more_information_count"],
             },
             "web_llm": {"status": web_status,
                         "risk_level": (web.get("risk_level") if web else "unknown"),
                         "action": (web.get("action") if web else "no_action"),
                         "sources_count": len(web_sources),
                         "impact": ("downgrade" if web_downgrade else "none"),
                         "invalid_neutralized": web_invalid}}
    return {"sem": sem, "sem_status": sem_status, "sem_events": sem_events, "sem_sevs": sem_sevs,
            "high_full": high_full, "high_material": high_material, "high_incomplete": high_incomplete,
            "regulatory": regulatory, "sem_pending": sem_pending,
            "sem_impact": sem_impact, "web": web, "web_sources": web_sources, "web_status": web_status,
            "web_downgrade": web_downgrade, "trace": trace}


def _semantic_holding_lines(sc: dict) -> list:
    """4.2 S2: 持仓 semantic 的用户可见文本行(build_m67 持仓分支 + build_holding_report 共用,防漂移)。
    official 证据齐全且人工确认重大 high → 清仓复核(标非生产 advisory);web → 持仓警戒;pending → 待核。持仓恒持有、不自动卖出;减仓价/清仓价见 R3(advisory),到价提示/移保本=R4a(within-week advisory)、跨周持久收紧 ratchet=R4b。"""
    lines = []
    if sc["high_material"]:
        lines.append(f"官方结构化 high({ADVISORY_VETO_TAG}):建议清仓复核(人工,不自动卖出,清仓价见 R3 结构化列,到价提示/移保本=R4a(within-week advisory)、跨周持久收紧 ratchet=R4b)")
    if sc["web_downgrade"]:
        lines.append(f"web/LLM {sc['web_status']}({sc['web'].get('risk_level')}):持仓警戒(advisory)")
    if sc["sem_pending"]:
        lines.append("官方语义待核(证据不全/medium·low,未扣分)")
    return lines


# ── S3b R1+R2: 持仓处置 结构化列 + severity 合并引擎 ───────────────────────────────────────────
# 把 held 报告各 holding_row_impact 的 holding_effect 合成一个结构化「持仓处置」(决策1:操作 enum 不扩,持仓处置是独立列)+
# 「禁止加仓」布尔(blocked_add_required OR)。**advisory 复核建议、不自动卖出**;减仓价/清仓价=R3、到价提示/移保本=R4a(within-week advisory)、跨周持久收紧 ratchet=R4b。
# severity-max = anti-rescue(正面/低信号不能压低高信号);仅 held 报告。S3a holding_levels(被动系统止损/止盈)是另一维(价格位),不冲突。
_HOLDING_SEVERITY = ["clear_review", "reduce_review", "manual_review", "hold_watch", "hold"]   # 降序(§7.1;none/缺省=最低,默认 hold)
_HOLDING_DISPOSITION_LABEL = {"hold": "持有", "hold_watch": "持有警戒", "reduce_review": "建议减仓复核",
                              "clear_review": "建议清仓复核", "manual_review": "立即人工复核"}
_REDUCE_RATIO_ADVISORY = "1/3"   # S3b R3: reduce_review 的 advisory 减仓比例(固定档,人工复核定量;advisory、不自动执行)


def _is_held_signal(imp):
    """S3b 持仓处置合并的**唯一合法输入** = 真正的持仓侧信号:visibility_shape==holding_row_impact + impact_scope==existing_holding +
    私密(private_account/secret_or_raw_provider)。候选/公开 shape 的 impact(即便被篡改带上 holding_effect/blocked_add_required)绝不参与
    持仓处置合并——**fail-closed on scope**(防 builder 漂移或手构报告把 public/candidate 证据提升成私密持仓处置;呼应 ⑬⑭/⑮⑯ 同类
    guard-vs-claim 边界)。R-ASHORT-S3B-HOLDING-DISPOSITION-SCOPE-GUARD-GAP。"""
    return (imp.get("visibility_shape") == "holding_row_impact"
            and imp.get("impact_scope") == "existing_holding"
            and imp.get("privacy_class") in ("private_account", "secret_or_raw_provider"))


def _merge_holding_disposition(op_impacts, *, plan=None, hard_veto=False):
    """S3b R1+R2 合并引擎:从持仓 machine.operation_impact 合成 (holding_management_signal, blocked_add_required)。
    **仅 _is_held_signal(持仓侧 shape/scope/私密)的 impact 参与**(scope fail-closed;候选/公开 shape 即便带 holding_effect/blocked 也忽略)。
    signal = 各合法 impact 的 holding_effect 取 **severity-max**(clear_review>reduce_review>manual_review>hold_watch>hold;none/缺省不计;
    全无 → 默认 'hold'=持有)——severity-max 即 **anti-rescue**(正面/低信号不能压低高信号)。
    blocked_add_required = 各合法 impact 的 blocked_add_required **OR**；系统计划破位或持仓命中明确硬风险
    也会在这里作为最高级 `clear_review` 输入。这样 build、pipeline 重算和 validator 共享同一处置真值，
    而不把持仓降级成候选式否决、丢掉已有退出计划。"""
    best, blocked = "hold", False
    for imp in (op_impacts or []):
        if not _is_held_signal(imp):
            continue
        if imp.get("blocked_add_required"):
            blocked = True
        eff = imp.get("holding_effect")
        if eff in _HOLDING_SEVERITY and _HOLDING_SEVERITY.index(eff) < _HOLDING_SEVERITY.index(best):
            best = eff
    if hard_veto:
        best, blocked = "clear_review", True
    if isinstance(plan, dict) and plan.get("breached"):
        best = "clear_review"
    return best, blocked


# ── S3b R4a: 持仓主动管理 within-week advisory(到价提示 price_cross + 移保本 move_to_breakeven)───────────────
# 均 advisory:**不改 disposition/操作/不自动卖出/不改 plan.stop**;跨周持久化 + 单向收紧 ratchet = R4b(已实现,见 `_holding_ratchet`)。
# 到价复用 M6.7 价格钟现价(inp.close = machine.current_close,与 S3a/render 同一来源),比对 R3 减仓价(=S3a 盈一 plan.t1)/清仓价(=S3a 损 plan.stop)。
# 移保本 1R 基准 = 成本价 − S3a 系统跟踪止损 plan.stop(用户拍板;无新阈值、不依赖可选手填止损):浮盈≥1R → 建议移止损到成本价(不自动改 plan.stop=R4b ratchet)。
def _is_finite_num(x):
    """有限数值(排除 None/bool/NaN/Inf)——价位/现价比较前的安全门(pre-flight F:非有限值)。"""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _holding_active_alerts(close, sig, reduce_price, clear_price, plan_stop, avg_cost):
    """S3b R4a within-week advisory(单一来源:_apply 设值 + validate 独立重算共用,防两份派生漂移)。返回 (price_cross, move_to_breakeven)。

    **到价提示 price_cross**(由 disposition 决定哪个价位生效;不改 disposition/操作/不自动卖):
      reduce_review & 现价 ≥ 减仓价(盈一 plan.t1)→ 'reduce_price_reached';
      clear_review & 现价 ≤ 清仓价(损 plan.stop)→ 'clear_price_reached';其余 disposition / 缺价 → 'none'。
      (减仓价=plan.t1 恒 > 现价[S3a holding_levels 构造,line 502],故周内基本不触发,跨周由 R4b 持久层激活;清仓价=plan.stop,现价≤stop = S3a 破位。)
    **移保本 move_to_breakeven**(disposition 无关,仅看浮盈;1R 基准 = 成本价 − S3a plan_stop):
      仅 plan_stop < 成本价(R>0)且 现价 ≥ 成本价 + R(= 2·成本价 − plan_stop)→ triggered + breakeven_price=成本价
      (建议把保护止损上移到成本价;**不自动改 plan.stop** = R4b ratchet)。plan_stop ≥ 成本价(已无亏损风险)/缺价/缺成本/破位 → 不触发(breakeven_price=None)。"""
    status = "none"
    if sig == "reduce_review" and _is_finite_num(close) and _is_finite_num(reduce_price) and close >= reduce_price:
        status = "reduce_price_reached"
    elif sig == "clear_review" and _is_finite_num(close) and _is_finite_num(clear_price) and close <= clear_price:
        status = "clear_price_reached"
    triggered, breakeven_price = False, None
    if _is_finite_num(close) and _is_finite_num(avg_cost) and _is_finite_num(plan_stop):
        risk = avg_cost - plan_stop
        if risk > 0 and close >= avg_cost + risk:
            triggered, breakeven_price = True, avg_cost
    return status, {"triggered": triggered, "breakeven_price": breakeven_price}


# ── S3b R4b: 跨周持久收紧 ratchet(纯函数;pipeline 持久层 apply + validate 共用单一来源)──────────────
# 把 R4a 的 within-week advisory 沉淀成跨周状态:**止损只升不降、disposition 只升档不降(anti-rescue across weeks)**;
# keyed on (ts_code, entry_date),re-entry(新 entry_date)重置(防永久 trap)。持久层 IO/私密路由在 pipeline(涉真实持仓)。
def _severity_max_disposition(a, b):
    """两个 disposition 取 severity-max(更严的,_HOLDING_SEVERITY 降序 index 越小越严);非法值按 hold(最低)。"""
    ia = _HOLDING_SEVERITY.index(a) if a in _HOLDING_SEVERITY else _HOLDING_SEVERITY.index("hold")
    ib = _HOLDING_SEVERITY.index(b) if b in _HOLDING_SEVERITY else _HOLDING_SEVERITY.index("hold")
    return a if ia <= ib else b


def _holding_ratchet(this_week, last_week):
    """S3b R4b 跨周持久收紧 ratchet(纯函数,单一来源:pipeline apply + validate 共用,防漂移)。
    this_week = {ts_code, entry_date, as_of, close(价格钟), stop(S3a plan.stop), breakeven(R4a move_to_breakeven.breakeven_price 或 None),
                 disposition(holding_management_signal), reduce_price(R3), clear_price(R3)};
    last_week = 上周持久行 {entry_date, ratcheted_stop, last_disposition, last_reduce_price, last_clear_price, week_count} 或 None。

    **单向只升不降**(plan + 用户 Q2=只升):
      ratcheted_stop = max(本周 effective_stop = max(S3a stop, R4a breakeven), 上周 ratcheted_stop) —— 止损只升不降;
      ratcheted_disposition = severity-max(本周 disposition, 上周 last_disposition) —— disposition 只升档不降。
    **re-entry 重置**:last_week 缺失 或 entry_date 变(换仓)→ bootstrap(ratcheted=本周值、week_count=1、无跨周到价)。
    **跨周到价**(用户 Q1 滚动 + 清仓跟 ratcheted_stop):续持时 本周现价 ≥ **上周 last_reduce_price** → reduce_price_reached(滚动一周);
      本周现价 ≤ ratcheted_stop → clear_price_reached(清仓价跟 ratcheted_stop);else none。advisory,不自动卖/不改 table.损。
    返回 (machine_ratchet, persisted_row):machine_ratchet={ratcheted_stop,ratcheted_disposition,week_count,cross_week_price_cross,bootstrap};
      persisted_row=写回 sidecar 新行(last_as_of=本周 as_of;last_reduce_price=**本周 reduce_price** 供下周滚动比对;last_clear_price=ratcheted_stop)。"""
    ed = str(this_week.get("entry_date"))
    as_of = str(this_week.get("as_of") or "")
    # 同周 re-run 幂等(plan「跨周持久幂等」):last_week 已是本周态(同 entry_date 且 last_as_of==本次 as_of)→ 原样返回
    # (不增 week_count、不重算跨周到价;ratcheted_stop max / disposition severity-max 本就幂等,但 week_count/cross_week 需显式幂等)。
    if (last_week is not None and str(last_week.get("entry_date")) == ed
            and str(last_week.get("last_as_of")) == as_of):
        return ({"ratcheted_stop": last_week.get("ratcheted_stop"),
                 "ratcheted_disposition": last_week.get("last_disposition"),
                 "week_count": last_week.get("week_count"),
                 "cross_week_price_cross": last_week.get("cross_week_price_cross"),
                 "bootstrap": last_week.get("bootstrap")}, dict(last_week))
    disp = this_week.get("disposition") if this_week.get("disposition") in _HOLDING_SEVERITY else "hold"
    close = this_week.get("close")
    eff_cands = [v for v in (this_week.get("stop"), this_week.get("breakeven")) if _is_finite_num(v)]
    eff_stop = max(eff_cands) if eff_cands else None       # 本周 within-week 最紧止损(S3a 止损 vs R4a 保本)
    cw = "none"
    if last_week is not None and str(last_week.get("entry_date")) == ed:        # 续持(非 re-entry)
        last_stop = last_week.get("ratcheted_stop")
        stop_cands = [v for v in (eff_stop, last_stop) if _is_finite_num(v)]
        ratcheted_stop = max(stop_cands) if stop_cands else None                # 只升不降:缺本周值则保留上周
        ratcheted_disposition = _severity_max_disposition(disp, last_week.get("last_disposition") or "hold")
        week_count = int(last_week.get("week_count") or 0) + 1
        bootstrap = False
        lrp = last_week.get("last_reduce_price")
        if _is_finite_num(close) and _is_finite_num(lrp) and close >= lrp:
            cw = "reduce_price_reached"                                         # 滚动:现价到上周减仓价(盈一)
        elif _is_finite_num(close) and _is_finite_num(ratcheted_stop) and close <= ratcheted_stop:
            cw = "clear_price_reached"                                          # 现价跌破跨周收紧止损
    else:                                                                       # 首周 / re-entry(换仓)→ 重置
        ratcheted_stop, ratcheted_disposition, week_count, bootstrap = eff_stop, disp, 1, True
    machine_ratchet = {"ratcheted_stop": ratcheted_stop, "ratcheted_disposition": ratcheted_disposition,
                       "week_count": week_count, "cross_week_price_cross": cw, "bootstrap": bootstrap}
    persisted_row = {"ts_code": str(this_week.get("ts_code") or ""), "entry_date": ed,
                     "last_as_of": as_of, "ratcheted_stop": ratcheted_stop,
                     "last_disposition": ratcheted_disposition, "last_reduce_price": this_week.get("reduce_price"),
                     "last_clear_price": ratcheted_stop, "week_count": week_count,
                     "cross_week_price_cross": cw, "bootstrap": bootstrap}
    return machine_ratchet, persisted_row


def _ratchet_report_error(mc):
    """S3b R4b: machine.ratchet 的 **within-report 弱不变式**(单一来源:validate_m67_consistency 持有分支 + pipeline _apply_holding_ratchet
    写后共用,防两份漂移)。不依赖上周持久态(跨周 only-up vs 上周 / 滚动到价 / re-entry / 幂等的**强**不变式由 pipeline 持久层 + 跨周测试守)。
    返回错误串或 None。无 ratchet → None(R4b 持久层仅 --account run 注入,可选)。检查:① shape 五键;② **本周有有效 effective_stop
    (=max(S3a stop, R4a 保本))时 ratcheted_stop 必非空有限 且 ≥ 它**(ratchet 含本周值;堵「ratcheted_stop=null 在本周有效 stop 时跳过不变式」缺口
    R-ASHORT-S3B-R4B-RATCHET-INVARIANT-GUARD-GAP);③ ratcheted_disposition severity ≥ 本周 disposition(只升档不降);④ cross_week_price_cross==
    clear_price_reached ⟹ ratcheted_stop 有限 且 现价≤ratcheted_stop;⑤ week_count≥1。"""
    rt = mc.get("ratchet")
    if rt is None:
        return None
    if not isinstance(rt, dict) or any(k not in rt for k in
            ("ratcheted_stop", "ratcheted_disposition", "week_count", "cross_week_price_cross", "bootstrap")):
        return "machine.ratchet 形态不完整(R4b 跨周 ratchet 五键)"
    rs = rt.get("ratcheted_stop")
    plan = (mc.get("entry_exit_size_star") or {}).get("plan") or {}
    eff = [v for v in (plan.get("stop"), (mc.get("move_to_breakeven") or {}).get("breakeven_price")) if _is_finite_num(v)]
    if eff:                                  # 本周有有效 effective_stop → ratcheted_stop 必非空有限(=max(eff,上周)≥eff;堵 null 跳过不变式缺口)
        if not _is_finite_num(rs):
            return f"ratcheted_stop={rs!r} 为空/非有限,但本周 effective_stop={max(eff)!r} 有效(ratchet 必随本周止损落地,不得 null)"
        if rs < max(eff) - 1e-9:
            return f"ratcheted_stop={rs!r} < 本周 effective_stop={max(eff)!r}(跨周 ratchet 只升不降,不得低于本周最紧止损)"
    rd, cur = rt.get("ratcheted_disposition"), (mc.get("holding_management_signal") or "hold")
    if _severity_max_disposition(rd, cur) != rd:
        return f"ratcheted_disposition={rd!r} 严重度 < 本周 disposition={cur!r}(跨周只升档不降)"
    close = mc.get("current_close")
    if rt.get("cross_week_price_cross") == "clear_price_reached":
        if not _is_finite_num(rs):           # 同类:clear 到价需有效跨周止损,null rs 时不得标 clear(否则不变式被跳过)
            return "cross_week_price_cross=clear_price_reached 但 ratcheted_stop 非有限(到价清仓需有效跨周止损)"
        if _is_finite_num(close) and close > rs:
            return "cross_week_price_cross=clear_price_reached 但 现价>ratcheted_stop(到价清仓口径不符)"
    if not (isinstance(rt.get("week_count"), int) and rt["week_count"] >= 1):
        return "ratchet week_count 须 ≥1 整数"
    return None


def _apply_holding_disposition(report):
    """S3b R1+R2:对 **持仓行(table.操作=='持有')** 就地设 table.持仓处置/table.禁止加仓 + machine.holding_management_signal/
    blocked_add_required(从 machine.operation_impact 全量重算)。键于 `操作=='持有'`(与 validate_m67_consistency 持有分支对齐,
    覆盖 build_m67 held 候选 + build_holding Tier-3);非持有行 → no-op(候选行不带持仓处置)。build_m67_report/build_holding_report
    末尾各调一次(独立 build 自洽);pipeline attach forward_event held 后再调一次纳入晚到信号;**每次重算 → 幂等**。
    R3 附 reduce/clear advisory 价位(减仓价/清仓价,复用 S3a 损/盈一);**R4a 末尾设 machine.price_cross(到价提示)+
    machine.move_to_breakeven(移保本),均 within-week advisory:不自动下单/不自动改 plan.stop(跨周持久收紧=R4b)**。返回 report(就地改)。"""
    tbl = (report.get("m67") or {}).get("table") or {}
    if tbl.get("操作") != "持有":
        return report
    mc = report.get("machine") or {}
    plan = (mc.get("entry_exit_size_star") or {}).get("plan") or {}
    sig, blocked = _merge_holding_disposition(
        mc.get("operation_impact") or [], plan=plan,
        hard_veto=bool((mc.get("layer") or {}).get("hard_veto")),
    )
    mc["holding_management_signal"] = sig
    mc["blocked_add_required"] = blocked
    tbl["持仓处置"] = _HOLDING_DISPOSITION_LABEL[sig]
    tbl["禁止加仓"] = blocked
    # S3b R3: 减仓价/清仓价/减仓比例 = **advisory 价位**,复用 S3a holding_levels(plan.stop=损 / plan.t1=盈一),仅 reduce/clear disposition;
    # **不自动执行**(到价提示/移保本=R4a within-week advisory;跨周持久收紧 ratchet=R4b)。S3a 未算出/破位(plan 缺或对应位 None)→ 价位 None(诚实不伪造)。pop-then-set 保持幂等
    # (signal 在 pipeline attach 后可能变,清旧价位防残留)。与 S3a 损/盈一/盈二(table 已显)是同值引用、两维共存,不重算。
    for _k in ("减仓价", "清仓价", "减仓比例"):
        tbl.pop(_k, None)
    for _k in ("reduce_price", "clear_price", "reduce_ratio"):
        mc.pop(_k, None)
    if sig == "clear_review":
        tbl["清仓价"] = mc["clear_price"] = plan.get("stop")          # 清仓价 = S3a 损(系统跟踪止损)
    elif sig == "reduce_review":
        tbl["减仓价"] = mc["reduce_price"] = plan.get("t1")           # 减仓价 = S3a 盈一(到盈一减仓锁利复核)
        tbl["减仓比例"] = mc["reduce_ratio"] = _REDUCE_RATIO_ADVISORY
    # S3b R4a: within-week advisory 到价提示 + 移保本(复用价格钟 current_close + 本次 sig 对应的 R3 减仓价/清仓价 + S3a plan.stop + 成本价)。
    # 全 advisory、**不改 disposition/操作/不自动卖/不改 plan.stop**;跨周持久 + 单向收紧 ratchet = R4b。在 R3 价位之后算;每次重算 → 幂等
    # (pipeline attach forward_event held 后 sig 变 → price_cross 随之重算)。current_close 由 builder 在 held 行注入(非持有行不带 → 非持有 guard 拒键)。
    pc, mtb = _holding_active_alerts(
        mc.get("current_close"), sig, mc.get("reduce_price"), mc.get("clear_price"),
        plan.get("stop"), ((mc.get("stateful_risk") or {}).get("position") or {}).get("avg_cost"))
    mc["price_cross"] = pc
    mc["move_to_breakeven"] = mtb
    # Keep the primary user instruction aligned with the structured table and
    # machine disposition. The renderer repeats the same table value.
    label = _HOLDING_DISPOSITION_LABEL[sig]
    conclusion = ((report.get("m67") or {}).get("精简结论区") or {})
    advice = str(conclusion.get("操作建议") or "")
    # Replace any prior disposition sentence before appending the current one.
    # The pipeline may add a late holding impact and call this function again;
    # changing the structured disposition must not leave stale advice behind.
    advice = re.sub(r"\s*持仓处置=[^。]*。", "", advice).strip()
    cause = ("现价已跌破系统止损" if plan.get("breached") else
             ("命中硬风控" if (mc.get("layer") or {}).get("hard_veto") else "持仓风险合并"))
    if sig == "clear_review":
        detail = f"{cause}；清仓价={mc.get('clear_price') if mc.get('clear_price') is not None else '未算出'}"
    elif sig == "reduce_review":
        detail = f"减仓价={mc.get('reduce_price') if mc.get('reduce_price') is not None else '未算出'}；减仓比例={mc.get('reduce_ratio')}"
    else:
        detail = cause
    conclusion["操作建议"] = advice + f" 持仓处置={label}（{detail}；advisory复核建议,不自动卖出）。"
    return report


def model_build_eligible(inp: dict, ind: dict, rule6_gate: dict, *, regime: str,
                         extra_halve: bool, halve_reason: str,
                         high_material: list[dict], web: dict,
                         web_status: str, web_downgrade: bool) -> bool:
    """Return P3's account-independent, comparison-only model-selection flag.

    The public strategy checks stay intact, while current holdings, account
    integrity/cooldowns and cash allocation are deliberately removed.  The
    official M6.7 action remains authoritative and can still be ``观察``.
    """
    model_inp = dict(inp)
    model_inp["stateful_risk"] = {"position_state": "flat"}
    # Synthetic capital removes only account-capacity gating. Liquidity and
    # impact limits still have to produce a valid minimum-size plan.
    model_inp["account"] = {
        "available_cash": 1_000_000_000_000_000.0,
        "bucket_capital": 1_000_000_000_000_000.0,
        "new_exposure_capacity": 1_000_000_000_000_000.0,
    }
    families = classify_risk_families(model_inp, ind, rule6_gate=rule6_gate)
    if high_material:
        families["semantic_official"].update(
            hit=True, action="hard_veto",
            reasons=[f"语义官方:{event['risk_type']}(high,人工确认,{ADVISORY_VETO_TAG})"
                     for event in high_material],
        )
    if web_downgrade:
        families["semantic_web_llm"].update(
            hit=True, action="downgrade",
            reasons=[f"语义web/LLM:{web_status}({web.get('risk_level')})"],
        )
    if any(families[family]["action"] == "hard_veto" for family in RISK_FAMILIES):
        return False
    if str(model_inp.get("analysis_role") or "") != "final":
        return False
    if rule6_gate.get("manual_review_check_ids"):
        return False
    etype, _ = entry_type(model_inp, ind)
    if etype == "观察":
        return False
    plan, _ = exit_and_size(model_inp, ind, regime, etype, extra_halve, halve_reason)
    return plan is not None


def _margin_source_is_unavailable(inp: dict, as_of: str) -> bool:
    """Return true unless the batch coverage and both margin checks are complete."""
    coverage = inp.get("margin_coverage")
    if not isinstance(coverage, dict):
        return True
    if (coverage.get("status") != "complete"
            or coverage.get("coverage_complete") is not True
            or not isinstance(coverage.get("reference_date"), str)
            or not isinstance(coverage.get("effective_ref_date"), str)):
        return True
    price_data_through = str(inp.get("price_data_through") or as_of)
    if (not coverage["reference_date"].isdigit() or len(coverage["reference_date"]) != 8
            or not coverage["effective_ref_date"].isdigit() or len(coverage["effective_ref_date"]) != 8
            or coverage["reference_date"] != price_data_through
            or price_data_through > str(as_of)
            or coverage["effective_ref_date"] > coverage["reference_date"]):
        return True
    try:
        universe_size = int(coverage.get("universe_size"))
        row_count = int(coverage.get("row_count"))
    except (TypeError, ValueError):
        return True
    if universe_size < 1000 or row_count < universe_size:
        return True
    margin_source_ids = {
        "rule6_margin_extreme_accumulation", "rule6_short_selling_surge",
    }
    checks = {
        check.get("id"): check for check in (inp.get("rule6_checks") or [])
        if isinstance(check, dict) and check.get("id") in margin_source_ids
    }
    return any(
        not isinstance(checks.get(check_id), dict)
        or (checks[check_id].get("metrics") or {}).get("status") != "complete"
        for check_id in margin_source_ids
    )


def build_m67_report(inp: dict, as_of: str, generated_at: str) -> dict:
    ind = compute_indicators(inp.get("price_series", []))
    rule6_gate = assess_rule6_checks(inp.get("rule6_checks"))
    rule6_d_tier_banner = render_rule6_d_tier_banner(rule6_gate)
    margin_source_ids = {
        "rule6_margin_extreme_accumulation", "rule6_short_selling_surge",
    }
    margin_source_unavailable = _margin_source_is_unavailable(inp, as_of)
    fam = classify_risk_families(inp, ind, rule6_gate=rule6_gate)
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
    analysis_role = str(inp.get("analysis_role") or "")
    final_new_entry_eligible = analysis_role == "final"
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
    # 经校验后:有 events ⟺ status==risk,severity 合法。official high 先待人工确认；只有人工确认重大者可进入 semantic_official
    # hard_veto(进下方 hard→否决,绝不救回);**缺 URL 的 high → 待核(不否决)**;medium/low → 仅"待核"
    # (不扣分/不清/不降星);clear/unknown/无输入 → 中性。(下方 high_full/high_incomplete 实现此分流)
    # 语义消费单一来源(_consume_semantic: build_m67 候选行 + build_holding 持仓行共用,防两份校验/派生漂移)。
    sc = _consume_semantic(inp, as_of)
    high_full, high_incomplete = sc["high_full"], sc["high_incomplete"]
    high_material = sc["high_material"]
    web, web_status, web_downgrade = sc["web"], sc["web_status"], sc["web_downgrade"]
    sem_pending = sc["sem_pending"]
    # 候选行决策路径(持仓走 build_holding_report 的 advisory 路径,不在此):人工确认重大的证据齐全 high → fam hard_veto(进否决,
    # reason 标非生产 advisory);web risk/headwind+sources → fam downgrade(绝不 hard_veto);tailwind/clear/unknown → 中性。
    # S2: semantic 的 hard_veto/downgrade 路径**只对候选行**(not has_position)。持仓(任何 Tier,无论走 build_m67
    # 还是 build_holding)的 semantic 永远 advisory:official high → 持有 + 清仓复核(下方 op_impacts existing_holding),
    # 绝不进候选 hard_veto→否决(R-ASHORT-GAP42-S2-HOLDING-SEMANTIC-TOPN-RENDER-DRIFT);web → 持仓警戒,不进候选 downgrade。
    if high_material and not has_position:
        fam["semantic_official"].update(
            hit=True, action="hard_veto",
            reasons=[f"语义官方:{e['risk_type']}(high,人工确认,{ADVISORY_VETO_TAG})" for e in high_material])
    if web_downgrade and not has_position:
        fam["semantic_web_llm"].update(
            hit=True, action="downgrade",
            reasons=[f"语义web/LLM:{web_status}({web.get('risk_level')})"])

    hard = [r for f in RISK_FAMILIES if fam[f]["action"] == "hard_veto" for r in fam[f]["reasons"]]
    downgrades = [r for f in RISK_FAMILIES if fam[f]["action"] == "downgrade" for r in fam[f]["reasons"]]
    observe = list(inp.get("observe_only") or [])     # 缺数据项(§3 层3 / §9 盘中类不在此,见 out_of_scope)
    if not has_position and not final_new_entry_eligible:
        observe.append("analysis_role=非 final，仅观察")
    llm_notes = list(inp.get("llm_enrichment") or []) # §10 Tier C:只解释,不改判决
    # A source-wide margin outage is one system condition, not N fake
    # ticker-specific failures.  It still blocks new entries below.
    rule6_manual_review_ids = [
        check_id for check_id in rule6_gate["manual_review_check_ids"]
        if not (margin_source_unavailable and check_id in margin_source_ids)
    ]
    if rule6_manual_review_ids:
        observe.append("rule6_manual_review:" + ",".join(rule6_manual_review_ids))

    if sem_pending:
        sem_reason = ("官方 high 待人工确认" if sc["regulatory"]["pending_high"]
                      else ("官方 high 缺 URL/PDF 证据(证据不全)" if high_incomplete
                            else "官方 medium/low 命中(例行件)"))
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
    model_eligible = model_build_eligible(
        inp, ind, rule6_gate, regime=regime, extra_halve=extra_halve,
        halve_reason=halve_reason, high_material=high_material, web=web,
        web_status=web_status, web_downgrade=web_downgrade,
    )

    # 决策
    if has_position:
        action, etype = "持有", "已有持仓"
        plan, hl_reject = holding_levels(inp, ind, regime)   # S3a:系统跟踪止损/止盈(被动显示)
        reject = ("已有持仓:按持仓管理输出,不按新开仓处理;禁止自动加仓"
                  + (f";命中硬风控:{'|'.join(hard)}" if hard else ""))
    elif hard:
        action, etype, plan, reject = "否决", "N/A", None, "|".join(hard)
    elif not final_new_entry_eligible:
        action, etype, plan, reject = "观察", "N/A", None, "非 final，仅观察"
    elif margin_source_unavailable:
        action, etype, plan = "观察", "N/A", None
        reject = "系统级：两融数据源本周不可用/覆盖不足，两条两融规则未执行"
    elif rule6_manual_review_ids:
        action, etype, plan = "观察", "N/A", None
        reject = "Rule6 未完成核查，需人工复核:" + ",".join(rule6_manual_review_ids)
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
    # Industry trend is authorized to alter only the displayed M6.7 star. Cash
    # allocation still uses the prior risk-derived order so an SW-L2 signal
    # label cannot silently change shares, cash, position cap, or action.
    allocation_input = dict(inp)
    allocation_input["industry_trend"] = "neutral"
    allocation_star = compute_star(allocation_input, fam, eligible) if action != "否决" else 0

    # 操作建议行(诚实护栏:建仓必带置信/试探/止损)
    if action == "建仓":
        iv_caveat = "" if iv_known else " **IV feed 缺失,未执行 IV 风控,仓位已保守再减半**。"
        regime_caveat = (" **EGS regime unknown,按震荡期保守降级并减半**。"
                         if regime_unknown_fallback else "")
        rng = (f"**挂单区间 {plan['entry_low']}–{plan['entry_high']}**(决策价 {plan['entry']}、盈亏比 {plan['rr']})"
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
    industry_trend_detail = dict(inp.get("industry_trend_detail") or {})
    industry_trend = str(inp.get("industry_trend") or "unknown")
    fundamental_trend = str(inp.get("industry_fundamental_trend") or "unknown")
    if industry_trend == "headwind":
        industry_trend_text = "industry_trend=headwind (deterministic SW L2 heat; formal -1 star)"
    elif industry_trend == "tailwind":
        industry_trend_text = "industry_trend=tailwind (display only; no positive star bonus)"
    elif industry_trend == "neutral":
        industry_trend_text = "industry_trend=neutral (display only)"
    else:
        industry_trend_text = "industry_trend=unknown (fail-closed; manual review, no star adjustment)"
    fundamental_text = f"industry_fundamental_trend={fundamental_trend} (LLM/advisory; no deterministic decision effect)"

    consumption = {
        "indicators": "→ 入场类型/止损/止盈/盈亏比/股数",
        "risk_families": "→ hard_veto(否决)/ downgrade(降星·减仓)/ market_regime(IV闸门)",
        "overlay.eligible": "→ comparison display only; no star/risk/action/cash effect",
        "overlay.crowding_hit": "→ comparison display only; no production risk-family effect",
        "iv.iv_percentile_252d": "→ Rule3 IV 闸门(>90否决 / >80减半)",
        "industry_trend": "→ deterministic SW L2 headwind only: -1 star; tailwind has no bonus; unknown requires manual review",
        "industry_fundamental_trend": "→ advisory display only; no deterministic decision effect",
        "analysis_role": "→ only analysis_role=final may produce a new-entry plan; non-final is observe-only, while existing holdings stay on holding management",
        "observe_only": "→ M6.5 观察项(不改动作);缺数据保守",
        "rule6_checks": "→ 任一失败硬否决；D-tier 仅人工核查；其余未决、缺失或漂移均需人工复核，空仓仅观察不得建仓",
        "llm_enrichment": "→ M6.7 风险摘要(不改 deterministic decision)",
        "account/liquidity": "→ 仓位上限/冲击成本/100股",
        "stateful_risk": "→ positions 决定 持有/新开仓 分流;Rule12 冷静期禁新开仓/恢复首笔限仓;Rule13 止损后再入冷静期或复核限仓",
        "semantic": "→ semantic_official 族(official high **且证据齐全(非空 url_or_pdf)并经人工确认重大**→非生产 advisory 否决;未确认或缺 URL 的 high→待人工确认;"
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
    breakout_agreement = breakout_source_agreement(inp, ind)
    if breakout_agreement in {"egs_only", "pipeline_only"}:
        table["触发条件"] += "；两套技术指标口径不一致，按保守口径处理"
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
                              else (("Rule6待人工核查:" + ",".join(rule6_manual_review_ids))
                                    if rule6_manual_review_ids else (sem_note if sem_note else "无"))),
            "Rule6人工核查": rule6_d_tier_banner,
            "板块资金事件": industry_trend_text + " | " + fundamental_text +
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
    # 候选行 → new_entry(official 证据齐全且人工确认重大 high → m67_advisory_veto 否决 / web downgrade → priority_down);
    # 持仓行(含在 TopN 走 build_m67 的 Tier-1·2 持仓)→ existing_holding(official → clear_review / web → hold_watch、
    # blocked_add、持有不否决)。semantic 永 advisory(production_effect_enabled=False、web_llm 绝不 hard_veto)。
    op_impacts.extend(_semantic_operation_impacts(
        high_material, web, web_downgrade, str(as_of), "existing_holding" if has_position else "new_entry"))
    # 4.2 财报质量①(复用,comparison-only):候选行红旗(EGS 既有 ESP-Q / 扣非净利同比<0)→ advisory priority_down impact
    # + 落 风控触发(财报质量对照)。零新取数、绝不 hard_veto、不改 EGS/选股/股数。仅候选(not has_position),持仓财报质量留后续刀。
    if not has_position:
        _fq_imps = _financial_quality_operation_impacts(inp.get("financial_quality"), str(as_of))
        if _fq_imps:
            op_impacts.extend(_fq_imps)
            _fcut = m67["精简结论区"]
            _fprev = _fcut.get("风控触发") or ""
            _fcut["风控触发"] = (f"{_fprev}｜{_fq_imps[0]['reason']}" if _fprev and _fprev != "无"
                                  else _fq_imps[0]["reason"])
    sizing_block = ([reject] if action == "观察" and reject and
                    any(marker in str(reject) for marker in
                        ("bucket", "new_exposure_capacity", "股数/金额不足", "组合现金分配")) else [])
    result = {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "ts_code": str(inp.get("ts_code", "")), "name": str(inp.get("name", "")),
        "m67": m67,
        "machine": {
            "indicators": ind, "risk_families": fam,
            "breakout_source_agreement": breakout_agreement,
            "rule6_gate": rule6_gate,
            "layer": {"hard_veto": hard, "downgrade": downgrades,
                      "observe_only": observe, "llm_enrichment": llm_notes,
                      "semantic_risk": sc["trace"],
                      "decision_reasons": {"hard_veto": list(hard),
                                           "downgrade": list(downgrades),
                                           "observe_only": list(observe),
                                           "manual_review": list(rule6_manual_review_ids),
                                           "margin_source_unavailable": margin_source_unavailable,
                                           "sizing_block": sizing_block}},
            "entry_exit_size_star": {"action": action, "type": etype if action != "否决" else "N/A",
                                     "star": star, "cash_allocation_star": allocation_star,
                                     "plan": plan, "reject_reason": reject},
            "model_build_eligible": model_eligible,
            "iv_gate": {"iv_percentile_252d": iv_pct, "halve": iv_halve, "status": iv_status,
                        "iv_value": (inp.get("iv") or {}).get("iv_value"),
                        "hv_value": (inp.get("iv") or {}).get("hv_value"),
                        "iv_hv_ratio": iv_hv_ratio, "iv_hv_regime": iv_hv_regime},
            "industry_trend": industry_trend_detail,
            "theme_comparison": dict((inp.get("overlay") or {}).get("theme_taxonomy") or {}),
            "stateful_risk": stateful,
            "consumption": consumption,
        },
        "boundary": {"production": False, "real_money": False,
                     "is_validated_alpha": False, "satisfies_ship_gate": False},
    }
    if op_impacts:                       # 仅命中时加 key,正常报告零改动(向后兼容)
        result["machine"]["operation_impact"] = op_impacts
    if table["操作"] == "持有":           # S3b R4a: 价格钟现价(到价/移保本判定基准),仅持仓行注入;held+hard_veto(操作=否决)不注入 → 非持有 guard 拒键
        result["machine"]["current_close"] = inp.get("close")
    _apply_holding_disposition(result)   # S3b R1+R2: held 报告设 持仓处置/禁止加仓(非 held no-op)+ R4a 到价/移保本;pipeline attach forward_event held 后再调一次
    return result


def _is_valid_date(s) -> bool:
    # 严格 canonical(P1 修复):strptime("%Y%m%d") 单用会接受 '202606 5'/'2026065'(解析成 20260605),
    # 非真 canonical。要求**恰好 8 个 ASCII 数字** + 合法历法日;否则 disclosure_date / as_of 的非规范值会
    # 既过 canonical 声称、又因 PIT 字符串比较(空格<数字)被当成 <= as_of。镜像 ledger 的 _is_canonical_date。
    from datetime import datetime
    t = str(s)
    if len(t) != 8 or not (t.isascii() and t.isdigit()):
        return False
    try:
        datetime.strptime(t, "%Y%m%d")
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
    # Tier-3 placeholder 风险族用 canonical 键(与主引擎 RISK_FAMILIES 对齐,Codex S3#2-1):全 not-evaluated
    # (未核查、非 hit);此前用非 canonical liquidity_impact/event_hard_veto 会让按 canonical 键聚合的下游漏读。
    fam = {k: {"hit": False, "action": "none", "reasons": []} for k in
           ("market_regime", "overheat_crowding", "liquidity_execution",
            "negative_event", "semantic_official", "stateful_risk")}
    # 4.2 S2: 持仓 semantic 数据接入(让持仓也抓 cninfo/web 语义)。复用 _consume_semantic(候选/持仓单一来源)+
    # _semantic_operation_impacts(scope=existing_holding → holding_row_impact: clear_review/hold_watch + blocked_add
    # + pending S3b)。持仓 action 恒「持有」(不否决/不自动卖出,减仓价/清仓价见 R3,到价提示/移保本=R4a(within-week advisory)、跨周持久收紧 ratchet=R4b);official 证据齐全且人工确认重大 high → 清仓复核 advisory
    # (标非生产)、web → 持仓警戒;web/LLM 永久 advisory-only、绝不 hard_veto。**无 semantic 输入(provider None)→ 全 unknown、
    # 零 op_impact、文本保持「未核查」(S1 向后兼容)**。涉真实持仓 → 私密路由(weekly_private,带 --account 自动私密)。
    has_semantic_input = inp.get("semantic") is not None or inp.get("semantic_web_llm") is not None
    sc = _consume_semantic(inp, as_of)
    # Finding 2 fix: 「已核查」文本判据用**真核查**(official_status 或 web_status 任一非 unknown,= render `_has_semantic` 同一判据),
    # 不用 has_semantic_input —— 有输入但 trace 全 unknown(取数失败/无结果)时,has_semantic_input 会误写「语义已核查」,
    # 与 render `_has_semantic`(精确判未核查)同一份 Markdown 自相矛盾(违反 no-false-clear)。
    sem_checked = sc["sem_status"] != "unknown" or sc["web_status"] != "unknown"
    sem_op_impacts = _semantic_operation_impacts(sc["high_material"], sc["web"], sc["web_downgrade"], as_of, "existing_holding")
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
            "Rule6人工核查": "仅人工核查：本周 EGS 粗筛未覆盖，Rule6 机器检查未运行。",
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
    _hr = {
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
    _hr["machine"]["current_close"] = inp.get("close")   # S3b R4a: 价格钟现价(到价/移保本判定基准;Tier-3 持仓恒 held)
    _apply_holding_disposition(_hr)       # S3b R1+R2: Tier-3 持仓(操作=持有)设 持仓处置/禁止加仓(从 sem_op_impacts 重算)+ R4a 到价/移保本
    return _hr


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
      且 veto_class!=production_hard_veto;semantic_official_high_confirmed 必须保持 m67_advisory_veto;semantic_web_llm 必须保持 none
      且 new_entry_effect!='hard_veto'(web/LLM 永久 advisory-only,绝不 hard_veto)。
    ⑧.5【S3b 全局持仓效应闭合,source-class 无关】任何 impact 带持仓效应(holding_effect∉{none,缺省} 或 blocked_add_required) ⟹ (a) 必是
      `_is_held_signal`(holding_row_impact/existing_holding/private,= 持仓处置合并唯一合法输入,单一来源)且 (b) 仅持仓(position_state==held)报告;
      补 ⑧⑪⑬⑭ 只覆盖具体 source-class 的缺口(generic source_field 夹带 wrong-shape 持仓字段 / 非持仓报告夹带持仓效应,均拒)。
    报告级(存在该类 impact 时):
    ⑨【第3轮】任一 m67_advisory_veto ⟹ 否决审查触发/操作建议 含 ADVISORY_VETO_TAG(advisory 否决须显式标非生产,与生产硬否决物理区分);
    ⑩【第3轮】任一 blocked_add_required==True ⟹ 操作建议/风控触发 含「禁止加仓」(独立旗标必用户可见,不被其它处置吞掉)。
    ⑪【4.2 forward_events】source_field 以 'forward_event_' 开头(覆盖 limit_unlock/earnings_disclosure/未来类) ⟹ 永久 analysis-only:
      field_class=='structured'、production_effect_enabled is False、veto_class=='none'、new_entry_effect!='hard_veto'、
      holding_effect∈{none,hold_watch}(source-class 级绑定,防篡改 veto_class/effect 伪装生产硬否决;呼应 semantic-isolation ⑧)。
      **+ 持仓 shape/privacy 闭合(S3b 持仓处置输入)**:held ⟹ holding_row_impact/existing_holding/private;非 held ⟹ candidate_row_impact/
      public_tracked 且 holding_effect=none/无 blocked(防手构把 public/candidate forward_event 提升成私密持仓处置;镜像 ⑬⑭)。
    ⑫【4.2 forward_events ADVICE-LANDING】任一 forward_event_ impact ⟹ 操作建议含未来事件提示「未来已知事件」
      (候选/持仓不得仍像干净建仓——未来事件须落用户主看的操作建议,不只风控触发;字面同步 pipeline _FORWARD_EVENT_MARKER)。
    ⑬⑭【4.2 Round5 龙虎榜/大宗交易 trade-event】source_field ∈ {dragon_list_appearance, block_trade_appearance} ⟹ 永久 analysis-only +
      comparison-only(只记成交事实,绝不改 EGS/TopN/选股/股数/操作/否决):field_class=='structured'、production_effect_enabled is False、
      veto_class=='none'、new_entry_effect∈{informational,none}、holding_effect=='none'、blocked_add_required is False(比 forward_event
      更严:无任何动作)。**+ 持仓 privacy/shape 闭合**:held(position_state==held)⟹ holding_row_impact/existing_holding/new_entry_effect=none/
      private_account;非 held ⟹ candidate_row_impact/public_tracked(涉真实持仓须私密;防 builder 漂移/手构混淆)。报告级任一该 impact
      ⟹ 板块资金事件含对应 marker(龙虎榜对照 / 大宗交易对照,同步 pipeline _DRAGON_LIST_MARKER / _BLOCK_TRADE_MARKER)。
    ⑮【4.2 财报质量① 复用】source_field=='financial_quality' ⟹ 永久 comparison-only advisory(field_class=='structured'、
      production_effect_enabled is False、veto_class=='none'、new_entry_effect∈{priority_down,informational,none} 绝不 hard_veto、
      holding_effect=='none' 候选 only);报告级任一该 impact ⟹ 风控触发含 _FINANCIAL_QUALITY_MARKER「财报质量对照」(no-dangling)。
    ⑯【4.2 财报质量趋势 ②forecast/③income/④balancesheet】source_field 以 'financial_trend_' 开头 ⟹ 永久 comparison-only advisory +
      candidate-only(field_class=='structured'、production_effect_enabled is False、veto_class=='none'、new_entry_effect∈{priority_down,
      informational,none} 绝不 hard_veto、holding_effect=='none'、candidate_row_impact/new_entry/public_tracked、blocked_add=false、held 报告拒);
      报告级任一该 impact ⟹ 风控触发含「财报趋势对照」(no-dangling;字面同步 pipeline _FIN_STATEMENT_MARKER)。
    ⑰【4.2 财报质量趋势⑤ 行业基本面】source_field=='industry_fundamentals' ⟹ 拒(⑤ 是 summary_only 周报全局摘要,绝不产逐票 operation_impact;
      逐票财报红旗已由③④ financial_trend_ 落地)。
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
    sector_text = str(cut.get("板块资金事件", ""))
    position_state = ((report.get("machine") or {}).get("stateful_risk") or {}).get("position_state")
    _TRADE_EVENT_MARKERS = {"dragon_list_appearance": "龙虎榜对照", "block_trade_appearance": "大宗交易对照"}   # 4.2 Round5 龙虎榜/大宗(单一来源,同步 pipeline _DRAGON_LIST_MARKER/_BLOCK_TRADE_MARKER)
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
        # 【S3b 全局持仓效应闭合,source-class 无关】(R-ASHORT-S3B-HOLDING-DISPOSITION-SCOPE-GUARD-GAP):任何 operation_impact 只要带持仓效应
        #   (holding_effect ∉ {none,缺省} 或 blocked_add_required)就 (a) 必须是真持仓侧信号 `_is_held_signal`(holding_row_impact/existing_holding/
        #   private,= `_merge_holding_disposition` 合并的唯一合法输入,单一来源判据),且 (b) 只能出现在持仓(position_state==held)报告。
        #   补 ⑧⑪⑬⑭ 只覆盖具体 source-class 的缺口——generic source_field(不匹配任何 source-class guard)夹带 wrong-shape holding_effect/blocked、
        #   或非持仓报告夹带持仓效应,均直接拒(否则会污染持仓处置合并)。
        _he = imp.get("holding_effect")
        if (_he not in (None, "none")) or imp.get("blocked_add_required"):
            if not _is_held_signal(imp):
                raise ValueError(f"operation_impact {sf} 带持仓效应(holding_effect={_he!r}/blocked_add)但非持仓侧 shape"
                                 "(须 holding_row_impact/existing_holding/private;持仓处置合并仅认持仓侧信号)")
            if position_state != "held":
                raise ValueError(f"operation_impact {sf} 带持仓效应但报告非持仓(position_state={position_state!r}!=held)——持仓效应仅持仓报告")
        # ⑧ semantic 来源(field_class==semantic_advisory 或 source_field 以 semantic_ 开头)= 永久 advisory。
        #   source-class 级绑定(不只按 veto_class 分支,防"改 veto_class/丢分类绕过";堵三类伪装:official→production_hard_veto+enabled /
        #   official hard_veto 丢 advisory 分类 / web_llm production-enabled):一律非生产、绝不 production_hard_veto;
        #   semantic_official_high_confirmed 必保 m67_advisory_veto;semantic_web_llm 必保 veto_class=none 且非 hard_veto。单一 block = 未来加 semantic 不变式只在此处。
        if imp.get("field_class") == "semantic_advisory" or str(imp.get("source_field", "")).startswith("semantic_"):
            if imp.get("production_effect_enabled") is not False:
                raise ValueError(f"operation_impact {sf} semantic 来源必须 production_effect_enabled=false(语义永久 advisory,不进生产)")
            if imp.get("veto_class") == "production_hard_veto":
                raise ValueError(f"operation_impact {sf} semantic 来源不得标 production_hard_veto(语义不进生产硬否决)")
            if imp.get("source_field") == "semantic_official_high_confirmed" and imp.get("veto_class") != "m67_advisory_veto":
                raise ValueError(f"operation_impact {sf} semantic_official_high_confirmed 必须 m67_advisory_veto")
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
            # 持仓 shape/privacy/effect 闭合(R-ASHORT-S3B-HOLDING-DISPOSITION-SCOPE-GUARD-GAP;镜像 ⑬⑭ trade-event):forward_event held
            # 信号(holding_effect=hold_watch/blocked)是 S3b 持仓处置合并的输入,必须焊死持仓侧 shape——held(position_state==held)⟹
            # holding_row_impact/existing_holding/private;非 held(候选)⟹ candidate_row_impact/public_tracked 且 holding_effect=none/无 blocked
            # (候选 forward_event 绝不带持仓效应)。防手构把 public/candidate forward_event 提升成私密持仓处置输入(_merge_holding_disposition 同步 fail-closed)。
            if position_state == "held":
                if not (imp.get("visibility_shape") == "holding_row_impact" and imp.get("impact_scope") == "existing_holding"
                        and imp.get("privacy_class") in ("private_account", "secret_or_raw_provider")):
                    raise ValueError(f"operation_impact {sf} forward_event 在持仓(held)行必须 holding_row_impact/existing_holding/private(涉真实持仓须私密 shape)")
            else:
                if not (imp.get("visibility_shape") == "candidate_row_impact" and imp.get("privacy_class") == "public_tracked"):
                    raise ValueError(f"operation_impact {sf} forward_event 在非持仓(候选)行必须 candidate_row_impact/public_tracked")
                if imp.get("holding_effect") != "none" or imp.get("blocked_add_required"):
                    raise ValueError(f"operation_impact {sf} forward_event 在非持仓(候选)行不得带持仓效应(holding_effect/blocked_add)")
        # ⑬⑭ trade-event 来源(dragon_list_appearance / block_trade_appearance)= 永久 analysis-only + comparison-only(4.2 Round5 龙虎榜/大宗:
        #   只记成交事实,绝不改 EGS/TopN/选股/股数/操作/否决):field_class=structured、production=false、veto=none、
        #   new_entry_effect∈{informational,none}、holding_effect=none、blocked_add=false(比 forward_event 更严,无任何动作)。
        #   **+ 持仓 privacy/shape 闭合(R-...-TRADE-EVENT-COVERAGE-PRIVACY-GUARD-GAP)**:held(position_state==held)⟹ holding_row_impact/
        #   existing_holding/new_entry_effect=none/private_account(涉真实持仓须私密);非 held ⟹ candidate_row_impact/public_tracked。
        #   不靠 registry 测试——运行时写时强制(防 builder 漂移或手构报告把持仓事件标成 public/candidate)。
        if str(imp.get("source_field", "")) in _TRADE_EVENT_MARKERS:
            _te = "dragon_list" if imp.get("source_field") == "dragon_list_appearance" else "block_trade"
            if imp.get("field_class") != "structured":
                raise ValueError(f"operation_impact {sf} {_te} 必须 field_class=structured")
            if imp.get("production_effect_enabled") is not False:
                raise ValueError(f"operation_impact {sf} {_te} 必须 production_effect_enabled=false(永久 analysis-only)")
            if imp.get("veto_class") != "none":
                raise ValueError(f"operation_impact {sf} {_te} 必须 veto_class=none(comparison-only,绝不否决)")
            if imp.get("new_entry_effect") not in ("informational", "none"):
                raise ValueError(f"operation_impact {sf} {_te} new_entry_effect={imp.get('new_entry_effect')!r} 越界(comparison-only 仅 informational/none)")
            if imp.get("holding_effect") != "none":
                raise ValueError(f"operation_impact {sf} {_te} holding_effect={imp.get('holding_effect')!r} 越界(comparison-only 仅 none)")
            if imp.get("blocked_add_required"):
                raise ValueError(f"operation_impact {sf} {_te} 不得 blocked_add_required=true(comparison-only 不禁止加仓)")
            if position_state == "held":
                if not (imp.get("visibility_shape") == "holding_row_impact" and imp.get("impact_scope") == "existing_holding"
                        and imp.get("new_entry_effect") == "none"
                        and imp.get("privacy_class") in ("private_account", "secret_or_raw_provider")):
                    raise ValueError(f"operation_impact {sf} {_te} 在持仓(held)行必须 holding_row_impact/existing_holding/new_entry_effect=none/private_account(涉真实持仓须私密 shape)")
            elif not (imp.get("visibility_shape") == "candidate_row_impact" and imp.get("privacy_class") == "public_tracked"):
                raise ValueError(f"operation_impact {sf} {_te} 在非持仓(候选)行必须 candidate_row_impact/public_tracked")
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
    # ⑬⑭ TRADE-EVENT-LANDING(4.2 Round5):任一 dragon_list_appearance / block_trade_appearance impact ⟹ 板块资金事件含对应 marker
    #   (comparison-only 成交事实须落用户主看的 板块资金事件;字面同步 pipeline _DRAGON_LIST_MARKER / _BLOCK_TRADE_MARKER)。
    for _te_src, _te_marker in _TRADE_EVENT_MARKERS.items():
        if any(str(imp.get("source_field", "")) == _te_src for imp in impacts) and _te_marker not in sector_text:
            raise ValueError(f"存在 {_te_src} impact 但 板块资金事件未含「{_te_marker}」(comparison-only 成交事实须落用户可见的板块资金事件)")
    # ⑮ FINANCIAL-QUALITY(4.2 财报质量①复用):financial_quality impact ⟹ 永久 comparison-only advisory(structured,
    #   绝不 hard_veto / 非生产 / 候选 only)+ 落 风控触发 marker(no-dangling;字面同步 _FINANCIAL_QUALITY_MARKER)。
    for imp in impacts:
        if str(imp.get("source_field", "")) != "financial_quality":
            continue
        if imp.get("field_class") != "structured":
            raise ValueError("financial_quality impact field_class 须为 structured")
        if imp.get("production_effect_enabled") is not False:
            raise ValueError("financial_quality impact 须 production_effect_enabled=false(comparison-only,不改 EGS/选股)")
        if imp.get("veto_class") != "none" or imp.get("new_entry_effect") == "hard_veto":
            raise ValueError("financial_quality impact 绝不 hard_veto(第一类结构化但仅 advisory:priority_down/informational)")
        if imp.get("new_entry_effect") not in ("priority_down", "informational", "none"):
            raise ValueError(f"financial_quality impact new_entry_effect={imp.get('new_entry_effect')!r} 越界(仅 priority_down/informational/none)")
        if imp.get("holding_effect") != "none":
            raise ValueError("financial_quality impact 第一刀=候选 only,holding_effect 须 none(持仓财报质量留后续刀)")
        # 候选 only 形态闭合(R-...-FINANCIAL-QUALITY-CANDIDATE-SCOPE-GUARD-GAP):必 candidate_row_impact/new_entry/public_tracked,
        # 且持仓(held)报告绝不得带 financial_quality(持仓财报质量是后续刀,须单独审查;防 builder 漂移/手构混淆绕过候选 only 声明)。
        if imp.get("visibility_shape") != "candidate_row_impact" or imp.get("impact_scope") != "new_entry":
            raise ValueError(f"financial_quality impact 须 candidate_row_impact/new_entry(第一刀候选 only),"
                             f"实为 {imp.get('visibility_shape')!r}/{imp.get('impact_scope')!r}")
        if imp.get("privacy_class") != "public_tracked":
            raise ValueError(f"financial_quality impact 须 public_tracked(候选行无账户隐私),实为 {imp.get('privacy_class')!r}")
        if position_state == "held":
            raise ValueError("持仓(position_state=held)报告不得带 financial_quality impact(第一刀候选 only,持仓财报质量留后续刀)")
        if _FINANCIAL_QUALITY_MARKER not in risk_text:
            raise ValueError(f"financial_quality impact 但 风控触发未含「{_FINANCIAL_QUALITY_MARKER}」(no-dangling:财报质量须落用户可见风控触发)")
    # ⑯ FINANCIAL-TRENDS(4.2 财报质量趋势 ②forecast/③income/④balancesheet 新增报表取数):source_field 以 `financial_trend_` 开头 ⟹ 永久
    #   comparison-only advisory + **candidate-only**(财报报表红旗仅 advisory 降优先级,绝不 hard_veto/否决/改 EGS·选股·股数;持仓财报趋势留后续刀):
    #   field_class=structured、production_effect_enabled=False、veto_class=none、new_entry_effect∈{priority_down,informational,none} 绝不 hard_veto、
    #   holding_effect=none、candidate_row_impact/new_entry/public_tracked、blocked_add=false、held 报告拒。source-class 级绑定(不枚举具体类,
    #   防"篡改 veto_class/shape/加新类漏覆盖"绕过候选 only)。报告级任一该 impact ⟹ 风控触发含「财报趋势对照」(no-dangling;字面同步 pipeline _FIN_STATEMENT_MARKER)。
    _FIN_TREND_MARKER = "财报趋势对照"   # 字面同步 runners/a_short_weekly_pipeline.py::_FIN_STATEMENT_MARKER(emission 在 pipeline,guard 在此;镜像 forward_event ⑫)
    for imp in impacts:
        if not str(imp.get("source_field", "")).startswith("financial_trend_"):
            continue
        if imp.get("field_class") != "structured":
            raise ValueError("financial_trend impact field_class 须为 structured")
        if imp.get("production_effect_enabled") is not False:
            raise ValueError("financial_trend impact 须 production_effect_enabled=false(comparison-only,不改 EGS/选股)")
        if imp.get("veto_class") != "none" or imp.get("new_entry_effect") == "hard_veto":
            raise ValueError("financial_trend impact 绝不 hard_veto(财报报表红旗仅 advisory:priority_down/informational)")
        if imp.get("new_entry_effect") not in ("priority_down", "informational", "none"):
            raise ValueError(f"financial_trend impact new_entry_effect={imp.get('new_entry_effect')!r} 越界(仅 priority_down/informational/none)")
        if imp.get("holding_effect") != "none":
            raise ValueError("financial_trend impact 候选 only,holding_effect 须 none(持仓财报趋势留后续刀)")
        if imp.get("visibility_shape") != "candidate_row_impact" or imp.get("impact_scope") != "new_entry":
            raise ValueError(f"financial_trend impact 须 candidate_row_impact/new_entry(candidate-only),"
                             f"实为 {imp.get('visibility_shape')!r}/{imp.get('impact_scope')!r}")
        if imp.get("privacy_class") != "public_tracked":
            raise ValueError(f"financial_trend impact 须 public_tracked(候选行无账户隐私),实为 {imp.get('privacy_class')!r}")
        if imp.get("blocked_add_required"):
            raise ValueError("financial_trend impact 不得 blocked_add_required=true(comparison-only 不禁止加仓)")
        if position_state == "held":
            raise ValueError("持仓(position_state=held)报告不得带 financial_trend impact(candidate-only,持仓财报趋势留后续刀)")
    if any(str(imp.get("source_field", "")).startswith("financial_trend_") for imp in impacts) and _FIN_TREND_MARKER not in risk_text:
        raise ValueError(f"financial_trend impact 但 风控触发未含「{_FIN_TREND_MARKER}」(no-dangling:财报趋势须落用户可见风控触发)")
    # ⑰ INDUSTRY-FUNDAMENTALS-SUMMARY-ONLY(4.2 财报质量趋势⑤):⑤ 行业基本面是 summary_only 周报全局摘要,**绝不产逐票 operation_impact**
    #   (逐票财报红旗已由③④ financial_trend_ 落地)。任何 source_field=='industry_fundamentals' 的 row-level impact = 把 summary-only 层
    #   伪装成逐票影响 → 拒(防 builder 漂移/手构把 ⑤ 提升为 row impact;呼应 weekly validator 的 ⑤ summary-only 契约)。
    for imp in impacts:
        if str(imp.get("source_field", "")) == "industry_fundamentals":
            raise ValueError("operation_impact source_field=industry_fundamentals 非法(⑤ 行业基本面 summary_only,绝不产逐票 operation_impact)")


def validate_m67_consistency(report: dict) -> None:
    """§4 不变量 + R-ASHORT-M67-...-WRITE-CONTRACT:消费完整性 / 热度不覆盖硬风控 / 诚实护栏 /
    每族一次 / as_of 历法 / table↔machine 一致 / 建仓正数+plan匹配 / 非建仓 null / IV缺失显式。"""
    mc = report["machine"]
    m67 = report["m67"]
    tbl = m67["table"]
    action = mc["entry_exit_size_star"]["action"]
    if "model_build_eligible" in mc and not isinstance(mc["model_build_eligible"], bool):
        raise ValueError("machine.model_build_eligible 必须为布尔值")
    rule6_gate = mc.get("rule6_gate")
    if action != "持有" and not isinstance(rule6_gate, dict):
        raise ValueError("候选报告缺 Rule6 completion gate")
    if isinstance(rule6_gate, dict):
        disposition = rule6_gate.get("disposition")
        manual_review_ids = rule6_gate.get("manual_review_check_ids")
        hard_veto_ids = rule6_gate.get("hard_veto_check_ids")
        if disposition not in ("clear", "manual_review", "hard_veto"):
            raise ValueError(f"Rule6 completion gate disposition 非法:{disposition!r}")
        if not isinstance(manual_review_ids, list) or not isinstance(hard_veto_ids, list):
            raise ValueError("Rule6 completion gate ids 必须为列表")
        if not isinstance(rule6_gate.get("not_applicable_checks"), list):
            raise ValueError("Rule6 completion gate D-tier checks 必须为列表")
        if disposition == "manual_review" and action == "建仓":
            raise ValueError("Rule6 未完成核查不得建仓")
        expected_banner = render_rule6_d_tier_banner(rule6_gate)
        if m67["精简结论区"].get("Rule6人工核查") != expected_banner:
            raise ValueError("Rule6 D-tier 人工核查横幅与 completion gate 不一致")
    # Knife 7 applies only to EGS-covered candidate reports (including a
    # candidate that is already held). Tier-3 holding reports have no EGS
    # breakout source and therefore do not manufacture this four-state
    # comparison.
    breakout_agreement = mc.get("breakout_source_agreement")
    allowed_breakout_agreements = {"agree_true", "agree_false", "egs_only", "pipeline_only"}
    # Historical published reports predate the marker. Missing is therefore
    # unavailable (and cannot render a clean conclusion), while any marker
    # that is present is closed-world and checked against the final text.
    if breakout_agreement is not None:
        if breakout_agreement not in allowed_breakout_agreements:
            raise ValueError("breakout_source_agreement 非法")
        disagreement_notice = "两套技术指标口径不一致，按保守口径处理"
        has_disagreement_notice = disagreement_notice in str(tbl.get("触发条件") or "")
        if (breakout_agreement in {"egs_only", "pipeline_only"}) != has_disagreement_notice:
            raise ValueError("breakout_source_agreement 与触发条件分歧提示不一致")
    # held-state 不变式(P1 修复 R-ASHORT-M67-HELD-STATE-ACTION-BIND):action=持有 必须真持仓(stateful_risk.position_state==held
    # + position 非空且 ts_code 与 report 一致),防 flat 候选冒充持仓行过 validator(候选/持仓串线);建仓/观察 反向必非 held;
    # held+hard-veto 仍必须走持仓管理：硬风险进入 clear_review/blocked_add，但不抹掉 S3a plan。
    _sr = mc.get("stateful_risk") or {}
    _ps, _pos = _sr.get("position_state"), (_sr.get("position") or None)
    if action == "持有":
        if _ps != "held" or not _pos:
            raise ValueError(f"持有 action 但 machine.stateful_risk 非持仓(position_state={_ps!r}/position 空)——候选/持仓串线")
        if str((_pos or {}).get("ts_code") or "") != str(report.get("ts_code") or ""):
            raise ValueError("持有 action 但 position.ts_code 与 report ts_code 不一致(持仓串线)")
    elif action in ("建仓", "观察") and _ps == "held":
        raise ValueError(f"{action} action 但 position_state=held(候选/持仓串线;持仓应走 持有/否决)")
    plan = mc["entry_exit_size_star"].get("plan")
    # as_of 历法
    if not _is_valid_date(report["as_of"]):
        raise ValueError("as_of 非合法日历日期")
    # 每族最多一次硬处理
    for f, v in mc["risk_families"].items():
        if v["hit"] and v["action"] not in ("hard_veto", "downgrade"):
            raise ValueError(f"风险族 {f} 命中但 action 非法")
    # 热度不覆盖硬风控。已有持仓的硬风险只能升级持仓处置为 clear_review，不能抹掉持仓计划。
    if mc["layer"]["hard_veto"] and not (
            action == "否决" or (action == "持有" and _ps == "held")):
        raise ValueError("存在 hard_veto 却未否决或进入持仓清仓复核(热度/分数不得救回硬风控)")
    # table 操作必须 == machine action
    if tbl["操作"] != action:
        raise ValueError("M6.7 table 操作 与 machine action 不一致")
    # S3b R1+R2: 持仓处置/禁止加仓(table)+ holding_management_signal/blocked_add_required(machine)是**持仓行(操作=持有)专属**结构化字段;
    # 非持有(建仓/观察/否决)行 table+machine 都不得带(防漂移/手构把持仓处置或 machine 信号泄漏到候选行;R-ASHORT-S3B-HOLDING-DISPOSITION-SCOPE-GUARD-GAP)。
    if action != "持有":
        if "持仓处置" in tbl or "禁止加仓" in tbl:
            raise ValueError("非持有行不得带 持仓处置/禁止加仓(S3b:持仓处置仅持仓行)")
        if "holding_management_signal" in mc or "blocked_add_required" in mc:   # 键存在即泄漏(含显式 null)
            raise ValueError("非持有行 machine 不得带 holding_management_signal/blocked_add_required(S3b:持仓处置仅持仓行)")
        # S3b R3: 减仓价/清仓价/减仓比例(table)+ reduce_price/clear_price/reduce_ratio(machine)同为持仓行专属,非持有行不得带
        # (**按键存在判定**,含显式 null:R-ASHORT-S3B-R3-EXPLICIT-NULL-PRICE-GUARD-GAP——present-but-None 也算泄漏)
        if any(_k in tbl for _k in ("减仓价", "清仓价", "减仓比例")):
            raise ValueError("非持有行不得带 减仓价/清仓价/减仓比例(S3b R3:价位仅持仓行)")
        if any(_k in mc for _k in ("reduce_price", "clear_price", "reduce_ratio")):
            raise ValueError("非持有行 machine 不得带 reduce_price/clear_price/reduce_ratio(S3b R3:价位仅持仓行)")
        # S3b R4a: current_close/price_cross/move_to_breakeven(到价/移保本 advisory)同为持仓行专属,非持有行不得带(按键存在,含显式 null)
        if any(_k in mc for _k in ("current_close", "price_cross", "move_to_breakeven", "ratchet")):
            raise ValueError("非持有行 machine 不得带 current_close/price_cross/move_to_breakeven/ratchet(S3b R4a/R4b:到价/移保本/跨周 ratchet 仅持仓行)")
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
        # 唯一可执行决策价必须是最不利价 entry_high；table/plan/advice/RR 不得回到参考 close。
        if abs(plan.get("entry", -1) - plan.get("entry_high", -2)) > 1e-9:
            raise ValueError("建仓 plan.entry 必须等于唯一决策价 entry_high")
        if not (plan.get("entry_low") <= plan.get("entry") <= plan.get("entry_high")):
            raise ValueError("建仓 plan.entry 必须落在 entry_low–entry_high 区间内")
        _rr_risk = plan.get("entry") - plan.get("stop")
        if _rr_risk <= 0:
            raise ValueError("建仓 plan.entry/stop 无有效风险距离")
        _rr_from_plan = (plan.get("t1") - plan.get("entry")) / _rr_risk
        if abs(plan.get("rr", -1) - round(_rr_from_plan, 3)) > 1e-9:
            raise ValueError("建仓 plan.rr 与唯一决策价重算结果不一致")
        if abs(plan.get("rr_at_entry_high", -1) - plan.get("rr", -2)) > 1e-9:
            raise ValueError("建仓 rr_at_entry_high 与展示 rr 不一致")
        if plan.get("rr") < plan.get("rr_floor"):
            raise ValueError("建仓展示 rr 低于当前 RR 门槛")
        if f"盈亏比 {plan['rr']}" not in adv:
            raise ValueError("建仓 advice 缺精确展示盈亏比短语(不得低于/偏离 RR 门槛口径)")
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
        # S3b R1+R2: 持仓处置/禁止加仓 结构化列一致性 —— **独立重算** _merge_holding_disposition(不信任 builder),比对
        # machine.holding_management_signal/blocked_add_required + table.持仓处置/禁止加仓(映射)。持仓行(操作=持有)必带这 4 字段。
        # 与 S3a holding_levels(被动止损/止盈价位:损/盈一/盈二,上方已校)是两个维度——持仓处置=advisory 处置档;R3 价位见下(引用 S3a 同值)。
        _plan = (mc.get("entry_exit_size_star") or {}).get("plan") or {}
        _sig, _blk = _merge_holding_disposition(
            mc.get("operation_impact") or [], plan=_plan,
            hard_veto=bool(mc.get("layer", {}).get("hard_veto")),
        )
        if mc.get("holding_management_signal") != _sig:
            raise ValueError(f"持有 machine.holding_management_signal={mc.get('holding_management_signal')!r} != 合并重算 {_sig!r}")
        if bool(mc.get("blocked_add_required")) != _blk:
            raise ValueError(f"持有 machine.blocked_add_required != 合并重算 {_blk}")
        if tbl.get("持仓处置") != _HOLDING_DISPOSITION_LABEL[_sig]:
            raise ValueError(f"持有 table.持仓处置={tbl.get('持仓处置')!r} != machine.holding_management_signal 映射 {_HOLDING_DISPOSITION_LABEL[_sig]!r}")
        if "禁止加仓" not in tbl or bool(tbl["禁止加仓"]) != _blk:
            raise ValueError("持有 table.禁止加仓 缺失或 != machine.blocked_add_required")
        _advice_dispositions = re.findall(r"持仓处置=([^（。]+)（", adv)
        if len(_advice_dispositions) != 1 or _advice_dispositions[0] != tbl["持仓处置"]:
            raise ValueError("持有 advice 的持仓处置必须恰好一条且与 table.持仓处置一致")
        # S3b R3: 减仓价/清仓价/减仓比例 = advisory 价位,仅 reduce/clear disposition 带。**显式 null no-dangling**(区分键缺失 vs 显式 null;
        # R-ASHORT-S3B-R3-EXPLICIT-NULL-PRICE-GUARD-GAP):按 disposition 焊死 table+machine **恰好这组键存在**(S3a 未算出也须显式 null 键、不得省略、
        # 不得多带);值独立比对 S3a plan(清仓价==损 plan.stop、减仓价==盈一 plan.t1,含显式 None,不信任 builder/不重算 S3a)+ machine↔table 一致。不产自动执行(到价提示/移保本=R4a advisory;跨周 ratchet=R4b)。
        if _sig == "clear_review":
            _exp_tbl, _exp_mc = {"清仓价"}, {"clear_price"}
        elif _sig == "reduce_review":
            _exp_tbl, _exp_mc = {"减仓价", "减仓比例"}, {"reduce_price", "reduce_ratio"}
        else:                                                    # hold/hold_watch/manual_review → 无 R3 价位
            _exp_tbl, _exp_mc = set(), set()
        _got_tbl = {_k for _k in ("减仓价", "清仓价", "减仓比例") if _k in tbl}
        _got_mc = {_k for _k in ("reduce_price", "clear_price", "reduce_ratio") if _k in mc}
        if _got_tbl != _exp_tbl:
            raise ValueError(f"持有 {_sig} R3 table 价位键集 {_got_tbl} != 期望 {_exp_tbl}(显式 null 也须键存在、不得缺/多带)")
        if _got_mc != _exp_mc:
            raise ValueError(f"持有 {_sig} R3 machine 价位键集 {_got_mc} != 期望 {_exp_mc}(显式 null 也须键存在、不得缺/多带)")
        if _sig == "clear_review" and tbl.get("清仓价") != _plan.get("stop"):
            raise ValueError(f"持有 clear_review table.清仓价={tbl.get('清仓价')!r} != S3a 损 plan.stop={_plan.get('stop')!r}")
        if _sig == "reduce_review":
            if tbl.get("减仓价") != _plan.get("t1"):
                raise ValueError(f"持有 reduce_review table.减仓价={tbl.get('减仓价')!r} != S3a 盈一 plan.t1={_plan.get('t1')!r}")
            if tbl.get("减仓比例") != _REDUCE_RATIO_ADVISORY:
                raise ValueError(f"持有 reduce_review table.减仓比例={tbl.get('减仓比例')!r} != advisory {_REDUCE_RATIO_ADVISORY!r}")
        if (mc.get("clear_price") != tbl.get("清仓价") or mc.get("reduce_price") != tbl.get("减仓价")
                or mc.get("reduce_ratio") != tbl.get("减仓比例")):
            raise ValueError("持有 machine reduce_price/clear_price/reduce_ratio 与 table 减仓价/清仓价/减仓比例 不一致")
        # S3b R4a: within-week advisory 到价提示 price_cross + 移保本 move_to_breakeven —— 持仓行必带这三字段;**独立重算**(不信任 builder)。
        # current_close = 价格钟现价,须 == 现价与成本 显示价(provenance bind:防 builder 篡改判定基准与用户可见价脱节);price_cross/move_to_breakeven
        # 经 _holding_active_alerts(与 _apply 同一来源)从 current_close + R3 减仓价/清仓价 + S3a plan.stop + 成本价 重算比对。全 advisory:不改 disposition/操作/plan.stop(=R4b)。
        if "current_close" not in mc:
            raise ValueError("持有 machine 缺 current_close(S3b R4a 到价/移保本判定基准)")
        _close = mc.get("current_close")
        if not str(m67["精简结论区"].get("现价与成本", "")).startswith(f"{_close} "):
            raise ValueError(f"持有 machine.current_close={_close!r} 与 现价与成本 显示价不符(到价/移保本判定基准须 == 价格钟现价)")
        _avg_cost = ((mc.get("stateful_risk") or {}).get("position") or {}).get("avg_cost")
        _exp_pc, _exp_mtb = _holding_active_alerts(_close, _sig, mc.get("reduce_price"), mc.get("clear_price"),
                                                   _plan.get("stop"), _avg_cost)
        if mc.get("price_cross") != _exp_pc:
            raise ValueError(f"持有 machine.price_cross={mc.get('price_cross')!r} != 重算 {_exp_pc!r}(到价提示 advisory)")
        if mc.get("move_to_breakeven") != _exp_mtb:
            raise ValueError(f"持有 machine.move_to_breakeven={mc.get('move_to_breakeven')!r} != 重算 {_exp_mtb!r}(移保本 advisory)")
        # S3b R4b: 跨周持久收紧 ratchet within-report 弱不变式(单一来源 `_ratchet_report_error`,与 pipeline _apply_holding_ratchet 写后共用)。
        # **可选**(持久层在 pipeline,仅 --account 真持仓 run 注入;直接 build/观察 run 无 ratchet→None no-op)。跨周强不变式由 pipeline 持久层 + 测守。
        _rt_err = _ratchet_report_error(mc)
        if _rt_err:
            raise ValueError(f"持有 {_rt_err}")
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
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
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
