# -*- coding: utf-8 -*-
"""Tests for US-short per-stock theme-heat scoring (engine/us_short_theme_heat.py) — §4.3.

Adversarial focus (fewer FAIL->修复 rounds): the load-bearing gates are the >=3-of-7 confirmation gate
plus the 个股闸 (a weak stock earns no theme score even if the theme is confirmed), the fit floor, the
continuous (NOT flat) score with the post-gate persistence floor, and the chasing_extreme strip.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_theme_heat as th  # noqa: E402


def _flags(*items):
    return {k: True for k in items}


class MarketConfirmationTests(unittest.TestCase):
    def test_three_items_and_strong_passes(self):
        f = _flags("theme_source_count", "theme_member_count", "theme_breadth_up_frac")
        self.assertTrue(th.market_confirmation_passed(f, stock_is_strong=True))

    def test_exactly_min_is_the_boundary(self):
        f = _flags("theme_source_count", "theme_member_count")          # 2 items
        self.assertFalse(th.market_confirmation_passed(f, stock_is_strong=True))
        f["theme_leader_rs"] = True                                     # -> 3 items
        self.assertTrue(th.market_confirmation_passed(f, stock_is_strong=True))

    def test_weak_stock_earns_nothing_even_if_theme_confirmed(self):
        # REVERSE-FAILURE control: the 个股闸 — a confirmed theme + weak stock must NOT pass
        f = _flags("theme_source_count", "theme_member_count", "theme_breadth_up_frac",
                   "theme_volume_confirm_frac")
        self.assertFalse(th.market_confirmation_passed(f, stock_is_strong=False))

    def test_unknown_keys_cannot_pad_the_count(self):
        f = {"bogus1": True, "bogus2": True, "bogus3": True, "theme_source_count": True}
        self.assertFalse(th.market_confirmation_passed(f, stock_is_strong=True))  # only 1 real item

    def test_no_items_fails(self):
        self.assertFalse(th.market_confirmation_passed({}, stock_is_strong=True))


class FitMultTests(unittest.TestCase):
    def test_above_floor_is_continuous(self):
        self.assertEqual(th.fit_mult_from_score(0.8), 0.8)
        self.assertEqual(th.fit_mult_from_score(0.40), 0.40)           # boundary inclusive

    def test_below_floor_is_gated_to_zero(self):
        self.assertEqual(th.fit_mult_from_score(0.30), 0.0)

    def test_none_or_nan_is_zero(self):
        self.assertEqual(th.fit_mult_from_score(None), 0.0)
        self.assertEqual(th.fit_mult_from_score(float("nan")), 0.0)

    def test_clamped_to_one(self):
        self.assertEqual(th.fit_mult_from_score(1.5), 1.0)


class ContinuousThemeScoreTests(unittest.TestCase):
    def test_proportional_not_flat(self):
        hi = th.continuous_theme_score(90.0, 0.5, 1.0, gate_passed=True)
        lo = th.continuous_theme_score(50.0, 0.5, 1.0, gate_passed=True)
        self.assertAlmostEqual(hi, 45.0)
        self.assertAlmostEqual(lo, 25.0)
        self.assertGreater(hi, lo)                                     # heat-proportional, not flattened

    def test_persistence_floor_applies_after_gate(self):
        # a fresh theme with low persistence is floored, not crushed
        self.assertAlmostEqual(th.continuous_theme_score(80.0, 0.1, 0.8, gate_passed=True), 80 * 0.30 * 0.8)

    def test_gate_not_passed_is_zero(self):
        self.assertEqual(th.continuous_theme_score(90.0, 0.8, 1.0, gate_passed=False), 0.0)

    def test_chasing_extreme_strips_to_zero(self):
        # REVERSE-FAILURE control: chasing_extreme strips the theme score even when heat is high
        self.assertEqual(
            th.continuous_theme_score(95.0, 0.9, 1.0, gate_passed=True, chasing_extreme=True), 0.0)

    def test_missing_inputs_are_zero(self):
        self.assertEqual(th.continuous_theme_score(None, 0.5, 1.0, gate_passed=True), 0.0)
        self.assertEqual(th.continuous_theme_score(80.0, None, 1.0, gate_passed=True), 0.0)
        self.assertEqual(th.continuous_theme_score(80.0, 0.5, float("inf"), gate_passed=True), 0.0)

    def test_fit_mult_clamped_inside_score(self):
        # an out-of-range fit_mult is clamped, not multiplied raw
        self.assertAlmostEqual(th.continuous_theme_score(80.0, 0.5, 1.5, gate_passed=True), 80 * 0.5 * 1.0)


if __name__ == "__main__":
    unittest.main()
