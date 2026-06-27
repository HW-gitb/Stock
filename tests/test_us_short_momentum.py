# -*- coding: utf-8 -*-
"""Tests for engine/us_short_momentum.py (§4.2 momentum block).

Pure/offline. Covers feature computation (returns, relative strength, volume surge), strict numeric
validation (bool/NaN/numeric-string rejected), insufficient-history fail-closed (no fake neutral),
percentile mapping (ties, single, empty), and the full momentum_block pipeline + degrade-on-missing.
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_momentum import (  # noqa: E402
    compute_momentum_features,
    momentum_block,
    _percentile_rank,
    _clean_series,
    _ret,
    MIN_HISTORY_DAYS,
    LOOKBACK_3M,
    VOL_SURGE_LONG,
)


def _rising(n, start=10.0, step=1.0):
    return [start + i * step for i in range(n)]


class TestCleanSeries(unittest.TestCase):
    def test_rejects_short_series(self):
        self.assertIsNone(_clean_series([1.0, 2.0]))  # < MIN_HISTORY_DAYS

    def test_rejects_non_list(self):
        self.assertIsNone(_clean_series("nope"))
        self.assertIsNone(_clean_series(None))

    def test_rejects_nan_inf_in_series(self):
        s = _rising(MIN_HISTORY_DAYS)
        s[3] = float("nan")
        self.assertIsNone(_clean_series(s))

    def test_rejects_bool_in_series(self):
        s = _rising(MIN_HISTORY_DAYS)
        s[2] = True
        self.assertIsNone(_clean_series(s))

    def test_accepts_valid(self):
        s = _rising(MIN_HISTORY_DAYS)
        self.assertEqual(len(_clean_series(s)), MIN_HISTORY_DAYS)


class TestRet(unittest.TestCase):
    def test_simple_return(self):
        s = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]
        self.assertAlmostEqual(_ret(s, 5), 16.0 / 11.0 - 1.0)

    def test_too_short(self):
        self.assertIsNone(_ret([1.0, 2.0], 5))

    def test_nonpositive_base(self):
        s = [0.0] + _rising(10)
        self.assertIsNone(_ret(s, 10))  # base price is 0


class TestComputeFeatures(unittest.TestCase):
    def test_empty_when_insufficient_history(self):
        out = compute_momentum_features([1.0, 2.0])
        self.assertEqual(out["n_features"], 0)
        self.assertEqual(out["features"], {})

    def test_short_history_gets_short_features_only(self):
        # exactly MIN_HISTORY_DAYS → ret_5d computable, ret_1m/3m not
        out = compute_momentum_features(_rising(MIN_HISTORY_DAYS))
        self.assertIn("ret_5d", out["features"])
        self.assertNotIn("ret_3m", out["features"])

    def test_full_history_all_price_features(self):
        out = compute_momentum_features(_rising(LOOKBACK_3M + 5))
        for f in ("ret_1m", "ret_3m", "ret_5d", "ret_10d"):
            self.assertIn(f, out["features"])

    def test_relative_strength_vs_benchmark(self):
        closes = _rising(30, start=100.0, step=2.0)   # strong uptrend
        spy = _rising(30, start=100.0, step=0.5)       # weak uptrend
        out = compute_momentum_features(closes, spy_closes=spy)
        self.assertIn("rel_spy_1m", out["features"])
        self.assertGreater(out["features"]["rel_spy_1m"], 0)  # outperforms SPY

    def test_no_benchmark_no_rel_feature(self):
        out = compute_momentum_features(_rising(30))
        self.assertNotIn("rel_spy_1m", out["features"])

    def test_volume_surge(self):
        closes = _rising(VOL_SURGE_LONG + 5)
        vols = [1000.0] * VOL_SURGE_LONG + [5000.0] * 5  # recent spike
        out = compute_momentum_features(closes, volumes=vols)
        self.assertIn("vol_surge", out["features"])
        self.assertGreater(out["features"]["vol_surge"], 1.0)

    def test_volume_too_short_no_surge(self):
        closes = _rising(30)
        out = compute_momentum_features(closes, volumes=[1000.0] * 30)  # < VOL_SURGE_LONG
        self.assertNotIn("vol_surge", out["features"])


class TestPercentileRank(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_percentile_rank({}), {})

    def test_single_is_mid(self):
        self.assertEqual(_percentile_rank({"A": 5.0}), {"A": 50.0})

    def test_monotone(self):
        out = _percentile_rank({"A": 1.0, "B": 2.0, "C": 3.0})
        self.assertEqual(out["A"], 0.0)
        self.assertEqual(out["C"], 100.0)
        self.assertEqual(out["B"], 50.0)

    def test_ties_share_average(self):
        out = _percentile_rank({"A": 1.0, "B": 1.0, "C": 3.0})
        self.assertEqual(out["A"], out["B"])  # tie → same percentile


class TestMomentumBlock(unittest.TestCase):
    def test_full_pool_percentile(self):
        feats = {
            "HI": {"ret_1m": 0.30, "ret_5d": 0.10},
            "MID": {"ret_1m": 0.10, "ret_5d": 0.05},
            "LO": {"ret_1m": -0.10, "ret_5d": -0.02},
        }
        out = momentum_block(feats)
        b = out["momentum_block"]
        self.assertEqual(b["HI"], 100.0)
        self.assertEqual(b["LO"], 0.0)
        self.assertEqual(b["MID"], 50.0)
        self.assertEqual(out["insufficient_history"], [])

    def test_insufficient_history_excluded_not_faked(self):
        feats = {
            "GOOD": {"ret_1m": 0.2},
            "EMPTY": {},          # no sub-features → insufficient
        }
        out = momentum_block(feats)
        self.assertIn("EMPTY", out["insufficient_history"])
        self.assertNotIn("EMPTY", out["momentum_block"])  # NOT a fake neutral
        self.assertIn("GOOD", out["momentum_block"])

    def test_partial_subfeatures_still_scored(self):
        # one ticker has only ret_5d, another has full set → both scored on what they have
        feats = {
            "A": {"ret_1m": 0.1, "ret_3m": 0.2, "ret_5d": 0.05},
            "B": {"ret_5d": 0.5},  # only one feature, but very high
        }
        out = momentum_block(feats)
        self.assertIn("A", out["momentum_block"])
        self.assertIn("B", out["momentum_block"])
        self.assertEqual(out["insufficient_history"], [])

    def test_coverage_counts(self):
        feats = {
            "A": {"ret_1m": 0.1, "vol_surge": 1.2},
            "B": {"ret_1m": 0.2},
        }
        out = momentum_block(feats)
        self.assertEqual(out["sub_feature_coverage"]["ret_1m"], 2)
        self.assertEqual(out["sub_feature_coverage"]["vol_surge"], 1)

    def test_bool_value_rejected_as_feature(self):
        # a bool sneaking in as a feature value must not be scored
        feats = {"A": {"ret_1m": True}, "B": {"ret_1m": 0.2}}
        out = momentum_block(feats)
        self.assertIn("A", out["insufficient_history"])  # True rejected → A has no valid feature

    def test_empty_input(self):
        out = momentum_block({})
        self.assertEqual(out["momentum_block"], {})
        self.assertEqual(out["insufficient_history"], [])

    def test_non_dict_input(self):
        out = momentum_block("nope")
        self.assertEqual(out["momentum_block"], {})


if __name__ == "__main__":
    unittest.main()
