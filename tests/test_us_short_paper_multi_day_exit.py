# -*- coding: utf-8 -*-
"""Tests for US-short §12.1 multi-day held-position exit (engine/us_short_paper_multi_day_exit.py).

Covers: a held position exiting on a later day (stop / tp, multi_day_* reason), STOP priority on a both-triggered
day, exit on the FIRST triggering day, no-hit → stays filled_held (unrealized, no time-stop), empty window → held;
the whole malformed-input class (held shape / prices / level geometry stop<fill<tp [inverted / equal refused, incl.
the stop>=fill and tp<=fill probes] / bars / OHLC sanity); and the integration through
paper_net_result (multi_day_stop / tp realize net; held → unrealized None). Pure/offline; no provider/live; no
A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_multi_day_exit as md  # noqa: E402
import engine.us_short_paper_net_result as nr  # noqa: E402

HELD = {"fill_price": 100.0, "stop_clear_price": 95.0, "take_profit_exit_price": 110.0}
COST = {"commission_fee": 0.001, "slippage_bps": 10.0, "spread_cost": 0.0005}  # total 0.0025


def _bar(o, h, low, c):
    return {"open": o, "high": h, "low": low, "close": c}


class MultiDayExit(unittest.TestCase):
    def test_stop_on_a_later_day(self):
        r = md.simulate_multi_day_exit(HELD, [_bar(101, 103, 99, 102), _bar(100, 101, 94, 96)])  # day2 low 94 <= stop 95
        self.assertEqual((r["status"], r["exit_price"], r["exit_reason"]), ("filled_stopped", 95.0, "multi_day_stop"))

    def test_tp_on_a_later_day(self):
        r = md.simulate_multi_day_exit(HELD, [_bar(101, 103, 99, 102), _bar(105, 111, 104, 110)])  # day2 high 111 >= tp 110
        self.assertEqual((r["status"], r["exit_price"], r["exit_reason"]), ("filled_tp_exit", 110.0, "multi_day_tp_exit"))

    def test_stop_priority_both_trigger(self):
        r = md.simulate_multi_day_exit(HELD, [_bar(100, 111, 94, 100)])  # high>=tp AND low<=stop → STOP priority
        self.assertEqual(r["status"], "filled_stopped")

    def test_exits_first_triggering_day(self):
        r = md.simulate_multi_day_exit(HELD, [_bar(101, 103, 99, 102), _bar(100, 101, 94, 96), _bar(100, 111, 90, 100)])
        self.assertEqual(r["exit_price"], 95.0)  # stopped on day 2, not day 3's tp

    def test_no_hit_stays_held(self):
        r = md.simulate_multi_day_exit(HELD, [_bar(101, 103, 99, 102), _bar(100, 108, 97, 105)])  # neither 95 nor 110
        self.assertEqual(r["status"], "filled_held")
        self.assertIsNone(r["exit_price"])
        self.assertIsNone(r["exit_reason"])

    def test_empty_bars_stays_held(self):
        self.assertEqual(md.simulate_multi_day_exit(HELD, [])["status"], "filled_held")


class Malformed(unittest.TestCase):
    def test_held_not_dict(self):
        with self.assertRaises(md.PaperMultiDayExitError):
            md.simulate_multi_day_exit([100.0], [_bar(100, 101, 99, 100)])

    def test_missing_price(self):
        with self.assertRaises(md.PaperMultiDayExitError):
            md.simulate_multi_day_exit({"fill_price": 100.0, "stop_clear_price": 95.0}, [_bar(100, 101, 99, 100)])

    def test_level_geometry_must_bracket_fill(self):
        # a LONG's passive levels MUST be stop < fill < tp; inverted / equal geometry is refused BEFORE any bar /
        # net booking (else a "stop" books a gain or a "take-profit" books a loss). Incl. Codex's two probes.
        for stop, tp in [(105.0, 110.0),   # stop >= fill (Codex probe 1: would book a stop@105 as +5%)
                         (90.0, 95.0),     # tp <= fill (Codex probe 2: would book a tp@95 as -5%)
                         (100.0, 110.0),   # stop == fill
                         (90.0, 100.0),    # tp == fill
                         (110.0, 110.0)]:  # stop == tp
            with self.assertRaises(md.PaperMultiDayExitError):
                md.simulate_multi_day_exit({"fill_price": 100.0, "stop_clear_price": stop, "take_profit_exit_price": tp},
                                           [_bar(100, 106, 99, 104)])

    def test_bars_not_list(self):
        with self.assertRaises(md.PaperMultiDayExitError):
            md.simulate_multi_day_exit(HELD, _bar(100, 101, 99, 100))

    def test_bad_bar_ohlc(self):
        with self.assertRaises(md.PaperMultiDayExitError):
            md.simulate_multi_day_exit(HELD, [_bar(100, 99, 101, 100)])  # high 99 < low 101


class Integration(unittest.TestCase):
    def test_stopped_feeds_net_result(self):
        net = nr.paper_net_result(md.simulate_multi_day_exit(HELD, [_bar(100, 101, 94, 96)]), cost_prior=COST)
        self.assertEqual(net["outcome"], "filled_stopped")
        self.assertAlmostEqual(net["gross_return"], (95.0 - 100.0) / 100.0)  # -0.05 realized

    def test_tp_feeds_net_result(self):
        net = nr.paper_net_result(md.simulate_multi_day_exit(HELD, [_bar(105, 111, 104, 110)]), cost_prior=COST)
        self.assertEqual(net["outcome"], "filled_tp_exit")
        self.assertAlmostEqual(net["gross_return"], 0.10)

    def test_held_feeds_net_result_unrealized(self):
        net = nr.paper_net_result(md.simulate_multi_day_exit(HELD, [_bar(100, 108, 97, 105)]), cost_prior=COST)
        self.assertEqual(net["outcome"], "open_unrealized")
        self.assertIsNone(net["net_return"])


if __name__ == "__main__":
    unittest.main()
