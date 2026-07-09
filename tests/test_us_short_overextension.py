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
from datetime import date as _date, timedelta as _timedelta
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

    def test_non_dict_metrics_is_none_not_crash(self):
        # a truthy non-dict metrics (str/list/int) must fail closed to none (no fabrication), never crash
        for bad in ("bad", ["close"], 1):
            out = ox.classify_overextension(bad)
            self.assertEqual(out["overextension_state"], "none", repr(bad))
            self.assertFalse(out["strips_theme_score"], repr(bad))

    def test_numeric_string_metric_does_not_parse_into_condition(self):
        # strict finite: a numeric-string daily_change must NOT parse into the daily_move condition
        base = {"close": 100.0, "ma5": 99.0, "ma10": 98.0, "ma20": 97.0, "atr": 2.0,
                "vol_ratio": 1.0, "vertical_run": False, "weak_retrace": False}
        out = ox.classify_overextension({**base, "daily_change": "20"})
        self.assertNotIn("daily_move_ge_m_atr", out["condition_names"])   # the string didn't parse into a condition


class ContractConformanceTests(unittest.TestCase):
    def test_state_vocab_matches_frozen_action_table(self):
        act = json.loads(_ACT.read_text(encoding="utf-8"))
        self.assertEqual(set(ox.OVEREXTENSION_STATES), set(act["design_locked_enums"]["overextension_state"]))

    def test_all_outputs_are_frozen_vocab(self):
        for m in (_CHASING, _WARNING, {"close": 100.0, "ma10": 100.0, "atr": 2.0}):
            self.assertIn(ox.classify_overextension(m)["overextension_state"], ox.OVEREXTENSION_STATES)


class HugeIntHardeningTests(unittest.TestCase):
    def test_huge_int_metric_does_not_crash_classify(self):
        # The metrics layer makes this module RAW-FACING, so a forged/corrupt huge int (overflows float()) in
        # ANY numeric field must be CONTAINED to None (fail-closed), never a raw OverflowError — this session's
        # whole-class huge-int hardening (mirrors momentum/theme siblings).
        huge = 10 ** 400
        for field in ("close", "atr", "ma5", "ma10", "ma20", "daily_change", "vol_ratio"):
            m = dict(_CHASING)
            m[field] = huge
            out = ox.classify_overextension(m)   # must not raise
            self.assertIn(out["overextension_state"], ox.OVEREXTENSION_STATES, field)


class OverextensionMetricsTests(unittest.TestCase):
    def test_moving_averages(self):
        closes = [float(x) for x in range(1, 21)]   # 1..20
        m = ox.compute_overextension_metrics(closes, [])
        self.assertAlmostEqual(m["ma5"], sum(range(16, 21)) / 5)    # 18.0
        self.assertAlmostEqual(m["ma10"], sum(range(11, 21)) / 10)  # 15.5
        self.assertAlmostEqual(m["ma20"], sum(range(1, 21)) / 20)   # 10.5

    def test_moving_average_too_short_is_none(self):
        m = ox.compute_overextension_metrics([1.0, 2.0, 3.0], [])   # < 5
        self.assertIsNone(m["ma5"])
        self.assertIsNone(m["ma10"])
        self.assertIsNone(m["ma20"])

    def test_ma_bad_value_in_window_is_none(self):
        closes = [float(x) for x in range(1, 20)] + [float("nan")]  # bad tail value
        self.assertIsNone(ox.compute_overextension_metrics(closes, [])["ma5"])

    def test_daily_change_is_signed_close_to_close(self):
        self.assertEqual(ox.compute_overextension_metrics([100.0, 106.0], [])["daily_change"], 6.0)
        self.assertEqual(ox.compute_overextension_metrics([100.0, 97.0], [])["daily_change"], -3.0)  # down = negative

    def test_daily_change_too_short_is_none(self):
        self.assertIsNone(ox.compute_overextension_metrics([100.0], [])["daily_change"])

    def test_vol_ratio_climax(self):
        vols = [1_000_000.0] * 20 + [3_000_000.0]   # 21: baseline-20 avg 1e6, today 3e6
        self.assertAlmostEqual(ox.compute_overextension_metrics([100.0] * 21, vols)["vol_ratio"], 3.0)

    def test_vol_ratio_too_short_is_none(self):
        self.assertIsNone(ox.compute_overextension_metrics([100.0] * 21, [1_000_000.0] * 20)["vol_ratio"])  # < 21

    def test_vol_ratio_missing_recent_volume_is_none(self):
        vols = [None] + [1_000_000.0] * 19 + [2_000_000.0]   # a None inside the recent baseline
        self.assertIsNone(ox.compute_overextension_metrics([100.0] * 21, vols)["vol_ratio"])

    def test_vol_ratio_zero_baseline_is_none(self):
        vols = [0.0] * 20 + [3_000_000.0]
        self.assertIsNone(ox.compute_overextension_metrics([100.0] * 21, vols)["vol_ratio"])

    def test_vertical_run_true_broken_and_short(self):
        self.assertTrue(ox.compute_overextension_metrics([1.0, 2.0, 3.0, 4.0, 5.0], [])["vertical_run"])   # 4 up-days
        self.assertFalse(ox.compute_overextension_metrics([1.0, 2.0, 3.0, 2.0, 5.0], [])["vertical_run"])  # a down day
        self.assertFalse(ox.compute_overextension_metrics([1.0, 2.0, 3.0, 4.0], [])["vertical_run"])       # < 5 closes

    def test_weak_retrace_true_when_runup_and_shallow(self):
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 111.0]  # +11%, monotonic
        self.assertTrue(ox.compute_overextension_metrics(closes, [])["weak_retrace"])

    def test_weak_retrace_false_on_deep_pullback(self):
        # ran up (+30% net) but a ~9% peak-to-trough pullback => NOT a weak/shallow retrace
        closes = [100.0, 105.0, 110.0, 100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0]
        self.assertFalse(ox.compute_overextension_metrics(closes, [])["weak_retrace"])

    def test_weak_retrace_false_when_no_runup(self):
        # REVERSE control: a flat/quiet window (no run-up) must NOT count as weak_retrace
        closes = [100.0, 100.5] * 5
        self.assertFalse(ox.compute_overextension_metrics(closes, [])["weak_retrace"])

    def test_strict_finite_inputs_never_crash(self):
        # bool / numeric-string / NaN / Inf / overflowing huge-int in the series must not crash, never fabricate
        for bad in (True, "5", float("nan"), float("inf"), 10 ** 400):
            closes = [float(x) for x in range(1, 20)] + [bad]
            m = ox.compute_overextension_metrics(closes, [])   # must not raise
            self.assertIsNone(m["ma5"], repr(bad))             # bad tail value → MA window unavailable
            self.assertIsNone(m["daily_change"], repr(bad))    # bad last close → None

    def test_non_list_inputs_are_honest_empty(self):
        empty = {"ma5": None, "ma10": None, "ma20": None, "vol_ratio": None,
                 "daily_change": None, "vertical_run": False, "weak_retrace": False}
        for bad in (None, "bad", 123, {"x": 1}):
            self.assertEqual(ox.compute_overextension_metrics(bad, bad), empty, repr(bad))   # must not crash


class OverextensionMetricsIntegrationTests(unittest.TestCase):
    """Prove the cut-1 metrics layer plugs straight into classify_overextension (the whole point)."""

    def test_parabolic_series_metrics_feed_chasing_extreme(self):
        closes = [float(106 + i) for i in range(24)] + [135.0]   # 106..129 then a jump to 135
        volumes = [1_000_000.0] * 24 + [3_000_000.0]             # 3x volume climax on the last day
        metrics = ox.compute_overextension_metrics(closes, volumes)
        out = ox.classify_overextension({**metrics, "close": 135.0, "atr": 2.0})
        self.assertEqual(out["overextension_state"], "chasing_extreme")
        self.assertTrue(out["strips_theme_score"])
        self.assertGreaterEqual(out["conditions_met"], ox.CHASING_MIN_CONDITIONS)

    def test_benign_series_metrics_feed_none(self):
        closes = [100.0, 101.0] * 13
        volumes = [1_000_000.0] * 26
        metrics = ox.compute_overextension_metrics(closes, volumes)
        out = ox.classify_overextension({**metrics, "close": 101.0, "atr": 2.0})
        self.assertEqual(out["overextension_state"], "none")
        self.assertFalse(out["strips_theme_score"])


_OX_BASE = _date(2026, 6, 1)


def _dt(i):
    return (_OX_BASE + _timedelta(days=i)).isoformat()


def _ohlcv(closes, volumes=None, *, future_closes=None, spread=0.5):
    """Build an OHLCV dated series (ascending daily dates). as_of = the last CURRENT close's date;
    future_closes (if given) become points dated AFTER as_of — for PIT / look-ahead tests."""
    pts = []
    for i, c in enumerate(closes):
        p = {"date": _dt(i), "high": float(c) + spread, "low": float(c) - spread, "close": float(c)}
        if volumes is not None:
            p["volume"] = float(volumes[i])
        pts.append(p)
    as_of = _dt(len(closes) - 1)
    for j, c in enumerate(future_closes or []):
        pts.append({"date": _dt(len(closes) + j), "high": float(c) + spread, "low": float(c) - spread,
                    "close": float(c)})
    return {"as_of": as_of, "session": "RTH", "adjustment_mode": "split_adjusted", "points": pts}


_PARABOLIC_CLOSES = [106 + i for i in range(24)] + [135]
_PARABOLIC_VOLUMES = [1_000_000.0] * 24 + [3_000_000.0]


class OverextensionFeaturesTests(unittest.TestCase):
    """cut 2a: the per-ticker producer entry (OHLCV PIT-series → tier). ATR from the price engine + cut-1
    metrics + classify, computed BEFORE ranking so chasing_extreme can strip theme at the selection layer."""

    def test_parabolic_ohlcv_series_is_chasing(self):
        out = ox.compute_overextension_features(_ohlcv(_PARABOLIC_CLOSES, _PARABOLIC_VOLUMES))
        self.assertEqual(out["overextension_state"], "chasing_extreme")
        self.assertTrue(out["strips_theme_score"])
        self.assertEqual(out["disposition"], "scored")
        self.assertGreaterEqual(out["conditions_met"], ox.CHASING_MIN_CONDITIONS)
        self.assertEqual(out["pit"]["n_points"], len(_PARABOLIC_CLOSES))

    def test_benign_ohlcv_series_is_none(self):
        out = ox.compute_overextension_features(_ohlcv([100, 101] * 13, [1_000_000.0] * 26))
        self.assertEqual(out["overextension_state"], "none")
        self.assertFalse(out["strips_theme_score"])
        self.assertEqual(out["disposition"], "scored")

    def test_volume_absent_still_classifies_chasing(self):
        # OHLC-only (no volume) → vol_ratio None → volume_climax can't fire, but the other 4 conditions still
        # reach chasing (graceful degradation without volume).
        out = ox.compute_overextension_features(_ohlcv(_PARABOLIC_CLOSES, volumes=None))
        self.assertEqual(out["overextension_state"], "chasing_extreme")
        self.assertNotIn("volume_climax", out["condition_names"])

    # ---- PIT / look-ahead (the load-bearing safety) ----
    def test_future_parabola_does_not_leak_no_look_ahead(self):
        # ≤as_of is BENIGN; the parabolic spike lives ONLY in future (> as_of) points → must classify none.
        s = _ohlcv([100, 101] * 13, [1_000_000.0] * 26, future_closes=[110, 120, 130, 140, 150, 160])
        out = ox.compute_overextension_features(s)
        self.assertEqual(out["overextension_state"], "none")   # future spike PIT-cut → no look-ahead

    def test_future_malformed_point_does_not_reject_valid_current_series(self):
        # a FUTURE point with non-finite values must NOT over-reject the valid ≤as_of series (future values
        # are never validated — mirrors momentum).
        s = _ohlcv([100, 101] * 13, [1_000_000.0] * 26)
        s["points"].append({"date": _dt(999), "high": float("nan"), "low": float("nan"), "close": float("nan")})
        out = ox.compute_overextension_features(s)
        self.assertEqual(out["disposition"], "scored")
        self.assertIn(out["overextension_state"], ox.OVEREXTENSION_STATES)

    # ---- fail-closed / insufficient ----
    def test_short_series_insufficient_atr(self):
        out = ox.compute_overextension_features(_ohlcv([100, 101, 102, 103, 104], [1e6] * 5))  # < ATR window
        self.assertEqual(out["disposition"], "insufficient_data")
        self.assertEqual(out["overextension_state"], "none")

    def test_malformed_kept_bar_high_below_low_fails_closed(self):
        s = _ohlcv(_PARABOLIC_CLOSES, _PARABOLIC_VOLUMES)
        s["points"][10]["high"] = s["points"][10]["low"] - 1.0   # high < low = malformed bar
        self.assertEqual(ox.compute_overextension_features(s)["disposition"], "insufficient_data")

    def test_nonpositive_close_kept_bar_fails_closed(self):
        s = _ohlcv(_PARABOLIC_CLOSES, _PARABOLIC_VOLUMES)
        s["points"][5]["close"] = 0.0   # non-positive close = malformed price
        self.assertEqual(ox.compute_overextension_features(s)["disposition"], "insufficient_data")

    def test_non_ascending_axis_fails_closed(self):
        s = _ohlcv([100, 101, 102, 103, 104, 105], [1e6] * 6)
        s["points"][3]["date"] = s["points"][2]["date"]   # duplicate date → not strictly ascending
        self.assertEqual(ox.compute_overextension_features(s)["disposition"], "insufficient_data")

    def test_point_missing_required_key_fails_closed(self):
        s = _ohlcv([100, 101, 102, 103, 104, 105], [1e6] * 6)
        del s["points"][2]["low"]   # missing required 'low'
        self.assertEqual(ox.compute_overextension_features(s)["disposition"], "insufficient_data")

    def test_malformed_series_shapes_are_insufficient_not_crash(self):
        p = {"date": "2026-06-01", "high": 1.0, "low": 1.0, "close": 1.0}
        for bad in (None, "bad", 123, {}, {"as_of": "2026-06-10"},
                    {"as_of": "bad", "session": "RTH", "adjustment_mode": "x", "points": [p]},
                    {"as_of": "2026-06-10", "session": "RTH", "adjustment_mode": "x", "points": []}):
            out = ox.compute_overextension_features(bad)   # must not crash
            self.assertEqual(out["disposition"], "insufficient_data", repr(bad))
            self.assertEqual(out["overextension_state"], "none", repr(bad))


if __name__ == "__main__":
    unittest.main()
