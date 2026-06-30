# -*- coding: utf-8 -*-
"""Tests for engine/us_short_industry_heat.py (§4.3 GICS industry heat producer).

Pure/offline. Covers strict numeric/series validation, per-sector sub-metrics (group relative strength,
breadth-up, new-high, leader RS), cross-sector percentile mapping, the MIN_SECTOR_MEMBERS coverage gate
(insufficient sector → no member heat, not a fake neutral), missing-benchmark graceful degrade, and
hot-vs-cold sector positive controls.
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_industry_heat import (  # noqa: E402
    industry_heat_block,
    _finite,
    _clean_series,
    _ret,
    _benchmark_return,
    _percentile_rank,
    MIN_SECTOR_MEMBERS,
    RS_WINDOW,
    _MIN_HISTORY,
)

N = _MIN_HISTORY            # the minimum clean-series length (64)


def _series(start, step, n=N):
    return [float(start + i * step) for i in range(n)]


def _rising(start=100.0, step=1.0):
    return _series(start, step)


def _declining(start=200.0, step=-1.0):
    return _series(start, step)


def _sector(prefix, builder, k=3):
    """k members in one sector, each its own ticker, all built by `builder`."""
    return {f"{prefix}{i}": {"sector": prefix, "closes": builder()} for i in range(k)}


class TestHelpers(unittest.TestCase):
    def test_finite_strict(self):
        self.assertEqual(_finite(3), 3.0)
        for bad in (True, "3", float("nan"), float("inf"), None):
            self.assertIsNone(_finite(bad))

    def test_clean_series_rejects(self):
        self.assertIsNone(_clean_series([1.0, 2.0]))           # too short
        self.assertIsNone(_clean_series("nope"))
        s = _rising(); s[3] = float("nan")
        self.assertIsNone(_clean_series(s))                    # hole
        s = _rising(); s[2] = True
        self.assertIsNone(_clean_series(s))                    # bool
        self.assertEqual(len(_clean_series(_rising())), N)

    def test_ret(self):
        self.assertAlmostEqual(_ret(_rising(100.0, 1.0), RS_WINDOW), 163.0 / 100.0 - 1.0)
        self.assertIsNone(_ret([1.0, 2.0], RS_WINDOW))

    def test_benchmark_return_mean_of_available(self):
        spy = _rising(100.0, 1.0)   # 3m ret 0.63
        qqq = _rising(100.0, 0.5)   # 3m ret 0.315
        self.assertAlmostEqual(_benchmark_return(spy, qqq, RS_WINDOW), (0.63 + 0.315) / 2.0, places=6)
        self.assertAlmostEqual(_benchmark_return(spy, None, RS_WINDOW), 0.63, places=6)
        self.assertIsNone(_benchmark_return(None, None, RS_WINDOW))   # neither → None (degrade, not crash)

    def test_percentile_rank(self):
        self.assertEqual(_percentile_rank({}), {})
        self.assertEqual(_percentile_rank({"A": 5.0}), {"A": 50.0})   # single → mid
        out = _percentile_rank({"A": 1.0, "B": 2.0, "C": 3.0})
        self.assertEqual((out["A"], out["B"], out["C"]), (0.0, 50.0, 100.0))
        tie = _percentile_rank({"A": 1.0, "B": 1.0, "C": 9.0})
        self.assertEqual(tie["A"], tie["B"])


class TestIndustryHeatBlock(unittest.TestCase):
    def test_hot_sector_outranks_cold(self):
        members = {}
        members.update(_sector("HOT", _rising))        # rising → high returns, new highs, breadth up
        members.update(_sector("COLD", _declining))    # declining → low returns, no new highs
        out = industry_heat_block(members, spy_closes=_rising(100.0, 0.2), qqq_closes=_rising(100.0, 0.2))
        self.assertGreater(out["sector_heat"]["HOT"], out["sector_heat"]["COLD"])
        self.assertEqual(out["sector_heat"]["HOT"], 100.0)
        self.assertEqual(out["sector_heat"]["COLD"], 0.0)
        # every member inherits its sector's heat
        self.assertEqual(out["industry_heat_by_ticker"]["HOT0"], 100.0)
        self.assertEqual(out["industry_heat_by_ticker"]["COLD1"], 0.0)
        self.assertEqual(out["insufficient_sectors"], [])

    def test_three_way_percentile_has_mid(self):
        members = {}
        members.update(_sector("HOT", _rising))
        members.update(_sector("MID", lambda: _series(120.0, 0.0)))   # flat → mid-ish
        members.update(_sector("COLD", _declining))
        out = industry_heat_block(members, spy_closes=_rising(100.0, 0.2))
        heats = sorted(out["sector_heat"].values())
        self.assertEqual(heats, [0.0, 50.0, 100.0])
        self.assertEqual(out["sector_heat"]["HOT"], 100.0)
        self.assertEqual(out["sector_heat"]["COLD"], 0.0)

    def test_insufficient_members_gets_no_heat(self):
        members = {}
        members.update(_sector("BIG", _rising, k=MIN_SECTOR_MEMBERS))
        members.update(_sector("SMALL", _declining, k=MIN_SECTOR_MEMBERS - 1))   # below the gate
        out = industry_heat_block(members, spy_closes=_rising(100.0, 0.2))
        self.assertIn("SMALL", out["insufficient_sectors"])
        self.assertNotIn("SMALL", out["sector_heat"])
        self.assertNotIn("SMALL0", out["industry_heat_by_ticker"])   # no fake neutral
        self.assertIn("BIG0", out["industry_heat_by_ticker"])

    def test_bad_member_series_dropped(self):
        # members with a malformed close series drop out; the rest of the sector still scores (>= the gate)
        members = _sector("S", _rising, k=5)
        members["S0"]["closes"] = [1.0, 2.0, 3.0]          # too short
        members["S1"]["closes"][5] = float("nan")          # hole
        members.update(_sector("T", _declining, k=3))      # a second sector so percentile has peers
        out = industry_heat_block(members, spy_closes=_rising(100.0, 0.2))
        self.assertEqual(out["sector_metrics"]["S"]["members"], 3)   # S0/S1 dropped, S2/S3/S4 remain
        self.assertNotIn("S0", out["industry_heat_by_ticker"])
        self.assertNotIn("S1", out["industry_heat_by_ticker"])
        self.assertIn("S2", out["industry_heat_by_ticker"])

    def test_member_without_sector_dropped(self):
        members = _sector("A", _rising, k=3)
        members["NOSEC"] = {"closes": _rising()}            # no sector key
        members["BLANK"] = {"sector": "  ", "closes": _rising()}
        out = industry_heat_block(members, spy_closes=_rising(100.0, 0.2))
        self.assertNotIn("NOSEC", out["industry_heat_by_ticker"])
        self.assertNotIn("BLANK", out["industry_heat_by_ticker"])

    def test_missing_benchmark_degrades_not_crashes(self):
        # no benchmark → group_rel_strength / leader_rs are None (neutral-filled); breadth/new_high still drive heat
        members = {}
        members.update(_sector("HOT", _rising))
        members.update(_sector("COLD", _declining))
        out = industry_heat_block(members)   # no spy/qqq
        self.assertIsNone(out["sector_metrics"]["HOT"]["group_rel_strength"])
        self.assertIsNone(out["sector_metrics"]["HOT"]["leader_rs"])
        self.assertGreater(out["sector_heat"]["HOT"], out["sector_heat"]["COLD"])   # breadth+new_high still rank

    def test_single_sector_is_mid(self):
        out = industry_heat_block(_sector("ONLY", _rising), spy_closes=_rising(100.0, 0.2))
        self.assertEqual(out["sector_heat"]["ONLY"], 50.0)   # can't rank against peers → mid

    def test_sector_metrics_breadth_and_new_high(self):
        # 3 rising + 1 declining in one sector (+ a peer sector) → breadth 3/4, new_high 3/4
        members = {f"M{i}": {"sector": "MIX", "closes": _rising()} for i in range(3)}
        members["M3"] = {"sector": "MIX", "closes": _declining()}
        members.update(_sector("PEER", _rising, k=3))
        out = industry_heat_block(members, spy_closes=_rising(100.0, 0.2))
        m = out["sector_metrics"]["MIX"]
        self.assertEqual(m["members"], 4)
        self.assertAlmostEqual(m["breadth_up_frac"], 0.75)
        self.assertAlmostEqual(m["new_high_frac"], 0.75)
        self.assertIsNotNone(m["group_rel_strength"])

    def test_nonpositive_close_members_get_no_heat(self):
        # R-USSHORT-INDUSTRY-HEAT-NONPOSITIVE-CLOSE-FAILOPEN — the exact Codex probe: all-zero / negative-price
        # sectors must NOT manufacture new_high heat; their members drop and the sectors fall to insufficient.
        members = {f"Z{i}": {"sector": "ZERO", "closes": [0.0] * N} for i in range(3)}
        members.update({f"NG{i}": {"sector": "NEG", "closes": [-5.0] * N} for i in range(3)})
        members.update(_sector("COLD", _declining, k=3))            # valid positive declining peer
        out = industry_heat_block(members, spy_closes=_rising(100.0, 0.2))
        for bad in ("ZERO", "NEG"):
            self.assertIn(bad, out["insufficient_sectors"])
            self.assertNotIn(bad, out["sector_heat"])
        self.assertNotIn("Z0", out["industry_heat_by_ticker"])      # no fake heat
        self.assertNotIn("NG0", out["industry_heat_by_ticker"])
        self.assertIn("COLD0", out["industry_heat_by_ticker"])      # valid peer still scored

    def test_sector_thinned_below_min_by_nonpositive(self):
        # 2 valid + 2 zero-price in one sector → drops to 2 < MIN_SECTOR_MEMBERS → insufficient, valid members no heat
        members = {f"V{i}": {"sector": "MIX", "closes": _rising()} for i in range(2)}
        members.update({f"Z{i}": {"sector": "MIX", "closes": [0.0] * N} for i in range(2)})
        members.update(_sector("PEER", _rising, k=3))
        out = industry_heat_block(members, spy_closes=_rising(100.0, 0.2))
        self.assertIn("MIX", out["insufficient_sectors"])
        self.assertNotIn("V0", out["industry_heat_by_ticker"])

    def test_nonpositive_benchmark_is_not_relative_strength_evidence(self):
        members = {}
        members.update(_sector("HOT", _rising))
        members.update(_sector("COLD", _declining))
        out = industry_heat_block(members, spy_closes=[0.0] * N, qqq_closes=[-1.0] * N)
        self.assertIsNone(out["sector_metrics"]["HOT"]["group_rel_strength"])   # invalid benchmark → degrade
        self.assertIsNone(out["sector_metrics"]["HOT"]["leader_rs"])
        self.assertGreater(out["sector_heat"]["HOT"], out["sector_heat"]["COLD"])  # breadth+new_high still rank

    def test_empty_and_non_dict(self):
        self.assertEqual(industry_heat_block({})["industry_heat_by_ticker"], {})
        self.assertEqual(industry_heat_block("nope")["sector_heat"], {})

    def test_result_shape(self):
        out = industry_heat_block(_sector("X", _rising), spy_closes=_rising(100.0, 0.2))
        self.assertEqual(set(out), {"industry_heat_by_ticker", "sector_heat", "sector_metrics",
                                    "insufficient_sectors", "min_sector_members"})
        self.assertEqual(out["min_sector_members"], MIN_SECTOR_MEMBERS)


if __name__ == "__main__":
    unittest.main()
