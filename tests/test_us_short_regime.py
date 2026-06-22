# -*- coding: utf-8 -*-
"""Tests for the US-short market risk-regime engine (engine/us_short_regime.py) — §7.

Adversarial focus (fewer FAIL->修复 rounds): the load-bearing safety gate is never-default-
aggressive on incomplete data, plus anti-chatter (downgrade fast / upgrade slow) and the frozen
cap ladder. Conformance triangulates the engine's cap ladder + anti-chatter run count against
the frozen us_short_regime_governance preset.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_regime as rg  # noqa: E402

_GOV = ROOT / "presets" / "us_short_regime_governance_20260620.json"


def _r(vix=None, trend=None, breadth=None):
    d = {}
    if vix is not None:
        d["vix"] = vix
    if trend is not None:
        d["market_trend"] = trend
    if breadth is not None:
        d["breadth"] = breadth
    return d


class ClassifyVixTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(rg.classify_vix(12.0), "进攻")
        self.assertEqual(rg.classify_vix(20.0), "震荡")
        self.assertEqual(rg.classify_vix(30.0), "防御")
        self.assertEqual(rg.classify_vix(40.0), "极度防御")

    def test_boundaries_are_lower_inclusive(self):
        self.assertEqual(rg.classify_vix(17.999), "进攻")
        self.assertEqual(rg.classify_vix(18.0), "震荡")   # >= 18 leaves 进攻
        self.assertEqual(rg.classify_vix(25.0), "防御")
        self.assertEqual(rg.classify_vix(35.0), "极度防御")

    def test_unknown_never_guessed(self):
        for bad in (None, float("nan"), float("inf"), "x"):
            self.assertEqual(rg.classify_vix(bad), rg.UNKNOWN)
        self.assertEqual(rg.classify_vix("18"), "震荡")   # numeric string parses, not unknown


class WorstOfAndDegradationTests(unittest.TestCase):
    def test_worst_of_full_data(self):
        self.assertEqual(rg.compute_market_risk_regime(_r("进攻", "进攻", "进攻"))["market_risk_regime"], "进攻")
        self.assertEqual(rg.compute_market_risk_regime(_r("进攻", "震荡", "防御"))["market_risk_regime"], "防御")

    def test_unknown_axis_never_stays_aggressive(self):
        # REVERSE-FAILURE control: a missing/unknown axis must NOT pass as 进攻 (never_default_aggressive)
        out = rg.compute_market_risk_regime(_r(rg.UNKNOWN, "进攻", "进攻"))
        self.assertNotEqual(out["market_risk_regime"], "进攻")
        self.assertEqual(out["market_risk_regime"], "震荡")   # 1 missing -> one conservative downgrade
        self.assertEqual(out["missing_axes"], ["vix"])

    def test_missing_critical_trend_floors_at_defensive(self):
        out = rg.compute_market_risk_regime(_r(vix="进攻", breadth="进攻"))   # market_trend absent (critical)
        self.assertEqual(out["market_risk_regime"], "防御")

    def test_all_axes_missing_is_restricted_most_defensive(self):
        out = rg.compute_market_risk_regime({})
        self.assertEqual(out["market_risk_regime"], "极度防御")
        self.assertTrue(out["restricted"])
        self.assertEqual(out["position_cap"], 0.0)
        self.assertFalse(out["new_entry_permitted"])

    def test_more_missing_is_more_defensive(self):
        one = rg.compute_market_risk_regime(_r("进攻", "进攻"))["market_risk_regime"]   # breadth missing
        two = rg.compute_market_risk_regime(_r("进攻"))["market_risk_regime"]            # trend+breadth missing
        self.assertGreaterEqual(rg._SEVERITY[two], rg._SEVERITY[one])

    def test_non_dict_axis_input_is_restricted_not_crash(self):
        # a truthy non-dict axis_regimes (list/str/int) must fail closed to restricted/极度防御, never crash
        for bad in (["进攻"], "进攻", 1, ("震荡",)):
            out = rg.compute_market_risk_regime(bad)
            self.assertEqual(out["market_risk_regime"], "极度防御", repr(bad))
            self.assertTrue(out["restricted"], repr(bad))
            self.assertFalse(out["new_entry_permitted"], repr(bad))


class AntiChatterTests(unittest.TestCase):
    def test_downgrade_is_immediate(self):
        out = rg.compute_market_risk_regime(_r("防御", "防御", "防御"), prior_regime="进攻")
        self.assertEqual(out["market_risk_regime"], "防御")
        self.assertEqual(out["upgrade_count"], 0)

    def test_upgrade_needs_two_consecutive_better_runs(self):
        first = rg.compute_market_risk_regime(_r("进攻", "进攻", "进攻"), prior_regime="防御", prior_upgrade_count=0)
        self.assertEqual(first["market_risk_regime"], "防御")   # held, not yet upgraded
        self.assertEqual(first["upgrade_count"], 1)
        second = rg.compute_market_risk_regime(_r("进攻", "进攻", "进攻"), prior_regime="防御", prior_upgrade_count=1)
        self.assertEqual(second["market_risk_regime"], "进攻")  # confirmed -> upgrade
        self.assertEqual(second["upgrade_count"], 0)

    def test_equal_regime_no_chatter(self):
        out = rg.compute_market_risk_regime(_r("震荡", "震荡", "震荡"), prior_regime="震荡")
        self.assertEqual(out["market_risk_regime"], "震荡")


class ContractConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_cap_ladder_matches_preset(self):
        preset = {c["regime"]: c["position_cap"] for c in self.gov["market_risk_regime_caps"]}
        self.assertEqual(preset, rg.POSITION_CAP)
        self.assertEqual(set(preset), set(rg.REGIMES))

    def test_anti_chatter_run_count_matches_preset(self):
        self.assertEqual(self.gov["anti_chatter"]["upgrade_confirmation_weekly_runs"], rg.UPGRADE_CONFIRM_RUNS)

    def test_each_regime_emits_its_frozen_cap(self):
        for regime, cap in rg.POSITION_CAP.items():
            out = rg.compute_market_risk_regime(_r(regime, regime, regime))
            self.assertEqual(out["market_risk_regime"], regime)
            self.assertEqual(out["position_cap"], cap)

    def test_scope_is_not_hard_veto(self):
        # §7 scope: regime affects sizing/new-entry, never a hard veto — the engine emits no veto field.
        out = rg.compute_market_risk_regime(_r("极度防御", "极度防御", "极度防御"))
        self.assertNotIn("veto_tier", out)
        self.assertNotIn("hard_veto", out)
        self.assertTrue(self.gov["scope"]["not_hard_veto"])


if __name__ == "__main__":
    unittest.main()
