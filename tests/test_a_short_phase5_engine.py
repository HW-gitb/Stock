"""Tests for the A-short Phase 5 deterministic engine (Slice B v1, batch ① part 2).

Covers indicators, entry-type, exit/size (RR floor + tentative-position), risk-family routing,
the four-layer decision, IV gate, the M6.7-only output, and the §4 invariants (consumption
completeness, heat-cannot-rescue-hard-veto, honesty guard) + governance parity + schema.
Pure engine on normalized synthetic inputs; no live data.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_phase5_engine import (  # noqa: E402
    compute_indicators, entry_type, exit_and_size, classify_risk_families,
    build_m67_report, build_holding_report, validate_m67_consistency, write_m67_report, GOVERNANCE,
    tick_ref, tick_up, tick_down, holding_levels, effective_support, effective_resistance, SR_SPIKE_ATR,
    BREAKOUT_RR_BONUS,
    iv_hv_tag, iv_hv_vol_note, IV_HV_RATIO_HI, IV_HV_RATIO_LO, IV_HV_REGIMES,
)
from engine.a_short_rule6_contract import RULE6_CHECKS, RULE6_D_TIER_REASONS  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "a_short_m67_report.schema.json"
GOV_PATH = ROOT / "presets" / "a_short_phase5_engine_governance_20260610.json"
AS_OF = "20260609"


def _series():
    # 30d; day12 carries support 2.87 (corroborated by 2.88 → strong) + resistance 3.10; day13 ALSO highs 3.10
    # so resistance is corroborated (#6 effective_resistance → strong, not a single-day spike). Both day12/13 are
    # inside the 20d lookback but outside the 14d ATR window, so ATR stays ~0.04. closes 2.90 so MAs ~2.90.
    s = []
    for i in range(30):
        trade_date = (date(2026, 5, 11) + timedelta(days=i)).strftime("%Y%m%d")
        if i == 12:
            s.append({"trade_date": trade_date, "high": 3.10, "low": 2.87, "close": 2.90})
        elif i == 13:
            s.append({"trade_date": trade_date, "high": 3.10, "low": 2.88, "close": 2.90})   # #6:次日背书近20日高 → resistance strong(否则单日 3.10 被判插针)
        else:
            s.append({"trade_date": trade_date, "high": 2.92, "low": 2.88, "close": 2.90})
    return s


def _rule6_checks(status="pass"):
    return [
        {"id": check_id, "group": group,
         "status": "not_applicable" if check_id in RULE6_D_TIER_REASONS else status,
         "notes": RULE6_D_TIER_REASONS.get(check_id)}
        for check_id, group in RULE6_CHECKS
    ]


def _good_input(**over):
    inp = {
        "ts_code": "600000.SH", "name": "测试", "close": 2.90, "price_series": _series(),
        "analysis_role": "final",
        "esp_score": 60, "l4_score": 70,
        "overlay": {"eligible": True, "crowding_hit": False},
        "industry_trend": "neutral",
        "derived": {"overheat": False, "chasing_high": False, "breakout": False, "vol_confirm": False,
                    "crash_veto": False, "limit_locked": False, "suspended": False},
        "event": {"holder_reduction_active": False, "st_or_delisting": False,
                  "regulatory_legacy_vetoed": False},
        "rule6_checks": _rule6_checks(),
        "liquidity": {"avg_amount_5d": 2e8, "avg_amount_20d": 2e8},
        "iv": {"iv_percentile_252d": 55.0},
        "market_regime": "震荡期",
        "account": {"available_cash": 500000.0},
        "portfolio": {}, "observe_only": [], "llm_enrichment": [],
    }
    inp.update(over)
    return inp


def _held_state():
    return {
        "position_state": "held",
        "position": {"ts_code": "600000.SH", "shares": 1000, "avg_cost": 2.70,
                     "entry_date": "20260601", "stop_loss": 2.55},
        "rule12": {"status": "inactive"},
        "rule13": {"status": "none"},
        "size_multiplier": 1.0,
        "reasons": [],
    }


def _flat_rule12_active():
    return {
        "position_state": "flat",
        "position": None,
        "rule12": {"status": "active_cooldown", "new_entry_blocked": True,
                   "cooldown_until": "20260610"},
        "rule13": {"status": "none"},
        "size_multiplier": 1.0,
        "reasons": ["Rule12 active_cooldown:block_new_entries"],
    }


def _flat_rule13_active():
    return {
        "position_state": "flat",
        "position": None,
        "rule12": {"status": "inactive"},
        "rule13": {"status": "active_cooldown", "reentry_blocked": True,
                   "cooldown_until": "20260610"},
        "size_multiplier": 1.0,
        "reasons": ["Rule13 active_cooldown:block_reentry"],
    }


class IndicatorTests(unittest.TestCase):
    def test_indicators(self):
        ind = compute_indicators(_series())
        self.assertAlmostEqual(ind["ma5"], 2.90)
        self.assertAlmostEqual(ind["support"], 2.87)        # 极值 2.87 被次低 2.88 背书(差 0.01 < 1×ATR 0.04)→ strong, 不变
        self.assertEqual(ind["support_quality"], "strong")
        self.assertAlmostEqual(ind["recent_low_20"], 2.87)  # 原始近20日最低保留
        self.assertAlmostEqual(ind["resistance"], 3.10)     # #6 有效压力:3.10 被次高 3.10(day13)背书 → strong, 不变
        self.assertEqual(ind["resistance_quality"], "strong")
        self.assertAlmostEqual(ind["recent_high_20"], 3.10)  # 原始近20日最高保留
        self.assertAlmostEqual(ind["atr14"], 0.04, places=3)


class Rule6CompletionGateTests(unittest.TestCase):
    def test_model_build_eligibility_ignores_account_cash_but_keeps_public_plan_checks(self):
        cashless = build_m67_report(_good_input(account={"available_cash": 0.0}), AS_OF, "t")
        funded = build_m67_report(_good_input(account={"available_cash": 500000.0}), AS_OF, "t")
        self.assertEqual(cashless["machine"]["model_build_eligible"],
                         funded["machine"]["model_build_eligible"])
        self.assertTrue(cashless["machine"]["model_build_eligible"])
        self.assertEqual(cashless["m67"]["table"]["操作"], "观察")

    def test_d_tier_banner_is_persistent_and_clear_machine_checks_can_build(self):
        report = build_m67_report(_good_input(rule6_checks=_rule6_checks()), AS_OF, "t")
        self.assertEqual(report["m67"]["table"]["操作"], "建仓")
        banner = report["m67"]["精简结论区"]["Rule6人工核查"]
        self.assertIn("仅人工核查", banner)
        for check_id in RULE6_D_TIER_REASONS:
            self.assertIn(check_id, banner)
        validate_m67_consistency(report)

    def test_pending_rule6_check_observes_and_never_builds(self):
        checks = _rule6_checks()
        checks[2]["status"] = "pending_data"
        report = build_m67_report(_good_input(rule6_checks=checks), AS_OF, "t")
        self.assertEqual(report["m67"]["table"]["操作"], "观察")
        self.assertEqual(report["machine"]["rule6_gate"]["disposition"], "manual_review")
        self.assertIn("rule6_holder_below_5pct",
                      report["machine"]["rule6_gate"]["manual_review_check_ids"])
        self.assertIn("Rule6待人工核查", report["m67"]["精简结论区"]["否决审查触发"])
        validate_m67_consistency(report)

    def test_failed_rule6_check_is_hard_veto(self):
        checks = _rule6_checks()
        checks[2]["status"] = "fail"
        report = build_m67_report(_good_input(rule6_checks=checks), AS_OF, "t")
        self.assertEqual(report["m67"]["table"]["操作"], "否决")
        self.assertEqual(report["machine"]["rule6_gate"]["disposition"], "hard_veto")
        self.assertIn("rule6_holder_below_5pct",
                      report["machine"]["rule6_gate"]["hard_veto_check_ids"])
        validate_m67_consistency(report)

    def test_pending_rule6_check_keeps_existing_holding_management(self):
        checks = _rule6_checks()
        checks[2]["status"] = "pending_data"
        report = build_m67_report(
            _good_input(rule6_checks=checks, stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(report["m67"]["table"]["操作"], "持有")
        self.assertEqual(report["machine"]["rule6_gate"]["disposition"], "manual_review")
        validate_m67_consistency(report)

    def test_market_level_rule6_iv_failure_keeps_existing_holding_management(self):
        checks = _rule6_checks()
        iv_check = next(item for item in checks if item["id"] == "rule6_50etf_iv")
        iv_check.update(status="fail", severity="hard_veto", notes="Rule3 50ETF IV percentile")
        report = build_m67_report(
            _good_input(rule6_checks=checks, stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(report["m67"]["table"]["操作"], "持有")
        self.assertEqual(report["machine"]["rule6_gate"]["hard_veto_check_ids"], ["rule6_50etf_iv"])
        self.assertFalse(any("rule6_50etf_iv" in reason
                             for reason in report["machine"]["layer"]["decision_reasons"]["hard_veto"]))
        self.assertTrue(any("rule6_50etf_iv" in reason
                            for reason in report["machine"]["layer"]["decision_reasons"]["downgrade"]))
        validate_m67_consistency(report)

    def test_security_specific_rule6_failure_still_vetoes_existing_holding(self):
        checks = _rule6_checks()
        failure = next(item for item in checks if item["id"] == "rule6_holder_below_5pct")
        failure.update(status="fail", severity="hard_veto", notes="holder stake below threshold")
        report = build_m67_report(
            _good_input(rule6_checks=checks, stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(report["m67"]["table"]["操作"], "否决")
        self.assertTrue(any("rule6_holder_below_5pct" in reason
                            for reason in report["machine"]["layer"]["decision_reasons"]["hard_veto"]))
        validate_m67_consistency(report)

    def test_validator_rejects_tampered_d_tier_banner(self):
        report = build_m67_report(_good_input(rule6_checks=_rule6_checks()), AS_OF, "t")
        report["m67"]["精简结论区"]["Rule6人工核查"] = "无"
        with self.assertRaises(ValueError):
            validate_m67_consistency(report)


class EffectiveSupportTests(unittest.TestCase):
    """#5 有效支撑:抗单日极值结构位 + 质量标记(strong/weak/fallback_extreme);只动建仓侧 support,不动 resistance。"""
    def _s(self, lows):                                      # 构造 series(close 固定高于所有 low,确保不破结构)
        return [{"high": x + 0.5, "low": x, "close": max(lows) + 0.5} for x in lows]

    def test_strong_when_extreme_corroborated(self):
        sup, q, raw = effective_support(self._s([10.0, 10.02, 10.5, 10.6, 10.7]), atr=0.5)
        self.assertEqual((sup, q, raw), (10.0, "strong", 10.0))   # 次低 10.02 仅高 0.02 < 1×0.5 → 极值可信

    def test_weak_drops_single_day_spike(self):
        sup, q, raw = effective_support(self._s([9.0, 10.0, 10.1, 10.2, 10.3]), atr=0.5)
        self.assertEqual((sup, q, raw), (10.0, "weak", 9.0))      # 9.0 比次低 10.0 低 1.0 > 1×0.5 → 插针,取次低

    def test_fallback_extreme_when_no_atr(self):
        sup, q, raw = effective_support(self._s([9.0, 10.0, 10.1]), atr=None)
        self.assertEqual((sup, q, raw), (9.0, "fallback_extreme", 9.0))   # 无 ATR 无法评估 → 退原始极值

    def test_spike_threshold_boundary(self):
        # 差恰 = 1×ATR(不严格 >)→ 视为背书 strong(用 raw_low),非插针
        sup, q, _ = effective_support(self._s([9.5, 10.0, 10.1, 10.2]), atr=0.5)
        self.assertEqual((sup, q), (9.5, "strong"))

    def test_exit_and_size_carries_support_and_quality(self):
        # 建仓 plan 携带结构支撑 + 质量;stop 以有效 support 为基准(本切片改建仓 stop)。
        ind = {"support": 10.0, "support_quality": "weak", "resistance": 12.0, "atr14": 0.5}
        plan, rej = exit_and_size(_good_input(close=10.30), ind, "震荡期", etype="低吸")
        self.assertIsNone(rej)
        self.assertEqual(plan["support"], 10.0)
        self.assertEqual(plan["support_quality"], "weak")

    def test_build_report_surfaces_and_validates_support_quality(self):
        r = build_m67_report(_good_input(), AS_OF, "t")            # _series → support 2.87 strong
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        self.assertEqual(plan["support_quality"], "strong")
        self.assertIn("质量 strong", r["m67"]["精简结论区"]["操作建议"])   # 文案落点
        validate_m67_consistency(r)                                # 正向必过

    def test_validator_rejects_bad_or_dangling_support_quality(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["machine"]["entry_exit_size_star"]["plan"]["support_quality"] = "bogus"   # 非枚举
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)
        r2 = build_m67_report(_good_input(), AS_OF, "t")           # 删质量 token → no-dangling
        r2["m67"]["精简结论区"]["操作建议"] = r2["m67"]["精简结论区"]["操作建议"].replace("质量 strong", "质量")
        with self.assertRaises(ValueError):
            validate_m67_consistency(r2)

    def test_validator_rejects_dangling_support_value(self):
        # R-ASHORT-M67-PRICE5-SUPPORT-VALUE-NODANGLE:删掉支撑价位、仅留「质量 Q」→ 必拒(只查质量会放过)。
        r = build_m67_report(_good_input(), AS_OF, "t")
        sup = r["machine"]["entry_exit_size_star"]["plan"]["support"]
        r["m67"]["精简结论区"]["操作建议"] = r["m67"]["精简结论区"]["操作建议"].replace(f"结构支撑 {sup}、", "")
        self.assertIn("质量 strong", r["m67"]["精简结论区"]["操作建议"])   # 质量 token 仍在(隔离支撑价位缺失)
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)


class EffectiveResistanceTests(unittest.TestCase):
    """#6 有效压力(resistance 有效化,对称 #5):抗单日极值结构位 + 质量(strong/weak/fallback_extreme)。
    双侧消费:建仓 t1/RR 门**分子** + 持仓跟踪止损基准——上插针顶高会让 RR 虚高(假性过门)或持仓止损过紧。"""
    def _s(self, highs):                                     # close 固定低于所有 high,确保结构正常
        return [{"high": x, "low": x - 0.5, "close": min(highs) - 0.5} for x in highs]

    def test_strong_when_extreme_corroborated(self):
        res, q, raw = effective_resistance(self._s([10.7, 10.68, 10.2, 10.1, 10.0]), atr=0.5)
        self.assertEqual((res, q, raw), (10.7, "strong", 10.7))   # 次高 10.68 仅低 0.02 < 1×0.5 → 极值可信

    def test_weak_drops_single_day_spike(self):
        res, q, raw = effective_resistance(self._s([11.0, 10.0, 9.9, 9.8, 9.7]), atr=0.5)
        self.assertEqual((res, q, raw), (10.0, "weak", 11.0))     # 11.0 比次高 10.0 高 1.0 > 1×0.5 → 插针,取次高

    def test_fallback_extreme_when_no_atr(self):
        res, q, raw = effective_resistance(self._s([11.0, 10.0, 9.9]), atr=None)
        self.assertEqual((res, q, raw), (11.0, "fallback_extreme", 11.0))   # 无 ATR 无法评估 → 退原始极值

    def test_spike_threshold_boundary(self):
        # 差恰 = 1×ATR(不严格 >)→ 视为背书 strong(用 raw_high),非插针
        res, q, _ = effective_resistance(self._s([10.5, 10.0, 9.9, 9.8]), atr=0.5)
        self.assertEqual((res, q), (10.5, "strong"))

    def test_compute_indicators_despikes_resistance(self):
        s = [{"high": 10.0, "low": 9.5, "close": 9.8} for _ in range(20)]
        s[5] = {"high": 13.0, "low": 9.5, "close": 9.8}      # 单日上插针(在 ATR 窗外)
        ind = compute_indicators(s)
        self.assertEqual(ind["resistance_quality"], "weak")
        self.assertAlmostEqual(ind["recent_high_20"], 13.0)  # 原始近20日最高保留
        self.assertAlmostEqual(ind["resistance"], 10.0)      # 有效压力取次高(去插针)

    def test_build_surfaces_and_validates_resistance_quality(self):
        r = build_m67_report(_good_input(), AS_OF, "t")       # _series → resistance 3.10 strong(day12+13 背书)
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        self.assertEqual(plan["resistance_quality"], "strong")
        self.assertAlmostEqual(plan["resistance"], 3.10)
        self.assertIn(f"结构阻力 {plan['resistance']}、质量 strong", r["m67"]["精简结论区"]["操作建议"])
        validate_m67_consistency(r)                           # 正向必过

    def test_validator_rejects_bad_or_dangling_resistance_quality(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["machine"]["entry_exit_size_star"]["plan"]["resistance_quality"] = "bogus"   # 非枚举
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)
        r2 = build_m67_report(_good_input(), AS_OF, "t")
        res2 = r2["machine"]["entry_exit_size_star"]["plan"]["resistance"]
        r2["m67"]["精简结论区"]["操作建议"] = r2["m67"]["精简结论区"]["操作建议"].replace(f"结构阻力 {res2}、", "")   # 删压力价位
        with self.assertRaises(ValueError):
            validate_m67_consistency(r2)

    def test_despiked_resistance_rejects_spike_inflated_build(self):
        # 核心价值:上插针顶高的 resistance 会把 t1/RR 顶过门;去插针(次高)后 RR 真实不足 → 正确拒。
        close = 10.0
        base = {"support": 9.5, "support_quality": "strong", "atr14": 0.4}
        despiked = {**base, "resistance": 10.1, "resistance_quality": "weak"}   # 去插针后的次高
        plan, rej = exit_and_size(_good_input(close=close), despiked, "震荡期", etype="低吸")
        self.assertIsNone(plan)                              # t1=10.1 → RR=(10.1-10)/1.0=0.1 < 1.5 → 拒
        self.assertIn("盈亏比", rej)
        raw_spike = {**base, "resistance": 12.0, "resistance_quality": "strong"}  # 未去插针(bug)→ RR 虚高过门
        plan2, _ = exit_and_size(_good_input(close=close), raw_spike, "震荡期", etype="低吸")
        self.assertIsNotNone(plan2)                          # 对照:插针未去时会假性建仓(正是本切片要堵的)

    def test_holding_stop_consumes_resistance(self):
        ind = {"resistance": 10.0, "resistance_quality": "weak", "atr14": 0.4}   # 去插针后的次高
        plan, rej = holding_levels(_good_input(close=9.8), ind, "震荡期")
        self.assertIsNone(rej)
        self.assertAlmostEqual(plan["recent_high"], 10.0)
        self.assertAlmostEqual(plan["stop"], 9.5)            # tick_up(10.0 − 1.25×0.4) = 9.5(基准用去插针的压力)

    # ── #6 t1 目标基准真实性(R-ASHORT-M67-PRICE-RESISTANCE-T1-BASIS-DANGLING)─────────────
    def test_t1_basis_structural_when_resistance_above_close(self):
        ind = {"support": 9.5, "support_quality": "strong", "atr14": 0.4,
               "resistance": 12.0, "resistance_quality": "strong"}
        plan, rej = exit_and_size(_good_input(close=10.0), ind, "震荡期", etype="低吸")
        self.assertIsNone(rej)
        self.assertEqual(plan["t1_basis"], "structural_resistance")
        self.assertAlmostEqual(plan["t1"], 12.0)             # t1 = tick_down(resistance)

    def test_t1_basis_fallback_when_resistance_not_above_close(self):
        # resistance <= close(== 与 <)→ t1 走 RR 门兜底,t1_basis=rr_floor_fallback,t1 ≠ resistance
        for res in (10.0, 9.5):
            ind = {"support": 9.5, "support_quality": "strong", "atr14": 0.4,
                   "resistance": res, "resistance_quality": "strong"}
            plan, rej = exit_and_size(_good_input(close=10.0), ind, "震荡期", etype="低吸")
            self.assertIsNone(rej, f"res={res}")
            self.assertEqual(plan["t1_basis"], "rr_floor_fallback", f"res={res}")
            self.assertNotAlmostEqual(plan["t1"], res)       # t1 不是结构阻力

    def _fallback_series(self):
        # Codex probe:紧致区间 high==close==近20日最高 → 有效压力 == 现价 → t1 走 RR 兜底,但仍是合法低吸建仓
        return [{"high": 10.0, "low": 9.86, "close": 10.0} for _ in range(30)]

    def test_build_fallback_advice_basis_truthful_and_validates(self):
        r = build_m67_report(_good_input(close=10.0, price_series=self._fallback_series()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        self.assertEqual(plan["t1_basis"], "rr_floor_fallback")
        adv = r["m67"]["精简结论区"]["操作建议"]
        self.assertIn("由 RR 门槛兜底推算", adv)
        self.assertNotIn("目标基准:结构阻力", adv)         # 不得虚标结构阻力为目标依据(Codex dangling)
        validate_m67_consistency(r)                           # 正向必过

    def test_validator_rejects_fallback_with_structural_basis_phrase(self):
        # Codex 原始 dangling:fallback 报告塞入结构阻力目标基准短语 → 必拒
        r = build_m67_report(_good_input(close=10.0, price_series=self._fallback_series()), AS_OF, "t")
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        r["m67"]["精简结论区"]["操作建议"] += (f"盈一 {plan['t1']} 目标基准:结构阻力 {plan['resistance']}、"
                                                f"质量 {plan['resistance_quality']}")
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_forged_t1_basis_on_structural(self):
        r = build_m67_report(_good_input(), AS_OF, "t")       # _series → structural
        r["machine"]["entry_exit_size_star"]["plan"]["t1_basis"] = "rr_floor_fallback"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_rejects_structural_relabeled_as_fallback(self):
        # Codex branch-guard probe:structural plan(t1==tick_down(resistance))整体改标 fallback + 换上 branch-一致的
        # fallback 文案 → validator 必须靠 plan 数学(t1==tick_down(res) 不得 fallback)抓出,不能只信声明分支+文案。
        r = build_m67_report(_good_input(), AS_OF, "t")       # structural, t1==tick_down(resistance)==3.1
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        struct = (f"**盈一 {plan['t1']} 目标基准:结构阻力 {plan['resistance']}、质量 {plan['resistance_quality']}**"
                  f"(上插针顶高时取次高,RR 不虚高)。")
        fb = (f"**盈一 {plan['t1']} 由 RR 门槛兜底推算**(结构阻力 {plan['resistance']}/质量 "
              f"{plan['resistance_quality']} 未用作目标:不高于现价)。")
        adv = r["m67"]["精简结论区"]["操作建议"]
        self.assertIn(struct, adv)                            # sanity:结构句确在
        r["m67"]["精简结论区"]["操作建议"] = adv.replace(struct, fb)   # branch-一致伪造
        r["machine"]["entry_exit_size_star"]["plan"]["t1_basis"] = "rr_floor_fallback"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)


class BreakoutRRFloorTests(unittest.TestCase):
    """#6 V14.2 迁移(proposal §6 首项):突破型 RR floor = RR_FLOOR[regime] + BREAKOUT_RR_BONUS;
    追高 entry_high 在现价上方、风险更大 → 要求更高赔率;只建仓侧,持仓(无 etype)不受影响。"""
    def _ind(self, res):
        return {"support": 9.5, "resistance": res, "atr14": 0.4, "support_quality": "strong"}

    def test_breakout_floor_stricter_than_lowxi(self):
        # close=10、risk=1 → rr=(res−10)。res=11.7 → rr≈1.7:低吸(门 1.5)过、突破(门 2.0)拒。
        ind = self._ind(11.7)
        lo, rej_lo = exit_and_size(_good_input(close=10.0), ind, "震荡期", etype="低吸")
        self.assertIsNone(rej_lo)
        self.assertEqual(lo["rr_floor"], 1.5)
        bo, rej_bo = exit_and_size(_good_input(close=10.0), ind, "震荡期", etype="突破")
        self.assertIsNone(bo)                          # 突破被更高门拒
        self.assertIn("盈亏比", rej_bo)

    def test_breakout_passes_with_enough_rr_and_floor_reflects_bonus(self):
        bo, rej = exit_and_size(_good_input(close=10.0), self._ind(13.0), "震荡期", etype="突破")
        self.assertIsNone(rej)
        self.assertEqual(bo["rr_floor"], 1.5 + BREAKOUT_RR_BONUS)   # plan 记录抬升后的门槛
        self.assertEqual(bo["entry_type"], "突破")

    def test_lowxi_advice_floor_landing_no_breakout_wording(self):
        # #6-i 诚实显示:低吸 build advice 含「门槛 1.5」、**不含**「突破型更严」(低吸没被额外加严)。
        lo = build_m67_report(_good_input(), AS_OF, "t")
        self.assertEqual(lo["m67"]["table"]["操作"], "建仓")
        adv = lo["m67"]["精简结论区"]["操作建议"]
        self.assertIn("门槛 1.5", adv)
        self.assertNotIn("突破型更严", adv)
        validate_m67_consistency(lo)

    def test_breakout_advice_shows_stricter_floor(self):
        inp = _good_input()
        inp["derived"] = {**inp["derived"], "breakout": True, "vol_confirm": True}
        bo = build_m67_report(inp, AS_OF, "t")
        self.assertEqual(bo["m67"]["table"]["操作"], "建仓")
        adv = bo["m67"]["精简结论区"]["操作建议"]
        self.assertIn("门槛 2.0", adv)             # 1.5 + 0.5
        self.assertIn("突破型更严", adv)
        validate_m67_consistency(bo)

    def test_validator_rejects_dangling_rr_floor(self):
        # R-ASHORT-M67-PRICE6-RR-FLOOR-NODANGLE:删掉 advice 的「门槛 {rr_floor}」→ 必拒。
        r = build_m67_report(_good_input(), AS_OF, "t")
        floor = r["machine"]["entry_exit_size_star"]["plan"]["rr_floor"]
        r["m67"]["精简结论区"]["操作建议"] = r["m67"]["精简结论区"]["操作建议"].replace(f"门槛 {floor}", "门槛")
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)


class EntryExitTests(unittest.TestCase):
    def setUp(self):
        self.ind = compute_indicators(_series())

    def test_entry_type_lowxi(self):
        etype, _ = entry_type(_good_input(), self.ind)
        self.assertEqual(etype, "低吸")

    def test_entry_type_observe_below_all_ma(self):
        etype, _ = entry_type(_good_input(close=2.80), self.ind)
        self.assertEqual(etype, "观察")

    def test_breakout_not_gated_by_vol_confirm(self):
        # #6-ii(R-ASHORT-EGS-BREAKOUT-SPEC-M67-VOLCONFIRM-DRIFT):is_breakout=v14.2 spec(EGS 算 MA10+放量)即触发
        # 突破;旧非-spec vol_confirm 不再叠加门。is_breakout=True + vol_confirm=False → 仍突破(去掉旧额外门)。
        d = _good_input()["derived"]; d["breakout"] = True; d["vol_confirm"] = False
        et, _ = entry_type(_good_input(derived=d), self.ind)
        self.assertEqual(et, "突破")
        d2 = _good_input()["derived"]; d2["breakout"] = False; d2["vol_confirm"] = True
        et2, _ = entry_type(_good_input(derived=d2), self.ind)
        self.assertNotEqual(et2, "突破")     # 无 is_breakout → 非突破(vol_confirm 不能单独触发)

    def test_exit_size_buildable(self):
        plan, rej = exit_and_size(_good_input(), self.ind, "震荡期", extra_halve=False)
        self.assertIsNone(rej)
        self.assertGreaterEqual(plan["rr"], 1.5)
        self.assertGreaterEqual(plan["shares"], 100)

    def test_exit_size_extra_halve_smaller(self):
        full, _ = exit_and_size(_good_input(), self.ind, "震荡期", extra_halve=False)
        half, _ = exit_and_size(_good_input(), self.ind, "震荡期", extra_halve=True, halve_reason="x")
        self.assertLess(half["shares"], full["shares"])

    def test_exit_size_stateful_multiplier_smaller(self):
        full, _ = exit_and_size(_good_input(), self.ind, "震荡期", extra_halve=False)
        limited, _ = exit_and_size(_good_input(), self.ind, "震荡期", extra_halve=False,
                                   size_multiplier=0.5, size_multiplier_reason="Rule12 recovery")
        self.assertLess(limited["shares"], full["shares"])
        self.assertTrue(any("Rule12 recovery" in x for x in limited["sizing_notes"]))

    def test_exit_size_shrink_regime_blocked(self):
        plan, rej = exit_and_size(_good_input(), self.ind, "收缩期", extra_halve=False)
        self.assertIsNone(plan)


class TickPriceTests(unittest.TestCase):
    """Slice 0: side-aware A股 0.01 tick + exit_and_size post-tick 重校验(价格提案 §2/§2.1)。"""
    def test_tick_ref_half_up_not_bankers(self):
        self.assertEqual(tick_ref(2.675), 2.68)          # half-up,非 banker's(round(2.675,2)=2.67)
        self.assertEqual(tick_ref(2.674), 2.67)
        self.assertEqual(tick_ref(10.0), 10.0)

    def test_tick_up_ceils_to_001(self):
        self.assertEqual(tick_up(9.341), 9.35)           # 止损向上(不低于风险线)
        self.assertEqual(tick_up(9.34), 9.34)
        self.assertEqual(tick_up(9.996), 10.0)

    def test_tick_down_floors_to_001(self):
        self.assertEqual(tick_down(10.999), 10.99)       # 止盈向下(不高估)
        self.assertEqual(tick_down(10.99), 10.99)

    def test_tick_none_naninf_returns_none(self):        # 绝不伪造价
        for fn in (tick_ref, tick_up, tick_down):
            self.assertIsNone(fn(None))
            self.assertIsNone(fn(float("nan")))
            self.assertIsNone(fn(float("inf")))

    def test_exit_size_levels_are_001_ticked(self):
        plan, rej = exit_and_size(_good_input(), compute_indicators(_series()), "震荡期")
        self.assertIsNone(rej)
        for k in ("entry", "stop", "t1", "t2"):          # 每个执行价都是 0.01 整数倍
            self.assertAlmostEqual(plan[k] * 100, round(plan[k] * 100), places=6)

    def test_exit_size_rejects_when_tick_breaks_structure(self):
        # 对抗(Codex Required):raw 合格(stop=9.996<close=10、rr 巨大),但止损向上取→10.00==入 →
        # 取整后结构失效 → 必须拒(转观察),不输出取整后其实不合格的建仓。
        ind = {"support": 9.999, "resistance": 10.80, "atr14": 0.0024}
        plan, rej = exit_and_size(_good_input(close=10.00), ind, "震荡期")
        self.assertIsNone(plan)
        self.assertIn("取整后", rej)

    def test_exit_size_sizing_uses_worst_case_entry_high_not_close(self):
        # #2/§11.3:股数/金额按**区间上沿(最不利价 entry_high)**计、不按 close。突破 entry_high=close+0.3×ATR>close →
        # cap 介于 100×close 与 100×entry_high 之间时:close 本可买 100 股、按 entry_high 买不起 → 转观察(不输出按上沿成交其实买不起的建仓)。
        # close=100.00,atr=1 → entry_high=tick_down(100.3)=100.3;cap=avail*0.40*0.5=10020(avail=50100、amt5 不绑定);
        # close: 10020//100=100 股;entry_high: 10020//100.3→0 股 → 拒。
        ind = {"support": 98.0, "resistance": 120.0, "atr14": 1.0}
        inp = _good_input(close=100.00)
        inp["account"] = {"available_cash": 50100.0}
        inp["liquidity"] = {"avg_amount_5d": 1e9}
        plan, rej = exit_and_size(inp, ind, "震荡期", etype="突破")
        self.assertIsNone(plan)                 # 按最不利价 entry_high=100.3 买不起 100 股 → 拒
        self.assertIn("entry_high", rej)


class HoldingLevelsTests(unittest.TestCase):
    """S3a: 持仓系统跟踪止损/止盈(被动)= recent_high(20日高=resistance)−ATR×倍数;side-aware tick;
    破位/缺数据不伪造;不算入场价/股数。"""
    def test_ratchet_higher_recent_high_raises_stop(self):
        low, _ = holding_levels({"close": 70.0}, {"resistance": 72.0, "atr14": 2.0}, "震荡期")
        high, _ = holding_levels({"close": 70.0}, {"resistance": 75.0, "atr14": 2.0}, "震荡期")
        self.assertGreater(high["stop"], low["stop"])   # 近高更高 → 跟踪止损上移(ratchet)

    def test_dated_post_entry_high_excludes_pre_entry_extreme(self):
        # B1: a historical 20-day high before entry must not tighten a live holding's trailing stop.
        inp = {"close": 11.0,
               "price_series": [
                   {"trade_date": "20260610", "high": 100.0, "low": 9.0, "close": 10.0},
                   {"trade_date": "20260611", "high": 12.0, "low": 10.0, "close": 11.0},
               ],
               "stateful_risk": {"position": {"entry_date": "20260611", "stop_loss": 8.0}}}
        plan, rej = holding_levels(inp, {"resistance": 100.0, "atr14": 1.0}, "震荡期")
        self.assertIsNone(rej)
        self.assertEqual(plan["highest_since_entry"], 12.0)
        self.assertEqual(plan["stop"], 10.75)

    def test_held_missing_price_dates_fail_closed_even_with_manual_stop(self):
        for date in (None, "20260631"):
            inp = {"close": 11.0,
                   "price_series": [{"trade_date": date, "high": 12.0, "low": 10.0, "close": 11.0}],
                   "stateful_risk": {"position": {"entry_date": "20260611", "stop_loss": 8.0}}}
            plan, reason = holding_levels(inp, {"resistance": 12.0, "atr14": 1.0}, "震荡期")
            self.assertIsNone(plan)
            self.assertIn("价格日期", reason)

    def test_held_nonmapping_price_row_fails_closed(self):
        inp = {"close": 11.0, "price_series": [None],
               "stateful_risk": {"position": {"entry_date": "20260611", "stop_loss": 8.0}}}
        plan, reason = holding_levels(inp, {"resistance": 12.0, "atr14": 1.0}, "震荡期")
        self.assertIsNone(plan)
        self.assertIn("价格行", reason)

    def test_breached_when_price_below_trailing_stop(self):
        plan, rej = holding_levels({"close": 68.0}, {"resistance": 72.0, "atr14": 2.1}, "震荡期")
        self.assertIsNone(rej)
        self.assertTrue(plan["breached"])          # 现价 < 跟踪止损 69.38 → 破位
        self.assertEqual(plan["stop"], 69.38)
        self.assertIsNone(plan["t1"])              # 破位不伪造止盈
        self.assertIsNone(plan["t2"])

    def test_missing_data_rejects_not_fabricated(self):
        self.assertIsNone(holding_levels({"close": 70.0}, {"resistance": None, "atr14": 2.0}, "震荡期")[0])
        self.assertIsNone(holding_levels({"close": 70.0}, {"resistance": 72.0, "atr14": None}, "震荡期")[0])
        self.assertIsNone(holding_levels({"close": None}, {"resistance": 72.0, "atr14": 2.0}, "震荡期")[0])

    def test_validator_hold_rejects_entry_or_shares_nonnull(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        r["m67"]["table"]["入"] = 10.0             # 持仓不应有入场价 → validator 必拒
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_hold_no_system_level_no_manual_ref_no_contradiction(self):
        # R-ASHORT-S3A-HOLDING-LEVELS-MISSING-MANUAL-STOP-ADVICE:系统位算不出(缺价数据)+ 无手填止损(v1.1 允许)
        # → advice **不得**说"按手填参考止损执行"(根本没有),须诚实标"无可执行止损位"。
        held_no_stop = {"position_state": "held",
                        "position": {"ts_code": "600000.SH", "shares": 1000, "avg_cost": 2.70,
                                     "entry_date": "20260601", "stop_loss": None},
                        "rule12": {"status": "inactive"}, "rule13": {"status": "none"},
                        "size_multiplier": 1.0, "reasons": []}
        r = build_m67_report(_good_input(price_series=_series()[:3], stateful_risk=held_no_stop), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertIsNone(r["machine"]["entry_exit_size_star"]["plan"])   # 系统位未算出(缺 ATR)
        adv = r["m67"]["精简结论区"]["操作建议"]
        self.assertIn("无可执行止损位", adv)            # 诚实标
        self.assertNotIn("请按手填参考止损", adv)        # 不伪造"执行不存在的参考止损"
        validate_m67_consistency(r)                      # 持有 plan None → 损/盈一/盈二 null,仍过

    def test_validator_hold_present_plan_requires_execution_discipline(self):
        # Codex probe②:系统位已算出但 advice 缺「无条件/盘中手动」执行纪律 → validator 必拒(state-bound)。
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertIsNotNone(r["machine"]["entry_exit_size_star"]["plan"])    # 系统位已算出
        r["m67"]["精简结论区"]["操作建议"] = "已有持仓。系统跟踪止损 3.05。"     # 去掉 无条件/盘中
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_validator_hold_noref_planNone_rejects_execute_manual_ref(self):
        # Codex probe①:系统位未算出 + 无手填参考,advice 却说「请按手填参考止损…」(伪造不存在的止损)→ 必拒(state-bound)。
        held_no_stop = {"position_state": "held",
                        "position": {"ts_code": "600000.SH", "shares": 1000, "avg_cost": 2.70,
                                     "entry_date": "20260601", "stop_loss": None},
                        "rule12": {"status": "inactive"}, "rule13": {"status": "none"},
                        "size_multiplier": 1.0, "reasons": []}
        r = build_m67_report(_good_input(price_series=_series()[:3], stateful_risk=held_no_stop), AS_OF, "t")
        self.assertIsNone(r["machine"]["entry_exit_size_star"]["plan"])        # 系统位未算出
        r["m67"]["精简结论区"]["操作建议"] = "已有持仓。请按手填参考止损盘中无条件手动执行。"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)


class EntryRangeTests(unittest.TestCase):
    """#2:入场区间(低吸/突破)+ 最不利价(区间上沿)RR 门(价格提案 §3 + §11.2)。"""
    def test_lowxi_range_high_is_close(self):
        ind = {"support": 9.5, "resistance": 12.0, "atr14": 0.4}
        plan, rej = exit_and_size(_good_input(close=10.00), ind, "震荡期", etype="低吸")
        self.assertIsNone(rej)
        self.assertEqual(plan["entry"], 10.00)             # 参考价=close
        self.assertEqual(plan["entry_high"], 10.00)        # 低吸上沿=close(向下取)
        self.assertEqual(plan["entry_low"], 9.80)          # tick_up(max(9.5, 10−0.5×0.4=9.8))
        self.assertEqual(plan["entry_type"], "低吸")
        self.assertIsNone(plan["chase_invalid_above"])
        self.assertEqual(plan["entry_for_risk"], plan["entry_high"])

    def test_breakout_range_and_chase(self):
        ind = {"support": 9.5, "resistance": 15.0, "atr14": 1.0}
        plan, rej = exit_and_size(_good_input(close=10.00), ind, "震荡期", etype="突破")
        self.assertIsNone(rej)
        self.assertEqual(plan["entry_high"], 10.30)        # tick_down(10+0.3×1)
        self.assertEqual(plan["chase_invalid_above"], 10.50)   # close+0.5×ATR
        self.assertEqual(plan["entry_for_risk"], 10.30)    # RR 用区间上沿
        self.assertLessEqual(plan["rr_at_entry_high"], plan["rr"])   # 上沿 RR ≤ 参考价 RR

    def test_breakout_worst_case_rr_gate_rejects(self):
        # 参考价 RR 够(≈2.14 ≥ 突破门 2.0)但区间上沿 RR<门(≈1.68)→ 拒(不输出按上沿成交其实不够 RR 的建仓)。
        # (#6 后突破门=2.0,故用更大 ATR 拉开 close↔entry_high 间距来隔离最不利价门,而非参考价门。)
        ind = {"support": 9.0, "resistance": 17.5, "atr14": 2.0}
        plan, rej = exit_and_size(_good_input(close=10.00), ind, "震荡期", etype="突破")
        self.assertIsNone(plan)
        self.assertIn("最不利价", rej)

    def test_no_dangling_entry_range_must_surface_in_advice(self):
        # #4 no-dangling(价格提案 §8):建仓 plan 有 entry_low/high,但 advice 不含数值 → validator 拒,
        # 防机器算了入场区间用户看不到/无法复核(护栏被静默改坏时此负向测试会红)。
        r = build_m67_report(_good_input(), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        self.assertIsNotNone(r["machine"]["entry_exit_size_star"]["plan"]["entry_low"])
        validate_m67_consistency(r)                              # 原样:advice 含区间 → 过
        # 保留诚实护栏词(试探仓/止损/未验证),仅抹掉入场区间数值 → 触发 no-dangling
        r["m67"]["精简结论区"]["操作建议"] = "试探仓建仓,止损纪律,edge未验证"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_no_dangling_rejects_substring_collision(self):
        # R-ASHORT-M67-PRICE-NODANGLE-SUBSTRING-FALSE-NEGATIVE:entry_low 仅作为 entry_high 的子串出现
        # (10.0 ⊂ 110.0),advice 不含精确「挂单区间 10.0–110.0」短语 → 旧松散 `str(x) in adv` 会放过,
        # 精确带标签短语检查必拒(证明每个机器价位有真正可见落点,而非子串巧合)。
        r = build_m67_report(_good_input(), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        plan["entry_low"], plan["entry_high"] = 10.0, 110.0     # entry/t1/t2/stop 不动 → table↔plan 一致性仍过
        # advice 仅含 entry_high(110.0),其中含 '10.0' 子串;保留诚实护栏词
        r["m67"]["精简结论区"]["操作建议"] = "试探仓建仓,止损纪律,edge未验证;参考价位 110.0"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_breakout_build_report_chase_phrase_validates(self):
        # 突破建仓端到端正向:build_m67_report 生成的 advice 含精确「突破追价超过 {chase}」短语,validate 必过
        # (证 generator↔validator 的 chase 短语逐字节一致 + chase 字段有可见落点,非悬空)。
        inp = _good_input()
        inp["derived"] = {**inp["derived"], "breakout": True, "vol_confirm": True}
        r = build_m67_report(inp, AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        plan = r["machine"]["entry_exit_size_star"]["plan"]
        self.assertEqual(plan["entry_type"], "突破")
        self.assertIsNotNone(plan["chase_invalid_above"])
        adv = r["m67"]["精简结论区"]["操作建议"]
        self.assertIn(f"挂单区间 {plan['entry_low']}–{plan['entry_high']}", adv)
        self.assertIn(f"突破追价超过 {plan['chase_invalid_above']}", adv)
        validate_m67_consistency(r)                                        # 含 chase no-dangling 的正向必过


class RiskFamilyTests(unittest.TestCase):
    def setUp(self):
        self.ind = compute_indicators(_series())

    def test_reduction_hard_veto(self):
        fam = classify_risk_families(_good_input(event={"holder_reduction_active": True,
                                                        "st_or_delisting": False,
                                                        "regulatory_legacy_vetoed": False}), self.ind)
        self.assertEqual(fam["negative_event"]["action"], "hard_veto")

    def test_iv_nobuild_hard_veto(self):
        fam = classify_risk_families(_good_input(iv={"iv_percentile_252d": 95.0}), self.ind)
        self.assertEqual(fam["market_regime"]["action"], "hard_veto")

    def test_iv_halve_downgrade(self):
        fam = classify_risk_families(_good_input(iv={"iv_percentile_252d": 85.0}), self.ind)
        self.assertEqual(fam["market_regime"]["action"], "downgrade")

    def test_unknown_regime_fallback_downgrades(self):
        fam = classify_risk_families(_good_input(regime_fallback={
            "active": True, "reason": "EGS market_regime unknown/missing→按震荡期保守处理"}), self.ind)
        self.assertEqual(fam["market_regime"]["action"], "downgrade")
        self.assertIn("EGS market_regime unknown", "|".join(fam["market_regime"]["reasons"]))

    def test_overheat_downgrade(self):
        d = _good_input()["derived"]; d["overheat"] = True
        fam = classify_risk_families(_good_input(derived=d), self.ind)
        self.assertEqual(fam["overheat_crowding"]["action"], "downgrade")

    def test_egs_hard_veto_flag_hard_vetoes(self):
        # EGS aggregate hard_veto must hard-veto independently (defensive vs decomposed reasons).
        d = _good_input()["derived"]; d["hard_veto"] = True
        fam = classify_risk_families(_good_input(derived=d), self.ind)
        self.assertEqual(fam["negative_event"]["action"], "hard_veto")
        r = build_m67_report(_good_input(derived=d), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")

    def test_stateful_rule12_active_blocks_flat_new_entry(self):
        fam = classify_risk_families(_good_input(stateful_risk=_flat_rule12_active()), self.ind)
        self.assertEqual(fam["stateful_risk"]["action"], "hard_veto")
        self.assertIn("Rule12", "|".join(fam["stateful_risk"]["reasons"]))

    def test_stateful_existing_position_is_downgrade_not_hard(self):
        st = _held_state()
        st["rule12"] = {"status": "active_cooldown", "new_entry_blocked": True}
        fam = classify_risk_families(_good_input(stateful_risk=st), self.ind)
        self.assertEqual(fam["stateful_risk"]["action"], "downgrade")
        self.assertIn("已有持仓", "|".join(fam["stateful_risk"]["reasons"]))


class BuildReportTests(unittest.TestCase):
    def test_buildable_m67(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")

    def test_watch_candidate_is_observed_not_built(self):
        r = build_m67_report(_good_input(analysis_role="watch"), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "观察")
        self.assertIsNone(r["m67"]["table"]["股数"])
        self.assertIn("非 final，仅观察", r["m67"]["精简结论区"]["操作建议"])
        validate_m67_consistency(r)

    def test_watch_with_large_unlock_stays_observed(self):
        r = build_m67_report(_good_input(
            analysis_role="watch",
            event={"holder_reduction_active": False, "st_or_delisting": False,
                   "regulatory_legacy_vetoed": False},
        ), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "观察")
        self.assertIn("非 final，仅观察", r["machine"]["entry_exit_size_star"]["reject_reason"])

    def test_watch_with_existing_position_keeps_holding_management(self):
        r = build_m67_report(_good_input(analysis_role="watch", stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertEqual(r["machine"]["entry_exit_size_star"]["type"], "已有持仓")

    def test_existing_position_yields_hold_not_new_entry(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertEqual(r["machine"]["entry_exit_size_star"]["type"], "已有持仓")
        self.assertIsNone(r["m67"]["table"]["股数"])
        self.assertIn("已有持仓", r["m67"]["精简结论区"]["操作建议"])
        self.assertIn("系统跟踪止损", r["m67"]["精简结论区"]["操作建议"])   # S3a:系统位(非手填)
        self.assertIn("手填参考止损", r["m67"]["精简结论区"]["操作建议"])   # 旧 user-stop 降为参考
        self.assertIsNotNone(r["m67"]["table"]["损"])                      # S3a:系统跟踪止损落表
        validate_m67_consistency(r)
        jsonschema.validate(r, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_existing_position_with_hard_veto_is_denied_not_held(self):
        r = build_m67_report(_good_input(
            stateful_risk=_held_state(),
            event={"holder_reduction_active": False,
                   "st_or_delisting": True,
                   "regulatory_legacy_vetoed": False},
        ), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        self.assertNotEqual(r["m67"]["table"]["操作"], "持有")
        self.assertIn("ST/退市", "|".join(r["machine"]["layer"]["hard_veto"]))
        self.assertIn("已有持仓也不得加仓", r["m67"]["精简结论区"]["操作建议"])
        self.assertIn("手动执行", r["m67"]["精简结论区"]["操作建议"])
        for k in ("股数", "入", "盈一", "盈二", "损"):
            self.assertIsNone(r["m67"]["table"][k])
        validate_m67_consistency(r)

    def test_existing_position_with_market_veto_stays_held_not_denied(self):
        # 市场级否决(IV>90 / 收缩期)是 v14.2「终止所有建仓 / 禁新建仓」语义,只约束**新建仓**;
        # 对**已有持仓**不得硬否决——持仓须保持「持有」+ S3a 系统止损/止盈不被抹掉(对齐 Tier-3
        # build_holding_report;镜像 stateful_risk 新建仓硬限制仅空仓)。回归 held+IV>90/收缩期 抹掉持仓管理层 bug。
        r = build_m67_report(_good_input(iv={"iv_percentile_252d": 95.0},
                                         stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")                 # 不再误判 否决
        self.assertEqual(r["machine"]["layer"]["hard_veto"], [])            # 市场级 veto 对持仓非 hard
        self.assertEqual(r["machine"]["risk_families"]["market_regime"]["action"], "downgrade")  # 降为 advisory
        self.assertIsNotNone(r["m67"]["table"]["损"])                       # S3a 系统跟踪止损未被抹掉
        self.assertIn("系统跟踪止损", r["m67"]["精简结论区"]["操作建议"])
        validate_m67_consistency(r)
        # 收缩期同理:持仓不被否决、S3a 保留。
        r2 = build_m67_report(_good_input(market_regime="收缩期",
                                          stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r2["m67"]["table"]["操作"], "持有")
        self.assertEqual(r2["machine"]["risk_families"]["market_regime"]["action"], "downgrade")
        self.assertIsNotNone(r2["m67"]["table"]["损"])
        validate_m67_consistency(r2)
        # 对照(新建仓限制不变):空仓 + IV>90 仍硬否决。
        flat = build_m67_report(_good_input(iv={"iv_percentile_252d": 95.0}), AS_OF, "t")
        self.assertEqual(flat["m67"]["table"]["操作"], "否决")

    def test_rule12_active_flat_candidate_is_denied(self):
        r = build_m67_report(_good_input(stateful_risk=_flat_rule12_active()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        self.assertIn("Rule12", "|".join(r["machine"]["layer"]["hard_veto"]))
        validate_m67_consistency(r)

    def test_rule12_active_existing_position_holds(self):
        st = _held_state()
        st["rule12"] = {"status": "active_cooldown", "new_entry_blocked": True}
        r = build_m67_report(_good_input(stateful_risk=st), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertIn("Rule12", "|".join(r["machine"]["layer"]["downgrade"]))
        validate_m67_consistency(r)

    def test_rule13_active_flat_reentry_is_denied(self):
        r = build_m67_report(_good_input(stateful_risk=_flat_rule13_active()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        self.assertIn("Rule13", "|".join(r["machine"]["layer"]["hard_veto"]))
        validate_m67_consistency(r)

    def test_stateful_recovery_multiplier_reduces_new_entry_size(self):
        base = build_m67_report(_good_input(), AS_OF, "t")
        st = {"position_state": "flat", "position": None,
              "rule12": {"status": "recovery_1", "recovery_position_multiplier": 0.5},
              "rule13": {"status": "none"},
              "size_multiplier": 0.5,
              "reasons": ["Rule12 recovery_1:size_multiplier=0.50"]}
        r = build_m67_report(_good_input(stateful_risk=st), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        self.assertLess(r["m67"]["table"]["股数"], base["m67"]["table"]["股数"])
        self.assertIn("Rule12 recovery", r["m67"]["table"]["触发条件"])

    def test_breakout_m67_path_active_without_vol_confirm(self):
        # #6-ii 对抗:EGS 新 spec 真突破(is_breakout=True)但旧 vol_confirm=False → M6.7 仍到 type=突破
        # (证 downstream drift 已修:不再被非-spec vol_confirm 门挡回观察)。
        d = _good_input()["derived"]; d["breakout"] = True; d["vol_confirm"] = False
        r = build_m67_report(_good_input(derived=d), AS_OF, "t")
        self.assertEqual(r["machine"]["entry_exit_size_star"]["type"], "突破")
        adv = r["m67"]["精简结论区"]["操作建议"]
        for token in ("试探仓", "止损", "未验证"):
            self.assertIn(token, adv)
        self.assertIsNotNone(r["m67"]["table"]["损"])
        self.assertEqual(r["m67"]["table"]["优先级"], "⭐×3")  # comparison overlay has no official star effect
        validate_m67_consistency(r)
        jsonschema.validate(r, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_hard_veto_report(self):
        r = build_m67_report(_good_input(event={"holder_reduction_active": True,
                                                "st_or_delisting": False,
                                                "regulatory_legacy_vetoed": False}), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        self.assertIsNone(r["m67"]["table"]["损"])
        self.assertIn("硬否决", r["m67"]["精简结论区"]["操作建议"])
        validate_m67_consistency(r)

    def test_iv_nobuild_report(self):
        r = build_m67_report(_good_input(iv={"iv_percentile_252d": 95.0}), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "否决")

    def test_observe_report(self):
        r = build_m67_report(_good_input(close=2.80), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "观察")
        self.assertIsNone(r["m67"]["table"]["损"])

    def test_iv_missing_is_explicit_not_fail_open(self):
        for ivval in ({}, {"iv_percentile_252d": None}):
            r = build_m67_report(_good_input(iv=ivval), AS_OF, "t")
            self.assertEqual(r["machine"]["iv_gate"]["status"], "observe_only_missing_feed")
            self.assertTrue(any("iv_regime_status" in str(o) for o in r["machine"]["layer"]["observe_only"]))
            self.assertIn("IV未知", r["m67"]["精简结论区"]["波动率状态"])
            self.assertNotIn("Rule3减半:否", r["m67"]["精简结论区"]["波动率状态"])
            validate_m67_consistency(r)
            if r["m67"]["table"]["操作"] == "建仓":
                self.assertIn("IV feed 缺失", r["m67"]["精简结论区"]["操作建议"])

    def test_unknown_regime_fallback_is_shock_downgrade_and_halve(self):
        base = build_m67_report(_good_input(), AS_OF, "t")
        r = build_m67_report(_good_input(regime_fallback={
            "active": True,
            "source_status": "unknown",
            "fallback_regime": "震荡期",
            "reason": "EGS market_regime unknown/missing→按震荡期保守处理",
            "action": "downgrade_and_halve",
        }), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        self.assertEqual(r["machine"]["risk_families"]["market_regime"]["action"], "downgrade")
        self.assertLess(r["m67"]["table"]["股数"], base["m67"]["table"]["股数"])
        self.assertIn("EGS regime unknown", r["m67"]["精简结论区"]["当前环境"])
        self.assertIn("regime unknown", r["m67"]["精简结论区"]["操作建议"])
        self.assertIn("market_regime_status=unknown_fallback_to_shock",
                      r["machine"]["layer"]["observe_only"])
        validate_m67_consistency(r)
        jsonschema.validate(r, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


class InvariantTests(unittest.TestCase):
    def setUp(self):
        self.good = build_m67_report(_good_input(), AS_OF, "t")

    def test_valid_passes(self):
        validate_m67_consistency(self.good)

    def test_hard_veto_with_build_rejected(self):
        r = copy.deepcopy(self.good)
        r["machine"]["layer"]["hard_veto"] = ["planted"]   # action still 建仓
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_missing_caveat_rejected(self):
        r = copy.deepcopy(self.good)
        r["m67"]["精简结论区"]["操作建议"] = "低吸建仓。"  # stripped 试探仓/止损/未验证
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_boundary_true_rejected(self):
        r = copy.deepcopy(self.good)
        r["boundary"]["is_validated_alpha"] = True
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_negative_shares_rejected(self):
        r = copy.deepcopy(self.good)
        r["m67"]["table"]["股数"] = -100
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_table_action_mismatch_rejected(self):
        r = copy.deepcopy(self.good)
        r["m67"]["table"]["操作"] = "观察"   # machine action 仍是 建仓
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_build_with_null_plan_rejected(self):
        r = copy.deepcopy(self.good)
        r["machine"]["entry_exit_size_star"]["plan"] = None
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_invalid_as_of_rejected(self):
        r = copy.deepcopy(self.good)
        r["as_of"] = "20260631"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_target_price_mismatch_rejected(self):
        for k in ("盈一", "盈二"):
            r = copy.deepcopy(self.good)
            r["m67"]["table"][k] = r["m67"]["table"][k] + 0.5   # drift away from machine plan
            with self.assertRaises(ValueError):
                validate_m67_consistency(r)


class GovernanceAndSchemaTests(unittest.TestCase):
    def test_governance_parity(self):
        gov = json.loads(GOV_PATH.read_text(encoding="utf-8"))
        self.assertEqual(gov["governance"], GOVERNANCE)

    def test_schema_boundary_true_rejected(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["boundary"]["production"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(r, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_schema_extra_top_field_rejected(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        r["unexpected"] = 1
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(r, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_write_path_validates(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "m67.json"
            write_m67_report(r, str(out))
            self.assertTrue(out.exists())


class EgsScoreInM67Tests(unittest.TestCase):
    """Slice A: build_m67 把选股质量分 egs_score 放进 m67.table[\"EGS分\"](与风控星级两个维度,
    渲染层并列展示;不改 compute_star 保守逻辑)。"""

    def test_egs_score_passed_to_table(self):
        inp = _good_input()
        inp["egs_score"] = 82.66
        self.assertEqual(build_m67_report(inp, AS_OF, "t")["m67"]["table"]["EGS分"], 82.66)

    def test_missing_egs_score_is_none(self):
        self.assertIsNone(build_m67_report(_good_input(), AS_OF, "t")["m67"]["table"]["EGS分"])


class IvHvTagTests(unittest.TestCase):
    """#6 IV-HV advisory 纯函数:IV/HV 比值分档 + 缺数据/退化 → unknown(绝不伪造比值)。"""

    def test_pure_tag_buckets(self):
        self.assertEqual(iv_hv_tag(0.30, 0.20)[0], "iv_rich")     # 1.5 ≥ 1.2
        self.assertEqual(iv_hv_tag(0.20, 0.20)[0], "iv_inline")   # 1.0
        self.assertEqual(iv_hv_tag(0.18, 0.20)[0], "iv_cheap")    # 0.9 ≤ 0.9
        self.assertAlmostEqual(iv_hv_tag(0.30, 0.20)[1], 1.5, places=4)

    def test_threshold_boundaries_inclusive(self):
        self.assertEqual(iv_hv_tag(IV_HV_RATIO_HI, 1.0)[0], "iv_rich")    # ratio == hi → rich
        self.assertEqual(iv_hv_tag(IV_HV_RATIO_LO, 1.0)[0], "iv_cheap")   # ratio == lo → cheap

    def test_unknown_on_missing_or_degenerate(self):
        for bad in (None, 0.0, -1.0, float("nan"), float("inf"), "x"):
            self.assertEqual(iv_hv_tag(bad, 0.2), ("unknown", None))
            self.assertEqual(iv_hv_tag(0.2, bad), ("unknown", None))

    def test_vol_note(self):
        note, reg, ratio = iv_hv_vol_note(0.30, 0.20)
        self.assertIn("IV/HV", note)
        self.assertIn("advisory", note)
        self.assertEqual(reg, "iv_rich")
        self.assertAlmostEqual(ratio, 1.5, places=4)
        n2, r2, x2 = iv_hv_vol_note(None, 0.2)
        self.assertIn("IV-HV未知", n2)
        self.assertEqual((r2, x2), ("unknown", None))


class IvHvReportIntegrationTests(unittest.TestCase):
    """IV-HV 标签落到 M6.7(波动率状态 文案 + machine.iv_gate);两条报告路径(候选 + 持仓)都surfacing。"""

    def _iv(self, iv_value, hv_value):
        return {"iv_percentile_252d": 55.0, "iv_value": iv_value, "hv_value": hv_value}

    def test_candidate_report_surfaces_when_present(self):
        r = build_m67_report(_good_input(iv=self._iv(0.30, 0.20)), AS_OF, "t")
        vs = r["m67"]["精简结论区"]["波动率状态"]
        self.assertIn("IV/HV", vs)
        ig = r["machine"]["iv_gate"]
        self.assertEqual(ig["iv_hv_regime"], "iv_rich")
        self.assertAlmostEqual(ig["iv_hv_ratio"], 1.5, places=4)
        self.assertEqual((ig["iv_value"], ig["hv_value"]), (0.30, 0.20))
        validate_m67_consistency(r)

    def test_candidate_report_unknown_when_absent(self):
        r = build_m67_report(_good_input(), AS_OF, "t")     # 默认 iv 无 iv_value/hv_value
        self.assertIn("IV-HV未知", r["m67"]["精简结论区"]["波动率状态"])
        self.assertEqual(r["machine"]["iv_gate"]["iv_hv_regime"], "unknown")
        self.assertIsNone(r["machine"]["iv_gate"]["iv_hv_ratio"])
        validate_m67_consistency(r)

    def test_held_path_surfaces(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state(), iv=self._iv(0.18, 0.20)), AS_OF, "t")
        self.assertIn("IV/HV", r["m67"]["精简结论区"]["波动率状态"])
        self.assertEqual(r["machine"]["iv_gate"]["iv_hv_regime"], "iv_cheap")   # 0.9
        validate_m67_consistency(r)

    def test_uncovered_holding_report_surfaces(self):
        r = build_holding_report(_good_input(stateful_risk=_held_state(), iv=self._iv(0.30, 0.20)), AS_OF, "t")
        self.assertIn("IV/HV", r["m67"]["精简结论区"]["波动率状态"])
        self.assertEqual(r["machine"]["iv_gate"]["iv_hv_regime"], "iv_rich")
        validate_m67_consistency(r)

    def test_advisory_does_not_change_action(self):
        # IV-HV 任一档都不得翻动 action(纯 advisory):iv_rich/iv_cheap/unknown 下候选 action 不变。
        base = build_m67_report(_good_input(), AS_OF, "t")["machine"]["entry_exit_size_star"]["action"]
        for iv in (self._iv(0.30, 0.20), self._iv(0.18, 0.20), self._iv(0.20, 0.20)):
            r = build_m67_report(_good_input(iv=iv), AS_OF, "t")
            self.assertEqual(r["machine"]["entry_exit_size_star"]["action"], base)


class IvHvConsistencyTests(unittest.TestCase):
    """validate_m67_consistency 守护 machine↔文案 一致(对抗式伪造 regime/ratio 须被抓)。"""

    def _good(self):
        return build_m67_report(_good_input(iv={"iv_percentile_252d": 55.0, "iv_value": 0.30, "hv_value": 0.20}),
                                AS_OF, "t")

    def test_forged_regime_ratio_mismatch_rejected(self):
        r = self._good()
        validate_m67_consistency(r)                                  # baseline OK (iv_rich, 1.5)
        r["machine"]["iv_gate"]["iv_hv_regime"] = "iv_cheap"         # ratio 1.5 却标 cheap → 矛盾
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_inline_with_extreme_ratio_rejected(self):
        r = self._good()
        r["machine"]["iv_gate"]["iv_hv_regime"] = "iv_inline"        # 1.5 不在 (lo,hi) 区间
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_unknown_with_ratio_rejected(self):
        r = build_m67_report(_good_input(), AS_OF, "t")              # unknown, ratio None
        r["machine"]["iv_gate"]["iv_hv_ratio"] = 1.3                 # unknown 不该有比值
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_illegal_regime_rejected(self):
        r = self._good()
        r["machine"]["iv_gate"]["iv_hv_regime"] = "bogus"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_missing_any_iv_hv_key_rejected(self):
        for k in ("iv_value", "hv_value", "iv_hv_ratio", "iv_hv_regime"):
            r = self._good()
            del r["machine"]["iv_gate"][k]
            with self.assertRaises(ValueError):
                validate_m67_consistency(r)

    def test_stale_ratio_rejected(self):
        # raw 0.30/0.20 → 真 ratio 1.5;篡改成 1.3(仍 ≥ hi=1.2,旧阈值检查会放过)→ 须被 raw 重算抓到
        r = self._good()
        r["machine"]["iv_gate"]["iv_hv_ratio"] = 1.3
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_stale_raw_values_rejected(self):
        # 改 raw 使其与保留的 ratio/regime 矛盾(0.25/0.20=1.25 仍 rich,但 ratio 仍写 1.5)→ ratio≠重算 → reject
        r = self._good()
        r["machine"]["iv_gate"]["iv_value"] = 0.25
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_unknown_with_valid_raw_rejected(self):
        # regime 标 unknown 但 raw 有效正值(0.30/0.20 应是 iv_rich)→ 重算 ≠ unknown → reject
        r = self._good()
        r["machine"]["iv_gate"]["iv_hv_regime"] = "unknown"
        r["machine"]["iv_gate"]["iv_hv_ratio"] = None
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)


class CanonicalDateStrictnessTests(unittest.TestCase):
    """P1(Codex 审查补漏):_is_valid_date / _validate_semantic_official 必须严格 canonical(8 ASCII 数字),
    拒 strptime 宽松接受的 '202606 5'/'2026065'(否则非规范 disclosure_date 既过 canonical 声称、又因
    PIT 字符串比较[空格<数字]被当成 <= as_of)。"""

    def test_is_valid_date_strict(self):
        from runners.a_short_phase5_engine import _is_valid_date
        self.assertTrue(_is_valid_date("20260605"))
        for bad in ("202606 5", "2026065", "2026/6/5", "20260631", "", "2026060a"):
            self.assertFalse(_is_valid_date(bad), f"应拒非 canonical {bad!r}")

    def test_validate_semantic_official_rejects_noncanonical_disclosure_date(self):
        from runners.a_short_phase5_engine import _validate_semantic_official
        for bad in ("202606 5", "2026065"):
            sem = {"status": "risk", "had_pit_announcements": True, "events": [{
                "source": "cninfo", "title": "t", "category": "c", "disclosure_date": bad,
                "risk_type": "r", "severity": "high", "url_or_pdf": ""}]}
            with self.assertRaises(ValueError):
                _validate_semantic_official(sem, "20260630")
        ok = {"status": "risk", "had_pit_announcements": True, "events": [{
            "source": "cninfo", "title": "t", "category": "c", "disclosure_date": "20260605",
            "risk_type": "r", "severity": "high", "url_or_pdf": "http://x"}]}
        self.assertIsNotNone(_validate_semantic_official(ok, "20260630"))


class HeldStateActionBindTests(unittest.TestCase):
    """P1(Codex Slice4):validate_m67_consistency 必须绑 action=持有 ⟺ position_state=held + position,
    防 flat 候选冒充持仓行(候选/持仓串线);建仓/观察 反向不得 held。"""

    def _held_report(self):
        return build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")

    def test_normal_held_passes(self):
        r = self._held_report()
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        validate_m67_consistency(r)

    def test_held_action_with_flat_state_rejected(self):
        r = self._held_report()
        r["machine"]["stateful_risk"]["position_state"] = "flat"
        r["machine"]["stateful_risk"]["position"] = None
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_held_action_with_mismatched_position_ts_code_rejected(self):
        r = self._held_report()
        r["machine"]["stateful_risk"]["position"]["ts_code"] = "600519.SH"
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)

    def test_build_action_with_held_state_rejected(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        r["machine"]["stateful_risk"] = {"position_state": "held", "position": {"ts_code": "600000.SH"}}
        with self.assertRaises(ValueError):
            validate_m67_consistency(r)


if __name__ == "__main__":
    unittest.main()
