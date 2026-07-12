# -*- coding: utf-8 -*-
"""Tests for engine/us_short_industry_heat.py (§4.3 GICS industry heat producer).

Pure/offline. Covers strict numeric/series validation, the PIT-bearing dated-series parse (PIT cut / future
block / uniform decision clock — Cut 3a), per-sector sub-metrics (group relative strength, breadth-up,
new-high, leader RS), cross-sector percentile mapping, the MIN_SECTOR_MEMBERS coverage gate (insufficient
sector → no member heat, not a fake neutral), missing-benchmark graceful degrade, and hot-vs-cold positive
controls. The sub-metric math is unchanged by Cut 3a, so the value assertions carry over from the bare-array
version with the inputs wrapped as dated series.
"""
import math
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_industry_heat import (  # noqa: E402
    industry_heat_block,
    IndustryHeatError,
    _finite,
    _clean_series,
    _ret,
    _benchmark_return,
    _percentile_rank,
    _valid_date,
    _parse_dated_series,
    MIN_SECTOR_MEMBERS,
    RS_WINDOW,
    _MIN_HISTORY,
)

N = _MIN_HISTORY            # the minimum clean-series length (64)
_AS_OF = "2026-06-26"


def _series(start, step, n=N):
    return [float(start + i * step) for i in range(n)]


def _rising(start=100.0, step=1.0):
    return _series(start, step)


def _declining(start=200.0, step=-1.0):
    return _series(start, step)


def _dates(n, as_of=_AS_OF):
    """n ascending unique daily date strings ending at as_of (calendar-agnostic — the engine validates the
    date axis + PIT cut, not the trading calendar)."""
    end = datetime.strptime(as_of, "%Y-%m-%d").date()
    return [(end - timedelta(days=(n - 1 - i))).isoformat() for i in range(n)]


def _dseries(closes, *, as_of=_AS_OF, session="RTH", adjustment_mode="split_adjusted", dates=None):
    """Wrap a bare close list into a PIT-bearing dated series."""
    n = len(closes)
    ds = dates if dates is not None else _dates(n, as_of)
    return {"as_of": as_of, "session": session, "adjustment_mode": adjustment_mode,
            "points": [{"date": ds[i], "close": closes[i]} for i in range(n)]}


def _sector(prefix, builder, k=3):
    """k members in one sector, each its own ticker, all built (as a dated series) by `builder`."""
    return {f"{prefix}{i}": {"sector": prefix, "series": _dseries(builder())} for i in range(k)}


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
        s = _rising(); s[4] = 0.0
        self.assertIsNone(_clean_series(s))                    # non-positive
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


class TestDatedSeriesParse(unittest.TestCase):
    """Cut 3a: PIT-bearing dated-series parse + PIT cut (mirrors the momentum parser, own non-positive _clean_series)."""

    def test_valid_date(self):
        self.assertIsNotNone(_valid_date("2026-06-26"))
        for bad in ("2026-13-01", "2026-6-1", "nope", 20260626, None):
            self.assertIsNone(_valid_date(bad))

    def test_parse_valid(self):
        p = _parse_dated_series(_dseries(_rising()))
        self.assertEqual(len(p["closes"]), N)
        self.assertEqual((p["session"], p["adjustment_mode"]), ("RTH", "split_adjusted"))

    def test_parse_rejects_bad_shape(self):
        self.assertIsNone(_parse_dated_series([1, 2, 3]))
        self.assertIsNone(_parse_dated_series({"as_of": _AS_OF, "points": []}))   # missing keys + empty
        extra = _dseries(_rising()); extra["surprise"] = 1
        self.assertIsNone(_parse_dated_series(extra))                              # closed-world

    def test_parse_rejects_bad_as_of_and_blank_meta(self):
        s = _dseries(_rising()); s["as_of"] = "2026-13-40"
        self.assertIsNone(_parse_dated_series(s))
        s = _dseries(_rising()); s["session"] = ""
        self.assertIsNone(_parse_dated_series(s))

    def test_parse_rejects_nonascending_or_duplicate(self):
        s = _dseries(_rising()); s["points"][5]["date"] = s["points"][4]["date"]   # duplicate → corrupt axis
        self.assertIsNone(_parse_dated_series(s))

    def test_parse_rejects_nonpositive_and_short(self):
        self.assertIsNone(_parse_dated_series(_dseries([0.0] * N)))                 # non-positive close
        self.assertIsNone(_parse_dated_series(_dseries(_series(100.0, 1.0, n=3))))  # too short

    def test_future_point_blocked_pit_cut(self):
        closes = _rising(100.0, 1.0)
        s = _dseries(closes)
        future = (datetime.strptime(_AS_OF, "%Y-%m-%d").date() + timedelta(days=3)).isoformat()
        s["points"].append({"date": future, "close": 99999.0})   # absurd future close — must be BLOCKED
        p = _parse_dated_series(s)
        self.assertEqual(len(p["closes"]), N)                    # future point excluded
        self.assertEqual(p["closes"][-1], closes[-1])            # last close is the <=as_of one, not 99999


class TestIndustryHeatBlock(unittest.TestCase):
    def test_hot_sector_outranks_cold(self):
        members = {}
        members.update(_sector("HOT", _rising))        # rising → high returns, new highs, breadth up
        members.update(_sector("COLD", _declining))    # declining → low returns, no new highs
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)),
                                  qqq_series=_dseries(_rising(100.0, 0.2)))
        self.assertGreater(out["sector_heat"]["HOT"], out["sector_heat"]["COLD"])
        self.assertEqual(out["sector_heat"]["HOT"], 100.0)
        self.assertEqual(out["sector_heat"]["COLD"], 0.0)
        self.assertEqual(out["industry_heat_by_ticker"]["HOT0"], 100.0)
        self.assertEqual(out["industry_heat_by_ticker"]["COLD1"], 0.0)
        self.assertEqual(out["insufficient_sectors"], [])

    def test_three_way_percentile_has_mid(self):
        members = {}
        members.update(_sector("HOT", _rising))
        members.update(_sector("MID", lambda: _series(120.0, 0.0)))   # flat → mid-ish
        members.update(_sector("COLD", _declining))
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        heats = sorted(out["sector_heat"].values())
        self.assertEqual(heats, [0.0, 50.0, 100.0])
        self.assertEqual(out["sector_heat"]["HOT"], 100.0)
        self.assertEqual(out["sector_heat"]["COLD"], 0.0)

    def test_insufficient_members_gets_no_heat(self):
        members = {}
        members.update(_sector("BIG", _rising, k=MIN_SECTOR_MEMBERS))
        members.update(_sector("SMALL", _declining, k=MIN_SECTOR_MEMBERS - 1))   # below the gate
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        self.assertIn("SMALL", out["insufficient_sectors"])
        self.assertNotIn("SMALL", out["sector_heat"])
        self.assertNotIn("SMALL0", out["industry_heat_by_ticker"])   # no fake neutral
        self.assertIn("BIG0", out["industry_heat_by_ticker"])

    def test_bad_member_series_dropped(self):
        members = _sector("S", _rising, k=5)
        members["S0"]["series"] = _dseries(_series(100.0, 1.0, n=3))   # too short
        bad = _rising(); bad[5] = float("nan")
        members["S1"]["series"] = _dseries(bad)                        # hole
        members.update(_sector("T", _declining, k=3))                  # a second sector so percentile has peers
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        self.assertEqual(out["sector_metrics"]["S"]["members"], 3)     # S0/S1 dropped, S2/S3/S4 remain
        self.assertNotIn("S0", out["industry_heat_by_ticker"])
        self.assertNotIn("S1", out["industry_heat_by_ticker"])
        self.assertIn("S2", out["industry_heat_by_ticker"])

    def test_member_without_sector_dropped(self):
        members = _sector("A", _rising, k=3)
        members["NOSEC"] = {"series": _dseries(_rising())}            # no sector key
        members["BLANK"] = {"sector": "  ", "series": _dseries(_rising())}
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        self.assertNotIn("NOSEC", out["industry_heat_by_ticker"])
        self.assertNotIn("BLANK", out["industry_heat_by_ticker"])

    def test_missing_benchmark_degrades_not_crashes(self):
        members = {}
        members.update(_sector("HOT", _rising))
        members.update(_sector("COLD", _declining))
        out = industry_heat_block(members)   # no spy/qqq
        self.assertIsNone(out["sector_metrics"]["HOT"]["group_rel_strength"])
        self.assertIsNone(out["sector_metrics"]["HOT"]["leader_rs"])
        self.assertGreater(out["sector_heat"]["HOT"], out["sector_heat"]["COLD"])   # breadth+new_high still rank

    def test_single_sector_is_mid(self):
        out = industry_heat_block(_sector("ONLY", _rising), spy_series=_dseries(_rising(100.0, 0.2)))
        self.assertEqual(out["sector_heat"]["ONLY"], 50.0)   # can't rank against peers → mid

    def test_sector_metrics_breadth_and_new_high(self):
        members = {f"M{i}": {"sector": "MIX", "series": _dseries(_rising())} for i in range(3)}
        members["M3"] = {"sector": "MIX", "series": _dseries(_declining())}
        members.update(_sector("PEER", _rising, k=3))
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        m = out["sector_metrics"]["MIX"]
        self.assertEqual(m["members"], 4)
        self.assertAlmostEqual(m["breadth_up_frac"], 0.75)
        self.assertAlmostEqual(m["new_high_frac"], 0.75)
        self.assertIsNotNone(m["group_rel_strength"])

    def test_nonpositive_close_members_get_no_heat(self):
        # R-USSHORT-INDUSTRY-HEAT-NONPOSITIVE-CLOSE-FAILOPEN — all-zero / negative-price sectors must NOT
        # manufacture new_high heat; members drop (parse rejects non-positive) and the sectors fall to insufficient.
        members = {f"Z{i}": {"sector": "ZERO", "series": _dseries([0.0] * N)} for i in range(3)}
        members.update({f"NG{i}": {"sector": "NEG", "series": _dseries([-5.0] * N)} for i in range(3)})
        members.update(_sector("COLD", _declining, k=3))            # valid positive declining peer
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        for bad in ("ZERO", "NEG"):
            self.assertIn(bad, out["insufficient_sectors"])
            self.assertNotIn(bad, out["sector_heat"])
        self.assertNotIn("Z0", out["industry_heat_by_ticker"])      # no fake heat
        self.assertNotIn("NG0", out["industry_heat_by_ticker"])
        self.assertIn("COLD0", out["industry_heat_by_ticker"])      # valid peer still scored

    def test_sector_thinned_below_min_by_nonpositive(self):
        members = {f"V{i}": {"sector": "MIX", "series": _dseries(_rising())} for i in range(2)}
        members.update({f"Z{i}": {"sector": "MIX", "series": _dseries([0.0] * N)} for i in range(2)})
        members.update(_sector("PEER", _rising, k=3))
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        self.assertIn("MIX", out["insufficient_sectors"])
        self.assertNotIn("V0", out["industry_heat_by_ticker"])

    def test_nonpositive_benchmark_is_not_relative_strength_evidence(self):
        members = {}
        members.update(_sector("HOT", _rising))
        members.update(_sector("COLD", _declining))
        out = industry_heat_block(members, spy_series=_dseries([0.0] * N), qqq_series=_dseries([-1.0] * N))
        self.assertIsNone(out["sector_metrics"]["HOT"]["group_rel_strength"])   # invalid benchmark → degrade
        self.assertIsNone(out["sector_metrics"]["HOT"]["leader_rs"])
        self.assertGreater(out["sector_heat"]["HOT"], out["sector_heat"]["COLD"])  # breadth+new_high still rank

    def test_empty_and_non_dict(self):
        self.assertEqual(industry_heat_block({})["industry_heat_by_ticker"], {})
        self.assertEqual(industry_heat_block("nope")["sector_heat"], {})

    def test_result_shape(self):
        out = industry_heat_block(_sector("X", _rising), spy_series=_dseries(_rising(100.0, 0.2)))
        self.assertEqual(set(out), {"industry_heat_by_ticker", "sector_heat", "sector_metrics",
                                    "insufficient_sectors", "min_sector_members"})
        self.assertEqual(out["min_sector_members"], MIN_SECTOR_MEMBERS)


class TestPitClock(unittest.TestCase):
    """Cut 3a: PIT cut + uniform decision clock (non-uniform → IndustryHeatError, fail-closed)."""

    def test_uniform_clock_scores(self):
        members = _sector("A", _rising); members.update(_sector("B", _declining))
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        self.assertIn("A", out["sector_heat"])   # uniform clock → no raise

    def test_nonuniform_member_clock_raises(self):
        members = _sector("A", _rising)
        members["A0"]["series"] = _dseries(_rising(), as_of="2026-06-25")   # deviating as_of
        with self.assertRaises(IndustryHeatError):
            industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))

    def test_nonuniform_benchmark_session_raises(self):
        members = _sector("A", _rising)
        with self.assertRaises(IndustryHeatError):
            industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2), session="ETH"))

    def test_nonuniform_adjustment_raises(self):
        members = _sector("A", _rising)
        members.update(_sector("B", _rising))
        members["B0"]["series"] = _dseries(_rising(), adjustment_mode="raw")
        with self.assertRaises(IndustryHeatError):
            industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))

    def test_future_point_blocked_in_block(self):
        # a member carrying a future point still scores (the future point is PIT-blocked, not a crash)
        members = _sector("A", _rising); members.update(_sector("B", _declining))
        fut = (datetime.strptime(_AS_OF, "%Y-%m-%d").date() + timedelta(days=2)).isoformat()
        members["A0"]["series"]["points"].append({"date": fut, "close": 1e9})
        out = industry_heat_block(members, spy_series=_dseries(_rising(100.0, 0.2)))
        self.assertIn("A0", out["industry_heat_by_ticker"])   # still scored, future point excluded


if __name__ == "__main__":
    unittest.main()
