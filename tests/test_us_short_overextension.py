# -*- coding: utf-8 -*-
"""Tests for the US-short overextension tiering (engine/us_short_overextension.py) — §4.3.

Adversarial focus (fewer FAIL->修复 rounds): the load-bearing gates are chasing_extreme requiring
>= K co-occurring conditions (a single big move NEVER triggers it — the never-solo analog), the
mutual exclusivity (chasing_extreme precedence so a stock is penalised once), and warning being
execution-side-only (it must NEVER strip the theme score). Conformance checks the state vocab against
the frozen action_table contract.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_overextension as ox  # noqa: E402

_ACT = ROOT / "presets" / "us_short_action_table_contract_20260620.json"

# >=3 parabolic conditions (vertical_run + daily_move + volume_climax + far_above_all_mas)
_CHASING = {"close": 120.0, "ma5": 110.0, "ma10": 105.0, "ma20": 100.0, "atr": 2.0,
            "daily_change": 6.0, "vol_ratio": 3.0, "vertical_run": True, "weak_retrace": False}
# mild over-MA10, trend intact, no parabolic conditions met
_WARNING = {"close": 104.0, "ma5": 101.0, "ma10": 101.0, "ma20": 100.0, "atr": 2.0,
            "daily_change": 1.0, "vol_ratio": 1.0, "vertical_run": False, "weak_retrace": False}


class ChasingExtremeTests(unittest.TestCase):
    def test_multi_condition_parabolic_is_chasing_and_strips_theme(self):
        out = ox.classify_overextension(_CHASING)
        self.assertEqual(out["overextension_state"], "chasing_extreme")
        self.assertTrue(out["strips_theme_score"])
        self.assertGreaterEqual(out["conditions_met"], ox.CHASING_MIN_CONDITIONS)

    def test_single_condition_alone_never_chasing(self):
        # REVERSE-FAILURE control: a huge daily move ALONE (1 condition) must NOT be chasing_extreme
        m = {"close": 100.0, "ma5": 99.0, "ma10": 98.0, "ma20": 97.0, "atr": 2.0,
             "daily_change": 20.0, "vol_ratio": 1.0, "vertical_run": False, "weak_retrace": False}
        out = ox.classify_overextension(m)
        self.assertNotEqual(out["overextension_state"], "chasing_extreme")
        self.assertLess(out["conditions_met"], ox.CHASING_MIN_CONDITIONS)

    def test_just_below_threshold_is_not_chasing(self):
        # exactly K-1 conditions (vertical_run + daily_move) must not tip into chasing_extreme
        m = {"close": 100.0, "ma5": 99.0, "ma10": 98.0, "ma20": 97.0, "atr": 2.0,
             "daily_change": 6.0, "vol_ratio": 1.0, "vertical_run": True, "weak_retrace": False}
        out = ox.classify_overextension(m)
        self.assertEqual(out["conditions_met"], ox.CHASING_MIN_CONDITIONS - 1)
        self.assertNotEqual(out["overextension_state"], "chasing_extreme")


class WarningTests(unittest.TestCase):
    def test_warning_is_execution_side_and_keeps_theme_score(self):
        out = ox.classify_overextension(_WARNING)
        self.assertEqual(out["overextension_state"], "warning")
        self.assertFalse(out["strips_theme_score"])      # REVERSE: warning must NEVER strip the theme score
        self.assertTrue(out["execution_flags"]["force_pullback"])
        self.assertTrue(out["execution_flags"]["reduce_size"])
        self.assertTrue(out["execution_flags"]["raise_rr_gate"])

    def test_none_when_not_extended(self):
        m = {"close": 100.0, "ma5": 100.0, "ma10": 100.0, "ma20": 100.0, "atr": 2.0,
             "daily_change": 0.0, "vol_ratio": 1.0, "vertical_run": False, "weak_retrace": False}
        out = ox.classify_overextension(m)
        self.assertEqual(out["overextension_state"], "none")
        self.assertFalse(out["strips_theme_score"])
        self.assertEqual(out["execution_flags"], {})


class MutualExclusivityTests(unittest.TestCase):
    def test_chasing_takes_precedence_over_warning(self):
        # _CHASING is also above MA10+k1*ATR, but a stock is penalised once: chasing wins, not warning
        out = ox.classify_overextension(_CHASING)
        self.assertEqual(out["overextension_state"], "chasing_extreme")  # not "warning"

    def test_states_are_mutually_exclusive_single_value(self):
        for m in (_CHASING, _WARNING):
            self.assertIn(ox.classify_overextension(m)["overextension_state"], ox.OVEREXTENSION_STATES)


class MissingDataTests(unittest.TestCase):
    def test_missing_close_or_atr_is_none_no_fabrication(self):
        for bad in ({"close": None, "atr": 2.0}, {"close": 100.0, "atr": None}, {"close": 100.0, "atr": 0.0}):
            out = ox.classify_overextension(bad)
            self.assertEqual(out["overextension_state"], "none")
            self.assertFalse(out["strips_theme_score"])


class ContractConformanceTests(unittest.TestCase):
    def test_state_vocab_matches_frozen_action_table(self):
        act = json.loads(_ACT.read_text(encoding="utf-8"))
        self.assertEqual(set(ox.OVEREXTENSION_STATES), set(act["design_locked_enums"]["overextension_state"]))

    def test_all_outputs_are_frozen_vocab(self):
        for m in (_CHASING, _WARNING, {"close": 100.0, "ma10": 100.0, "atr": 2.0}):
            self.assertIn(ox.classify_overextension(m)["overextension_state"], ox.OVEREXTENSION_STATES)


if __name__ == "__main__":
    unittest.main()
