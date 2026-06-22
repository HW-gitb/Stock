# -*- coding: utf-8 -*-
"""Tests for US-short theme_block (engine/us_short_theme_block.py) — §4.3 35% 块方向合成.

Adversarial focus: the §13.1 #38 direction rule (cross-sector → theme base, else fail-safe GICS industry
base), strict `theme_is_cross_sector`, overlap-counted-once (no double boost), and fail-closed inputs.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_theme_block as tb  # noqa: E402


def _anti(cross0):
    # r0 = LOW theme / HIGH industry; anti-correlated pool so orthogonal residuals collapse to 0
    r0 = {"theme_heat_score": 10, "industry_heat_score": 90}
    if cross0 is not None:
        r0["theme_is_cross_sector"] = cross0
    return [r0, {"theme_heat_score": 50, "industry_heat_score": 50},
            {"theme_heat_score": 90, "industry_heat_score": 10}]


class DirectionRuleTests(unittest.TestCase):
    def test_cross_sector_uses_theme_base_pure_uses_industry_base(self):
        # r0 has low theme / high industry → industry base (no flag) ranks it ABOVE theme base (cross=True)
        industry_base = tb.assemble_theme_block(_anti(None))
        theme_base = tb.assemble_theme_block(_anti(True))
        self.assertGreater(industry_base[0], theme_base[0])

    def test_failsafe_to_industry_base_unless_explicit_true(self):
        ref = tb.assemble_theme_block(_anti(None))[0]            # no flag → industry base
        for bad in (False, 1, "yes", None, 0):                  # truthy-non-True / falsey → still industry base
            self.assertEqual(tb.assemble_theme_block(_anti(bad))[0], ref, repr(bad))


class OverlapCountedOnceTests(unittest.TestCase):
    def test_perfect_overlap_does_not_double_count(self):
        # industry == theme for every row → orthogonal residual 0 → block = base percentile only, no boost
        rows = [{"theme_heat_score": v, "industry_heat_score": v} for v in (10, 50, 90)]
        block = tb.assemble_theme_block(rows)
        self.assertEqual(block, tb._pool_percentile(rows, "industry_heat_score"))


class FailClosedTests(unittest.TestCase):
    def test_non_list_and_empty(self):
        self.assertEqual(tb.assemble_theme_block("notalist"), [])
        self.assertEqual(tb.assemble_theme_block([]), [])

    def test_unusable_row_is_none(self):
        rows = [{"theme_heat_score": "x", "industry_heat_score": None},   # industry base, malformed → None
                {"theme_heat_score": 50, "industry_heat_score": 50},
                {"theme_heat_score": 90, "industry_heat_score": 10}]
        block = tb.assemble_theme_block(rows)
        self.assertIsNone(block[0])
        self.assertIsNotNone(block[1])

    def test_block_values_in_range(self):
        rows = [{"theme_heat_score": v, "industry_heat_score": 100 - v} for v in (10, 30, 50, 70, 90)]
        for b in tb.assemble_theme_block(rows):
            if b is not None:
                self.assertTrue(0.0 <= b <= 100.0, b)


class BaseOnlyRowTests(unittest.TestCase):
    """§13 #38: the orthogonal residual is an ADDITIVE de-dup term — a missing OPPOSITE source must not drop
    a row that has a valid base heat (the common pure-GICS case)."""

    def test_pure_gics_industry_only_rows_rank_by_industry(self):
        rows = [{"industry_heat_score": 10}, {"industry_heat_score": 50}, {"industry_heat_score": 90}]
        block = tb.assemble_theme_block(rows)
        self.assertNotIn(None, block)
        self.assertEqual(block, tb._pool_percentile(rows, "industry_heat_score"))

    def test_cross_sector_theme_only_rows_rank_by_theme(self):
        rows = [{"theme_heat_score": v, "theme_is_cross_sector": True} for v in (10, 50, 90)]
        block = tb.assemble_theme_block(rows)
        self.assertNotIn(None, block)
        self.assertEqual(block, tb._pool_percentile(rows, "theme_heat_score"))

    def test_base_only_row_kept_in_mixed_pool(self):
        rows = [{"industry_heat_score": 30},                          # industry-only base
                {"theme_heat_score": 50, "industry_heat_score": 50},
                {"theme_heat_score": 90, "industry_heat_score": 10}]
        self.assertIsNotNone(tb.assemble_theme_block(rows)[0])

    def test_malformed_selected_base_still_none_even_with_opposite_present(self):
        # industry base (no cross flag) with malformed industry but valid theme → still None (base gates)
        rows = [{"industry_heat_score": "x", "theme_heat_score": 80},
                {"industry_heat_score": 50, "theme_heat_score": 50},
                {"industry_heat_score": 90, "theme_heat_score": 10}]
        self.assertIsNone(tb.assemble_theme_block(rows)[0])


class ConstantTests(unittest.TestCase):
    def test_residual_coef_valid_coefficient(self):
        self.assertTrue(0.0 < tb.RESIDUAL_COEF <= 1.0)


if __name__ == "__main__":
    unittest.main()
