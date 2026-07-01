# -*- coding: utf-8 -*-
"""Tests for engine/us_short_momentum.py (§4.2 momentum block).

Pure/offline. Covers feature computation (returns, relative strength, volume surge), strict numeric
validation (bool/NaN/numeric-string rejected), insufficient-history fail-closed (no fake neutral),
percentile mapping (ties, single, empty), and the full momentum_block pipeline + degrade-on-missing.
"""
import math
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_momentum import (  # noqa: E402
    compute_momentum_features,
    momentum_block,
    _percentile_rank,
    _clean_series,
    _parse_dated_series,
    _ret,
    MIN_HISTORY_DAYS,
    LOOKBACK_1M,
    LOOKBACK_3M,
    VOL_SURGE_LONG,
)

_AS_OF = "2026-06-26"


def _rising(n, start=10.0, step=1.0):
    return [start + i * step for i in range(n)]


def _dates(n, as_of=_AS_OF):
    """n ascending unique daily date strings ending at as_of (calendar-agnostic — the engine aligns by
    date string, so consecutive-day stamps are fine for tests)."""
    end = datetime.strptime(as_of, "%Y-%m-%d").date()
    return [(end - timedelta(days=(n - 1 - i))).isoformat() for i in range(n)]


def _series(closes, *, as_of=_AS_OF, session="RTH", adjustment_mode="split_div_adjusted",
            volumes=None, dates=None):
    """Build a PIT-bearing dated series from a closes list (+ optional volumes / explicit dates)."""
    n = len(closes)
    ds = dates if dates is not None else _dates(n, as_of)
    points = []
    for i in range(n):
        pt = {"date": ds[i], "close": closes[i]}
        if volumes is not None:
            pt["volume"] = volumes[i]
        points.append(pt)
    return {"as_of": as_of, "session": session, "adjustment_mode": adjustment_mode, "points": points}


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

    def test_rejects_nonpositive(self):
        # Codex F-A: a non-positive close is malformed price data, never evidence (mirrors industry_heat)
        s = _rising(MIN_HISTORY_DAYS); s[2] = 0.0
        self.assertIsNone(_clean_series(s))
        s = _rising(MIN_HISTORY_DAYS); s[3] = -1.0
        self.assertIsNone(_clean_series(s))


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
        out = compute_momentum_features(_series([1.0, 2.0]))
        self.assertEqual(out["n_features"], 0)
        self.assertEqual(out["features"], {})

    def test_short_history_gets_short_features_only(self):
        # exactly MIN_HISTORY_DAYS → ret_5d computable, ret_1m/3m not
        out = compute_momentum_features(_series(_rising(MIN_HISTORY_DAYS)))
        self.assertIn("ret_5d", out["features"])
        self.assertNotIn("ret_3m", out["features"])

    def test_full_history_all_price_features(self):
        out = compute_momentum_features(_series(_rising(LOOKBACK_3M + 5)))
        for f in ("ret_1m", "ret_3m", "ret_5d", "ret_10d"):
            self.assertIn(f, out["features"])

    def test_relative_strength_vs_benchmark(self):
        closes = _rising(30, start=100.0, step=2.0)   # strong uptrend
        spy = _rising(30, start=100.0, step=0.5)       # weak uptrend
        out = compute_momentum_features(_series(closes), spy_series=_series(spy))
        self.assertIn("rel_spy_1m", out["features"])
        self.assertGreater(out["features"]["rel_spy_1m"], 0)  # outperforms SPY
        self.assertEqual(out["alignment"]["rel_spy_1m"], "ok")

    def test_no_benchmark_no_rel_feature(self):
        out = compute_momentum_features(_series(_rising(30)))
        self.assertNotIn("rel_spy_1m", out["features"])
        self.assertEqual(out["alignment"]["rel_spy_1m"], "no_benchmark")

    def test_volume_surge(self):
        closes = _rising(VOL_SURGE_LONG + 5)
        vols = [1000.0] * VOL_SURGE_LONG + [5000.0] * 5  # recent spike
        out = compute_momentum_features(_series(closes, volumes=vols))
        self.assertIn("vol_surge", out["features"])
        self.assertGreater(out["features"]["vol_surge"], 1.0)

    def test_volume_too_short_no_surge(self):
        out = compute_momentum_features(_series(_rising(30), volumes=[1000.0] * 30))  # < VOL_SURGE_LONG
        self.assertNotIn("vol_surge", out["features"])

    def test_partial_volume_coverage_no_surge(self):
        # a missing (None) volume INSIDE the VOL_SURGE_LONG window omits vol_surge — no partial-coverage surge
        vols = [1000.0] * (VOL_SURGE_LONG + 4) + [None]
        out = compute_momentum_features(_series(_rising(VOL_SURGE_LONG + 5), volumes=vols))
        self.assertNotIn("vol_surge", out["features"])

    def test_vol_surge_ignores_early_missing_volume(self):
        # F-C (self-review): a missing volume OUTSIDE the VOL_SURGE_LONG window must NOT omit a computable
        # surge (over-omission would drop a feature and could push the ticker below min_coverage).
        n = VOL_SURGE_LONG + 5
        vols = [None] + [1000.0] * (n - 6) + [5000.0] * 5   # only index 0 (outside the last VOL_SURGE_LONG) is None
        self.assertEqual(len(vols), n)
        out = compute_momentum_features(_series(_rising(n), volumes=vols))
        self.assertIn("vol_surge", out["features"])
        self.assertGreater(out["features"]["vol_surge"], 1.0)

    def test_negative_last_volume_omits_vol_surge(self):
        # Codex residual: a negative kept volume is malformed market data — it must NOT enter vol_surge
        vols = [1000.0] * (VOL_SURGE_LONG + 4) + [-5.0]      # negative last volume (inside the window)
        out = compute_momentum_features(_series(_rising(VOL_SURGE_LONG + 5), volumes=vols))
        self.assertNotIn("vol_surge", out["features"])

    def test_negative_volume_in_window_omits_vol_surge(self):
        n = VOL_SURGE_LONG + 5
        vols = [1000.0] * n; vols[-3] = -1.0                 # negative inside the VOL_SURGE_LONG tail
        out = compute_momentum_features(_series(_rising(n), volumes=vols))
        self.assertNotIn("vol_surge", out["features"])

    def test_nonfinite_or_nonnumeric_volume_omits_vol_surge(self):
        n = VOL_SURGE_LONG + 5
        for bad in (float("nan"), "1000", True):
            vols = [1000.0] * n; vols[-2] = bad              # non-finite / numeric-string / bool → None → omit
            out = compute_momentum_features(_series(_rising(n), volumes=vols))
            self.assertNotIn("vol_surge", out["features"], bad)

    def test_valid_zero_volume_kept(self):
        # positive control: a zero volume is VALID (kept, unlike negative) — a no-trade day, not malformed
        n = VOL_SURGE_LONG + 5
        vols = [1000.0] * n; vols[-20] = 0.0                 # a zero inside the window stays (>=0)
        out = compute_momentum_features(_series(_rising(n), volumes=vols))
        self.assertIn("vol_surge", out["features"])


class TestPitAlignment(unittest.TestCase):
    """R-USSHORT-BATCH5-MOMENTUM-COVERAGE-PIT-COMPARABILITY-GAP — PIT/alignment input-rework half."""

    # --- dated-series parse / fail-closed ---
    def test_parse_rejects_non_dict_and_bad_shape(self):
        self.assertIsNone(_parse_dated_series([1, 2, 3]))
        self.assertIsNone(_parse_dated_series({"as_of": _AS_OF, "points": []}))   # missing keys
        extra = _series(_rising(30)); extra["surprise"] = 1
        self.assertIsNone(_parse_dated_series(extra))                              # closed-world

    def test_parse_rejects_bad_as_of(self):
        s = _series(_rising(30)); s["as_of"] = "2026-13-99"
        self.assertIsNone(_parse_dated_series(s))

    def test_parse_rejects_blank_metadata(self):
        s = _series(_rising(30)); s["session"] = ""
        self.assertIsNone(_parse_dated_series(s))

    def test_parse_rejects_nonascending_or_duplicate_dates(self):
        s = _series(_rising(30)); s["points"][5]["date"] = s["points"][4]["date"]  # duplicate -> corrupt axis
        self.assertIsNone(_parse_dated_series(s))

    def test_parse_rejects_nonfinite_close(self):
        s = _series(_rising(30)); s["points"][10]["close"] = float("nan")
        self.assertIsNone(_parse_dated_series(s))

    def test_future_point_blocked_pit_cut(self):
        # a point dated AFTER as_of is BLOCKED: the return uses the last <=as_of close, not the future one
        closes = _rising(40, start=100.0, step=1.0)
        s = _series(closes)
        future = (datetime.strptime(_AS_OF, "%Y-%m-%d").date() + timedelta(days=5)).isoformat()
        s["points"].append({"date": future, "close": 99999.0})   # absurd close that WOULD dominate if used
        out = compute_momentum_features(s)
        self.assertAlmostEqual(out["features"]["ret_5d"], closes[-1] / closes[-6] - 1.0)
        self.assertEqual(out["pit"]["n_points"], 40)             # future point not counted

    def test_future_nonfinite_close_not_rejected(self):
        # F-D (self-review): a future point's value is PIT-BLOCKED and never validated, so a future NON-FINITE
        # close must NOT over-reject an otherwise-valid <=as_of series (a kept non-finite close is still rejected
        # — see test_parse_rejects_nonfinite_close). Consistent with industry_heat.
        closes = _rising(40, start=100.0, step=1.0)
        s = _series(closes)
        fut = (datetime.strptime(_AS_OF, "%Y-%m-%d").date() + timedelta(days=4)).isoformat()
        s["points"].append({"date": fut, "close": float("nan")})   # future NaN — must be ignored, not reject
        out = compute_momentum_features(s)
        self.assertAlmostEqual(out["features"]["ret_5d"], closes[-1] / closes[-6] - 1.0)
        self.assertEqual(out["pit"]["n_points"], 40)               # future point excluded, series still scored

    def test_last_zero_close_rejected(self):
        # Codex F-A: a non-positive close IN the kept window makes the ticker unusable (no features)
        closes = _rising(40, start=100.0, step=1.0); closes[-1] = 0.0
        self.assertEqual(compute_momentum_features(_series(closes))["features"], {})

    def test_earlier_negative_close_in_kept_rejected(self):
        closes = _rising(40, start=100.0, step=1.0); closes[5] = -5.0
        self.assertEqual(compute_momentum_features(_series(closes))["features"], {})

    def test_nonpositive_benchmark_omits_rel(self):
        out = compute_momentum_features(_series(_rising(40, start=100.0, step=2.0)),
                                        spy_series=_series([0.0] * 40))   # non-positive benchmark → unusable
        self.assertNotIn("rel_spy_1m", out["features"])
        self.assertEqual(out["alignment"]["rel_spy_1m"], "parse_failed")

    def test_ipo_short_history_after_cut_no_features(self):
        self.assertEqual(compute_momentum_features(_series(_rising(3)))["features"], {})

    # --- relative-strength alignment: common dates + matching as_of/session/adjustment ---
    def test_missing_benchmark_dates_aligns_on_common(self):
        closes = _rising(40, start=100.0, step=2.0)
        spy_series = _series(_rising(40, start=100.0, step=0.5))
        spy_series["points"] = spy_series["points"][3:]          # benchmark missing 3 early dates
        out = compute_momentum_features(_series(closes), spy_series=spy_series)
        self.assertEqual(out["alignment"]["rel_spy_1m"], "ok")   # aligned over the common dates
        self.assertIn("rel_spy_1m", out["features"])

    def test_insufficient_overlap_omits_rel(self):
        spy_series = _series(_rising(40))
        spy_series["points"] = spy_series["points"][-(LOOKBACK_1M - 2):]   # < LOOKBACK_1M+1 common days
        out = compute_momentum_features(_series(_rising(40)), spy_series=spy_series)
        self.assertEqual(out["alignment"]["rel_spy_1m"], "insufficient_overlap")
        self.assertNotIn("rel_spy_1m", out["features"])

    def test_adjustment_mismatch_omits_rel(self):
        out = compute_momentum_features(
            _series(_rising(30), adjustment_mode="split_div_adjusted"),
            spy_series=_series(_rising(30), adjustment_mode="raw"))
        self.assertEqual(out["alignment"]["rel_spy_1m"], "adjustment_mismatch")
        self.assertNotIn("rel_spy_1m", out["features"])

    def test_session_mismatch_omits_rel(self):
        out = compute_momentum_features(
            _series(_rising(30), session="RTH"), spy_series=_series(_rising(30), session="ETH"))
        self.assertEqual(out["alignment"]["rel_spy_1m"], "session_mismatch")
        self.assertNotIn("rel_spy_1m", out["features"])

    def test_as_of_mismatch_omits_rel(self):
        out = compute_momentum_features(
            _series(_rising(30), as_of="2026-06-26"), spy_series=_series(_rising(30), as_of="2026-06-25"))
        self.assertEqual(out["alignment"]["rel_spy_1m"], "as_of_mismatch")
        self.assertNotIn("rel_spy_1m", out["features"])

    def test_benchmark_parse_failed_note(self):
        out = compute_momentum_features(_series(_rising(30)), spy_series={"as_of": _AS_OF})  # bad shape
        self.assertEqual(out["alignment"]["rel_spy_1m"], "parse_failed")
        self.assertNotIn("rel_spy_1m", out["features"])

    def test_pit_provenance_recorded(self):
        out = compute_momentum_features(_series(_rising(30)))
        self.assertEqual(out["pit"]["as_of"], _AS_OF)
        self.assertEqual(out["pit"]["session"], "RTH")
        self.assertEqual(out["pit"]["n_points"], 30)

    def test_same_day_alignment_value_correct(self):
        # positive control: identical axes → rel = own 1m return − benchmark 1m return over the same days
        closes = _rising(40, start=100.0, step=2.0)
        spy = _rising(40, start=100.0, step=0.5)
        out = compute_momentum_features(_series(closes), spy_series=_series(spy))
        own_r = closes[-1] / closes[-1 - LOOKBACK_1M] - 1.0
        spy_r = spy[-1] / spy[-1 - LOOKBACK_1M] - 1.0
        self.assertAlmostEqual(out["features"]["rel_spy_1m"], own_r - spy_r)


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


# the full 7-sub-feature set; a ticker carrying all of them clears the default min-coverage (4) and is scored.
_FULL = ("ret_1m", "ret_3m", "ret_5d", "ret_10d", "rel_spy_1m", "rel_qqq_1m", "vol_surge")


def _full_feats(value):
    return {sf: value for sf in _FULL}


class TestMomentumBlock(unittest.TestCase):
    def test_full_pool_percentile(self):
        feats = {"HI": _full_feats(0.30), "MID": _full_feats(0.10), "LO": _full_feats(-0.10)}
        out = momentum_block(feats)
        b = out["momentum_block"]
        self.assertEqual(b["HI"], 100.0)
        self.assertEqual(b["LO"], 0.0)
        self.assertEqual(b["MID"], 50.0)
        self.assertEqual(out["insufficient_history"], [])

    def test_insufficient_history_excluded_not_faked(self):
        feats = {
            "GOOD": _full_feats(0.2),
            "EMPTY": {},          # no sub-features → insufficient_history
        }
        out = momentum_block(feats)
        self.assertIn("EMPTY", out["insufficient_history"])
        self.assertNotIn("EMPTY", out["momentum_block"])  # NOT a fake neutral
        self.assertIn("GOOD", out["momentum_block"])

    def test_below_min_coverage_not_scored(self):
        # R-USSHORT-BATCH5-MOMENTUM-COVERAGE-PIT-COMPARABILITY-GAP: a ticker below min-coverage is NOT scored on
        # the handful it has (it goes to insufficient_coverage, distinct from the no-feature insufficient_history).
        feats = {"FULL": _full_feats(0.1), "SPARSE": {"ret_5d": 0.5}}   # SPARSE has 1 of 7 < min 4
        out = momentum_block(feats)
        self.assertIn("FULL", out["momentum_block"])
        self.assertIn("SPARSE", out["insufficient_coverage"])
        self.assertNotIn("SPARSE", out["momentum_block"])        # not auto-full-weighted
        self.assertNotIn("SPARSE", out["insufficient_history"])  # it HAS a feature, just below min

    def test_sparse_extreme_does_not_outrank_full(self):
        # the exact Codex probe: a single-feature EXTREME ticker must not outrank a full-feature ticker — it is
        # below min-coverage so it is not scored at all (previously it could score 100 and outrank FULL).
        feats = {"FULL": _full_feats(0.0), "SHORT": {"ret_5d": 999.0}}
        out = momentum_block(feats)
        self.assertIn("FULL", out["momentum_block"])
        self.assertNotIn("SHORT", out["momentum_block"])
        self.assertIn("SHORT", out["insufficient_coverage"])

    def test_neutral_fill_caps_partial_extreme(self):
        # a ticker AT min-coverage with all-top present features is pulled toward neutral by its MISSING features
        # (neutral-fill over the SAME full set), so a genuinely full-feature top ticker still ranks above it.
        feats = {
            "TOP": _full_feats(2.0),                                                   # 7 features, all top
            "PARTIAL": {sf: 1.0 for sf in ("ret_1m", "ret_3m", "ret_5d", "ret_10d")},  # exactly 4 (>=min), 3 missing→neutral
            "LOW": _full_feats(0.0),                                                   # 7 features, all low
        }
        out = momentum_block(feats)
        b = out["momentum_block"]
        self.assertGreater(b["TOP"], b["PARTIAL"])   # full-coverage top beats partial-but-extreme
        self.assertGreater(b["PARTIAL"], b["LOW"])

    def test_coverage_matrix_and_min_coverage_reported(self):
        feats = {"FULL": _full_feats(0.1), "SPARSE": {"ret_5d": 0.1}}
        out = momentum_block(feats)
        self.assertEqual(out["min_coverage"], 4)
        self.assertEqual(out["coverage_matrix"]["FULL"], {"n_present": 7, "scored": True})
        self.assertEqual(out["coverage_matrix"]["SPARSE"], {"n_present": 1, "scored": False})

    def test_min_coverage_param_and_validation(self):
        feats = {"A": {"ret_1m": 0.1, "ret_5d": 0.2}, "B": {"ret_1m": 0.2, "ret_5d": 0.1}}
        out = momentum_block(feats, min_coverage=2)   # lowered threshold → both 2-feature tickers scored
        self.assertIn("A", out["momentum_block"])
        self.assertIn("B", out["momentum_block"])
        with self.assertRaises(ValueError):
            momentum_block(feats, min_coverage=0)
        with self.assertRaises(ValueError):
            momentum_block(feats, min_coverage=True)   # bool is not a valid int threshold

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
