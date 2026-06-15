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
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_phase5_engine import (  # noqa: E402
    compute_indicators, entry_type, exit_and_size, classify_risk_families,
    build_m67_report, validate_m67_consistency, write_m67_report, GOVERNANCE,
)

SCHEMA_PATH = ROOT / "schemas" / "a_short_m67_report.schema.json"
GOV_PATH = ROOT / "presets" / "a_short_phase5_engine_governance_20260610.json"
AS_OF = "20260609"


def _series():
    # 30d; day12 carries support 2.87 + resistance 3.10 (inside 20d lookback, outside 14d ATR);
    # all closes 2.90 so MAs ~2.90 (current 2.90 not below all MAs).
    s = []
    for i in range(30):
        if i == 12:
            s.append({"high": 3.10, "low": 2.87, "close": 2.90})
        else:
            s.append({"high": 2.92, "low": 2.88, "close": 2.90})
    return s


def _good_input(**over):
    inp = {
        "ts_code": "600000.SH", "name": "测试", "close": 2.90, "price_series": _series(),
        "esp_score": 60, "l4_score": 70,
        "overlay": {"eligible": True, "crowding_hit": False},
        "industry_trend": "neutral",
        "derived": {"overheat": False, "chasing_high": False, "breakout": False, "vol_confirm": False,
                    "crash_veto": False, "limit_locked": False, "suspended": False},
        "event": {"holder_reduction_active": False, "st_or_delisting": False,
                  "regulatory_legacy_vetoed": False},
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
        self.assertAlmostEqual(ind["support"], 2.87)
        self.assertAlmostEqual(ind["resistance"], 3.10)
        self.assertAlmostEqual(ind["atr14"], 0.04, places=3)


class EntryExitTests(unittest.TestCase):
    def setUp(self):
        self.ind = compute_indicators(_series())

    def test_entry_type_lowxi(self):
        etype, _ = entry_type(_good_input(), self.ind)
        self.assertEqual(etype, "低吸")

    def test_entry_type_observe_below_all_ma(self):
        etype, _ = entry_type(_good_input(close=2.80), self.ind)
        self.assertEqual(etype, "观察")

    def test_breakout_entry_gated_by_vol_confirm(self):
        # R-ASHORT-FIRSTGAP-BREAKOUT-E2E: is_breakout alone stays non-breakout; vol_confirm un-dormants it.
        d = _good_input()["derived"]; d["breakout"] = True; d["vol_confirm"] = False
        et, _ = entry_type(_good_input(derived=d), self.ind)
        self.assertNotEqual(et, "突破")
        d2 = _good_input()["derived"]; d2["breakout"] = True; d2["vol_confirm"] = True
        et2, _ = entry_type(_good_input(derived=d2), self.ind)
        self.assertEqual(et2, "突破")

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

    def test_existing_position_yields_hold_not_new_entry(self):
        r = build_m67_report(_good_input(stateful_risk=_held_state()), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "持有")
        self.assertEqual(r["machine"]["entry_exit_size_star"]["type"], "已有持仓")
        self.assertIsNone(r["m67"]["table"]["股数"])
        self.assertIn("已有持仓", r["m67"]["精简结论区"]["操作建议"])
        self.assertIn("手动止损", r["m67"]["精简结论区"]["操作建议"])
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

    def test_breakout_m67_path_active_with_vol_confirm(self):
        # M6.7 breakout branch is no longer dormant: is_breakout+vol_confirm reaches type=突破.
        d = _good_input()["derived"]; d["breakout"] = True; d["vol_confirm"] = True
        r = build_m67_report(_good_input(derived=d), AS_OF, "t")
        self.assertEqual(r["machine"]["entry_exit_size_star"]["type"], "突破")
        adv = r["m67"]["精简结论区"]["操作建议"]
        for token in ("试探仓", "止损", "未验证"):
            self.assertIn(token, adv)
        self.assertIsNotNone(r["m67"]["table"]["损"])
        self.assertEqual(r["m67"]["table"]["优先级"], "⭐×4")  # base3 + overlay eligible
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


if __name__ == "__main__":
    unittest.main()
