# -*- coding: utf-8 -*-
"""Tests for engine/us_short_provisional_theme_heat.py (§4.3 provisional_theme_lane heat + confirmation).

Pure/offline. Covers strict numeric/series validation, per-theme price/volume sub-metrics (breadth-up,
volume-confirm, leader RS), the 4 price/count confirmation pass flags, cross-theme percentile heat, the
MIN_THEME_MEMBERS coverage gate (insufficient theme → no heat/flags, the anti-self-confirm guard), and
missing-benchmark / missing-volume graceful degrade.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_provisional_theme_heat import (  # noqa: E402
    provisional_theme_heat_block,
    _finite,
    _clean_series,
    _ret,
    _vol_surge,
    _benchmark_return,
    MIN_THEME_MEMBERS,
    MEMBER_COUNT_PASS,
    RS_WINDOW,
    VOL_SURGE_LONG,
    _MIN_HISTORY,
)

N = _MIN_HISTORY


def _rising(start=100.0, step=1.0):
    return [float(start + i * step) for i in range(N)]


def _declining(start=200.0, step=-1.0):
    return [float(start + i * step) for i in range(N)]


def _surge_vol():
    return [1000.0] * 54 + [6000.0] * 10     # recent avg >> baseline → vol_surge > 1


def _flat_vol():
    return [1000.0] * 64                      # no surge → vol_surge == 1.0 (not confirmed)


def _hot_member():
    return {"closes": _rising(), "volumes": _surge_vol()}


def _cold_member():
    return {"closes": _declining(), "volumes": _flat_vol()}


def _theme(builder, k):
    return {"members": {f"m{i}": builder() for i in range(k)}}


_BENCH = _rising(100.0, 0.2)


class TestHelpers(unittest.TestCase):
    def test_finite_strict(self):
        self.assertEqual(_finite(3), 3.0)
        for bad in (True, "3", float("nan"), float("inf"), None):
            self.assertIsNone(_finite(bad))

    def test_clean_series_min_len(self):
        self.assertIsNone(_clean_series([1.0] * 10, 64))     # too short
        self.assertEqual(len(_clean_series([1.0] * 64, 64)), 64)
        s = [1.0] * 64; s[3] = True
        self.assertIsNone(_clean_series(s, 64))              # bool hole

    def test_vol_surge(self):
        self.assertGreater(_vol_surge(_surge_vol()), 1.0)
        self.assertEqual(_vol_surge(_flat_vol()), 1.0)
        self.assertIsNone(_vol_surge([0.0] * 64))           # zero baseline → None

    def test_ret_and_benchmark(self):
        self.assertAlmostEqual(_ret(_rising(100.0, 1.0), RS_WINDOW), 163.0 / 100.0 - 1.0)
        self.assertIsNone(_benchmark_return(None, None, RS_WINDOW))


class TestProvisionalThemeHeat(unittest.TestCase):
    def test_hot_theme_outranks_cold(self):
        themes = {"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_closes=_BENCH, qqq_closes=_BENCH)
        self.assertGreater(out["theme_heat"]["HOT"], out["theme_heat"]["COLD"])
        self.assertEqual(out["theme_heat"]["HOT"], 100.0)
        self.assertEqual(out["theme_heat"]["COLD"], 0.0)
        self.assertEqual(out["insufficient_themes"], [])

    def test_confirm_flags_hot_all_pass_cold_all_fail(self):
        themes = {"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_closes=_BENCH)
        self.assertEqual(out["confirm_flags"]["HOT"],
                         {"theme_breadth_up_frac": True, "theme_volume_confirm_frac": True,
                          "theme_leader_rs": True, "theme_member_count": True})
        self.assertEqual(out["confirm_flags"]["COLD"],
                         {"theme_breadth_up_frac": False, "theme_volume_confirm_frac": False,
                          "theme_leader_rs": False, "theme_member_count": False})   # 3 < MEMBER_COUNT_PASS

    def test_member_count_flag_boundary(self):
        themes = {"FIVE": _theme(_hot_member, MEMBER_COUNT_PASS),
                  "FOUR": _theme(_hot_member, MEMBER_COUNT_PASS - 1)}
        out = provisional_theme_heat_block(themes, spy_closes=_BENCH)
        self.assertTrue(out["confirm_flags"]["FIVE"]["theme_member_count"])
        self.assertFalse(out["confirm_flags"]["FOUR"]["theme_member_count"])   # scored, but count flag fails

    def test_insufficient_theme_gets_no_heat_or_flags(self):
        themes = {"BIG": _theme(_hot_member, MIN_THEME_MEMBERS),
                  "SMALL": _theme(_cold_member, MIN_THEME_MEMBERS - 1)}
        out = provisional_theme_heat_block(themes, spy_closes=_BENCH)
        self.assertIn("SMALL", out["insufficient_themes"])
        self.assertNotIn("SMALL", out["theme_heat"])
        self.assertNotIn("SMALL", out["confirm_flags"])
        self.assertIn("BIG", out["theme_heat"])

    def test_bad_member_series_dropped(self):
        themes = {"T": _theme(_hot_member, 5), "U": _theme(_cold_member, 3)}
        themes["T"]["members"]["m0"]["closes"] = [1.0, 2.0, 3.0]       # too short
        themes["T"]["members"]["m1"]["closes"][5] = float("nan")      # hole
        out = provisional_theme_heat_block(themes, spy_closes=_BENCH)
        self.assertEqual(out["theme_metrics"]["T"]["member_count"], 3)   # 5 - 2 dropped

    def test_missing_volume_degrades(self):
        # all members lack volume → coverage-aware volume_confirm_frac == 0.0 (not confirmed) → flag False; heat
        # still computed from breadth/leader (R-USSHORT-PROVISIONAL-THEME-HEAT-PARTIAL-VOLUME-COVERAGE-FAILOPEN)
        members = {f"m{i}": {"closes": _rising()} for i in range(3)}
        themes = {"NV": {"members": members}, "PEER": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_closes=_BENCH)
        self.assertEqual(out["theme_metrics"]["NV"]["volume_confirm_frac"], 0.0)
        self.assertFalse(out["confirm_flags"]["NV"]["theme_volume_confirm_frac"])
        self.assertIn("NV", out["theme_heat"])

    def test_partial_volume_coverage_not_full_confirmation(self):
        # exact Codex probe: a 5-member theme where only ONE member carries (surging) volume must NOT report 100%
        # volume confirmation — the denominator is all 5 members, so 1 surge → 0.2, flag False.
        members = {f"p{i}": {"closes": _rising()} for i in range(4)}          # closes only, no volume
        members["pV"] = {"closes": _rising(), "volumes": _surge_vol()}        # the single surging member
        out = provisional_theme_heat_block({"THIN": {"members": members}, "PEER": _theme(_cold_member, 3)},
                                           spy_closes=_BENCH)
        self.assertEqual(out["theme_metrics"]["THIN"]["member_count"], 5)
        self.assertAlmostEqual(out["theme_metrics"]["THIN"]["volume_confirm_frac"], 0.2)   # 1/5, not 1/1
        self.assertFalse(out["confirm_flags"]["THIN"]["theme_volume_confirm_frac"])

    def test_below_threshold_partial_coverage_fails(self):
        # 2 of 5 surging → 0.4 < VOL_CONFIRM_PASS_FRAC (0.5) → not confirmed
        members = {f"p{i}": {"closes": _rising()} for i in range(3)}
        members.update({f"pv{i}": {"closes": _rising(), "volumes": _surge_vol()} for i in range(2)})
        out = provisional_theme_heat_block({"P40": {"members": members}, "PEER": _theme(_cold_member, 3)},
                                           spy_closes=_BENCH)
        self.assertAlmostEqual(out["theme_metrics"]["P40"]["volume_confirm_frac"], 0.4)
        self.assertFalse(out["confirm_flags"]["P40"]["theme_volume_confirm_frac"])

    def test_broad_volume_coverage_confirms(self):
        # 3 of 5 surging → 0.6 >= 0.5 → confirmed (positive control: broad coverage genuinely confirms)
        members = {f"pn{i}": {"closes": _rising()} for i in range(2)}
        members.update({f"pv{i}": {"closes": _rising(), "volumes": _surge_vol()} for i in range(3)})
        out = provisional_theme_heat_block({"BROAD": {"members": members}, "PEER": _theme(_cold_member, 3)},
                                           spy_closes=_BENCH)
        self.assertAlmostEqual(out["theme_metrics"]["BROAD"]["volume_confirm_frac"], 0.6)
        self.assertTrue(out["confirm_flags"]["BROAD"]["theme_volume_confirm_frac"])

    def test_missing_benchmark_degrades(self):
        themes = {"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes)   # no benchmark
        self.assertIsNone(out["theme_metrics"]["HOT"]["leader_rs"])
        self.assertFalse(out["confirm_flags"]["HOT"]["theme_leader_rs"])
        self.assertGreater(out["theme_heat"]["HOT"], out["theme_heat"]["COLD"])   # breadth+volume still rank

    def test_single_theme_is_mid(self):
        out = provisional_theme_heat_block({"ONLY": _theme(_hot_member, 3)}, spy_closes=_BENCH)
        self.assertEqual(out["theme_heat"]["ONLY"], 50.0)

    def test_nonpositive_close_member_dropped(self):
        # same class as the industry-heat non-positive-close fix: a 0/negative-price member is dropped (not
        # admitted to member_count or the volume metric), and a theme emptied that way → insufficient.
        themes = {"T": _theme(_hot_member, 5), "U": _theme(_cold_member, 3)}
        themes["T"]["members"]["m0"]["closes"] = [0.0] * N      # zero price
        themes["T"]["members"]["m1"]["closes"] = [-3.0] * N     # negative price
        out = provisional_theme_heat_block(themes, spy_closes=_BENCH)
        self.assertEqual(out["theme_metrics"]["T"]["member_count"], 3)   # m0/m1 dropped
        empty = {f"z{i}": {"closes": [0.0] * N, "volumes": _surge_vol()} for i in range(3)}
        out2 = provisional_theme_heat_block({"EMPTY": {"members": empty}, "P": _theme(_cold_member, 3)},
                                            spy_closes=_BENCH)
        self.assertIn("EMPTY", out2["insufficient_themes"])
        self.assertNotIn("EMPTY", out2["theme_heat"])

    def test_nonpositive_benchmark_degrades(self):
        themes = {"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_closes=[0.0] * N)   # non-positive benchmark → invalid
        self.assertIsNone(out["theme_metrics"]["HOT"]["leader_rs"])
        self.assertFalse(out["confirm_flags"]["HOT"]["theme_leader_rs"])

    def test_zero_volume_day_is_valid(self):
        # volumes are NON-NEGATIVE (not strictly positive): a zero-volume day must not drop the member; only the
        # volume_confirm metric degrades (vol_surge over all-zero volume → None).
        members = {f"m{i}": {"closes": _rising(), "volumes": [0.0] * 64} for i in range(3)}
        out = provisional_theme_heat_block({"ZV": {"members": members}, "P": _theme(_cold_member, 3)},
                                           spy_closes=_BENCH)
        self.assertEqual(out["theme_metrics"]["ZV"]["member_count"], 3)
        self.assertEqual(out["theme_metrics"]["ZV"]["volume_confirm_frac"], 0.0)   # zero-volume → not confirmed

    def test_empty_and_non_dict(self):
        self.assertEqual(provisional_theme_heat_block({})["theme_heat"], {})
        self.assertEqual(provisional_theme_heat_block("nope")["confirm_flags"], {})

    def test_result_shape(self):
        out = provisional_theme_heat_block({"X": _theme(_hot_member, 3)}, spy_closes=_BENCH)
        self.assertEqual(set(out), {"theme_heat", "confirm_flags", "theme_metrics",
                                    "insufficient_themes", "min_theme_members"})
        self.assertEqual(out["min_theme_members"], MIN_THEME_MEMBERS)


if __name__ == "__main__":
    unittest.main()
