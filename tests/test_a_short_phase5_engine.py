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

    def test_exit_size_buildable(self):
        plan, rej = exit_and_size(_good_input(), self.ind, "震荡期", extra_halve=False)
        self.assertIsNone(rej)
        self.assertGreaterEqual(plan["rr"], 1.5)
        self.assertGreaterEqual(plan["shares"], 100)

    def test_exit_size_extra_halve_smaller(self):
        full, _ = exit_and_size(_good_input(), self.ind, "震荡期", extra_halve=False)
        half, _ = exit_and_size(_good_input(), self.ind, "震荡期", extra_halve=True, halve_reason="x")
        self.assertLess(half["shares"], full["shares"])

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


class BuildReportTests(unittest.TestCase):
    def test_buildable_m67(self):
        r = build_m67_report(_good_input(), AS_OF, "t")
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
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


if __name__ == "__main__":
    unittest.main()
