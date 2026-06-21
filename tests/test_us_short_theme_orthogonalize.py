# -*- coding: utf-8 -*-
"""Tests for US-short industry⊥theme orthogonalization (engine/us_short_theme_orthogonalize.py) — §4.3.

Adversarial focus: the overlap-removed property (industry strength explained by theme → low residual;
unexplained industry → high residual), the degenerate fallbacks (too-few-paired / zero theme variance),
alignment with the pool (None where industry absent), and whole-class input validation incl. the
`min_paired` default param and malformed pool rows.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_theme_orthogonalize as ot  # noqa: E402


def _pool(*pairs):
    return [{"theme_heat_score": t, "industry_heat_score": y} for (t, y) in pairs]


class OrthogonalizationTests(unittest.TestCase):
    def test_unexplained_industry_gets_highest_residual(self):
        # 4 stocks on the industry≈2×theme line + 1 with industry far above what theme explains → that
        # one carries the most theme-orthogonal industry strength → highest percentile.
        pool = _pool((10, 20), (20, 40), (30, 60), (40, 80), (50, 200))
        out = ot.orthogonalize_industry_on_theme(pool)
        self.assertEqual(len(out), 5)
        for v in out:
            self.assertTrue(0.0 <= v <= 100.0)
        self.assertEqual(out.index(max(out)), 4)        # the anomalous-industry stock ranks top
        self.assertEqual(out[4], 100.0)

    def test_perfectly_explained_industry_is_non_boosting_zero(self):
        # REVERSE-FAILURE control: industry == 2×theme exactly → no separable industry signal → all 0.0;
        # the overlap is counted once and must NOT become a max-percentile boost.
        out = ot.orthogonalize_industry_on_theme(_pool((10, 20), (20, 40), (30, 60), (40, 80)))
        self.assertTrue(all(v == 0.0 for v in out))

    def test_too_few_paired_rows_fall_back_to_industry_percentile(self):
        out = ot.orthogonalize_industry_on_theme(_pool((10, 50), (20, 90)))   # 2 paired < MIN_PAIRED
        self.assertEqual(out, [50.0, 100.0])

    def test_zero_theme_variance_falls_back_to_industry_percentile(self):
        out = ot.orthogonalize_industry_on_theme(_pool((10, 50), (10, 90), (10, 70)))   # theme has no variance
        self.assertAlmostEqual(out[0], 100.0 / 3)
        self.assertEqual(out[1], 100.0)
        self.assertAlmostEqual(out[2], 200.0 / 3)


class AlignmentAndMissingTests(unittest.TestCase):
    def test_missing_industry_row_is_none(self):
        pool = _pool((10, 20), (20, 40), (30, 60)) + [{"theme_heat_score": 40}]   # last has no industry
        out = ot.orthogonalize_industry_on_theme(pool)
        self.assertEqual(len(out), 4)
        self.assertIsNone(out[3])

    def test_industry_only_row_is_none_in_regression_case(self):
        # mirror A-short: in the regression case a row with industry but no theme isn't paired -> None
        pool = _pool((10, 20), (20, 40), (30, 60), (40, 80)) + [{"industry_heat_score": 99}]
        out = ot.orthogonalize_industry_on_theme(pool)
        self.assertIsNone(out[4])

    def test_empty_pool_is_empty(self):
        self.assertEqual(ot.orthogonalize_industry_on_theme([]), [])


class BadInputTests(unittest.TestCase):
    def test_non_list_pool_is_empty(self):
        for bad in (None, "pool", 5, {"theme_heat_score": 1}):
            self.assertEqual(ot.orthogonalize_industry_on_theme(bad), [])

    def test_non_dict_or_malformed_rows_have_no_value(self):
        pool = [None, "row", {"theme_heat_score": "10", "industry_heat_score": True},
                {"theme_heat_score": float("nan"), "industry_heat_score": float("inf")}]
        out = ot.orthogonalize_industry_on_theme(pool)
        self.assertEqual(out, [None, None, None, None])   # every value malformed -> no industry -> None

    def test_min_paired_below_floor_falls_back_to_default(self):
        # MIN_PAIRED=3 is the invariant: malformed OR an int < 3 (incl. 2) falls back to the floor.
        pool = _pool((10, 20), (20, 40), (30, 60), (40, 80), (50, 200))
        baseline = ot.orthogonalize_industry_on_theme(pool)
        for bad in ("3", None, True, 0, -1, 1, 2, 2.0):
            self.assertEqual(ot.orthogonalize_industry_on_theme(pool, min_paired=bad), baseline, repr(bad))

    def test_min_paired_two_does_not_regress_two_points(self):
        # the min_paired=2 bypass is closed: 2 paired rows degenerate to the industry percentile, never a
        # (meaningless) perfect-fit regression of two points.
        out = ot.orthogonalize_industry_on_theme(_pool((10, 50), (20, 90)), min_paired=2)
        self.assertEqual(out, [50.0, 100.0])

    def test_min_paired_can_be_raised_for_calibration(self):
        # a caller may RAISE the threshold (valid calibration, not the fail-closed default): with
        # min_paired=5 a 4-paired pool degenerates to the industry percentile instead of regressing.
        pool = _pool((10, 20), (20, 45), (30, 55), (40, 85))   # 4 paired with real residual dispersion
        regressed = ot.orthogonalize_industry_on_theme(pool, min_paired=3)
        degenerate = ot.orthogonalize_industry_on_theme(pool, min_paired=5)
        self.assertNotEqual(regressed, degenerate)
        self.assertEqual(degenerate, ot._percentile_rank_0_100([20, 45, 55, 85]))


if __name__ == "__main__":
    unittest.main()
