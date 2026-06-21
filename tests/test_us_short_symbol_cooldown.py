# -*- coding: utf-8 -*-
"""Tests for US-short symbol_cooldown (engine/us_short_symbol_cooldown.py) — §8 单票再入场冷静期.

Adversarial focus: a position that never filled is NOT punished (unfilled breakout → no cooldown), the
re-entry gate needs ALL three (anti-revenge-buy), and strict True on every gate input.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_symbol_cooldown as sc  # noqa: E402

_GOV = ROOT / "presets" / "us_short_symbol_cooldown_governance_20260620.json"


class EntersCooldownTests(unittest.TestCase):
    def test_filled_then_failure_enters(self):
        self.assertTrue(sc.enters_cooldown("filled_then_stop_loss"))
        self.assertTrue(sc.enters_cooldown("filled_then_breakout_failure"))

    def test_unfilled_breakout_never_enters(self):
        # 没进场不罚: a breakout that never filled does NOT cooldown (§8 / §18.1 #16)
        for t in ("breakout_unfilled", "unfilled", "filled_then_take_profit", "", None, True, 1):
            self.assertFalse(sc.enters_cooldown(t), repr(t))


class ReentryGateTests(unittest.TestCase):
    def test_all_three_required(self):
        self.assertTrue(sc.reentry_allowed(True, True, True))

    def test_any_missing_blocks(self):
        self.assertFalse(sc.reentry_allowed(True, True, False))
        self.assertFalse(sc.reentry_allowed(True, False, True))
        self.assertFalse(sc.reentry_allowed(False, True, True))

    def test_truthy_non_true_does_not_satisfy(self):
        # strict True — a stray truthy flag must NOT open the re-entry gate (fail closed)
        for truthy in (1, "yes", [1], 1.0):
            self.assertFalse(sc.reentry_allowed(truthy, True, True), repr(truthy))
            self.assertFalse(sc.reentry_allowed(True, truthy, True), repr(truthy))
            self.assertFalse(sc.reentry_allowed(True, True, truthy), repr(truthy))


class StatusTests(unittest.TestCase):
    def test_fresh_filled_failure_enters_cooldown(self):
        out = sc.symbol_cooldown_status(False, trigger="filled_then_stop_loss")
        self.assertEqual(out["status"], "entering_cooldown")
        self.assertEqual(out["action"], "downgrade_to_observe")

    def test_no_trigger_is_none(self):
        out = sc.symbol_cooldown_status(False, trigger="breakout_unfilled")
        self.assertEqual(out["status"], "none")
        self.assertIsNone(out["action"])

    def test_in_cooldown_downgrades_until_full_gate(self):
        out = sc.symbol_cooldown_status(True, new_catalyst=True, new_structure=True, cooldown_expired=False)
        self.assertEqual(out["status"], "in_cooldown")
        self.assertEqual(out["action"], "downgrade_to_observe")
        self.assertFalse(out["reentry_allowed"])

    def test_in_cooldown_full_gate_allows_reentry(self):
        out = sc.symbol_cooldown_status(True, new_catalyst=True, new_structure=True, cooldown_expired=True)
        self.assertEqual(out["status"], "reentry_allowed")
        self.assertTrue(out["reentry_allowed"])

    def test_malformed_in_cooldown_fails_closed_to_observe(self):
        # a state we can't trust must NOT yield an unrestricted symbol — fail closed to observe
        for bad in (1, 0, None, "true", "false", []):
            out = sc.symbol_cooldown_status(bad, trigger="filled_then_stop_loss",
                                            new_catalyst=True, new_structure=True, cooldown_expired=True)
            self.assertEqual(out["status"], "in_cooldown", repr(bad))
            self.assertEqual(out["action"], "downgrade_to_observe", repr(bad))
            self.assertFalse(out["reentry_allowed"], repr(bad))


class ContractTests(unittest.TestCase):
    def test_constants_match_preset(self):
        gov = json.loads(_GOV.read_text(encoding="utf-8"))
        self.assertEqual(sc.ENTERS_COOLDOWN_ON, tuple(gov["enters_cooldown_on"]))
        self.assertEqual(sc.REENTRY_REQUIRES, tuple(gov["reentry_requires"]))
        self.assertEqual(sc.DURING_COOLDOWN_ACTION, gov["during_cooldown_action"])
        self.assertTrue(gov["reentry_all_required"])
        self.assertTrue(gov["breakout_unfilled_no_cooldown"])


if __name__ == "__main__":
    unittest.main()
