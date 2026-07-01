# -*- coding: utf-8 -*-
"""Tests for engine/us_short_provisional_theme_heat.py (§4.3 provisional_theme_lane heat + confirmation).

Pure/offline. Covers strict numeric/series validation, per-theme price/volume sub-metrics (breadth-up,
volume-confirm, leader RS), the 4 price/count confirmation pass flags, cross-theme percentile heat, the
MIN_THEME_MEMBERS coverage gate (insufficient theme → no heat/flags, the anti-self-confirm guard),
missing-benchmark / missing-volume graceful degrade, and the Cut 3b PIT / uniform-decision-clock contract
(dated series, future points blocked, non-uniform clock fail-closed).
"""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_provisional_theme_heat import (  # noqa: E402
    provisional_theme_heat_block,
    ProvisionalThemeHeatError,
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
AS_OF = "2026-06-30"
SESSION = "RTH"
ADJ = "split_div_adjusted"


def _rising(start=100.0, step=1.0):
    return [float(start + i * step) for i in range(N)]


def _declining(start=200.0, step=-1.0):
    return [float(start + i * step) for i in range(N)]


def _surge_vol():
    return [1000.0] * 54 + [6000.0] * 10     # recent avg >> baseline → vol_surge > 1


def _flat_vol():
    return [1000.0] * 64                      # no surge → vol_surge == 1.0 (not confirmed)


def _dates(n, end=AS_OF):
    """n consecutive calendar days ending at `end` (ascending, unique, all <= end)."""
    e = date.fromisoformat(end)
    return [(e - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def _series(closes, volumes=None, *, as_of=AS_OF, session=SESSION, adj=ADJ, end=None):
    """Build a PIT-bearing dated series {as_of, session, adjustment_mode, points:[{date, close, volume?}]}
    whose dates end at `end` (default as_of), so every point is <= as_of (all kept)."""
    ds = _dates(len(closes), end or as_of)
    pts = []
    for i, c in enumerate(closes):
        p = {"date": ds[i], "close": c}
        if volumes is not None:
            p["volume"] = volumes[i]
        pts.append(p)
    return {"as_of": as_of, "session": session, "adjustment_mode": adj, "points": pts}


def _hot_member(**kw):
    return _series(_rising(), _surge_vol(), **kw)


def _cold_member(**kw):
    return _series(_declining(), _flat_vol(), **kw)


def _theme(builder, k):
    return {"members": {f"m{i}": builder() for i in range(k)}}


_BENCH = _series(_rising(100.0, 0.2))            # dated benchmark series (closes only)


class TestHelpers(unittest.TestCase):
    def test_finite_strict(self):
        self.assertEqual(_finite(3), 3.0)
        for bad in (True, "3", float("nan"), float("inf"), None):
            self.assertIsNone(_finite(bad))

    def test_clean_series_positive_and_min_len(self):
        self.assertIsNone(_clean_series([1.0] * 10))         # too short (< _MIN_HISTORY)
        self.assertEqual(len(_clean_series([1.0] * N)), N)
        s = [1.0] * N; s[3] = True
        self.assertIsNone(_clean_series(s))                  # bool hole
        z = [1.0] * N; z[7] = 0.0
        self.assertIsNone(_clean_series(z))                  # non-positive close
        neg = [1.0] * N; neg[7] = -2.0
        self.assertIsNone(_clean_series(neg))

    def test_vol_surge_tail_only(self):
        self.assertGreater(_vol_surge(_surge_vol()), 1.0)
        self.assertEqual(_vol_surge(_flat_vol()), 1.0)
        self.assertIsNone(_vol_surge([0.0] * N))             # zero baseline → None
        self.assertIsNone(_vol_surge([1000.0] * 10))         # shorter than VOL_SURGE_LONG → None
        # a None INSIDE the averaged tail → None; a None OUTSIDE the last-VOL_SURGE_LONG tail → still computes
        self.assertIsNone(_vol_surge([1000.0] * (N - 1) + [None]))
        self.assertIsNotNone(_vol_surge([None] + [1000.0] * (N - 1)))

    def test_ret_and_benchmark(self):
        self.assertAlmostEqual(_ret(_rising(100.0, 1.0), RS_WINDOW), 163.0 / 100.0 - 1.0)
        self.assertIsNone(_benchmark_return(None, None, RS_WINDOW))


class TestProvisionalThemeHeat(unittest.TestCase):
    def test_hot_theme_outranks_cold(self):
        themes = {"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_series=_BENCH, qqq_series=_BENCH)
        self.assertGreater(out["theme_heat"]["HOT"], out["theme_heat"]["COLD"])
        self.assertEqual(out["theme_heat"]["HOT"], 100.0)
        self.assertEqual(out["theme_heat"]["COLD"], 0.0)
        self.assertEqual(out["insufficient_themes"], [])

    def test_confirm_flags_hot_all_pass_cold_all_fail(self):
        themes = {"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_series=_BENCH)
        self.assertEqual(out["confirm_flags"]["HOT"],
                         {"theme_breadth_up_frac": True, "theme_volume_confirm_frac": True,
                          "theme_leader_rs": True, "theme_member_count": True})
        self.assertEqual(out["confirm_flags"]["COLD"],
                         {"theme_breadth_up_frac": False, "theme_volume_confirm_frac": False,
                          "theme_leader_rs": False, "theme_member_count": False})   # 3 < MEMBER_COUNT_PASS

    def test_member_count_flag_boundary(self):
        themes = {"FIVE": _theme(_hot_member, MEMBER_COUNT_PASS),
                  "FOUR": _theme(_hot_member, MEMBER_COUNT_PASS - 1)}
        out = provisional_theme_heat_block(themes, spy_series=_BENCH)
        self.assertTrue(out["confirm_flags"]["FIVE"]["theme_member_count"])
        self.assertFalse(out["confirm_flags"]["FOUR"]["theme_member_count"])   # scored, but count flag fails

    def test_insufficient_theme_gets_no_heat_or_flags(self):
        themes = {"BIG": _theme(_hot_member, MIN_THEME_MEMBERS),
                  "SMALL": _theme(_cold_member, MIN_THEME_MEMBERS - 1)}
        out = provisional_theme_heat_block(themes, spy_series=_BENCH)
        self.assertIn("SMALL", out["insufficient_themes"])
        self.assertNotIn("SMALL", out["theme_heat"])
        self.assertNotIn("SMALL", out["confirm_flags"])
        self.assertIn("BIG", out["theme_heat"])

    def test_bad_member_series_dropped(self):
        themes = {"T": {"members": {"m0": _series(_rising()[:3], _surge_vol()[:3]),   # too short → dropped
                                    "m1": _hot_member(), "m2": _hot_member(),
                                    "m3": _hot_member(), "m4": _hot_member()}},
                  "U": _theme(_cold_member, 3)}
        themes["T"]["members"]["m1"]["points"][5]["close"] = float("nan")            # hole → dropped
        out = provisional_theme_heat_block(themes, spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["T"]["member_count"], 3)               # 5 - 2 dropped

    def test_missing_volume_degrades(self):
        # all members lack volume → coverage-aware volume_confirm_frac == 0.0 (not confirmed) → flag False; heat
        # still computed from breadth/leader (R-USSHORT-PROVISIONAL-THEME-HEAT-PARTIAL-VOLUME-COVERAGE-FAILOPEN)
        members = {f"m{i}": _series(_rising()) for i in range(3)}
        themes = {"NV": {"members": members}, "PEER": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["NV"]["volume_confirm_frac"], 0.0)
        self.assertFalse(out["confirm_flags"]["NV"]["theme_volume_confirm_frac"])
        self.assertIn("NV", out["theme_heat"])

    def test_partial_volume_coverage_not_full_confirmation(self):
        # a 5-member theme where only ONE member carries (surging) volume must NOT report 100% volume
        # confirmation — the denominator is all 5 members, so 1 surge → 0.2, flag False.
        members = {f"p{i}": _series(_rising()) for i in range(4)}                 # closes only, no volume
        members["pV"] = _series(_rising(), _surge_vol())                          # the single surging member
        out = provisional_theme_heat_block({"THIN": {"members": members}, "PEER": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["THIN"]["member_count"], 5)
        self.assertAlmostEqual(out["theme_metrics"]["THIN"]["volume_confirm_frac"], 0.2)   # 1/5, not 1/1
        self.assertFalse(out["confirm_flags"]["THIN"]["theme_volume_confirm_frac"])

    def test_below_threshold_partial_coverage_fails(self):
        # 2 of 5 surging → 0.4 < VOL_CONFIRM_PASS_FRAC (0.5) → not confirmed
        members = {f"p{i}": _series(_rising()) for i in range(3)}
        members.update({f"pv{i}": _series(_rising(), _surge_vol()) for i in range(2)})
        out = provisional_theme_heat_block({"P40": {"members": members}, "PEER": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertAlmostEqual(out["theme_metrics"]["P40"]["volume_confirm_frac"], 0.4)
        self.assertFalse(out["confirm_flags"]["P40"]["theme_volume_confirm_frac"])

    def test_broad_volume_coverage_confirms(self):
        # 3 of 5 surging → 0.6 >= 0.5 → confirmed (positive control: broad coverage genuinely confirms)
        members = {f"pn{i}": _series(_rising()) for i in range(2)}
        members.update({f"pv{i}": _series(_rising(), _surge_vol()) for i in range(3)})
        out = provisional_theme_heat_block({"BROAD": {"members": members}, "PEER": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertAlmostEqual(out["theme_metrics"]["BROAD"]["volume_confirm_frac"], 0.6)
        self.assertTrue(out["confirm_flags"]["BROAD"]["theme_volume_confirm_frac"])

    def test_early_missing_volume_still_surges(self):
        # Cut 3b tail-only vol_surge (mirrors momentum): a member missing only an EARLY volume (outside the last
        # VOL_SURGE_LONG tail it averages) still gets vol_surge — the flat whole-array requirement would have
        # over-omitted it. Build 5 such members → volume_confirm_frac 1.0.
        members = {}
        for i in range(5):
            m = _series(_rising(), _surge_vol())
            del m["points"][0]["volume"]         # drop the earliest volume (index 0, outside the last-63 tail)
            members[f"e{i}"] = m
        out = provisional_theme_heat_block({"EARLY": {"members": members}, "PEER": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["EARLY"]["member_count"], 5)
        self.assertAlmostEqual(out["theme_metrics"]["EARLY"]["volume_confirm_frac"], 1.0)

    def test_missing_benchmark_degrades(self):
        themes = {"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes)   # no benchmark
        self.assertIsNone(out["theme_metrics"]["HOT"]["leader_rs"])
        self.assertFalse(out["confirm_flags"]["HOT"]["theme_leader_rs"])
        self.assertGreater(out["theme_heat"]["HOT"], out["theme_heat"]["COLD"])   # breadth+volume still rank

    def test_single_theme_is_mid(self):
        out = provisional_theme_heat_block({"ONLY": _theme(_hot_member, 3)}, spy_series=_BENCH)
        self.assertEqual(out["theme_heat"]["ONLY"], 50.0)

    def test_nonpositive_close_member_dropped(self):
        # same class as the industry-heat non-positive-close fix: a 0/negative-price member is dropped (not
        # admitted to member_count or the volume metric), and a theme emptied that way → insufficient.
        themes = {"T": {"members": {"m0": _series([0.0] * N, _surge_vol()),        # zero price
                                    "m1": _series([-3.0] * N, _surge_vol()),       # negative price
                                    "m2": _hot_member(), "m3": _hot_member(), "m4": _hot_member()}},
                  "U": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["T"]["member_count"], 3)   # m0/m1 dropped
        empty = {f"z{i}": _series([0.0] * N, _surge_vol()) for i in range(3)}
        out2 = provisional_theme_heat_block({"EMPTY": {"members": empty}, "P": _theme(_cold_member, 3)},
                                            spy_series=_BENCH)
        self.assertIn("EMPTY", out2["insufficient_themes"])
        self.assertNotIn("EMPTY", out2["theme_heat"])

    def test_nonpositive_benchmark_degrades(self):
        themes = {"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)}
        out = provisional_theme_heat_block(themes, spy_series=_series([0.0] * N))   # non-positive benchmark
        self.assertIsNone(out["theme_metrics"]["HOT"]["leader_rs"])
        self.assertFalse(out["confirm_flags"]["HOT"]["theme_leader_rs"])

    def test_zero_volume_day_is_valid(self):
        # volumes are NON-NEGATIVE (not strictly positive): a zero-volume day must not drop the member; only the
        # volume_confirm metric degrades (vol_surge over all-zero volume → None).
        members = {f"m{i}": _series(_rising(), [0.0] * N) for i in range(3)}
        out = provisional_theme_heat_block({"ZV": {"members": members}, "P": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["ZV"]["member_count"], 3)
        self.assertEqual(out["theme_metrics"]["ZV"]["volume_confirm_frac"], 0.0)   # zero-volume → not confirmed

    def test_negative_volume_maps_to_unconfirmed(self):
        # a NEGATIVE volume in the tail is malformed → mapped to None → vol_surge unavailable → not confirmed
        # (member still kept via closes).
        vols = _surge_vol(); vols[-1] = -5.0
        members = {f"m{i}": _series(_rising(), list(vols)) for i in range(3)}
        out = provisional_theme_heat_block({"NEG": {"members": members}, "P": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["NEG"]["member_count"], 3)
        self.assertEqual(out["theme_metrics"]["NEG"]["volume_confirm_frac"], 0.0)

    # --- Cut 3b PIT + uniform-decision-clock contract (mirrors industry_heat Cut 3a / momentum Cut 2) ---
    def test_future_point_pit_cut(self):
        # a point dated AFTER as_of is BLOCKED (excluded) and its VALUE is not validated — a future non-finite
        # close must not reject an otherwise-valid <=as_of series.
        m = _hot_member()
        m["points"].append({"date": "2026-07-15", "close": float("nan"), "volume": 5.0})   # future junk
        themes = {"T": {"members": {"m0": m, "m1": _hot_member(), "m2": _hot_member()}}}
        out = provisional_theme_heat_block(themes, spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["T"]["member_count"], 3)   # m0 still valid (future point cut)

    def test_corrupt_axis_dropped(self):
        # a non-strictly-ascending / duplicated date axis is corrupt → member dropped (never silently reordered)
        dup = _hot_member()
        dup["points"][10]["date"] = dup["points"][9]["date"]            # duplicate date
        themes = {"T": {"members": {"m0": dup, "m1": _hot_member(), "m2": _hot_member(), "m3": _hot_member()}}}
        out = provisional_theme_heat_block(themes, spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["T"]["member_count"], 3)   # corrupt m0 dropped

    def test_nonuniform_as_of_clock_raises(self):
        m2 = _hot_member(as_of="2026-06-29", end="2026-06-29")          # different as_of
        themes = {"T": {"members": {"a": _hot_member(), "b": m2, "c": _hot_member()}}}
        with self.assertRaises(ProvisionalThemeHeatError):
            provisional_theme_heat_block(themes, spy_series=_BENCH)

    def test_nonuniform_session_or_adjustment_clock_raises(self):
        for kw in ({"session": "PRE"}, {"adj": "raw_unadjusted"}):
            m2 = _hot_member(**kw)
            themes = {"T": {"members": {"a": _hot_member(), "b": m2, "c": _hot_member()}}}
            with self.assertRaises(ProvisionalThemeHeatError):
                provisional_theme_heat_block(themes, spy_series=_BENCH)

    def test_benchmark_clock_mismatch_raises(self):
        # the benchmark participates in the uniform-clock gate too
        themes = {"T": _theme(_hot_member, 3)}
        with self.assertRaises(ProvisionalThemeHeatError):
            provisional_theme_heat_block(themes, spy_series=_series(_rising(100.0, 0.2), as_of="2026-06-29",
                                                                    end="2026-06-29"))

    def test_uniform_clock_ok(self):
        # positive control: all members + both benchmarks share one clock → scores, no raise
        out = provisional_theme_heat_block({"HOT": _theme(_hot_member, 5), "COLD": _theme(_cold_member, 3)},
                                           spy_series=_BENCH, qqq_series=_BENCH)
        self.assertEqual(out["theme_heat"]["HOT"], 100.0)

    def test_empty_and_non_dict(self):
        self.assertEqual(provisional_theme_heat_block({})["theme_heat"], {})
        self.assertEqual(provisional_theme_heat_block("nope")["confirm_flags"], {})

    def test_result_shape(self):
        out = provisional_theme_heat_block({"X": _theme(_hot_member, 3)}, spy_series=_BENCH)
        self.assertEqual(set(out), {"theme_heat", "confirm_flags", "theme_metrics",
                                    "insufficient_themes", "min_theme_members"})
        self.assertEqual(out["min_theme_members"], MIN_THEME_MEMBERS)


class TestIdentityAndClockValidation(unittest.TestCase):
    """Cut 3b identity + clock hardening (R-USSHORT-PROVISIONAL-THEME-IDENTITY-AND-CLOCK-VALIDATION-GAP): member
    IDs canonicalized (invalid/A-share excluded, alias collisions fail-closed) before counting; theme IDs nonblank
    strings (collision fail-closed, no mixed-type sort crash); clock metadata nonblank without whitespace drift."""

    def test_case_whitespace_ticker_aliases_raise(self):
        # one security as AAPL/aapl/ AAPL /AaPl/AAPL  → all canonicalize to AAPL → alias collision → fail-closed
        # (Codex probe A1: this used to report member_count=5 + 4 True flags).
        alias = {"AL": {"members": {k: _hot_member() for k in ("AAPL", "aapl", " AAPL ", "AaPl", "AAPL ")}}}
        with self.assertRaises(ProvisionalThemeHeatError):
            provisional_theme_heat_block(alias, spy_series=_BENCH)

    def test_ashare_and_invalid_member_keys_excluded(self):
        # Codex probe A2: A-share codes + integer + None keys must NOT be counted. A theme of only-rejected keys
        # → insufficient; a MIXED theme counts ONLY its canonical US members.
        bad = {"000001.SZ": _hot_member(), "600000.SH": _hot_member(), "430047.BJ": _hot_member(),
               123: _hot_member(), None: _hot_member()}
        out = provisional_theme_heat_block({"BAD": {"members": bad}, "P": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertIn("BAD", out["insufficient_themes"])
        self.assertNotIn("BAD", out["theme_heat"])
        mixed = {"AAPL": _hot_member(), "MSFT": _hot_member(), "JPM": _hot_member(),
                 "000001.SZ": _hot_member(), "600000.SH": _hot_member()}      # 3 US + 2 A-share
        out2 = provisional_theme_heat_block({"MIX": {"members": mixed}, "P": _theme(_cold_member, 3)},
                                            spy_series=_BENCH)
        self.assertEqual(out2["theme_metrics"]["MIX"]["member_count"], 3)     # A-share excluded, not counted

    def test_unicode_folded_member_keys_excluded(self):
        # independent-adversarial probe: 'ſ'/'ß'/'ı' fold via .upper() to ASCII S/SS/I and used to count as
        # fabricated members; the single identity policy now rejects non-ASCII, so they are excluded (not counted).
        mixed = {"AAPL": _hot_member(), "MSFT": _hot_member(), "JPM": _hot_member(),
                 "ſ": _hot_member(), "ß": _hot_member(), "ı": _hot_member()}   # 3 US + 3 unicode phantoms
        out = provisional_theme_heat_block({"UF": {"members": mixed}, "P": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["UF"]["member_count"], 3)       # phantoms excluded

    def test_valid_class_share_symbol_counted(self):
        # positive control: a valid class-share symbol (BRK.B) is a real US identity and IS counted
        ok = {"BRK.B": _hot_member(), "AAPL": _hot_member(), "MSFT": _hot_member()}
        out = provisional_theme_heat_block({"OK": {"members": ok}, "P": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertEqual(out["theme_metrics"]["OK"]["member_count"], 3)

    def test_nonstring_theme_id_raises(self):
        with self.assertRaises(ProvisionalThemeHeatError):
            provisional_theme_heat_block({1: _theme(_hot_member, 3), "x": _theme(_cold_member, 3)},
                                         spy_series=_BENCH)

    def test_blank_theme_id_raises(self):
        for blank in ("", "   "):
            with self.assertRaises(ProvisionalThemeHeatError):
                provisional_theme_heat_block({blank: _theme(_hot_member, 3)}, spy_series=_BENCH)

    def test_theme_id_normalization_collision_raises(self):
        with self.assertRaises(ProvisionalThemeHeatError):
            provisional_theme_heat_block({"x": _theme(_hot_member, 3), " x ": _theme(_cold_member, 3)},
                                         spy_series=_BENCH)

    def test_whitespace_only_clock_excluded(self):
        members = {t: _hot_member(session="   ") for t in ("AAPL", "MSFT", "JPM")}   # blank session
        out = provisional_theme_heat_block({"WS": {"members": members}, "P": _theme(_cold_member, 3)},
                                           spy_series=_BENCH)
        self.assertIn("WS", out["insufficient_themes"])          # blank-clock series dropped → not scored
        self.assertNotIn("WS", out["theme_heat"])

    def test_clock_whitespace_drift_excluded(self):
        for kw in ({"session": " RTH "}, {"adj": " split_div_adjusted "}):    # leading/trailing drift
            members = {t: _hot_member(**kw) for t in ("AAPL", "MSFT", "JPM")}
            out = provisional_theme_heat_block({"DR": {"members": members}, "P": _theme(_cold_member, 3)},
                                               spy_series=_BENCH)
            self.assertIn("DR", out["insufficient_themes"], kw)

    def test_aliases_cannot_supply_confirmation_items(self):
        # adjacent-gate assertion: the alias attack (one security → 5 members → 4 True flags → gate pass) is
        # closed — the producer raises, so no price-derived flags exist, and market_confirmation_passed cannot
        # reach its 3-of-7 minimum from an empty flag set.
        from engine.us_short_theme_heat import market_confirmation_passed
        alias = {"AL": {"members": {k: _hot_member() for k in ("AAPL", "aapl", " AAPL ", "AaPl", "AAPL ")}}}
        with self.assertRaises(ProvisionalThemeHeatError):
            provisional_theme_heat_block(alias, spy_series=_BENCH)
        self.assertFalse(market_confirmation_passed({}, stock_is_strong=True))


if __name__ == "__main__":
    unittest.main()
